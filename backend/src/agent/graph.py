import os
import traceback

from agent.tools_and_schemas import (
    SearchQueryList,
    Reflection,
    QueryClassification,
    InputGuardrailResult,
)
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langgraph.types import Send
from langgraph.graph import StateGraph
from langgraph.graph import START, END
from langchain_core.runnables import RunnableConfig
from google.genai import Client

from agent.state import (
    OverallState,
    QueryGenerationState,
    ReflectionState,
    WebSearchState,
    KnowledgeSearchState,
    QueryClassificationState,
)
from agent.configuration import Configuration
from agent.prompts import (
    get_current_date,
    query_writer_instructions,
    knowledge_query_writer_instructions,
    web_searcher_instructions,
    knowledge_searcher_instructions,
    reflection_instructions,
    knowledge_reflection_instructions,
    answer_instructions,
    query_classification_instructions,
    direct_answer_instructions,
    input_guardrail_instructions,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from agent.utils import (
    get_citations,
    get_research_topic,
    insert_citation_markers,
    resolve_urls,
)
from agent.tools.retrieve import generate_embeddings, query_to_vss

load_dotenv()

if os.getenv("GEMINI_API_KEY") is None:
    raise ValueError("GEMINI_API_KEY is not set")

# Used for Google Search API
genai_client = Client(api_key=os.getenv("GEMINI_API_KEY"))


# Nodes
def input_guardrail(state: OverallState, config: RunnableConfig) -> OverallState:
    """LangGraph node that validates user input against security guardrails.

    Checks for potential security threats including:
    - System prompt injection attempts
    - Discriminatory or hateful language
    - Personal information extraction attempts
    - Illegal activity requests

    Args:
        state: Current graph state containing the user's messages
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including is_safe_input, guardrail_violations, and original_input
    """
    configurable = Configuration.from_runnable_config(config)

    # Extract the latest user message
    user_messages = [
        msg for msg in state["messages"] if hasattr(msg, "type") and msg.type == "human"
    ]
    if not user_messages:
        # No user messages found, treat as safe
        return {
            "is_safe_input": True,
            "guardrail_violations": [],
            "original_input": "",
        }

    latest_user_input = user_messages[-1].content

    # init Gemini 2.0 Flash for guardrail validation
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=0.1,  # Low temperature for consistent security decisions
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(InputGuardrailResult)

    # Format the prompt with user input
    formatted_prompt = input_guardrail_instructions.format(user_input=latest_user_input)

    # Validate the input
    try:
        result = structured_llm.invoke(formatted_prompt)

        return {
            "is_safe_input": result.is_safe,
            "guardrail_violations": result.violations,
            "original_input": latest_user_input,
        }
    except Exception as e:
        # In case of error, err on the side of safety
        print(f"InputGuardrail 오류 발생: {traceback.format_exc()}")
        return {
            "is_safe_input": False,
            "guardrail_violations": ["시스템 오류로 인한 안전성 확인 불가"],
            "original_input": latest_user_input,
        }


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


def guardrail_block(state: OverallState, config: RunnableConfig) -> OverallState:
    """LangGraph node that handles blocked requests due to guardrail violations.

    Provides a user-friendly response explaining why the request was blocked
    without revealing specific security details.

    Args:
        state: Current graph state containing the guardrail violations
        config: Configuration for the runnable

    Returns:
        Dictionary with state update, including a blocking message
    """
    # Create a user-friendly error message
    block_message = """죄송합니다. 요청하신 내용이 다음과 같은 이유로 처리될 수 없습니다:

🛡️ **보안 정책 위반 감지**

안전하고 건전한 서비스 제공을 위해 다음과 같은 내용은 제한됩니다:
• 시스템 보안을 우회하려는 시도
• 차별적이거나 혐오적인 표현
• 개인정보나 민감정보 요구
• 불법적인 활동과 관련된 요청

💡 **대신 이런 질문을 해보세요:**
• 채널톡의 기능이나 사용법에 대한 문의
• 일반적인 정보나 지식에 대한 질문
• 건설적이고 도움이 되는 대화

다시 한번 정중하고 적절한 질문으로 문의해 주시면 성심껏 도와드리겠습니다."""

    return {
        "messages": [AIMessage(content=block_message)],
    }


def classify_query(
    state: OverallState, config: RunnableConfig
) -> QueryClassificationState:
    """LangGraph node that classifies whether a query needs web search, knowledge search, or can be answered directly.

    Analyzes the user's question to determine if it requires current/real-time information
    that would need web search, Channel Talk internal knowledge search, or if it can be answered directly with general knowledge.

    Args:
        state: Current graph state containing the user's question
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including needs_web_search, needs_knowledge_search and query classification info
    """
    configurable = Configuration.from_runnable_config(config)

    # init Gemini 2.0 Flash
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=0.3,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(QueryClassification)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = query_classification_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
    )

    # Classify the query
    result = structured_llm.invoke(formatted_prompt)

    return {
        "needs_web_search": result.needs_web_search,
        "needs_knowledge_search": result.needs_knowledge_search,
        "query_classification": result.query_type,
    }


