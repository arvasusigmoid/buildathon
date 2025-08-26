from datetime import datetime
import json
import mysql.connector
from inventory_depletion import deplete_inventory_from_order

# --- Helper function to get current inventory for debugging ---
def get_ingredient_current_inventory(ingredient_id, conn):
    """Fetches the current_inventory for a given ingredient_id."""
    if conn is None:
        return None
    try:
        with conn.cursor() as cursor:
            query = "SELECT ingredient_name, current_inventory, unit FROM Ingredients WHERE ingredient_id = %s;"
            cursor.execute(query, (ingredient_id,))
            result = cursor.fetchone()
            if result:
                return {"name": result[0], "inventory": result[1], "unit": result[2]}
            return None
    except mysql.connector.Error as err:
        print(f"Error fetching inventory for ingredient ID {ingredient_id}: {err}")
        return None

def insert_orders_from_bot(order_data, conn):
    """
    Saves order data from the bot's 'cart' list directly to the MySQL 'Orders' table.
    Then triggers inventory depletion and prints before/after inventory levels.
    """
    if conn is None:
        print("Error: MySQL connection not established. Cannot save order.")
        return

    try:
        with conn.cursor() as cursor:
            meal_name_to_id = {}
            try:
                cursor.execute("SELECT name, meal_id FROM Meals")
                meal_name_to_id = {name.lower(): meal_id for name, meal_id in cursor.fetchall()}
            except mysql.connector.Error as err:
                print(f"Error fetching meal_id mapping: {err}")
                return

            orders_to_insert = []
            for item in order_data:
                item_name = item.item_name
                quantity = item.quantity
                modifiers = json.dumps(item.modifiers) if item.modifiers else None
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                meal_id = meal_name_to_id.get(item_name.lower())
                
                if meal_id is not None:
                    orders_to_insert.append((meal_id, item_name, quantity, modifiers, timestamp))
                else:
                    print(f"Warning: Meal '{item_name}' not found in database. Skipping this order item.")
            
            if orders_to_insert:
                insert_query = """
                INSERT INTO Orders (meal_id, item_name, quantity, modifiers, timestamp)
                VALUES (%s, %s, %s, %s, %s);
                """
                cursor.executemany(insert_query, orders_to_insert)
                conn.commit()
                print(f"\nSuccessfully saved {len(orders_to_insert)} order items to the 'Orders' table.")
                
                # --- Pre-depletion Inventory Check ---
                print("\n--- Pre-depletion Inventory Check ---")
                ingredients_to_check = {} # {ingredient_id: (ingredient_name, unit)}
                
                # First, gather all unique ingredients involved in the *current* order from Recipe_Ingredients
                for order_item in order_data:
                    meal_id_for_item = meal_name_to_id.get(order_item.item_name.lower())
                    if meal_id_for_item:
                        recipe_query = """
                        SELECT ri.ingredient_id, i.ingredient_name, i.unit
                        FROM Recipe_Ingredients ri
                        JOIN Ingredients i ON ri.ingredient_id = i.ingredient_id
                        WHERE ri.meal_id = %s;
                        """
                        cursor.execute(recipe_query, (meal_id_for_item,))
                        for ing_id, ing_name, ing_unit in cursor.fetchall():
                            ingredients_to_check[ing_id] = {"name": ing_name, "unit": ing_unit}

                # Now fetch their current inventory levels
                ingredients_before_depletion = {} # {ingredient_id: {name, inventory, unit}}
                for ing_id, ing_data in ingredients_to_check.items():
                    inv = get_ingredient_current_inventory(ing_id, conn)
                    if inv:
                        ingredients_before_depletion[ing_id] = inv

                for ing_id, inv_data in ingredients_before_depletion.items():
                    print(f"  - BEFORE: {inv_data['name']} (ID: {ing_id}): {inv_data['inventory']} {inv_data['unit']}")


                # --- Call inventory depletion from the separate module ---
                # The deplete_inventory_from_order function itself will print detailed DEBUG messages
                deplete_inventory_from_order(order_data, conn)

                # --- Post-depletion Inventory Check ---
                print("\n--- Post-depletion Inventory Check ---")
                for ing_id, _ in ingredients_before_depletion.items(): # Use the same IDs checked before
                    inv = get_ingredient_current_inventory(ing_id, conn)
                    if inv:
                        print(f"  - AFTER: {inv['name']} (ID: {ing_id}): {inv['inventory']} {inv['unit']}")

            else:
                print("\nNo valid order items to save to the 'Orders' table.")

    except mysql.connector.Error as err:
        print(f"An error occurred while saving orders to MySQL: {err}")
    except Exception as e:
        print(f"An unexpected error occurred while saving orders: {e}")
    rejected_items: list[tuple]
