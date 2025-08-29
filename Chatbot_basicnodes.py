import streamlit as st
import mysql.connector
import json
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from basic_nodes_bot import makegraph, insert_orders_from_bot
from Classes import Item # Assuming Item class is defined in Classes.py
from SQLFILE import deplete_inventory_from_order
from dotenv import load_dotenv
import os
load_dotenv("keys.env")
# --- IMPORTANT: MySQL DB_CONFIG for Streamlit App ---
# Ensure these details match your 'restaurant_new_db' setup
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',        # Your MySQL username
    'password': '12345678', # Your MySQL password
    'database': os.getenv('DB_NAME') # The database where 'Orders' table is
}
# ----------------------------------------------------

# Streamlit Page Config
st.set_page_config(page_title="Menu Order Chatbot", page_icon="🍽️", layout="centered")
st.title("🍽️ Restaurant Order Assistant")
st.caption("Ask questions about the menu or place an order.")

def get_item_price_from_db(item_name: str, conn):
    """
    Fetches the price of an item from the 'Meals' table in the database.
    Assumes 'Meals' table has 'item_name' and 'price' columns.
    """
    if conn is None:
        return None # Cannot get price without connection
    try:
        cursor = conn.cursor()
        query = "SELECT price FROM Meals WHERE name = %s"
        cursor.execute(query, (item_name,))
        result = cursor.fetchone()
        cursor.close()
        if result:
            return float(result[0])
        return None
    except mysql.connector.Error as err:
        st.error(f"Error fetching price for {item_name}: {err}")
        return None

def initialize_session_state():
    """Initializes all necessary session state variables."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "cart" not in st.session_state:
        st.session_state.cart = [] # This will store Item objects
    if "rejected_items" not in st.session_state:
        st.session_state.rejected_items = [] # This will store dicts for rejected items

    # Initialize MySQL connection
    if "mysql_conn" not in st.session_state:
        try:
            st.session_state.mysql_conn = mysql.connector.connect(**DB_CONFIG)
            st.success("✅ MySQL connection established!")
        except mysql.connector.Error as err:
            st.error(f"❌ Error connecting to MySQL: {err}. Order saving and price display will not work.")
            st.session_state.mysql_conn = None

    # Initialize LangGraph graph
    if "graph" not in st.session_state:
        if st.session_state.mysql_conn:
            # We assume makegraph internally handles its dependencies or doesn't need mysql_conn directly for graph creation.
            st.session_state.graph = makegraph()
            st.session_state.thread_id = "streamlit_user_thread" # A fixed thread ID for the Streamlit user
            st.session_state.config = {"configurable": {"thread_id": st.session_state.thread_id}}
            st.success("✅ Restaurant assistant initialized!")
        else:
            st.warning("⚠️ Cannot initialize bot without database connection.")
            st.session_state.graph = None


def process_message(user_input: str):
    """Processes user input through the LangGraph bot and updates session state."""
    if st.session_state.graph is None:
        return "The bot is not initialized. Please check the database connection."

    st.session_state.messages.append(HumanMessage(content=user_input))

    # Update the graph's initial state for this interaction
    # The graph processes its state, and we'll pull the updated cart/rejected items back
    st.session_state.graph.update_state(
        st.session_state.config,
        {
            "cart": st.session_state.cart,
            "rejected_items": st.session_state.rejected_items
        }
    )

    full_response_content = ""
    ai_messages_for_display = []

    # Handle checkout
    if user_input.lower().strip() in {"checkout", "confirm", "yes", "y"}:
        if st.session_state.cart:
            if st.session_state.mysql_conn:
                status = insert_orders_from_bot(st.session_state.cart, st.session_state.mysql_conn,deplete_inventory_from_order)
                if status == "ok":
                    full_response_content = "Order confirmed and will be sent to the Kitchen! Thank you."
                elif status == "notok-err":
                    full_response_content = "Sorry, some unexpected error occured with our inventory system."
                elif status == "not_enough":
                    full_response_content = "Sorry, we don't currently have all the required supplies in the kitchen to fulfill your order. Please try ordering a lesser quantity or different items on our menu!"
                ai_messages_for_display.append(AIMessage(content=full_response_content))
                st.session_state.cart = [] # Clear cart after confirmation
                st.session_state.rejected_items = [] # Clear rejected items
                st.session_state.graph.update_state(st.session_state.config, {"cart": [], "rejected_items": []}) # Reset graph state too
            else:
                full_response_content = "Cannot confirm order. Database connection not established."
                ai_messages_for_display.append(AIMessage(content=full_response_content))
        else:
            full_response_content = "Your cart is empty, nothing to save or confirm."
            ai_messages_for_display.append(AIMessage(content=full_response_content))
        st.session_state.messages.extend(ai_messages_for_display)
        return full_response_content

    # Stream updates from the graph
    for update in st.session_state.graph.stream({"messages": [HumanMessage(content=user_input)]}, config=st.session_state.config):
        for step, output in update.items():
            if "messages" in output:
                for m in output["messages"]:
                    if isinstance(m, (AIMessage, ToolMessage)):
                        full_response_content += m.content + "\n"
                        ai_messages_for_display.append(m)
            # You might want to update cart/rejected_items more granularly if needed here
            # For now, we'll get the final state after the stream.

    # Get the final state after the stream to update session_state.cart and rejected_items
    final_state_values = st.session_state.graph.get_state(config=st.session_state.config).values
    st.session_state.cart = final_state_values.get('cart', [])
    st.session_state.rejected_items = final_state_values.get('rejected_items', [])

    st.session_state.messages.extend(ai_messages_for_display)
    return full_response_content.strip()


def display_chat_messages():
    """Display chat messages from session state."""
    for msg in st.session_state.messages:
        if isinstance(msg, HumanMessage):
            with st.chat_message("user"):
                st.markdown(msg.content)
        elif isinstance(msg, (AIMessage, ToolMessage)):
            with st.chat_message("assistant"):
                st.markdown(msg.content)

def display_order_summary():
    """Display current order summary in sidebar using st.session_state.cart, including prices."""
    st.sidebar.markdown("### 📋 Current Order")

    if st.session_state.cart:
        total_order_price = 0.0
        st.sidebar.markdown("---")
        for item in st.session_state.cart:
            name = item.item_name
            qty = item.quantity
            modifiers = item.modifiers if hasattr(item, 'modifiers') and item.modifiers else []
            mod_text = f" ({', '.join(modifiers)})" if modifiers else ""

            item_price = get_item_price_from_db(name, st.session_state.mysql_conn)
            if item_price is not None:
                item_total = item_price * qty
                total_order_price += item_total
                st.sidebar.markdown(f"""
                <div class="menu-item">
                    <strong>{name}</strong> x{qty}{mod_text} <span style="float:right;">${item_total:.2f}</span>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.sidebar.markdown(f"""
                <div class="menu-item">
                    <strong>{name}</strong> x{qty}{mod_text} <span style="float:right;">Price N/A</span>
                </div>
                """, unsafe_allow_html=True)

        st.sidebar.markdown("---")
        st.sidebar.markdown(f"""
        <div style="background-color: #f0f2f6; padding: 0.75rem; border-radius: 5px; text-align: center;">
            <strong>Total:</strong> <span style="float:right; color: #28a745; font-weight: bold;">${total_order_price:.2f}</span>
        </div>
        """, unsafe_allow_html=True)
        st.sidebar.markdown("---")
        st.sidebar.info("Type 'checkout' or 'confirm' to place your order.")

        # Clear order button
        if st.sidebar.button("🗑️ Clear Cart", type="secondary", use_container_width=True):
            st.session_state.cart = []
            st.session_state.rejected_items = []
            if st.session_state.graph:
                st.session_state.graph.update_state(st.session_state.config, {"cart": [], "rejected_items": []})
            st.rerun()

    elif st.session_state.rejected_items:
        st.sidebar.warning("Some items were not recognized or are unavailable.")
        for item in st.session_state.rejected_items:
            st.sidebar.markdown(f"- **'{item.get('original_request', 'Unknown Item')}'**")
            if item.get('similar_items'):
                st.sidebar.markdown(f"  *Did you mean*: {', '.join(item['similar_items'])}")
        if st.sidebar.button("Clear Rejected Items", type="secondary", use_container_width=True):
            st.session_state.rejected_items = []
            if st.session_state.graph:
                st.session_state.graph.update_state(st.session_state.config, {"rejected_items": []})
            st.rerun()
    else:
        st.sidebar.info("No items in your cart yet.")


