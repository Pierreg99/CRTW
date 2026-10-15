"""LLM provider module for CRTW.

This module defines the LLM provider contract used by every agent in the
code-review + testing workflow, plus three concrete providers:

* ``NullProvider``  — backward-compatible default. Returns an empty suggestion
  string. Fully deterministic, fully offline, no dependencies. The pipeline
  still produces real findings from deterministic AST / regex / static-analysis
  checks; LLM suggestions are optional enrichments.

* ``OfflineMockProvider``  — fully offline heuristic suggester. Inspects the
  request to return a *useful* suggestion (e.g. remediation hint seeded from
  the finding title and the system prompt). No external network call, no API
  key. Useful for CI smoke runs that want a non-empty suggestion field.

* ``ScriptedProvider``  — deterministic test double. The caller pre-loads a
  list of canned responses; each ``complete()`` call returns the next one.
  Raises ``LLMStopped`` when the script is exhausted. Used by the unit-test
  suite.

* ``AnthropicProvider``  — real Claude API client. Wraps the official
  ``anthropic`` SDK and tracks token usage + approximate USD cost. The
  ``model`` argument is validated against a prefix allowlist *before* any
  network call goes out, so an unrecognised model ID can never reach the API.
  If the SDK is not installed or the call fails, the provider raises
  ``LLMStopped`` and the workflow can fall back to ``NullProvider``.

Plugging in a custom provider
=============================

1. Subclass ``LLMProvider`` and implement ``complete(request)`` (and
   optionally ``usage()``).
2. Either set the env var ``CRTW_LLM_PROVIDER=module:Class`` before running
   the workflow, or call ``set_default_provider(YourProvider())`` from your
   own code.

Backwards compatibility
=======================

The public names ``LLMRequest``, ``LLMResponse``, ``LLMProvider`` (Protocol),
``NullProvider``, ``get_default_provider``, ``set_default_provider`` all
preserve the signatures and behaviour of the original module so existing
importers keep working.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


# =============================================================================
# Wire types
# =============================================================================


@dataclass
class LLMRequest:
    """A request handed to a provider's ``complete()``.

    The orchestrator and agents only ever need four fields: a system
    instruction, a user instruction, an output budget, and a sampling
    temperature. Provider-specific extras (model name, tools, etc.) are
    configured on the provider itself, not per-request, to keep the contract
    narrow.
    """

    system: str = ""
    user: str = ""
    max_tokens: int = 256
    temperature: float = 0.0
    # Optional metadata. Providers may inspect ``meta`` but must never depend
    # on any specific key being present.
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """The provider's answer.

    ``text`` is the suggestion body, ``provider`` is the provider's
    self-reported name, and ``raw`` is an optional dict for any provider-
    specific debug data (e.g. token counts, finish reason).
    """

    text: str
    provider: str
    raw: dict[str, Any] | None = None


# =============================================================================
# Exceptions
# =============================================================================


class LLMStopped(RuntimeError):
    """Raised by a provider when it cannot produce a usable response.

    Examples: the safety filter rejected the request, the response was
    truncated at ``max_tokens``, the Anthropic API returned an auth error,
    or a ``ScriptedProvider`` ran out of canned responses.
    """


# =============================================================================
# Protocol + abstract base
# =============================================================================


@runtime_checkable
class LLMProvider(Protocol):
    """The minimum contract every provider must satisfy.

    ``name`` is a short identifier (e.g. ``"null"``, ``"offline-mock"``,
    ``"anthropic"``) used in reports and logs. ``complete()`` takes an
    ``LLMRequest`` and returns an ``LLMResponse``. ``usage()`` is optional
    and returns a dict describing cumulative token / cost stats, or ``None``
    if the provider does not track usage.
    """

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...

    def usage(self) -> dict[str, Any] | None: ...


class BaseProvider(ABC):
    """Convenience base class for concrete providers.

    Subclasses get a default ``name`` setter, thread-safe usage tracking,
    and a uniform error-translation layer (``complete_or_raise`` wraps the
    subclass's ``_complete`` and turns any unexpected exception into an
    ``LLMStopped``).
    """

    name: str = "base"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._usage: dict[str, Any] = {
            "requests": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cost_usd": 0.0,
            "models": {},
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Dispatch to ``_complete`` and update usage.

        Provider-specific exceptions (``LLMStopped``) are re-raised verbatim.
        Anything else is wrapped in ``LLMStopped`` so a buggy provider never
        aborts the workflow — the orchestrator catches this and falls back to
        the deterministic pipeline.
        """
        with self._lock:
            self._usage["requests"] += 1
        try:
            response = self._complete(request)
        except LLMStopped:
            raise
        except Exception as exc:  # noqa: BLE001 — provider isolation
            raise LLMStopped(
                f"{self.name}.complete() failed: {type(exc).__name__}: {exc}"
            ) from exc
        self._record_response(response)
        return response

    def usage(self) -> dict[str, Any] | None:
        with self._lock:
            # Return a copy so callers cannot mutate our internal counters.
            return dict(self._usage) if self._usage["requests"] else None

    # ------------------------------------------------------------------
    # Subclass hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def _complete(self, request: LLMRequest) -> LLMResponse:
        """Produce a response. Subclasses implement this."""

    def _record_response(self, response: LLMResponse) -> None:
        """Hook for subclasses to fold token / cost data into ``self._usage``.

        The base implementation does nothing; the Anthropic provider
        overrides it.
        """


