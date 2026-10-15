"""LLM provider protocol for CRTW.

By default we use the ``NullProvider`` which is fully deterministic and offline.
You can subclass ``LLMProvider`` to plug in a real provider (Anthropic, OpenAI,
local model) without changing any agent code.

Wire it in by setting the env var ``CRTW_LLM_PROVIDER`` to a fully-qualified
``module:class`` string, or pass ``llm_provider=...`` into the orchestrator.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class LLMRequest:
    system: str = ""
    user: str = ""
    max_tokens: int = 256
    temperature: float = 0.0


@dataclass
class LLMResponse:
    text: str
    provider: str
    raw: dict[str, Any] | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class NullProvider:
    """Deterministic, offline LLM.

    Returns an empty suggestion string. The pipeline still produces real
    findings from deterministic AST/regex/static-analysis checks; LLM
    suggestions are optional enrichments.
    """

    name = "null"

    def complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(text="", provider=self.name, raw={"offline": True})


_DEFAULT: LLMProvider = NullProvider()


def get_default_provider() -> LLMProvider:
    """Resolve the provider from CRTW_LLM_PROVIDER, falling back to NullProvider."""
    global _DEFAULT
    if not isinstance(_DEFAULT, NullProvider):
        return _DEFAULT
    spec = os.environ.get("CRTW_LLM_PROVIDER")
    if spec:
        try:
            module_name, class_name = spec.split(":", 1)
            import importlib
            mod = importlib.import_module(module_name)
            cls = getattr(mod, class_name)
            _DEFAULT = cls()
        except Exception:
            # Fall through to NullProvider — never crash the workflow because
            # of an optional LLM.
            _DEFAULT = NullProvider()
    return _DEFAULT


def set_default_provider(provider: LLMProvider) -> None:
    global _DEFAULT
    _DEFAULT = provider