def main():
    initialize_session_state()

    # Sidebar
    with st.sidebar:
        st.markdown("### 🎯 Quick Actions")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("📜 Show Menu", use_container_width=True):
                with st.spinner("Getting menu..."):
                    response = process_message("Show me the menu")
                st.rerun() # Rerun to update chat and sidebar

        with col2:
            if st.button("📋 Order Summary", use_container_width=True):
                with st.spinner("Getting order summary..."):
                    response = process_message("Show my order summary")
                st.rerun() # Rerun to update chat and sidebar

        st.markdown("---")
        display_order_summary()

        st.markdown("---")
        st.markdown("### 💡 Sample Orders")
        sample_orders = [ "What paneer items do you have?", " What are the Beverages you offer? "]

        for sample in sample_orders:
            if st.button(f"💬 {sample}", key=sample, use_container_width=True):
                with st.spinner("Processing..."):
                    response = process_message(sample)
                st.rerun() # Rerun to update chat and sidebar

    # Main chat interface
    st.markdown("### 💬 Chat with our Assistant")

    # Display chat messages
    display_chat_messages()

    # Chat input
    if prompt := st.chat_input("Type your order or question here..."):
        # Process the message
        with st.chat_message("assistant"):
            with st.spinner("Processing your request..."):
                _ = process_message(prompt) # The function already updates st.session_state.messages
        st.rerun() # Rerun to update the chat history and order summary


    # Footer
    st.markdown("---")
    st.markdown("""
    <div style="text-align: center; color: #666; margin-top: 2rem;">
        🤖 Built with Streamlit and LangGraph
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
