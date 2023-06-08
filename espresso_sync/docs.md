# Espresso Sync Object Mapping Documentation

Espresso Sync provides a flexible way to map JSON objects from external systems to Frappe documents and vice versa. It uses three types of expressions - Jinja templates, JSONPath expressions, and Espresso Sync Dynamic Tags - along with Mapping Functions to provide a wide range of possibilities.

## Jinja Templates

Jinja templates are enclosed in double curly brackets `{{ }}`. They are a powerful tool for dynamic data processing, allowing for conditional formatting, evaluation of expressions, and even some mathematical operations.

### Basic Example

```json
"customer": "{{ billing.company if billing.company else billing.first_name ~ ' ' ~ billing.last_name }}-{{ billing.city }}"
```

In this example, if `billing.company` is present, it's used as the customer's name. Otherwise, the first and last name from `billing` are concatenated with a space in between. The result is then appended with a '-' and the `billing.city`.

### Mathematical Operations

Jinja templates support basic mathematical operations. For example, multiplying a variable by 100:

```json
"amount": "{{ billing_rate * 100 }}"
```

In this case, the value of `billing_rate` is multiplied by 100 before it's assigned to the `amount`.

### Returning Numbers

To return a number instead of a string from a Jinja template, you can use a '#' at the beginning of your template:

```json
"amount": "#{{ billing_rate * 100 if billing_rate else 0 | int }}"
```

In this case, the `#` symbol is a special indicator that tells the system to treat the result of the template as a number. If `billing_rate` is present, it's multiplied by 100, and the result is returned as an integer number due to the `int` filter. If `billing_rate` is not present, 0 is returned.

### Formatting

You can also use Jinja templates to format values. For example, to format a number as a floating-point number with two decimal places:

```json
"amount": "{{ '%.2f'|format(billing_rate) }}"
```

In this example, `billing_rate` is formatted as a floating-point number with two decimal places. The `format` filter applies the specified string formatting to `billing_rate`.

Jinja templates can be a powerful tool in formatting and manipulating your data before export. Their flexibility allows you to handle a wide range of scenarios in data processing.

## JSONPath Expressions

JSONPath expressions allow for navigating the object tree and they start with a `$`.

```json
"project_name": "$.name"
```

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
