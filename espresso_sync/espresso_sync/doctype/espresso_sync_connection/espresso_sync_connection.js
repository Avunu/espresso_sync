// Copyright (c) 2023, Avunu LLC and contributors
// For license information, please see license.txt

frappe.realtime.on("show_alert", function (data) {
	frappe.show_alert({
		message: data.message,
		indicator: data.indicator,
	});
});

frappe.realtime.on("import_progress", function (data) {
	// use show_progress
	frappe.show_progress("Processing " + data.doctype + "s", data.progress, data.total);
	// hide progress when complete
	if (data.progress == data.total) {
		frappe.hide_progress();
	}
});

frappe.ui.form.on("Espresso Sync Connection Shot", {
	form_render: function (frm, cdt, cdn) {
		var cur_row = locals[cdt][cdn];
		const dialog_form = frm.fields_dict.shots.grid.open_grid_row;
		// render the filter widget
		make_filter_widget(cur_row, dialog_form);
		// Add a buttons to the code editors
		add_editor_buttons(cur_row, dialog_form);
	},
	render_sample: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		object_map = cur_row.object_map_import;
		sample_object = cur_row.sample_object;
		if (object_map && sample_object) {
			// object_map = JSON.parse(object_map);
			// sample_object = JSON.parse(sample_object);
			frm.call({
				method: "render_sample",
				args: {
					object_map: object_map,
					sample_object: sample_object,
				},
				callback: function (response) {
					// show the sample in a frappe dialog
					const sample = response.message || {};
					const sample_formatted = JSON.stringify(sample, null, 2);
					frappe.msgprint({ message: "<pre>" + sample_formatted + "</pre>", title: "Sample Data" });
				},
			});
		}
	},
	test_import: function (frm, cdt, cdn) {
		cur_row = locals[cdt][cdn];
		if (!cur_row.sample_object) {
			cur_row.sample_object = "{}";
		}

		frm.call({
			method: "test_import",
			doc: frm.doc,
			args: {
				shot_name: cdn,
				sample_object: cur_row.sample_object,
			},
			callback: function (response) {
				// show the sample in a frappe dialog
				const sample = response.message || {};
				const sample_formatted = JSON.stringify(sample, null, 2);
				frappe.msgprint({ message: "<pre>" + sample_formatted + "</pre>", title: "Sample Import" });
			},
		});
	},
	get_samples: function (frm, cdt, cdn) {
		frappe.show_alert(__("Fetching sample data"));
		var cur_row = locals[cdt][cdn];
		try {
			frm.call({
				method: "get_sample_data",
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
					frappe.show_alert(__("Sample data updated"));
				},
			});
		} catch (error) {
			console.error(error);
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
			method: "get_reference_docs",
			doc: frm.doc,
			args: {
				doctype: dt,
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
				frappe.show_alert(__("Reference docs updated"));
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
			index++;
			const reference_docs = JSON.parse(cur_row.reference_docs);
			cur_row.reference_index = index;
			cur_row.reference_doc = JSON.stringify(reference_docs[index], null, 2);
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
			cur_row.reference_index = index;
			cur_row.reference_doc = JSON.stringify(reference_docs[index], null, 2);
			// refresh the form
			frm.refresh_field("shots");
		}
	},
});

// shot form filter widget for the export documents
function make_filter_widget(cur_row, dialog_form) {
	var doctype = cur_row.dt;
	var filters = cur_row.filters;
	if (dialog_form && doctype) {
		const filter_widget = dialog_form.fields_dict.filter_widget.$wrapper;
		frappe.model.with_doctype(doctype, () => {
			filter_widget.empty();
			// console.log(frm.fields_dict.shots.grid);
			this.filter_group = new frappe.ui.FilterGroup({
				parent: filter_widget,
				doctype: cur_row.dt,
				on_change: () => {
					this.filters = this.filter_group.get_filters();
					cur_row.filters = JSON.stringify(this.filters, null, 2);
					frm.refresh_field("shots");
					frm.dirty();
				},
			});
			if (filters) {
				this.filter_group.add_filters_to_filter_group(JSON.parse(filters));
			}
		});
	}
}

// helper function to add extra utility buttons to the code editors
function add_editor_buttons(cur_row, dialog_form) {
	const code_editors = ["object_map_import", "request_payload", "object_map_export"];
	// format code button
	code_editors.forEach((editor_name) => {
		const editor_field = dialog_form.fields_dict[editor_name];
		const $format_button = $('<button class="btn btn-xs btn-default">Format</button>');
		$format_button.click(() => editor_field.editor.autoIndent());
		editor_field.$input_wrapper.append($format_button);
	});
}
