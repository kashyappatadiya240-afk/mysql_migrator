# Copyright (c) 2026, Kashyap and contributors
# For license information, please see license.txt

import os
import re
import time
import datetime
import frappe
from frappe import _
from frappe.utils import now_datetime, cint, flt

def resolve_file_path(file_path):
	"""
	Resolves relative paths, site paths, or uploaded file URLs to an absolute file path.
	"""
	if not file_path:
		return None
	file_path = str(file_path).strip()
	if os.path.isabs(file_path) and os.path.exists(file_path):
		return file_path

	bench_path = frappe.utils.get_bench_path() if hasattr(frappe.utils, "get_bench_path") else "/home/kashyap/Desktop/ERPNext/tally/tally"
	site_name = getattr(frappe.local, "site", "tally.site") or "tally.site"

	clean = file_path.lstrip("./")
	candidates = [
		os.path.join(bench_path, clean),
		os.path.join(bench_path, "sites", clean),
		os.path.join(bench_path, "sites", site_name, clean),
		os.path.join(bench_path, "sites", site_name, clean.lstrip(site_name).lstrip("/")),
		os.path.join(bench_path, "sites", site_name, file_path.lstrip("/")),
		os.path.abspath(file_path),
	]
	for c in candidates:
		if os.path.exists(c):
			return os.path.abspath(c)
	return file_path


