import os
from pydantic import BaseModel, Field
from typing import Any, Optional, Literal

from langchain_core.runnables import RunnableConfig


class Configuration(BaseModel):
    """The configuration for the agent."""

    query_generator_model: str = Field(
        default="gemini-2.0-flash",
        metadata={
            "description": "The name of the language model to use for the agent's query generation."
        },
    )

    reflection_model: str = Field(
        default="gemini-2.5-flash",
        metadata={
            "description": "The name of the language model to use for the agent's reflection."
        },
    )

    answer_model: str = Field(
        default="gemini-2.5-pro",
        metadata={
            "description": "The name of the language model to use for the agent's answer."
        },
    )

    number_of_initial_queries: int = Field(
        default=3,
        metadata={"description": "The number of initial search queries to generate."},
    )

    max_research_loops: int = Field(
        default=2,
        metadata={"description": "The maximum number of research loops to perform."},
    )

    max_intent_clarify_attempts: int = Field(
        default=2,
        metadata={
            "description": "The maximum number of intent clarification attempts before forcing to proceed."
        },
    )

    force_search_mode: Literal["auto", "web", "knowledge"] = Field(
        default="knowledge",
        metadata={
            "description": "Force search mode configuration. 'auto' follows normal classification logic, 'web' forces web search, 'knowledge' forces knowledge search."
        },
    )

    enable_intent_clarify: bool = Field(
        default=False,
        metadata={
            "description": "Whether to enable intent clarification functionality. If True, unclear queries will be clarified. If False, will proceed directly to the next step."
        },
    )

    @classmethod
    def from_runnable_config(
        cls, config: Optional[RunnableConfig] = None
    ) -> "Configuration":
        """Create a Configuration instance from a RunnableConfig."""
        configurable = (
            config["configurable"] if config and "configurable" in config else {}
        )

        # Get raw values from environment or config
        raw_values: dict[str, Any] = {
            name: os.environ.get(name.upper(), configurable.get(name))
            for name in cls.model_fields.keys()
        }

        # Filter out None values
        values = {k: v for k, v in raw_values.items() if v is not None}

        return cls(**values)
