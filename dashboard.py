import streamlit as st
import pandas as pd
import mysql.connector
from dotenv import load_dotenv
import os
load_dotenv("keys.env")

# --- MySQL Database Configuration ---
# Ensure these details match your 'restaurant_new_db' setup.
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',         # Your MySQL username
    'password': '12345678',  # Your MySQL password
    'database': os.getenv('DB_NAME') # The database to connect to
}
# ----------------------------------

# We will NOT cache the connection function directly.
# Instead, we will get a fresh connection for each data fetch.
def get_mysql_connection_uncached():
    """Establishes and returns a connection to the MySQL database."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except mysql.connector.Error as err:
        st.error(f"Error connecting to MySQL: {err}")
        st.error("Please ensure your MySQL server is running and connection details are correct.")
        return None
def reorder_ingredients_via_backend():
    """Triggers the check_and_order_ingredients function from SQLFILEBUILDER_FINAL.py."""
    try:
        # We need a way to call this function. A simple approach is to have a separate script
        # or a direct function call if the files were structured differently.
        # For this example, we'll simulate the call and explain the backend change.
        # The user will need to run the `check_and_order_ingredients()` function.
        # This part of the code is a conceptual placeholder.
        st.info("Placing reorder for all low-stock ingredients...")
        # Simulate the call to the backend function.
        import time
        from SQLFILEBUILDER_FINAL import check_and_order_ingredients
        check_and_order_ingredients()
        st.success("Reorder request sent to backend. Inventory will be updated shortly.")
    except Exception as e:
        st.error(f"An error occurred during reordering: {e}")

# Now, fetch_data will create its own connection and close it.
def fetch_data(table_name):
    """Fetches all data from a specified table and returns it as a Pandas DataFrame."""
    conn = get_mysql_connection_uncached() # Get a fresh connection
    if conn:
        try:
            query = f"SELECT * FROM {table_name}"
            df = pd.read_sql(query, conn)
            return df
        except mysql.connector.Error as err:
            st.error(f"Error fetching data from {table_name}: {err}")
            return pd.DataFrame() # Return empty DataFrame on error
        finally:
            if conn.is_connected(): # Check if connection is still open before closing
                conn.close() # Always close the connection after fetching data
    return pd.DataFrame()

# --- Streamlit Dashboard Layout ---

st.set_page_config(layout="wide") # Use wide layout for better data display
st.title("🍽️ Restaurant Inventory & Orders Dashboard")
st.markdown("Monitor your **Orders** and **Ingredient Inventory** in real-time.")

# --- Orders Table Section ---
st.header("🛒 Recent Orders")
st.markdown("Details of all customer orders.")

orders_df = fetch_data("Order_Items")
if not orders_df.empty:
    st.dataframe(orders_df)
    st.subheader("Order Statistics")
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Orders", orders_df['order_id'].nunique())
    with col2:
        st.metric("Total Items Ordered", orders_df['quantity'].sum())
else:
    st.info("No order data available. Place some orders using the bot!")

st.markdown("---") # Horizontal line separator

# --- Ingredients Table Section ---
st.header("🥦 Ingredient Inventory")
st.markdown("Current stock levels of all ingredients.")

ingredients_df = fetch_data("Ingredients")
if not ingredients_df.empty:
    st.dataframe(ingredients_df)

    st.subheader("Inventory Summary")
    
    # Simple bar chart for top N ingredients by current_inventory
    top_n_ingredients = st.slider("Show Top N Ingredients in Chart", 5, 20, 10)
    
    # Ensure current_inventory is numeric
    ingredients_df['current_inventory'] = pd.to_numeric(ingredients_df['current_inventory'], errors='coerce')
    
    top_ingredients = ingredients_df.nlargest(top_n_ingredients, 'current_inventory')
    
    st.bar_chart(top_ingredients.set_index('ingredient_name')['current_inventory'])

    # Display ingredients below reorder point
    st.subheader("⚠️ Ingredients Below Reorder Point")
    below_reorder = ingredients_df[ingredients_df['current_inventory'] < ingredients_df['reorder_point']]
    if not below_reorder.empty:
        st.warning("The following ingredients need reordering soon:")
        st.dataframe(below_reorder[['ingredient_name', 'current_inventory', 'reorder_point', 'supplier_id']])
        if st.button("Place Reorder for All Low-Stock Ingredients"):
            reorder_ingredients_via_backend()
            # Rerun the app to show the updated inventory
            st.rerun()
    else:
        st.success("All ingredients are currently above their reorder points!")

else:
    st.info("No ingredient data available. Ensure your database is populated.")

st.markdown("---")
st.caption("Data refreshed on demand. Click 'Rerun' above to get the latest data.")
