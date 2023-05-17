def permutation_builder(url, shot):
    # get the parent sync connection
    sync_connection = frappe.get_doc("Espresso Sync Connection", shot.sync_connection)
    # get the api domain, api base, and headers
    api_domain = sync_connection.api_domain
    api_base = sync_connection.api_base
    headers = get_request_headers(sync_connection)
    # get the uri
    uri = shot.uri
    # get the payload
    payload = shot.request_payload

    dyno_params = {
        "url_dynos": [],
        "api_base_dynos": [],
        "uri_dynos": [],
    }

    potential_dynamic_string_parameters = {
        # get the override fields: override_url, override_api_base, override_uris
        "overridden_url": shot.url,
        "overridden_api_base": shot.api_base,
        "overridden_get_uri": shot.get_uri,
        "overridden_post_uri": shot.post_uri,
        "overridden_put_uri": shot.put_uri,
        "overridden_delete_uri": shot.delete_uri,
    }
    # for each item in potential_dynamic_parameters, check if it is set. If it is, generate variations
    for key in potential_dynamic_parameters:
        if potential_dynamic_parameters[key]:
            dynamic_parameters = []
            # look for parts of the string that start with { and end with }
            if re.search(r'{(.*?)}', potential_dynamic_parameters[key]):
                # if there are any, get them all
                findall = re.findall(r'{(.*?)}', potential_dynamic_parameters[key])
                # for each one, check if it starts with doc: or id:
                # fetch single doc values from db if string starts with "doc:"
                # such as "doc:Selling Settings:default_price_list"
                # fetch external id of linked doc if string starts with "id:"
                # such as "id:project"
                # otherwise do nothing
                for match in findall:
                    if match.startswith('doc:'):
                        # get the doctype and field name
                        parts = match.split(':')
                        doctype = parts[1]
                        field = parts[2]
                        # get the doc
                        doc = frappe.get_doc(doctype, shot[field])
                        # get the value of the field
                        value = doc[field]
                        # add the value to the dynamic_parameters dict
                        dynamic_parameters.append(value)
                    elif match.startswith('id:'):
                        # get the doctype
                        doctype = match.split(':')[1]
                        # get the external id
                        external_id = frappe.get_value(doctype, shot[doctype], 'external_id')
                        # add the external id to the dynamic_parameters dict
                        dynamic_parameters.append(external_id)
                    else:
                        # do nothing
                        pass