import os
from dotenv import load_dotenv
from langgraph.graph import StateGraph
from langgraph.graph import START, END

from agent.state import OverallState
from agent.configuration import Configuration
from agent.nodes import (
    input_guardrail,
    guardrail_block,
    intent_clarify,
    provide_clarification,
    classify_query,
    direct_answer,
    generate_query,
    web_research,
    reflection,
    finalize_answer,
    generate_knowledge_query,
    knowledge_search,
    knowledge_reflection,
)
from agent.edges import (
    route_after_guardrail,
    route_after_classification,
    route_after_intent_clarify_search,
    continue_to_web_research,
    continue_to_knowledge_search,
    evaluate_research,
    evaluate_knowledge_search,
)

load_dotenv()

if os.getenv("GEMINI_API_KEY") is None:
    raise ValueError("GEMINI_API_KEY is not set")


# Graph Definition


# Create our Agent Graph
builder = StateGraph(OverallState, config_schema=Configuration)

# Define the nodes we will cycle between
builder.add_node("input_guardrail", input_guardrail)
builder.add_node("guardrail_block", guardrail_block)
builder.add_node("intent_clarify", intent_clarify)
builder.add_node("provide_clarification", provide_clarification)
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

# Add conditional edge based on query classification (moved up)
builder.add_conditional_edges(
    "classify_query",
    route_after_classification,
    ["intent_clarify", "direct_answer"],
)

# Add conditional edge based on intent clarity analysis for search queries
builder.add_conditional_edges(
    "intent_clarify",
    route_after_intent_clarify_search,
    [
        "generate_query",
        "generate_knowledge_query",
        "provide_clarification",
    ],
)

# Clarification response goes straight to END
builder.add_edge("provide_clarification", END)

# Guardrail block goes straight to END
builder.add_edge("guardrail_block", END)

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
