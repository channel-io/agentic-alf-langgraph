import os
import traceback
import asyncio
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from google.genai import Client

from agent.schemas import (
    SearchQueryList,
    Reflection,
    QueryClassification,
    InputGuardrailResult,
    IntentClarityResult,
)
from agent.tools import retrieve_tool
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
    reflection_instructions,
    knowledge_reflection_instructions,
    answer_instructions,
    query_classification_instructions,
    direct_answer_instructions,
    input_guardrail_instructions,
    intent_clarify_instructions,
)
from agent.utils import (
    get_citations,
    get_research_topic,
    insert_citation_markers,
    resolve_urls,
    format_conversation_history,
    get_latest_user_message,
)

# Used for Google Search API
genai_client = Client(api_key=os.getenv("GEMINI_API_KEY"))


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

    # Format the prompt with user input and conversation history
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = input_guardrail_instructions.format(
        user_input=latest_user_input, conversation_history=conversation_history
    )

    # Validate the input
    try:
        result = structured_llm.invoke(formatted_prompt)

        return {
            "is_safe_input": result.is_safe,
            "guardrail_violations": result.violations,
            "original_input": latest_user_input,
            "messages": state["messages"],
        }
    except Exception as e:
        # In case of error, err on the side of safety
        print(f"InputGuardrail 오류 발생: {traceback.format_exc()}")
        return {
            "is_safe_input": False,
            "guardrail_violations": ["시스템 오류로 인한 안전성 확인 불가"],
            "original_input": latest_user_input,
            "messages": state["messages"],
        }


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


def intent_clarify(state: OverallState, config: RunnableConfig) -> OverallState:
    """LangGraph node that analyzes user input for clarity and generates clarification questions if needed.

    Determines if the user's query is clear enough to provide a meaningful answer or if it needs
    clarification questions to understand the specific intent. Limits clarification attempts to 3 times.

    Args:
        state: Current graph state containing the user's messages
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including is_clear_intent, needs_clarification, and clarification_questions
    """
    configurable = Configuration.from_runnable_config(config)

    # Increment intent clarify count
    current_count = state.get("intent_clarify_count", 0)

    # If we've already asked for clarification max times, force proceed
    if current_count >= configurable.max_intent_clarify_attempts + 1:
        print(f"Intent clarification 횟수 초과 ({current_count}번), 강제로 진행합니다.")
        return {
            "is_clear_intent": True,
            "needs_clarification": False,
            "clarification_questions": [],
            "intent_clarify_count": current_count,
            "messages": state["messages"],
        }

    # Extract the latest user message
    user_messages = [
        msg for msg in state["messages"] if hasattr(msg, "type") and msg.type == "human"
    ]
    if not user_messages:
        # No user messages found, treat as needing clarification
        return {
            "is_clear_intent": False,
            "needs_clarification": True,
            "clarification_questions": [
                "어떤 것을 도와드릴까요? 구체적으로 질문해주세요."
            ],
            "intent_clarify_count": current_count,
            "messages": state["messages"],
        }

    latest_user_input = user_messages[-1].content

    # Initialize Gemini 2.0 Flash for intent clarity analysis
    llm = ChatGoogleGenerativeAI(
        model=configurable.query_generator_model,
        temperature=0.1,  # Low temperature for consistent analysis
        max_retries=2,
        api_key=os.getenv("GEMINI_API_KEY"),
    )
    structured_llm = llm.with_structured_output(IntentClarityResult)

    # Format the prompt with user input and conversation history
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = intent_clarify_instructions.format(
        user_input=latest_user_input, conversation_history=conversation_history
    )

    # Analyze the intent clarity
    try:
        result = structured_llm.invoke(formatted_prompt)

        return {
            "is_clear_intent": result.is_clear,
            "needs_clarification": result.needs_clarification,
            "clarification_questions": result.clarification_questions,
            "intent_clarify_count": current_count,
            "messages": state["messages"],
        }
    except Exception as e:
        # In case of error, assume clarification is needed for safety
        print(f"Intent Clarification 오류 발생: {traceback.format_exc()}")
        return {
            "is_clear_intent": False,
            "needs_clarification": True,
            "clarification_questions": [
                "죄송합니다. 질문을 더 자세히 설명해 주실 수 있나요?"
            ],
            "intent_clarify_count": current_count,
            "messages": state["messages"],
        }


