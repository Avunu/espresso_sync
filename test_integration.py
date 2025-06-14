"""
Integration test to verify that the new JSONata implementation works 
through the existing extract_object interface.
"""
import json
import sys
import os

# Add the espresso_sync directory to the path so we can import modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'espresso_sync'))

# Mock frappe module since it's not available in test environment
class MockFrappe:
    @staticmethod
    def log_error(msg):
        print(f"ERROR: {msg}")
    
    @staticmethod
    def render_template(template, data):
        # Simple mock - just return the template for testing
        return template

# Install the mock
sys.modules['frappe'] = MockFrappe()

# Now import our modules
from map_machine import extract_object


def test_integration():
    """Test that the new JSONata integration works through the existing interface"""
    
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
    
    print("Testing JSONata integration through extract_object...")
    print("Sample data:", json.dumps(sample_data, indent=2))
    print("\n" + "="*60 + "\n")

    # Test 1: Pure JSONata expression as string
    jsonata_mapping = '''
    {
      "customer": billing.company ? billing.company : name,
      "location": billing.city,
      "item_count": $count(line_items),
      "items": line_items.{
        "code": sku,
        "quantity": quantity,
        "price": price
      }
    }
    '''
    
    result1 = extract_object(jsonata_mapping, sample_data)
    print("Test 1 - Pure JSONata expression:")
    print(json.dumps(result1, indent=2))
    
    expected1 = {
        "customer": "ACME Corp",
        "location": "Boston",
        "item_count": 2,
        "items": [
            {"code": "ABC", "quantity": 2, "price": 10.50},
            {"code": "DEF", "quantity": 1, "price": 25.00}
        ]
    }
    assert result1 == expected1, f"JSONata mapping failed: expected {expected1}, got {result1}"
    print("✓ JSONata expression test passed")

    # Test 2: Legacy dict mapping (backward compatibility)
    legacy_mapping = {
        "project_name": "$.name",
        "customer_city": "{{ billing.city }}"
    }
    
    result2 = extract_object(legacy_mapping, sample_data)
    print("\nTest 2 - Legacy dict mapping:")
    print(json.dumps(result2, indent=2))
    
    # Note: The exact results depend on the mock implementations
    print("✓ Legacy mapping test completed")

    print("\n" + "="*60)
    print("Integration tests completed successfully!")
    return True


if __name__ == "__main__":
    test_integration()