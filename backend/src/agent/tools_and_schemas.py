from typing import List
from pydantic import BaseModel, Field


class SearchQueryList(BaseModel):
    """List of search queries to use for web research."""

    query: list[str] = Field(description="A list of search queries.")
    rationale: str = Field(
        description="The reasoning behind the search queries.",
    )


class Reflection(BaseModel):
    """Reflection on the search results."""

    is_sufficient: bool = Field(
        description="Whether the search results are sufficient to answer the question.",
    )
    knowledge_gap: str = Field(
        description="Description of what information is missing or needs clarification.",
    )
    follow_up_queries: list[str] = Field(
        description="A list of follow-up queries to address knowledge gaps.",
    )


class QueryClassification(BaseModel):
    """Classification of whether a query needs web search or can be answered directly."""

    needs_web_search: bool = Field(
        description="Whether the query requires web search for current/real-time information."
    )
    needs_knowledge_search: bool = Field(
        description="Whether the query requires internal knowledge search for Channel Talk service-related information."
    )
    reasoning: str = Field(
        description="Explanation of why web search or knowledge search is or isn't needed."
    )
    query_type: str = Field(
        description="Type of query: 'smalltalk', 'general_knowledge', 'current_events', 'factual_lookup', 'channel_talk_service', etc."
    )


class KnowledgeSearchResult(BaseModel):
    """Result from knowledge search."""

    results: list[dict] = Field(
        description="List of search results containing text and metadata."
    )
    query_used: str = Field(description="The actual query used for the search.")
    total_results: int = Field(description="Total number of results found.")
