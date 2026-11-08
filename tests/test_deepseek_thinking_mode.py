from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
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


OMITTED = object()


def build_deepseek_settings(
    model: str,
    thinking_mode: str | None | object = OMITTED,
    reasoning_effort: str | None = None,
) -> SettingsModel:
    deepseek_kwargs = {
        "deepseek_model": model,
        "deepseek_api_key": "dummy-key",
        "deepseek_reasoning_effort": reasoning_effort,
    }
    if thinking_mode is not OMITTED:
        deepseek_kwargs["deepseek_thinking_mode"] = thinking_mode
    settings = SettingsModel(
        translate_engine_settings=DeepSeekSettings(**deepseek_kwargs)
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


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        ("deepseek-v4-flash", "high"),
        ("deepseek-chat", "max"),
        ("deepseek-reasoner", "high"),
        ("custom-deepseek-model", "max"),
    ],
)
def test_deepseek_enabled_is_model_name_independent(model, effort):
    settings = build_deepseek_settings(model, "enabled", effort)
    translator, fake_client = build_translator(settings)

    translator.do_llm_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["model"] == model
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert request_kwargs["reasoning_effort"] == effort


@pytest.mark.parametrize(
    "model",
    ["deepseek-v4-flash", "deepseek-chat", "deepseek-reasoner", "custom-model"],
)
def test_deepseek_disabled_is_model_name_independent_and_omits_effort(model):
    settings = build_deepseek_settings(model, "disabled", "max")
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["model"] == model
    assert request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request_kwargs


@pytest.mark.parametrize("request_method", ["do_translate", "do_llm_translate"])
def test_deepseek_enabled_without_effort_omits_reasoning_effort(request_method):
    settings = build_deepseek_settings("deepseek-chat", "enabled")
    translator, fake_client = build_translator(settings)

    getattr(translator, request_method)("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "enabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_omitted_thinking_mode_defaults_to_explicit_disabled():
    deepseek = DeepSeekSettings(
        deepseek_model="custom-model",
        deepseek_api_key="dummy-key",
        deepseek_reasoning_effort="max",
    )
    assert deepseek.deepseek_thinking_mode == "disabled"
    settings = SettingsModel(translate_engine_settings=deepseek)
    settings.validate_settings()
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request_kwargs


@pytest.mark.parametrize("model", ["deepseek-v4-flash", "deepseek-chat"])
def test_deepseek_explicit_none_sends_disabled_without_effort(model):
    settings = build_deepseek_settings(model, None, "max")
    translator, fake_client = build_translator(settings)

    translator.do_translate("hello")

    request_kwargs = fake_client.completions.calls[0]
    assert request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in request_kwargs


def test_deepseek_rejects_unknown_thinking_mode():
    settings = DeepSeekSettings(
        deepseek_api_key="dummy-key",
        deepseek_thinking_mode="auto",
    )

    with pytest.raises(
        ValueError, match="DeepSeek thinking mode must be enabled or disabled"
    ):
        settings.validate_settings()


def test_deepseek_rejects_unknown_reasoning_effort():
    settings = DeepSeekSettings(
        deepseek_api_key="dummy-key",
        deepseek_reasoning_effort="medium",
    )

    with pytest.raises(
        ValueError, match="DeepSeek reasoning effort must be high or max"
    ):
        settings.validate_settings()


def test_deepseek_cache_inputs_follow_effective_thinking_mode():
    omitted_translator, _ = build_translator(
        build_deepseek_settings("deepseek-chat")
    )
    none_translator, _ = build_translator(
        build_deepseek_settings("deepseek-chat", None)
    )
    disabled_translator, _ = build_translator(
        build_deepseek_settings("deepseek-chat", "disabled")
    )
    enabled_translator, _ = build_translator(
        build_deepseek_settings("deepseek-chat", "enabled")
    )

    disabled_body = {"thinking": {"type": "disabled"}}
    for translator in (omitted_translator, none_translator, disabled_translator):
        assert translator.cache.params["extra_body"] == disabled_body
    assert enabled_translator.cache.params["extra_body"] == {
        "thinking": {"type": "enabled"}
    }
    assert (
        omitted_translator.cache.translate_engine_params
        == none_translator.cache.translate_engine_params
        == disabled_translator.cache.translate_engine_params
    )
    assert (
        enabled_translator.cache.translate_engine_params
        != disabled_translator.cache.translate_engine_params
    )


def test_deepseek_settings_excludes_old_paired_thinking_bools():
    assert "deepseek_thinking_enabled" not in DeepSeekSettings.model_fields
    assert "deepseek_thinking_disabled" not in DeepSeekSettings.model_fields
