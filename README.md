# MySQL Migrator for ERPNext

[![Frappe Framework](https://img.shields.io/badge/Frappe-v15%20%7C%20v16-blue.svg)](https://frappeframework.com/)
[![ERPNext](https://img.shields.io/badge/ERPNext-Compatible-green.svg)](https://erpnext.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](license.txt)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

**MySQL Migrator** is a universal data migration application for ERPNext and Frappe. It allows administrators to import legacy or external MySQL database dumps (such as ClassicModels, custom procurement databases, supply chain ERPs, and legacy accounting tables) directly into **native ERPNext default DocTypes** (`Customer`, `Supplier`, `Item`, `Purchase Order`, `Sales Order`, `Employee`, `Branch`, `Payment Entry`, etc.) without polluting your instance with unnecessary custom storage DocTypes.

---

## 🌟 Key Features

### 1. 🎯 Direct Storage in Native ERPNext DocTypes
- **No Custom Storage DocTypes**: Migrated records land straight into ERPNext core business modules (`tabCustomer`, `tabSupplier`, `tabItem`, `tabPurchase Order`, etc.).
- Keeps your ERPNext schema pristine, maintainable, and upgrade-safe.

### 2. 🔍 Dynamic Table Discovery on Save
- Simply attach or specify the file path of any `.sql` dump file and click **Save**.
- The migrator automatically parses the DDL and lists all discovered MySQL tables in the **Tables Summary** child table, showing exact source row counts.

### 3. 🔀 Flexible Target DocType Mapping
- In the **Tables Summary** child table, each row features a searchable **Link to `DocType`** displaying all DocTypes present in your ERPNext system.
- Automatically suggests sensible defaults (e.g., `suppliers` ➔ `Supplier`, `customers` ➔ `Customer`, `items` ➔ `Item`, `purchase_orders` ➔ `Purchase Order`, `orders` ➔ `Sales Order`, `employees` ➔ `Employee`).
- Administrators can override and assign **any custom or standard ERPNext DocType** for each table.

### 4. ⚖️ Field Matching & Discrepancy Detection
- The system automatically compares MySQL table column definitions against the selected ERPNext DocType:
  - **Matched Fields**: Identifies matching columns (including intelligent synonyms like `phone` ➔ `mobile_no`, `postalCode` ➔ `pincode`, `unitCost` ➔ `standard_rate`, `category` ➔ `item_group`).
  - **Unmatched Fields**: Detects which source columns **do not exist** in the target ERPNext DocType.

### 5. 🛡️ Interactive Approval Workflow ("Proceed" vs. "Put on Hold")
- When you click **Run Migration**, if any unmapped columns are detected:
  - An interactive modal appears listing the exact table names, target DocTypes, and missing column names.
  - **"Proceed Without Missing Fields"**: Approves the migration. Records are inserted into the target ERPNext DocType, cleanly omitting the unmapped fields.
  - **"Put on Hold"**: Immediately stops the process and sets the job status to **`On Hold`**, allowing the administrator to review fields or create custom fields before proceeding.

### 6. ⚡ Ultra-High Performance & Resilient DDL Parser
- **Balanced Parenthesis Parser**: Correctly extracts `CREATE TABLE` bodies while cleanly isolating table options (`ENGINE=InnoDB`, `DEFAULT CHARSET=utf8mb4`).
- **Universal Multi-Chunk INSERT Handling**: Supports both `INSERT INTO tbl (cols) VALUES ...` and column-less `INSERT INTO tbl VALUES ...`.
- **High-Speed Batch Inserter**: Utilizes multi-row `REPLACE INTO` batches of 500 rows, importing **100,000 records in ~7 seconds**.

---

## 📦 Installation

To install **MySQL Migrator** on your Frappe bench:

```bash
# 1. Switch to your bench directory
cd ~/frappe-bench

# 2. Get the app from GitHub
bench get-app https://github.com/kashyappatadiya240-afk/mysql_migrator.git

# 3. Install the app on your site
bench --site <your-site-name> install-app mysql_migrator

# 4. Run database migrations and clear cache
bench --site <your-site-name> migrate
bench --site <your-site-name> clear-cache
```

---

## 🚀 How to Use (Desk Interface)

### Step 1: Create a Migration Job
1. In ERPNext Desk, search for **MySQL Migration Job** or open the **MySQL Migration** workspace.
2. Click **New**.
3. Select **Source Type**: `SQL Dump File`.
4. Upload your `.sql` file using **Or Upload SQL File**, or provide the absolute path in **SQL File Path**.
5. Click **Save**.

### Step 2: Review Discovered Tables & Assign Target DocTypes
1. Upon saving, the **Tables Summary** child table is automatically populated with all tables found in the file.
2. Review the auto-suggested **Target DocType** for each table or select the desired DocType from the searchable dropdown.
3. Observe the **Matched Fields** and **Unmatched in ERPNext** columns.

### Step 3: Run Migration & Handle Approvals
1. Click the primary **Run Migration** button.
2. If all fields match, the migration runs directly.
3. If unmapped fields exist, an approval dialog displays the missing fields:
   - Click **Proceed Without Missing Fields** to import the data into ERPNext.
   - Click **Put on Hold** to halt execution and investigate.
4. Once completed, a detailed log and record count breakdown are displayed in the form.

---

## 💻 Bench CLI Usage

You can also run migrations directly from the terminal using the custom bench command:

```bash
# Migrate SQL dump into ERPNext default DocTypes
bench --site <your-site-name> mysql-import --file /path/to/database.sql

# Clear existing target data before migration
bench --site <your-site-name> mysql-import --file /path/to/database.sql --clear
```

---

## 📊 Verified Datasets & Benchmarks

| SQL Dataset | Total Rows | Target ERPNext DocTypes | Execution Time |
|---|---|---|---|
| **Procurement 100k** (`procurement_system_100k.sql`) | 100,000 | `Supplier`, `Customer`, `Item`, `Purchase Order`, `Purchase Order Item` | **7.06s** |
| **ClassicModels** (`mysqlsampledatabase.sql`) | 3,864 | `Customer`, `Item`, `Sales Order`, `Employee`, `Branch`, `Payment Entry` | **0.82s** |
| **Dummy Multi-Template** (`01_mysql_source_dummy.sql`) | 12 | `Customer`, `Supplier`, `Purchase Order`, `Purchase Order Item` | **0.05s** |

---

## 🛠️ Field Synonyms Reference

The migrator includes built-in semantic mappings for common legacy column naming schemes:

| MySQL Column Variant | Mapped ERPNext DocType Field |
|---|---|
| `customerName`, `customer_name` | `customer_name` |
| `supplierName`, `supplier_name` | `supplier_name` |
| `itemCode`, `productCode` | `item_code` |
| `itemName`, `productName` | `item_name` |
| `category`, `productLine` | `item_group` |
| `phone`, `phoneNumber`, `telephone` | `mobile_no` |
| `email`, `emailAddress` | `email_id` |
| `addressLine1` | `primary_address` |
| `postalCode`, `zipCode` | `pincode` |
| `unitCost`, `buyPrice`, `standardCost` | `valuation_rate` / `standard_rate` |
| `orderDate` | `transaction_date` |
| `expectedDeliveryDate` | `schedule_date` |
| `totalAmount` | `grand_total` |

---

## 📄 License

This project is licensed under the **MIT License**. See [`license.txt`](license.txt) for details.

Developed with ❤️ for the Frappe and ERPNext ecosystem.
