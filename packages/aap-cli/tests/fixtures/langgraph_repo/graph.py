from langgraph.graph import StateGraph


def build_graph() -> StateGraph:
    g = StateGraph(dict)
    g.add_node("triage", lambda s: s)
    return g


def refund_tool(amount: int) -> str:
    return str(amount)
