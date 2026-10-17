import json
from collections.abc import Generator
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest
from pdf2zh_next import DeepSeekReviewSettings
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import ConfigManager
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import OpenAISettings
from pdf2zh_next.translator.cache import clean_test_db
from pdf2zh_next.translator.cache import init_test_db
from pdf2zh_next.translator.translator_impl.deepseekreview import REVIEW_SYSTEM_PROMPT
from pdf2zh_next.translator.translator_impl.deepseekreview import (
    TRANSLATION_SYSTEM_PROMPT,
)
from pdf2zh_next.translator.translator_impl.deepseekreview import (
    DeepSeekReviewTranslator,
)
from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator
from pdf2zh_next.translator.utils import get_translator
from tenacity import wait_none


def completion(content: str | None, finish_reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason=finish_reason
            )
        ],
        usage=SimpleNamespace(total_tokens=30, prompt_tokens=20, completion_tokens=10),
    )


@pytest.fixture
def engine(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[DeepSeekReviewTranslator, None, None]:
    database = init_test_db()
    client = MagicMock()
    monkeypatch.setattr(
        "pdf2zh_next.translator.translator_impl.openai.openai.OpenAI",
        lambda **_kwargs: client,
    )
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key",
            deepseek_review_domain="reinforcement learning",
            deepseek_review_context="DreamerV3; actor and critic are RL components.",
        )
    )
    translator = DeepSeekReviewTranslator(settings, MagicMock())
    yield translator
    clean_test_db(database)


def test_reviewed_text_reaches_cache(engine: DeepSeekReviewTranslator) -> None:
    source = "All entries of twohot are 0 except for the two entries closest to x."
    revised = "twohot 中除最接近 x 的两个条目外，其余条目均为 0。"
    engine.client.chat.completions.create.side_effect = [
        completion("twohot 中最接近 x 的两个条目也为 0。"),
        completion(json.dumps({"translation": revised})),
    ]
    assert engine.translate(source) == revised
    assert engine.translate(source) == revised
    assert engine.client.chat.completions.create.call_count == 2
    assert engine.rate_limiter.wait.call_count == 2
    review = engine.client.chat.completions.create.call_args.kwargs
    assert review["messages"][0]["content"] == REVIEW_SYSTEM_PROMPT
    payload = json.loads(review["messages"][1]["content"])
    assert source in payload["original_request"]
    assert payload["domain"] == "reinforcement learning"
    assert "DreamerV3" in payload["background"]
    assert engine.token_count.value == 60
    draft_call = engine.client.chat.completions.create.call_args_list[0].kwargs
    assert draft_call["messages"][0]["content"] == TRANSLATION_SYSTEM_PROMPT
    assert draft_call["messages"][0]["content"] != review["messages"][0]["content"]
    draft_payload = json.loads(draft_call["messages"][1]["content"])
    assert draft_payload["domain"] == payload["domain"]
    assert draft_payload["background"] == payload["background"]
    assert source in draft_payload["original_request"]


@pytest.mark.parametrize("method", ["translate", "llm_translate"])
def test_unresolved_review_failure_blocks_fallback_until_successful_retry(
    engine: DeepSeekReviewTranslator, method: str
) -> None:
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        completion("not JSON"),
    ]
    with pytest.raises(ValueError, match="invalid JSON"):
        getattr(engine, method)("actor")
    with pytest.raises(ValueError, match="unresolved failed requests"):
        engine.raise_for_incomplete_reviews()
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        completion(json.dumps({"translation": "策略网络"})),
    ]
    assert getattr(engine, method)("actor") == "策略网络"
    engine.raise_for_incomplete_reviews()
    assert getattr(engine, method)("actor") == "策略网络"
    engine.raise_for_incomplete_reviews()


def test_batch_keeps_context_ids_and_placeholders(
    engine: DeepSeekReviewTranslator,
) -> None:
    request = 'Title: Mastering Diverse Domains through World Models\nGlossary: critic -> 价值网络\n[{"id": 7, "input": "Critic learning {v1}<style id=\'2\'>1.44 bits</style>"}]'
    draft = json.dumps(
        [{"id": 7, "output": "批评学习 {v1}<style id='2'>1 以下 44 比特</style>"}]
    )
    revised = json.dumps(
        [{"id": 7, "output": "价值网络学习 {v1}<style id='2'>1.44 比特</style>"}]
    )
    engine.client.chat.completions.create.side_effect = [
        completion(draft),
        completion(json.dumps({"translation": revised})),
    ]
    assert (
        engine.llm_translate(request, rate_limit_params={"request_json_mode": True})
        == revised
    )
    payload = json.loads(
        engine.client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    )
    assert payload["original_request"] == request
    draft_call = engine.client.chat.completions.create.call_args_list[0].kwargs
    assert draft_call["messages"][0]["content"] == TRANSLATION_SYSTEM_PROMPT
    assert (
        json.loads(draft_call["messages"][1]["content"])["original_request"] == request
    )
    assert engine.client.chat.completions.create.call_args.kwargs[
        "response_format"
    ] == {"type": "json_object"}


