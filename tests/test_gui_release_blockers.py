import sys
import tempfile
from pathlib import Path

import pytest
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel


def _gui(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["pytest"])
    import pdf2zh_next.gui as gui

    return gui


def _empty_state():
    return {
        "session_id": None,
        "current_task": None,
        "results": {},
        "file_order": [],
        "display_map": {},
        "parent_map": {},
        "uploaded_files": [],
    }


def _base_gui_inputs():
    return {
        "service": "SiliconFlowFree",
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
        "watermark_output_mode": "No Watermark",
        "rate_limit_mode": "Custom",
        "custom_qps": 4,
        "custom_pool_workers": None,
        "min_text_length": 5,
        "rpc_doclayout": "",
        "enable_auto_term_extraction": False,
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
        "siliconflow_free_enable_json_mode": False,
    }


def test_pdf_preview_allowed_paths_exclude_broad_filesystem_paths(monkeypatch):
    gui = _gui(monkeypatch)

    allowed_paths = [Path(path).resolve() for path in gui.pdf_preview_allowed_paths]
    root_paths = {Path(path.anchor).resolve() for path in allowed_paths if path.anchor}

    assert Path.cwd().resolve() not in allowed_paths
    assert Path.home().resolve() not in allowed_paths
    assert not root_paths.intersection(allowed_paths)


def test_pdf_preview_allowed_paths_keep_accepted_preview_locations(monkeypatch):
    gui = _gui(monkeypatch)

    allowed_paths = [Path(path).resolve() for path in gui.pdf_preview_allowed_paths]
    expected_paths = {
        gui.logo_path.resolve(),
        Path("pdf2zh_files").resolve(),
        Path(tempfile.gettempdir()).resolve(),
    }

    assert set(allowed_paths) == expected_paths


def test_on_file_upload_empty_list_returns_all_declared_outputs(monkeypatch):
    gui = _gui(monkeypatch)
    state = _empty_state()

    result = gui.on_file_upload([], state)

    assert len(result) == 3
    assert result[0]["choices"] == []
    assert result[0]["value"] is None
    assert result[0]["visible"] is False
    assert result[1] is state
    assert result[2]["value"] == ""
    assert result[2]["visible"] is False


def test_on_file_upload_none_returns_all_declared_outputs(monkeypatch):
    gui = _gui(monkeypatch)
    state = _empty_state()

    result = gui.on_file_upload(None, state)

    assert len(result) == 3
    assert result[0]["choices"] == []
    assert result[0]["value"] is None
    assert result[0]["visible"] is False
    assert result[1] is state
    assert result[2]["value"] == ""
    assert result[2]["visible"] is False


def test_enhance_compatibility_update_forces_all_babeldoc_compatibility_flags(
    monkeypatch,
):
    gui = _gui(monkeypatch)

    result = gui._enhance_compatibility_option_updates(True)

    assert result == (
        {"value": True, "interactive": False, "__type__": "update"},
        {"value": True, "interactive": False, "__type__": "update"},
        {"value": True, "interactive": False, "__type__": "update"},
    )


def test_enhance_compatibility_update_restores_all_compatibility_controls(
    monkeypatch,
):
    gui = _gui(monkeypatch)

    result = gui._enhance_compatibility_option_updates(False)

    assert result == (
        {"interactive": True, "__type__": "update"},
        {"interactive": True, "__type__": "update"},
        {"interactive": True, "__type__": "update"},
    )


def test_enhance_compatibility_initial_policy_forces_configured_false_controls(
    monkeypatch,
):
    gui = _gui(monkeypatch)

    result = gui._enhance_compatibility_control_policy(
        enhance_value=True,
        configured_value=False,
    )

    assert result == {"value": True, "interactive": False}


def test_enhance_compatibility_reload_updates_restore_configured_false_values(
    monkeypatch,
):
    gui = _gui(monkeypatch)

    result = gui._enhance_compatibility_config_updates(
        enhance_value=False,
        skip_clean_value=False,
        disable_rich_text_translate_value=False,
        dual_translate_first_value=False,
    )

    assert result == (
        {"value": False, "interactive": True, "__type__": "update"},
        {"value": False, "interactive": True, "__type__": "update"},
        {"value": False, "interactive": True, "__type__": "update"},
    )


def test_enhance_compatibility_reload_updates_force_configured_false_values(
    monkeypatch,
):
    gui = _gui(monkeypatch)

    result = gui._enhance_compatibility_config_updates(
        enhance_value=True,
        skip_clean_value=False,
        disable_rich_text_translate_value=False,
        dual_translate_first_value=False,
    )

    assert result == (
        {"value": True, "interactive": False, "__type__": "update"},
        {"value": True, "interactive": False, "__type__": "update"},
        {"value": True, "interactive": False, "__type__": "update"},
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"skip_clean": True},
        {"disable_rich_text_translate": True},
        {"skip_clean": True, "disable_rich_text_translate": True},
    ],
)
def test_standalone_compatibility_options_do_not_force_dual_translate_first(
    tmp_path, monkeypatch, overrides
):
    gui = _gui(monkeypatch)
    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    gui_inputs = _base_gui_inputs() | overrides
    gui_inputs["dual_translate_first"] = False
    gui_inputs["enhance_compatibility"] = False

    translate_settings = gui._build_translate_settings(
        CLIEnvSettingsModel(),
        input_pdf,
        output_dir,
        gui.SaveMode.never,
        gui_inputs,
    )

    assert translate_settings.pdf.dual_translate_first is False


