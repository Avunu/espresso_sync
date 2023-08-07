import frappe
from jsonpath_ng import jsonpath, parse


def extract_dynamic_tag(tag, object, sync_connection, doc):
    """
    This function identifies the tag type and calls the respective handler function.
    :param tag: the entire tag string (e.g., "{doc:Selling Settings:default_price_list}")
    :param object: the data object that data will be fetched from
    :param sync_connection: the Espresso Sync Connection
    :param doc: the associated frappe doc as a dictionary (used for exporting)
    """
    # take the brackets off
    tag = tag[1:-1]
    tag_type = tag.split(':')[0]
    params = ":".join(tag.split(':')[1:])
    handlers = {
        "doc": doc_tag,
        # "docs": docs_tag,
        "link": link_tag,
        "id": id_tag,
    }
    if tag_type in handlers:
        try:
            return handlers[tag_type](params, object, sync_connection, doc)
        except Exception as e:
            frappe.log_error(f"Error handling dynamic tag {tag}: {e}")
            return None
    else:
        frappe.log_error(f"Unknown dynamic tag type {tag_type}")
        return None

def doc_tag(params, object, sync_connection, doc):
    """
    This function handles "doc" tags.
    Example: "{doc:Selling Settings:default_price_list}" - fetches the default price list from the Selling Settings doctype.
    """
    try:
        return frappe.db.get_single_value(params.split(":")[0], params.split(":")[1])
    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None

def docs_tag(params, object, sync_connection, doc):
    # Handle the dyno tag as a list of docs
    # Get the doctype from the dynamic tag
    doctype = params.split(':')[1]
    # dynamic_tag_doc_list = frappe.get_all(doctype="Espresso Sync ID", filters={'sync_connection': sync_connection.name, 'parenttype': doctype}, fields=['external_id'])

    # Get the list of doc names from the doctype
    try:
        doc_names = frappe.db.get_list(doctype, pluck='name', limit=10)
        # Get the list of external IDs from the Espresso Sync ID doctype
        return frappe.db.get_list('Espresso Sync ID', filters={'sync_connection': sync_connection.name, 'parenttype': doctype, 'parent': ['in', doc_names]}, fields=['external_id'])
    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None

def id_tag(params, object, sync_connection, doc):
    """
    This function handles "id" tags.
    Example: "{id:project}" - fetches the external ID of the linked doc in the project field.
    """
    try:
        return frappe.db.get_value(
            doctype="Espresso Sync ID",
            filters={'sync_connection': sync_connection.name,
                     'parent': doc[params]},
            fieldname="external_id"
        )
    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None

# TODO: Get rid of duplicate link_tag function

def link_tag(params, object, sync_connection, doc):
    """
    This function handles "link" tags.
    Example: "{link:Customer:$.clientId}" - fetches the name of the linked Customer doctype using the client ID.
    """
    try:
        doctype, id = params.split(":")
        jsonpath_expr = parse(id)
        matches = [match.value for match in jsonpath_expr.find(object)]
        if not matches:
            return None
        external_id = matches[0]
        # return the frappe doc whose espresso_sync_id matches the client ID for the sync connection
        return frappe.db.get_value(
            doctype="Espresso Sync ID",
            filters={'sync_connection': sync_connection.name,
                        'parenttype': doctype, 'external_id': external_id},
            fieldname="parent"
        )
    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None

def link_tag(params, object, sync_connection, doc):
    """
    This function handles "link" tags.
    Example: "{link:Customer:$.clientId}" - fetches the name of the linked Customer doctype using the client ID.
    """
    try:
        doctype, id = params.split(":")
        jsonpath_expr = parse(id)
        matches = [match.value for match in jsonpath_expr.find(object)]
        if not matches:
            return None
        external_id = matches[0]
        # return the frappe doc whose espresso_sync_id matches the client ID for the sync connection
        return frappe.db.get_value(
            doctype="Espresso Sync ID",
            filters={'sync_connection': sync_connection.name,
                        'parenttype': doctype, 'external_id': external_id},
            fieldname="parent"
        )
    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None
    
def id_tag(params, object, sync_connection, doc):
    """
    This function handles "id" tags.
    Example: "{id:project}" - fetches the external ID of the linked doc in the project field.
    """
    try:
        return frappe.db.get_value(
            doctype="Espresso Sync ID",
            filters={'sync_connection': sync_connection.name,
                     'parent': doc[params]},
            fieldname="external_id"        )

    except Exception as e:
        frappe.log_error(f"Error handling dynamic tag {params}: {e}")
        return None