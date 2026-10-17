import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import pymupdf
import pytest
from babeldoc.format.pdf.translation_config import TranslateResult
from pdf2zh_next import DeepSeekReviewSettings
from pdf2zh_next import OpenAISettings
from pdf2zh_next import PDFSettings
from pdf2zh_next import SettingsModel
from pdf2zh_next import high_level
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.main import ConfigManager
from pdf2zh_next.config.main import build_args_parser
from pdf2zh_next.visual_review import VISUAL_OUTPUT_CONTRACT
from pdf2zh_next.visual_review import VisualReviewError
from pdf2zh_next.visual_review import review_pdf_outputs


def make_pdf(path: Path, pages: int = 1, width: int = 300) -> Path:
    with pymupdf.open() as document:
        for number in range(pages):
            page = document.new_page(width=width, height=300)
            page.insert_text((30, 60), f"Algorithm ABC - page {number + 1}")
        document.save(path)
    return path


def response(content: str | None, reason: str = "stop") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason=reason
            )
        ],
        usage=SimpleNamespace(total_tokens=30, prompt_tokens=20, completion_tokens=10),
    )


def verdict(value: str = "pass") -> str:
    return json.dumps(
        {
            "verdict": value,
            "summary": "Checked the page pixels.",
            "issues": []
            if value != "needs_revision"
            else [
                {
                    "kind": "glyph",
                    "description": "Incorrect visible acronym",
                    "bbox": [0.1, 0.1, 0.4, 0.2],
                }
            ],
        }
    )


async def collect(stream: object) -> list[dict]:
    return [event async for event in stream]


@pytest.fixture
def setup_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    source = make_pdf(tmp_path / "source.pdf")
    output = make_pdf(tmp_path / "final.pdf")
    settings = SettingsModel(
        translate_engine_settings=DeepSeekReviewSettings(
            deepseek_review_api_key="test-key"
        )
    )
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.chat.completions.create = AsyncMock(return_value=response(verdict()))
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("pdf2zh_next.visual_review.openai.AsyncOpenAI", factory)
    monkeypatch.setattr("pdf2zh_next.visual_review.get_rate_limiter", lambda _qps: None)
    return SimpleNamespace(
        source=source,
        output=output,
        settings=settings,
        client=client,
        factory=factory,
        result=TranslateResult(output, None),
        directory=tmp_path,
    )


def read_report(setup: SimpleNamespace) -> dict:
    paths = list(setup.directory.glob("deepseek-visual-review-*/report.json"))
    assert len(paths) == 1
    return json.loads(paths[0].read_text(encoding="utf-8"))


def test_actual_page_images_and_context_are_sent(setup_review: SimpleNamespace) -> None:
    setup = setup_review
    setup.settings.translate_engine_settings.deepseek_review_domain = "robotics"
    setup.settings.translate_engine_settings.deepseek_review_visual_prompt = (
        "Read page pixels."
    )
    events = asyncio.run(
        collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
    )
    assert events[-1]["visual_review"]["status"] == "passed"
    assert events[-1]["visual_review"]["pages_reviewed"] == 1
    assert events[-1]["visual_review"]["token_usage"]["total"] == 30
    request = setup.client.chat.completions.create.call_args.kwargs
    assert request["model"] == "deepseek-flash"
    assert (
        request["messages"][0]["content"]
        == "Read page pixels.\n\n" + VISUAL_OUTPUT_CONTRACT
    )
    content = request["messages"][1]["content"]
    assert json.loads(content[0]["text"])["domain"] == "robotics"
    assert len(content) == 3
    for item in content[1:]:
        assert item["type"] == "image_url"
        image = base64.b64decode(item["image_url"]["url"].split(",", 1)[1])
        assert image.startswith(b"\x89PNG\r\n\x1a\n")
        assert item["image_url"]["detail"] == "original"
    report = read_report(setup)
    assert report["total_pages"] == len(report["pages"]) == 1
    assert report["outputs"][0]["sha256"]
    assert "test-key" not in json.dumps(report)
    setup.client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("value", ["needs_revision", "uncertain"])
def test_issues_or_uncertainty_block_completion(
    setup_review: SimpleNamespace, value: str
) -> None:
    setup = setup_review
    setup.client.chat.completions.create.return_value = response(verdict(value))
    with pytest.raises(VisualReviewError, match="need revision or manual review"):
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    report = read_report(setup)
    assert report["status"] == "needs_revision"
    assert report["pages"][0]["verdict"] == value
    assert (
        Path(next(setup.directory.glob("deepseek-visual-review-*")))
        / report["pages"][0]["image"]
    ).exists()


