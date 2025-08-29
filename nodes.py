from Classes import State, Item
from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
from utils import get_context
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

def router_node(state: State, routerChain):
    """Routes user input to either order extraction or menu query."""
    messages = state["messages"]
    for m in messages[::-1]:
        if isinstance(m, HumanMessage):
            user_input = m.content
            break
    response = routerChain.invoke({"user_input": [user_input]})
    return {"internals": [response.content]}

def extract_order_node(state: State, orderChain, parser):
    """Extracts structured order JSON from user input."""
    messages = state["messages"]
    cart = state["cart"]
    for m in messages[::-1]:
        if isinstance(m, HumanMessage):
            user_input = m.content
            break
    
    try:
        result = orderChain.invoke({
            "user_input": user_input,
            "format_instructions": parser.get_format_instructions(),
            "cart": cart
        })
        return {"internals": [AIMessage(content=result.model_dump_json(), name="extract")], "most_recent_order": result}
    except Exception as e:
        print("order parsing error!")
        return {"messages": [AIMessage(content=f"Error parsing order: {str(e)}")]}
    
def menu_query_node(state: State, conversationChain, retriever):
    """Answers questions about the menu."""
    messages = state["messages"]
    for m in messages[::-1]:
        if isinstance(m, HumanMessage):
            user_input = m.content
            # print(f"DEBUG - PROCESSING MESSAGE: ")
            break

    # print(f"DEBUG - PROCESSING THIS MESSAGE - {user_input}")
    
    _, context = get_context(user_input, retriever)
    ai_response = conversationChain.invoke({
        "context": context,
        "user_input": user_input,
        "chat_history": messages
    })
    
    return {"messages": [AIMessage(content=ai_response.content)]}

def routeFunc(state: State):
    internals = state["internals"]
    last_m = internals[-1]

    if last_m.strip().lower() in ["extract", "conversation","menu_query"]:
        return last_m.strip().lower()
    else:
        print(f"unrecognized router output - {last_m}")
        return None

# save static version
# menuembeddings = embedder.encode(menu['item_name'].tolist())
# menuembeddings = menuembeddings/np.linalg.norm(menuembeddings, axis=1, keepdims=True)

import numpy as np
from difflib import SequenceMatcher

def cosine_similarity(query_emb, doc_embs):
    q = query_emb / np.linalg.norm(query_emb)
    d = doc_embs / np.linalg.norm(doc_embs, axis=1, keepdims=True)
    return np.dot(d, q)

def modifyOrder(state: State, embedder, seq_thresh=0.6):
    mro = state["most_recent_order"]
    cart = state["cart"]
    rej_items = []

    def sequenceMatch(item_name, seq_threshold, items):
        item_lower = item_name.lower().strip()
        res, scores = [], []
        for opt in items:
            similarity = SequenceMatcher(None, item_lower, opt.lower()).ratio()
            if similarity >= seq_threshold:
                res.append(opt)
                scores.append(similarity)
        if res:
            return {'found': True, 'items': res, 'scores': scores}
        return {'found': False, 'items': [], 'scores': []}

    for item in mro.modify:
        cart_names = [c.item_name for c in cart]
        if not cart_names:
            continue

        if item.item_name.lower().strip() in [c.lower() for c in cart_names]:
            target_names = [item.item_name]
        else:
            seq = sequenceMatch(item.item_name, seq_thresh, cart_names)
            query_emb = np.array(embedder.embed_query(item.item_name))
            cart_embs = np.array(embedder.embed_documents(cart_names))
            sims = cosine_similarity(query_emb, cart_embs)

            certain_match_seq = [n for n, s in zip(seq["items"], seq["scores"]) if s >= 0.8]
            certain_match_emb = [n for n, s in zip(cart_names, sims) if s >= 0.85]
            certain_set = list(set(certain_match_seq + certain_match_emb))

            if len(certain_set) == 1:
                target_names = certain_set
            elif len(certain_set) > 1:
                print(f"Multiple matches found for '{item.item_name}':")
                for i, opt in enumerate(certain_set, 1):
                    print(f"{i}. {opt}")
                try:
                    choice = int(input("Which one would you like to modify? ")) - 1
                    if 0 <= choice < len(certain_set):
                        target_names = [certain_set[choice]]
                    else:
                        print("Invalid choice. Skipping this item.")
                        continue
                except ValueError:
                    print("Invalid input. Skipping this item.")
                    continue
            else:
                good_match_seq = [n for n, s in zip(seq["items"], seq["scores"]) if s >= 0.6]
                good_match_emb = [n for n, s in zip(cart_names, sims) if s >= 0.5]
                good_set = list(set(good_match_seq + good_match_emb))

                if len(good_set) == 1:
                    target_names = good_set
                elif len(good_set) > 1:
                    print(f"Possible matches for '{item.item_name}':")
                    for i, opt in enumerate(good_set, 1):
                        print(f"{i}. {opt}")
                    try:
                        choice = int(input("Which one would you like to modify? ")) - 1
                        if 0 <= choice < len(good_set):
                            target_names = [good_set[choice]]
                        else:
                            print("Invalid choice. Skipping this item.")
                            continue
                    except ValueError:
                        print("Invalid input. Skipping this item.")
                        continue
                else:
                    maxidx = np.argmax(sims)
                    rej_items.append((item.item_name, cart_names[maxidx]))
                    continue

        for target in target_names:
            for i, added_item in enumerate(cart):
                if target.lower().strip() == added_item.item_name.lower().strip():
                    if item.quantity:
                        cart[i].quantity = item.quantity
                    if item.modifiers:
                        cart[i].modifiers.extend(item.modifiers)
                    break

    return {"cart": cart, "rejected_items": rej_items}


