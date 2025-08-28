import pandas as pd
import os
from dotenv import load_dotenv
import warnings

from langgraph.graph import StateGraph, START, END

from langchain.chat_models import init_chat_model
from langchain_groq import ChatGroq
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver

#from rank_bm25 import BM25Okapi
from searchers import MultiSearch
from langchain_community.vectorstores import FAISS 
from langchain_huggingface import HuggingFaceEmbeddings

from promptstore import orderPrompt, conversationPrompt, routerPrompt
from Classes import Item, Order, State
from utils import makeRetriever
from db_utils import get_ingredient_current_inventory, insert_orders_from_bot
from SQLFILEBUILDER_FINAL import deplete_inventory_from_order
from nodes import router_node, extract_order_node, routeFunc, processOrder, menu_query_node, summary_node, confirm_order, clarify_options_node, deleteOrder, display_rejected, checkRejected, modifyOrder

import mysql.connector

os.environ["TOKENIZERS_PARALLELISM"] = "false"
load_dotenv("keys.env")
warnings.filterwarnings("ignore")

# --- IMPORTANT: MySQL DB_CONFIG for basic_nodes_bot ---
# Ensure these details match your 'restaurant_new_db' setup
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',        # Your MySQL username
    'password': '12345678', # Your MySQL password
    'database': os.getenv('DB_NAME') # The database where 'Orders' table is
}
# ----------------------------------------------------

# Establish a single, persistent MySQL connection for the bot's session
try:
    mysql_conn = mysql.connector.connect(**DB_CONFIG)
    print("MySQL connection established for basic_nodes_bot.")
except mysql.connector.Error as err:
    print(f"Error connecting to MySQL for basic_nodes_bot: {err}")
    mysql_conn = None # Set to None if connection fails

# Check if DB connection failed
if mysql_conn is None:
    print("FATAL: Database connection failed. Bot will not be able to save orders or deplete inventory.")

parser = PydanticOutputParser(pydantic_object=Order)
menu = pd.read_csv("sqldatafiles/meals_new.csv")

menu_searcher = MultiSearch(menu, bm_thresh= 0.01)

# Defining chains and tools
LLM_NAME="gpt-oss-120b-groq"

if LLM_NAME == "llama-local":
    llm = init_chat_model("ollama:llama3.1")
elif LLM_NAME == "gpt-oss-120b-groq":
    llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model='openai/gpt-oss-120b')
elif LLM_NAME == "gpt-oss-20b-groq":
    llm = ChatGroq(api_key=os.getenv("GROQ_API_KEY"), model='openai/gpt-oss-20b')


orderChain = orderPrompt | llm | parser
conversationChain = conversationPrompt | llm
routerChain = routerPrompt | llm

retriever = makeRetriever(menu, search_type="similarity", k=10)
corpus = list(menu["item_name"])
tcorpus = [c.lower().split() for c in corpus]
#bm_searcher = BM25Okapi(tcorpus)
embedder = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
vectordb = FAISS.from_texts(corpus, embedder)
emb_thresh=0.5
seq_thresh=0.5


def makegraph():
    builder = StateGraph(State)
    builder.add_node("router", lambda s: router_node(s, routerChain))
    builder.add_node("extract_order", lambda s: extract_order_node(s, orderChain, parser))
    builder.add_node("menu_query", lambda s: menu_query_node(s, conversationChain, retriever))
    builder.add_node("process_order", lambda s: processOrder(s, menu_searcher, None, vectordb, emb_thresh, seq_thresh))
    builder.add_node("delete_order", lambda s: deleteOrder(s, embedder, seq_thresh))
    builder.add_node("modify_order", lambda s: modifyOrder(s, embedder, seq_thresh))
    builder.add_node("confirm_order", confirm_order)
    builder.add_node("display_rejected", display_rejected)
    builder.add_node("clarify_options", clarify_options_node)
    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        "router",
        routeFunc, 
        {
            "extract": "extract_order",
            "conversation": "menu_query"
        }
    )
    
    builder.add_edge("extract_order", "delete_order")
    builder.add_edge("delete_order", "modify_order")
    builder.add_edge("modify_order", "process_order")
    builder.add_conditional_edges(
        "process_order",
        checkRejected, 
        {
            "summary_node": "confirm_order",
            "display_rejected": "display_rejected"
        }
    )
    builder.add_edge("confirm_order", END)
    builder.add_edge("display_rejected", END)
    builder.add_edge("menu_query", END)

    memory = MemorySaver()

    graph = builder.compile(checkpointer=memory)
    return graph


if __name__ == "__main__":
    graph = makegraph()
    draw = False

    if draw:
        ascii_rep = graph.get_graph().draw_ascii()
        print(ascii_rep)
        graph.get_graph().draw_png("graph.png")
        os.system("open graph.png")

    thread_id = "abc1234"
    config = {"configurable": {"thread_id": thread_id}}
        
    graph.update_state(config, {
        "cart": [],
        "rejected_items": []
    })

    try:
        while True:
            user_input = input("You: ")

            if user_input.lower().strip() in {"exit", "bye", "quit", "q"}:
                print("\nChatbot: Bye!")
                break

            if user_input.lower().strip() in {"checkout", "confirm", "yes", "y"}:
                current_cart = graph.get_state(config=config).values.get('cart', [])
                if current_cart:
                    insert_orders_from_bot(current_cart, mysql_conn, None)
                    print("\nChatbot: Order confirmed and will be sent to the Kitchen! Thank you.")
                    break
                else:
                    print("Chatbot: Your cart is empty, nothing to save.")
                    break
                        
            for update in graph.stream({"messages": [HumanMessage(user_input)]}, config=config):
                for step, output in update.items():
                    if "messages" in output:
                        for m in output["messages"]:
                            if isinstance(m, (AIMessage, ToolMessage)):
                                print(f"Chatbot: {m.content}")
            
    finally:
        if mysql_conn:
            mysql_conn.close()
            print("\nMySQL database connection closed.")
