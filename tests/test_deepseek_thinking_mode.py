from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings
from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator


class FakeRateLimiter:
    def wait(self, rate_limit_params: dict | None = None):
        pass


class FakeCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="translated"))],
            usage=None,
        )


class FakeOpenAIClient:
    def __init__(self):
        self.completions = FakeCompletions()
        self.chat = SimpleNamespace(completions=self.completions)


def build_deepseek_settings(
    model: str,
    thinking_mode: str | None = None,
    reasoning_effort: str | None = None,
) -> SettingsModel:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekSettings(
            deepseek_model=model,
            deepseek_api_key="dummy-key",
            deepseek_thinking_mode=thinking_mode,
            deepseek_reasoning_effort=reasoning_effort,
        )
    )
    settings.validate_settings()
    return settings


def build_translator(settings: SettingsModel) -> tuple[OpenAITranslator, FakeOpenAIClient]:
    fake_client = FakeOpenAIClient()
    with patch(
        "pdf2zh_next.translator.translator_impl.openai.openai.OpenAI",
        return_value=fake_client,
    ):
        translator = OpenAITranslator(settings, FakeRateLimiter())
    return translator, fake_client


def test_deepseek_settings_default_to_disabled_thinking_mode():
    settings = DeepSeekSettings(deepseek_api_key="dummy-key")

    assert settings.deepseek_thinking_mode == "disabled"


def test_deepseek_v4_unforced_omits_extra_body_and_reasoning_effort():
    settings = build_deepseek_settings("deepseek-v4-flash")
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert "extra_body" not in request_kwargs
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_v4_disabled_sends_extra_body_without_reasoning_effort():
    settings = build_deepseek_settings(
        "deepseek-v4-flash",
        thinking_mode="disabled",
        reasoning_effort="max",
    )
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_v4_enabled_sends_extra_body_and_configured_effort():
    settings = build_deepseek_settings(
        "deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="high",
    )
    translator, fake_client = build_translator(settings)

    translator.do_llm_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request_kwargs["reasoning_effort"] == "high"


def test_deepseek_v4_enabled_without_effort_omits_reasoning_effort():
    settings = build_deepseek_settings("deepseek-v4-flash", thinking_mode="enabled")
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_rejects_unknown_thinking_mode():
    settings = DeepSeekSettings(
        deepseek_api_key="dummy-key",
        deepseek_thinking_mode="auto",
    )

    try:
        settings.validate_settings()
    except ValueError as exc:
        assert str(exc) == "DeepSeek thinking mode must be enabled or disabled"
    else:
        raise AssertionError("Expected unknown DeepSeek thinking mode to fail")


def test_deepseek_rejects_unknown_reasoning_effort():
    settings = DeepSeekSettings(
        deepseek_api_key="dummy-key",
        deepseek_reasoning_effort="medium",
    )

    try:
        settings.validate_settings()
    except ValueError as exc:
        assert str(exc) == "DeepSeek reasoning effort must be high or max"
    else:
        raise AssertionError("Expected unknown DeepSeek reasoning effort to fail")


def test_deepseek_alias_models_do_not_send_extra_body_thinking():
    for model in ("deepseek-chat", "deepseek-reasoner"):
        settings = build_deepseek_settings(
            model,
            thinking_mode="enabled",
            reasoning_effort="high",
        )
        translator, fake_client = build_translator(settings)

        translator.do_translate("hello")

        request_kwargs = fake_client.completions.calls[0]
        assert "extra_body" not in request_kwargs
        assert "reasoning_effort" not in request_kwargs


def test_deepseek_v4_cache_impact_distinguishes_thinking_modes():
    unforced_settings = build_deepseek_settings("deepseek-v4-flash")
    disabled_settings = build_deepseek_settings(
        "deepseek-v4-flash",
        thinking_mode="disabled",
    )
    enabled_settings = build_deepseek_settings("deepseek-v4-flash", "enabled")
    unforced_translator, _ = build_translator(unforced_settings)
    disabled_translator, _ = build_translator(disabled_settings)
    enabled_translator, _ = build_translator(enabled_settings)

    assert "extra_body" not in unforced_translator.cache.params
    assert disabled_translator.cache.params["extra_body"] == {
        "thinking": {"type": "disabled"}
    }
    assert enabled_translator.cache.params["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert (
        disabled_translator.cache.translate_engine_params
        != enabled_translator.cache.translate_engine_params
    )
    assert (
        unforced_translator.cache.translate_engine_params
        != disabled_translator.cache.translate_engine_params
    )


def test_deepseek_settings_excludes_old_paired_thinking_bools():
    assert "deepseek_thinking_enabled" not in DeepSeekSettings.model_fields
    assert "deepseek_thinking_disabled" not in DeepSeekSettings.model_fields