# =============================================================================
# Built-in providers
# =============================================================================


class NullProvider(BaseProvider):
    """Backwards-compatible default. Returns an empty suggestion string.

    The deterministic AST / regex / static-analysis checks produce real
    findings without any LLM at all; this provider exists so the rest of
    the code path is exercised (request / response types, usage counters)
    even when no LLM is wired in.
    """

    name = "null"

    def _complete(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse(
            text="",
            provider=self.name,
            raw={"offline": True, "reason": "NullProvider always returns empty"},
        )


class OfflineMockProvider(BaseProvider):
    """Fully offline heuristic suggester.

    Inspects the request to return a *useful* suggestion seeded from the
    system / user text. No network call, no API key, no SDK dependency. Use
    this when you want non-empty suggestion text in CI without paying for a
    real LLM.

    The provider is intentionally simple: it never fabricates file paths
    or specific code lines — it only reformulates the title and the
    remediation cue the agent already provided. That keeps suggestions
    auditable: they are *always* a paraphrase of the deterministic finding.
    """

    name = "offline-mock"

    # Generic credential keywords. Checked *after* the specific technical
    # detectors (md5 / sha1 / sql / etc.) so that e.g. "MD5 password hashing"
    # lands on the hash template and not the generic "hardcoded credential"
    # template.
    _TRIGGER_KEYWORDS = {
        "hardcoded", "secret", "password", "token", "api_key", "aws",
        "private key", "connection string",
    }

    def _complete(self, request: LLMRequest) -> LLMResponse:
        user_lower = (request.user or "").lower()
        sys_lower = (request.system or "").lower()
        combined = user_lower + " " + sys_lower

        # Specific technical indicators take priority over generic keywords.
        if "md5" in combined or "sha1" in combined or "weak hash" in combined:
            suggestion = self._hash_template(request)
        elif "sql" in combined and "injection" in combined:
            suggestion = self._sql_template(request)
        elif "eval" in combined or "exec" in combined or "pickle" in combined:
            suggestion = self._rce_template(request)
        elif "shell" in combined and "true" in combined:
            suggestion = self._shell_template(request)
        elif "verify=false" in combined or "tls" in combined or "ssl" in combined:
            suggestion = self._tls_template(request)
        elif any(k in combined for k in self._TRIGGER_KEYWORDS):
            suggestion = self._secret_template(request)
        else:
            suggestion = self._generic_template(request)

        # Respect the caller's max_tokens. Approximate: ~4 chars per token.
        # No artificial floor — the caller asked for a budget and we honour it.
        max_tokens = int(request.max_tokens) if request.max_tokens else 256
        max_chars = max_tokens * 4
        if max_chars > 0 and len(suggestion) > max_chars:
            suggestion = suggestion[: max(0, max_chars - 3)].rstrip() + "..."

        return LLMResponse(
            text=suggestion,
            provider=self.name,
            raw={"offline": True, "template": suggestion.split(" ", 1)[0]},
        )

    # ------------------------- templates -------------------------

    def _secret_template(self, request: LLMRequest) -> str:
        title = self._extract_title(request)
        return (
            f"Detected a hardcoded credential: {title}. "
            "Move the value to an environment variable or a secret manager "
            "(AWS Secrets Manager, HashiCorp Vault, etc.), read it at runtime, "
            "and rotate the leaked value immediately. Add a pre-commit hook "
            "(e.g. gitleaks, trufflehog) to prevent regressions."
        )

    def _sql_template(self, request: LLMRequest) -> str:
        return (
            "Replace the f-string with a parameterised query. "
            "cursor.execute(\"SELECT ... WHERE id = %s\", (user_id,)) "
            "is safe; string interpolation in the SQL body is not."
        )

    def _hash_template(self, request: LLMRequest) -> str:
        return (
            "Use a memory-hard, salted KDF such as Argon2id or scrypt. "
            "If you must stay in the stdlib, hashlib.pbkdf2_hmac with a "
            "high iteration count is acceptable. Never use MD5 or SHA1 for "
            "password storage."
        )

    def _rce_template(self, request: LLMRequest) -> str:
        return (
            "eval(), exec(), and pickle.loads on untrusted input enable "
            "remote code execution. Replace with ast.literal_eval for "
            "data, json.loads for JSON, and a typed schema validator for "
            "structured input."
        )

    def _shell_template(self, request: LLMRequest) -> str:
        return (
            "subprocess.run(..., shell=True) with an f-string command is a "
            "command-injection vector. Pass argv as a list (no shell) and "
            "validate every interpolated value against a strict allowlist."
        )

    def _tls_template(self, request: LLMRequest) -> str:
        return (
            "verify=False disables certificate validation and exposes the "
            "client to man-in-the-middle attacks. Remove the flag and pin "
            "the CA bundle if the corporate proxy requires it."
        )

    def _generic_template(self, request: LLMRequest) -> str:
        title = self._extract_title(request)
        return (
            f"Review: {title}. The deterministic check has already produced "
            "the evidence; this suggestion is a paraphrase only. Apply the "
            "remediation step, re-run the test suite, and add a regression "
            "test that would have failed before the fix."
        )

    @staticmethod
    def _extract_title(request: LLMRequest) -> str:
        # The user message often starts with a one-line title. If absent, fall
        # back to a short prefix of the system prompt.
        first = (request.user or "").strip().splitlines()[0] if request.user else ""
        if first:
            return first[:120]
        return (request.system or "issue").strip().splitlines()[0][:120] or "issue"


class ScriptedProvider(BaseProvider):
    """Deterministic test double.

    Pass a list of canned responses; each ``complete()`` call returns the
    next one. When the list is exhausted, the provider raises ``LLMStopped``
    so the calling test can assert on the exhaustion behaviour.
    """

    name = "scripted"

    def __init__(self, responses: Optional[list[LLMResponse]] = None) -> None:
        super().__init__()
        self._responses: list[LLMResponse] = list(responses or [])
        self._index: int = 0
        self._call_log: list[LLMRequest] = []

    def push(self, response: LLMResponse) -> None:
        """Append a canned response. Useful in test setUp()."""
        self._responses.append(response)

    def call_log(self) -> list[LLMRequest]:
        """All requests observed so far. Useful for assertions."""
        return list(self._call_log)

    def _complete(self, request: LLMRequest) -> LLMResponse:
        if self._index >= len(self._responses):
            raise LLMStopped(
                f"ScriptedProvider exhausted after {self._index} response(s); "
                "push more responses or stop calling complete()."
            )
        response = self._responses[self._index]
        self._index += 1
        # Only record successful requests in the call log; calls that fail
        # with LLMStopped never reach this line.
        self._call_log.append(request)
        return response


class AnthropicProvider(BaseProvider):
    """Real Claude API client.

    Wraps the official ``anthropic`` SDK. The model ID is validated against
    a prefix allowlist (``CLAUDE_MODEL_PREFIXES``) *before* any network call,
    so a misconfigured model name can never reach the API. Token usage and
    approximate cost are tracked per response.

    The provider is optional: if the ``anthropic`` package is missing or the
    API call fails, ``LLMStopped`` is raised and the orchestrator can fall
    back to ``NullProvider``. The CRTW pipeline never depends on this
    provider for correctness.
    """

    name = "anthropic"

    # Default prefix allowlist. Override the tuple on the class (or pass a
    # custom ``model_prefixes=``) to lock down which models are reachable.
    CLAUDE_MODEL_PREFIXES: tuple[str, ...] = ("claude-",)

    # List-price estimates in USD per million tokens. These are deliberately
    # conservative upper bounds used only for the post-run usage report; the
    # real bill is whatever Anthropic charges.
    PRICE_TABLE: dict[str, dict[str, float]] = {
        "claude-opus-4-7": {
            "input_tokens": 15.0,
            "output_tokens": 75.0,
            "cache_creation_input_tokens": 18.75,
            "cache_read_input_tokens": 1.50,
        },
        "claude-sonnet-4-5": {
            "input_tokens": 3.0,
            "output_tokens": 15.0,
            "cache_creation_input_tokens": 3.75,
            "cache_read_input_tokens": 0.30,
        },
        "claude-haiku-4-5": {
            "input_tokens": 0.80,
            "output_tokens": 4.0,
            "cache_creation_input_tokens": 1.0,
            "cache_read_input_tokens": 0.08,
        },
    }
    _DEFAULT_PRICE = {"input_tokens": 3.0, "output_tokens": 15.0}

    def __init__(
        self,
        model: str = "claude-haiku-4-5",
        *,
        max_tokens: int = 1024,
        model_prefixes: Optional[tuple[str, ...]] = None,
        client: Any = None,
    ) -> None:
        super().__init__()
        self.model = self._validate_model(
            model, model_prefixes or self.CLAUDE_MODEL_PREFIXES
        )
        self.max_tokens = int(max_tokens)
        self._client = client  # injected for tests
        self._anthropic_module = None
        if self._client is None:
            try:
                import anthropic as _anthropic  # type: ignore
            except Exception as exc:  # noqa: BLE001
                raise LLMStopped(
                    "anthropic SDK is not installed. Run `pip install anthropic` "
                    "or set CRTW_LLM_PROVIDER to an offline provider."
                ) from exc
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise LLMStopped(
                    "ANTHROPIC_API_KEY is not set. Export it or use an offline "
                    "provider (NullProvider / OfflineMockProvider)."
                )
            self._anthropic_module = _anthropic
            try:
                self._client = _anthropic.Anthropic()
            except Exception as exc:  # noqa: BLE001
                raise LLMStopped(
                    f"Failed to construct Anthropic client: {exc}"
                ) from exc

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @classmethod
    def _validate_model(cls, model: str, prefixes: tuple[str, ...]) -> str:
        name = (model or "").strip()
        if not name:
            raise LLMStopped("AnthropicProvider: model name is empty.")
        if any(c.isspace() for c in name):
            raise LLMStopped(
                f"AnthropicProvider: model name {name!r} contains whitespace."
            )
        if not name.startswith(prefixes):
            raise LLMStopped(
                f"AnthropicProvider: model {name!r} is not in the allowlist "
                f"(must start with one of {prefixes})."
            )
        return name

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def _complete(self, request: LLMRequest) -> LLMResponse:
        messages = []
        if request.user:
            messages.append({"role": "user", "content": request.user})
        if not messages:
            raise LLMStopped("AnthropicProvider: empty user message.")

        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": min(self.max_tokens, int(request.max_tokens) or self.max_tokens),
            "temperature": float(request.temperature),
            "messages": messages,
        }
        if request.system:
            kwargs["system"] = request.system

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001
            # Catch *any* SDK or transport failure and re-raise as LLMStopped
            # so the orchestrator can degrade gracefully.
            raise LLMStopped(
                f"Anthropic API call failed: {type(exc).__name__}: {exc}"
            ) from exc

        text = self._extract_text(response)
        return LLMResponse(
            text=text,
            provider=self.name,
            raw={
                "model": getattr(response, "model", self.model),
                "stop_reason": getattr(response, "stop_reason", None),
                "usage": self._usage_dict(response),
            },
        )

    @staticmethod
    def _extract_text(response: Any) -> str:
        content = getattr(response, "content", None) or []
        chunks: list[str] = []
        for block in content:
            # Block may be a pydantic model or a dict depending on SDK version.
            text = getattr(block, "text", None)
            if text is None and isinstance(block, dict):
                text = block.get("text")
            if isinstance(text, str):
                chunks.append(text)
        return "".join(chunks)

    @staticmethod
    def _usage_dict(response: Any) -> dict[str, int]:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return {}
        out: dict[str, int] = {}
        for key in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        ):
            value = getattr(usage, key, None)
            if value is None and isinstance(usage, dict):
                value = usage.get(key)
            if isinstance(value, int):
                out[key] = value
        return out

    # ------------------------------------------------------------------
    # Usage rollup
    # ------------------------------------------------------------------

    def _record_response(self, response: LLMResponse) -> None:
        raw = response.raw or {}
        usage = raw.get("usage") or {}
        model = raw.get("model") or self.model
        with self._lock:
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            ):
                if isinstance(usage.get(key), int):
                    self._usage[key] = self._usage.get(key, 0) + int(usage[key])
            models = self._usage.setdefault("models", {})
            if isinstance(models, dict):
                models[model] = int(models.get(model, 0)) + 1
            self._usage["cost_usd"] = round(
                self._estimate_cost(model, self._usage), 6
            )

    @classmethod
    def _estimate_cost(cls, model: str, usage: dict[str, Any]) -> float:
        prices = cls.PRICE_TABLE.get(model) or cls._DEFAULT_PRICE
        cost = 0.0
        for key, price in prices.items():
            count = int(usage.get(key, 0) or 0)
            cost += count * price / 1_000_000.0
        return cost


