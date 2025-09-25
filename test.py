import unittest
from unittest import mock
from datetime import datetime
import time

# Import the function we want to test
from db_utils import insert_orders_from_bot, get_ingredient_current_inventory

# Mock the external dependencies that db_utils.py imports
# We'll need to mock SQLFILEBUILDER_FINAL and inventory_depletion
# Create a dummy Item class as it's used in order_data
class MockItem:
    def __init__(self, name, quantity, notes=""):
        self.name = name
        self.quantity = quantity
        self.notes = notes

# We need to mock the functions imported from SQLFILEBUILDER_FINAL
# and inventory_depletion.
# For simplicity, we create dummy modules here. In a real project,
# these would likely be in separate files and imported directly.
mock_sql_file_builder = mock.MagicMock()
mock_inventory_depletion = mock.MagicMock()

# Patch the imports for the module under test
# This ensures that when db_utils tries to import these, it gets our mocks
mock.patch('db_utils.update_meal_availability', mock_sql_file_builder.update_meal_availability).start()
mock.patch('db_utils.get_mysql_connection', mock_sql_file_builder.get_mysql_connection).start()
mock.patch('inventory_depletion.deplete_inventory_from_order', mock_inventory_depletion.deplete_inventory_from_order).start()
# Also need to mock the original update_meal_availability that is imported
mock.patch('SQLFILEBUILDER_FINAL.update_meal_availability', mock_sql_file_builder.update_meal_availability).start()