def direct_answer(state: OverallState, config: RunnableConfig) -> OverallState:
    """LangGraph node that provides direct answers without web search.

    Responds to queries that don't require current information using the model's
    general knowledge, suitable for smalltalk, general questions, and established facts.

    Args:
        state: Current graph state containing the user's question
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including the direct answer message
    """
    configurable = Configuration.from_runnable_config(config)
    reasoning_model = state.get("reasoning_model", configurable.answer_model)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = direct_answer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
    )

    # init LLM for direct answer
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=0.7,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )

    result = llm.invoke(formatted_prompt)

    return {
        "messages": [AIMessage(content=result.content)],
    }


def route_after_classification(state: QueryClassificationState) -> str:
    """LangGraph routing function that determines whether to use web search, knowledge search, or direct answer.

    Routes the query based on the classification result - either to web research
    for current information, knowledge search for Channel Talk information, or direct answer for general knowledge.

    Args:
        state: Current graph state containing the classification result

    Returns:
        String literal indicating the next node to visit ("generate_query", "generate_knowledge_query", or "direct_answer")
    """
    if state["needs_web_search"]:
        return "generate_query"
    elif state["needs_knowledge_search"]:
        return "generate_knowledge_query"
    else:
        return "direct_answer"


def generate_query(state: OverallState, config: RunnableConfig) -> QueryGenerationState:
    """LangGraph node that generates search queries based on the User's question.

    Uses Gemini 2.0 Flash to create an optimized search queries for web research based on
    the User's question.

    Args:
        state: Current graph state containing the User's question
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including search_query key containing the generated queries
    """
    configurable = Configuration.from_runnable_config(config)

    # check for custom initial search query count
    if state.get("initial_search_query_count") is None:
        state["initial_search_query_count"] = configurable.number_of_initial_queries

    # init Gemini 2.0 Flash
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(SearchQueryList)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = query_writer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        number_queries=state["initial_search_query_count"],
    )
    # Generate the search queries
    result = structured_llm.invoke(formatted_prompt)
    return {"search_query": result.query}


def continue_to_web_research(state: QueryGenerationState):
    """LangGraph node that sends the search queries to the web research node.

    This is used to spawn n number of web research nodes, one for each search query.
    """
    return [
        Send("web_research", {"search_query": search_query, "id": int(idx)})
        for idx, search_query in enumerate(state["search_query"])
    ]


def web_research(state: WebSearchState, config: RunnableConfig) -> OverallState:
    """LangGraph node that performs web research using the native Google Search API tool.

    Executes a web search using the native Google Search API tool in combination with Gemini 2.0 Flash.

    Args:
        state: Current graph state containing the search query and research loop count
        config: Configuration for the runnable, including search API settings

    Returns:
        Dictionary with state update, including sources_gathered, research_loop_count, and web_research_results
    """
    # Configure
    configurable = Configuration.from_runnable_config(config)
    formatted_prompt = web_searcher_instructions.format(
        current_date=get_current_date(),
        research_topic=state["search_query"],
    )

    # Uses the google genai client as the langchain client doesn't return grounding metadata
    response = genai_client.models.generate_content(
        model=configurable.query_generator_model,
        contents=formatted_prompt,
        config={
            "tools": [{"google_search": {}}],
            "temperature": 0,
        },
    )
    # resolve the urls to short urls for saving tokens and time
    resolved_urls = resolve_urls(
        response.candidates[0].grounding_metadata.grounding_chunks, state["id"]
    )
    # Gets the citations and adds them to the generated text
    citations = get_citations(response, resolved_urls)
    modified_text = insert_citation_markers(response.text, citations)
    sources_gathered = [item for citation in citations for item in citation["segments"]]

    return {
        "sources_gathered": sources_gathered,
        "search_query": [state["search_query"]],
        "web_research_result": [modified_text],
    }


