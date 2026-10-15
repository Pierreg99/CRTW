"""CRTW agent package.

Re-exports the LLM provider surface so that ``from crtw.agents import ...``
works in user code and in the rest of the workflow.
"""
from __future__ import annotations

from crtw.agents.llm import (
    AnthropicProvider,
    BaseProvider,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStopped,
    NullProvider,
    OfflineMockProvider,
    ScriptedProvider,
    get_default_provider,
    list_providers,
    register_provider,
    reset_default_provider,
    set_default_provider,
)

__all__ = [
    "AnthropicProvider",
    "BaseProvider",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMStopped",
    "NullProvider",
    "OfflineMockProvider",
    "ScriptedProvider",
    "get_default_provider",
    "list_providers",
    "register_provider",
    "reset_default_provider",
    "set_default_provider",
]
