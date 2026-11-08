import sys
from pathlib import Path

from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.translate_engine_model import (
    TERM_EXTRACTION_ENGINE_METADATA_MAP,
)
from pdf2zh_next.config.translate_engine_model import DeepSeekSettings


def _gui(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    import pdf2zh_next.gui as gui

    return gui


def _base_gui_inputs(**overrides):
    inputs = {
        "service": "DeepSeek",
        "lang_from": "English",
        "lang_to": "Simplified Chinese",
        "page_range": "All",
        "page_input": "",
        "prompt": "",
        "ignore_cache": False,
        "no_mono": False,
        "no_dual": False,
        "dual_translate_first": False,
        "use_alternating_pages_dual": False,
        "watermark_output_mode": "Watermarked",
        "rate_limit_mode": "Custom",
        "custom_qps": 4,
        "custom_pool_workers": None,
        "min_text_length": 5,
        "rpc_doclayout": "",
        "enable_auto_term_extraction": True,
        "primary_font_family": "Auto",
        "skip_clean": False,
        "disable_rich_text_translate": False,
        "enhance_compatibility": False,
        "split_short_lines": False,
        "short_line_split_factor": 0.8,
        "translate_table_text": False,
        "skip_scanned_detection": False,
        "ocr_workaround": False,
        "max_pages_per_part": 0,
        "formular_font_pattern": "",
        "formular_char_pattern": "",
        "auto_enable_ocr_workaround": False,
        "only_include_translated_page": False,
        "merge_alternating_line_numbers": True,
        "remove_non_formula_lines": True,
        "non_formula_line_iou_threshold": 0.5,
        "figure_table_protection_threshold": 0.5,
        "skip_formula_offset_calculation": False,
        "term_service": "Follow main translation engine",
        "term_rate_limit_mode": "Custom",
        "term_rpm_input": 240,
        "term_concurrent_threads": 20,
        "term_custom_qps": 4,
        "term_custom_pool_workers": None,
        "custom_system_prompt_input": "",
        "glossaries": None,
        "save_auto_extracted_glossary": False,
        "deepseek_model": "deepseek-v4-flash",
        "deepseek_api_key": "dummy-key",
        "deepseek_enable_json_mode": False,
        "deepseek_thinking_mode": None,
        "deepseek_reasoning_effort": "high",
    }
    inputs.update(overrides)
    return inputs


def _build_settings(tmp_path: Path, ui_inputs: dict, gui, save_mode=None):
    if save_mode is None:
        save_mode = gui.SaveMode.never
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    return gui._build_translate_settings(
        CLIEnvSettingsModel(), input_pdf, output_dir, save_mode, ui_inputs
    )


def test_gui_deepseek_thinking_field_declares_mode_dropdown():
    mode_field = DeepSeekSettings.model_fields["deepseek_thinking_mode"]

    assert mode_field.default == "disabled"
    assert mode_field.json_schema_extra["gui"] == {
        "widget": "dropdown",
        "choices": [
            ("Unset (defaults to disabled)", None),
            ("enabled", "enabled"),
            ("disabled", "disabled"),
        ],
        "preserve_current_value": True,
    }


def test_gui_deepseek_mode_updates_preserve_enabled_and_unset(monkeypatch):
    gui = _gui(monkeypatch)
    field = DeepSeekSettings.model_fields["deepseek_thinking_mode"]

    enabled_update = gui._gui_field_update(field, visible=True, current_value="enabled")
    unset_update = gui._gui_field_update(field, visible=True, current_value=None)

    assert enabled_update["value"] == "enabled"
    assert unset_update["value"] is None
    assert unset_update["choices"][0] == (
        "Unset (defaults to disabled)",
        None,
    )


def test_gui_deepseek_reasoning_effort_metadata_controls_visibility(monkeypatch):
    gui = _gui(monkeypatch)
    field = DeepSeekSettings.model_fields["deepseek_reasoning_effort"]

    assert field.json_schema_extra["gui"] == {
        "widget": "dropdown",
        "choices": ["high", "max"],
        "default_on_show": "high",
        "visible_when": {
            "field": "deepseek_thinking_mode",
            "equals": "enabled",
        },
        "preserve_current_value": True,
    }
    assert gui._gui_field_visible(
        "deepseek_reasoning_effort",
        field,
        True,
        {"deepseek_thinking_mode": "disabled"},
    ) is False
    assert gui._gui_field_visible(
        "deepseek_reasoning_effort",
        field,
        True,
        {"deepseek_thinking_mode": "enabled"},
    ) is True


def test_gui_metadata_field_update_preserves_current_value(monkeypatch):
    gui = _gui(monkeypatch)
    field = DeepSeekSettings.model_fields["deepseek_reasoning_effort"]

    enabled_update = gui._gui_field_update(
        field,
        visible=True,
        current_value="max",
    )
    disabled_update = gui._gui_field_update(
        field,
        visible=False,
        current_value="max",
    )

    assert enabled_update["choices"] == ["high", "max"]
    assert enabled_update["value"] == "max"
    assert enabled_update["visible"] is True
    assert disabled_update["value"] == "max"
    assert disabled_update["visible"] is False


def test_term_deepseek_metadata_preserves_prefixed_visibility(monkeypatch):
    gui = _gui(monkeypatch)
    term_model = TERM_EXTRACTION_ENGINE_METADATA_MAP[
        "DeepSeek"
    ].term_setting_model_type
    term_mode_field = term_model.model_fields["term_deepseek_thinking_mode"]
    term_field = term_model.model_fields["term_deepseek_reasoning_effort"]

    assert term_mode_field.default == "disabled"
    assert term_mode_field.json_schema_extra["gui"]["choices"][0] == (
        "Unset (defaults to disabled)",
        None,
    )
    assert term_field.json_schema_extra["gui"]["widget"] == "dropdown"
    assert term_field.json_schema_extra["gui"]["choices"] == ["high", "max"]
    assert term_field.json_schema_extra["gui"]["visible_when"] == {
        "field": "deepseek_thinking_mode",
        "equals": "enabled",
    }
    assert gui._gui_field_visible(
        "term_deepseek_reasoning_effort",
        term_field,
        True,
        {"term_deepseek_thinking_mode": "disabled"},
    ) is False
    assert gui._gui_field_visible(
        "term_deepseek_reasoning_effort",
        term_field,
        True,
        {"term_deepseek_thinking_mode": "enabled"},
    ) is True


def test_gui_new_deepseek_model_uses_disabled_and_hides_effort(monkeypatch):
    gui = _gui(monkeypatch)
    model = DeepSeekSettings()
    mode_field = DeepSeekSettings.model_fields["deepseek_thinking_mode"]
    effort_field = DeepSeekSettings.model_fields["deepseek_reasoning_effort"]

    assert model.deepseek_thinking_mode == "disabled"
    assert gui._gui_field_value(mode_field, model.deepseek_thinking_mode) == "disabled"
    assert gui._gui_field_visible(
        "deepseek_reasoning_effort",
        effort_field,
        True,
        {"deepseek_thinking_mode": model.deepseek_thinking_mode},
    ) is False


def test_gui_unset_deepseek_current_run_sends_disabled_without_effort(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_mode=None,
            deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.translate_engine_settings.openai_send_reasoning_effort is None
    assert settings.translate_engine_settings.openai_reasoning_effort is None


def test_gui_disabled_deepseek_current_run_omits_reasoning_effort(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_mode="disabled",
            deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.translate_engine_settings.openai_send_reasoning_effort is None
    assert settings.translate_engine_settings.openai_reasoning_effort is None


def test_gui_enabled_deepseek_defaults_reasoning_effort_to_high(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_mode="enabled",
            deepseek_reasoning_effort="high",
        ),
        gui,
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "enabled"}
    }
    assert settings.translate_engine_settings.openai_send_reasoning_effort is True
    assert settings.translate_engine_settings.openai_reasoning_effort == "high"


def test_gui_enabled_deepseek_accepts_max_reasoning_effort(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_mode="enabled",
            deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.translate_engine_settings.openai_reasoning_effort == "max"


def test_term_deepseek_uses_same_thinking_mode_control(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode="enabled",
            term_deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "enabled"}
    }
    assert settings.term_extraction_engine_settings.openai_send_reasoning_effort is True
    assert settings.term_extraction_engine_settings.openai_reasoning_effort == "max"


def test_unset_term_deepseek_sends_disabled_without_effort(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode=None,
            term_deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.term_extraction_engine_settings.openai_send_reasoning_effort is None
    assert settings.term_extraction_engine_settings.openai_reasoning_effort is None


def test_disabled_term_deepseek_current_run_omits_reasoning_effort(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode="disabled",
            term_deepseek_reasoning_effort="max",
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.term_extraction_engine_settings.openai_send_reasoning_effort is None
    assert settings.term_extraction_engine_settings.openai_reasoning_effort is None


def test_gui_config_save_persists_selected_deepseek_thinking_settings(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    captured = {}

    class FakeConfigManager:
        config_cli_settings = CLIEnvSettingsModel()

        def write_user_default_config_file(self, settings):
            captured["settings"] = settings.clone()

    monkeypatch.setattr(gui, "config_manager", FakeConfigManager())

    _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_thinking_mode="disabled",
            deepseek_reasoning_effort="max",
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode="enabled",
            term_deepseek_reasoning_effort="high",
        ),
        gui,
        save_mode=gui.SaveMode.always,
    )

    saved = captured["settings"]
    assert saved.deepseek_detail.deepseek_thinking_mode == "disabled"
    assert saved.deepseek_detail.deepseek_reasoning_effort == "max"
    assert saved.term_deepseek_detail.term_deepseek_thinking_mode == "enabled"
    assert saved.term_deepseek_detail.term_deepseek_reasoning_effort == "high"


def test_gui_config_save_preserves_disabled_deepseek_reasoning_effort(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)

    captured = {}

    class FakeConfigManager:
        config_cli_settings = CLIEnvSettingsModel()

        def write_user_default_config_file(self, settings):
            captured["settings"] = settings.clone()

    monkeypatch.setattr(gui, "config_manager", FakeConfigManager())

    _build_settings(
        tmp_path,
        _base_gui_inputs(
            deepseek_reasoning_effort="max",
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode="disabled",
            term_deepseek_reasoning_effort="max",
        ),
        gui,
        save_mode=gui.SaveMode.always,
    )

    saved = captured["settings"]
    assert saved.deepseek_detail.deepseek_thinking_mode is None
    assert saved.deepseek_detail.deepseek_reasoning_effort == "max"
    assert saved.term_deepseek_detail.term_deepseek_thinking_mode == "disabled"
    assert saved.term_deepseek_detail.term_deepseek_reasoning_effort == "max"


def test_gui_main_deepseek_can_clear_saved_thinking_mode(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)
    base_settings = CLIEnvSettingsModel()
    base_settings.deepseek_detail.deepseek_thinking_mode = "disabled"
    base_settings.deepseek_detail.deepseek_reasoning_effort = "max"
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")

    settings = gui._build_translate_settings(
        base_settings,
        input_pdf,
        tmp_path,
        gui.SaveMode.never,
        _base_gui_inputs(deepseek_thinking_mode=None),
    )

    assert settings.translate_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.translate_engine_settings.openai_reasoning_effort is None


def test_gui_term_deepseek_can_clear_saved_thinking_mode(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)
    base_settings = CLIEnvSettingsModel()
    base_settings.term_deepseek_detail.term_deepseek_thinking_mode = "enabled"
    base_settings.term_deepseek_detail.term_deepseek_reasoning_effort = "max"
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")

    settings = gui._build_translate_settings(
        base_settings,
        input_pdf,
        tmp_path,
        gui.SaveMode.never,
        _base_gui_inputs(
            term_service="DeepSeek",
            term_deepseek_model="deepseek-v4-flash",
            term_deepseek_api_key="dummy-key",
            term_deepseek_enable_json_mode=False,
            term_deepseek_thinking_mode=None,
        ),
    )

    assert settings.term_extraction_engine_settings._openai_extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert settings.term_extraction_engine_settings.openai_reasoning_effort is None


def test_gui_term_nullable_int_field_accepts_present_none(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="Ollama",
            term_num_predict=None,
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings.num_predict is None


def test_gui_term_nullable_bool_field_accepts_present_none(tmp_path, monkeypatch):
    gui = _gui(monkeypatch)

    settings = _build_settings(
        tmp_path,
        _base_gui_inputs(
            term_service="OpenAI",
            term_openai_api_key="dummy-key",
            term_openai_send_reasoning_effort=None,
        ),
        gui,
    )

    assert settings.term_extraction_engine_settings.openai_send_reasoning_effort is None


def test_deepseek_thinking_mode_rejects_unknown_value():
    settings = DeepSeekSettings(
        deepseek_api_key="dummy-key",
        deepseek_thinking_mode="auto",
    )

    try:
        settings.validate_settings()
    except ValueError as exc:
        assert str(exc) == "DeepSeek thinking mode must be enabled or disabled"
    else:
        raise AssertionError("Expected unknown thinking mode to fail")