def reflection(state: OverallState, config: RunnableConfig) -> ReflectionState:
    """LangGraph node that identifies knowledge gaps and generates potential follow-up queries.

    Analyzes the current summary to identify areas for further research and generates
    potential follow-up queries. Uses structured output to extract
    the follow-up query in JSON format.

    Args:
        state: Current graph state containing the running summary and research topic
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including search_query key containing the generated follow-up query
    """
    configurable = Configuration.from_runnable_config(config)
    # Increment the research loop count and get the reasoning model
    state["research_loop_count"] = state.get("research_loop_count", 0) + 1
    reasoning_model = state.get("reasoning_model", configurable.reflection_model)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = reflection_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n\n---\n\n".join(state["web_research_result"]),
    )
    # init Reasoning Model
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    result = llm.with_structured_output(Reflection).invoke(formatted_prompt)

    return {
        "is_sufficient": result.is_sufficient,
        "knowledge_gap": result.knowledge_gap,
        "follow_up_queries": result.follow_up_queries,
        "research_loop_count": state["research_loop_count"],
        "number_of_ran_queries": len(state["search_query"]),
    }


def evaluate_research(
    state: ReflectionState,
    config: RunnableConfig,
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
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


def finalize_answer(state: OverallState, config: RunnableConfig):
    """LangGraph node that finalizes the research summary.

    Prepares the final output by deduplicating and formatting sources, then
    combining them with the running summary to create a well-structured
    research report with proper citations. Handles both web search and knowledge search results.

    Args:
        state: Current graph state containing the running summary and sources gathered

    Returns:
        Dictionary with state update, including running_summary key containing the formatted final summary with sources
    """
    configurable = Configuration.from_runnable_config(config)
    reasoning_model = state.get("reasoning_model") or configurable.answer_model

    # Combine web search and knowledge search results
    all_summaries = []
    if state.get("web_research_result"):
        all_summaries.extend(state["web_research_result"])
    if state.get("knowledge_search_result"):
        all_summaries.extend(state["knowledge_search_result"])

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = answer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n---\n\n".join(all_summaries),
    )

    # init Reasoning Model, default to Gemini 2.5 Flash
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    result = llm.invoke(formatted_prompt)

    # Replace the short urls with the original urls and add all used urls to the sources_gathered (for web search)
    unique_sources = []
    if state.get("sources_gathered"):
        for source in state["sources_gathered"]:
            if source["short_url"] in result.content:
                result.content = result.content.replace(
                    source["short_url"], source["value"]
                )
                unique_sources.append(source)

    return {
        "messages": [AIMessage(content=result.content)],
        "sources_gathered": unique_sources,
    }


def generate_knowledge_query(
    state: OverallState, config: RunnableConfig
) -> QueryGenerationState:
    """LangGraph node that generates knowledge search queries based on the User's question.

    Uses Gemini 2.0 Flash to create optimized search queries for Channel Talk knowledge base research based on
    the User's question.

    Args:
        state: Current graph state containing the User's question
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including search_query key containing the generated queries
    """
    configurable = Configuration.from_runnable_config(config)

    # check for custom initial search query count
    if state.get("initial_search_query_count") is None:
        state["initial_search_query_count"] = configurable.number_of_initial_queries

    # init Gemini 2.0 Flash
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(SearchQueryList)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = knowledge_query_writer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        number_queries=state["initial_search_query_count"],
    )
    # Generate the search queries
    result = structured_llm.invoke(formatted_prompt)
    return {"search_query": result.query}


def continue_to_knowledge_search(state: QueryGenerationState):
    """LangGraph node that sends the search queries to the knowledge search node.

    This is used to spawn n number of knowledge search nodes, one for each search query.
    """
    return [
        Send("knowledge_search", {"search_query": search_query, "id": int(idx)})
        for idx, search_query in enumerate(state["search_query"])
    ]


def knowledge_search(
    state: KnowledgeSearchState, config: RunnableConfig
) -> OverallState:
    """LangGraph node that performs knowledge search using the internal Channel Talk knowledge base.

    Executes a knowledge search using the retrieve.py tool to search Channel Talk internal documentation.

    Args:
        state: Current graph state containing the search query and id
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including knowledge_search_result key containing the search results
    """
    import asyncio

    configurable = Configuration.from_runnable_config(config)
    formatted_prompt = knowledge_searcher_instructions.format(
        research_topic=state["search_query"],
    )

    async def _async_search():
        try:
            # Generate embeddings for the search query
            embeddings, latency = await generate_embeddings([state["search_query"]])

            # Perform vector search
            search_results = await query_to_vss(
                embeddings[0], state["search_query"], 10
            )

            if not search_results:
                return {
                    "knowledge_search_result": [
                        "검색 결과가 없습니다. 다른 키워드로 다시 시도해보세요."
                    ],
                    "search_query": [],
                }

            # Combine search results into a formatted response
            combined_results = ""
            for i, result in enumerate(search_results, 1):
                combined_results += f"{result.get('text', '')}\n\n"

            return {
                "knowledge_search_result": [combined_results],
                "search_query": [state["search_query"]],
            }

        except Exception as e:
            print(f"지식 검색 중 오류가 발생했습니다: {traceback.format_exc()}")
            error_message = f"지식 검색 중 오류가 발생했습니다: {str(e)}"
            return {"knowledge_search_result": [error_message]}

    # Run the async search
    return asyncio.run(_async_search())


