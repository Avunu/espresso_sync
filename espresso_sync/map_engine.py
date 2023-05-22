import frappe
import re
from jsonpath_ng import jsonpath, parse
from espresso_sync.dynamic_tags import tamp_dynamic_tag
from jinja2 import Template


# This function builds a list of all possible permutations of a parameter string based on dynamic tags in the string
def tamp_dynamic_parameter(parameter, shot, sync_connection, docs=[0]):
    finished_parameters = []
    # loop over exported docs (if any)
    # if no docs are passed, loop over a single empty dict
    for doc in docs:
        # Start with the original parameter
        half_roasted_parameters = [parameter]
        # finished_parameters = []
        while half_roasted_parameters:
            # Take the last parameter from the list
            parameter = half_roasted_parameters.pop()
            # Find the first dynamic parameter in the parameter string
            first_dynamic_tag = re.search(r'{(.*?)}', parameter)
            if first_dynamic_tag:
                # Get everything between the dynamic tag braces
                dynamic_tag = first_dynamic_tag.group(1)

                # debug
                frappe.publish_realtime('console.log', 'dynamic_tag:', user=frappe.session.user)
                frappe.publish_realtime('console.log', dynamic_tag, user=frappe.session.user)
                # end debug

                if dynamic_tag.startswith('id:'):
                    # Handle the dyno tag as a doc id
                    doc_id = tamp_dynamic_tag(dynamic_tag, None, sync_connection, doc)
                    new_parameter = parameter.replace(first_dynamic_tag.group(0), doc_id)
                    # Add the new parameter to the half_roasted_parameters list
                    half_roasted_parameters.append(new_parameter)
                elif dynamic_tag.startswith('docs:'):
                    # Handle the dyno tag as a list of docs
                    # Get the doctype from the dynamic tag
                    doctype = dynamic_tag.split(':')[1]
                    dynamic_tag_doc_list = frappe.get_all(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parenttype': doctype}, fields=['external_id'])
                    # Loop through the list of docs
                    for external_id in dynamic_tag_doc_list:
                        new_parameter = parameter.replace(first_dynamic_tag.group(0), external_id['external_id'])
                        # Add the new parameter to the half_roasted_parameters list
                        half_roasted_parameters.append(new_parameter)
                else:
                    # Handle the dyno tag as jinja
                    try:
                        # Replace the dynamic parameter with the value
                        # new_parameter = parameter.replace(first_dynamic_tag.group(0), frappe.render_template(dynamic_tag, shot.as_dict()))
                        new_parameter = parameter.replace(first_dynamic_tag.group(0), Template(dynamic_tag).render(shot.as_dict()))

                        # debug
                        frappe.publish_realtime('console.log', 'new_parameter:', user=frappe.session.user)
                        frappe.publish_realtime('console.log', new_parameter, user=frappe.session.user)
                        # end debug

                        # Add the new parameter to the half_roasted_parameters list
                        half_roasted_parameters.append(new_parameter)
                    except Exception as e:
                        frappe.publish_realtime('show_alert', {'message': f"Error rendering template: {e}", 'indicator': 'orange'}, user=frappe.session.user)
                        frappe.log_error(f"Error rendering template: {e}")
            # If there are no dynamic parameters, add the parameter to the finished_parameters list
            else:
                finished_parameters.append(parameter)
    
    # debug
    frappe.publish_realtime('console.log', 'finished_parameters:', user=frappe.session.user)
    frappe.publish_realtime('console.log', finished_parameters, user=frappe.session.user)
    # end debug

    return finished_parameters

def tamp_object_map(object_map, object, sync_connection=None, doc=None):
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
                result[key] = tamp_dynamic_tag(value, object, sync_connection, doc)
            else:
                result[key] = frappe.render_template(value, object)
        elif isinstance(value, dict):
            match key in value:
                # function dicts
                case "match":
                    match_key = value["match"]["match-on"]
                    match_value = object.get(match_key)
                    cases = value["match"]["cases"]
                    result[key] = cases.get(match_value)
                case "foreach":
                    objects_key = value["foreach"]["objects"]
                    nested_objects = object.get(objects_key, [])
                    nested_object_map = value["foreach"]["map"]
                    result[key] = [tamp_object_map(
                        nested_object_map, object) for object in nested_objects]
                # non-function dicts
                case _:
                    result[key] = value
        elif isinstance(value, list):
            result[key] = [tamp_object_map(
                item, object) for item in value]
    return result