"""
Tavily Search Tool integration for AutoGen agents.
Provides real-time web search for destinations, accommodations, attractions, and travel advice.
"""
from typing import Optional
from config.settings import TAVILY_API_KEY
from langchain_tavily import TavilySearch
from autogen_core.tools import FunctionTool


def create_travel_specific_search_tool(
    api_key: Optional[str] = None,
    max_results: int = 3,
) -> FunctionTool:
    """
    Create a travel-specific search tool with customized instructions.

    Args:
        api_key: Optional Tavily API key. If omitted, uses TAVILY_API_KEY from config.
        max_results: Maximum number of search results to return.

    Returns:
        FunctionTool: Clean FunctionTool ready for AutoGen agents and Gemini.
    """
    effective_key = api_key or TAVILY_API_KEY
    if not effective_key:
        raise ValueError(
            "TAVILY_API_KEY is missing. Please set TAVILY_API_KEY in your .env file or environment."
        )

    tavily_client = TavilySearch(
        tavily_api_key=effective_key,
        max_results=max_results,
        include_answer=True,
        include_raw_content=False,
        include_images=False,
    )

    def travel_search(query: str) -> str:
        """Search for current travel-related information including destinations, hotels,
        restaurants, attractions, transportation, activities, and practical travel advice.
        Use this tool to find real-time, verified information for trip planning."""
        try:
            res = tavily_client.invoke({"query": query})
            return str(res)
        except Exception as e:
            return f"Search error for query '{query}': {str(e)}"

    return FunctionTool(
        travel_search,
        name="travel_search",
        description=(
            "Search for current travel-related information including destinations, hotels, "
            "restaurants, attractions, transportation, activities, and practical travel advice. "
            "Use this tool to find real-time, verified information for trip planning."
        ),
    )
