import frappe
import re
import jsonata
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


def evaluate_jsonata(expression, data):
    """
    Evaluate a JSONata expression against the given data.
    Returns the result or None if evaluation fails.
    """
    try:
        expr = jsonata.Jsonata(expression)
        return expr.evaluate(data)
    except Exception as e:
        frappe.log_error(f"Error evaluating JSONata expression '{expression}': {e}")
        return None


def extract_object(object_map, object, sync_connection=None, doc=None):
    """
    Extract and transform object data using JSONata expressions.
    Supports mixed mode with Frappe dynamic tags for backward compatibility.
    """
    # Check for {condition} key and evaluate its list
    if "{condition}" in object_map:
        conditions = object_map.get('{condition}', [])
        for condition in conditions:
            # For backwards compatibility, still support Jinja conditions
            test_result = frappe.render_template(condition, object)
            if not bool(test_result):
                return None
    
    result = {}
    for key, value in object_map.items():
        # Skip condition key as it's already processed
        if key == "{condition}":
            continue
            
        # Handle simple value types
        if isinstance(value, (float, int, bool, type(None))):
            result[key] = value
            continue
            
        # Handle string values - this is where the main JSONata logic goes
        if isinstance(value, str):
            # Check if it's a Frappe dynamic tag (preserve for Frappe integration)
            if value.startswith("{") and not value[1] in ["%", "#", "{"]:
                result[key] = extract_dynamic_tag(value, object, sync_connection, doc)
            # Check if it's a legacy numeric template (for backwards compatibility)
            elif value.startswith("#"):
                template_value = value[1:]  # remove the '#'
                template_result = frappe.render_template(template_value, object)
                result[key] = float(template_result) if '.' in template_result else int(template_result)
            # Everything else is treated as a JSONata expression
            else:
                result[key] = evaluate_jsonata(value, object)
                
        # Handle dictionary values (nested objects or legacy function objects)
        elif isinstance(value, dict):
            # Check for legacy mapping functions for backward compatibility
            if "match" in value:
                # Legacy match function - convert to JSONata equivalent
                match_on = value["match"]["match-on"]
                cases = value["match"]["cases"]
                
                # Handle legacy JSONPath syntax by removing the '$.' prefix if present
                if match_on.startswith("$."):
                    match_on = match_on[2:]  # Remove '$.' prefix for JSONata
                
                # Extract the value to match on using JSONata
                match_value = evaluate_jsonata(match_on, object)
                result[key] = cases.get(str(match_value)) if match_value is not None else None
                
            elif "foreach" in value:
                # Legacy foreach function - convert to array processing
                objects_expr = value["foreach"]["objects"]
                nested_object_map = value["foreach"]["map"]
                
                # Handle legacy JSONPath syntax by removing the '$.' prefix if present
                if objects_expr.startswith("$."):
                    objects_expr = objects_expr[2:]  # Remove '$.' prefix for JSONata
                
                # Get the array using JSONata
                nested_objects = evaluate_jsonata(objects_expr, object)
                if isinstance(nested_objects, list):
                    result[key] = [extract_object(nested_object_map, obj, sync_connection, doc) for obj in nested_objects]
                else:
                    result[key] = []
                    
            else:
                # Regular nested object mapping
                result[key] = extract_object(value, object, sync_connection, doc)
                
        # Handle list values
        elif isinstance(value, list):
            result[key] = [extract_object(item, object, sync_connection, doc) for item in value]
            
    return result


# Helper function to evaluate a JSONPath expression
# DEPRECATED: This function is kept for backward compatibility only
# New code should use JSONata expressions instead
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