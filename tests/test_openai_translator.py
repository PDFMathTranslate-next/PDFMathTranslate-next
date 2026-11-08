from types import SimpleNamespace
from unittest.mock import Mock

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import OpenAISettings
from pdf2zh_next.translator.translator_impl.openai import OpenAITranslator


def _build_translator(use_stream: bool) -> OpenAITranslator:
    settings = SettingsModel(
        translate_engine_settings=OpenAISettings(
            openai_api_key="test-key",
            openai_model="test-model",
            openai_use_stream=use_stream,
        )
    )
    return OpenAITranslator(settings, rate_limiter=None)


def test_openai_translator_uses_non_stream_by_default():
    translator = _build_translator(use_stream=False)
    create = Mock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=" translated text "),
                )
            ],
            usage=None,
        )
    )
    translator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    assert translator.do_llm_translate("source text") == "translated text"
    assert create.call_args.kwargs.get("stream") is not True


def test_openai_translator_can_collect_stream_chunks():
    translator = _build_translator(use_stream=True)
    create = Mock(
        return_value=iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(delta=SimpleNamespace(content=" translated"))
                    ],
                    usage=None,
                ),
                SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=" text "))],
                    usage=None,
                ),
                SimpleNamespace(choices=[], usage=None),
            ]
        )
    )
    translator.client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )

    assert translator.do_llm_translate("source text") == "translated text"
    assert create.call_args.kwargs["stream"] is True
