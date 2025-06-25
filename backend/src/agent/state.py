from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypedDict

from langgraph.graph import add_messages
from typing_extensions import Annotated


import operator


class OverallState(TypedDict):
    """Main state used throughout the entire graph"""

    # Message related
    messages: Annotated[list, add_messages]
    original_input: str

    # Search query related
    search_query: Annotated[list[str], operator.add]
    initial_search_query_count: int

    # Search results related
    web_research_result: Annotated[list, operator.add]
    knowledge_search_result: Annotated[list, operator.add]
    sources_gathered: Annotated[list, operator.add]

    # Research loop control
    max_research_loops: int
    research_loop_count: int
    number_of_ran_queries: int

    # Model configuration
    reasoning_model: str

    # Search necessity determination
    needs_web_search: bool
    needs_knowledge_search: bool
    query_classification: str

    # Guardrail related
    is_safe_input: bool
    guardrail_violations: Annotated[list[str], operator.add]

    # Intent clarification related
    is_clear_intent: bool
    clarification_questions: Annotated[list[str], operator.add]
    needs_clarification: bool
    intent_clarify_count: int

    # Reflection related
    knowledge_gap: str
    follow_up_queries: Annotated[list[str], operator.add]
    is_sufficient: bool


class ReflectionState(TypedDict):
    """State for reflection on web search and knowledge search results"""

    is_sufficient: bool
    knowledge_gap: str
    follow_up_queries: Annotated[list, operator.add]
    research_loop_count: int
    number_of_ran_queries: int


class Query(TypedDict):
    """Individual search query structure"""

    query: str
    rationale: str


class QueryGenerationState(TypedDict):
    """Query generation node state"""

    search_query: list[Query]


class QueryClassificationState(TypedDict):
    """Query classification node state"""

    needs_web_search: bool
    needs_knowledge_search: bool
    reasoning: str
    query_type: str


class WebSearchState(TypedDict):
    """Web search node state"""

    search_query: str
    id: str
    messages: Annotated[list, add_messages]


class KnowledgeSearchState(TypedDict):
    """Knowledge search node state"""

    search_query: str
    id: str
    messages: Annotated[list, add_messages]


@dataclass(kw_only=True)
class SearchStateOutput:
    """Final output state for search results"""

    running_summary: str = field(default=None)  # Final report