class TestInsertOrdersFromBot(unittest.TestCase):

    def setUp(self):
        """Set up mock objects for each test."""
        self.mock_conn = mock.MagicMock()
        self.mock_cursor = mock.MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        # Mock lastrowid for the order_id
        self.mock_cursor.lastrowid = 123
        self.mock_conn.is_connected.return_value = True

        # Reset mocks before each test
        mock_sql_file_builder.reset_mock()
        mock_inventory_depletion.reset_mock()
        self.mock_conn.reset_mock()
        self.mock_cursor.reset_mock()

    @mock.patch('time.sleep', return_value=None) # Mock time.sleep to avoid actual delay
    def test_insert_orders_from_bot_success(self, mock_time_sleep):
        """
        Tests the successful insertion of an order, including total amount calculation,
        delay, and calls to availability/depletion functions, including Paneer Tikka.
        """
        print("\n--- Running test_insert_orders_from_bot_success ---") # Added print statement
        # Define mock data for meals from the database
        # (name, meal_id, price)
        mock_meals_data = [
            ("Pizza Margherita", 1, 12.50),
            ("Pasta Carbonara", 2, 15.00),
            ("Caesar Salad", 3, 8.75),
            ("Paneer Tikka", 4, 18.00), # Added Paneer Tikka
        ]
        # (ingredient_name, current_inventory, unit) for get_ingredient_current_inventory
        mock_ingredient_inventory = {
            101: {"name": "Tomato", "inventory": 500, "unit": "g"},
            102: {"name": "Mozzarella", "inventory": 300, "unit": "g"},
            103: {"name": "Pasta", "inventory": 1000, "unit": "g"},
            104: {"name": "Paneer", "inventory": 700, "unit": "g"}, # Ingredient for Paneer Tikka
            105: {"name": "Yogurt", "inventory": 200, "unit": "ml"}, # Ingredient for Paneer Tikka
        }

        # Configure mock_cursor.execute to return different data based on the query
        self.mock_cursor.execute.side_effect = [
            None, # First call to execute for meal names/prices
            None, # For Pizza ingredients
            None, # For Pasta ingredients
            None, # For Caesar Salad ingredients
            None, # For Paneer Tikka ingredients
            None, # For insert_order_query
            None, # For insert_item_query
        ]
        
        # Configure mock_cursor.fetchall to return different data based on the call sequence
        self.mock_cursor.fetchall.side_effect = [
            mock_meals_data,
            # For Recipe_Ingredients queries for each meal
            [(101, "Tomato", "g"), (102, "Mozzarella", "g")], # Ingredients for Pizza (meal_id 1)
            [(103, "Pasta", "g")], # Ingredients for Pasta (meal_id 2)
            [], # No specific ingredients for Caesar Salad in this mock scenario
            [(104, "Paneer", "g"), (105, "Yogurt", "ml")], # Ingredients for Paneer Tikka (meal_id 4)
            [] # Default for any unexpected fetchall
        ]

        # Mock get_ingredient_current_inventory's return value
        with mock.patch('db_utils.get_ingredient_current_inventory', side_effect=lambda ing_id, conn: mock_ingredient_inventory.get(ing_id)) as mock_get_inventory:

            order_data = [
                MockItem("Pizza Margherita", 2, "extra cheese"),
                MockItem("Pasta Carbonara", 1),
                MockItem("Paneer Tikka", 1, "spicy"), # Added Paneer Tikka to the order
                MockItem("Non Existent Item", 1), # Should be skipped
            ]

            # Expected total amount: (2 * 12.50) + (1 * 15.00) + (1 * 18.00) = 25.00 + 15.00 + 18.00 = 58.00
            expected_total_amount = 58.00

            insert_orders_from_bot(order_data, self.mock_conn, mock_inventory_depletion.deplete_inventory_from_order)

            # Assertions for Orders table insertion
            self.mock_cursor.execute.assert_any_call(
                unittest.mock.ANY, # Query string for INSERT INTO Orders
                unittest.mock.ANY # Tuple for (order_date, total_amount)
            )
            
            # Find the call that inserted into Orders
            orders_insert_call_args = None
            for call_args, call_kwargs in self.mock_cursor.execute.call_args_list:
                if "INSERT INTO Orders" in call_args[0]:
                    orders_insert_call_args = call_args
                    break
            
            self.assertIsNotNone(orders_insert_call_args, "INSERT INTO Orders query not found.")
            
            # Check the total_amount passed to the Orders insert
            actual_total_amount = orders_insert_call_args[1][1]
            self.assertAlmostEqual(actual_total_amount, expected_total_amount, places=2)

            # Assertions for Order_Items table insertion
            self.mock_cursor.executemany.assert_called_once_with(
                "INSERT INTO Order_Items (order_id, meal_id, quantity, notes) VALUES (%s, %s, %s, %s);",
                [(123, 1, 2, "extra cheese"), (123, 2, 1, ""), (123, 4, 1, "spicy")], # Updated with Paneer Tikka
            )
            self.mock_conn.commit.assert_called_once()

            # Assert the time delay was called
            mock_time_sleep.assert_called_once_with(10)

            # Assert that inventory depletion and meal availability were updated
            mock_inventory_depletion.deplete_inventory_from_order.assert_called_once_with(order_data)
            mock_sql_file_builder.update_meal_availability.assert_called_once()

            # Verify ingredient inventory checks were made
            mock_get_inventory.assert_any_call(101, self.mock_conn)
            mock_get_inventory.assert_any_call(102, self.mock_conn)
            mock_get_inventory.assert_any_call(103, self.mock_conn)
            mock_get_inventory.assert_any_call(104, self.mock_conn) # Added Paneer ingredient
            mock_get_inventory.assert_any_call(105, self.mock_conn) # Added Yogurt ingredient


    @mock.patch('time.sleep', return_value=None)
    def test_insert_orders_from_bot_empty_order(self, mock_time_sleep):
        """Tests behavior with an empty order_data list."""
        print("\n--- Running test_insert_orders_from_bot_empty_order ---") # Added print statement
        order_data = []
        insert_orders_from_bot(order_data, self.mock_conn, mock.MagicMock())

        self.mock_cursor.execute.assert_called_once_with("SELECT name, meal_id, price FROM Meals")
        self.mock_conn.commit.assert_not_called()
        self.mock_cursor.executemany.assert_not_called()
        mock_time_sleep.assert_not_called()
        mock_inventory_depletion.deplete_inventory_from_order.assert_not_called()
        mock_sql_file_builder.update_meal_availability.assert_not_called()

    @mock.patch('time.sleep', return_value=None)
    def test_insert_orders_from_bot_no_connection(self, mock_time_sleep):
        """Tests behavior when no MySQL connection is provided."""
        print("\n--- Running test_insert_orders_from_bot_no_connection ---") # Added print statement
        insert_orders_from_bot([], None, mock.MagicMock())
        self.mock_conn.cursor.assert_not_called()
        mock_time_sleep.assert_not_called()
        mock_inventory_depletion.deplete_inventory_from_order.assert_not_called()
        mock_sql_file_builder.update_meal_availability.assert_not_called()

    @mock.patch('time.sleep', return_value=None)
    def test_insert_orders_from_bot_price_not_found(self, mock_time_sleep):
        """Tests total amount calculation when some meal prices are not found."""
        print("\n--- Running test_insert_orders_from_bot_price_not_found ---") # Added print statement
        mock_meals_data = [
            ("Pizza Margherita", 1, 12.50),
            # Pasta Carbonara price is missing in mock_meals_data for this test
            ("Paneer Tikka", 4, 18.00), # Included Paneer Tikka
        ]
        self.mock_cursor.fetchall.side_effect = [
            mock_meals_data,
            [(101, "Tomato", "g")], # Ingredients for Pizza
            [(104, "Paneer", "g")], # Ingredients for Paneer Tikka
            [], # Default
        ]

        order_data = [
            MockItem("Pizza Margherita", 2),
            MockItem("Pasta Carbonara", 1), # Price for this will not be found
            MockItem("Paneer Tikka", 1), # Price for this will be found
        ]

        # Expected total amount: (2 * 12.50) + (1 * 18.00) = 25.00 + 18.00 = 43.00
        expected_total_amount = 43.00
        
        insert_orders_from_bot(order_data, self.mock_conn, mock.MagicMock())

        orders_insert_call_args = None
        for call_args, call_kwargs in self.mock_cursor.execute.call_args_list:
            if "INSERT INTO Orders" in call_args[0]:
                orders_insert_call_args = call_args
                break
        
        self.assertIsNotNone(orders_insert_call_args, "INSERT INTO Orders query not found.")
        actual_total_amount = orders_insert_call_args[1][1]
        self.assertAlmostEqual(actual_total_amount, expected_total_amount, places=2)