@pytest.mark.parametrize("save_mode_name", ["always", "follow_settings"])
def test_build_translate_settings_preserves_current_gui_language_on_save(
    tmp_path, monkeypatch, save_mode_name
):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )
    startup_settings = gui.config_manager.config_cli_settings.clone()
    startup_settings.gui_settings.ui_lang = "en"
    startup_settings.gui_settings.server_port = 7860
    startup_settings.gui_settings.share = False
    startup_settings.gui_settings.auth_file = None
    startup_settings.gui_settings.welcome_page = "snapshot-welcome.md"
    startup_settings.gui_settings.disable_gui_sensitive_input = True
    startup_settings.gui_settings.disable_config_auto_save = True
    monkeypatch.setattr(gui.config_manager, "config_cli_settings", startup_settings)

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.ui_lang = "zh"
    current_settings.gui_settings.server_port = 9999
    current_settings.gui_settings.share = True
    current_settings.gui_settings.auth_file = str(tmp_path / "runtime-auth.csv")
    current_settings.gui_settings.welcome_page = "runtime-welcome.md"
    current_settings.gui_settings.disable_gui_sensitive_input = False
    current_settings.gui_settings.disable_config_auto_save = False
    monkeypatch.setattr(gui, "settings", current_settings.clone())

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    gui._build_translate_settings(
        current_settings,
        input_pdf,
        output_dir,
        getattr(gui.SaveMode, save_mode_name),
        _base_gui_inputs(),
    )

    assert len(captured_settings) == 1
    assert captured_settings[0].gui_settings.ui_lang == "zh"
    assert captured_settings[0].gui_settings.server_port == 7860
    assert captured_settings[0].gui_settings.share is False
    assert captured_settings[0].gui_settings.auth_file is None
    assert captured_settings[0].gui_settings.welcome_page == "snapshot-welcome.md"
    assert captured_settings[0].gui_settings.disable_gui_sensitive_input is True
    assert captured_settings[0].gui_settings.disable_config_auto_save is True
    assert gui.settings.gui_settings.ui_lang == "zh"
    assert gui.settings.gui_settings.server_port == 9999
    assert gui.settings.gui_settings.share is True
    assert gui.settings.gui_settings.auth_file == str(tmp_path / "runtime-auth.csv")
    assert gui.settings.gui_settings.welcome_page == "runtime-welcome.md"
    assert gui.settings.gui_settings.disable_gui_sensitive_input is False
    assert gui.settings.gui_settings.disable_config_auto_save is False


def test_build_translate_settings_follow_settings_respects_auto_save_disabled(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.disable_config_auto_save = True

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    gui._build_translate_settings(
        current_settings,
        input_pdf,
        output_dir,
        gui.SaveMode.follow_settings,
        _base_gui_inputs(),
    )

    assert captured_settings == []


def test_build_translate_settings_never_save_mode_skips_config_write(
    tmp_path, monkeypatch
):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )

    current_settings = CLIEnvSettingsModel()

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    gui._build_translate_settings(
        current_settings,
        input_pdf,
        output_dir,
        gui.SaveMode.never,
        _base_gui_inputs(),
    )

    assert captured_settings == []


@pytest.mark.parametrize("save_mode_name", ["never", "follow_settings"])
def test_build_translate_settings_no_config_snapshot_skips_no_save_without_crash(
    tmp_path, monkeypatch, save_mode_name
):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )
    monkeypatch.setattr(gui.config_manager, "config_cli_settings", None)

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.disable_config_auto_save = True

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    gui._build_translate_settings(
        current_settings,
        input_pdf,
        output_dir,
        getattr(gui.SaveMode, save_mode_name),
        _base_gui_inputs(),
    )

    assert captured_settings == []