def deleteOrder(state: State, embedder, seq_thresh=0.6):
    mro = state["most_recent_order"]
    cart = state["cart"]
    rej_items = []

    # sequenceMatch function (pulled from MultiSearch)
    def sequenceMatch(item_name, seq_threshold, items):
        item_lower = item_name.lower().strip()
        res, scores = [], []
        for opt in items:
            similarity = SequenceMatcher(None, item_lower, opt.lower()).ratio()
            if similarity >= seq_threshold:
                res.append(opt)
                scores.append(similarity)
        if res:
            return {'found': True, 'items': res, 'scores': scores}
        return {'found': False, 'items': [], 'scores': []}
    target_names=[]
    for item in mro.delete:
        cart_names = [c.item_name for c in cart]
        if not cart_names:
            continue

        # 1. exact match
        if item.item_name.lower().strip() in [c.lower() for c in cart_names]:
            target_names.append(item.item_name)
        else:
            # 2. sequence matching
            seq = sequenceMatch(item.item_name, seq_thresh, cart_names)

            # 3. embedding cosine similarity
            query_emb = np.array(embedder.embed_query(item.item_name))
            cart_embs = np.array(embedder.embed_documents(cart_names))
            sims = cosine_similarity(query_emb, cart_embs)

            # classify matches
            certain_match_seq = [n for n, s in zip(seq["items"], seq["scores"]) if s >= 0.8]
            certain_match_emb = [n for n, s in zip(cart_names, sims) if s >= 0.85]
            certain_set = list(set(certain_match_seq + certain_match_emb))

            if len(certain_set) == 1:
                target_names.append(certain_set[0])
            elif len(certain_set) > 1:
                print(f"Multiple matches found for '{item.item_name}':")
                for i, opt in enumerate(certain_set, 1):
                    print(f"{i}. {opt}")
                try:
                    choice = int(input("Which one would you like to remove? ")) - 1
                    if 0 <= choice < len(certain_set):
                        target_names.append(certain_set[choice])
                    else:
                        print("Invalid choice. Skipping this item.")
                        continue
                except ValueError:
                    print("Invalid input. Skipping this item.")
                    continue
            else:
                good_match_seq = [n for n, s in zip(seq["items"], seq["scores"]) if s >= 0.6]
                good_match_emb = [n for n, s in zip(cart_names, sims) if s >= 0.5]
                good_set = list(set(good_match_seq + good_match_emb))

                if len(good_set) == 1:
                    target_names.append(good_set[0])
                elif len(good_set) > 1:
                    print(f"Possible matches for '{item.item_name}':")
                    for i, opt in enumerate(good_set, 1):
                        print(f"{i}. {opt}")
                    try:
                        choice = int(input("Which one would you like to remove? ")) - 1
                        if 0 <= choice < len(good_set):
                            target_names.append(good_set[choice])
                        else:
                            print("Invalid choice. Skipping this item.")
                            continue
                    except ValueError:
                        print("Invalid input. Skipping this item.")
                        continue
                else:
                    # rejection case → suggest closest by embedding
                    maxidx = np.argmax(sims)
                    rej_items.append((item.item_name, cart_names[maxidx]))
                    continue
        print(target_names)

    # perform deletion
    for target in target_names:
        print('here')
        for i, added_item in enumerate(cart):
            if target.lower().strip() == added_item.item_name.lower().strip() and item.modifiers == added_item.modifiers:
                cart[i].quantity -= item.quantity
                deleted = True
                break
            elif target.lower().strip() == added_item.item_name.lower().strip():
                cart[i].quantity -= item.quantity
                deleted = True
                break
    print("should always print!")
    cart = [c for c in cart if c.quantity > 0]
    return {"cart": cart, "rejected_items": rej_items}