def knowledge_reflection(
    state: OverallState, config: RunnableConfig
) -> ReflectionState:
    """LangGraph node that identifies knowledge gaps and generates potential follow-up queries for Channel Talk knowledge.

    Analyzes the current knowledge search results to identify areas for further research and generates
    potential follow-up queries. Uses structured output to extract
    the follow-up query in JSON format.

    Args:
        state: Current graph state containing the knowledge search results and research topic
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including search_query key containing the generated follow-up query
    """
    configurable = Configuration.from_runnable_config(config)
    # Increment the research loop count and get the reasoning model
    state["research_loop_count"] = state.get("research_loop_count", 0) + 1
    reasoning_model = state.get("reasoning_model", configurable.reflection_model)

    # Format the prompt
    current_date = get_current_date()
    formatted_prompt = knowledge_reflection_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n\n---\n\n".join(state["knowledge_search_result"]),
    )
    # init Reasoning Model
    llm = ChatGoogleGenerativeAI(
        model=reasoning_model,
        temperature=1.0,
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    result = llm.with_structured_output(Reflection).invoke(formatted_prompt)

    return {
        "is_sufficient": result.is_sufficient,
        "knowledge_gap": result.knowledge_gap,
        "follow_up_queries": result.follow_up_queries,
        "research_loop_count": state["research_loop_count"],
        "number_of_ran_queries": len(state["search_query"]),
    }


def evaluate_knowledge_search(
    state: ReflectionState,
    config: RunnableConfig,
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
                },
            )
            for idx, follow_up_query in enumerate(state["follow_up_queries"])
        ]


# Create our Agent Graph
builder = StateGraph(OverallState, config_schema=Configuration)

# Define the nodes we will cycle between
builder.add_node("input_guardrail", input_guardrail)
builder.add_node("guardrail_block", guardrail_block)
builder.add_node("classify_query", classify_query)
builder.add_node("direct_answer", direct_answer)
builder.add_node("generate_query", generate_query)
builder.add_node("web_research", web_research)
builder.add_node("reflection", reflection)
builder.add_node("finalize_answer", finalize_answer)
builder.add_node("generate_knowledge_query", generate_knowledge_query)
builder.add_node("knowledge_search", knowledge_search)
builder.add_node("knowledge_reflection", knowledge_reflection)

# Set the entrypoint as `input_guardrail`
# This means that this node is the first one called
builder.add_edge(START, "input_guardrail")

# Add conditional edge based on guardrail validation
builder.add_conditional_edges(
    "input_guardrail",
    route_after_guardrail,
    ["classify_query", "guardrail_block"],
)

# Guardrail block goes straight to END
builder.add_edge("guardrail_block", END)

# Add conditional edge based on query classification
builder.add_conditional_edges(
    "classify_query",
    route_after_classification,
    ["generate_query", "direct_answer", "generate_knowledge_query"],
)

# Direct answer goes straight to END
builder.add_edge("direct_answer", END)

# Add conditional edge to continue with search queries in a parallel branch
builder.add_conditional_edges(
    "generate_query", continue_to_web_research, ["web_research"]
)
# Reflect on the web research
builder.add_edge("web_research", "reflection")
# Evaluate the research
builder.add_conditional_edges(
    "reflection", evaluate_research, ["web_research", "finalize_answer"]
)
# Finalize the answer
builder.add_edge("finalize_answer", END)

# Add conditional edge to continue with knowledge search in a parallel branch
builder.add_conditional_edges(
    "generate_knowledge_query", continue_to_knowledge_search, ["knowledge_search"]
)
# Reflect on the knowledge search
builder.add_edge("knowledge_search", "knowledge_reflection")
# Evaluate the knowledge search
builder.add_conditional_edges(
    "knowledge_reflection",
    evaluate_knowledge_search,
    ["knowledge_search", "finalize_answer"],
)

graph = builder.compile(name="pro-search-agent")