# =============================================================================
# Resolution + registry
# =============================================================================


# Built-in registry. Custom providers can be registered at runtime via
# ``register_provider("name", cls)`` and then activated by setting
# ``CRTW_LLM_PROVIDER=crtw.agents.llm:name``.
_PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "null": NullProvider,
    "offline-mock": OfflineMockProvider,
    "scripted": ScriptedProvider,
    "anthropic": AnthropicProvider,
}


def register_provider(name: str, cls: type[BaseProvider]) -> None:
    """Register a custom provider under a short name.

    ``name`` must be unique; re-registering an existing name overwrites the
    previous entry. The class must inherit from ``BaseProvider`` (or
    implement the ``LLMProvider`` protocol).
    """
    if not name or not isinstance(name, str):
        raise ValueError("provider name must be a non-empty string")
    _PROVIDER_REGISTRY[name] = cls


def list_providers() -> list[str]:
    """Return the names of all registered providers, in registration order."""
    return list(_PROVIDER_REGISTRY.keys())


_DEFAULT: LLMProvider = NullProvider()
_DEFAULT_LOCK = threading.Lock()


def get_default_provider() -> LLMProvider:
    """Resolve the default provider from the environment.

    Resolution order:

    1. If ``_DEFAULT`` has been overridden via ``set_default_provider``,
       return that.
    2. Otherwise, if ``CRTW_LLM_PROVIDER`` is set, parse it as
       ``module:Class`` *or* as a short registry name and try to load the
       provider. Any failure falls back to ``NullProvider`` (the pipeline
       must never crash because of an optional LLM).
    3. Otherwise, return ``NullProvider``.

    This function is thread-safe and idempotent: the lookup runs at most
    once and the result is cached.
    """
    global _DEFAULT
    if not isinstance(_DEFAULT, NullProvider):
        return _DEFAULT
    with _DEFAULT_LOCK:
        if not isinstance(_DEFAULT, NullProvider):
            return _DEFAULT
        spec = os.environ.get("CRTW_LLM_PROVIDER", "").strip()
        if spec:
            try:
                _DEFAULT = _load_provider(spec)
            except LLMStopped:
                _DEFAULT = NullProvider()
            except Exception:  # noqa: BLE001
                _DEFAULT = NullProvider()
    return _DEFAULT


