import frappe
import re
from jsonpath_ng import jsonpath, parse
from espresso_sync.dynamic_tags import extract_dynamic_tag


# This function builds a list of all possible permutations of a parameter string based on dynamic tags in the string
def tamp_dynamic_parameter(parameter, shot, sync_connection, doc_names=[0]):
    finished_parameters = []
    # loop over exported docs (if any)
    # if no docs are passed, loop over a single empty dict
    i = 0
    for doc_name in doc_names:
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
                            frappe.publish_realtime('show_alert', {'message': f"No doc id found for {dynamic_tag.split(':')[1]} on {sync_connection.name} on {shot.dt} shot and {doc_name} doc.", 'indicator': 'orange'}, user=frappe.session.user)
                            frappe.log_error(f"No doc id found for {dynamic_tag.split(':')[1]} on {sync_connection.name} on {shot.dt} shot and {doc_name} doc.")
                    elif dynamic_tag.startswith('{docs:'):
                        # Handle the dyno tag as a list of docs
                        dynamic_tag = dynamic_tag[1:-1]
                        # Get the doctype from the dynamic tag
                        doctype = dynamic_tag.split(':')[1]
                        dynamic_tag_doc_list = frappe.get_all(doctype='Espresso Sync ID', filters={'sync_connection': sync_connection.name, 'parenttype': doctype}, fields=['external_id'])
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
                        # Get the doc data from the dynamic tag
                        if doc_name:
                            doc_data = frappe.get_doc(shot.dt, doc_name).as_dict()
                        else:
                            doc_data = {}
                        jinja_value = frappe.render_template(dynamic_tag, doc_data)
                        jinja_value = apply_quotes(jinja_value)
                        # Replace the dynamic parameter with the value
                        new_parameter = parameter.replace(first_dynamic_tag.group(0), jinja_value)
                        # Add the new parameter to the half_tamped_parameters list
                        half_tamped_parameters.append(new_parameter)
                    except Exception as e:
                        frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
                        frappe.log_error(f"Error rendering template: {e} for dynamic tag: {dynamic_tag} on shot {shot.dt} and doc {doc_name}")
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
     # 1. Check for {condition} key and evaluate its list
    if "{condition}" in object_map:
        conditions = object_map.get('{condition}', [])
        for condition in conditions:
            test_result = frappe.render_template(condition, object)
            if not bool(test_result):
                return None
    result = {}
    for key, value in object_map.items():
        # if it's a float or int, just return it
        if isinstance(value, float) or isinstance(value, int):
            result[key] = value
        # if it's a string, process it
        if isinstance(value, str):
            # check if the value is a JSONPath expression
            if value.startswith("$"):
                result[key] = extract_jsonpath(value, object)
            # detect dynamic tags as single-bracketed strings (exclude jinja delimiters)
            elif value.startswith("{") and not value[1] in ["%", "#", "{"]:
                # process it as a dynamic tag
                result[key] = extract_dynamic_tag(value, object, sync_connection, doc)
            else:
                # check if the template should be numeric (starts with #)
                if value.startswith("#"):
                    template_value = value[1:]  # remove the '#'
                    template_result = frappe.render_template(template_value, object)
                    result[key] = float(template_result) if '.' in template_result else int(template_result)
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


# Helper function to evaluate a JSONPath expression
def extract_jsonpath(expression, data):
    # Handle JSONPath expression with the || operator
    if "||" in expression:
        expressions = expression.split("||")
        for expr in expressions:
            trimmed_expr = expr.strip()
            if not trimmed_expr.startswith("$"):
                return trimmed_expr
            result = extract_jsonpath(trimmed_expr, data)
            if result:
                return result # Return the first non-empty result
    result = []
    jsonpath_expr = parse(expression)
    for match in jsonpath_expr.find(data):
        result.append(match.value)
    if len(result):
        return result[0]
    return ''