def extract_create_tables_balanced(content):
	"""
	Extracts CREATE TABLE statements by tracking balanced parentheses
	so that table options like ENGINE=InnoDB DEFAULT CHARSET=... are never
	treated as columns.
	"""
	tables = {}
	pattern = re.compile(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`a-zA-Z0-9_]+)\s*\(', re.IGNORECASE)
	pos = 0
	while True:
		match = pattern.search(content, pos)
		if not match:
			break
		tbl_name = match.group(1).replace('`', '').lower()
		start_paren = match.end() - 1
		depth = 0
		in_str = False
		quote_char = None
		escape = False
		body_end = -1
		i = start_paren
		n = len(content)
		while i < n:
			ch = content[i]
			if escape:
				escape = False
				i += 1
				continue
			if ch == '\\':
				escape = True
				i += 1
				continue
			if in_str:
				if ch == quote_char:
					in_str = False
				i += 1
				continue
			if ch in ("'", '"', '`'):
				in_str = True
				quote_char = ch
				i += 1
				continue
			if ch == '(':
				depth += 1
			elif ch == ')':
				depth -= 1
				if depth == 0:
					body_end = i
					break
			i += 1

		if body_end != -1:
			body = content[start_paren + 1:body_end]
			tables[tbl_name] = body
			pos = body_end + 1
		else:
			pos = match.end()
	return tables


def parse_ddl_columns(body):
	"""
	Parses column definitions inside the CREATE TABLE parenthesis body,
	ignoring indexes, constraints, and engine/charset options.
	"""
	items = []
	current = []
	depth = 0
	in_str = False
	quote_char = None
	escape = False

	for ch in body:
		if escape:
			escape = False
			current.append(ch)
			continue
		if ch == '\\':
			escape = True
			current.append(ch)
			continue
		if in_str:
			if ch == quote_char:
				in_str = False
			current.append(ch)
			continue
		if ch in ("'", '"', '`'):
			in_str = True
			quote_char = ch
			current.append(ch)
			continue
		if ch == '(':
			depth += 1
			current.append(ch)
			continue
		if ch == ')':
			depth -= 1
			current.append(ch)
			continue
		if ch == ',' and depth == 0:
			items.append(''.join(current).strip())
			current = []
			continue
		current.append(ch)

	if current:
		items.append(''.join(current).strip())

	cols = []
	pk = None
	ignored_prefixes = (
		'PRIMARY KEY', 'KEY', 'INDEX', 'UNIQUE', 'CONSTRAINT', 'FOREIGN KEY',
		'CHECK', 'FULLTEXT', 'SPATIAL', 'ENGINE', 'DEFAULT', 'CHARSET', 'COLLATE'
	)

	for item in items:
		clean = re.sub(r'--.*$', '', item).strip()
		if not clean:
			continue
		upper = clean.upper()
		if any(upper.startswith(prefix) for prefix in ignored_prefixes):
			if upper.startswith('PRIMARY KEY'):
				m_pk = re.search(r'\(([`a-zA-Z0-9_]+)\)', clean)
				if m_pk:
					pk = m_pk.group(1).replace('`', '')
			continue

		tokens = clean.split()
		if not tokens:
			continue
		col_name = tokens[0].replace('`', '').strip()
		if not col_name or col_name.upper() in ('ENGINE', 'DEFAULT', 'CHARSET', 'COLLATE', 'AUTO_INCREMENT'):
			continue
		if col_name.startswith(')'):
			continue

		col_type = "VARCHAR(255)"
		if len(tokens) > 1:
			rest = clean[len(tokens[0]):].strip()
			m_type = re.match(r'^([a-zA-Z0-9_]+(?:\s*\([^)]*\))?)', rest)
			if m_type:
				col_type = m_type.group(1)
			else:
				col_type = tokens[1]

		cols.append({"name": col_name, "type": col_type})
		if 'PRIMARY KEY' in upper and not pk:
			pk = col_name

	return cols, pk


def find_statement_end(content, start_pos):
	"""
	Finds the terminating semicolon of a SQL statement, skipping quotes and escapes.
	"""
	in_str = False
	quote_char = None
	escape = False
	n = len(content)
	i = start_pos
	while i < n:
		ch = content[i]
		if escape:
			escape = False
			i += 1
			continue
		if ch == '\\':
			escape = True
			i += 1
			continue
		if in_str:
			if ch == quote_char:
				in_str = False
			i += 1
			continue
		if ch in ("'", '"'):
			in_str = True
			quote_char = ch
			i += 1
			continue
		if ch == ';':
			return i
		i += 1
	return n


def parse_values_string(cols, val_string):
	"""
	Tokenizes SQL value tuples respecting strings, escapes, and NULLs.
	"""
	rows = []
	current_row = []
	current_val = []
	in_str = False
	quote_char = None
	escape = False
	in_tuple = False

	for ch in val_string:
		if escape:
			current_val.append(ch)
			escape = False
			continue

		if ch == "\\":
			escape = True
			continue

		if in_str:
			if ch == quote_char:
				in_str = False
				quote_char = None
			else:
				current_val.append(ch)
			continue

		if ch in ("'", '"'):
			in_str = True
			quote_char = ch
			continue

		if ch == "(":
			if not in_tuple:
				in_tuple = True
				current_row = []
				current_val = []
				continue

		if ch == ")":
			if in_tuple:
				v = "".join(current_val).strip()
				if v == "NULL":
					v = None
				elif (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
					v = v[1:-1]
				current_row.append(v)
				if len(current_row) == len(cols):
					rows.append(dict(zip(cols, current_row)))
				in_tuple = False
				current_row = []
				current_val = []
				continue

		if ch == ",":
			if in_tuple:
				v = "".join(current_val).strip()
				if v == "NULL":
					v = None
				elif (v.startswith("'") and v.endswith("'")) or (v.startswith('"') and v.endswith('"')):
					v = v[1:-1]
				current_row.append(v)
				current_val = []
				continue

		if in_tuple:
			current_val.append(ch)

	return rows


def parse_sql_file_full(file_path):
	"""
	Universal SQL parser that dynamically extracts:
	1. All CREATE TABLE DDLs (table names, column names, data types, primary keys).
	2. All INSERT INTO statements and rows for every table present in the file.
	"""
	real_path = resolve_file_path(file_path)
	if not real_path or not os.path.exists(real_path):
		raise FileNotFoundError(f"SQL file not found at: {file_path} (resolved: {real_path})")

	with open(real_path, "r", encoding="utf-8", errors="ignore") as f:
		content = f.read()

	# 1. Parse DDL using balanced parentheses
	create_tables_raw = extract_create_tables_balanced(content)
	create_tables = {}
	for tbl, body in create_tables_raw.items():
		cols, pk = parse_ddl_columns(body)
		create_tables[tbl] = {"cols": cols, "pk": pk}

	# 2. Parse INSERT statements (supports multi-batch and tables without explicit col lists)
	parsed_data = {}
	ins_pattern = re.compile(r'INSERT\s+INTO\s+([`a-zA-Z0-9_]+)(?:\s*\((.*?)\))?\s*VALUES', re.IGNORECASE)

	for m in ins_pattern.finditer(content):
		tbl = m.group(1).replace('`', '').lower()
		if m.group(2):
			cols = [c.strip().replace('`', '') for c in m.group(2).split(',') if c.strip()]
		else:
			cols = [c["name"] for c in create_tables.get(tbl, {}).get("cols", [])]

		if not cols:
			continue

		start_val = m.end()
		end_val = find_statement_end(content, start_val)
		val_str = content[start_val:end_val]

		rows = parse_values_string(cols, val_str)
		if tbl not in parsed_data:
			parsed_data[tbl] = []
		parsed_data[tbl].extend(rows)

	return create_tables, parsed_data


class MigrationLogger:
	def __init__(self):
		self.logs = []

	def log(self, message):
		ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		entry = f"[{ts}] {message}"
		self.logs.append(entry)
		print(entry)

	def get_text(self):
		return "\n".join(self.logs)


# -------------------------------------------------------------
# FIELD MATCHING & AUTO-DETECTION DICTIONARIES
# -------------------------------------------------------------

AUTO_DETECT_DOCTYPES = {
	# Customers
	"customer": "Customer",
	"customers": "Customer",
	"tbl_cust": "Customer",
	"tbl_customer": "Customer",
	"client": "Customer",
	"clients": "Customer",
	# Suppliers
	"supplier": "Supplier",
	"suppliers": "Supplier",
	"tbl_supp": "Supplier",
	"tbl_supplier": "Supplier",
	"vendor": "Supplier",
	"vendors": "Supplier",
	# Items / Products
	"item": "Item",
	"items": "Item",
	"product": "Item",
	"products": "Item",
	"tbl_item": "Item",
	"productlines": "Item Group",
	# Orders
	"purchase_orders": "Purchase Order",
	"purchase_order": "Purchase Order",
	"purchase_order_details": "Purchase Order Item",
	"tbl_po_hdr": "Purchase Order",
	"tbl_po_dtl": "Purchase Order Item",
	"orders": "Sales Order",
	"order": "Sales Order",
	"salesorder": "Sales Order",
	"salesorders": "Sales Order",
	"orderdetails": "Sales Order Item",
	# Employees / HR
	"employee": "Employee",
	"employees": "Employee",
	"staff": "Employee",
	# Offices / Branch
	"office": "Branch",
	"offices": "Branch",
	"branch": "Branch",
	"branches": "Branch",
	# Payments
	"payment": "Payment Entry",
	"payments": "Payment Entry",
}

COMMON_FIELD_SYNONYMS = {
	# Generic
	"id": "name",
	"code": "name",
	"description": "description",
	"notes": "notes",
	"status": "status",
	# Customer / Supplier
	"customername": "customer_name",
	"customernumber": "name",
	"suppliername": "supplier_name",
	"suppliernumber": "name",
	"phone": "mobile_no",
	"phonenumber": "mobile_no",
	"telephone": "mobile_no",
	"email": "email_id",
	"emailaddress": "email_id",
	"addressline1": "primary_address",
	"addressline2": "address_line2",
	"city": "city",
	"state": "state",
	"country": "country",
	"postalcode": "pincode",
	"zipcode": "pincode",
	"creditlimit": "credit_limit",
	"contactfirstname": "first_name",
	"contactlastname": "last_name",
	# Item / Product
	"itemcode": "item_code",
	"productcode": "item_code",
	"itemname": "item_name",
	"productname": "item_name",
	"category": "item_group",
	"productline": "item_group",
	"unitofmeasure": "stock_uom",
	"uom": "stock_uom",
	"standardcost": "valuation_rate",
	"unitcost": "standard_rate",
	"buyprice": "valuation_rate",
	"listprice": "standard_rate",
	"msrp": "standard_rate",
	"quantityinstock": "opening_stock",
	"reorderlevel": "safety_stock",
	# Orders
	"purchaseordernumber": "name",
	"ordernumber": "name",
	"orderdate": "transaction_date",
	"expecteddeliverydate": "schedule_date",
	"totalamount": "grand_total",
	"shippingmethod": "shipping_method",
	"paymentterms": "payment_terms",
}


def inspect_field_matching(table_name, target_doctype, cols_list):
	"""
	Compares source MySQL columns with target ERPNext DocType fields.
	Returns:
	- matched: list of source columns that match target fields
	- unmatched: list of source columns that do NOT exist in the ERPNext DocType
	- field_mapping: dict mapping source_column -> target_fieldname
	"""
	if not target_doctype or not frappe.db.exists("DocType", target_doctype):
		return [], [c["name"] for c in cols_list], {}

	meta = frappe.get_meta(target_doctype)
	dt_fields = {f.fieldname.lower(): f.fieldname for f in meta.fields}
	dt_fields["name"] = "name"

	matched = []
	unmatched = []
	field_mapping = {}

	for col_info in cols_list:
		c_name = col_info["name"] if isinstance(col_info, dict) else str(col_info)
		c_clean = c_name.lower().replace("_", "").replace("-", "")

		mapped_target = None
		# 1. Exact match on fieldname
		if c_name.lower() in dt_fields:
			mapped_target = dt_fields[c_name.lower()]
		# 2. Match via synonym dictionary
		elif c_clean in COMMON_FIELD_SYNONYMS and COMMON_FIELD_SYNONYMS[c_clean] in dt_fields:
			mapped_target = dt_fields[COMMON_FIELD_SYNONYMS[c_clean]]
		# 3. Match normalized fieldname
		else:
			for dt_lower, dt_orig in dt_fields.items():
				if dt_lower.replace("_", "") == c_clean:
					mapped_target = dt_orig
					break

		if mapped_target:
			matched.append(c_name)
			field_mapping[c_name] = mapped_target
		else:
			unmatched.append(c_name)

	return matched, unmatched, field_mapping


def populate_and_match_tables(job_doc):
	"""
	Scans the SQL file, populates the table_summary child table,
	preserves user-selected target DocTypes, auto-suggests new ones,
	and calculates matched vs. unmatched fields.
	"""
	raw_path = job_doc.uploaded_sql_file or job_doc.sql_file_path
	if not raw_path:
		return

	file_path = resolve_file_path(raw_path)
	if not file_path or not os.path.exists(file_path):
		return

	create_tables, parsed_data = parse_sql_file_full(file_path)

	# Build existing row lookup
	existing_rows = {r.table_name: r for r in (job_doc.table_summary or [])}
	new_summary = []
	total_source = 0
	any_unmatched = False

	# Order tables
	all_tables = list(parsed_data.keys())
	for tbl in create_tables.keys():
		if tbl not in all_tables:
			all_tables.append(tbl)

	for tbl in all_tables:
		cols = create_tables.get(tbl, {}).get("cols", [])
		if not cols and tbl in parsed_data and parsed_data[tbl]:
			cols = [{"name": k} for k in parsed_data[tbl][0].keys()]

		src_cnt = len(parsed_data.get(tbl, []))
		total_source += src_cnt

		# Retrieve existing row if user already set target_doctype
		existing_row = existing_rows.get(tbl)
		target_dt = existing_row.target_doctype if existing_row and existing_row.target_doctype else None

		# Auto-detect target DocType if not manually set
		if not target_dt:
			target_dt = AUTO_DETECT_DOCTYPES.get(tbl.lower())

		# Perform field comparison
		if target_dt:
			matched, unmatched, _ = inspect_field_matching(tbl, target_dt, cols)
			matched_str = ", ".join(matched) if matched else "None"
			unmatched_str = ", ".join(unmatched) if unmatched else "All fields match"
			status = "Pending Approval" if unmatched else "Validated"
			if unmatched:
				any_unmatched = True
			details = f"Target: {target_dt} | Matched: {len(matched)}, Unmatched: {len(unmatched)}"
		else:
			matched_str = ""
			unmatched_str = "Please select a Target DocType"
			status = "Pending"
			details = "Target DocType not selected"

		new_summary.append({
			"table_name": tbl,
			"source_count": src_cnt,
			"target_doctype": target_dt,
			"status": status,
			"matched_fields": matched_str,
			"unmatched_fields": unmatched_str,
			"imported_count": existing_row.imported_count if existing_row else 0,
			"duration_sec": existing_row.duration_sec if existing_row else 0.0,
			"details": details
		})

	job_doc.table_summary = []
	for r in new_summary:
		job_doc.append("table_summary", r)

	job_doc.total_source_records = total_source
	if job_doc.status not in ("Completed", "In Progress", "On Hold"):
		job_doc.status = "Pending Approval" if any_unmatched else "Validated"


def check_field_compatibility(job_name):
	"""
	Returns details about unmatched fields across all mapped tables for the Desk modal.
	"""
	job = frappe.get_doc("MySQL Migration Job", job_name)
	unmapped_tables = []
	unmapped_doctypes = []

	for row in job.table_summary:
		if not row.target_doctype:
			unmapped_doctypes.append(row.table_name)
			continue

		if row.unmatched_fields and row.unmatched_fields not in ("All fields match", "None", ""):
			unmapped_tables.append({
				"table_name": row.table_name,
				"target_doctype": row.target_doctype,
				"unmatched_fields": row.unmatched_fields,
				"source_count": row.source_count
			})

	return {
		"has_unmapped": bool(unmapped_tables),
		"unmapped_tables": unmapped_tables,
		"unmapped_doctypes": unmapped_doctypes
	}


def set_job_on_hold(job_name):
	"""
	Sets the job status to 'On Hold' when user declines to proceed with missing fields.
	"""
	job = frappe.get_doc("MySQL Migration Job", job_name)
	job.status = "On Hold"
	for row in job.table_summary:
		if row.status == "Pending Approval":
			row.status = "On Hold"
	logger = MigrationLogger()
	logger.log("⚠️ Migration halted by user approval check. Status placed ON HOLD.")
	job.execution_log = (job.execution_log or "") + "\n" + logger.get_text()
	job.save()
	frappe.db.commit()
	return {"status": "On Hold"}


# -------------------------------------------------------------
# NATIVE ERPNEXT DATA MIGRATION ENGINE
# -------------------------------------------------------------

def execute_migration_job(job_name, approved=False):
	"""
	Executes migration directly into native ERPNext DocTypes (Customer, Supplier, Item, etc.),
	omitting unmapped fields upon user approval.
	"""
	job = frappe.get_doc("MySQL Migration Job", job_name)
	logger = MigrationLogger()
	start_time = time.time()

	raw_path = job.uploaded_sql_file or job.sql_file_path
	file_path = resolve_file_path(raw_path)
	if not file_path or not os.path.exists(file_path):
		raise FileNotFoundError(f"SQL file not found at: {file_path}")

	# Check unmapped fields approval
	comp = check_field_compatibility(job_name)
	if comp["unmapped_doctypes"]:
		frappe.throw(f"Please assign a Target DocType for tables: {', '.join(comp['unmapped_doctypes'])}")

	if comp["has_unmapped"] and not approved:
		job.status = "Pending Approval"
		job.save()
		frappe.db.commit()
		return {"status": "Pending Approval", "requires_approval": True, "unmapped_tables": comp["unmapped_tables"]}

	job.status = "In Progress"
	job.save()
	frappe.db.commit()

	try:
		logger.log("==================================================")
		logger.log(f"STARTING ERPNEXT CORE MIGRATION: {job.title} ({job.name})")
		logger.log("==================================================")
		logger.log(f"Source SQL File: {file_path}")

		create_tables, parsed_data = parse_sql_file_full(file_path)
		total_imported = 0
		now = now_datetime()

		for row in job.table_summary:
			tbl = row.table_name
			target_dt = row.target_doctype
			if not target_dt or not frappe.db.exists("DocType", target_dt):
				row.status = "Failed"
				row.details = f"Target DocType '{target_dt}' does not exist!"
				continue

			src_rows = parsed_data.get(tbl, [])
			if not src_rows:
				row.imported_count = 0
				row.status = "Success"
				row.details = "No data rows in source"
				continue

			t0 = time.time()
			logger.log(f"\nMigrating table '{tbl}' -> ERPNext `{target_dt}` ({len(src_rows)} records)...")

			# Get DocType DB columns and field mapping
			db_table = f"tab{target_dt}"
			db_cols = {c[0].lower(): c[0] for c in frappe.db.sql(f"DESCRIBE `{db_table}`")}
			cols_list = create_tables.get(tbl, {}).get("cols", [])
			if not cols_list and src_rows:
				cols_list = [{"name": k} for k in src_rows[0].keys()]

			matched_names, unmatched_names, field_mapping = inspect_field_matching(tbl, target_dt, cols_list)
			logger.log(f"-> Matched fields ({len(matched_names)}): {', '.join(matched_names)}")
			if unmatched_names:
				logger.log(f"-> Omitting unmapped fields ({len(unmatched_names)}): {', '.join(unmatched_names)}")

			# If option clear_existing_data is enabled, clear target DocType
			if job.clear_existing_data:
				frappe.db.sql(f"DELETE FROM `{db_table}`")
				frappe.db.commit()

			# Prepare clean rows for batch insert
			clean_rows = []
			for idx, r in enumerate(src_rows, 1):
				clean = {}
				for src_k, src_v in r.items():
					if src_k in field_mapping:
						target_col = field_mapping[src_k].lower()
						if target_col in db_cols:
							clean[db_cols[target_col]] = src_v

				# Set standard Frappe audit fields
				if "creation" in db_cols and "creation" not in clean:
					clean[db_cols["creation"]] = now
				if "modified" in db_cols and "modified" not in clean:
					clean[db_cols["modified"]] = now
				if "owner" in db_cols and "owner" not in clean:
					clean[db_cols["owner"]] = "Administrator"
				if "modified_by" in db_cols and "modified_by" not in clean:
					clean[db_cols["modified_by"]] = "Administrator"
				if "docstatus" in db_cols and "docstatus" not in clean:
					clean[db_cols["docstatus"]] = 0
				if "idx" in db_cols and "idx" not in clean:
					clean[db_cols["idx"]] = idx

				# Primary Key `name` assignment
				pk_val = None
				for k in ("name", "supplierNumber", "customerNumber", "itemCode", "productCode", "orderNumber", "purchaseOrderNumber", "employeeNumber", "officeCode"):
					if k in r and r[k]:
						pk_val = str(r[k]).strip()
						break

				if not pk_val:
					pk_val = f"{tbl.upper()}-{idx:05d}"
				clean["name"] = pk_val

				# Mandatory fields defaults for standard ERPNext DocTypes
				if target_dt == "Customer":
					if "customer_name" in db_cols and "customer_name" not in clean:
						clean[db_cols["customer_name"]] = clean["name"]
					if "customer_type" in db_cols and "customer_type" not in clean:
						clean[db_cols["customer_type"]] = "Company"
					if "customer_group" in db_cols and "customer_group" not in clean:
						clean[db_cols["customer_group"]] = "Commercial"
					if "territory" in db_cols and "territory" not in clean:
						clean[db_cols["territory"]] = "Rest Of The World"

				elif target_dt == "Supplier":
					if "supplier_name" in db_cols and "supplier_name" not in clean:
						clean[db_cols["supplier_name"]] = clean["name"]
					if "supplier_type" in db_cols and "supplier_type" not in clean:
						clean[db_cols["supplier_type"]] = "Company"
					if "supplier_group" in db_cols and "supplier_group" not in clean:
						clean[db_cols["supplier_group"]] = "Local"

				elif target_dt == "Item":
					if "item_code" in db_cols and "item_code" not in clean:
						clean[db_cols["item_code"]] = clean["name"]
					if "item_name" in db_cols and "item_name" not in clean:
						clean[db_cols["item_name"]] = clean["name"]
					if "item_group" in db_cols and "item_group" not in clean:
						clean[db_cols["item_group"]] = "Products"
					if "stock_uom" in db_cols and "stock_uom" not in clean:
						clean[db_cols["stock_uom"]] = "Nos"
					if "is_stock_item" in db_cols and "is_stock_item" not in clean:
						clean[db_cols["is_stock_item"]] = 0
					if "gst_hsn_code" in db_cols and "gst_hsn_code" not in clean:
						clean[db_cols["gst_hsn_code"]] = "95030020"

				elif target_dt == "Employee":
					if "first_name" in db_cols and "first_name" not in clean:
						clean[db_cols["first_name"]] = clean["name"]
					if "employee_name" in db_cols and "employee_name" not in clean:
						clean[db_cols["employee_name"]] = clean["name"]
					if "company" in db_cols and "company" not in clean:
						clean[db_cols["company"]] = "Tally"
					if "date_of_joining" in db_cols and "date_of_joining" not in clean:
						clean[db_cols["date_of_joining"]] = now.strftime("%Y-%m-%d")

				elif target_dt == "Branch":
					if "branch" in db_cols and "branch" not in clean:
						clean[db_cols["branch"]] = clean["name"]

				clean_rows.append(clean)

			# High speed batch insertion
			if clean_rows:
				all_keys = list(clean_rows[0].keys())
				cols_str = ", ".join([f"`{k}`" for k in all_keys])
				single_placeholder = f"({', '.join(['%s'] * len(all_keys))})"
				batch_size = 500

				for i in range(0, len(clean_rows), batch_size):
					batch = clean_rows[i:i + batch_size]
					vals = []
					for cr in batch:
						for k in all_keys:
							vals.append(cr.get(k))
					placeholders = ", ".join([single_placeholder] * len(batch))
					query = f"REPLACE INTO `{db_table}` ({cols_str}) VALUES {placeholders}"
					frappe.db.sql(query, vals)

				frappe.db.commit()

			imp_cnt = len(clean_rows)
			dur = round(time.time() - t0, 2)
			total_imported += imp_cnt
			row.imported_count = imp_cnt
			row.duration_sec = dur
			row.status = "Success"
			row.details = f"Successfully imported {imp_cnt} records into {target_dt} ({dur}s)"
			logger.log(f"✅ Stored {imp_cnt} records into ERPNext DocType `{target_dt}` in {dur}s.")

		dur_total = round(time.time() - start_time, 2)
		logger.log("==================================================")
		logger.log(f"MIGRATION COMPLETED SUCCESSFULLY in {dur_total}s!")
		logger.log(f"Total Records Stored in Native ERPNext DocTypes: {total_imported}")
		logger.log("==================================================")

		job.status = "Completed"
		job.total_imported_records = total_imported
		job.migration_duration = f"{dur_total} seconds"
		job.execution_log = (job.execution_log or "") + "\n\n" + logger.get_text()
		job.save()
		frappe.db.commit()

		return {"status": "Completed", "total_imported": total_imported, "duration": dur_total}

	except Exception as e:
		frappe.db.rollback()
		logger.log(f"ERROR: Migration failed with exception: {str(e)}")
		import traceback
		logger.log(traceback.format_exc())
		job.status = "Failed"
		job.execution_log = (job.execution_log or "") + "\n\n" + logger.get_text()
		job.save()
		frappe.db.commit()
		raise e


def clear_migrated_data(job_name):
	"""
	Clears migrated records from target DocTypes and resets the job summary.
	"""
	job = frappe.get_doc("MySQL Migration Job", job_name)
	logger = MigrationLogger()
	logger.log(f"Clearing migrated data for job: {job_name}")

	for row in job.table_summary:
		target_dt = row.target_doctype
		if target_dt and frappe.db.exists("DocType", target_dt):
			db_table = f"tab{target_dt}"
			frappe.db.sql(f"DELETE FROM `{db_table}`")
			row.imported_count = 0
			row.duration_sec = 0.0
			row.status = "Pending"
			row.details = "Data cleared"

	frappe.db.commit()
	job.total_imported_records = 0
	job.status = "Draft"
	logger.log("All target DocType records cleared.")
	job.execution_log = (job.execution_log or "") + "\n\n" + logger.get_text()
	job.save()
	frappe.db.commit()
	return {"status": "cleared"}

