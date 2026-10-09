from langchain_core.tools import tool


@tool
def search_claims(query: str) -> str:
    """Search the claims index."""
    return query
