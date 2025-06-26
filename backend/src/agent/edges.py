from langgraph.types import Send
from agent.state import (
    OverallState,
    QueryGenerationState,
    ReflectionState,
    QueryClassificationState,
)
from agent.configuration import Configuration


def route_after_guardrail(state: OverallState) -> str:
    """LangGraph routing function that determines whether input is safe to proceed.

    Routes based on guardrail validation result - either proceeds to query classification
    or blocks the request with an error response.

    Args:
        state: Current graph state containing the guardrail validation result

    Returns:
        String literal indicating the next node to visit ("classify_query" or "guardrail_block")
    """
    if state["is_safe_input"]:
        return "classify_query"
    else:
        return "guardrail_block"


def route_after_classification(state: QueryClassificationState) -> str:
    """LangGraph routing function that determines whether to check intent clarity or provide direct answer.

    Routes the query based on the classification result - either to intent clarity check
    for search-required queries, or direct answer for general knowledge.

    Args:
        state: Current graph state containing the classification result

    Returns:
        String literal indicating the next node to visit ("intent_clarify" or "direct_answer")
    """
    if state["needs_web_search"] or state["needs_knowledge_search"]:
        return "intent_clarify"
    else:
        return "direct_answer"


def route_after_intent_clarify_search(state: OverallState, config) -> str:
    """LangGraph routing function that routes to appropriate search type after intent clarification.

    Determines whether to proceed with web search, knowledge search, or provide clarification
    based on the intent clarity and query classification results. Enforces maximum clarification attempts.

    Args:
        state: Current graph state containing the intent clarity and classification results
        config: Configuration for the runnable, including max_intent_clarify_attempts and enable_intent_clarify settings

    Returns:
        String literal indicating the next node to visit
    """
    from agent.configuration import Configuration

    configurable = Configuration.from_runnable_config(config)
    current_count = state.get("intent_clarify_count", 0)

    # If intent clarification is disabled, skip clarification and proceed directly
    if not configurable.enable_intent_clarify:
        print("Intent clarification이 비활성화되어 다음 단계로 진행합니다.")
        # Proceed based on configuration or original classification
        if state.get("needs_web_search"):
            return "generate_query"
        elif state.get("needs_knowledge_search"):
            return "generate_knowledge_query"
        else:
            return "direct_answer"

    # If we've reached the maximum clarification attempts, force proceed with search or direct answer
    if current_count >= configurable.max_intent_clarify_attempts:
        print(
            f"Intent clarification 최대 횟수 도달 ({current_count}번), 검색으로 진행합니다."
        )
        # Force proceed based on original classification
        if state.get("needs_web_search"):
            return "generate_query"
        elif state.get("needs_knowledge_search"):
            return "generate_knowledge_query"
        else:
            return "direct_answer"

    # Normal flow - check if clarification is needed
    if not state["needs_clarification"]:
        return "provide_clarification"

    # Check the original classification to determine search type
    if state.get("needs_web_search"):
        return "generate_query"
    elif state.get("needs_knowledge_search"):
        return "generate_knowledge_query"
    else:
        # Fallback to direct answer if no search is needed
        return "direct_answer"


def continue_to_web_research(state: OverallState):
    """LangGraph node that sends the search queries to the web research node.

    This is used to spawn n number of web research nodes, one for each search query.
    """
    return [
        Send(
            "web_research",
            {
                "search_query": search_query,
                "id": int(idx),
                "messages": state["messages"],
            },
        )
        for idx, search_query in enumerate(state["search_query"])
    ]


def continue_to_knowledge_search(state: OverallState):
    """LangGraph node that sends the search queries to the knowledge search node.

    This is used to spawn n number of knowledge search nodes, one for each search query.
    """
    return [
        Send(
            "knowledge_search",
            {
                "search_query": search_query,
                "id": int(idx),
                "messages": state["messages"],
            },
        )
        for idx, search_query in enumerate(state["search_query"])
    ]


def evaluate_research(
    state: OverallState,
    config,
) -> OverallState:
    """LangGraph routing function that determines the next step in the research flow.

    Controls the research loop by deciding whether to continue gathering information
    or to finalize the summary based on the configured maximum number of research loops.

    Args:
        state: Current graph state containing the research loop count
        config: Configuration for the runnable, including max_research_loops setting

    Returns:
        String literal indicating the next node to visit ("web_research" or "finalize_summary")
    """
    configurable = Configuration.from_runnable_config(config)
    max_research_loops = (
        state.get("max_research_loops")
        if state.get("max_research_loops") is not None
        else configurable.max_research_loops
    )
    if state["is_sufficient"] or state["research_loop_count"] >= max_research_loops:
        return "finalize_answer"
    else:
        return [
            Send(
                "web_research",
                {
                    "search_query": follow_up_query,
                    "id": state["number_of_ran_queries"] + int(idx),
                    "messages": state["messages"],
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


def evaluate_knowledge_search(
    state: OverallState,
    config,
) -> OverallState:
    """LangGraph routing function that determines the next step in the knowledge search flow.

    Controls the knowledge search loop by deciding whether to continue gathering information
    or to finalize the summary based on the configured maximum number of research loops.

    Args:
        state: Current graph state containing the research loop count
        config: Configuration for the runnable, including max_research_loops setting

    Returns:
        String literal indicating the next node to visit ("knowledge_search" or "finalize_answer")
    """
    configurable = Configuration.from_runnable_config(config)
    max_research_loops = (
        state.get("max_research_loops")
        if state.get("max_research_loops") is not None
        else configurable.max_research_loops
    )
    if state["is_sufficient"] or state["research_loop_count"] >= max_research_loops:
        return "finalize_answer"
    else:
        return [
            Send(
                "knowledge_search",
                {
                    "search_query": follow_up_query,
                    "id": state["number_of_ran_queries"] + int(idx),
                    "messages": state["messages"],
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]