@pytest.mark.parametrize("save_mode_name", ["always", "follow_settings"])
def test_build_translate_settings_no_config_snapshot_saves_safe_gui_defaults(
    tmp_path, monkeypatch, save_mode_name
):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )
    monkeypatch.setattr(gui.config_manager, "config_cli_settings", None)

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.ui_lang = "zh"
    current_settings.gui_settings.server_port = 9999
    current_settings.gui_settings.share = True
    current_settings.gui_settings.auth_file = str(tmp_path / "runtime-auth.csv")
    current_settings.gui_settings.welcome_page = "runtime-welcome.md"
    current_settings.gui_settings.disable_gui_sensitive_input = True
    current_settings.gui_settings.disable_config_auto_save = False
    monkeypatch.setattr(gui, "settings", current_settings.clone())

    input_pdf = tmp_path / "input.pdf"
    input_pdf.write_bytes(b"%PDF-1.4\n")
    output_dir = tmp_path / "out"
    output_dir.mkdir()

    gui._build_translate_settings(
        current_settings,
        input_pdf,
        output_dir,
        getattr(gui.SaveMode, save_mode_name),
        _base_gui_inputs(),
    )

    default_gui_settings = CLIEnvSettingsModel().gui_settings
    assert len(captured_settings) == 1
    assert captured_settings[0].gui_settings.ui_lang == "zh"
    assert captured_settings[0].gui_settings.server_port == default_gui_settings.server_port
    assert captured_settings[0].gui_settings.share == default_gui_settings.share
    assert captured_settings[0].gui_settings.auth_file == default_gui_settings.auth_file
    assert captured_settings[0].gui_settings.welcome_page == default_gui_settings.welcome_page
    assert (
        captured_settings[0].gui_settings.disable_gui_sensitive_input
        == default_gui_settings.disable_gui_sensitive_input
    )
    assert (
        captured_settings[0].gui_settings.disable_config_auto_save
        == default_gui_settings.disable_config_auto_save
    )
    assert gui.settings.gui_settings.ui_lang == "zh"
    assert gui.settings.gui_settings.server_port == 9999
    assert gui.settings.gui_settings.share is True
    assert gui.settings.gui_settings.auth_file == str(tmp_path / "runtime-auth.csv")
    assert gui.settings.gui_settings.welcome_page == "runtime-welcome.md"
    assert gui.settings.gui_settings.disable_gui_sensitive_input is True
    assert gui.settings.gui_settings.disable_config_auto_save is False


def test_gui_language_save_preserves_snapshot_gui_security_fields(monkeypatch, tmp_path):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )
    def ignore_language_update(_lang):
        return None

    monkeypatch.setattr(gui, "update_current_languages", ignore_language_update)

    startup_settings = gui.config_manager.config_cli_settings.clone()
    startup_settings.gui_settings.ui_lang = "en"
    startup_settings.gui_settings.server_port = 7860
    startup_settings.gui_settings.share = False
    startup_settings.gui_settings.auth_file = None
    startup_settings.gui_settings.welcome_page = "snapshot-welcome.md"
    startup_settings.gui_settings.disable_gui_sensitive_input = True
    startup_settings.gui_settings.disable_config_auto_save = True
    monkeypatch.setattr(gui.config_manager, "config_cli_settings", startup_settings)

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.ui_lang = "en"
    current_settings.gui_settings.server_port = 9999
    current_settings.gui_settings.share = True
    current_settings.gui_settings.auth_file = str(tmp_path / "runtime-auth.csv")
    current_settings.gui_settings.welcome_page = "runtime-welcome.md"
    current_settings.gui_settings.disable_gui_sensitive_input = False
    current_settings.gui_settings.disable_config_auto_save = False
    monkeypatch.setattr(gui, "settings", current_settings)

    gui._save_gui_language_settings("zh")

    assert len(captured_settings) == 1
    assert captured_settings[0].gui_settings.ui_lang == "zh"
    assert captured_settings[0].gui_settings.server_port == 7860
    assert captured_settings[0].gui_settings.share is False
    assert captured_settings[0].gui_settings.auth_file is None
    assert captured_settings[0].gui_settings.welcome_page == "snapshot-welcome.md"
    assert captured_settings[0].gui_settings.disable_gui_sensitive_input is True
    assert captured_settings[0].gui_settings.disable_config_auto_save is True
    assert gui.settings.gui_settings.ui_lang == "zh"
    assert gui.settings.gui_settings.server_port == 9999
    assert gui.settings.gui_settings.share is True
    assert gui.settings.gui_settings.auth_file == str(tmp_path / "runtime-auth.csv")
    assert gui.settings.gui_settings.welcome_page == "runtime-welcome.md"
    assert gui.settings.gui_settings.disable_gui_sensitive_input is False
    assert gui.settings.gui_settings.disable_config_auto_save is False


def test_gui_language_save_no_config_snapshot_does_not_crash(monkeypatch):
    gui = _gui(monkeypatch)
    captured_settings = []

    def capture_user_config(settings):
        captured_settings.append(settings.clone())

    monkeypatch.setattr(
        gui.config_manager,
        "write_user_default_config_file",
        capture_user_config,
    )
    def ignore_language_update(_lang):
        return None

    monkeypatch.setattr(gui, "update_current_languages", ignore_language_update)
    monkeypatch.setattr(gui.config_manager, "config_cli_settings", None)

    current_settings = CLIEnvSettingsModel()
    current_settings.gui_settings.server_port = 9999
    current_settings.gui_settings.share = True
    monkeypatch.setattr(gui, "settings", current_settings)

    gui._save_gui_language_settings("zh")

    assert len(captured_settings) == 1
    assert captured_settings[0].gui_settings.ui_lang == "zh"
    assert captured_settings[0].gui_settings.server_port != 9999
    assert captured_settings[0].gui_settings.share is False
    assert gui.settings.gui_settings.ui_lang == "zh"
    assert gui.settings.gui_settings.server_port == 9999
    assert gui.settings.gui_settings.share is True
