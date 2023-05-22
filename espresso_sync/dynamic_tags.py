import frappe
from jsonpath_ng import jsonpath, parse


def tamp_dynamic_tag(tag, object, sync_connection, doc):
    """
    This function identifies the tag type and calls the respective handler function.
    :param tag: the entire tag string (e.g., "{doc:Selling Settings:default_price_list}")
    :param object: the data object that data will be fetched from
    :param sync_connection: the Espresso Sync Connection
    :param doc: the associated frappe doc as a dictionary (used for exporting)
    """
    # broken_tag = tag.split(':')
    tag_type = tag.split(':')[0]
    params = ":".join(tag.split(':')[1:])
    handlers = {
        "doc": doc_tag,
        "link": link_tag,
        "id": id_tag,
    }
    if tag_type in handlers:
        return handlers[tag_type](params, object, sync_connection, doc)

def doc_tag(params, object, sync_connection, doc):
    """
    This function handles "doc" tags.
    Example: "{doc:Selling Settings:default_price_list}" - fetches the default price list from the Selling Settings doctype.
    """
    return frappe.db.get_single_value(params.split(":")[0], params.split(":")[1])

def link_tag(params, object, sync_connection, doc):
    """
    This function handles "link" tags.
    Example: "{link:Customer:$.clientId}" - fetches the name of the linked Customer doctype using the client ID.
    """
    doctype, id = params.split(":")
    jsonpath_expr = parse(id)
    match = jsonpath_expr.find(object)[0].value
    return frappe.db.get_value(
        doctype="Espresso Sync ID",
        filters={'sync_connection': sync_connection.name,
                 'parenttype': doctype, 'external_id': match},
        fieldname="parent"
    )

def id_tag(params, object, sync_connection, doc):
    """
    This function handles "id" tags.
    Example: "{id:project}" - fetches the external ID of the linked doc in the project field.
    """
    return frappe.db.get_value(
        doctype="Espresso Sync ID",
        filters={'sync_connection': sync_connection.name,
                 'parent': doc[params]},
        fieldname="external_id"
    )