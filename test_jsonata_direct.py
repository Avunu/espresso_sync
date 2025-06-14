"""
Direct test of the JSONata mapper functionality
"""
import json
import sys
import os

# Mock frappe module
class MockFrappe:
    @staticmethod
    def log_error(msg):
        print(f"LOG ERROR: {msg}")
    
    @staticmethod
    def render_template(template, data):
        # Simple mock - return template with data interpolation
        if "billing.city" in template:
            return "Boston"
        return template

sys.modules['frappe'] = MockFrappe()

# Mock the extract_dynamic_tag function
def mock_extract_dynamic_tag(tag, object, sync_connection, doc):
    # Simple mock for testing
    if tag == "{doc:Settings:field}":
        return "mock_value"
    return tag

sys.modules['espresso_sync.dynamic_tags'] = type('MockModule', (), {
    'extract_dynamic_tag': mock_extract_dynamic_tag
})()

# Mock jsonpath_ng
class MockJsonPath:
    @staticmethod
    def parse(expression):
        return MockJsonPathExpr(expression)

class MockJsonPathExpr:
    def __init__(self, expr):
        self.expr = expr
    
    def find(self, data):
        # Simple mock for $.name
        if self.expr == "$.name":
            return [type('Match', (), {'value': data.get('name', '')})()]
        return [type('Match', (), {'value': ''})()]

sys.modules['jsonpath_ng'] = MockJsonPath()
sys.modules['jsonpath_ng.jsonpath'] = MockJsonPath()
sys.modules['jsonpath_ng.parse'] = MockJsonPath.parse

# Now import and test our JSONata mapper directly
import jsonata


def test_direct_jsonata():
    """Test JSONata mapper directly without complex dependencies"""
    
    # Import here after mocking
    from espresso_sync.jsonata_mapper import extract_object_jsonata
    
    sample_data = {
        "name": "John Doe",
        "billing": {
            "company": "ACME Corp",
            "city": "Boston"
        },
        "line_items": [
            {"sku": "ABC", "quantity": 2, "price": 10.50, "name": "Widget A"},
            {"sku": "DEF", "quantity": 1, "price": 25.00, "name": "Widget B"}
        ]
    }
    
    print("Testing JSONata mapper directly...")
    print("Sample data:", json.dumps(sample_data, indent=2))
    print("\n" + "="*60 + "\n")

    # Test 1: Pure JSONata expression
    jsonata_expression = '''
    {
      "customer": billing.company ? billing.company : name,
      "location": billing.city,
      "total_items": $count(line_items),
      "items": line_items.{
        "code": sku,
        "qty": quantity,
        "rate": price,
        "description": name
      }
    }
    '''
    
    result1 = extract_object_jsonata(jsonata_expression, sample_data)
    print("Test 1 - JSONata expression result:")
    print(json.dumps(result1, indent=2))
    
    expected_keys = ["customer", "location", "total_items", "items"]
    for key in expected_keys:
        assert key in result1, f"Missing key {key} in result"
    
    assert result1["customer"] == "ACME Corp", f"Expected 'ACME Corp', got {result1['customer']}"
    assert result1["location"] == "Boston", f"Expected 'Boston', got {result1['location']}"
    assert result1["total_items"] == 2, f"Expected 2, got {result1['total_items']}"
    assert len(result1["items"]) == 2, f"Expected 2 items, got {len(result1['items'])}"
    
    print("✓ JSONata expression test passed!")

    # Test 2: Legacy-style mapping
    legacy_mapping = {
        "project_name": "John Doe",  # Will be processed as a literal since no special syntax
        "customer_city": "Boston"    # Same here
    }
    
    result2 = extract_object_jsonata(legacy_mapping, sample_data)
    print("\nTest 2 - Legacy mapping result:")
    print(json.dumps(result2, indent=2))
    print("✓ Legacy mapping test completed!")

    print("\n" + "="*60)
    print("Direct JSONata mapper tests completed successfully!")
    return True


if __name__ == "__main__":
    test_direct_jsonata()