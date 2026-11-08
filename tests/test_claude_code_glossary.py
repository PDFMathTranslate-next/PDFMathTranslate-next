import json
import subprocess
import sys
from pathlib import Path

import pytest
from babeldoc.format.pdf.high_level import translator_supports_llm
from babeldoc.glossary import Glossary
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.translate_engine_model import (
    TERM_EXTRACTION_ENGINE_METADATA_MAP,
)
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.translator.translator_impl.claudecode import ClaudeCodeTranslator
from pdf2zh_next.translator.utils import get_translator


def translator():
    instance = object.__new__(ClaudeCodeTranslator)
    instance.claude_code_path = "claude"
    instance.claude_code_model = "test-model"
    instance.lang_out = "zh"
    return instance


def test_claude_supports_glossaries_without_enabling_automatic_extraction():
    metadata = TRANSLATION_ENGINE_METADATA_MAP["ClaudeCode"]
    assert metadata.support_glossary is True
    assert metadata.support_llm is False
    assert "ClaudeCode" not in TERM_EXTRACTION_ENGINE_METADATA_MAP
    settings = CLIEnvSettingsModel(claudecode=True).to_settings_model()
    settings.validate_settings()
    assert settings.term_extraction_engine_settings is None
    assert settings.translation.no_auto_extract_glossary is True
    assert TRANSLATION_ENGINE_METADATA_MAP["OpenAI"].support_glossary is True
    assert TRANSLATION_ENGINE_METADATA_MAP["Google"].support_glossary is False


def test_claude_translator_accepts_explicit_glossary_without_auto_extraction(
    monkeypatch,
):
    settings = CLIEnvSettingsModel(
        claudecode=True, translation={"glossaries": "terms.csv"}
    ).to_settings_model()
    settings.validate_settings()
    monkeypatch.setattr(ClaudeCodeTranslator, "_test_claude_code", lambda _self: None)
    monkeypatch.setattr(
        ClaudeCodeTranslator, "do_translate", lambda _self, _text, *_args: "ok"
    )
    instance = get_translator(settings)
    assert isinstance(instance, ClaudeCodeTranslator)
    assert settings.translation.no_auto_extract_glossary is True


def test_gui_accepts_utf8_glossary_for_claude_but_not_google(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    import pdf2zh_next.gui as gui

    monkeypatch.setattr(gui.tempfile, "tempdir", str(tmp_path))
    data = "source,target,tgt_lng\nkidney,肾脏,zh\n".encode("utf-8-sig")
    path = gui._build_glossary_list([data], "ClaudeCode")
    assert path is not None
    terms = Glossary.from_csv(Path(path), target_lang_out="zh").entries
    assert len(terms) == 1
    assert terms[0].source == "kidney"
    assert terms[0].target == "肾脏"
    assert gui._build_glossary_list([data], "Google") is None


def test_llm_probe_does_not_launch_a_process(monkeypatch):
    monkeypatch.setattr(
        "subprocess.Popen", lambda *_args, **_kwargs: pytest.fail("unexpected process")
    )
    assert translator().do_llm_translate(None) is None
    assert translator_supports_llm(translator()) is True


def test_llm_request_passes_complete_prompt_without_translation_wrapper(monkeypatch):
    captured = {}
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-key")

    class Process:
        returncode = 0

        def communicate(self, **kwargs):
            captured["input"] = json.loads(kwargs["input"])
            return json.dumps(
                {
                    "type": "assistant",
                    "message": {"content": [{"type": "text", "text": "术语结果"}]},
                }
            ), ""

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return Process()

    monkeypatch.setattr("subprocess.Popen", popen)
    prompt = "Translate with glossary: kidney = 肾脏. Return JSON."
    assert (
        translator().do_llm_translate(prompt, {"request_json_mode": True}) == "术语结果"
    )
    assert captured["input"]["message"] == {"role": "user", "content": prompt}
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert "ANTHROPIC_API_KEY" not in captured["kwargs"]["env"]
    assert captured["command"][captured["command"].index("--tools") + 1] == ""
    assert "--no-session-persistence" in captured["command"]


def test_normal_translation_still_uses_standard_translation_prompt(monkeypatch):
    instance = translator()
    captured = []
    monkeypatch.setattr(
        instance, "_run_prompt", lambda prompt: captured.append(prompt) or "译文"
    )
    assert instance.do_translate("kidney") == "译文"
    assert "translate it into zh" in captured[0]
    assert captured[0].endswith("kidney")


def test_stream_result_fallback_and_error_handling():
    instance = translator()
    assert (
        instance._parse_output(
            json.dumps({"type": "result", "result": "译文", "is_error": False})
        )
        == "译文"
    )
    assistant = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "译文"}]},
    }
    final = {"type": "result", "result": "译文", "is_error": False}
    assert (
        instance._parse_output(json.dumps(assistant) + "\n" + json.dumps(final))
        == "译文"
    )
    with pytest.raises(ValueError, match="returned an error"):
        instance._parse_output(
            json.dumps({"type": "result", "is_error": True, "result": "error"})
        )
    with pytest.raises(ValueError, match="No translation"):
        instance._parse_output(json.dumps({"type": "system"}))


def test_timeout_kills_cli_and_does_not_leak_prompt(monkeypatch, caplog):
    class Process:
        returncode = None
        killed = False
        waited = False

        def communicate(self, **_kwargs):
            raise subprocess.TimeoutExpired("claude", 120)

        def kill(self):
            self.killed = True

        def wait(self):
            self.waited = True

    process = Process()
    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: process)
    with pytest.raises(ValueError, match="timed out"):
        translator()._run_prompt("private document text")
    assert process.killed
    assert process.waited
    assert "private document text" not in caplog.text


def test_cli_failure_does_not_expose_cli_error_output(monkeypatch, caplog):
    class Process:
        returncode = 1

        def communicate(self, **_kwargs):
            return "", "private stderr"

    monkeypatch.setattr("subprocess.Popen", lambda *_args, **_kwargs: Process())
    with pytest.raises(subprocess.CalledProcessError) as caught:
        translator()._run_prompt("private document text")
    assert "private stderr" not in str(caught.value)
    assert "private document text" not in caplog.text