def processOrder(state: State, menu_searcher, bm_searcher, vectordb, emb_thresh, seq_thresh):
    mro = state["most_recent_order"]
    cart = state["cart"]
    rej_items = []
        
    new_messages = []
    # print(f"mro items - {mro.items}")
    # print(f"mro delete - {mro.delete}")
    for item in mro.items:
        # pass something to internal for each of the 3 scenarios so you can make conditional edges for all 3 later.
        # print(type(mro), type(item), type(mro.model_dump_json()))
        result = menu_searcher.unify(item.item_name, bm_searcher=bm_searcher, vectordb=vectordb, emb_thresh=emb_thresh, seq_thresh=seq_thresh)
        
        if result.get('exact', False):
            # Exact match
            cart.append(Item(item_name=result['item'], quantity=item.quantity, modifiers=item.modifiers))
        else:
            # no exact
            # 3 scenarios
            # 1. one very good match -> add directly to cart
            # 2. multiple good matches -> ask for clarification
            # 3. no good matches -> reject, and show best alternative (maybe use metadata based retriever which will be used by menu query)

            # certain match - 0.85 emb, 0.8 seq
            # good match - 0.5 emb, 0.6 seq
            # bad match - everything else

            # one certain match
            seq = result["seq"]
            emb = result["emb"]

            # print(seq)

            certain_match_seq = [item for item, score in zip(seq["items"], seq["scores"]) if score >= 0.8]
            certain_match_emb = [item for item, score in zip(emb["items"], emb["scores"]) if score >= 0.85]

            certain_set = set(certain_match_seq + certain_match_emb)
            if len(certain_set) == 1:
                # add to cart
                item_name = list(certain_set)[0]
                cart.append(Item(item_name=item_name, quantity=item.quantity, modifiers=item.modifiers))
                continue

            elif len(certain_set) > 1:
                # clarify -> go to clarify node to display options. or call a clarify function to do it here itself dont need another node?
                s = f"We have the following options related to {item.item_name} -\n" + "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(certain_set))
                new_messages.append(AIMessage(s))
                continue
            
            # no certains if code reaches here
            
            good_match_seq = [item for item, score in zip(seq["items"], seq["scores"]) if score >= 0.6]
            good_match_emb = [item for item, score in zip(emb["items"], emb["scores"]) if score >= 0.5]
            good_set = set(good_match_emb + good_match_seq)

            if len(good_set) != 0:
                # clarification
                s = f"We have the following options related to {item.item_name} -\n" + "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(good_set))
                new_messages.append(AIMessage(s))
                continue
            else:
                # bad. rejection logic.
                similars = menu_searcher.embeddingSearch(item.item_name, vectordb=vectordb, emb_thresh=0)
                # if not similars["found"]:
                #     new_messages.append(AIMessage())

                maxidx = np.argmax(similars["scores"])
                rej_items.append((item.item_name, similars["items"][maxidx]))

    
    print(f"Your cart is now {cart}")

    return {
        "messages": new_messages,
        "cart": cart,
        "rejected_items": rej_items
    }

def summary_node(state: State):
    """Generates a summary of the current order cart."""
    cart = state.get("cart", [])
    if not cart:
        summary = "Your cart is empty."
    else:
        items = []
        for item in cart:
            item_desc = f"{item.quantity} x {item.item_name}"
            if hasattr(item, "modifiers") and item.modifiers:
                item_desc += f" ({', '.join(item.modifiers)})"
            items.append(item_desc)
        summary = "Your order:\n" + "\n".join(items)
    msg = AIMessage(content=summary, name="order_summary")
    return {"messages": [msg]}

def confirm_order(state: State):
    """Prepares a confirmation message for the user's order."""
    cart = state.get("cart", [])
    if not cart:
        summary = "Your cart is empty."
    else:
        items = []
        for item in cart:
            item_desc = f"{item.quantity} x {item.item_name}"
            if item.modifiers:
                item_desc += f" ({', '.join(item.modifiers)})"
            items.append(item_desc)
        summary = "Your order:\n" + "\n".join(items)
    msg = AIMessage(
        content=f"\nIf you are done ordering, confirm and place your order by typing 'yes'.",
        name="confirm_order"
    )
    return {"messages": [msg]}

def checkRejected(state: State):
    rej_items = state.get("rejected_items", [])
    if not len(rej_items):
        return "summary_node"
    else:
        return "display_rejected"

def display_rejected(state: State):
    rej_items = state.get("rejected_items", [])

    m = AIMessage(f"The following items - {[n for (n, m) in rej_items]} are unavailable. You can try these alternatives from our menu instead: {[m for (n, m) in rej_items]}", name="display_rejected")

    return {"messages": [m]}


def clarify_options_node(state: State):
    """Provides clarification options for rejected items."""
    rejected = state.get("rejected_items", [])
    if rejected:
        message = "I'm sorry, we don't have that exact item. Did you mean one of these?\n"
        for item in rejected:
            original = item.get('original_request', 'N/A')
            similar = item.get('similar_items', [])
            
            if similar:
                message += f"For '{original}', you can choose from: {', '.join(similar)}\n"
            else:
                message += f"I can't find '{original}'. Is there something similar you'd like?\n"
    else:
        message = "There are no rejected items to clarify."
    
    return {"messages": [AIMessage(content=message)]}

