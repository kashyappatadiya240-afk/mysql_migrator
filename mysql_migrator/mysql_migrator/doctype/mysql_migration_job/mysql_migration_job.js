// Copyright (c) 2026, Kashyap and contributors
// For license information, please see license.txt

frappe.ui.form.on('MySQL Migration Job', {
	refresh: function(frm) {
		// Custom status indicators
		if (frm.doc.status === 'Completed') {
			frm.page.set_indicator(__('Completed'), 'green');
		} else if (frm.doc.status === 'Pending Approval') {
			frm.page.set_indicator(__('Pending Approval'), 'orange');
		} else if (frm.doc.status === 'On Hold') {
			frm.page.set_indicator(__('On Hold'), 'yellow');
		} else if (frm.doc.status === 'Validated') {
			frm.page.set_indicator(__('Validated'), 'blue');
		} else if (frm.doc.status === 'Failed') {
			frm.page.set_indicator(__('Failed'), 'red');
		} else if (frm.doc.status === 'In Progress') {
			frm.page.set_indicator(__('In Progress'), 'purple');
		}

		if (!frm.is_new()) {
			// Action button: Rescan & Match Fields
			frm.add_custom_button(__('Rescan & Match Fields'), function() {
				frm.save();
			}, __('Actions'));

			// Action button: Clear Migrated Data
			frm.add_custom_button(__('Clear Target Data'), function() {
				frappe.confirm(
					__('WARNING: This will clear records in the selected target ERPNext DocTypes. Continue?'),
					function() {
						frappe.call({
							method: 'clear_data',
							doc: frm.doc,
							freeze: true,
							freeze_message: __('Clearing target data...'),
							callback: function(r) {
								frm.reload_doc();
								frappe.show_alert({message: __('Target data cleared'), indicator: 'blue'});
							}
						});
					}
				);
			}, __('Actions'));

			// Primary Action: Run Migration with Approval Workflow
			if (frm.doc.status !== 'Completed') {
				frm.page.set_primary_action(__('Run Migration'), function() {
					run_migration_workflow(frm);
				});
			} else {
				frm.page.set_secondary_action(__('Re-Run Migration'), function() {
					run_migration_workflow(frm);
				});
			}
		}
	}
});

// Update field matching when target_doctype is changed in table summary
frappe.ui.form.on('MySQL Migration Table Summary', {
	target_doctype: function(frm, cdt, cdn) {
		frm.dirty();
		frm.save();
	}
});

function run_migration_workflow(frm) {
	// 1. Verify that all tables have target DocTypes selected
	let missing_doctypes = [];
	(frm.doc.table_summary || []).forEach(row => {
		if (!row.target_doctype) {
			missing_doctypes.push(row.table_name);
		}
	});

	if (missing_doctypes.length > 0) {
		frappe.msgprint({
			title: __('Target DocType Required'),
			message: __('Please select a Target DocType for the following table(s) before migrating: <br><b>') + missing_doctypes.join(', ') + '</b>',
			indicator: 'red'
		});
		return;
	}

	// 2. Check field compatibility between MySQL tables and ERPNext DocTypes
	frappe.call({
		method: 'check_field_compatibility',
		doc: frm.doc,
		freeze: true,
		freeze_message: __('Inspecting Field Matching...'),
		callback: function(r) {
			if (r.message && r.message.has_unmapped) {
				show_approval_dialog(frm, r.message.unmapped_tables);
			} else {
				// Perfect match on all fields
				frappe.confirm(
					__('All fields match target ERPNext DocTypes. Proceed to migrate all records into native ERPNext?'),
					function() {
						execute_migration(frm, 1);
					}
				);
			}
		}
	});
}

function show_approval_dialog(frm, unmapped_tables) {
	let rows_html = '';
	unmapped_tables.forEach(t => {
		rows_html += `
			<tr>
				<td style="font-weight: 600;">${t.table_name}</td>
				<td><span class="badge badge-info" style="background: #e3f2fd; color: #1565c0; font-size: 11px; padding: 4px 8px;">${t.target_doctype}</span></td>
				<td style="color: #c62828;"><code>${t.unmatched_fields}</code></td>
			</tr>
		`;
	});

	let dialog_content = `
		<div style="font-size: 13px;">
			<div class="alert alert-warning" style="margin-bottom: 15px;">
				<b>Field Discrepancy Detected:</b> Some columns in your MySQL table(s) do not exist in the selected ERPNext DocType.
			</div>
			<p class="text-muted" style="margin-bottom: 10px;">
				The following columns from your MySQL source will be <b>omitted</b> because they do not exist in ERPNext:
			</p>
			<div style="max-height: 240px; overflow-y: auto; border: 1px solid #d1d8dd; border-radius: 4px; margin-bottom: 15px;">
				<table class="table table-bordered table-sm" style="margin-bottom: 0; font-size: 12px;">
					<thead style="background: #f8f9fa;">
						<tr>
							<th style="width: 25%;">MySQL Table</th>
							<th style="width: 25%;">Target DocType</th>
							<th style="width: 50%;">Missing in ERPNext (Omitted)</th>
						</tr>
					</thead>
					<tbody>
						${rows_html}
					</tbody>
				</table>
			</div>
			<p style="font-weight: 500;">
				Do you approve proceeding to store data in ERPNext <b>without</b> these fields, or would you like to halt and put this migration on hold?
			</p>
		</div>
	`;

	let d = new frappe.ui.Dialog({
		title: __('Field Matching Approval Required'),
		fields: [
			{
				fieldtype: 'HTML',
				fieldname: 'details_html',
				options: dialog_content
			}
		],
		primary_action_label: __('Proceed Without Missing Fields'),
		primary_action: function() {
			d.hide();
			execute_migration(frm, 1);
		},
		secondary_action_label: __('Put on Hold'),
		secondary_action: function() {
			d.hide();
			frappe.call({
				method: 'set_on_hold',
				doc: frm.doc,
				freeze: true,
				freeze_message: __('Putting migration on hold...'),
				callback: function(r) {
					frm.reload_doc();
					frappe.msgprint({
						title: __('Migration On Hold'),
						message: __('Migration has been stopped and marked <b>On Hold</b>. You can review field mappings or adjust DocType fields before proceeding.'),
						indicator: 'yellow'
					});
				}
			});
		}
	});

	d.show();
}

function execute_migration(frm, approved) {
	frappe.call({
		method: 'run_migration',
		doc: frm.doc,
		args: {
			approved: approved
		},
		freeze: true,
		freeze_message: __('Migrating Data into Native ERPNext DocTypes...'),
		callback: function(r) {
			frm.reload_doc();
			frappe.msgprint({
				title: __('Migration Completed'),
				message: __('Migration finished with status: ') + '<b>' + (frm.doc.status || 'Completed') + '</b><br>' +
				         __('Total Records Imported: ') + '<b>' + (frm.doc.total_imported_records || 0) + '</b>',
				indicator: frm.doc.status === 'Completed' ? 'green' : 'orange'
			});
		}
	});
}
