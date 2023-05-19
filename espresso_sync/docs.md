# Espresso Sync Object Mapping Documentation

Espresso Sync provides a flexible way to map JSON objects from external systems to Frappe documents and vice versa. It uses three types of expressions - Jinja templates, JSONPath expressions, and Espresso Sync Dynamic Tags - along with Mapping Functions to provide a wide range of possibilities.

## Jinja Templates

Jinja templates are enclosed in double curly brackets `{{ }}` and they allow for conditional formatting and evaluation of expressions.

```json
"customer": "{{ billing.company if billing.company else billing.first_name ~ ' ' ~ billing.last_name }}-{{ billing.city }}"
```

## JSONPath Expressions

JSONPath expressions allow for navigating the object tree and they start with a `$`.

```json
"woocommerce_id": "$.id"
```

Sure, here are the detailed specifications for the Mapping Functions.

---

## Mapping Functions

Mapping Functions provide additional transformation and extraction capabilities, beyond the built-in mechanisms provided by Jinja templates and JSONPath expressions. Currently, Espresso Sync supports two mapping functions: `match` and `foreach`.

### Match Function

The `match` function matches an input value (specified by a JSONPath expression) with one of the predefined cases and returns the corresponding output.

Here's a breakdown of its structure:

- `match`: The main function identifier.

- `match-on`: A JSONPath expression that points to the value to be matched.

- `cases`: A dictionary of possible input values (keys) and their corresponding output values (values).

```json
"status": {
  "match": {
    "match-on": "$.status",
    "cases": {
      "pending": "Draft",
      "processing": "To Deliver and Bill",
      "completed": "Delivered and Billed",
      "canceled": "Cancelled",
      "refunded": "Refunded",
      "failed": "Cancelled"
    }
  }
}
```

In this example, the `match` function uses the value from `$.status` and translates it to a corresponding status in the Frappe system based on the provided cases.

### Foreach Function

The `foreach` function iterates over an array of objects (specified by a JSONPath expression) and maps each object based on the provided map.

Here's a breakdown of its structure:

- `foreach`: The main function identifier.

- `objects`: A JSONPath expression that points to the array of objects to iterate over.

- `map`: A dictionary that describes how each object in the array should be mapped.

```json
"items": {
  "foreach": {
    "objects": "$.line_items",
    "map": {
      "item_code": "{{ sku if sku else variation_id if variation_id else product_id }}",
      "qty": "$.quantity",
      "rate": "$.price",
      "description": "$.name"
    }
  }
}
```

In this example, the `foreach` function iterates over the array from `$.line_items` and for each item in the array, it creates a new object with properties `item_code`, `qty`, `rate`, and `description` mapped as described in the `map`.


## Espresso Sync Dynamic Tags

Espresso Sync dynamic tags are enclosed in single curly brackets `{ }` and provide a way to fetch data directly from Frappe database or linked documents.

- `doc`: Fetches a single document value from the database. The format is `{doc:Doctype:fieldname}` where `Doctype` is the document type and `fieldname` is the field of the document to fetch.

```json
"default_price_list": "{doc:Selling Settings:default_price_list}"
```

- `id`: Fetches the external ID of a linked document. The format is `{id:fieldname}` where `fieldname` is the name of the link field connecting the current document to a related document.

```json
"project_id": "{id:project}"
```

- `link`: Fetches the linked document name based on its external ID. The format is `{link:Doctype:JSONPath}` where `Doctype` is the document type and `JSONPath` is the JSONPath expression to find the external ID in the object.

```json
"customer": "{link:Customer:$.clientId}"
```
