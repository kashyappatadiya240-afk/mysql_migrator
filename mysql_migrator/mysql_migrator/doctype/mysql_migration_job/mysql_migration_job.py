# Copyright (c) 2026, Kashyap and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import cint

class MySQLMigrationJob(Document):
	def validate(self):
		from mysql_migrator.migrator import populate_and_match_tables
		populate_and_match_tables(self)

	@frappe.whitelist()
	def check_field_compatibility(self):
		from mysql_migrator.migrator import check_field_compatibility
		return check_field_compatibility(self.name)

	@frappe.whitelist()
	def run_migration(self, approved=0):
		from mysql_migrator.migrator import execute_migration_job
		return execute_migration_job(self.name, approved=bool(cint(approved)))

	@frappe.whitelist()
	def set_on_hold(self):
		from mysql_migrator.migrator import set_job_on_hold
		return set_job_on_hold(self.name)

	@frappe.whitelist()
	def reload_all_tables(self):
		from mysql_migrator.migrator import reload_tables_from_sql
		return reload_tables_from_sql(self.name)

	@frappe.whitelist()
	def clear_data(self):
		from mysql_migrator.migrator import clear_migrated_data
		return clear_migrated_data(self.name)