@pytest.mark.parametrize(
    "content,reason",
    [
        (None, "stop"),
        (verdict(), "length"),
        ("not JSON", "stop"),
        ('{"verdict":"pass","summary":"ok"}', "stop"),
        (verdict("needs_revision").replace('"needs_revision"', '"pass"'), "stop"),
        (verdict("needs_revision").replace("0.4", "1.4"), "stop"),
        (verdict("needs_revision").replace("0.4", "0.01"), "stop"),
        (verdict().replace('"pass"', '"not_sure"'), "stop"),
    ],
)
def test_invalid_review_never_passes(
    setup_review: SimpleNamespace, content: str | None, reason: str
) -> None:
    setup = setup_review
    setup.client.chat.completions.create.return_value = response(content, reason)
    with pytest.raises(VisualReviewError):
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    assert read_report(setup)["status"] == "error"


def test_api_failure_sanitizes_report_and_exception(
    setup_review: SimpleNamespace,
) -> None:
    setup = setup_review
    setup.client.chat.completions.create.side_effect = RuntimeError(
        "secret test-key data:image/png;base64,abc"
    )
    with pytest.raises(VisualReviewError) as error:
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    serialized = json.dumps(read_report(setup)) + str(error.value)
    assert "test-key" not in serialized
    assert "data:image" not in serialized
    assert read_report(setup)["current_page"]["output_page"] == 1


def test_cancellation_preserves_incomplete_report(
    setup_review: SimpleNamespace,
) -> None:
    setup = setup_review
    setup.client.chat.completions.create.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    assert read_report(setup)["status"] == "cancelled"
    setup.client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize("alternating", [False, True])
def test_every_output_variant_and_page_is_reviewed(
    setup_review: SimpleNamespace, alternating: bool
) -> None:
    setup = setup_review
    setup.source = make_pdf(setup.directory / "source-many.pdf", 3)
    setup.output = make_pdf(setup.directory / "final-many.pdf", 2)
    dual = make_pdf(
        setup.directory / "dual.pdf",
        4 if alternating else 2,
        300 if alternating else 600,
    )
    setup.settings.pdf = PDFSettings(
        pages="1,3",
        only_include_translated_page=True,
        use_alternating_pages_dual=alternating,
    )
    result = TranslateResult(setup.output, dual)
    events = asyncio.run(
        collect(review_pdf_outputs(setup.settings, setup.source, result))
    )
    assert events[-1]["visual_review"]["pages_reviewed"] == (6 if alternating else 4)
    report = read_report(setup)
    assert [page["source_page"] for page in report["pages"]] == (
        [1, 3, 1, 1, 3, 3] if alternating else [1, 3, 1, 3]
    )
    calls = setup.client.chat.completions.create.call_args_list
    if not alternating:
        assert len(calls[-1].kwargs["messages"][1]["content"]) == 5


def test_page_count_mismatch_blocks_before_api(setup_review: SimpleNamespace) -> None:
    setup = setup_review
    setup.source = make_pdf(setup.directory / "two-pages.pdf", 2)
    with pytest.raises(VisualReviewError):
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    setup.client.chat.completions.create.assert_not_awaited()
    assert read_report(setup)["status"] == "error"


def test_pdf_mutation_during_review_blocks_pass(setup_review: SimpleNamespace) -> None:
    setup = setup_review

    async def mutate(**_kwargs: object) -> SimpleNamespace:
        setup.output.write_bytes(setup.output.read_bytes() + b"\n% changed")
        return response(verdict())

    setup.client.chat.completions.create.side_effect = mutate
    with pytest.raises(VisualReviewError):
        asyncio.run(
            collect(review_pdf_outputs(setup.settings, setup.source, setup.result))
        )
    assert read_report(setup)["status"] == "error"


