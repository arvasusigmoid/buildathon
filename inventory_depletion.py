import mysql.connector
import json
from datetime import datetime

# Corrected: Import Item from Classes.py
from Classes import Item # Assuming Item class is defined in Classes.py

# --- IMPORTANT: MySQL DB_CONFIG for inventory_depletion.py ---
# Ensure these details match your 'restaurant_new_db' setup.
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',        # Your MySQL username
    'password': '12345678', # Your MySQL password
    'database': 'restaurant_new_db' # The database where 'Ingredients' and 'Recipe_Ingredients' tables are
}
# ----------------------------------------------------

def get_mysql_connection():
    """Establishes and returns a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        print(f"Error connecting to MySQL: {err}")
        print("Please ensure your MySQL server is running and connection details are correct.")
        return None

def deplete_inventory_from_order(order_data_items, conn):
    """
    Depletes ingredients from the Ingredients table based on the confirmed order items.
    
    Args:
        order_data_items (list[Item]): A list of Item objects from the confirmed order.
        conn (mysql.connector.connection.MySQLConnection): An active MySQL database connection.
    """
    if conn is None:
        print("Error: MySQL connection not established. Cannot deplete inventory.")
        return False

    print("\n--- Starting inventory depletion from single order ---")
    try:
        with conn.cursor() as cursor:
            # Step 1: Map meal names to meal_ids from the database
            meal_name_to_id = {}
            try:
                cursor.execute("SELECT name, meal_id FROM Meals")
                meal_name_to_id = {name.lower(): meal_id for name, meal_id in cursor.fetchall()}
                print(f"DEBUG: Meal name to ID map: {meal_name_to_id}")
            except mysql.connector.Error as err:
                print(f"Error fetching meal_id mapping: {err}")
                return False

            for order_item in order_data_items:
                # Type check now correctly uses the imported Item class
                if not isinstance(order_item, Item):
                    print(f"Error: Expected 'Item' object but received type '{type(order_item).__name__}'. Cannot process order item: {order_item}")
                    return False # Return False to indicate failure if type is truly mismatched

                item_name = order_item.item_name
                order_quantity = order_item.quantity
                meal_id = meal_name_to_id.get(item_name.lower())
                print(f"\nDEBUG: Processing order for '{item_name}' (Quantity: {order_quantity})")
                print(f"DEBUG: Found Meal ID: {meal_id}")

                if meal_id is None:
                    print(f"Warning: Meal '{item_name}' not found in Meals table. Cannot deplete inventory for this item.")
                    continue

                # Step 2: Get required ingredients and quantities for the ordered meal from Recipe_Ingredients
                recipe_query = """
                SELECT ri.ingredient_id, ri.quantity, i.ingredient_name, i.current_inventory, i.unit AS recipe_unit
                FROM Recipe_Ingredients ri
                JOIN Ingredients i ON ri.ingredient_id = i.ingredient_id
                WHERE ri.meal_id = %s;
                """
                cursor.execute(recipe_query, (meal_id,))
                ingredients_for_recipe = cursor.fetchall()
                print(f"DEBUG: Ingredients for recipe (Meal ID {meal_id}): {ingredients_for_recipe}")


                if not ingredients_for_recipe:
                    print(f"Warning: No recipe ingredients found for meal '{item_name}'. Skipping inventory depletion for this item.")
                    continue

                print(f"Depleting inventory for '{item_name}' (ordered {order_quantity}x):")
                for ingredient_id, recipe_quantity_per_meal, ingredient_name, current_inventory, recipe_unit in ingredients_for_recipe:
                    total_depletion_amount = recipe_quantity_per_meal * order_quantity

                    print(f"DEBUG:   Ingredient: '{ingredient_name}' (ID: {ingredient_id})")
                    print(f"DEBUG:     Recipe Qty per meal: {recipe_quantity_per_meal} {recipe_unit}")
                    print(f"DEBUG:     Current Inventory: {current_inventory} {recipe_unit}")
                    print(f"DEBUG:     Total Depletion Amount: {total_depletion_amount} {recipe_unit}")

                    if current_inventory is None:
                        print(f"  - WARNING: Inventory for '{ingredient_name}' is NULL. Cannot deplete.")
                        continue
                    
                    new_inventory = current_inventory - total_depletion_amount

                    # Step 3: Update the current_inventory in the Ingredients table
                    update_inventory_query = """
                    UPDATE Ingredients
                    SET current_inventory = %s
                    WHERE ingredient_id = %s;
                    """
                    cursor.execute(update_inventory_query, (new_inventory, ingredient_id))
                    print(f"  - Depleted {total_depletion_amount} {recipe_unit} of '{ingredient_name}'. New inventory: {new_inventory} {recipe_unit}")
            
            conn.commit()
            print("Inventory depletion completed successfully.")
            return True

    except mysql.connector.Error as err:
        print(f"An error occurred during inventory depletion: {err}")
        conn.rollback() # Rollback changes if an error occurs
        return False
    except Exception as e:
        print(f"An unexpected error occurred during inventory depletion: {e}")
        return False
