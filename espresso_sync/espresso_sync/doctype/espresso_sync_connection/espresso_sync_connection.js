// Copyright (c) 2023, Avunu LLC and contributors
// For license information, please see license.txt

// debug
frappe.realtime.on("console_log", function (data) {
	console.log(data);
});
frappe.realtime.on("console.log", function (data) {
	console.log(data);
});

frappe.realtime.on("show_alert", function (data) {
	frappe.show_alert({
		message: data.message,
		indicator: data.indicator,
	})
});

frappe.realtime.on("import_progress", function (data) {
	// use show_progress
	frappe.show_progress("Importing Sync Items", data.progress, data.total);
	// hide progress when complete
	if (data.progress == data.total) {
		frappe.hide_progress();
	}
});

frappe.ui.form.on('Espresso Sync Connection', {
	refresh: function(frm) {
		// load css from assets/espresso_sync/css/espresso_sync_connection.css using frappe.dom.set_style()
		// frappe.dom.set_style(frappe.render_template("espresso_sync_connection_css"), "espresso_sync_connection_css");
	}
});

frappe.ui.form.on('Espresso Sync Connection Shot', {
	template_generator: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		dt = cur_row.dt;
		open_template_generator_dialog(frm, dt);
	},
	render_sample: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		object_map = cur_row.object_map;
		sample_object = cur_row.sample_object;
		if (object_map && sample_object) {
			object_map = JSON.parse(object_map);
			sample_object = JSON.parse(sample_object);
			frm.call({
				method: 'render_sample',
				args: {
					object_map: object_map,
					sample_object: sample_object,
				},
				callback: function (response) {
					// show the sample in a frappe dialog
					const sample = response.message || {};
					const sample_formatted = JSON.stringify(sample, null, 2);
					frappe.msgprint({'message': '<pre>' + sample_formatted + '</pre>', 'title': 'Sample Data'});
				},
			});
		}
	},
	test_import: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		if (!cur_row.sample_object) {
			cur_row.sample_object = '{}';
		}

		frm.call({
			method: 'test_import',
			doc: frm.doc,
			args: {
				import_step: cur_row,
				import_object: cur_row.sample_object,
			},
			callback: function (response) {
				// show the sample in a frappe dialog
				const sample = response.message || {};
				const sample_formatted = JSON.stringify(sample, null, 2);
				frappe.msgprint({'message': '<pre>' + sample_formatted + '</pre>', 'title': 'Sample Import'});
			},
		});
	},
	get_samples: function (frm, cdt, cdn) {
		frappe.show_alert("Fetching sample data");
		var cur_row = locals[cdt][cdn];
		const dt = cur_row.dt;
		const uri = cur_row.uri
		try {
			frm.call({
				method: 'get_sample_data',
				doc: frm.doc,
				args: {
					shot_name: cur_row.name,
				},
				callback: function (response) {
					const sample_data = response.message || [];
					const sample_data_count = sample_data.length;
					// update the sample_object field
					cur_row.sample_objects = JSON.stringify(sample_data, null, 2);
					cur_row.sample_count = sample_data_count;
					cur_row.sample_index = 0;
					// get the first object
					first_object = JSON.stringify(sample_data[0], null, 2);
					cur_row.sample_object = first_object;
					// refresh the form
					frm.refresh_field("shots");
					frappe.show_alert("Sample data updated");
				},
			});
		} catch (error) {
			console.error(error);
			console.log('error')
		}
	},
	next_sample: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		var index = cur_row.sample_index;
		const count = cur_row.sample_count;
		if (index < count - 1) {
			const sample_objects = JSON.parse(cur_row.sample_objects);
			index = index + 1;
			cur_row.sample_index = index;
			cur_row.sample_object = JSON.stringify(sample_objects[index], null, 2);
			// refresh the form
			frm.refresh_field("shots");
		}
	},
	previous_sample: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		var index = cur_row.sample_index;
		if (index > 0) {
			const sample_objects = JSON.parse(cur_row.sample_objects);
			index = index - 1;
			cur_row.sample_index = index;
			cur_row.sample_object = JSON.stringify(sample_objects[index], null, 2);
			// refresh the form
			frm.refresh_field("shots");
		}
	},
	get_references: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		const dt = cur_row.dt;
		frm.call({
			method: 'get_reference_docs',
			doc: frm.doc,
			args: {
				doctype: dt
			},
			callback: function (response) {
				const reference_docs = response.message || [];
				const reference_docs_count = reference_docs.length;
				// update the reference_docs field
				frappe.model.set_value(cdt, cdn, "reference_docs", JSON.stringify(reference_docs));
				frappe.model.set_value(cdt, cdn, "reference_count", reference_docs_count);
				frappe.model.set_value(cdt, cdn, "reference_index", 0);
				// get the first document
				first_doc = JSON.stringify(reference_docs[0], null, 2);
				frappe.model.set_value(cdt, cdn, "reference_doc", first_doc);
				frappe.show_alert("Reference docs updated");
				// refresh the form
				frm.refresh_field("shots");
			},
		});
	},
	next_reference: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		var index = cur_row.reference_index;
		const count = cur_row.reference_count;
		if (index < count - 1) {
			index = index + 1;
			const reference_docs = JSON.parse(cur_row.reference_docs);
			frappe.model.set_value(cdt, cdn, "reference_index", index);
			frappe.model.set_value(cdt, cdn, "reference_doc", reference_docs[index]);
			// refresh the form
			frm.refresh_field("shots");
		}
	},
	previous_reference: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		var index = cur_row.reference_index;
		if (index > 0) {
			index = index - 1;
			const reference_docs = JSON.parse(cur_row.reference_docs);
			frappe.model.set_value(cdt, cdn, "reference_index", index);
			frappe.model.set_value(cdt, cdn, "reference_doc", reference_docs[index]);
			// refresh the form
			frm.refresh_field("shots");
		}
	}
});

function open_template_generator_dialog(frm, doctype) {
	frm.call({
		method: 'get_doctype_fields',
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