// Copyright (c) 2023, Avunu LLC and contributors
// For license information, please see license.txt

frappe.ui.form.on('Espresso Sync Connection', {
	refresh: function(frm) {
		// load css from assets/espresso_sync/css/espresso_sync_connection.css using frappe.dom.set_style()
		// frappe.dom.set_style(frappe.render_template("espresso_sync_connection_css"), "espresso_sync_connection_css");
	}
});

frappe.ui.form.on('Espresso Sync Connection Import', {
	template_generator: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		import_doctype = cur_row.import_doctype;
		open_template_generator_dialog(frm, import_doctype);
	}
});

function open_template_generator_dialog(frm, doctype) {
	frappe.call({
		method: 'espresso_sync.espresso_sync.doctype.espresso_sync_connection.espresso_sync_connection.get_doctype_fields',
		args: {
			doctype: doctype,
		},
		callback: function (response) {
			const field_list = response.message || [];
			show_template_generator_dialog(frm, field_list);
		},
	});
}

function show_template_generator_dialog(frm, fields) {
	let dialog = new frappe.ui.Dialog({
		title: __('Template Generator'),
		fields: [
			{
				fieldtype: 'Section Break',
				label: __('Select Fields'),
			},
			// Main fields 'Table MultiSelect' will be added by add_fields_to_dialog function
			// Add more fields here for the table fields
		],
		primary_action_label: __('Render Template'),
		primary_action: function () {
			let selected_fields = get_selected_fields(dialog);
			let template_json = create_template_json(selected_fields);
			dialog.hide();
			frm.set_value('object_map', JSON.stringify(template_json, null, 2));
			frm.refresh_field('object_map');
		},
	});

	add_fields_to_dialog(dialog, fields);
	dialog.show();
}


// Helper functions to add fields to the dialog, get selected fields, create the JSON template, and show the output
function add_fields_to_dialog(dialog, fields) {
	const main_fields = fields.filter((field) => field.fieldtype !== "Table");
	const table_fields = fields.filter((field) => field.fieldtype === "Table");

	dialog.append({
		fieldtype: "Table MultiSelect",
		fieldname: "main_fields",
		label: __("Main Fields"),
		options: main_fields.map((field) => ({
			label: field.label,
			value: field.fieldname,
		})),
	});

	for (const table_field of table_fields) {
		dialog.append({
			fieldtype: "Table MultiSelect",
			fieldname: table_field.fieldname,
			label: __(table_field.label),
			options: table_field.child_fields.map((field) => ({
				label: field.label,
				value: field.fieldname,
			})),
		});

		dialog.append({
			fieldtype: "Select",
			fieldname: table_field.fieldname + "_options",
			label: __("Select " + table_field.label + " Template Type"),
			options: ["List", "Loop"],
			default: "List",
		});
	}
}

function get_selected_fields(dialog) {
	let selected_fields = {
		main_fields: [],
		table_fields: [],
	};

	const main_fields = dialog.get_field("main_fields").get_value();

	for (const fieldname of main_fields) {
		selected_fields.main_fields.push({ fieldname: fieldname });
	}

	for (const field of dialog.fields_list) {
		if (field.df.fieldtype === "Table MultiSelect") {
			const table_fieldname = field.df.fieldname;
			const table_options = dialog.get_field(table_fieldname + "_options").get_value();
			const table_fields = field.get_value().map((fieldname) => ({ fieldname: fieldname }));

			selected_fields.table_fields.push({
				fieldname: table_fieldname,
				options: table_options,
				fields: table_fields,
			});
		}
	}

	return selected_fields;
}



function create_template_json(selected_fields) {
	let template_json = {};

	for (const field of selected_fields.main_fields) {
		template_json[field.fieldname] = "";
	}

	for (const table_field of selected_fields.table_fields) {
		const table_fieldname = table_field.fieldname;
		const table_field_options = table_field.options;
		const table_fields = table_field.fields;

		let table_template_json = {};

		if (table_field_options === "List") {
			table_template_json[table_fieldname] = [{}];

			for (const child_field of table_fields) {
				table_template_json[table_fieldname][0][child_field.fieldname] = "";
			}
		} else if (table_field_options === "Loop") {
			table_template_json[table_fieldname] = {
				foreach: {
					elements: "",
					map: {},
				},
			};

			for (const child_field of table_fields) {
				table_template_json[table_fieldname].foreach.map[child_field.fieldname] = "";
			}
		}

		template_json = { ...template_json, ...table_template_json };
	}

	return template_json;
}
