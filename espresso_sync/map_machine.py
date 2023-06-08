import frappe
import re
from jsonpath_ng import jsonpath, parse
from espresso_sync.dynamic_tags import extract_dynamic_tag


# This function builds a list of all possible permutations of a parameter string based on dynamic tags in the string
def tamp_dynamic_parameter(parameter, shot, sync_connection, docs=[0]):
    finished_parameters = []
    # loop over exported docs (if any)
    # if no docs are passed, loop over a single empty dict
    i = 0
    for doc in docs:
        # Start with the original parameter
        half_tamped_parameters = [parameter]
        while half_tamped_parameters and i < 1000:
            i += 1
            # Take the last parameter from the list
            parameter = half_tamped_parameters.pop()
            # Find the first dynamic parameter in the parameter string
            # first_dynamic_tag = re.search(r'{(.*?)}', parameter)
            first_dynamic_tag = re.search(r"(\{[i|d|l|{|#|%].*\})", parameter)
            # first_dynamic_tag = re.search(r'\"(\{.*\})\"', parameter)
            
            if first_dynamic_tag:
                # Get everything between the inner curly braces
                dynamic_tag = first_dynamic_tag.group(1)
                # check if the dynamic tag is a single bracketed string (exclude jinja delimiters)
                if dynamic_tag.startswith('{') and not dynamic_tag[1] in ["%", "#", "{"]:
                    if dynamic_tag.startswith('{id:'):
                        # Handle the dyno tag as a doc id
                        doc_id = extract_dynamic_tag(dynamic_tag, None, sync_connection, doc)
                        if doc_id:
                            doc_id = apply_quotes(doc_id)
                            new_parameter = parameter.replace(first_dynamic_tag.group(0), doc_id)
                            # Add the new parameter to the half_tamped_parameters list
                            half_tamped_parameters.append(new_parameter)
                        else:
                            frappe.publish_realtime('show_alert', {'message': f"No doc id found for {dynamic_tag.split(':')[1]} on {sync_connection.name} on {shot.dt} shot and {doc.name} doc.", 'indicator': 'orange'}, user=frappe.session.user)
                            frappe.log_error(f"No doc id found for {dynamic_tag.split(':')[1]} on {sync_connection.name} on {shot.dt} shot and {doc.name} doc.")
                    elif dynamic_tag.startswith('{docs:'):
                        # Handle the dyno tag as a list of docs
                        dynamic_tag = dynamic_tag[1:-1]
                        # Get the doctype from the dynamic tag
                        doctype = dynamic_tag.split(':')[1]
                        dynamic_tag_doc_list = frappe.get_all(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parenttype': doctype}, fields=['external_id'])
                        # dynamic_tag_doc_list = extract_dynamic_tag(dynamic_tag, None, sync_connection, doc)
                        # Loop through the list of docs
                        if dynamic_tag_doc_list:
                            for external_id in dynamic_tag_doc_list:
                                external_id['external_id'] = apply_quotes(external_id['external_id'])
                                new_parameter = parameter.replace(first_dynamic_tag.group(0), external_id['external_id'])
                                # Add the new parameter to the half_tamped_parameters list
                                half_tamped_parameters.append(new_parameter)
                        else:
                            frappe.publish_realtime('show_alert', {'message': f"No docs found for {sync_connection.name}", 'indicator': 'orange'}, user=frappe.session.user)
                            frappe.log_error(f"No docs found for {sync_connection.name}")
                else:
                    # Handle the dyno tag as jinja
                    try:
                        jinja_value = frappe.render_template(dynamic_tag)
                        jinja_value = apply_quotes(jinja_value)
                        # Replace the dynamic parameter with the value
                        new_parameter = parameter.replace(first_dynamic_tag.group(0), jinja_value)
                        # Add the new parameter to the half_tamped_parameters list
                        half_tamped_parameters.append(new_parameter)
                    except Exception as e:
                        frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
                        frappe.log_error(f"Error rendering template: {e}")
            # If there are no dynamic parameters, add the parameter to the finished_parameters list
            else:
                finished_parameters.append(parameter)
            if i > 1000:
                frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
                frappe.log_error(f"Error rendering template: {e}")
    return finished_parameters

def apply_quotes(value):
    if isinstance(value, str):
        if not value.startswith('"') and not value.endswith('"'):
            value = '"' + value + '"'
    return value

def extract_object(object_map, object, sync_connection=None, doc=None):
    result = {}
    for key, value in object_map.items():
        if isinstance(value, str):
            # check if the value is a JSONPath expression
            if value.startswith("$"):
                jsonpath_expr = parse(value)
                match = jsonpath_expr.find(object)
                if match:
                    result[key] = match[0].value
                else:
                    result[key] = None
            # detect dynamic tags as single-bracketed strings (exclude jinja delimiters)
            elif value.startswith("{") and not value[1] in ["%", "#", "{"]:
                # process it as a dynamic tag
                result[key] = extract_dynamic_tag(value, object, sync_connection, doc)
            else:
                # process it as a jinja template 
                result[key] = frappe.render_template(value, object)
        elif isinstance(value, dict):
            for key in object_map:
                value = object_map[key]
                if isinstance(value, dict):
                    # function dicts
                    if "match" in value:
                        match_key = value["match"]["match-on"]
                        match_value = object.get(match_key)
                        cases = value["match"]["cases"]
                        result[key] = cases.get(match_value)
                    elif "foreach" in value:
                        objects_key = value["foreach"]["objects"]
                        nested_objects = object.get(objects_key, [])
                        nested_object_map = value["foreach"]["map"]
                        result[key] = [extract_object(nested_object_map, obj, sync_connection, doc) for obj in nested_objects]
                    # non-function dicts, pass through to extract_object
                    else:
                        result[key] = extract_object(value, object, sync_connection, doc)
                elif isinstance(value, list):
                    result[key] = [extract_object(item, object, sync_connection, doc) for item in value]
    return result