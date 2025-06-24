from langchain_core.tools import tool
import asyncio
import traceback


@tool
async def retrieve_tool(query: str, top_k: int = 10) -> str:
    """Internal knowledge search tool for Channel Talk service information.

    This tool searches the internal Channel Talk knowledge base to find relevant
    information about features, usage, troubleshooting, and other service-related topics.

    Args:
        query: The search query to find relevant information
        top_k: Maximum number of search results to return (default: 10)

    Returns:
        Formatted string containing the search results
    """
    try:
        # Import here to avoid circular imports
        from agent.internal.retrieve import generate_embeddings, query_to_vss

        # Generate embeddings for the search query
        embeddings, latency = await generate_embeddings([query])

        # Perform vector search
        search_results = await query_to_vss(embeddings[0], query, top_k)

        if not search_results:
            return "검색 결과가 없습니다. 다른 키워드로 다시 시도해보세요."

        # Combine search results into a formatted response
        combined_results = ""
        for i, result in enumerate(search_results, 1):
            combined_results += f"{result.get('text', '')}\n\n"

        return combined_results.strip()

    except Exception as e:
        error_message = f"지식 검색 중 오류가 발생했습니다: {str(e)}"
        print(f"retrieve_tool 오류: {traceback.format_exc()}")
        return error_message


# List of available tools
TOOLS = [retrieve_tool]
