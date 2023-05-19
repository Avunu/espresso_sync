# DEPRECATED
def generate_id_variations(sync_connection, dynamic_id_fields):
    is_string = False
    # first, check if it's a string
    if isinstance(dynamic_id_fields, str):
        is_string = True
        # convert the string to a dict based on the / delimiter
        parts = dynamic_id_fields.split('/')[1:]
        dynamic_id_fields = {parts[i]: parts[i + 1]
                             for i in range(0, len(parts), 2)}
    # generate all combinations of IDs
    dynamic_id_replacements = {}
    for key in dynamic_id_fields:
        if dynamic_id_fields[key].startswith('docs:'):
            doctype = dynamic_id_fields[key].split(':')[1]
            # Query for the IDs - USE THIS FOR PERMUTATION BUILDER
            ids = frappe.get_list(
                'Espresso Sync ID',
                filters={'parenttype': doctype,
                         'sync_connection': sync_connection.name},
                fields=['external_id']
            )
            # Store the IDs for replacement
            dynamic_id_replacements[key] = [id['external_id'] for id in ids]

    # Generate all combinations of IDs
    combinations = list(itertools.product(*dynamic_id_replacements.values()))

    # For each combination, replace the IDs in the payload and run the import step
    variations = []
    for combination in combinations:
        dynamic_id_value = dynamic_id_fields.copy()
        for key, value in zip(dynamic_id_replacements.keys(), combination):
            dynamic_id_value[key]['ids'] = [value]
        # add the variation to a list
        if is_string:
            variations.append('/'.join(dynamic_id_value))
        else:
            variations.append(dynamic_id_value)

    return variations