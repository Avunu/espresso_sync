"""
Basic tests for JSONata functionality without Frappe dependencies
"""
import json
import jsonata


def test_jsonata_functionality():
    """Test basic JSONata expressions that we'll be using"""
    
    sample_data = {
        "name": "John Doe",
        "age": 30,
        "billing": {
            "company": "ACME Corp",
            "first_name": "John", 
            "last_name": "Doe",
            "address_1": "123 Main St",
            "city": "Boston",
            "country": "US"
        },
        "line_items": [
            {"sku": "ABC", "quantity": 2, "price": 10.50, "name": "Widget A"},
            {"sku": "DEF", "quantity": 1, "price": 25.00, "name": "Widget B"}
        ],
        "status": "processing"
    }
    
    print("Testing JSONata expressions...")
    print("Sample data:", json.dumps(sample_data, indent=2))
    print("\n" + "="*60 + "\n")

    # Test 1: Simple field access
    expr1 = jsonata.Jsonata("name")
    result1 = expr1.evaluate(sample_data)
    print(f"Test 1 - Simple field: {result1}")
    assert result1 == "John Doe", f"Expected 'John Doe', got {result1}"

    # Test 2: Nested field access  
    expr2 = jsonata.Jsonata("billing.company")
    result2 = expr2.evaluate(sample_data)
    print(f"Test 2 - Nested field: {result2}")
    assert result2 == "ACME Corp", f"Expected 'ACME Corp', got {result2}"

    # Test 3: Conditional logic
    expr3 = jsonata.Jsonata("billing.company ? billing.company : name")
    result3 = expr3.evaluate(sample_data)
    print(f"Test 3 - Conditional: {result3}")
    assert result3 == "ACME Corp", f"Expected 'ACME Corp', got {result3}"

    # Test 4: Array mapping
    expr4 = jsonata.Jsonata('line_items.{"item_code": sku, "qty": quantity, "rate": price}')
    result4 = expr4.evaluate(sample_data)
    print(f"Test 4 - Array mapping: {json.dumps(result4, indent=2)}")
    expected4 = [
        {"item_code": "ABC", "qty": 2, "rate": 10.50},
        {"item_code": "DEF", "qty": 1, "rate": 25.00}
    ]
    assert result4 == expected4, f"Array mapping failed"

    # Test 5: Complete object transformation (the key test)
    expr5 = jsonata.Jsonata('''
    {
      "customer_name": billing.company ? billing.company : (billing.first_name & " " & billing.last_name),
      "customer_city": billing.city,
      "total_items": $count(line_items),
      "items": line_items.{
        "item_code": sku,
        "qty": quantity,
        "rate": price,
        "description": name
      }
    }
    ''')
    
    result5 = expr5.evaluate(sample_data)
    print(f"Test 5 - Complete mapping: {json.dumps(result5, indent=2)}")
    
    expected5 = {
        "customer_name": "ACME Corp",
        "customer_city": "Boston", 
        "total_items": 2,
        "items": [
            {"item_code": "ABC", "qty": 2, "rate": 10.50, "description": "Widget A"},
            {"item_code": "DEF", "qty": 1, "rate": 25.00, "description": "Widget B"}
        ]
    }
    assert result5 == expected5, f"Complete mapping failed"

    # Test 6: String concatenation (replaces current Jinja template functionality)
    expr6 = jsonata.Jsonata('"Customer: " & (billing.company ? billing.company : (billing.first_name & " " & billing.last_name)) & " - " & billing.city')
    result6 = expr6.evaluate(sample_data)
    print(f"Test 6 - String concatenation: {result6}")
    assert result6 == "Customer: ACME Corp - Boston"

    print("\n" + "="*60)
    print("All tests passed! JSONata is working correctly.")
    return True


if __name__ == "__main__":
    test_jsonata_functionality()