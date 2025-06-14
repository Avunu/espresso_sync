# Espresso Sync Object Mapping Documentation

Espresso Sync provides a flexible way to map JSON objects from external systems to Frappe documents and vice versa. As of this version, Espresso Sync uses **JSONata** as its primary object mapping syntax, offering a powerful and standardized approach to data transformation.

## JSONata Expressions

JSONata is a lightweight query and transformation language for JSON data. It provides a comprehensive set of operators and functions for extracting, transforming, and reshaping JSON data.

### Basic Field Access

```json
{
  "customer_name": "billing.company",
  "project_name": "name"
}
```

### Conditional Logic

JSONata supports powerful conditional expressions using the ternary operator:

```json
{
  "customer": "billing.company ? billing.company : (billing.first_name & ' ' & billing.last_name)"
}
```

### Array Transformations

Transform arrays of objects with ease:

```json
{
  "items": "line_items.{
    'item_code': sku,
    'qty': quantity,
    'rate': price,
    'description': name
  }"
}
```

### Complete Object Transformation

You can define an entire object mapping as a single JSONata expression:

```json
{
  "customer_name": "billing.company ? billing.company : name",
  "customer_city": "billing.city",
  "total_items": "$count(line_items)",
  "items": "line_items.{
    'item_code': sku,
    'qty': quantity,
    'rate': price,
    'description': name
  }"
}
```

### String Operations

JSONata provides powerful string manipulation capabilities:

```json
{
  "full_name": "billing.first_name & ' ' & billing.last_name",
  "email_domain": "$substringAfter(email, '@')",
  "formatted_phone": "$replace(phone, /[^\d]/g, '')"
}
```

### Mathematical Operations

Perform calculations directly in your mappings:

```json
{
  "total_amount": "$sum(line_items.price)",
  "tax_amount": "subtotal * 0.08",
  "discount_percent": "$round((original_price - discounted_price) / original_price * 100, 2)"
}
```

### Filtering and Sorting

Filter and sort data as part of your transformation:

```json
{
  "high_value_items": "line_items[price > 20].{
    'item_code': sku,
    'price': price
  }",
  "sorted_items": "line_items^(>price).{
    'item_code': sku,
    'price': price
  }"
}
```

## Dynamic Tags (Legacy Support)

For backward compatibility, Espresso Sync still supports dynamic tags within JSONata expressions. These are enclosed in single curly brackets `{ }` and provide access to Frappe database values.

### Supported Dynamic Tags

- `{doc:Doctype:fieldname}` - Fetches a value from a single document
- `{id:linkfield}` - Gets the external ID of a linked document  
- `{link:Doctype:JSONataExpression}` - Finds a document by external ID
- `{link_value:linkfield:valuefield}` - Gets a field value from a linked document
- `{get_value:Doctype:fieldname:filters}` - Queries the database with filters

### Example with Dynamic Tags

```json
{
  "default_price_list": "{doc:Selling Settings:default_price_list}",
  "customer": "{link:Customer:billing.customer_id}",
  "project_id": "{id:project}"
}
```

### Combining JSONata with Dynamic Tags

```json
{
  "customer_info": "{link:Customer:billing.customer_id}",
  "line_items": "line_items.{
    'item_code': sku,
    'qty': quantity,
    'rate': price,
    'tax_rate': '{doc:Tax Settings:default_tax_rate}'
  }"
}
```

## Migration from Legacy Syntax

### Old Jinja Template Syntax

**Before:**
```json
{
  "customer": "{{ billing.company if billing.company else billing.first_name ~ ' ' ~ billing.last_name }}"
}
```

**After (JSONata):**
```json
{
  "customer": "billing.company ? billing.company : (billing.first_name & ' ' & billing.last_name)"
}
```

### Old JSONPath + Foreach Syntax

**Before:**
```json
{
  "items": {
    "foreach": {
      "objects": "$.line_items",
      "map": {
        "item_code": "$.sku",
        "qty": "$.quantity"
      }
    }
  }
}
```

**After (JSONata):**
```json
{
  "items": "line_items.{
    'item_code': sku,
    'qty': quantity
  }"
}
```

### Old Match Function Syntax

**Before:**
```json
{
  "status": {
    "match": {
      "match-on": "$.status",
      "cases": {
        "pending": "Draft",
        "processing": "To Deliver and Bill"
      }
    }
  }
}
```

**After (JSONata):**
```json
{
  "status": "status = 'pending' ? 'Draft' : 
             status = 'processing' ? 'To Deliver and Bill' : 
             'Unknown'"
}
```

## JSONata Resources

For comprehensive documentation on JSONata capabilities, visit:
- [JSONata Documentation](https://docs.jsonata.org/)
- [JSONata Exerciser](https://try.jsonata.org/) - Interactive playground for testing expressions
