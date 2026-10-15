"""Unit tests for the LLM provider module.

These tests use only the stdlib and the providers in this package. No network
calls; no external API keys. The AnthropicProvider is exercised with an
injected fake client so the SDK does not need to be installed.
"""
from __future__ import annotations

import os
import unittest
import unittest.mock as mock
from typing import Any

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


# =============================================================================
# NullProvider
# =============================================================================


class NullProviderTests(unittest.TestCase):
    def test_returns_empty_text(self) -> None:
        provider = NullProvider()
        response = provider.complete(LLMRequest(user="hello"))
        self.assertEqual(response.text, "")
        self.assertEqual(response.provider, "null")
        self.assertEqual(response.raw, {"offline": True, "reason": "NullProvider always returns empty"})

    def test_usage_is_none_until_a_call_is_made(self) -> None:
        provider = NullProvider()
        self.assertIsNone(provider.usage())
        provider.complete(LLMRequest(user="x"))
        usage = provider.usage()
        self.assertIsNotNone(usage)
        self.assertEqual(usage["requests"], 1)


# =============================================================================
# OfflineMockProvider
# =============================================================================


class OfflineMockProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = OfflineMockProvider()

    def test_secret_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="hardcoded AWS access key detected"))
        self.assertIn("hardcoded credential", resp.text.lower())
        self.assertIn("environment variable", resp.text.lower())

    def test_sql_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="SQL injection via f-string"))
        self.assertIn("parameterised", resp.text.lower())

    def test_hash_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="md5 password hashing detected"))
        self.assertIn("argon2", resp.text.lower())

    def test_rce_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="eval() usage on untrusted input"))
        self.assertIn("remote code execution", resp.text.lower())

    def test_shell_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="subprocess shell=True with f-string"))
        self.assertIn("command-injection", resp.text.lower())

    def test_tls_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="verify=False disables TLS validation"))
        self.assertIn("man-in-the-middle", resp.text.lower())

    def test_generic_template(self) -> None:
        resp = self.provider.complete(LLMRequest(user="some other issue"))
        self.assertIn("Review:", resp.text)
        self.assertEqual(resp.provider, "offline-mock")

    def test_max_tokens_truncates(self) -> None:
        resp = self.provider.complete(
            LLMRequest(user="hardcoded password", max_tokens=10)
        )
        # 10 tokens * 4 chars = 40 chars + ellipsis
        self.assertLessEqual(len(resp.text), 50)


# =============================================================================
# ScriptedProvider
# =============================================================================


class ScriptedProviderTests(unittest.TestCase):
    def test_returns_canned_responses_in_order(self) -> None:
        provider = ScriptedProvider(
            responses=[
                LLMResponse(text="first", provider="scripted"),
                LLMResponse(text="second", provider="scripted"),
            ]
        )
        self.assertEqual(provider.complete(LLMRequest(user="a")).text, "first")
        self.assertEqual(provider.complete(LLMRequest(user="b")).text, "second")

    def test_exhaustion_raises_llmstopped(self) -> None:
        provider = ScriptedProvider(responses=[LLMResponse(text="only", provider="scripted")])
        provider.complete(LLMRequest(user="once"))
        with self.assertRaises(LLMStopped):
            provider.complete(LLMRequest(user="again"))

    def test_call_log_records_requests(self) -> None:
        provider = ScriptedProvider(responses=[LLMResponse(text="x", provider="scripted")])
        provider.complete(LLMRequest(user="hello"))
        # The second call exhausts the script; LLMStopped escapes so the
        # call log keeps only the successful request.
        with self.assertRaises(LLMStopped):
            provider.complete(LLMRequest(user="world"))
        log = provider.call_log()
        self.assertEqual(len(log), 1)  # only the successful call lands
        self.assertEqual(log[0].user, "hello")

    def test_push_appends(self) -> None:
        provider = ScriptedProvider()
        provider.push(LLMResponse(text="late", provider="scripted"))
        self.assertEqual(provider.complete(LLMRequest(user="x")).text, "late")


# =============================================================================
# BaseProvider error isolation
# =============================================================================


class _ExplodingProvider(BaseProvider):
    name = "explode"

    def _complete(self, request: LLMRequest) -> LLMResponse:
        raise ValueError("boom")


