---
title: Object maps
description: The JSON maps a shot uses to turn API objects into documents and back, with JSONata expressions and Frappe tags.
nav_title: Object maps
order: 1
updated: 2026-11-07
---

Espresso Sync uses **JSONata** as the primary object mapping syntax, providing powerful and flexible data transformation capabilities. JSONata is an industry-standard query and transformation language for JSON data, offering advanced features for filtering, aggregation, and complex data manipulations.

## What is JSONata?

JSONata is a lightweight query and transformation language for JSON data. It provides:

- **Powerful expressions** for data extraction and transformation
- **Built-in functions** for string, numeric, array, and date operations
- **Conditional logic** for complex business rules
- **Advanced filtering** and aggregation capabilities
- **Standardized syntax** that's well-documented and widely adopted

## How a value is read

- A key whose expression gives nothing (JSONata's _undefined_, for a field the object lacks) is left out of the result, so an update leaves that field as it is. An expression that gives `null` sets the field to empty.
- An expression that fails to parse or to evaluate is recorded in the Error Log and its key is left out too.
- Each evaluation may take at most 5 seconds and nest at most 200 levels deep; past that it fails with the JSONata error D1012 or D1011.

## Basic JSONata Syntax

### Simple Field Access

Access fields using dot notation:

```json
{
	"customer_name": "billing.company",
	"city": "billing.city"
}
```

### Conditional Logic

JSONata provides powerful conditional expressions that replace Jinja templates:

```json
{
	"customer": "billing.company ? billing.company : (billing.first_name & ' ' & billing.last_name)",
	"display_name": "name ? name : 'Unknown Customer'"
}
```

### String Operations

JSONata includes comprehensive string manipulation:

```json
{
	"full_name": "first_name & ' ' & last_name",
	"email_domain": "$substringAfter(email, '@')",
	"formatted_phone": "$replace(phone, /[^0-9]/g, '')"
}
```

## Array Operations

JSONata excels at array transformations, replacing the need for separate `foreach` functions:

### Array Transformation

Transform arrays of objects in a single expression:

```json
{
	"items": "line_items.{'code': sku, 'qty': quantity, 'total': price * quantity}"
}
```

### Filtering and Aggregation

Filter arrays and perform calculations:

```json
{
	"high_value_items": "line_items[price > 100].{'sku': sku, 'value': price * quantity}",
	"total_value": "$sum(line_items.(price * quantity))",
	"item_count": "$count(line_items)"
}
```

### Advanced Array Operations

```json
{
  "unique_categories": "$distinct(line_items.category)",
  "sorted_items": "line_items^(>price).{'name': name, 'price': price}",
  "grouped_by_category": "$map($distinct(line_items.category), function($cat) {
    {'category': $cat, 'items': line_items[category = $cat]}
  })"
}
```

## Conditional Mapping

JSONata's conditional syntax replaces the legacy `match` function:

### Simple Mapping

```json
{
	"status": "status = 'pending' ? 'Draft' : status = 'processing' ? 'To Deliver and Bill' : status = 'completed' ? 'Delivered and Billed' : 'Cancelled'"
}
```

### Complex Conditions

```json
{
	"priority": "total_value > 1000 ? 'High' : total_value > 500 ? 'Medium' : 'Low'",
	"shipping_method": "weight > 50 or total_value > 100 ? 'Express' : 'Standard'"
}
```

## Advanced Features

### Mathematical Operations

```json
{
	"discounted_price": "price * (1 - discount_rate)",
	"tax_amount": "$round(subtotal * tax_rate, 2)",
	"profit_margin": "$round((selling_price - cost_price) / selling_price * 100, 2)"
}
```

### Date and Time Operations

```json
{
	"formatted_date": "$now() ~> $toMillis() ~> $fromMillis('[Y0001]-[M01]-[D01]')",
	"days_since_order": "$floor(($now() - $toMillis(order_date)) / 86400000)"
}
```

### Complex Business Logic

```json
{
	"order_tier": "total_value > 500 ? 'premium' : 'standard'",
	"eligible_for_discount": "$count(line_items) >= 3 and total_value > 200",
	"recommended_items": "line_items[category = 'electronics'].related_products[price < 50]"
}
```

## Mixed Mode: JSONata + Dynamic Tags

Espresso Sync supports a mixed mode where JSONata handles data transformations while Frappe Dynamic Tags provide database integration:

### Frappe Dynamic Tags

Dynamic tags are preserved for Frappe-specific operations:

```json
{
	"customer": "{link:Customer:$.customer_id}",
	"default_price_list": "{doc:Selling Settings:default_price_list}",
	"project_external_id": "{id:project}",
	"customer_email": "{link_value:customer:email_id}"
}
```

### Combined Example

Mix JSONata expressions with dynamic tags:

```json
{
	"customer": "{link:Customer:$.customer_id}",
	"customer_display": "billing.company ? billing.company : (billing.first_name & ' ' & billing.last_name)",
	"items": "line_items.{'item_code': sku, 'qty': quantity, 'rate': price}",
	"total_amount": "$sum(line_items.(price * quantity))",
	"default_warehouse": "{doc:Stock Settings:default_warehouse}"
}
```

## Migration Guide

### From Jinja Templates

**Before (Jinja):**

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

### From JSONPath + Foreach

**Before (JSONPath + Foreach):**

```json
{
	"items": {
		"foreach": {
			"objects": "$.line_items",
			"map": {
				"item_code": "$.sku",
				"qty": "$.quantity",
				"total": "#{{ price * quantity }}"
			}
		}
	}
}
```

**After (JSONata):**

```json
{
	"items": "line_items.{'item_code': sku, 'qty': quantity, 'total': price * quantity}"
}
```

### From Match Function

**Before (Match Function):**

```json
{
	"status": {
		"match": {
			"match-on": "$.status",
			"cases": {
				"pending": "Draft",
				"processing": "To Deliver and Bill",
				"completed": "Delivered and Billed"
			}
		}
	}
}
```

**After (JSONata):**

```json
{
	"status": "status = 'pending' ? 'Draft' : status = 'processing' ? 'To Deliver and Bill' : status = 'completed' ? 'Delivered and Billed' : 'Unknown'"
}
```

## Benefits of JSONata

1. **Standardized**: Industry-standard syntax with comprehensive documentation
2. **Powerful**: Advanced transformations, filtering, and aggregation in single expressions
3. **Maintainable**: Clear, readable syntax that's easier to debug and modify
4. **Comprehensive**: Built-in functions for common operations eliminate custom code
5. **Future-proof**: Well-maintained open standard with active community

## JSONata Functions Reference

### String Functions

- `$string()` - Convert to string
- `$length()` - String length
- `$substring()` - Extract substring
- `$replace()` - Replace text using regex
- `$split()` - Split string into array
- `$join()` - Join array into string

### Array Functions

- `$count()` - Count array elements
- `$sum()` - Sum numeric values
- `$max()` / `$min()` - Find maximum/minimum
- `$average()` - Calculate average
- `$distinct()` - Remove duplicates
- `$sort()` - Sort array

### Numeric Functions

- `$number()` - Convert to number
- `$round()` - Round to decimal places
- `$floor()` / `$ceiling()` - Round down/up
- `$abs()` - Absolute value

### Date Functions

- `$now()` - Current timestamp
- `$toMillis()` - Convert to milliseconds
- `$fromMillis()` - Format from milliseconds

For complete documentation, see [JSONata.org](https://docs.jsonata.org/).

## Backward Compatibility

Legacy mapping functions (`match`, `foreach`) are still supported for migration purposes, but new mappings should use JSONata syntax for better performance and maintainability.