@pytest.mark.parametrize(
    "draft,revised",
    [
        ('[{"id": 1, "output": "草稿"}]', '[{"id": 2, "output": "译文"}]'),
        ('[{"id": "a", "output": "草稿"}]', '[{"id": "b", "output": "译文"}]'),
        ('[{"id": 1, "output": "草稿"}]', "[]"),
        ('[{"id": 1, "output": "草稿"}]', '[{"id": 1, "text": "译文"}]'),
        ('[{"id": 1, "output": "草稿"}]', '[{"id": 1, "output": 12}]'),
        ('[{"id": 1, "output": "草稿"}]', "not JSON"),
        (
            '```json\n[{"id": 1, "output": "草稿"}]\n```',
            '[{"id": 2, "output": "译文"}]',
        ),
        (
            '{"source": "actor", "target": "演员"}',
            '{"source": "critic", "target": "策略网络"}',
        ),
        ('[{"src": "actor", "tgt": "演员"}]', '[{"src": "critic", "tgt": "策略网络"}]'),
        ("公式 {v1} {v1}", "公式 {v1}"),
        ("<style id='2'>术语</style>", "<style id='3'>术语</style>"),
        ("草稿", ""),
    ],
)
def test_invalid_revision_is_not_cached(
    engine: DeepSeekReviewTranslator, draft: str, revised: str
) -> None:
    engine.client.chat.completions.create.side_effect = [
        completion(draft),
        completion(json.dumps({"translation": revised})),
    ]
    with pytest.raises(ValueError, match="DeepSeek review"):
        engine.llm_translate("request")
    assert engine.cache.get("request") is None


@pytest.mark.parametrize(
    "content,finish_reason",
    [
        (None, "stop"),
        ('{"translation":"译文"}', "length"),
        ("not JSON", "stop"),
        ('{"explanation":"wrong field"}', "stop"),
        ('{"translation":12}', "stop"),
    ],
)
def test_incomplete_or_invalid_review(
    engine: DeepSeekReviewTranslator, content: str | None, finish_reason: str
) -> None:
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        completion(content, finish_reason),
    ]
    with pytest.raises(ValueError, match="DeepSeek review"):
        engine.translate("source")
    assert engine.cache.get("source") is None


def test_cache_separates_review_context(engine: DeepSeekReviewTranslator) -> None:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key",
            deepseek_review_context="different paper",
        )
    )
    other = DeepSeekReviewTranslator(settings, MagicMock())
    engine.cache.set("source", "reviewed")
    assert other.cache.get("source") is None
    assert settings.translate_engine_settings.translate_engine_type == "DeepSeekReview"


def test_settings_cli_env_and_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    config = DeepSeekReviewSettings(
        deepseek_review_api_key=" test-key ",
        deepseek_review_translation_prompt=" Translate scientific prose. ",
        deepseek_review_prompt=" Check scientific accuracy. ",
    )
    config.validate_settings()
    assert config.deepseek_review_api_key == "test-key"
    assert config.deepseek_review_translation_prompt == "Translate scientific prose."
    assert config.deepseek_review_prompt == "Check scientific accuracy."
    assert "deepseek_review_api_key" in GUI_PASSWORD_FIELDS
    cli = CLIEnvSettingsModel(deepseekreview=True, deepseekreview_detail=config)
    settings = cli.to_settings_model()
    settings.validate_settings()
    assert settings.translate_engine_settings == config
    restored = SettingsModel.model_validate_json(settings.model_dump_json())
    assert restored.translate_engine_settings == config
    parser, _ = build_args_parser()
    args = parser.parse_args(
        [
            "--deepseekreview",
            "--deepseek-review-domain",
            "robotics",
            "--deepseek-review-translation-prompt",
            "Translate robotics research.",
            "--deepseek-review-prompt",
            "Check physical units.",
        ]
    )
    assert args.deepseekreview is True
    assert args.deepseek_review_domain == "robotics"
    assert args.deepseek_review_translation_prompt == "Translate robotics research."
    assert args.deepseek_review_prompt == "Check physical units."
    monkeypatch.setenv("PDF2ZH_DEEPSEEK_REVIEW_API_KEY", "env-test-key")
    monkeypatch.setenv(
        "PDF2ZH_DEEPSEEK_REVIEW_TRANSLATION_PROMPT", "Translate faithfully."
    )
    monkeypatch.setenv("PDF2ZH_DEEPSEEK_REVIEW_PROMPT", "Review faithfully.")
    env = ConfigManager().parse_env_vars()
    assert env["deepseekreview_detail"]["deepseek_review_api_key"] == "env-test-key"
    assert (
        env["deepseekreview_detail"]["deepseek_review_translation_prompt"]
        == "Translate faithfully."
    )
    assert (
        env["deepseekreview_detail"]["deepseek_review_prompt"] == "Review faithfully."
    )


