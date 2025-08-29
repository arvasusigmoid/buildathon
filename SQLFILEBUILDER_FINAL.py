import mysql.connector
import pandas as pd
import json
import os
import re
from datetime import datetime
import time 
from decimal import Decimal

from dotenv import load_dotenv
load_dotenv("keys.env")
# --- IMPORTANT: Configure your MySQL connection details here ---
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',        # Your MySQL username
    'password': '12345678', # Your MySQL password
}
NEW_DB_NAME = os.getenv('DB_NAME')
# -------------------------------------------------------------

def get_mysql_connection(database_name=NEW_DB_NAME):
    """Establishes a connection to the MySQL database."""
    try:
        config = DB_CONFIG.copy()
        if database_name:
            config['database'] = database_name
        
        conn = mysql.connector.connect(**config)
        return conn
    except mysql.connector.Error as err:
        print(f"Error: {err}")
        return None

def create_database_if_not_exists(conn, db_name):
    """Creates the database if it doesn't already exist."""
    cursor = conn.cursor()
    try:
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
        print(f"Database '{db_name}' ensured.")
    except mysql.connector.Error as err:
        print(f"Failed creating database: {err}")
    finally:
        cursor.close()

def drop_all_tables():
    """Drops all tables to ensure a clean slate for the script."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        tables_to_drop = [
            'Order_Items', 'Purchase_Orders', 'Recipe_Ingredients', 
            'Ingredients', 'Meals', 'Suppliers', 'Chefs'
        ]
        for table in tables_to_drop:
            try:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
                print(f"Table '{table}' dropped.")
            except mysql.connector.Error as err:
                print(f"Error dropping table '{table}': {err}")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
    finally:
        cursor.close()
        conn.close()

def create_restaurant_tables():
    """Creates the necessary tables for the restaurant management system."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        # Create Suppliers Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Suppliers (
            supplier_id VARCHAR(50) PRIMARY KEY,
            supplier_name VARCHAR(255) NOT NULL,
            contact_info VARCHAR(255)
        )
        """)
        print("Table 'Suppliers' created.")

        # Create Chefs Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Chefs (
            chef_id INT PRIMARY KEY AUTO_INCREMENT,
            name VARCHAR(255) NOT NULL,
            specialization VARCHAR(255)
        )
        """)
        print("Table 'Chefs' created.")

        # Create Meals Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Meals (
            meal_id INT PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            type VARCHAR(50),
            category VARCHAR(50),
            price DECIMAL(10, 2),
            Chef_chef_id INT,
            available BOOLEAN DEFAULT TRUE,
            FOREIGN KEY (Chef_chef_id) REFERENCES Chefs(chef_id) ON DELETE SET NULL
        )
        """)
        print("Table 'Meals' created.")

        # Create Ingredients Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Ingredients (
            ingredient_id INT AUTO_INCREMENT PRIMARY KEY,
            ingredient_name VARCHAR(255) UNIQUE NOT NULL,
            unit VARCHAR(50),
            current_inventory DECIMAL(10, 3) NOT NULL,
            reorder_point DECIMAL(10, 3) NOT NULL,
            reorder_quantity DECIMAL(10, 3),
            supplier_id VARCHAR(50),
            FOREIGN KEY (supplier_id) REFERENCES Suppliers(supplier_id)
        )
        """)
        print("Table 'Ingredients' created.")
        
        # Create Recipe_Ingredients Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Recipe_Ingredients (
            Meal_ID INT,
            Ingredient_ID INT,
            Quantity DECIMAL(10, 3) NOT NULL,
            PRIMARY KEY (Meal_ID, Ingredient_ID),
            FOREIGN KEY (Meal_ID) REFERENCES Meals(meal_id) ON DELETE CASCADE,
            FOREIGN KEY (Ingredient_ID) REFERENCES Ingredients(ingredient_id) ON DELETE CASCADE
        )
        """)
        print("Table 'Recipe_Ingredients' created.")

        # Create Purchase_Orders Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Purchase_Orders (
            order_id INT AUTO_INCREMENT PRIMARY KEY,
            ingredient_id INT NOT NULL,
            quantity_ordered DECIMAL(10, 3) NOT NULL,
            order_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            supplier_id VARCHAR(50),
            FOREIGN KEY (ingredient_id) REFERENCES Ingredients(ingredient_id) ON DELETE CASCADE
        )
        """)
        print("Table 'Purchase_Orders' created.")

        # Create Order_Items Table (for simulating customer orders)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Order_Items (
            order_item_id INT AUTO_INCREMENT PRIMARY KEY,
            order_id VARCHAR(75) NOT NULL,
            meal_id INT NOT NULL,
            quantity INT NOT NULL,
            FOREIGN KEY (meal_id) REFERENCES Meals(meal_id) ON DELETE CASCADE
        )
        """)
        print("Table 'Order_Items' created.")
    except mysql.connector.Error as err:
        print(f"Error creating tables: {err}")
    finally:
        cursor.close()
        conn.close()

def insert_data_into_tables():
    """Populates the database tables with data from CSV and JSON files."""
    conn = None
    try:
        conn = get_mysql_connection(database_name=NEW_DB_NAME)
        if not conn:
            print("Failed to get connection for inserting data.")
            return

        cursor = conn.cursor()
        
        # --- Insert Suppliers (Dummy Data) ---
        suppliers_data = [
            ('Supplier001', 'Green Groceries Inc.', 'contact1@example.com'),
            ('Supplier002', 'Spice Route Co.', 'contact2@example.com'),
            ('Supplier003', 'Dairy Farms Ltd.', 'contact3@example.com')
        ]
        supplier_insert_query = "INSERT INTO Suppliers (supplier_id, supplier_name, contact_info) VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE supplier_name=VALUES(supplier_name);"
        cursor.executemany(supplier_insert_query, suppliers_data)
        
        # --- Insert a Dummy Chef ---
        chef_insert_query = "INSERT INTO Chefs (name, specialization) VALUES ('Gordon Ramsay', 'French')"
        cursor.execute(chef_insert_query)
        dummy_chef_id = cursor.lastrowid
        print(f"  - Dummy chef with ID {dummy_chef_id} inserted.")

        # --- Insert Meals from meals.csv ---
        print("\n--- Inserting Meals from CSV ---")
        try:
            meals_df = pd.read_csv("sqldatafiles/meals.csv")
            insert_meal_query = """
                INSERT INTO Meals (meal_id, name, type, category, price, Chef_chef_id, available)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE)
                ON DUPLICATE KEY UPDATE name=VALUES(name);
            """
            # Add the dummy chef_id to the dataframe
            meals_df['Chef_chef_id'] = dummy_chef_id
            
            meal_data = [tuple(row) for row in meals_df.to_numpy()]
            cursor.executemany(insert_meal_query, meal_data)
            print(f"  - {cursor.rowcount} meals from CSV inserted/updated.")
        except FileNotFoundError:
            print("Warning: sqldatafiles/meals.csv not found. Skipping Meals data insertion.")

        # --- Insert Ingredients from ingredients_listcsv.csv ---
        print("\n--- Inserting Ingredients from CSV ---")
        ingredient_name_to_id = {}
        try:
            df_ingredients = pd.read_csv('sqldatafiles/ingredients_inventory.csv')
            
            ingredient_insert_query = """
                INSERT INTO Ingredients (ingredient_name, unit, current_inventory, reorder_point, reorder_quantity, supplier_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    unit = VALUES(unit),
                    current_inventory = VALUES(current_inventory),
                    reorder_point = VALUES(reorder_point),
                    reorder_quantity = VALUES(reorder_quantity),
                    supplier_id = VALUES(supplier_id);
            """
            ingredients_to_insert = [
                (row['ingredient_name'], row['unit'], row['current_inventory'], row['reorder_level'], 
                 row['reorder_quantity'] if 'reorder_quantity' in row else 25.0, row['supplier_id'])
                for index, row in df_ingredients.iterrows()
            ]
            
            cursor.executemany(ingredient_insert_query, ingredients_to_insert)
            print(f"  - {cursor.rowcount} ingredients from CSV inserted/updated.")
            
            conn.commit()
            
            # Re-fetch all ingredients and their IDs
            cursor.execute("SELECT ingredient_id, ingredient_name FROM Ingredients")
            ingredient_name_to_id = {name.lower(): id for id, name in cursor.fetchall()}
        except FileNotFoundError:
            print("Warning: sqldatafiles/ingredients_listcsv.csv not found. Skipping Ingredients data insertion.")

        # --- Insert Recipe Ingredients from ingredients.csv ---
        print("\n--- Inserting Recipes from ingredients.csv ---")
        try:
            recipes_df = pd.read_csv('sqldatafiles/meal_ingredients.csv')
            
            for index, row in recipes_df.iterrows():
                meal_id = row['meal_id']
                ingredient_name = row['name'].strip()
                quantity = row['qty']

                ing_id = ingredient_name_to_id.get(ingredient_name.lower())

                # Skip ingredients not found in the inventory
                if not ing_id:
                    print(f"  - Skipping unmapped ingredient: '{ingredient_name}' for meal '{meal_id}'")
                    continue

                # Ensure quantity is capped at 20.0
                capped_quantity = min(quantity, 20.0)

                recipe_ing_insert_query = """
                    INSERT INTO Recipe_Ingredients (Meal_ID, Ingredient_ID, Quantity)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE Quantity = VALUES(Quantity);
                """
                cursor.execute(recipe_ing_insert_query, (meal_id, ing_id, capped_quantity))
            
            conn.commit()
            print("  - Recipe ingredients inserted/updated.")

        except FileNotFoundError:
            print("Warning: sqldatafiles/ingredients.csv not found. Skipping recipe data insertion.")

        conn.commit()
        print("\nAll data insertion and updates completed successfully.")
    except mysql.connector.Error as err:
        print(f"Error inserting data: {err}")
        if conn: conn.rollback()
    finally:
        if conn and conn.is_connected():
            conn.close()

def set_reorder_point_from_recipes():
    """Sets the reorder point for each ingredient based on total recipe quantities."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION;")
        
        # Calculate the total quantity needed for each ingredient
        cursor.execute("""
            SELECT Ingredient_ID, SUM(Quantity) 
            FROM Recipe_Ingredients 
            GROUP BY Ingredient_ID
        """)
        recipe_qtys = cursor.fetchall()

        # Update the reorder_point in the Ingredients table
        update_query = "UPDATE Ingredients SET reorder_point = %s WHERE ingredient_id = %s"
        for ing_id, total_qty in recipe_qtys:
            # We assume the reorder point is the total quantity needed for all recipes
            cursor.execute(update_query, (total_qty, ing_id))
        
        conn.commit()
        print("\nSuccessfully updated reorder points based on total recipe quantities.")

    except mysql.connector.Error as err:
        print(f"Error updating reorder points: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def set_initial_inventory():
    """Sets the initial inventory to be above the reorder point."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION;")
        
        # Get ingredients where current inventory is below reorder point
        cursor.execute("SELECT ingredient_id, current_inventory, reorder_point FROM Ingredients WHERE current_inventory < reorder_point")
        low_stock_ingredients = cursor.fetchall()
        
        if not low_stock_ingredients:
            print("\nAll ingredients are at or above their reorder points. No initial stock adjustment needed.")
            conn.commit()
            return

        # For each low-stock ingredient, 'order' enough to bring it above the reorder point
        for ing_id, current_qty, reorder_point in low_stock_ingredients:
            qty_to_add = reorder_point - current_qty + Decimal('50.0')  # Add a buffer of 50.0
            
            # Update inventory
            update_query = "UPDATE Ingredients SET current_inventory = current_inventory + %s WHERE ingredient_id = %s"
            cursor.execute(update_query, (qty_to_add, ing_id))
            print(f"Added {qty_to_add:.2f}g to inventory for ingredient ID {ing_id}.")
            
        conn.commit()
        print("\nSuccessfully set initial inventory for ingredients below their reorder point.")
    
    except mysql.connector.Error as err:
        print(f"Error setting initial inventory: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def update_meal_availability():
    """Updates the availability of meals based on current ingredient inventory levels."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION;")

        # Set all meals to available by default
        cursor.execute("UPDATE Meals SET available = TRUE")
        
        # Find meals that are NOT available
        # Find meals where at least one ingredient is missing or not enough
        cursor.execute("""
            UPDATE Meals M
            SET available = FALSE
            WHERE EXISTS (
                SELECT 1
                FROM Recipe_Ingredients RI
                JOIN Ingredients I ON RI.Ingredient_ID = I.ingredient_id
                WHERE RI.Meal_ID = M.meal_id
                AND (I.current_inventory IS NULL OR I.current_inventory < RI.Quantity)
            );
        """)
        conn.commit()
        print("\nMeal availability has been updated based on current inventory levels.")
    except mysql.connector.Error as err:
        print(f"Error updating meal availability: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def fetch_order_data_from_db():
    """Fetches a sample order and inserts it into the Order_Items table."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    try:
        # Insert a sample customer order to work with
        sample_order_id = 1001
        sample_orders = [
            (sample_order_id, 1, 1),
            (sample_order_id, 94, 2)
        ]
        
        cursor.executemany("INSERT INTO Order_Items (order_id, meal_id, quantity) VALUES (%s, %s, %s)", sample_orders)
        conn.commit()

        # Fetch the newly inserted order
        cursor.execute(f"SELECT meal_id, quantity FROM Order_Items WHERE order_id = {sample_order_id}")
        order_data = cursor.fetchall()
        
        return order_data
    except mysql.connector.Error as err:
        print(f"Error fetching order data: {err}")
        return []
    finally:
        cursor.close()
        conn.close()

def deplete_inventory_from_order(customer_order):
    """Depletes inventory based on a customer order."""
    conn = get_mysql_connection()
    print('here')
    if not conn: 
        print('instant return! no conn!')
        return
    cursor = conn.cursor()
    # try:
    cursor.execute("START TRANSACTION;")
    for order_item in customer_order:
        

        meal_id = order_item['meal_id']
        ordered_quantity = order_item['quantity']
        
        # Get the ingredients and quantities for the meal by joining
        cursor.execute(f"SELECT I.ingredient_name, RI.Quantity, I.ingredient_id FROM Recipe_Ingredients RI JOIN Ingredients I ON RI.Ingredient_ID = I.ingredient_id WHERE RI.Meal_ID = {meal_id}")
        recipe_ingredients = cursor.fetchall()
        
        if not recipe_ingredients:
            print(f"No recipe found for meal ID {meal_id}.")
            continue
            
        for ingredient_name, recipe_qty, ing_id in recipe_ingredients:
            depletion_amount = recipe_qty * Decimal(str(ordered_quantity))
            
            # Deplete the inventory
            update_query = "UPDATE Ingredients SET current_inventory = current_inventory - %s WHERE ingredient_id = %s"
            cursor.execute(update_query, (depletion_amount, ing_id))
            print(f"Depleted {depletion_amount:.2f}g of {ingredient_name} for order.")

    conn.commit()
    print('here 2')
    print("\nInventory successfully depleted based on the customer order.")
    # except mysql.connector.Error as err:
    #     print(f"Error depleting inventory: {err}")
    #     conn.rollback()
    # finally:
    #     cursor.close()
    #     conn.close()

def check_and_order_ingredients():
    """Checks for low stock and places new orders."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor()
    try:
        cursor.execute("START TRANSACTION;")
        
        # Find ingredients that are now below the reorder point
        cursor.execute("SELECT ingredient_id, ingredient_name, current_inventory, reorder_point, supplier_id FROM Ingredients WHERE current_inventory < reorder_point")
        ingredients_to_order = cursor.fetchall()
        
        if not ingredients_to_order:
            print("\nAll ingredients are at or above their reorder points. No new orders needed.")
            conn.commit()
            return
            
        print("\nIngredients that need to be reordered:")
        for ing_id, name, current_qty, reorder_point, supplier_id in ingredients_to_order:
            # We will order enough to bring it back to the reorder point plus a buffer
            qty_to_order = reorder_point - current_qty + Decimal('50.0') # Add a buffer of 50.0
            
            # Log the order in the Purchase_Orders table
            insert_query = "INSERT INTO Purchase_Orders (ingredient_id, quantity_ordered, supplier_id) VALUES (%s, %s, %s)"
            cursor.execute(insert_query, (ing_id, qty_to_order, supplier_id))
            print(f"- {name}: Ordering {qty_to_order:.2f}g")
            
            # Simulate delivery by adding the ordered quantity to the inventory
            update_query = "UPDATE Ingredients SET current_inventory = current_inventory + %s WHERE ingredient_id = %s"
            cursor.execute(update_query, (qty_to_order, ing_id))
        
        conn.commit()
        print("\nSuccessfully placed orders and updated inventory for low-stock ingredients.")
    
    except mysql.connector.Error as err:
        print(f"Error checking and ordering ingredients: {err}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

def verify_purchase_orders():
    """Verifies the latest purchase orders from the database."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    try:
        print("\nVerifying the latest purchase orders...")
        cursor.execute("SELECT I.ingredient_name, P.quantity_ordered, P.order_date, P.supplier_id FROM Purchase_Orders P JOIN Ingredients I ON P.ingredient_id = I.ingredient_id ORDER BY P.order_date DESC LIMIT 5")
        orders = cursor.fetchall()
        
        if orders:
            print(f"Found {len(orders)} recent purchase orders:")
            for order in orders:
                print(f"  - Ingredient: {order['ingredient_name']}, Ordered: {order['quantity_ordered']:.2f}g, Supplier: {order['supplier_id']}, Date: {order['order_date']}")
        else:
            print("No recent purchase orders found.")
    except mysql.connector.Error as err:
        print(f"Error verifying purchase orders: {err}")
    finally:
        cursor.close()
        conn.close()

def debug_availability_issue():
    """Identifies and reports on meals that are currently unavailable."""
    conn = get_mysql_connection()
    if not conn: return
    cursor = conn.cursor(dictionary=True)
    try:
        print("\n--- Debugging Meal Availability Issues ---")
        
        # Find meals that are currently unavailable
        cursor.execute("SELECT meal_id, name FROM Meals WHERE available = FALSE")
        unavailable_meals = cursor.fetchall()
        
        if not unavailable_meals:
            print("All meals are currently available.")
            return

        print("The following meals are currently unavailable:")
        for meal in unavailable_meals:
            print(f"  - Meal ID: {meal['meal_id']}, Name: {meal['name']}")
            
            # Find the specific ingredients causing the unavailability
            cursor.execute("""
                SELECT I.ingredient_name, RI.Quantity AS required_qty, I.current_inventory AS current_qty
                FROM Recipe_Ingredients RI
                JOIN Ingredients I ON RI.Ingredient_ID = I.ingredient_id
                WHERE RI.Meal_ID = %s AND (I.current_inventory IS NULL OR I.current_inventory < RI.Quantity)
            """, (meal['meal_id'],))
            missing_ingredients = cursor.fetchall()
            
            for ingredient in missing_ingredients:
                print(f"    - Missing Ingredient: {ingredient['ingredient_name']}")
                print(f"      - Required: {ingredient['required_qty']:.2f}g")
                print(f"      - Available: {ingredient.get('current_qty', 0):.2f}g (Insufficient stock)")
    
    except mysql.connector.Error as err:
        print(f"Error in debugger: {err}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    conn_server = get_mysql_connection(database_name=None)
    if not conn_server:
        print("Could not connect to the database server. Please check your DB_CONFIG.")
        exit()

    try:
        create_database_if_not_exists(conn_server, NEW_DB_NAME)
    finally:
        if conn_server and conn_server.is_connected():
            conn_server.close()

    drop_all_tables()
    create_restaurant_tables()
    insert_data_into_tables()
    
    set_reorder_point_from_recipes()
    set_initial_inventory()
    update_meal_availability()

    customer_order = fetch_order_data_from_db()
    
    if customer_order:
        deplete_inventory_from_order(customer_order)
    else:
        print("\nNo order data to process for inventory depletion.")
    
    update_meal_availability()
    check_and_order_ingredients()
    verify_purchase_orders()
    update_meal_availability()
    debug_availability_issue()