class BaseProviderErrorIsolationTests(unittest.TestCase):
    def test_unexpected_exception_wrapped_as_llmstopped(self) -> None:
        provider = _ExplodingProvider()
        with self.assertRaises(LLMStopped) as cm:
            provider.complete(LLMRequest(user="x"))
        self.assertIn("ValueError", str(cm.exception))
        self.assertIn("boom", str(cm.exception))

    def test_llmstopped_re_raised_verbatim(self) -> None:
        class _Stop(BaseProvider):
            name = "stop"

            def _complete(self, request: LLMRequest) -> LLMResponse:
                raise LLMStopped("stopped!")

        provider = _Stop()
        with self.assertRaises(LLMStopped) as cm:
            provider.complete(LLMRequest(user="x"))
        self.assertEqual(str(cm.exception), "stopped!")


# =============================================================================
# AnthropicProvider (with injected client)
# =============================================================================


class _FakeAnthropicBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeAnthropicUsage:
    def __init__(self, **kw: int) -> None:
        self.input_tokens = kw.get("input_tokens", 0)
        self.output_tokens = kw.get("output_tokens", 0)
        self.cache_creation_input_tokens = kw.get("cache_creation_input_tokens", 0)
        self.cache_read_input_tokens = kw.get("cache_read_input_tokens", 0)


class _FakeAnthropicResponse:
    def __init__(self, text: str = "ok", model: str = "claude-haiku-4-5",
                 stop_reason: str = "end_turn", **usage: int) -> None:
        self.content = [_FakeAnthropicBlock(text)]
        self.model = model
        self.stop_reason = stop_reason
        self.usage = _FakeAnthropicUsage(**usage)


class AnthropicProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        # Make sure no ANTHROPIC_API_KEY leaks from the env into these tests.
        self._saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self) -> None:
        if self._saved_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self._saved_key

    def _client(self, *responses: _FakeAnthropicResponse) -> Any:
        client = mock.MagicMock()
        client.messages.create.side_effect = list(responses)
        return client

    def test_model_prefix_allowlist_rejects_unknown_prefix(self) -> None:
        with self.assertRaises(LLMStopped):
            AnthropicProvider(model="gpt-4o", client=self._client())

    def test_empty_model_rejected(self) -> None:
        with self.assertRaises(LLMStopped):
            AnthropicProvider(model="", client=self._client())

    def test_whitespace_in_model_rejected(self) -> None:
        with self.assertRaises(LLMStopped):
            AnthropicProvider(model="claude- opus", client=self._client())

    def test_missing_sdk_raises_llmstopped(self) -> None:
        # No client and SDK not installed -> LLMStopped.
        with mock.patch.dict("sys.modules", {"anthropic": None}):
            with self.assertRaises(LLMStopped):
                AnthropicProvider()

    def test_missing_api_key_raises_llmstopped(self) -> None:
        # Simulate SDK present but no key.
        with mock.patch.dict(
            "sys.modules",
            {"anthropic": mock.MagicMock(Anthropic=mock.MagicMock())},
        ):
            with self.assertRaises(LLMStopped):
                AnthropicProvider()

    def test_successful_call_records_usage(self) -> None:
        provider = AnthropicProvider(
            model="claude-haiku-4-5",
            client=self._client(
                _FakeAnthropicResponse(
                    text="hi",
                    input_tokens=12,
                    output_tokens=7,
                )
            ),
        )
        resp = provider.complete(LLMRequest(user="hello", system="sys"))
        self.assertEqual(resp.text, "hi")
        self.assertEqual(resp.provider, "anthropic")
        usage = provider.usage()
        self.assertIsNotNone(usage)
        self.assertEqual(usage["input_tokens"], 12)
        self.assertEqual(usage["output_tokens"], 7)
        self.assertEqual(usage["requests"], 1)
        # Cost is non-zero because we counted tokens.
        self.assertGreater(usage["cost_usd"], 0.0)

    def test_api_error_wrapped_as_llmstopped(self) -> None:
        client = mock.MagicMock()
        client.messages.create.side_effect = RuntimeError("network down")
        provider = AnthropicProvider(model="claude-haiku-4-5", client=client)
        with self.assertRaises(LLMStopped) as cm:
            provider.complete(LLMRequest(user="x"))
        self.assertIn("network down", str(cm.exception))

    def test_cost_estimation_uses_table(self) -> None:
        # The cost is computed from the *response* model (what the API actually
        # reported), so the fake response must declare the same model we
        # configured.
        provider = AnthropicProvider(
            model="claude-opus-4-7",
            client=self._client(
                _FakeAnthropicResponse(
                    model="claude-opus-4-7",
                    input_tokens=1_000_000,
                    output_tokens=0,
                )
            ),
        )
        provider.complete(LLMRequest(user="x"))
        usage = provider.usage()
        # opus input is $15/M tokens -> 1M tokens = $15.
        self.assertAlmostEqual(usage["cost_usd"], 15.0, places=3)

    def test_cost_estimation_falls_back_to_default_for_unknown_model(self) -> None:
        # Unknown models fall back to the default price list ($3 input / $15
        # output per million tokens).
        provider = AnthropicProvider(
            model="claude-haiku-4-5",
            client=self._client(
                _FakeAnthropicResponse(
                    model="claude-future-99",
                    input_tokens=1_000_000,
                    output_tokens=0,
                )
            ),
        )
        provider.complete(LLMRequest(user="x"))
        usage = provider.usage()
        self.assertAlmostEqual(usage["cost_usd"], 3.0, places=3)