def provide_clarification(state: OverallState, config: RunnableConfig) -> OverallState:
    """LangGraph node that provides clarification questions to the user.

    Creates a user-friendly response with clarification questions to help the user
    provide more specific information for better assistance.

    Args:
        state: Current graph state containing the clarification questions
        config: Configuration for the runnable

    Returns:
        Dictionary with state update, including a clarification message
    """
    configurable = Configuration.from_runnable_config(config)

    clarification_questions = state.get("clarification_questions", [])
    current_count = state.get("intent_clarify_count", 0) + 1

    # Build the clarification message
    if current_count >= configurable.max_intent_clarify_attempts + 1:
        clarification_message = """질문해 주셔서 감사합니다! 더 정확한 답변을 위해 마지막으로 한 번 더 확인하고 싶습니다.

🤔 **꼭 확인하고 싶은 점:**

"""
    else:
        clarification_message = """질문해 주셔서 감사합니다! 더 정확하고 도움이 되는 답변을 드리기 위해 몇 가지 확인하고 싶은 점이 있습니다.

🤔 **명확히 하고 싶은 점:**

"""

    for i, question in enumerate(clarification_questions, 1):
        clarification_message += f"{i}. {question}\n"

    if current_count >= configurable.max_intent_clarify_attempts + 1:
        clarification_message += """
⚡ **간단하게라도 알려주세요:**
• 어떤 기능이나 상황에 대한 질문인지
• 무엇을 하려고 하시는지

답변이 어려우시면 다른 방식으로 질문해 주셔도 됩니다!"""
    else:
        clarification_message += """
💡 **더 구체적으로 알려주시면 도움이 됩니다:**
• 구체적인 상황이나 맥락
• 원하시는 결과나 목표
• 관련된 기능이나 서비스명

다시 한번 자세히 질문해 주시면 정확한 답변을 드리겠습니다!"""

    return {
        "messages": [AIMessage(content=clarification_message)],
        "intent_clarify_count": current_count,
    }


def classify_query(
    state: OverallState, config: RunnableConfig
) -> QueryClassificationState:
    """LangGraph node that classifies whether a query needs web search, knowledge search, or can be answered directly.

    Analyzes the user's question to determine if it requires current/real-time information
    that would need web search, Channel Talk internal knowledge search, or if it can be answered directly with general knowledge.
    Can be overridden by search_mode configuration.

    Args:
        state: Current graph state containing the user's question
        config: Configuration for the runnable, including LLM provider settings and search_mode

    Returns:
        Dictionary with state update, including needs_web_search, needs_knowledge_search and query classification info
    """
    configurable = Configuration.from_runnable_config(config)

    # Force specific search based on search_mode
    if configurable.force_search_mode == "web":
        print("Force search mode가 'web'으로 설정되어 웹 검색을 강제 실행합니다.")
        return {
            "needs_web_search": True,
            "needs_knowledge_search": False,
            "query_classification": "web_search_required",
            "messages": state["messages"],
        }
    elif configurable.force_search_mode == "knowledge":
        print("Force search mode가 'knowledge'로 설정되어 지식 검색을 강제 실행합니다.")
        return {
            "needs_web_search": False,
            "needs_knowledge_search": True,
            "query_classification": "knowledge_search_required",
            "messages": state["messages"],
        }

    # Default auto behavior - perform normal classification
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = query_classification_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        conversation_history=conversation_history,
    )

    # Classify the query
    result = structured_llm.invoke(formatted_prompt)

    return {
        "needs_web_search": result.needs_web_search,
        "needs_knowledge_search": result.needs_knowledge_search,
        "query_classification": result.query_type,
        "messages": state["messages"],
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = direct_answer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        conversation_history=conversation_history,
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = query_writer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        number_queries=state["initial_search_query_count"],
        conversation_history=conversation_history,
    )
    # Generate the search queries
    result = structured_llm.invoke(formatted_prompt)
    return {"search_query": result.query, "messages": state["messages"]}


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
    # Get conversation history from the state messages
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = web_searcher_instructions.format(
        current_date=get_current_date(),
        research_topic=state["search_query"],
        conversation_history=conversation_history,
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = reflection_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n\n---\n\n".join(state["web_research_result"]),
        conversation_history=conversation_history,
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
        "messages": state["messages"],
    }


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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = answer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n---\n\n".join(all_summaries),
        conversation_history=conversation_history,
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = knowledge_query_writer_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        number_queries=state["initial_search_query_count"],
        conversation_history=conversation_history,
    )
    # Generate the search queries
    result = structured_llm.invoke(formatted_prompt)
    return {"search_query": result.query, "messages": state["messages"]}


def knowledge_search(
    state: KnowledgeSearchState, config: RunnableConfig
) -> OverallState:
    """LangGraph node that performs knowledge search using the retrieve_tool.

    Executes a knowledge search using the retrieve_tool to search Channel Talk internal documentation.
    This implements the tool usage pattern in LangGraph where the node uses a tool to perform its function.

    Args:
        state: Current graph state containing the search query and id
        config: Configuration for the runnable, including LLM provider settings

    Returns:
        Dictionary with state update, including knowledge_search_result key containing the search results
    """

    async def _async_search():
        try:
            # Use the retrieve_tool to perform the search
            # Call the tool function directly (since it's already async)
            search_result = await retrieve_tool.ainvoke(
                {"query": state["search_query"], "top_k": 10}
            )

            return {
                "knowledge_search_result": [search_result],
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
    conversation_history = format_conversation_history(state["messages"])
    formatted_prompt = knowledge_reflection_instructions.format(
        current_date=current_date,
        research_topic=get_research_topic(state["messages"]),
        summaries="\n\n---\n\n".join(state["knowledge_search_result"]),
        conversation_history=conversation_history,
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
        "messages": state["messages"],
    }
