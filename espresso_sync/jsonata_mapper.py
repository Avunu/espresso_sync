import frappe
import json
import jsonata
from espresso_sync.dynamic_tags import extract_dynamic_tag


def extract_object_jsonata(object_map, object, sync_connection=None, doc=None):
    """
    JSONata-based object mapping function to replace the legacy extract_object function.
    
    This function supports two modes:
    1. JSONata expression mode: object_map is a string containing a JSONata expression
    2. Legacy compatibility mode: object_map is a dict with individual field mappings
    
    Args:
        object_map: Either a JSONata expression string or a dict mapping (legacy)
        object: Source data object to transform
        sync_connection: Espresso Sync Connection (for dynamic tags)
        doc: Associated frappe document (for dynamic tags)
    
    Returns:
        Transformed object according to the mapping rules
    """
    
    # Check for {condition} key and evaluate its list (legacy compatibility)
    if isinstance(object_map, dict) and "{condition}" in object_map:
        conditions = object_map.get('{condition}', [])
        for condition in conditions:
            # For conditions, we'll still use Jinja for backward compatibility
            test_result = frappe.render_template(condition, object)
            if not bool(test_result):
                return None
    
    # Mode 1: JSONata expression string
    if isinstance(object_map, str):
        return _evaluate_jsonata_expression(object_map, object, sync_connection, doc)
    
    # Mode 2: Legacy dict mapping (backward compatibility)
    elif isinstance(object_map, dict):
        return _process_legacy_mapping(object_map, object, sync_connection, doc)
    
    # Mode 3: List of mappings
    elif isinstance(object_map, list):
        results = []
        for item in object_map:
            result = extract_object_jsonata(item, object, sync_connection, doc)
            if result is not None:
                results.append(result)
        return results
    
    # For primitive values, return as-is
    else:
        return object_map


def _evaluate_jsonata_expression(expression, data, sync_connection=None, doc=None):
    """
    Evaluate a JSONata expression with support for dynamic tags.
    """
    try:
        # Pre-process the expression to handle dynamic tags
        processed_expression = _preprocess_dynamic_tags(expression, data, sync_connection, doc)
        
        # Execute JSONata expression
        jsonata_expr = jsonata.Jsonata(processed_expression)
        result = jsonata_expr.evaluate(data)
        
        return result
    except Exception as e:
        frappe.log_error(f"Error evaluating JSONata expression '{expression}': {e}")
        return None


def _preprocess_dynamic_tags(expression, data, sync_connection=None, doc=None):
    """
    Pre-process JSONata expressions to handle Espresso Sync dynamic tags.
    
    This function finds dynamic tags like {doc:Settings:field} and replaces them
    with their resolved values before JSONata evaluation.
    """
    import re
    
    # Find all dynamic tags in the expression
    dynamic_tag_pattern = r'(\{[^{}]*\})'
    
    def replace_dynamic_tag(match):
        tag = match.group(1)
        # Skip if it looks like a JSONata object constructor
        if tag.startswith('{"') or '":' in tag:
            return tag
        
        try:
            # Extract the dynamic tag value
            tag_value = extract_dynamic_tag(tag, data, sync_connection, doc)
            
            # Convert to JSON-safe string if needed
            if isinstance(tag_value, str):
                return json.dumps(tag_value)  # Properly escape for JSON
            else:
                return json.dumps(tag_value)
        except Exception as e:
            frappe.log_error(f"Error processing dynamic tag {tag}: {e}")
            return tag  # Return original if processing fails
    
    processed = re.sub(dynamic_tag_pattern, replace_dynamic_tag, expression)
    return processed


def _process_legacy_mapping(object_map, object, sync_connection=None, doc=None):
    """
    Process legacy-style object mappings for backward compatibility.
    This handles the old dict-based mapping format.
    """
    result = {}
    
    for key, value in object_map.items():
        # Skip condition keys as they're handled earlier
        if key == "{condition}":
            continue
            
        # Handle different value types
        if isinstance(value, (float, int)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = _process_legacy_string_value(value, object, sync_connection, doc)
        elif isinstance(value, dict):
            result[key] = _process_legacy_dict_value(key, value, object, sync_connection, doc)
        elif isinstance(value, list):
            result[key] = [extract_object_jsonata(item, object, sync_connection, doc) for item in value]
    
    return result


def _process_legacy_string_value(value, object, sync_connection=None, doc=None):
    """Process legacy string values (JSONPath, Jinja, dynamic tags)"""
    
    # JSONPath expression
    if value.startswith("$"):
        from espresso_sync.map_machine import extract_jsonpath
        return extract_jsonpath(value, object)
    
    # Dynamic tag
    elif value.startswith("{") and not value[1] in ["%", "#", "{"]:
        return extract_dynamic_tag(value, object, sync_connection, doc)
    
    # Numeric template (starts with #)
    elif value.startswith("#"):
        template_value = value[1:]  # remove the '#'
        template_result = frappe.render_template(template_value, object)
        return float(template_result) if '.' in template_result else int(template_result)
    
    # Jinja template
    else:
        return frappe.render_template(value, object)


def _process_legacy_dict_value(key, value, object, sync_connection=None, doc=None):
    """Process legacy dict values (match, foreach functions)"""
    
    # Match function
    if "match" in value:
        match_key = value["match"]["match-on"]
        match_value = object.get(match_key)
        cases = value["match"]["cases"]
        return cases.get(match_value)
    
    # Foreach function
    elif "foreach" in value:
        objects_key = value["foreach"]["objects"]
        nested_objects = object.get(objects_key, [])
        nested_object_map = value["foreach"]["map"]
        return [extract_object_jsonata(nested_object_map, obj, sync_connection, doc) for obj in nested_objects]
    
    # Regular nested mapping
    else:
        return extract_object_jsonata(value, object, sync_connection, doc)