@pytest.mark.parametrize("debug", [False, True])
def test_high_level_finish_is_gated_by_visual_review(
    setup_review: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    setup = setup_review
    setup.settings.basic.debug = debug

    async def translated(*_args: object, **_kwargs: object) -> object:
        yield {
            "type": "finish",
            "translate_result": setup.result,
            "text_review": {"status": "passed"},
        }

    monkeypatch.setattr(high_level, "_translate_in_subprocess", translated)
    monkeypatch.setattr(high_level, "babeldoc_translate", translated)
    monkeypatch.setattr(
        high_level,
        "create_babeldoc_config",
        lambda *_args: SimpleNamespace(translator=MagicMock()),
    )
    events = asyncio.run(
        collect(high_level.do_translate_async_stream(setup.settings, setup.source))
    )
    assert [event["type"] for event in events] == ["visual_review_progress", "finish"]
    assert events[-1]["visual_review"]["status"] == "passed"
    assert events[-1]["token_usage"]["visual_review"]["total"] == 30


def test_high_level_rejects_bad_visual_review(
    setup_review: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = setup_review
    setup.client.chat.completions.create.return_value = response(
        verdict("needs_revision")
    )

    async def translated(*_args: object) -> object:
        yield {
            "type": "finish",
            "translate_result": setup.result,
            "text_review": {"status": "passed"},
        }

    monkeypatch.setattr(high_level, "_translate_in_subprocess", translated)
    events = []

    async def run() -> None:
        with pytest.raises(high_level.TranslationError):
            async for event in high_level.do_translate_async_stream(
                setup.settings, setup.source
            ):
                events.append(event)

    asyncio.run(run())
    assert events[-1]["type"] == "error"
    assert not any(event["type"] == "finish" for event in events)


def test_other_translation_engines_are_unchanged(
    setup_review: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = setup_review
    setup.settings.translate_engine_settings = OpenAISettings(openai_api_key="test-key")

    async def translated(*_args: object) -> object:
        yield {"type": "finish", "translate_result": setup.result}

    monkeypatch.setattr(high_level, "_translate_in_subprocess", translated)
    events = asyncio.run(
        collect(high_level.do_translate_async_stream(setup.settings, setup.source))
    )
    assert [event["type"] for event in events] == ["finish"]
    setup.factory.assert_not_called()


@pytest.mark.parametrize("debug", [False, True])
def test_incomplete_text_review_blocks_before_vision(
    setup_review: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, debug: bool
) -> None:
    setup = setup_review
    setup.settings.basic.debug = debug

    async def translated(*_args: object, **_kwargs: object) -> object:
        yield {"type": "finish", "translate_result": setup.result}

    translator = MagicMock()
    translator.raise_for_incomplete_reviews.side_effect = ValueError(
        "Unresolved text review"
    )
    monkeypatch.setattr(high_level, "_translate_in_subprocess", translated)
    monkeypatch.setattr(high_level, "babeldoc_translate", translated)
    monkeypatch.setattr(
        high_level,
        "create_babeldoc_config",
        lambda *_args: SimpleNamespace(translator=translator),
    )
    with pytest.raises(high_level.TranslationError):
        asyncio.run(
            collect(high_level.do_translate_async_stream(setup.settings, setup.source))
        )
    setup.factory.assert_not_called()


def test_visual_stream_without_completion_blocks_finish(
    setup_review: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    setup = setup_review

    async def translated(*_args: object) -> object:
        yield {
            "type": "finish",
            "translate_result": setup.result,
            "text_review": {"status": "passed"},
        }

    async def incomplete(*_args: object) -> object:
        for event in []:
            yield event

    monkeypatch.setattr(high_level, "_translate_in_subprocess", translated)
    monkeypatch.setattr("pdf2zh_next.visual_review.review_pdf_outputs", incomplete)
    with pytest.raises(
        high_level.TranslationError, match="visual review was not completed"
    ):
        asyncio.run(
            collect(high_level.do_translate_async_stream(setup.settings, setup.source))
        )


def test_visual_configuration_cli_env_roundtrip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parser, _ = build_args_parser()
    args = parser.parse_args(
        [
            "--deepseekreview",
            "--deepseek-review-visual-model",
            "deepseek-flash",
            "--deepseek-review-visual-prompt",
            "Inspect pixels",
        ]
    )
    assert args.deepseek_review_visual_prompt == "Inspect pixels"
    monkeypatch.setenv("PDF2ZH_DEEPSEEK_REVIEW_VISUAL_PROMPT", "Inspect pixels")
    values = ConfigManager().parse_env_vars()
    assert (
        values["deepseekreview_detail"]["deepseek_review_visual_prompt"]
        == "Inspect pixels"
    )
    settings = CLIEnvSettingsModel(deepseekreview=True, **values)
    restored = CLIEnvSettingsModel.model_validate_json(settings.model_dump_json())
    assert (
        restored.to_settings_model().translate_engine_settings.deepseek_review_visual_prompt
        == "Inspect pixels"
    )


def test_visual_model_must_be_nonempty() -> None:
    config = DeepSeekReviewSettings(
        deepseek_review_api_key="test-key", deepseek_review_visual_model=" "
    )
    with pytest.raises(ValueError, match="visual review model"):
        config.validate_settings()
