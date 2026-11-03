import click
import frappe
from frappe.commands import pass_context

@click.command("mysql-import")
@click.option("--file", default="/home/kashyap/Downloads/mysqlsampledatabase.sql", help="Path to MySQL SQL dump file")
@click.option("--clear", is_flag=True, default=False, help="Clear existing data before import")
@pass_context
def mysql_import_cmd(context, file, clear):
	"""Migrate a MySQL SQL database dump directly into native ERPNext DocTypes."""
	site = context.sites[0]
	frappe.init(site=site)
	frappe.connect()

	click.secho(f"\n🚀 Starting MySQL Import into Native ERPNext for site: {site}", fg="cyan", bold=True)
	click.secho(f"📁 SQL File: {file}", fg="cyan")

	job = frappe.new_doc("MySQL Migration Job")
	job.title = f"CLI Import - {frappe.utils.now()}"
	job.source_type = "SQL Dump File"
	job.sql_file_path = file
	job.clear_existing_data = 1 if clear else 0
	job.insert()
	frappe.db.commit()

	from mysql_migrator.migrator import execute_migration_job
	click.secho("⚡ Executing database migration into native ERPNext DocTypes...", fg="yellow")
	res = execute_migration_job(job.name, approved=True)

	click.secho(f"\n✅ Migration finished successfully!", fg="green", bold=True)
	click.secho(f"📊 Total Records Migrated: {res.get('total_imported')}", fg="green")
	click.secho(f"⏱️ Duration: {res.get('duration')}s\n", fg="green")

commands = [mysql_import_cmd]
