"""
Tests for JSONata-based object mapping functionality
"""
import json
import unittest
from unittest.mock import Mock, patch
from espresso_sync.jsonata_mapper import extract_object_jsonata


class TestJSONataMapper(unittest.TestCase):
    def setUp(self):
        """Set up test data"""
        self.sample_data = {
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
        
    def test_simple_jsonata_expression(self):
        """Test basic JSONata expression evaluation"""
        # Test simple field access
        result = extract_object_jsonata("name", self.sample_data)
        self.assertEqual(result, "John Doe")
        
        # Test nested field access
        result = extract_object_jsonata("billing.company", self.sample_data)
        self.assertEqual(result, "ACME Corp")
        
    def test_conditional_jsonata_expression(self):
        """Test conditional logic in JSONata"""
        # Test conditional with truthy condition
        expression = "billing.company ? billing.company : name"
        result = extract_object_jsonata(expression, self.sample_data)
        self.assertEqual(result, "ACME Corp")
        
        # Test conditional with falsy condition
        data_no_company = self.sample_data.copy()
        data_no_company["billing"] = {"first_name": "John", "last_name": "Doe"}
        result = extract_object_jsonata(expression, data_no_company) 
        self.assertEqual(result, "John Doe")
        
    def test_array_mapping(self):
        """Test array mapping functionality"""
        expression = 'line_items.{"item_code": sku, "qty": quantity, "rate": price}'
        result = extract_object_jsonata(expression, self.sample_data)
        
        expected = [
            {"item_code": "ABC", "qty": 2, "rate": 10.50},
            {"item_code": "DEF", "qty": 1, "rate": 25.00}
        ]
        self.assertEqual(result, expected)
        
    def test_complete_object_mapping(self):
        """Test complete object transformation"""
        expression = '''
        {
          "customer_name": billing.company ? billing.company : (billing.first_name & " " & billing.last_name),
          "customer_city": billing.city,
          "items": line_items.{
            "item_code": sku,
            "qty": quantity, 
            "rate": price,
            "description": name
          }
        }
        '''
        
        result = extract_object_jsonata(expression, self.sample_data)
        
        expected = {
            "customer_name": "ACME Corp",
            "customer_city": "Boston",
            "items": [
                {"item_code": "ABC", "qty": 2, "rate": 10.50, "description": "Widget A"},
                {"item_code": "DEF", "qty": 1, "rate": 25.00, "description": "Widget B"}
            ]
        }
        self.assertEqual(result, expected)
        
    def test_legacy_dict_mapping_compatibility(self):
        """Test backward compatibility with legacy dict mappings"""
        
        # Mock frappe.render_template for Jinja compatibility
        with patch('frappe.render_template') as mock_render:
            mock_render.return_value = "ACME Corp - Boston"
            
            legacy_mapping = {
                "customer": "{{ billing.company }} - {{ billing.city }}",
                "project_name": "$.name"
            }
            
            # Mock extract_jsonpath for JSONPath compatibility
            with patch('espresso_sync.map_machine.extract_jsonpath') as mock_jsonpath:
                mock_jsonpath.return_value = "John Doe"
                
                result = extract_object_jsonata(legacy_mapping, self.sample_data)
                
                expected = {
                    "customer": "ACME Corp - Boston",
                    "project_name": "John Doe"
                }
                self.assertEqual(result, expected)
                
    def test_legacy_foreach_compatibility(self):
        """Test backward compatibility with legacy foreach function"""
        legacy_mapping = {
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
        
        # Mock extract_jsonpath for the nested mappings
        with patch('espresso_sync.map_machine.extract_jsonpath') as mock_jsonpath:
            def mock_jsonpath_side_effect(expr, data):
                if expr == "$.sku":
                    return data.get("sku")
                elif expr == "$.quantity":
                    return data.get("quantity")
                return None
                
            mock_jsonpath.side_effect = mock_jsonpath_side_effect
            
            result = extract_object_jsonata(legacy_mapping, self.sample_data)
            
            expected = {
                "items": [
                    {"item_code": "ABC", "qty": 2},
                    {"item_code": "DEF", "qty": 1}
                ]
            }
            self.assertEqual(result, expected)

    def test_legacy_match_compatibility(self):
        """Test backward compatibility with legacy match function"""
        legacy_mapping = {
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
        
        result = extract_object_jsonata(legacy_mapping, self.sample_data)
        
        expected = {
            "status": "To Deliver and Bill"
        }
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()