def _load_provider(spec: str) -> LLMProvider:
    """Resolve a ``CRTW_LLM_PROVIDER`` spec to an instantiated provider.

    Two spec formats are supported:

    * ``name`` — looked up in the built-in registry.
    * ``module:Class`` — dynamically imported. Must be a class implementing
      the ``LLMProvider`` protocol (or inheriting from ``BaseProvider``).
    """
    if ":" in spec:
        module_name, class_name = spec.split(":", 1)
        import importlib
        mod = importlib.import_module(module_name)
        cls = getattr(mod, class_name)
        return cls()  # type: ignore[abstract]
    if spec in _PROVIDER_REGISTRY:
        return _PROVIDER_REGISTRY[spec]()  # type: ignore[abstract]
    raise LLMStopped(
        f"Unknown CRTW_LLM_PROVIDER={spec!r}. Known names: "
        f"{', '.join(list_providers())} or use module:Class form."
    )


def set_default_provider(provider: LLMProvider) -> None:
    """Override the default provider for the rest of the process."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = provider


def reset_default_provider() -> None:
    """Reset back to ``NullProvider`` (useful in tests)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = NullProvider()


__all__ = [
    "LLMRequest",
    "LLMResponse",
    "LLMProvider",
    "LLMStopped",
    "BaseProvider",
    "NullProvider",
    "OfflineMockProvider",
    "ScriptedProvider",
    "AnthropicProvider",
    "register_provider",
    "list_providers",
    "get_default_provider",
    "set_default_provider",
    "reset_default_provider",
]