@pytest.mark.parametrize("field", ["deepseek_review_api_key", "deepseek_review_model"])
def test_blank_settings_are_rejected(field: str) -> None:
    values = {"deepseek_review_api_key": "test-key", field: "   "}
    config = DeepSeekReviewSettings(**values)
    with pytest.raises(ValueError, match="is required"):
        config.validate_settings()


def test_none_llm_request_skips_both_passes(engine: DeepSeekReviewTranslator) -> None:
    assert engine.do_llm_translate(None) is None
    engine.client.chat.completions.create.assert_not_called()


def test_fenced_batch_is_validated(engine: DeepSeekReviewTranslator) -> None:
    draft = '```json\n[{"id": 1, "output": "草稿 {v1}"}]\n```'
    revised = '[{"id": 1, "output": "译文 {v1}"}]'
    engine.client.chat.completions.create.side_effect = [
        completion(draft),
        completion(json.dumps({"translation": revised})),
    ]
    assert engine.llm_translate("request") == revised


def test_review_rate_limit_retries_without_retranslating(
    engine: DeepSeekReviewTranslator, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = httpx.Response(
        429, request=httpx.Request("POST", "https://api.deepseek.com")
    )
    monkeypatch.setattr(engine._review.retry, "wait", wait_none())
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        openai.RateLimitError("Rate limited", response=response, body=None),
        completion('{"translation":"译文"}'),
    ]
    assert engine.translate("source") == "译文"
    assert engine.client.chat.completions.create.call_count == 3
    assert engine.rate_limiter.wait.call_count == 3


def test_api_failure_is_not_cached(engine: DeepSeekReviewTranslator) -> None:
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        openai.APIConnectionError(
            request=httpx.Request("POST", "https://api.deepseek.com")
        ),
    ]
    with pytest.raises(openai.APIConnectionError):
        engine.translate("source")
    assert engine.cache.get("source") is None


def test_factory_dispatches_review_engine(engine: DeepSeekReviewTranslator) -> None:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key"
        )
    )
    settings.validate_settings()
    engine.client.chat.completions.create.side_effect = [
        completion("你好"),
        completion('{"translation":"你好"}'),
    ]
    translator = get_translator(settings)
    assert isinstance(translator, DeepSeekReviewTranslator)
    assert engine.client.chat.completions.create.call_count == 2


def test_custom_prompts_apply_to_separate_passes(
    engine: DeepSeekReviewTranslator,
) -> None:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key",
            deepseek_review_translation_prompt="Translate using robotics terminology.",
            deepseek_review_prompt="Review negation and physical units carefully.",
        )
    )
    custom = DeepSeekReviewTranslator(settings, MagicMock())
    engine.client.chat.completions.create.side_effect = [
        completion("草稿"),
        completion('{"translation":"译文"}'),
    ]
    assert custom.llm_translate("request") == "译文"
    calls = custom.client.chat.completions.create.call_args_list
    translation_prompt = calls[0].kwargs["messages"][0]["content"]
    review_prompt = calls[1].kwargs["messages"][0]["content"]
    assert translation_prompt.startswith("Translate using robotics terminology.")
    assert "Review negation" not in translation_prompt
    assert review_prompt.startswith("Review negation and physical units carefully.")
    assert '"translation"' in review_prompt
    assert "JSON" in translation_prompt


@pytest.mark.parametrize(
    "field", ["deepseek_review_translation_prompt", "deepseek_review_prompt"]
)
def test_prompt_changes_separate_cached_results(
    engine: DeepSeekReviewTranslator, field: str
) -> None:
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key",
            deepseek_review_domain=engine.domain,
            deepseek_review_context=engine.context,
            **{field: "Custom scientific editing instructions."},
        )
    )
    custom = DeepSeekReviewTranslator(settings, MagicMock())
    engine.cache.set("request", "cached review")
    assert custom.cache.get("request") is None


def test_plain_openai_llm_messages_remain_unchanged(
    engine: DeepSeekReviewTranslator,
) -> None:
    settings = SettingsModel(
        translate_engine_settings=OpenAISettings(openai_api_key="test-key")
    )
    translator = OpenAITranslator(settings, MagicMock())
    engine.client.chat.completions.create.return_value = completion("translated")
    assert translator.do_llm_translate("original request") == "translated"
    assert translator.client.chat.completions.create.call_args.kwargs["messages"] == [
        {"role": "user", "content": "original request"}
    ]