# =============================================================================
# Resolution: get_default_provider / set_default_provider
# =============================================================================


class ProviderResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_provider()
        self._saved = os.environ.pop("CRTW_LLM_PROVIDER", None)

    def tearDown(self) -> None:
        reset_default_provider()
        if self._saved is not None:
            os.environ["CRTW_LLM_PROVIDER"] = self._saved
        else:
            os.environ.pop("CRTW_LLM_PROVIDER", None)

    def test_default_is_null_when_no_env(self) -> None:
        provider = get_default_provider()
        self.assertIsInstance(provider, NullProvider)
        self.assertEqual(provider.name, "null")

    def test_short_name_in_registry(self) -> None:
        os.environ["CRTW_LLM_PROVIDER"] = "offline-mock"
        provider = get_default_provider()
        self.assertIsInstance(provider, OfflineMockProvider)

    def test_unknown_short_name_falls_back_to_null(self) -> None:
        os.environ["CRTW_LLM_PROVIDER"] = "nonexistent"
        provider = get_default_provider()
        self.assertIsInstance(provider, NullProvider)

    def test_set_default_provider_overrides(self) -> None:
        provider = ScriptedProvider(
            responses=[LLMResponse(text="manual", provider="scripted")]
        )
        set_default_provider(provider)
        self.assertIs(get_default_provider(), provider)

    def test_register_provider_adds_to_registry(self) -> None:
        class _Custom(BaseProvider):
            name = "custom-test"
            def _complete(self, request: LLMRequest) -> LLMResponse:
                return LLMResponse(text="custom", provider=self.name)

        register_provider("custom-test", _Custom)
        try:
            self.assertIn("custom-test", list_providers())
            os.environ["CRTW_LLM_PROVIDER"] = "custom-test"
            reset_default_provider()
            provider = get_default_provider()
            self.assertIsInstance(provider, _Custom)
        finally:
            # Clean up
            from crtw.agents import llm as _llm
            _llm._PROVIDER_REGISTRY.pop("custom-test", None)

    def test_module_class_form_works(self) -> None:
        os.environ["CRTW_LLM_PROVIDER"] = "crtw.agents.llm:OfflineMockProvider"
        provider = get_default_provider()
        self.assertIsInstance(provider, OfflineMockProvider)

    def test_anthropic_provider_missing_key_falls_back_to_null(self) -> None:
        os.environ["CRTW_LLM_PROVIDER"] = "anthropic"
        with mock.patch.dict(
            "sys.modules",
            {"anthropic": mock.MagicMock(Anthropic=mock.MagicMock())},
        ):
            provider = get_default_provider()
        # No key -> AnthropicProvider construction raises LLMStopped ->
        # get_default_provider falls back to NullProvider.
        self.assertIsInstance(provider, NullProvider)


# =============================================================================
# Protocol conformance
# =============================================================================


class ProtocolConformanceTests(unittest.TestCase):
    def test_all_built_in_providers_satisfy_protocol(self) -> None:
        instances: list[LLMProvider] = [
            NullProvider(),
            OfflineMockProvider(),
            ScriptedProvider(responses=[LLMResponse(text="x", provider="scripted")]),
        ]
        for inst in instances:
            self.assertIsInstance(inst, LLMProvider)


if __name__ == "__main__":
    unittest.main()
