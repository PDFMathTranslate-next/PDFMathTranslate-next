import asyncio
import cgi
import csv
import io
import logging
import shutil
import tempfile
import typing
import uuid
import zipfile
from enum import Enum
from pathlib import Path
from string import Template

import chardet
import gradio as gr
import requests
import yaml
from babeldoc import __version__ as babeldoc_version
from gradio_i18n import Translate
from gradio_pdf import PDF

from pdf2zh_next import __version__
from pdf2zh_next.config import ConfigManager
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.config.translate_engine_model import GUI_PASSWORD_FIELDS
from pdf2zh_next.config.translate_engine_model import GUI_SENSITIVE_FIELDS
from pdf2zh_next.config.translate_engine_model import TERM_EXTRACTION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import (
    TERM_EXTRACTION_ENGINE_METADATA_MAP,
)
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA
from pdf2zh_next.config.translate_engine_model import TRANSLATION_ENGINE_METADATA_MAP
from pdf2zh_next.const import DEFAULT_CONFIG_DIR
from pdf2zh_next.const import DEFAULT_CONFIG_FILE
from pdf2zh_next.high_level import TranslationError
from pdf2zh_next.high_level import do_translate_async_stream
from pdf2zh_next.i18n import LANGUAGES
from pdf2zh_next.i18n import gettext as _
from pdf2zh_next.i18n import update_current_languages

logger = logging.getLogger(__name__)


class SaveMode(Enum):
    """Enum for configuration save behavior."""

    follow_settings = "follow_settings"  # Follow disable_config_auto_save setting
    never = "never"  # Never save
    always = "always"  # Always save regardless of disable_config_auto_save


def get_translation_dic(file_path: Path):
    with file_path.open(encoding="utf-8", newline="\n") as f:
        return yaml.safe_load(f)


__gui_service_arg_names = []
__gui_term_service_arg_names = []
LLM_support_index_map = {}


def _field_gui_extra(field) -> dict:
    return (field.json_schema_extra or {}).get("gui", {})


def _type_hint_allows_none(type_hint: typing.Any) -> bool:
    return type(None) in typing.get_args(type_hint)


def _gui_dependency_field_name(field_name: str, dependency_field_name: str) -> str:
    if field_name.startswith("term_") and not dependency_field_name.startswith("term_"):
        return f"term_{dependency_field_name}"
    return dependency_field_name


def _gui_field_visible(
    field_name: str,
    field,
    base_visible: bool,
    field_values: dict[str, typing.Any],
) -> bool:
    gui_extra = _field_gui_extra(field)
    visible_when = gui_extra.get("visible_when")
    if not visible_when:
        return base_visible
    dependency_field_name = _gui_dependency_field_name(
        field_name, visible_when["field"]
    )
    return base_visible and field_values.get(dependency_field_name) == visible_when["equals"]


def _gui_field_value(field, value):
    gui_extra = _field_gui_extra(field)
    if value:
        return value
    return gui_extra.get("default_on_show", value)


def _gui_field_update(field, visible: bool, current_value=None):
    gui_extra = _field_gui_extra(field)
    update_kwargs = {"visible": visible}
    if "choices" in gui_extra:
        update_kwargs["choices"] = gui_extra["choices"]
    if "default_on_show" in gui_extra or gui_extra.get("preserve_current_value"):
        update_kwargs["value"] = _gui_field_value(field, current_value)
    return gr.update(**update_kwargs)


def _enhance_compatibility_option_updates(enhance_value: bool):
    if enhance_value:
        return (
            gr.update(**_enhance_compatibility_control_policy(True, False)),
            gr.update(**_enhance_compatibility_control_policy(True, False)),
            gr.update(**_enhance_compatibility_control_policy(True, False)),
        )
    return (
        gr.update(interactive=True),
        gr.update(interactive=True),
        gr.update(interactive=True),
    )


def _enhance_compatibility_control_policy(
    enhance_value: bool,
    configured_value: bool,
) -> dict[str, bool]:
    return {
        "value": True if enhance_value else configured_value,
        "interactive": not enhance_value,
    }


def _enhance_compatibility_config_updates(
    enhance_value: bool,
    skip_clean_value: bool,
    disable_rich_text_translate_value: bool,
    dual_translate_first_value: bool,
):
    return (
        gr.update(
            **_enhance_compatibility_control_policy(
                enhance_value,
                skip_clean_value,
            )
        ),
        gr.update(
            **_enhance_compatibility_control_policy(
                enhance_value,
                disable_rich_text_translate_value,
            )
        ),
        gr.update(
            **_enhance_compatibility_control_policy(
                enhance_value,
                dual_translate_first_value,
            )
        ),
    )


def _persisted_gui_settings_with_ui_lang(ui_lang: str):
    config_cli_settings = getattr(config_manager, "config_cli_settings", None)
    if config_cli_settings is not None:
        gui_settings = config_cli_settings.gui_settings.model_copy(deep=True)
    else:
        gui_settings = CLIEnvSettingsModel().gui_settings.model_copy(deep=True)
    gui_settings.ui_lang = ui_lang
    return gui_settings


def _save_gui_language_settings(lang: str) -> None:
    settings.gui_settings.ui_lang = lang
    update_current_languages(lang)
    config_save_settings = settings.clone()
    config_save_settings.gui_settings = _persisted_gui_settings_with_ui_lang(lang)
    config_manager.write_user_default_config_file(settings=config_save_settings)


# The following variables associate strings with specific languages
lang_map = {
    "English": "en",
    "Simplified Chinese": "zh-CN",
    "Traditional Chinese - Hong Kong": "zh-HK",
    "Traditional Chinese - Taiwan": "zh-TW",
    "Japanese": "ja",
    "Korean": "ko",
    "Polish": "pl",
    "Russian": "ru",
    "Spanish": "es",
    "Portuguese": "pt",
    "Brazilian Portuguese": "pt-BR",
    "French": "fr",
    "Malay": "ms",
    "Indonesian": "id",
    "Turkmen": "tk",
    "Filipino (Tagalog)": "tl",
    "Vietnamese": "vi",
    "Kazakh (Latin)": "kk",
    "German": "de",
    "Dutch": "nl",
    "Irish": "ga",
    "Italian": "it",
    "Greek": "el",
    "Swedish": "sv",
    "Danish": "da",
    "Norwegian": "no",
    "Icelandic": "is",
    "Finnish": "fi",
    "Ukrainian": "uk",
    "Czech": "cs",
    "Romanian": "ro",  # Covers Romanian, Moldovan, Moldovan (Cyrillic)
    "Hungarian": "hu",
    "Slovak": "sk",
    "Croatian": "hr",  # Also listed later, keep first
    "Estonian": "et",
    "Latvian": "lv",
    "Lithuanian": "lt",
    "Belarusian": "be",
    "Macedonian": "mk",
    "Albanian": "sq",
    "Serbian (Cyrillic)": "sr",  # Covers Serbian (Latin) too
    "Slovenian": "sl",
    "Catalan": "ca",
    "Bulgarian": "bg",
    "Maltese": "mt",
    "Swahili": "sw",
    "Amharic": "am",
    "Oromo": "om",
    "Tigrinya": "ti",
    "Haitian Creole": "ht",
    "Latin": "la",
    "Lao": "lo",
    "Malayalam": "ml",
    "Gujarati": "gu",
    "Thai": "th",
    "Burmese": "my",
    "Tamil": "ta",
    "Telugu": "te",
    "Oriya": "or",  # Also listed later, keep first
    "Armenian": "hy",
    "Mongolian (Cyrillic)": "mn",
    "Georgian": "ka",
    "Khmer": "km",
    "Bosnian": "bs",
    "Luxembourgish": "lb",
    "Romansh": "rm",
    "Turkish": "tr",
    "Sinhala": "si",
    "Uzbek": "uz",
    "Kyrgyz": "ky",  # Listed as Kirghiz later, keep this one
    "Tajik": "tg",
    "Abkhazian": "ab",
    "Afar": "aa",
    "Afrikaans": "af",
    "Akan": "ak",
    "Aragonese": "an",
    "Avaric": "av",
    "Ewe": "ee",
    "Aymara": "ay",
    "Ojibwa": "oj",
    "Occitan": "oc",
    "Ossetian": "os",
    "Pali": "pi",
    "Bashkir": "ba",
    "Basque": "eu",
    "Breton": "br",
    "Chamorro": "ch",
    "Chechen": "ce",
    "Chuvash": "cv",
    "Tswana": "tn",
    "Ndebele, South": "nr",
    "Ndonga": "ng",
    "Faroese": "fo",
    "Fijian": "fj",
    "Frisian, Western": "fy",
    "Ganda": "lg",
    "Kongo": "kg",
    "Kalaallisut": "kl",
    "Church Slavic": "cu",
    "Guarani": "gn",
    "Interlingua": "ia",
    "Herero": "hz",
    "Kikuyu": "ki",
    "Rundi": "rn",
    "Kinyarwanda": "rw",
    "Galician": "gl",
    "Kanuri": "kr",
    "Cornish": "kw",
    "Komi": "kv",
    "Xhosa": "xh",
    "Corsican": "co",
    "Cree": "cr",
    "Quechua": "qu",
    "Kurdish (Latin)": "ku",
    "Kuanyama": "kj",
    "Limburgan": "li",
    "Lingala": "ln",
    "Manx": "gv",
    "Malagasy": "mg",
    "Marshallese": "mh",
    "Maori": "mi",
    "Navajo": "nv",
    "Nauru": "na",
    "Nyanja": "ny",
    "Norwegian Nynorsk": "nn",
    "Sardinian": "sc",
    "Northern Sami": "se",
    "Samoan": "sm",
    "Sango": "sg",
    "Shona": "sn",
    "Esperanto": "eo",
    "Scottish Gaelic": "gd",
    "Somali": "so",
    "Southern Sotho": "st",
    "Tatar": "tt",
    "Tahitian": "ty",
    "Tongan": "to",
    "Twi": "tw",
    "Walloon": "wa",
    "Welsh": "cy",
    "Venda": "ve",
    "Volapük": "vo",
    "Interlingue": "ie",
    "Hiri Motu": "ho",
    "Igbo": "ig",
    "Ido": "io",
    "Inuktitut": "iu",
    "Inupiaq": "ik",
    "Sichuan Yi": "ii",
    "Yoruba": "yo",
    "Zhuang": "za",
    "Tsonga": "ts",
    "Zulu": "zu",
}

rev_lang_map = {v: k for k, v in lang_map.items()}

# The following variable associate strings with page ranges
# Page map with fixed internal keys
page_map = {
    "All": None,
    "First": [0],
    "First 5 pages": list(range(0, 5)),
    "Range": None,  # User-defined range
}


def get_page_choices():
    """Get page range choices with translated labels"""
    return [
        (_("All"), "All"),
        (_("First"), "First"),
        (_("First 5 pages"), "First 5 pages"),
        (_("Range"), "Range"),
    ]


# Load configuration
config_manager = ConfigManager()
try:
    # Load configuration from files and environment variables
    settings = config_manager.initialize_cli_config()
    # Check if sensitive inputs should be disabled in GUI
    disable_sensitive_input = settings.gui_settings.disable_gui_sensitive_input
except Exception as e:
    logger.warning(f"Could not load initial config: {e}")
    settings = CLIEnvSettingsModel()
    disable_sensitive_input = False

# Define default values
default_lang_from = rev_lang_map.get(settings.translation.lang_in, "English")

default_lang_to = settings.translation.lang_out
for display_name, code in lang_map.items():
    if code == default_lang_to:
        default_lang_to = display_name
        break
else:
    default_lang_to = "Simplified Chinese"  # Fallback

# Available translation services
# This will eventually be dynamically determined based on available translators
available_services = [x.translate_engine_type for x in TRANSLATION_ENGINE_METADATA]

if settings.gui_settings.enabled_services:
    enabled_services = {
        x.lower() for x in settings.gui_settings.enabled_services.split(",")
    }
    available_services = [
        x for x in available_services if x.lower() in enabled_services
    ]

assert available_services, "No translation service is enabled"


disable_gui_sensitive_input = settings.gui_settings.disable_gui_sensitive_input


def _get_unique_dest_path(output_dir: Path, original_name: str) -> Path:
    """
    Get a unique destination path in the given output directory.

    This will try the original name first, then append an incrementing
    suffix like "_2", "_3", etc. until an unused name is found.
    """
    output_dir = Path(output_dir)
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix

    # First try the original name
    candidate = output_dir / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    # Increment index until we find an unused name
    index = 2
    while True:
        candidate = output_dir / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def download_with_limit(url: str, save_path: str, size_limit: int = None) -> str:
    """
    This function downloads a file from a URL and saves it to a specified path.

    Inputs:
        - url: The URL to download the file from
        - save_path: The path to save the file to
        - size_limit: The maximum size of the file to download

    Returns:
        - The path of the downloaded file
    """
    chunk_size = 1024
    total_size = 0
    with requests.get(url, stream=True, timeout=10) as response:
        response.raise_for_status()
        content = response.headers.get("Content-Disposition")
        try:  # filename from header
            un_used, params = cgi.parse_header(content)
            filename = params["filename"]
        except Exception:  # filename from url
            filename = Path(url).name
        filename = Path(filename).stem + ".pdf"
        save_path = Path(save_path).resolve()

        # Use a unique destination path to avoid overwriting existing files
        file_path = _get_unique_dest_path(save_path, filename)
        if not file_path.resolve().is_relative_to(save_path):
            raise gr.Error("Invalid filename")
        with file_path.open("wb") as file:
            for chunk in response.iter_content(chunk_size=chunk_size):
                total_size += len(chunk)
                if size_limit and total_size > size_limit:
                    raise gr.Error("Exceeds file size limit")
                file.write(chunk)
    return file_path


def _prepare_input_file(
    file_type: str,
    file_input: str | list,
    link_input: str,
    output_dir: Path,
    state: dict | None = None,
) -> list[Path]:
    """
    This function prepares the input file(s) for translation.

    Inputs:
        - file_type: The type of file to translate (File or Link)
        - file_input: The path to the file to translate or list of paths
        - link_input: The link to the file to translate
        - output_dir: The directory to save the file to

    Returns:
        - A list of paths of the input files
    """
    prepared_files = []

    if file_type == "File":
        # Handle normal case: file_input is provided by the File component
        if file_input:
            # Handle single file or multiple files
            if isinstance(file_input, str | Path):
                inputs = [file_input]
            else:
                inputs = file_input

            for f_in in inputs:
                # Gradio provides file paths as NamedString or str in temp
                src_path = Path(f_in.name if hasattr(f_in, "name") else f_in)
                # Use original filename without UUID prefix as requested, but avoid collisions
                dest_name = src_path.name
                dest_path = _get_unique_dest_path(output_dir, dest_name)
                shutil.copy(src_path, dest_path)
                prepared_files.append(dest_path)
        # Fallback case: rely on state when File component value is empty
        elif state and state.get("uploaded_files") and state.get("display_map"):
            for original_name in state.get("uploaded_files", []):
                src_str = state["display_map"].get(original_name)
                if not src_str:
                    continue
                src_path = Path(src_str)
                if not src_path.exists():
                    # Skip missing temp files; user may need to re-upload
                    continue
                dest_name = src_path.name
                dest_path = _get_unique_dest_path(output_dir, dest_name)
                shutil.copy(src_path, dest_path)
                prepared_files.append(dest_path)

        if not prepared_files:
            # Still nothing prepared: propagate original error
            raise gr.Error("No file input provided")

    else:
        if not link_input:
            raise gr.Error("No link input provided")
        try:
            file_path = download_with_limit(link_input, output_dir)
            prepared_files.append(Path(file_path))
        except Exception as e:
            raise gr.Error(f"Error downloading file: {e}") from e

    return prepared_files


def _validate_rate_limit_inputs(
    true_rate_limit_mode: str, **inputs
) -> tuple[bool, str]:
    """
    Validate rate limit inputs

    Returns:
        tuple: (is_valid, error_message)
    """
    if true_rate_limit_mode == "RPM":
        rpm = inputs.get("rpm_input", 0)
        if not isinstance(rpm, int | float) or rpm <= 0:
            return False, "RPM must be a positive integer"

        if isinstance(rpm, float):
            if not rpm.is_integer():
                return False, "RPM must be a positive integer"

    elif true_rate_limit_mode == "Concurrent Threads":
        threads = inputs.get("concurrent_threads", 0)
        if not isinstance(threads, int | float) or threads <= 0:
            return False, "Concurrent threads must be a positive integer"

        if isinstance(threads, float):
            if not threads.is_integer():
                return False, "Concurrent threads must be a positive integer"

    elif true_rate_limit_mode == "Custom":
        qps = inputs.get("custom_qps", 0)
        pool_workers = inputs.get("custom_pool_workers")

        if not isinstance(qps, int | float) or qps <= 0:
            return False, "QPS must be a positive integer"

        if isinstance(qps, float):
            if not qps.is_integer():
                return False, "QPS must be a positive integer"

        if pool_workers is not None and (
            not isinstance(pool_workers, int | float) or pool_workers < 0
        ):
            return False, "Pool workers must be a non-negative integer"

        if isinstance(pool_workers, float):
            if not pool_workers.is_integer():
                return False, "Pool workers must be a non-negative integer"

    return True, ""


def _calculate_rate_limit_params(
    rate_limit_mode: str, ui_inputs: dict, default_qps: int = 4
) -> tuple[int, int | None]:
    """
    Calculate QPS and pool workers based on rate limit mode

    Args:
        rate_limit_mode: Rate limit mode ("RPM", "Concurrent Threads", "Custom")
        ui_inputs: User input parameters dictionary
        default_qps: Default QPS value

    Returns:
        tuple: (qps, pool_max_workers)

    Raises:
        ValueError: When input parameter validation fails
    """
    # Validate input parameters
    is_valid, error_msg = _validate_rate_limit_inputs(
        true_rate_limit_mode=rate_limit_mode, **ui_inputs
    )
    if not is_valid:
        logger.warning(f"Rate limit validation failed: {error_msg}")
        raise ValueError(error_msg)

    if rate_limit_mode == "RPM":
        rpm: int = ui_inputs.get("rpm_input", 240)
        qps = max(1, rpm // 60)
        pool_workers = min(1000, qps * 10)

    elif rate_limit_mode == "Concurrent Threads":
        # NOTE: ui_inputs keys are normalized by build_ui_inputs():
        # - concurrent_threads (mapped from concurrent_threads_input in UI)
        threads: int = ui_inputs.get("concurrent_threads", 40)
        # Ensure at least 1 worker, at most 1000 workers, using a safer calculation method
        pool_workers = min(1000, max(1, min(int(threads * 0.9), max(1, threads - 20))))
        qps = max(1, pool_workers)

    else:  # Custom
        # NOTE: ui_inputs keys are normalized by build_ui_inputs():
        # - custom_qps (mapped from custom_qps_input in UI)
        # - custom_pool_workers (mapped from custom_pool_max_workers_input in UI)
        qps = ui_inputs.get("custom_qps", default_qps)
        pool_workers = ui_inputs.get("custom_pool_workers")
        qps = int(qps)
        pool_workers = int(pool_workers) if pool_workers and pool_workers > 0 else None

    logger.info(f"QPS: {qps}, Pool Workers: {pool_workers}")

    return qps, pool_workers if pool_workers and pool_workers > 0 else None


def _build_translate_settings(
    base_settings: CLIEnvSettingsModel,
    file_path: Path,
    output_dir: Path,
    save_mode: SaveMode,
    ui_inputs: dict,
) -> SettingsModel:
    """
    This function builds translation settings from UI inputs.

    Inputs:
        - base_settings: The base settings model to build upon
        - file_path: The path to the input file
        - output_dir: The output directory
        - save_mode: SaveMode enum indicating when to save config
        - ui_inputs: A dictionary of UI inputs

    Returns:
        - A configured SettingsModel instance
    """
    # Clone base settings to avoid modifying the original
    translate_settings = base_settings.clone()
    original_output = translate_settings.translation.output
    original_pages = translate_settings.pdf.pages
    original_gui_settings = translate_settings.gui_settings.model_copy(deep=True)

    # Extract UI values
    service = ui_inputs.get("service")
    lang_from = ui_inputs.get("lang_from")
    lang_to = ui_inputs.get("lang_to")
    page_range = ui_inputs.get("page_range")
    page_input = ui_inputs.get("page_input")
    prompt = ui_inputs.get("prompt")
    ignore_cache = ui_inputs.get("ignore_cache")

    # PDF Output Options
    no_mono = ui_inputs.get("no_mono")
    no_dual = ui_inputs.get("no_dual")
    dual_translate_first = ui_inputs.get("dual_translate_first")
    use_alternating_pages_dual = ui_inputs.get("use_alternating_pages_dual")
    watermark_output_mode = ui_inputs.get("watermark_output_mode")

    # Rate Limit Options
    rate_limit_mode = ui_inputs.get("rate_limit_mode")

    # Advanced Translation Options
    min_text_length = ui_inputs.get("min_text_length")
    rpc_doclayout = ui_inputs.get("rpc_doclayout")
    enable_auto_term_extraction = ui_inputs.get("enable_auto_term_extraction")
    primary_font_family = ui_inputs.get("primary_font_family")

    # Advanced PDF Options
    skip_clean = ui_inputs.get("skip_clean")
    disable_rich_text_translate = ui_inputs.get("disable_rich_text_translate")
    enhance_compatibility = ui_inputs.get("enhance_compatibility")
    split_short_lines = ui_inputs.get("split_short_lines")
    short_line_split_factor = ui_inputs.get("short_line_split_factor")
    translate_table_text = ui_inputs.get("translate_table_text")
    skip_scanned_detection = ui_inputs.get("skip_scanned_detection")
    ocr_workaround = ui_inputs.get("ocr_workaround")
    max_pages_per_part = ui_inputs.get("max_pages_per_part")
    formular_font_pattern = ui_inputs.get("formular_font_pattern")
    formular_char_pattern = ui_inputs.get("formular_char_pattern")
    auto_enable_ocr_workaround = ui_inputs.get("auto_enable_ocr_workaround")
    only_include_translated_page = ui_inputs.get("only_include_translated_page")

    # BabelDOC v0.5.1 new options
    merge_alternating_line_numbers = ui_inputs.get("merge_alternating_line_numbers")
    remove_non_formula_lines = ui_inputs.get("remove_non_formula_lines")
    non_formula_line_iou_threshold = ui_inputs.get("non_formula_line_iou_threshold")
    figure_table_protection_threshold = ui_inputs.get(
        "figure_table_protection_threshold"
    )
    skip_formula_offset_calculation = ui_inputs.get("skip_formula_offset_calculation")

    # Term extraction options
    term_service = ui_inputs.get("term_service")
    term_rate_limit_mode = ui_inputs.get("term_rate_limit_mode")
    term_rpm_input = ui_inputs.get("term_rpm_input")
    term_concurrent_threads = ui_inputs.get("term_concurrent_threads")
    term_custom_qps = ui_inputs.get("term_custom_qps")
    term_custom_pool_workers = ui_inputs.get("term_custom_pool_workers")

    # New input for custom_system_prompt
    custom_system_prompt_input = ui_inputs.get("custom_system_prompt_input")
    glossaries = ui_inputs.get("glossaries")
    save_auto_extracted_glossary = ui_inputs.get("save_auto_extracted_glossary")

    # Map UI language selections to language codes
    source_lang = lang_map.get(lang_from, "auto")
    target_lang = lang_map.get(lang_to, "zh")

    # Set up page selection
    if page_range == "Range" and page_input:
        pages = page_input  # The backend parser handles the format
    else:
        # Use predefined ranges from page_map
        selected_pages = page_map[page_range]
        if selected_pages is None:
            pages = None  # All pages
        else:
            # Convert page indices to comma-separated string
            pages = ",".join(
                str(p + 1) for p in selected_pages
            )  # +1 because UI is 1-indexed

    # Update settings with UI values
    translate_settings.basic.input_files = {str(file_path)}
    translate_settings.report_interval = 0.2
    translate_settings.translation.lang_in = source_lang
    translate_settings.translation.lang_out = target_lang
    translate_settings.translation.output = str(output_dir)
    translate_settings.translation.ignore_cache = ignore_cache

    # Update Translation Settings
    if min_text_length is not None:
        translate_settings.translation.min_text_length = int(min_text_length)
    if rpc_doclayout:
        translate_settings.translation.rpc_doclayout = rpc_doclayout

    # UI uses positive switch, config uses negative flag, so we invert here
    if enable_auto_term_extraction is not None:
        translate_settings.translation.no_auto_extract_glossary = (
            not enable_auto_term_extraction
        )
    if primary_font_family:
        if primary_font_family == "Auto":
            translate_settings.translation.primary_font_family = None
        else:
            translate_settings.translation.primary_font_family = primary_font_family

    # Calculate and update rate limit settings
    if service != "SiliconFlowFree":
        qps, pool_workers = _calculate_rate_limit_params(
            rate_limit_mode, ui_inputs, translate_settings.translation.qps or 4
        )

        # Update translation settings
        translate_settings.translation.qps = int(qps)
        translate_settings.translation.pool_max_workers = (
            int(pool_workers) if pool_workers is not None else None
        )

    # Calculate and update term extraction rate limit settings
    if term_rate_limit_mode:
        term_rate_inputs = {
            "rpm_input": term_rpm_input,
            "concurrent_threads": term_concurrent_threads,
            "custom_qps": term_custom_qps,
            "custom_pool_workers": term_custom_pool_workers,
        }
        term_qps, term_pool_workers = _calculate_rate_limit_params(
            term_rate_limit_mode,
            term_rate_inputs,
            translate_settings.translation.term_qps
            or translate_settings.translation.qps
            or 4,
        )
        translate_settings.translation.term_qps = int(term_qps)
        translate_settings.translation.term_pool_max_workers = (
            int(term_pool_workers) if term_pool_workers is not None else None
        )

    # Reset all term extraction engine flags
    for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, False)

    # Configure term extraction engine settings from UI when not following main engine
    if (
        term_service
        and term_service != "Follow main translation engine"
        and not translate_settings.translation.no_auto_extract_glossary
        and term_service in TERM_EXTRACTION_ENGINE_METADATA_MAP
    ):
        term_metadata = TERM_EXTRACTION_ENGINE_METADATA_MAP[term_service]

        # Enable selected term extraction engine flag
        term_flag_name = f"term_{term_metadata.cli_flag_name}"
        if hasattr(translate_settings, term_flag_name):
            setattr(translate_settings, term_flag_name, True)

        # Update term extraction engine detail settings
        if term_metadata.cli_detail_field_name:
            term_detail_field_name = f"term_{term_metadata.cli_detail_field_name}"
            term_detail_settings = getattr(translate_settings, term_detail_field_name)
            term_model_type = term_metadata.term_setting_model_type

            for field_name, field in term_model_type.model_fields.items():
                if field_name in ("translate_engine_type", "support_llm"):
                    continue

                if field_name not in ui_inputs:
                    continue
                value = ui_inputs[field_name]

                type_hint = field.annotation
                type_args = typing.get_args(type_hint)

                if value is None:
                    if _type_hint_allows_none(type_hint):
                        setattr(term_detail_settings, field_name, None)
                    continue

                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui term extraction engine settings"
                    )

                setattr(term_detail_settings, field_name, value)

    # Update PDF Settings
    translate_settings.pdf.pages = pages
    translate_settings.pdf.no_mono = no_mono
    translate_settings.pdf.no_dual = no_dual
    translate_settings.pdf.dual_translate_first = dual_translate_first
    translate_settings.pdf.use_alternating_pages_dual = use_alternating_pages_dual

    # Map watermark mode from UI to enum
    translate_settings.pdf.watermark_output_mode = (
        watermark_output_mode.lower().replace(" ", "_")
    )

    # Update Advanced PDF Settings
    translate_settings.pdf.skip_clean = skip_clean
    translate_settings.pdf.disable_rich_text_translate = disable_rich_text_translate
    translate_settings.pdf.enhance_compatibility = enhance_compatibility
    translate_settings.pdf.split_short_lines = split_short_lines
    translate_settings.pdf.ocr_workaround = ocr_workaround
    if short_line_split_factor is not None:
        translate_settings.pdf.short_line_split_factor = float(short_line_split_factor)

    translate_settings.pdf.translate_table_text = translate_table_text
    translate_settings.pdf.skip_scanned_detection = skip_scanned_detection
    translate_settings.pdf.auto_enable_ocr_workaround = auto_enable_ocr_workaround
    translate_settings.pdf.only_include_translated_page = only_include_translated_page

    if max_pages_per_part is not None and max_pages_per_part > 0:
        translate_settings.pdf.max_pages_per_part = int(max_pages_per_part)

    if formular_font_pattern:
        translate_settings.pdf.formular_font_pattern = formular_font_pattern

    if formular_char_pattern:
        translate_settings.pdf.formular_char_pattern = formular_char_pattern

    # Apply BabelDOC v0.5.1 new options
    translate_settings.pdf.no_merge_alternating_line_numbers = (
        not merge_alternating_line_numbers
    )
    translate_settings.pdf.no_remove_non_formula_lines = not remove_non_formula_lines
    if non_formula_line_iou_threshold is not None:
        translate_settings.pdf.non_formula_line_iou_threshold = float(
            non_formula_line_iou_threshold
        )
    if figure_table_protection_threshold is not None:
        translate_settings.pdf.figure_table_protection_threshold = float(
            figure_table_protection_threshold
        )
    translate_settings.pdf.skip_formula_offset_calculation = (
        skip_formula_offset_calculation
    )

    assert service in TRANSLATION_ENGINE_METADATA_MAP, "UNKNOW TRANSLATION ENGINE!"

    for metadata in TRANSLATION_ENGINE_METADATA:
        cli_flag = metadata.cli_flag_name
        setattr(translate_settings, cli_flag, False)

    metadata = TRANSLATION_ENGINE_METADATA_MAP[service]
    cli_flag = metadata.cli_flag_name
    setattr(translate_settings, cli_flag, True)
    if metadata.cli_detail_field_name:
        detail_setting = getattr(translate_settings, metadata.cli_detail_field_name)
        if metadata.setting_model_type:
            for field_name in metadata.setting_model_type.model_fields:
                if field_name == "translate_engine_type" or field_name == "support_llm":
                    continue
                if disable_gui_sensitive_input:
                    if field_name in GUI_PASSWORD_FIELDS:
                        continue
                    if field_name in GUI_SENSITIVE_FIELDS:
                        continue
                value = ui_inputs.get(field_name)
                type_hint = detail_setting.model_fields[field_name].annotation
                original_type = typing.get_origin(type_hint)
                type_args = typing.get_args(type_hint)
                if type_hint is str or str in type_args:
                    pass
                elif type_hint is int or int in type_args:
                    value = int(value)
                elif type_hint is bool or bool in type_args:
                    value = bool(value)
                else:
                    raise Exception(
                        f"Unsupported type {type_hint} for field {field_name} in gui translation engine settings"
                    )
                setattr(detail_setting, field_name, value)

    # Add custom prompt if provided
    if prompt:
        # This might need adjustment based on how prompt is handled in the new system
        translate_settings.custom_prompt = Template(prompt)

    # Add custom system prompt if provided
    if custom_system_prompt_input:
        translate_settings.translation.custom_system_prompt = custom_system_prompt_input
    else:
        translate_settings.translation.custom_system_prompt = None

    if glossaries:
        translate_settings.translation.glossaries = glossaries
    else:
        translate_settings.translation.glossaries = None

    translate_settings.translation.save_auto_extracted_glossary = (
        save_auto_extracted_glossary
    )

    # Validate settings before proceeding
    try:
        translate_settings.validate_settings()
        temp_settings = translate_settings.to_settings_model()
        translate_settings.translation.output = original_output
        translate_settings.pdf.pages = original_pages
        translate_settings.gui_settings = original_gui_settings
        translate_settings.basic.gui = False
        translate_settings.basic.debug = False
        translate_settings.translation.glossaries = None

        # Determine if config should be saved based on save_mode
        should_save = False
        if save_mode == SaveMode.always:
            should_save = True
        elif save_mode == SaveMode.follow_settings:
            should_save = not temp_settings.gui_settings.disable_config_auto_save
        # SaveMode.never: should_save remains False

        if should_save:
            config_save_settings = translate_settings.clone()
            config_save_settings.gui_settings = _persisted_gui_settings_with_ui_lang(
                translate_settings.gui_settings.ui_lang
            )
            config_manager.write_user_default_config_file(settings=config_save_settings)
            global settings
            settings = translate_settings
        temp_settings.validate_settings()
        return temp_settings
    except ValueError as e:
        raise gr.Error(f"Invalid settings: {e}") from e


def _build_glossary_list(glossary_file, service_name=None):
    if not LLM_support_index_map.get(service_name, False):
        return None
    glossary_list = []
    if glossary_file is None:
        return None
    for file in glossary_file:
        try:
            f = io.StringIO(file.decode(chardet.detect(file)["encoding"]))
            with tempfile.NamedTemporaryFile(
                mode="w", delete=False, suffix=".csv"
            ) as temp_file:
                temp_file.write(f.getvalue())
                f.close()
            glossary_list.append(temp_file.name)
        except (UnicodeDecodeError, csv.Error, KeyError) as e:
            logger.error(f"Error processing glossary file: {e}")
            gr.Error(f"Failed to process glossary file: {e}")
    return ",".join(glossary_list)


def build_ui_inputs(*args):
    """
    Build ui_inputs dictionary from *args.

    Args:
        *args: UI setting controls in the following order:
            service, lang_from, lang_to, page_range, page_input,
            no_mono, no_dual, dual_translate_first, use_alternating_pages_dual, watermark_output_mode,
            rate_limit_mode, rpm_input, concurrent_threads_input, custom_qps_input, custom_pool_max_workers_input,
            prompt, min_text_length, rpc_doclayout, custom_system_prompt_input, glossary_file,
            save_auto_extracted_glossary, enable_auto_term_extraction, primary_font_family, skip_clean,
            disable_rich_text_translate, enhance_compatibility, split_short_lines, short_line_split_factor,
            translate_table_text, skip_scanned_detection, max_pages_per_part, formular_font_pattern,
            formular_char_pattern, ignore_cache, state, ocr_workaround, auto_enable_ocr_workaround,
            only_include_translated_page, merge_alternating_line_numbers, remove_non_formula_lines,
            non_formula_line_iou_threshold, figure_table_protection_threshold, skip_formula_offset_calculation,
            term_service, term_rate_limit_mode, term_rpm_input, term_concurrent_threads_input,
            term_custom_qps_input, term_custom_pool_max_workers_input, *translation_engine_arg_inputs

    Returns:
        dict: ui_inputs dictionary with all UI settings
    """
    # Fixed parameter names in order (excluding translation_engine_arg_inputs)
    fixed_param_names = [
        "service",
        "lang_from",
        "lang_to",
        "page_range",
        "page_input",
        "no_mono",
        "no_dual",
        "dual_translate_first",
        "use_alternating_pages_dual",
        "watermark_output_mode",
        "rate_limit_mode",
        "rpm_input",
        "concurrent_threads",  # mapped from concurrent_threads_input
        "custom_qps",  # mapped from custom_qps_input
        "custom_pool_workers",  # mapped from custom_pool_max_workers_input
        "prompt",
        "min_text_length",
        "rpc_doclayout",
        "custom_system_prompt_input",
        "glossary_file",  # will be converted to glossaries
        "save_auto_extracted_glossary",
        "enable_auto_term_extraction",
        "primary_font_family",
        "skip_clean",
        "disable_rich_text_translate",
        "enhance_compatibility",
        "split_short_lines",
        "short_line_split_factor",
        "translate_table_text",
        "skip_scanned_detection",
        "max_pages_per_part",
        "formular_font_pattern",
        "formular_char_pattern",
        "ignore_cache",
        "state",
        "ocr_workaround",
        "auto_enable_ocr_workaround",
        "only_include_translated_page",
        "merge_alternating_line_numbers",
        "remove_non_formula_lines",
        "non_formula_line_iou_threshold",
        "figure_table_protection_threshold",
        "skip_formula_offset_calculation",
        "term_service",
        "term_rate_limit_mode",
        "term_rpm_input",
        "term_concurrent_threads",
        "term_custom_qps",
        "term_custom_pool_workers",
    ]

    # Split args into fixed params and translation_engine_arg_inputs
    num_fixed = len(fixed_param_names)
    fixed_args = args[:num_fixed]
    translation_engine_arg_inputs = args[num_fixed:]

    # Build ui_inputs dictionary
    ui_inputs = {}
    for param_name, arg_value in zip(fixed_param_names, fixed_args, strict=False):
        ui_inputs[param_name] = arg_value

    # Convert glossary_file to glossaries
    service = ui_inputs["service"]
    glossary_file = ui_inputs["glossary_file"]
    ui_inputs["glossaries"] = _build_glossary_list(glossary_file, service)

    # Add translation engine args (main translator + term translator detail settings)
    main_detail_count = len(__gui_service_arg_names)
    term_detail_count = len(__gui_term_service_arg_names)

    main_detail_inputs = translation_engine_arg_inputs[:main_detail_count]
    term_detail_inputs = translation_engine_arg_inputs[
        main_detail_count : main_detail_count + term_detail_count
    ]

    for arg_name, arg_input in zip(
        __gui_service_arg_names, main_detail_inputs, strict=False
    ):
        ui_inputs[arg_name] = arg_input

    for arg_name, arg_input in zip(
        __gui_term_service_arg_names, term_detail_inputs, strict=False
    ):
        ui_inputs[arg_name] = arg_input

    return ui_inputs


async def _run_translation_task(
    settings: SettingsModel,
    file_path: Path,
    state: dict,
    progress: gr.Progress,
    task_prefix: str = "",
) -> tuple[Path | None, Path | None, Path | None, dict | None]:
    """
    This function runs the translation task and handles progress updates.

    Inputs:
        - settings: The translation settings
        - file_path: The path to the input file
        - state: The state dictionary for tracking the task
        - progress: The Gradio progress bar
        - task_prefix: A prefix string for progress description

    Returns:
        - A tuple of (mono_pdf_path, dual_pdf_path, glossary_path, token_usage)
    """
    mono_path = None
    dual_path = None
    glossary_path = None
    token_usage = None

    try:
        settings.basic.input_files = set()
        async for event in do_translate_async_stream(settings, file_path):
            if event["type"] in (
                "progress_start",
                "progress_update",
                "progress_end",
            ):
                # Update progress bar
                desc = event["stage"]
                progress_value = event["overall_progress"] / 100.0
                part_index = event["part_index"]
                total_parts = event["total_parts"]
                stage_current = event["stage_current"]
                stage_total = event["stage_total"]

                # Combine task prefix with current status
                full_desc = f"{task_prefix}{desc} ({part_index}/{total_parts}, {stage_current}/{stage_total})"
                logger.info(f"Progress: {progress_value}, {full_desc}")
                progress(progress_value, desc=full_desc)
            elif event["type"] == "finish":
                # Extract result paths
                result = event["translate_result"]
                mono_path = result.mono_pdf_path
                dual_path = result.dual_pdf_path
                glossary_path = result.auto_extracted_glossary_path
                token_usage = event.get("token_usage", {})
                # progress(1.0, desc=_("Translation complete!")) # Let caller handle final completion
                break
            elif event["type"] == "error":
                # Handle error event
                error_msg = event.get("error", "Unknown error")
                error_details = event.get("details", "")
                raise gr.Error(f"Translation error: {error_msg}")
    except asyncio.CancelledError:
        # Handle task cancellation - let translate_file handle the UI updates
        logger.info(
            f"Translation for session {state.get('session_id', 'unknown')} was cancelled"
        )
        raise  # Re-raise for the calling function to handle
    except TranslationError as e:
        # Handle structured translation errors
        logger.error(f"Translation error: {e}")
        raise gr.Error(f"Translation error: {e.message}") from e
    except gr.Error as e:
        # Handle Gradio errors
        logger.error(f"Gradio error: {e}")
        raise
    except Exception as e:
        # Handle other exceptions
        logger.error(f"Error in _run_translation_task: {e}", exc_info=True)
        raise gr.Error(f"Translation failed: {e}") from e

    return mono_path, dual_path, glossary_path, token_usage


async def stop_translate_file(state: dict) -> None:
    """
    This function stops the translation process.

    Inputs:
        - state: The state of the translation process

    Returns:- None
    """
    if "current_task" not in state or state["current_task"] is None:
        return

    logger.info(
        f"Stopping translation for session {state.get('session_id', 'unknown')}"
    )
    # Cancel the task
    try:
        state["current_task"].cancel()
        # Wait briefly for cancellation to take effect
        await asyncio.sleep(0.1)
    except Exception as e:
        logger.error(f"Error stopping translation: {e}")
    finally:
        state["current_task"] = None


async def translate_files(
    file_type,
    file_input,
    link_input,
    *ui_args,
    progress=None,
):
    """
    This function translates PDF files and yields updates incrementally.
    """
    # Ensure there is a progress object
    if progress is None:
        progress = gr.Progress()

    # Build ui_inputs from *args
    ui_inputs = build_ui_inputs(*ui_args)
    state = ui_inputs["state"]

    # Initialize session and output directory
    session_id = str(uuid.uuid4())
    state["session_id"] = session_id
    # Reset results for new translation run, but keep display_map for uploaded files
    state["results"] = {}
    state["file_order"] = []

    # Ensure display_map exists (it might have been populated by on_file_upload)
    if "display_map" not in state:
        state["display_map"] = {}
    if "parent_map" not in state:
        state["parent_map"] = {}

    # Prepare output directory
    output_dir = Path("pdf2zh_files") / session_id
    output_dir.mkdir(parents=True, exist_ok=True)

    zip_path = output_dir / "all_translations.zip"
    zip_mono_path = output_dir / "all_mono_translations.zip"
    zip_dual_path = output_dir / "all_dual_translations.zip"
    zip_glossary_path = output_dir / "all_glossaries.zip"

    # Default return values (Hidden/Empty)
    def get_current_ui_update(preview_file_key=None):
        """Helper to generate the massive return tuple based on current state"""
        # Determine choices from display_map
        choices = list(state["display_map"].keys())

        # Determine values based on the preview_file_key (default to first processed file)
        current_res = {"mono": None, "dual": None, "glossary": None}
        preview_path = None

        if preview_file_key:
            preview_path = state["display_map"].get(preview_file_key)
            parent_key = state["parent_map"].get(preview_file_key)
            if parent_key and parent_key in state["results"]:
                current_res = state["results"][parent_key]

        # Build uploaded files markdown view
        uploaded_files = state.get("uploaded_files") or []
        if uploaded_files:
            uploaded_md = "\n".join(
                f"{idx + 1}. {name}" for idx, name in enumerate(uploaded_files)
            )
            uploaded_view_update = gr.update(value=uploaded_md, visible=True)
        else:
            uploaded_view_update = gr.update(value="", visible=False)

        return (
            current_res["mono"],
            preview_path,
            current_res["dual"],
            current_res["glossary"],
            gr.update(visible=bool(current_res["mono"])),
            gr.update(visible=bool(current_res["dual"])),
            gr.update(visible=bool(current_res["glossary"])),
            gr.update(visible=True, value="## Processing..."),  # Title
            gr.update(
                choices=choices, value=preview_file_key, visible=True
            ),  # Result Selector
            gr.update(visible=True),  # Result Selector Container
            gr.update(visible=False),  # Zip
            None,
            gr.update(visible=False),
            None,
            gr.update(visible=False),
            None,
            gr.update(visible=False),
            None,
            uploaded_view_update,
        )

    try:
        # Step 1: Prepare input files
        file_paths = _prepare_input_file(
            file_type, file_input, link_input, output_dir, state
        )
        total_files = len(file_paths)

        all_token_usage = {
            "total": 0,
            "prompt": 0,
            "cache_hit_prompt": 0,
            "completion": 0,
        }

        # Step 2: Iterate and Process each file
        for idx, file_path in enumerate(file_paths):
            filename = file_path.name
            current_file_idx = idx + 1
            task_prefix = f"[{current_file_idx}/{total_files}] {filename}: "

            logger.info(f"Processing file {current_file_idx}/{total_files}: {filename}")

            # Update display map for the original file being processed (if not already there)
            if filename not in state["display_map"]:
                state["display_map"][filename] = str(file_path)
                state["parent_map"][filename] = filename

            # Build translation settings
            translate_settings = _build_translate_settings(
                settings.clone(),
                file_path,
                output_dir,
                SaveMode.follow_settings,
                ui_inputs,
            )

            # Create task
            task = asyncio.create_task(
                _run_translation_task(
                    translate_settings,
                    file_path,
                    state,
                    progress,
                    task_prefix=task_prefix,
                )
            )
            state["current_task"] = task

            # Await result
            mono_path, dual_path, glossary_path, token_usage = await task

            # Store results
            result_entry = {
                "original_name": filename,
                "original_path": str(file_path),
                "mono": str(mono_path) if mono_path and mono_path.exists() else None,
                "dual": str(dual_path) if dual_path and dual_path.exists() else None,
                "glossary": str(glossary_path)
                if glossary_path and glossary_path.exists()
                else None,
                "token_usage": token_usage,
            }
            state["results"][filename] = result_entry
            state["file_order"].append(filename)

            # Update maps for dropdown
            if result_entry["mono"]:
                mono_label = f"{Path(filename).stem}_mono{Path(filename).suffix}"
                state["display_map"][mono_label] = result_entry["mono"]
                state["parent_map"][mono_label] = filename

            if result_entry["dual"]:
                dual_label = f"{Path(filename).stem}_dual{Path(filename).suffix}"
                state["display_map"][dual_label] = result_entry["dual"]
                state["parent_map"][dual_label] = filename

            # Accumulate tokens
            if token_usage:
                for key in ["main", "term"]:
                    if key in token_usage:
                        u = token_usage[key]
                        all_token_usage["total"] += u.get("total", 0)
                        all_token_usage["prompt"] += u.get("prompt", 0)
                        all_token_usage["cache_hit_prompt"] += u.get(
                            "cache_hit_prompt", 0
                        )
                        all_token_usage["completion"] += u.get("completion", 0)

            # YIELD UPDATE: Update the UI immediately after this file is done
            # Select the Dual version of the current file to show progress visually
            current_preview_label = filename
            if result_entry["dual"]:
                current_preview_label = (
                    f"{Path(filename).stem}_dual{Path(filename).suffix}"
                )
            elif result_entry["mono"]:
                current_preview_label = (
                    f"{Path(filename).stem}_mono{Path(filename).suffix}"
                )

            # Generate the intermediate UI update
            yield get_current_ui_update(current_preview_label)

        # Step 3: Finalize (Create Zips)
        # All files zip
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for _fname, res in state["results"].items():
                if res["mono"]:
                    zipf.write(res["mono"], arcname=f"mono_{Path(res['mono']).name}")
                if res["dual"]:
                    zipf.write(res["dual"], arcname=f"dual_{Path(res['dual']).name}")
                if res["glossary"]:
                    zipf.write(
                        res["glossary"],
                        arcname=f"glossary_{Path(res['glossary']).name}",
                    )

        # Individual Zips
        has_mono, has_dual, has_glossary = False, False, False
        with zipfile.ZipFile(zip_mono_path, "w") as zipf:
            for _fname, res in state["results"].items():
                if res["mono"]:
                    zipf.write(res["mono"], arcname=f"mono_{Path(res['mono']).name}")
                    has_mono = True

        with zipfile.ZipFile(zip_dual_path, "w") as zipf:
            for _fname, res in state["results"].items():
                if res["dual"]:
                    zipf.write(res["dual"], arcname=f"dual_{Path(res['dual']).name}")
                    has_dual = True

        with zipfile.ZipFile(zip_glossary_path, "w") as zipf:
            for _fname, res in state["results"].items():
                if res["glossary"]:
                    zipf.write(
                        res["glossary"],
                        arcname=f"glossary_{Path(res['glossary']).name}",
                    )
                    has_glossary = True

        progress(1.0, desc=_("All translations complete!"))

        # Final UI State
        token_info = f"\n\n**Total Token Usage:** Total {all_token_usage['total']} (Prompt {all_token_usage['prompt']}, Cache Hit {all_token_usage['cache_hit_prompt']}, Completion {all_token_usage['completion']})"

        # Determine final preview (last file processed or first)
        last_file_key = state["file_order"][-1] if state["file_order"] else None
        final_preview_label = None

        if last_file_key:
            res = state["results"][last_file_key]
            final_preview_label = last_file_key
            if res["dual"]:
                final_preview_label = (
                    f"{Path(last_file_key).stem}_dual{Path(last_file_key).suffix}"
                )
            elif res["mono"]:
                final_preview_label = (
                    f"{Path(last_file_key).stem}_mono{Path(last_file_key).suffix}"
                )

        # Get the base tuple
        (
            final_mono,
            final_preview_path,
            final_dual,
            final_glossary,
            vis_mono,
            vis_dual,
            vis_glossary,
            _u1,
            selector_update,
            selector_vis,
            _u2,
            _u3,
            _u4,
            _u5,
            _u6,
            _u7,
            _u8,
            _u9,
            uploaded_view_update,
        ) = get_current_ui_update(final_preview_label)

        # After successful translation of all files, clear uploaded files for next batch
        if "uploaded_files" in state:
            state["uploaded_files"] = []
            uploaded_view_update = gr.update(value="", visible=False)

        # Yield Final Result with Zips visible
        yield (
            final_mono,
            final_preview_path,
            final_dual,
            final_glossary,
            vis_mono,
            vis_dual,
            vis_glossary,
            gr.update(value=f"{_('## Translated')}{token_info}"),  # Title updated
            selector_update,
            selector_vis,
            gr.update(visible=True),
            str(zip_path),  # Zip
            gr.update(visible=has_mono),
            str(zip_mono_path) if has_mono else None,
            gr.update(visible=has_dual),
            str(zip_dual_path) if has_dual else None,
            gr.update(visible=has_glossary),
            str(zip_glossary_path) if has_glossary else None,
            uploaded_view_update,
        )

    except asyncio.CancelledError:
        gr.Info(_("Translation cancelled"))
        state["uploaded_files"] = []
        yield (
            None,
            None,
            None,
            None,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(choices=[], value=None, visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            None,
            gr.update(visible=False),
            None,
            gr.update(visible=False),
            None,
            gr.update(visible=False),
            None,
            gr.update(value="", visible=False),
        )
    except Exception as e:
        logger.exception(f"Error in translate_files: {e}")
        raise gr.Error(f"Translation failed: {e}") from e
    finally:
        state["current_task"] = None


def swap_languages(lang_from_value, lang_to_value):
    """
    交换源语言和目标语言的选择。
    """
    return lang_to_value, lang_from_value


def update_preview(selected_label, state):
    """
    Update preview based on selected label from dropdown.
    Modified to support previewing raw uploaded files before translation.
    """
    # 1. Basic validation
    if not selected_label or not state or "display_map" not in state:
        return (
            None,
            None,
            None,
            None,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )
    
    # 1.5. Validate selected_label is in display_map (choices)
    # This prevents Gradio errors when value is not in choices
    if selected_label not in state.get("display_map", {}):
        # Reset to first available choice or None
        choices = list(state.get("display_map", {}).keys())
        selected_label = choices[0] if choices else None
        if not selected_label:
            return (
                None,
                None,
                None,
                None,
                gr.update(visible=False),
                gr.update(visible=False),
                gr.update(visible=False),
            )

    # 2. Get the file path for the PDF viewer
    # This works for both uploaded files and translated files
    preview_path = state["display_map"].get(selected_label)

    if not preview_path:
        return (
            None,
            None,
            None,
            None,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )

    # 3. Try to get translation results for download buttons
    # If just uploaded (not translated), res will be None
    parent_key = state["parent_map"].get(selected_label)
    res = None
    if parent_key and "results" in state:
        res = state["results"].get(parent_key)

    # 4. Prepare return values
    # If res exists, show download buttons. If not, hide them.
    mono_path = res["mono"] if res else None
    dual_path = res["dual"] if res else None
    glossary_path = res["glossary"] if res else None

    return (
        mono_path,  # Download Mono Button Value
        preview_path,  # PDF Preview Value (Critical Fix: Always return this if found)
        dual_path,  # Download Dual Button Value
        glossary_path,  # Download Glossary Button Value
        gr.update(visible=bool(mono_path)),  # Mono Button Visibility
        gr.update(visible=bool(dual_path)),  # Dual Button Visibility
        gr.update(visible=bool(glossary_path)),  # Glossary Button Visibility
    )


def on_file_upload(files, state):
    """
    Handle file upload event to populate the preview dropdown immediately.
    """
    if not files:
        return (
            gr.update(choices=[], value=None, visible=False),
            state,
            gr.update(value="", visible=False),
        )

    # Initialize state if needed
    if not state:
        state = {
            "session_id": None,
            "current_task": None,
            "results": {},
            "file_order": [],
            "display_map": {},
            "parent_map": {},
            "uploaded_files": [],
        }

    if "display_map" not in state:
        state["display_map"] = {}
    if "parent_map" not in state:
        state["parent_map"] = {}
    if "uploaded_files" not in state:
        state["uploaded_files"] = []

    # Clear previous maps if this is a fresh upload action/session logic implies reset
    # For additive behavior, we keep them. Assuming additive for multi-upload.

    new_choices = []

    # Process uploaded files
    for f in files:
        # Gradio passes NamedString or file path
        f_path = Path(f.name if hasattr(f, "name") else f)
        original_name = f_path.name

        # Add to display map (Original file)
        state["display_map"][original_name] = str(f_path)
        state["parent_map"][original_name] = original_name

        # Track uploaded files for this session
        if original_name not in state["uploaded_files"]:
            state["uploaded_files"].append(original_name)

        # Add to local list to update UI
        if original_name not in new_choices:
            new_choices.append(original_name)

    # Get all current choices from state to preserve history + new files
    all_choices = list(state["display_map"].keys())

    # Default to the first file of the new batch if available
    default_value = (
        new_choices[0] if new_choices else (all_choices[0] if all_choices else None)
    )

    # Ensure default_value is in choices or None to avoid Gradio errors
    if default_value and default_value not in all_choices:
        default_value = all_choices[0] if all_choices else None

    # Build uploaded files markdown view
    uploaded_files = state["uploaded_files"]
    if uploaded_files:
        uploaded_md = "\n".join(
            f"{idx + 1}. {name}" for idx, name in enumerate(uploaded_files)
        )
        uploaded_view_update = gr.update(value=uploaded_md, visible=True)
    else:
        uploaded_view_update = gr.update(value="", visible=False)

    return (
        gr.update(choices=all_choices, value=default_value, visible=bool(all_choices)),
        state,
        uploaded_view_update,
    )


def on_file_clear(_files, state):
    """
    Handle file clear/delete event to clean up state and UI.
    When user clicks the X button on file input, this function removes uploaded files
    from state while preserving translation results.
    Also cancels any ongoing translation task.
    """
    # Initialize state if needed
    if not state:
        state = {
            "session_id": None,
            "current_task": None,
            "results": {},
            "file_order": [],
            "display_map": {},
            "parent_map": {},
            "uploaded_files": [],
        }

    if "display_map" not in state:
        state["display_map"] = {}
    if "parent_map" not in state:
        state["parent_map"] = {}
    if "uploaded_files" not in state:
        state["uploaded_files"] = []

    # Cancel any ongoing translation task
    if "current_task" in state and state["current_task"] is not None:
        try:
            state["current_task"].cancel()
            logger.info("Translation task cancelled due to file clear")
        except Exception as e:
            logger.error(f"Error cancelling translation task: {e}")
        finally:
            state["current_task"] = None

    # Get list of uploaded files to remove
    uploaded_files_to_remove = list(state["uploaded_files"])

    # Remove uploaded files from display_map and parent_map
    # But preserve translation results (mono/dual files)
    for original_name in uploaded_files_to_remove:
        # Remove original file entry from display_map
        if original_name in state["display_map"]:
            del state["display_map"][original_name]
        # Remove original file entry from parent_map
        if original_name in state["parent_map"]:
            del state["parent_map"][original_name]

    # Clear uploaded_files list
    state["uploaded_files"] = []

    # Build remaining choices (only translation results if any)
    remaining_choices = list(state["display_map"].keys())

    # Update UI components
    if remaining_choices:
        # If there are translation results, show them in dropdown
        default_value = remaining_choices[0]
        selector_update = gr.update(choices=remaining_choices, value=default_value, visible=True)
    else:
        # No files at all, hide dropdown
        default_value = None
        selector_update = gr.update(choices=[], value=None, visible=False)

    # Hide uploaded files view
    uploaded_view_update = gr.update(value="", visible=False)

    return (
        selector_update,
        state,
        uploaded_view_update,
        None,  # Clear preview
        None,  # Clear mono download
        None,  # Clear dual download
        None,  # Clear glossary download
        gr.update(visible=False),  # Hide mono button
        gr.update(visible=False),  # Hide dual button
        gr.update(visible=False),  # Hide glossary button
    )


def on_file_input_change(files, state, selected_label):
    """
    Handle per-file delete in the File(s) component (the small X on each row).

    Gradio triggers `change` when the list changes (add/remove). We diff against
    state["uploaded_files"] (which tracks current uploaded originals) to find removed
    items and keep state + preview selector consistent.
    """
    # Normalize files -> current names
    current_names: list[str] = []
    if files:
        for f in files:
            p = Path(f.name if hasattr(f, "name") else f)
            current_names.append(p.name)

    # Initialize state if needed
    if not state:
        state = {
            "session_id": None,
            "current_task": None,
            "results": {},
            "file_order": [],
            "display_map": {},
            "parent_map": {},
            "uploaded_files": [],
        }
    state.setdefault("display_map", {})
    state.setdefault("parent_map", {})
    state.setdefault("uploaded_files", [])

    prev_names = list(state.get("uploaded_files") or [])
    removed = [n for n in prev_names if n not in current_names]

    # If something was removed while translating, cancel to avoid processing stale inputs.
    if removed and state.get("current_task") is not None:
        try:
            state["current_task"].cancel()
            logger.info("Translation task cancelled due to per-file removal")
        except Exception as e:
            logger.error(f"Error cancelling translation task: {e}")
        finally:
            state["current_task"] = None

    # Remove deleted originals from display_map/parent_map
    for name in removed:
        state["display_map"].pop(name, None)
        state["parent_map"].pop(name, None)

    # Update uploaded_files to match current file_input
    state["uploaded_files"] = current_names

    # Rebuild uploaded files markdown view
    if current_names:
        uploaded_md = "\n".join(
            f"{idx + 1}. {name}" for idx, name in enumerate(current_names)
        )
        uploaded_view_update = gr.update(value=uploaded_md, visible=True)
    else:
        uploaded_view_update = gr.update(value="", visible=False)

    # Rebuild selector choices from state (includes translations + remaining originals)
    choices = list(state["display_map"].keys())

    # If current preview was removed, pick a safe fallback; otherwise keep selection.
    # Ensure selector_value is always in choices or None to avoid Gradio errors
    if selected_label in removed:
        selected_label = None
    if selected_label and selected_label in choices:
        selector_value = selected_label
    else:
        selector_value = choices[0] if choices else None

    # Always ensure value is in choices or None
    if selector_value and selector_value not in choices:
        selector_value = choices[0] if choices else None

    selector_update = (
        gr.update(choices=choices, value=selector_value, visible=bool(choices))
        if choices
        else gr.update(choices=[], value=None, visible=False)
    )

    # Update preview + download buttons based on new selection
    mono_path, preview_path, dual_path, glossary_path, vis_mono, vis_dual, vis_glossary = (
        update_preview(selector_value, state)
        if selector_value
        else (
            None,
            None,
            None,
            None,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )
    )

    return (
        selector_update,
        state,
        uploaded_view_update,
        preview_path,  # preview
        mono_path,
        dual_path,
        glossary_path,
        vis_mono,
        vis_dual,
        vis_glossary,
    )


def save_config(
    *ui_args,
    progress=None,
):
    """
    This function saves the translation configuration.

    Inputs:
        - *ui_args: UI setting controls (see build_ui_inputs for details)
        - progress: The progress bar
    """
    # Setup progress tracking
    if progress is None:
        progress = gr.Progress()

    # Build ui_inputs from *args
    ui_inputs = build_ui_inputs(*ui_args)

    # Track progress
    progress(0, desc=_("Saving configuration..."))

    # Prepare output directory
    output_dir = Path("pdf2zh_files")

    _build_translate_settings(
        settings.clone(), config_fake_pdf_path, output_dir, SaveMode.always, ui_inputs
    )

    # Show success message
    gr.Info(_("Configuration saved to: {path}").format(path=DEFAULT_CONFIG_FILE))


# Custom theme definition
custom_blue = gr.themes.Color(
    c50="#E8F3FF",
    c100="#BEDAFF",
    c200="#94BFFF",
    c300="#6AA1FF",
    c400="#4080FF",
    c500="#165DFF",  # Primary color
    c600="#0E42D2",
    c700="#0A2BA6",
    c800="#061D79",
    c900="#03114D",
    c950="#020B33",
)

custom_css = """
    .secondary-text {color: #999 !important;}
    footer {visibility: hidden}
    .env-warning {color: #dd5500 !important;}
    .env-success {color: #559900 !important;}

    /* SiliconFlow logo: 添加白色背景，确保在深色模式下清晰可见 */
    img[alt="Powered By SiliconFlow"] {
        background-color: #ffffff !important;
        padding: 4px !important;
        border-radius: 4px !important;
    }

    /* 保存设置按钮：添加背景色 */
    .save-settings-btn button,
    button.save-settings-btn {
        background-color: var(--primary-500) !important;
        color: #ffffff !important;
        border-color: var(--primary-500) !important;
    }
    .save-settings-btn button:hover,
    button.save-settings-btn:hover {
        background-color: var(--primary-600) !important;
        border-color: var(--primary-600) !important;
    }

    /* Add dashed border to input-file class */
    .input-file {
        border: 1.2px dashed #165DFF !important;
        border-radius: 6px !important;
    }

    /* Upload box: make it more compact (about half height) and keep text in one row (as in ref fig2) */
    .input-file [data-testid="file-upload"],
    .input-file [data-testid="file-upload"] > div,
    .input-file .wrap,
    .input-file .upload-box {
        min-height: 140px !important;
        height: 140px !important;
    }

    /* Center the dropzone content */
    .input-file [data-testid="file-upload"] .text,
    .input-file [data-testid="file-upload"] .file-upload-text,
    .input-file .file-upload-text,
    .input-file .upload-text {
        display: flex !important;
        flex-direction: row !important;
        align-items: center !important;
        justify-content: center !important;
        gap: 10px !important;
        white-space: nowrap !important;
        text-align: center !important;
        line-height: 1.2 !important;
    }

    /* Make the separator “- or -” behave like an inline pill */
    .input-file [data-testid="file-upload"] .text > br,
    .input-file .file-upload-text > br,
    .input-file .upload-text > br {
        display: none !important;
    }

    /* Slightly shrink icon/text so the compact height still looks balanced */
    .input-file [data-testid="file-upload"] svg {
        transform: scale(0.9);
        transform-origin: center;
    }
    .input-file [data-testid="file-upload"] .text,
    .input-file [data-testid="file-upload"] .file-upload-text,
    .input-file .file-upload-text,
    .input-file .upload-text {
        font-size: 0.95rem !important;
    }

    .progress-bar-wrap {
        border-radius: 8px !important;
    }

    .progress-bar {
        border-radius: 8px !important;
    }

    .pdf-canvas canvas {
        width: 100%;
    }

    /* 侧边栏：左侧窄卡片，两个图标按钮竖排 */
    .sidebar-nav {
        position: sticky;
        top: 20px;
        align-self: flex-start;
        border: 1px solid var(--block-border-color);
        border-radius: 14px;
        padding: 16px 10px;
        display: flex;
        flex-direction: column;
        gap: 10px;
        background: var(--block-background-fill);
        box-shadow: var(--block-shadow);
    }

    .sidebar-btn {
        width: 44px;
        height: 44px;
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin: 0 auto;
    }

    /* 首页左右列高度对齐：Row 内两列拉伸为同高 */
    .tab-main-row {
        align-items: stretch !important;
        gap: 16px !important;  /* 左右两列之间留出适当间距 */
    }
    .tab-main-row > .gr-column {
        height: 100% !important;
    }
    /* 左侧设置列：保持结构，用 padding 做与右侧对称的“外侧留白” */
    .tab-main-row > .gr-column:first-of-type {
        display: flex !important;
        flex-direction: column !important;
        padding-left: 20px !important;      /* 左侧留白 */
        padding-right: 0 !important;
    }


    .tab-main-row > .gr-column:last-of-type {
        background: rgba(0, 0, 0, 0.04) !important; /* 更明显的浅灰 */
        padding-right: 20px !important;             /* 右侧留白，与左侧对称 */
        padding-left: 0 !important;
    }

    /* 翻译/取消按钮一行展示，按钮收窄成圆角矩形 */
    .action-row {
        justify-content: flex-start !important;
        gap: 12px !important;
        margin-top: 12px !important;
        margin-bottom: 4px !important;
        padding-left: 8px !important;   /* 左侧留白，避免按钮贴左边 */
        padding-right: 8px !important;  /* 右侧留白，避免按钮贴右边 */
    }
    .action-row .action-btn button,
    .action-row button.action-btn {
        border-radius: 8px !important;        
        padding-inline: 24px !important;
        padding-block: 10px !important;
        min-width: 120px !important;
        font-weight: 500 !important;
    }
    /* 取消按钮：改成明显的红色背景 */
    .action-row .action-btn-secondary button,
    .action-row button.action-btn-secondary {
        background: #ff3b30 !important;
        border-color: rgba(255, 59, 48, 0.6) !important;
        color: #ffffff !important;
    }

    /* 固定大小的预览窗口，文档自动缩放以适配窗口高度，不再忽大忽小 */
    .pdf-preview-fixed {
        /* 在不同屏幕下保持较大的预览区域，减少“显示区域变小”的感觉 */
        height: min(75vh, 720px) !important;
        max-height: 720px !important;
        overflow: hidden !important;
        position: relative !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        padding: 12px !important;  /* 四周留白，确保文档不贴边 */
    }
    /* Gradio PDF 组件内部会渲染一个“BlockLabel”（data-testid="block-label"），
       默认文案是“File”。我们右侧已经有上方标题，因此这里把它隐藏，
       避免在 flex 居中布局下漂到左列按钮附近。 */
    .pdf-preview-fixed [data-testid="block-label"] {
        display: none !important;
    }

    /* PDF 容器：确保内容完全适配 */
    .pdf-preview-fixed .pdf-canvas {
        width: 100% !important;
        height: 100% !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        overflow: hidden !important;
        position: relative !important;
    }

    /* 让 PDF 内容按照高度缩放，宽度不超过窗口，并居中显示 */
    /* 使用 max-height 确保完整显示，不被裁剪 */
    .pdf-preview-fixed iframe,
    .pdf-preview-fixed embed {
        max-height: calc(100% - 24px) !important;  /* 减去上下 padding (12px * 2) */
        height: auto !important;  /* 自动高度，保持宽高比 */
        width: auto !important;
        max-width: calc(100% - 24px) !important;  /* 减去左右 padding */
        display: block !important;
        margin: 0 auto !important;
        object-fit: contain !important;  /* 确保完整显示，不被裁剪 */
    }

    /* Canvas 元素特殊处理：确保完全适配容器高度 */
    .pdf-preview-fixed canvas {
        max-height: calc(100% - 24px) !important;  /* 减去上下 padding (12px * 2) */
        max-width: calc(100% - 24px) !important;  /* 减去左右 padding */
        height: auto !important;
        width: auto !important;
        display: block !important;
        margin: 0 auto !important;
        /* Canvas 不支持 object-fit，需要通过 JS 动态缩放，但 CSS 确保不超出边界 */
        background: #ffffff !important;  /* 浅色模式下保持白色 */
        position: relative !important;
    }

    /* 深色模式下 PDF 预览区域背景保持深色 */
    .dark .pdf-preview-fixed,
    [data-theme="dark"] .pdf-preview-fixed,
    body.dark .pdf-preview-fixed {
        background: var(--block-background-fill, #1e1e1e) !important;
    }

    /* 深色模式下 PDF 容器背景保持透明，让深色背景显示 */
    .dark .pdf-preview-fixed .pdf-canvas,
    [data-theme="dark"] .pdf-preview-fixed .pdf-canvas,
    body.dark .pdf-preview-fixed .pdf-canvas {
        background: transparent !important;
    }

    /* 深色模式下 PDF canvas 使用柔和的浅灰色背景，不那么突兀 */
    .dark .pdf-preview-fixed canvas,
    [data-theme="dark"] .pdf-preview-fixed canvas,
    body.dark .pdf-preview-fixed canvas {
        background: #f5f5f5 !important;  /* 浅灰色，比纯白柔和 */
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1) !important;  /* 更柔和的阴影和边框 */
        border-radius: 4px !important;  /* 圆角使过渡更自然 */
        padding: 8px !important;  /* 内边距让背景稍微大一点 */
        box-sizing: content-box !important;  /* 确保 padding 不影响 canvas 大小 */
    }

    /* 深色模式下 iframe 和 embed 使用相同处理 */
    .dark .pdf-preview-fixed iframe,
    .dark .pdf-preview-fixed embed,
    [data-theme="dark"] .pdf-preview-fixed iframe,
    [data-theme="dark"] .pdf-preview-fixed embed,
    body.dark .pdf-preview-fixed iframe,
    body.dark .pdf-preview-fixed embed {
        background: #f5f5f5 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
        border-radius: 4px !important;
    }

    /* 确保 PDF 渲染容器在深色模式下背景透明 */
    .dark .pdf-preview-fixed > div,
    .dark .pdf-preview-fixed > div > div,
    [data-theme="dark"] .pdf-preview-fixed > div,
    [data-theme="dark"] .pdf-preview-fixed > div > div,
    body.dark .pdf-preview-fixed > div,
    body.dark .pdf-preview-fixed > div > div {
        background: transparent !important;
    }

    /* 通用深色模式检测 */
    [class*="dark"] .pdf-preview-fixed canvas,
    [class*="dark"] .pdf-preview-fixed iframe,
    [class*="dark"] .pdf-preview-fixed embed {
        background: #f5f5f5 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
        border-radius: 4px !important;
    }

    /* 确保 PDF 文本层在深色模式下可见 */
    .pdf-preview-fixed .textLayer {
        mix-blend-mode: normal !important;
    }

    /* 深色模式下 PDF 注释层 */
    .pdf-preview-fixed .annotationLayer {
        background: transparent !important;
    }

    /* 为 PDF canvas 添加一个包装器，用于精确控制背景大小 */
    .pdf-preview-fixed .pdf-canvas-wrapper {
        display: inline-block !important;
        background: transparent !important;
        position: relative !important;
    }

    /* 深色模式下 canvas 包装器背景 */
    .dark .pdf-preview-fixed .pdf-canvas-wrapper,
    [data-theme="dark"] .pdf-preview-fixed .pdf-canvas-wrapper,
    body.dark .pdf-preview-fixed .pdf-canvas-wrapper {
        background: #f5f5f5 !important;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4), 0 0 0 1px rgba(255, 255, 255, 0.1) !important;
        border-radius: 4px !important;
        padding: 8px !important;
        display: inline-block !important;
    }

    /* 重新布局 PDF 翻页控件：左右箭头居中悬浮，页码在底部居中 */
    .pdf-preview-fixed .button-row {
        position: absolute !important;
        inset: 0 !important;
        pointer-events: none !important; /* 只禁用容器，内部按钮和页码再单独开启 */
        background: transparent !important;
        z-index: 5 !important;
    }

    /* 左右翻页按钮：分别悬浮在左右居中位置，使用透明圆形按钮样式（类似 p1） */
    .pdf-preview-fixed .button-row > button {
        position: absolute !important;
        top: 50% !important;
        transform: translateY(-50%) !important;
        pointer-events: auto !important;
        background: transparent !important;      /* 默认透明背景 */
        border-radius: 999px !important;        /* 圆形按钮 */
        border: none !important;
        box-shadow: none !important;
        width: 40px !important;
        height: 40px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        color: #ffffff !important;              /* 白色箭头 */
        transition: background-color 0.18s ease-out, transform 0.18s ease-out !important;
    }
    /* 悬停时出现半透明高亮圈，模拟“隐约选中变色”效果 */
    .pdf-preview-fixed .button-row > button:hover {
        background: rgba(255, 255, 255, 0.12) !important;
        transform: translateY(-50%) scale(1.02) !important;
    }
    .pdf-preview-fixed .button-row > button:active {
        background: rgba(255, 255, 255, 0.18) !important;
        transform: translateY(-50%) scale(0.97) !important;
    }
    .pdf-preview-fixed .button-row > button:first-of-type {
        left: 12px !important;
    }
    .pdf-preview-fixed .button-row > button:last-of-type {
        right: 12px !important;
    }

    /* 页码信息：预览框内部底部居中悬浮 */
    .pdf-preview-fixed .button-row .page-count {
        position: absolute !important;
        left: 50% !important;
        bottom: 10px !important;
        transform: translateX(-50%) !important;
        pointer-events: auto !important;
        padding: 4px 10px !important;
        border-radius: 999px !important;
        background: rgba(0, 0, 0, 0.65) !important;
        color: #fff !important;
        display: flex !important;
        align-items: center !important;
        gap: 6px !important;
    }

    /* 页码输入框：未点击时背景透明，点击后显示半透明背景 */
    .pdf-preview-fixed .button-row .page-count input[type="number"] {
        background: transparent !important;  /* 默认透明背景，融入外层胶囊 */
        border: none !important;            /* 去掉矩形边框 */
        color: #fff !important;
        box-shadow: none !important;
        width: 3ch !important;          /* 只容纳 2~3 位数字，缩小整体宽度 */
        min-width: 3ch !important;
        padding: 2px 4px !important;    /* 收紧内边距，让方框更小巧 */
        font-size: 0.9em !important;
        border-radius: 4px !important;   /* 圆角，与背景矩形协调 */
        transition: background-color 0.2s ease !important;  /* 平滑过渡 */
        /* 隐藏原生上下小箭头，避免误导 */
        -moz-appearance: textfield !important;
    }
    /* 点击后（focus 状态）：显示半透明背景矩形 */
    .pdf-preview-fixed .button-row .page-count input[type="number"]:focus {
        background: rgba(255, 255, 255, 0.15) !important;  /* 半透明白色背景，提示可编辑 */
        outline: none !important;  /* 去掉默认的浏览器 focus outline */
    }
    .pdf-preview-fixed .button-row .page-count input[type="number"]::-webkit-inner-spin-button,
    .pdf-preview-fixed .button-row .page-count input[type="number"]::-webkit-outer-spin-button {
        -webkit-appearance: none !important;
        margin: 0 !important;
    }

    /* 整体视觉协调优化 */
    /* 标题字体稍微变小，并与卡片边框留一点内边距 */
    .tab-title h2 {
        font-size: 1.05rem !important;
        margin: 6px 8px 10px 8px !important;
    }

    /* 预览区标题和下拉框间距 */
    .tab-main-row > .gr-column:last-of-type .tab-title h2 {
        margin-bottom: 6px !important;
    }

    /* 左侧列内各区块间距优化 */
    .tab-main-row > .gr-column:first-of-type > * {
        margin-bottom: 16px !important;
    }
    .tab-main-row > .gr-column:first-of-type > *:last-child {
        margin-bottom: 0 !important;
    }

    /* 设置界面：限制最大宽度并左对齐，使界面更美观 */
    .settings-container {
        max-width: min(900px, 85vw) !important;  /* 最大 900px，小屏幕时不超过 85% 视口宽度 */
        margin: 0 !important;                     /* 左对齐，不居中 */
        padding-left: 20px !important;            /* 左侧留白 */
        padding-right: 0 !important;              /* 右侧不留白，让内容自然延伸 */
    }

    /* 上传文件列表：左侧留白，避免列表项贴左边 */
    .uploaded-files-list {
        padding-left: 12px !important;
    }
    .uploaded-files-list ul,
    .uploaded-files-list ol {
        padding-left: 0 !important;
        margin-left: 0 !important;
    }

    /* 语言选择行：作为交换按钮的定位参照容器 */
    .lang-row {
        position: relative !important;
        align-items: flex-start !important;
    }

    /* 语言交换按钮：悬浮在左侧标签文字右边的圆角矩形，两个下拉框仍紧挨在一起 */
    .lang-row .lang-swap-btn {
        position: absolute !important;
        /* 放在"从...翻译"标签的右边，与文字在同一水平线 */
        top: 7px !important;                 /* 与标签文字在同一水平线上 */
        left: 20% !important;                /* 位于左侧标签右边，不居中 */
        transform: none !important;          /* 不再居中，使用 left 直接定位 */
        width: 24px !important;             /* 更小的圆形图标按钮 */
        height: 24px !important;
        min-width: 24px !important;
        padding: 0 !important;
        border-radius: 999px !important;    /* 完全圆形 */
        background: transparent !important;
        border: none !important;
        color: rgba(148, 163, 184, 1) !important;  /* 中性色箭头，浅/深色都自然 */
        font-size: 14px !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        transition: all 0.2s ease !important;
        cursor: pointer !important;
        z-index: 5 !important;              /* 提到分隔线之上，避免被裁剪 */
    }
    .lang-swap-btn:hover {
        background: rgba(148, 163, 184, 0.12) !important;
        color: var(--primary-500) !important;
    }
    .lang-swap-btn:active {
        background: rgba(148, 163, 184, 0.2) !important;
    }
    """

# Build paths to resources
current_dir = Path(__file__).parent
assets_dir = current_dir / "assets"
logo_path = assets_dir / "powered_by_siliconflow_light.png"
translation_file_path = current_dir / "gui_translation.yaml"
config_fake_pdf_path = DEFAULT_CONFIG_DIR / "config.fake.pdf"
pdf_preview_allowed_paths = [
    logo_path,
    Path("pdf2zh_files").resolve(),  # translation outputs
    Path(tempfile.gettempdir()).resolve(),  # uploaded temp files
]

if not config_fake_pdf_path.exists():
    with config_fake_pdf_path.open("w") as f:
        f.write("This is a fake PDF file for configuration saving.")
        f.flush()


tech_details_string = f"""
                    <summary>Technical details</summary>
                    - ⭐ Star at GitHub: <a href="https://github.com/PDFMathTranslate-next/PDFMathTranslate-next">PDFMathTranslate-next/PDFMathTranslate-next</a><br>
                    - BabelDOC: <a href="https://github.com/funstory-ai/BabelDOC">funstory-ai/BabelDOC</a><br>
                    - GUI by: <a href="https://github.com/reycn">Rongxin</a> & <a href="https://github.com/hellofinch">hellofinch</a> & <a href="https://github.com/awwaawwa">awwaawwa</a> & <a href="https://github.com/zfb132">zfb132</a><br>
                    - pdf2zh Version: {__version__} <br>
                    - BabelDOC Version: {babeldoc_version}<br>
                    - Free translation service provided by <a href="https://siliconflow.cn/" target="_blank" style="text-decoration: none;">SiliconFlow</a><br>
                    <a href="https://siliconflow.cn/" target="_blank" style="text-decoration: none;">
                        <img src="/gradio_api/file={logo_path}" alt="Powered By SiliconFlow" style="height: 40px; margin-top: 10px; background-color: #ffffff; padding: 4px; border-radius: 4px;">
                    </a>
                    <br>
                """
update_current_languages(settings.gui_settings.ui_lang)
# The following code creates the GUI
with gr.Blocks(
    title="PDFMathTranslate - PDF Translation with preserved formats",
    theme=gr.themes.Default(
        primary_hue=custom_blue, spacing_size="md", radius_size="lg"
    ),
    css=custom_css,
) as demo:
    lang_selector = gr.Dropdown(
        choices=LANGUAGES,
        label=_("UI Language"),
        value=settings.gui_settings.ui_lang,
        render=False,
    )
    with Translate(get_translation_dic(translation_file_path), lang_selector):
        gr.Markdown("# [PDFMathTranslate Next](https://pdf2zh-next.com)")

        translation_engine_arg_inputs = []
        detail_text_inputs = []
        detail_text_input_field_names = []
        detail_text_input_fields = []
        detail_visibility_dependency_inputs = {}
        detail_visibility_dependency_events = []
        require_llm_translator_inputs = []
        detail_text_input_index_map = {}
        term_detail_text_inputs = []
        term_detail_text_input_field_names = []
        term_detail_text_input_fields = []
        term_detail_visibility_dependency_inputs = {}
        term_detail_visibility_dependency_events = []
        term_detail_text_input_index_map = {}
        LLM_support_index_map.clear()
        with gr.Row(elem_classes=["tab-main-row"], equal_height=True):
            # 左侧侧边栏
            with gr.Column(scale=0, min_width=70, elem_classes=["sidebar-nav"]):
                btn_main_tab = gr.Button("🚀", variant="primary", elem_classes=["sidebar-btn"])
                btn_settings_tab = gr.Button("⚙️", variant="secondary", elem_classes=["sidebar-btn"])

            # 右侧主内容区域：再拆成“主页”和“设置”两个分组
            with gr.Column(scale=1):
                with gr.Group(visible=True) as tab_main:
                    # 主页内部使用左右两列布局：左侧基础设置/翻译结果，右侧预览
                    with gr.Row():
                        with gr.Column(scale=1):
                            gr.Markdown(_("## File(s)"), elem_classes=["tab-title"])
                            file_type = gr.Radio(
                                choices=[("File(s)", "File"), ("Link", "Link")],
                                label="Type",
                                value="File",
                            )
                            file_input = gr.File(
                                label=_("File(s)"),
                                file_count="multiple",
                                file_types=[".pdf", ".PDF"],
                                type="filepath",
                                elem_classes=["input-file"],
                            )
                            link_input = gr.Textbox(
                                label=_("Link"),
                                visible=False,
                                interactive=True,
                            )
                            uploaded_files_view = gr.Markdown(
                                label=_("Uploaded files (this session)"),
                                value="",
                                visible=False,
                                elem_classes=["uploaded-files-list"],
                            )

                            gr.Markdown(_("## Translation Options"), elem_classes=["tab-title"])

                            # 语言选择与交换按钮所在的一行
                            with gr.Row(elem_classes=["lang-row"]):
                                lang_from = gr.Dropdown(
                                    label=_("Translate from"),
                                    choices=list(lang_map.keys()),
                                    value=default_lang_from,
                                )
                                # 交换语言按钮：放在两个下拉框之间
                                swap_lang_btn = gr.Button(
                                    "⇄",
                                    elem_classes=["lang-swap-btn"],
                                    scale=0,
                                    min_width=40,
                                )
                                lang_to = gr.Dropdown(
                                    label=_("Translate to"),
                                    choices=list(lang_map.keys()),
                                    value=default_lang_to,
                                )

                            # 主界面左侧保留翻译按钮和已翻译下载区
                            output_title = gr.Markdown(_("## Translated"), visible=False)
                            output_file_mono = gr.File(
                                label=_("Download Translation (Mono)"), visible=False
                            )
                            output_file_dual = gr.File(
                                label=_("Download Translation (Dual)"), visible=False
                            )
                            output_file_glossary = gr.File(
                                label=_("Download automatically extracted glossary"),
                                visible=False,
                            )
                            output_file_zip = gr.File(
                                label=_("Download All (ZIP)"), visible=False
                            )
                            output_file_zip_mono = gr.File(
                                label=_("Download All Mono (ZIP)"), visible=False
                            )
                            output_file_zip_dual = gr.File(
                                label=_("Download All Dual (ZIP)"), visible=False
                            )
                            output_file_zip_glossary = gr.File(
                                label=_("Download All Glossaries (ZIP)"), visible=False
                            )
                            # 操作按钮一行展示：翻译 / 取消 两个圆角按钮
                            with gr.Row(elem_classes=["action-row"]):
                                translate_btn = gr.Button(
                                    _("Translate"),
                                    variant="primary",
                                    elem_classes=["action-btn", "action-btn-primary"],
                                )
                                cancel_btn = gr.Button(
                                    _("Cancel"),
                                    variant="secondary",
                                    elem_classes=["action-btn", "action-btn-secondary"],
                                )

                        with gr.Column(scale=2):
                            gr.Markdown(_("## Preview"), elem_classes=["tab-title"])
                            # 结果选择 + 预览
                            result_file_selector = gr.Dropdown(
                                label=_("Select File to Preview/Download"),
                                choices=[],
                                value=None,
                                visible=True,
                                interactive=True,
                            )
                            # 预览区域上方已经有“## Preview”标题，这里关闭组件自带 label，
                            # 避免 Gradio 的标签卡片在布局调整后漂到左侧中间
                            preview = PDF(
                                label=None,
                                show_label=False,
                                visible=True,
                                elem_classes=["pdf-preview-fixed"],
                            )

                # 其余高级配置都移动到设置页
                with gr.Group(visible=False, elem_classes=["settings-container"]) as tab_settings:
                    # 界面语言切换只在“设置”页展示
                    lang_selector.render()
                    siliconflow_free_acknowledgement = gr.Markdown(
                        _(
                            "Free translation service provided by [SiliconFlow](https://siliconflow.cn)"
                        ),
                        visible=True,
                    )

                    detail_index = 0
                    term_detail_index = 0
                    with gr.Group() as translation_engine_settings:
                        service = gr.Dropdown(
                            label=_("Service"),
                            choices=available_services,
                            value=available_services[0],
                        )

                        __gui_service_arg_names = []
                        for service_name in available_services:
                            metadata = TRANSLATION_ENGINE_METADATA_MAP[service_name]
                            LLM_support_index_map[metadata.translate_engine_type] = (
                                metadata.support_llm
                            )
                            if not metadata.cli_detail_field_name:
                                # no detail field, no need to show
                                continue
                            detail_settings = getattr(
                                settings, metadata.cli_detail_field_name
                            )
                            visible = service.value == metadata.translate_engine_type

                            # OpenAI specific settings (initially visible if OpenAI is default)
                            with gr.Group(visible=True) as service_detail:
                                detail_text_input_index_map[
                                    metadata.translate_engine_type
                                ] = []
                                for (
                                    field_name,
                                    field,
                                ) in metadata.setting_model_type.model_fields.items():
                                    if disable_gui_sensitive_input:
                                        if field_name in GUI_SENSITIVE_FIELDS:
                                            continue
                                        if field_name in GUI_PASSWORD_FIELDS:
                                            continue
                                    if field.default_factory:
                                        continue

                                    if field_name == "translate_engine_type":
                                        continue
                                    if field_name == "support_llm":
                                        continue
                                    type_hint = field.annotation
                                    original_type = typing.get_origin(type_hint)
                                    type_args = typing.get_args(type_hint)
                                    value = getattr(detail_settings, field_name)
                                    gui_extra = _field_gui_extra(field)
                                    field_values = {
                                        name: getattr(detail_settings, name)
                                        for name in metadata.setting_model_type.model_fields
                                    }
                                    field_visible = _gui_field_visible(
                                        field_name,
                                        field,
                                        visible,
                                        field_values,
                                    )
                                    if gui_extra.get("widget") == "dropdown":
                                        field_input = gr.Dropdown(
                                            label=field.description,
                                            choices=gui_extra["choices"],
                                            value=_gui_field_value(field, value),
                                            interactive=True,
                                            visible=field_visible,
                                        )
                                    elif (
                                        type_hint is str
                                        or str in type_args
                                        or type_hint is int
                                        or int in type_args
                                    ):
                                        if field_name in GUI_PASSWORD_FIELDS:
                                            field_input = gr.Textbox(
                                                label=field.description,
                                                value=value,
                                                interactive=True,
                                                type="password",
                                                visible=field_visible,
                                            )
                                        else:
                                            field_input = gr.Textbox(
                                                label=field.description,
                                                value=value,
                                                interactive=True,
                                                visible=field_visible,
                                            )
                                    elif type_hint is bool or bool in type_args:
                                        field_input = gr.Checkbox(
                                            label=field.description,
                                            value=value,
                                            interactive=True,
                                            visible=field_visible,
                                        )
                                    else:
                                        raise Exception(
                                            f"Unsupported type {type_hint} for field {field_name} in gui translation engine settings"
                                        )
                                    detail_text_input_index_map[
                                        metadata.translate_engine_type
                                    ].append(detail_index)
                                    detail_index += 1
                                    detail_text_inputs.append(field_input)
                                    detail_text_input_field_names.append(field_name)
                                    detail_text_input_fields.append(field)
                                    visible_when = gui_extra.get("visible_when")
                                    if visible_when:
                                        dependency_field_name = _gui_dependency_field_name(
                                            field_name, visible_when["field"]
                                        )
                                        dependency_input = (
                                            detail_visibility_dependency_inputs.get(
                                                dependency_field_name
                                            )
                                        )
                                        if dependency_input is not None:
                                            detail_visibility_dependency_events.append(
                                                (
                                                    metadata.translate_engine_type,
                                                    field_name,
                                                    field,
                                                    dependency_input,
                                                    field_input,
                                                )
                                            )
                                    detail_visibility_dependency_inputs[field_name] = field_input
                                    __gui_service_arg_names.append(field_name)
                                    translation_engine_arg_inputs.append(field_input)
                    with gr.Group() as rate_limit_settings:
                        rate_limit_mode = gr.Radio(
                            choices=[
                                ("RPM (Requests Per Minute)", "RPM"),
                                ("Concurrent Requests", "Concurrent Threads"),
                                ("Custom", "Custom"),
                            ],
                            label="Rate Limit Mode",
                            value="Custom",
                            interactive=True,
                            visible=False,
                            info="Select the rate limit mode that best suits your API provider, system will automatically convert the rate limiting values of RPM or Concurrent Requests to QPS and Pool Max Workers when you click the Translate button",
                        )

                        rpm_input = gr.Number(
                            label=_("RPM (Requests Per Minute)"),
                            value=240,  # More conservative default value
                            precision=0,
                            minimum=1,
                            maximum=60000,
                            interactive=True,
                            visible=False,
                            info=_(
                                "Most API providers provide this parameter, such as OpenAI GPT-4: 500 RPM"
                            ),
                        )

                        concurrent_threads_input = gr.Number(
                            label=_("Concurrent Threads"),
                            value=20,  # More conservative default value
                            precision=0,
                            minimum=1,
                            maximum=1000,
                            interactive=True,
                            visible=False,
                            info=_(
                                "Maximum number of requests processed simultaneously"
                            ),
                        )

                        custom_qps_input = gr.Number(
                            label=_("QPS (Queries Per Second)"),
                            value=settings.translation.qps or 4,
                            precision=0,
                            minimum=1,
                            maximum=1000,
                            interactive=True,
                            visible=False,
                            info=_("Number of requests sent per second"),
                        )

                        custom_pool_max_workers_input = gr.Number(
                            label=_("Pool Max Workers"),
                            value=settings.translation.pool_max_workers,
                            precision=0,
                            minimum=0,
                            maximum=1000,
                            interactive=True,
                            visible=False,
                            info=_(
                                "If not set or set to 0, QPS will be used as the number of workers"
                            ),
                        )

                    # Term extraction options (engine + rate limit + detail settings)
                    with gr.Accordion(_("Auto Term Extraction"), open=True):
                        enable_auto_term_extraction = gr.Checkbox(
                            label=_("Enable auto term extraction"),
                            value=not settings.translation.no_auto_extract_glossary,
                            interactive=True,
                        )

                        term_disabled_info = gr.Markdown(
                            _(
                                "Auto term extraction is disabled. Term extraction settings below will not take effect until it is enabled."
                            ),
                            visible=settings.translation.no_auto_extract_glossary,
                        )

                        with gr.Group(visible=True) as term_settings_group:
                            term_service = gr.Dropdown(
                                label=_("Term extraction engine"),
                                choices=[
                                    (
                                        _("Follow main translation engine"),
                                        "Follow main translation engine",
                                    )
                                ]
                                + [
                                    metadata.translate_engine_type
                                    for metadata in TERM_EXTRACTION_ENGINE_METADATA
                                ],
                                value="Follow main translation engine",
                            )

                            # Term engine detail settings
                            __gui_term_service_arg_names = []
                            for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
                                if not term_metadata.cli_detail_field_name:
                                    continue
                                term_detail_field_name = (
                                    f"term_{term_metadata.cli_detail_field_name}"
                                )
                                term_detail_settings = getattr(
                                    settings, term_detail_field_name
                                )

                                # Term engine settings group should stay visible;
                                # visibility is controlled by each field input.
                                with gr.Group() as term_service_detail:
                                    term_detail_text_input_index_map[
                                        term_metadata.translate_engine_type
                                    ] = []
                                    for (
                                        field_name,
                                        field,
                                    ) in term_metadata.term_setting_model_type.model_fields.items():
                                        if field_name in (
                                            "translate_engine_type",
                                            "support_llm",
                                        ):
                                            continue
                                        if field.default_factory:
                                            continue

                                        base_field_name = field_name
                                        if base_field_name.startswith("term_"):
                                            base_name = base_field_name[len("term_") :]
                                        else:
                                            base_name = base_field_name

                                        if disable_gui_sensitive_input:
                                            if base_name in GUI_SENSITIVE_FIELDS:
                                                continue
                                            if base_name in GUI_PASSWORD_FIELDS:
                                                continue

                                        type_hint = field.annotation
                                        original_type = typing.get_origin(type_hint)
                                        type_args = typing.get_args(type_hint)
                                        value = getattr(term_detail_settings, field_name)
                                        gui_extra = _field_gui_extra(field)
                                        term_field_values = {
                                            name: getattr(term_detail_settings, name)
                                            for name in term_metadata.term_setting_model_type.model_fields
                                        }
                                        field_visible = _gui_field_visible(
                                            field_name,
                                            field,
                                            False,
                                            term_field_values,
                                        )

                                        if gui_extra.get("widget") == "dropdown":
                                            field_input = gr.Dropdown(
                                                label=field.description,
                                                choices=gui_extra["choices"],
                                                value=_gui_field_value(field, value),
                                                interactive=True,
                                                visible=field_visible,
                                            )
                                        elif (
                                            type_hint is str
                                            or str in type_args
                                            or type_hint is int
                                            or int in type_args
                                        ):
                                            if base_name in GUI_PASSWORD_FIELDS:
                                                field_input = gr.Textbox(
                                                    label=field.description,
                                                    value=value,
                                                    interactive=True,
                                                    type="password",
                                                    visible=field_visible,
                                                )
                                            else:
                                                field_input = gr.Textbox(
                                                    label=field.description,
                                                    value=value,
                                                    interactive=True,
                                                    visible=field_visible,
                                                )
                                        elif type_hint is bool or bool in type_args:
                                            field_input = gr.Checkbox(
                                                label=field.description,
                                                value=value,
                                                interactive=True,
                                                visible=field_visible,
                                            )
                                        else:
                                            raise Exception(
                                                f"Unsupported type {type_hint} for field {field_name} in gui term extraction engine settings"
                                            )

                                        term_detail_text_input_index_map[
                                            term_metadata.translate_engine_type
                                        ].append(term_detail_index)
                                        term_detail_index += 1
                                        term_detail_text_inputs.append(field_input)
                                        term_detail_text_input_field_names.append(field_name)
                                        term_detail_text_input_fields.append(field)
                                        visible_when = gui_extra.get("visible_when")
                                        if visible_when:
                                            dependency_field_name = _gui_dependency_field_name(
                                                field_name, visible_when["field"]
                                            )
                                            dependency_input = (
                                                term_detail_visibility_dependency_inputs.get(
                                                    dependency_field_name
                                                )
                                            )
                                            if dependency_input is not None:
                                                term_detail_visibility_dependency_events.append(
                                                    (
                                                        term_metadata.translate_engine_type,
                                                        field_name,
                                                        field,
                                                        dependency_input,
                                                        field_input,
                                                    )
                                                )
                                        term_detail_visibility_dependency_inputs[field_name] = field_input
                                        __gui_term_service_arg_names.append(field_name)
                                        translation_engine_arg_inputs.append(field_input)

                            term_rate_limit_mode = gr.Radio(
                                choices=[
                                    ("RPM (Requests Per Minute)", "RPM"),
                                    ("Concurrent Requests", "Concurrent Threads"),
                                    ("Custom", "Custom"),
                                ],
                                label="Term rate limit mode",
                                value="Custom",
                                interactive=True,
                            )

                            term_rpm_input = gr.Number(
                                label=_("Term RPM (Requests Per Minute)"),
                                value=240,
                                precision=0,
                                minimum=1,
                                maximum=60000,
                                interactive=True,
                                visible=False,
                            )

                            term_concurrent_threads_input = gr.Number(
                                label=_("Term concurrent threads"),
                                value=20,
                                precision=0,
                                minimum=1,
                                maximum=1000,
                                interactive=True,
                                visible=False,
                            )

                            term_custom_qps_input = gr.Number(
                                label=_("Term QPS (Queries Per Second)"),
                                value=(
                                    settings.translation.term_qps
                                    or settings.translation.qps
                                    or 4
                                ),
                                precision=0,
                                minimum=1,
                                maximum=1000,
                                interactive=True,
                                visible=True,
                            )

                            term_custom_pool_max_workers_input = gr.Number(
                                label=_("Term pool max workers"),
                                value=settings.translation.term_pool_max_workers,
                                precision=0,
                                minimum=0,
                                maximum=1000,
                                interactive=True,
                                visible=True,
                            )

                    page_range = gr.Radio(
                        choices=[
                            ("All", "All"),
                            ("First", "First"),
                            ("First 5 pages", "First 5 pages"),
                            ("Range", "Range"),
                        ],
                        label="Pages",
                        value="All",
                    )

                    page_input = gr.Textbox(
                    label=_("Page range (e.g., 1,3,5-10,-5)"),
                    visible=False,
                    interactive=True,
                    placeholder=_("e.g., 1,3,5-10"),
                    )

                    only_include_translated_page = gr.Checkbox(
                    label=_("Only include translated pages in the output PDF."),
                    info=_("Effective only when a page range is specified."),
                    value=settings.pdf.only_include_translated_page,
                    interactive=True,
                    )

                    # PDF Output Options
                    gr.Markdown(_("## PDF Output Options"))
                    compatibility_dual_translate_first_policy = (
                        _enhance_compatibility_control_policy(
                            settings.pdf.enhance_compatibility,
                            settings.pdf.dual_translate_first,
                        )
                    )
                    compatibility_skip_clean_policy = (
                        _enhance_compatibility_control_policy(
                            settings.pdf.enhance_compatibility,
                            settings.pdf.skip_clean,
                        )
                    )
                    compatibility_disable_rich_text_translate_policy = (
                        _enhance_compatibility_control_policy(
                            settings.pdf.enhance_compatibility,
                            settings.pdf.disable_rich_text_translate,
                        )
                    )
                    with gr.Row():
                        no_mono = gr.Checkbox(
                            label=_("Disable monolingual output"),
                            value=settings.pdf.no_mono,
                            interactive=True,
                        )
                        no_dual = gr.Checkbox(
                            label=_("Disable bilingual output"),
                            value=settings.pdf.no_dual,
                            interactive=True,
                        )

                    with gr.Row():
                        dual_translate_first = gr.Checkbox(
                            label=_("Put translated pages first in dual mode"),
                            value=compatibility_dual_translate_first_policy["value"],
                            interactive=compatibility_dual_translate_first_policy[
                                "interactive"
                            ],
                        )
                        use_alternating_pages_dual = gr.Checkbox(
                            label=_("Use alternating pages for dual PDF"),
                            value=settings.pdf.use_alternating_pages_dual,
                            interactive=True,
                        )

                    watermark_output_mode = gr.Radio(
                        choices=[
                            ("Watermarked", "Watermarked"),
                            ("No Watermark", "No Watermark"),
                        ],
                        label="Watermark mode",
                        value="Watermarked"
                        if settings.pdf.watermark_output_mode == "watermarked"
                        else "No Watermark",
                    )

                    # Additional translation options
                    with gr.Accordion(_("Advanced Options"), open=False):
                        prompt = gr.Textbox(
                        label=_("Custom prompt for translation"),
                        value="",
                        visible=False,
                        interactive=True,
                        placeholder=_("Custom prompt for the translator"),
                    )

                        # New Textbox for custom_system_prompt
                        custom_system_prompt_input = gr.Textbox(
                            label=_("Custom System Prompt"),
                            value=settings.translation.custom_system_prompt or "",
                            interactive=True,
                            placeholder=_(
                                "e.g. /no_think You are a professional zh-CN native translator who needs to fluently translate text into zh-CN."
                            ),
                        )

                        min_text_length = gr.Number(
                            label=_("Minimum text length to translate"),
                            value=settings.translation.min_text_length,
                            precision=0,
                            minimum=0,
                            interactive=True,
                        )

                        rpc_doclayout = gr.Textbox(
                            label=_("RPC service for document layout analysis (optional)"),
                            value=settings.translation.rpc_doclayout or "",
                            visible=False,
                            interactive=True,
                            placeholder="http://host:port",
                        )

                        save_auto_extracted_glossary = gr.Checkbox(
                            label=_("save automatically extracted glossary"),
                            value=settings.translation.save_auto_extracted_glossary,
                            interactive=True,
                        )

                        primary_font_family = gr.Dropdown(
                            label=_("Primary font family for translated text"),
                            choices=["Auto", "serif", "sans-serif", "script"],
                            value="Auto"
                            if not settings.translation.primary_font_family
                            else settings.translation.primary_font_family,
                            interactive=True,
                        )

                        glossary_file = gr.File(
                            label=_("Glossary File"),
                            file_count="multiple",
                            file_types=[".csv"],
                            type="binary",
                            visible=True,
                        )
                        require_llm_translator_inputs.append(glossary_file)

                        glossary_table = gr.Dataframe(
                            headers=["source", "target"],
                            datatype=["str", "str"],
                            interactive=False,
                            col_count=(2, "fixed"),
                            visible=False,
                        )
                        require_llm_translator_inputs.append(glossary_table)

                        # PDF options section
                        gr.Markdown(_("### PDF Options"))

                        skip_clean = gr.Checkbox(
                            label=_("Skip clean (maybe improve compatibility)"),
                            value=compatibility_skip_clean_policy["value"],
                            interactive=compatibility_skip_clean_policy["interactive"],
                        )

                        disable_rich_text_translate = gr.Checkbox(
                            label=_(
                                "Disable rich text translation (maybe improve compatibility)"
                            ),
                            value=compatibility_disable_rich_text_translate_policy[
                                "value"
                            ],
                            interactive=compatibility_disable_rich_text_translate_policy[
                                "interactive"
                            ],
                        )

                        enhance_compatibility = gr.Checkbox(
                            label=_(
                                "Enhance compatibility (auto-enables skip_clean and disable_rich_text)"
                            ),
                            value=settings.pdf.enhance_compatibility,
                            interactive=True,
                        )

                        split_short_lines = gr.Checkbox(
                            label=_("Force split short lines into different paragraphs"),
                            value=settings.pdf.split_short_lines,
                            interactive=True,
                        )

                        short_line_split_factor = gr.Slider(
                            label=_("Split threshold factor for short lines"),
                            value=settings.pdf.short_line_split_factor,
                            minimum=0.1,
                            maximum=1.0,
                            step=0.1,
                            interactive=True,
                            visible=settings.pdf.split_short_lines,
                        )

                        translate_table_text = gr.Checkbox(
                            label=_("Translate table text (experimental)"),
                            value=settings.pdf.translate_table_text,
                            interactive=True,
                        )

                        skip_scanned_detection = gr.Checkbox(
                            label=_("Skip scanned detection"),
                            value=settings.pdf.skip_scanned_detection,
                            interactive=True,
                        )

                        ocr_workaround = gr.Checkbox(
                            label=_(
                                "OCR workaround (experimental, will auto enable Skip scanned detection in backend)"
                            ),
                            value=settings.pdf.ocr_workaround,
                            interactive=True,
                        )

                        auto_enable_ocr_workaround = gr.Checkbox(
                            label=_(
                                "Auto enable OCR workaround (enable automatic OCR workaround for heavily scanned documents)"
                            ),
                            value=settings.pdf.auto_enable_ocr_workaround,
                            interactive=True,
                        )

                        max_pages_per_part = gr.Number(
                            label=_(
                                "Maximum pages per part (for auto-split translation, 0 means no limit)"
                            ),
                            value=settings.pdf.max_pages_per_part,
                            precision=0,
                            minimum=0,
                            interactive=True,
                        )

                        formular_font_pattern = gr.Textbox(
                            label=_(
                                "Font pattern to identify formula text (regex, not recommended to change)"
                            ),
                            value=settings.pdf.formular_font_pattern or "",
                            interactive=True,
                            placeholder="e.g., CMMI|CMR",
                        )

                        formular_char_pattern = gr.Textbox(
                            label=_(
                                "Character pattern to identify formula text (regex, not recommended to change)"
                            ),
                            value=settings.pdf.formular_char_pattern or "",
                            interactive=True,
                            placeholder="e.g., [∫∬∭∮∯∰∇∆]",
                        )

                        ignore_cache = gr.Checkbox(
                            label=_("Ignore cache"),
                            value=settings.translation.ignore_cache,
                            interactive=True,
                        )

                        # BabelDOC v0.5.1 new options
                        gr.Markdown(_("#### BabelDOC Advanced Options"))

                        merge_alternating_line_numbers = gr.Checkbox(
                            label=_("Merge alternating line numbers"),
                            info=_(
                                "Handle alternating line numbers and text paragraphs in documents with line numbers"
                            ),
                            value=not settings.pdf.no_merge_alternating_line_numbers,
                            interactive=True,
                        )

                        remove_non_formula_lines = gr.Checkbox(
                            label=_("Remove non-formula lines"),
                            info=_("Remove non-formula lines within paragraph areas"),
                            value=not settings.pdf.no_remove_non_formula_lines,
                            interactive=True,
                        )

                        non_formula_line_iou_threshold = gr.Slider(
                            label=_("Non-formula line IoU threshold"),
                            info=_("IoU threshold for identifying non-formula lines"),
                            value=settings.pdf.non_formula_line_iou_threshold,
                            minimum=0.0,
                            maximum=1.0,
                            step=0.05,
                            interactive=True,
                        )

                        figure_table_protection_threshold = gr.Slider(
                            label=_("Figure/table protection threshold"),
                            info=_(
                                "Protection threshold for figures and tables (lines within figures/tables will not be processed)"
                            ),
                            value=settings.pdf.figure_table_protection_threshold,
                            minimum=0.0,
                            maximum=1.0,
                            step=0.05,
                            interactive=True,
                        )

                        skip_formula_offset_calculation = gr.Checkbox(
                            label=_("Skip formula offset calculation"),
                            info=_("Skip formula offset calculation during processing"),
                            value=settings.pdf.skip_formula_offset_calculation,
                            interactive=True,
                        )

                    # （已移动到 tab_main 中）这里保留设置页底部的“保存设置”和技术说明
                    save_btn = gr.Button(_("Save Settings"), variant="secondary", elem_classes=["save-settings-btn"])

                    tech_details = gr.Markdown(
                        tech_details_string,
                        elem_classes=["secondary-text"],
                    )

        # Sidebar tab switching: 主界面 / 设置界面
        def _show_main_tab():
            return (
                gr.update(variant="primary"),
                gr.update(variant="secondary"),
                gr.update(visible=True),
                gr.update(visible=False),
            )

        def _show_settings_tab():
            return (
                gr.update(variant="secondary"),
                gr.update(variant="primary"),
                gr.update(visible=False),
                gr.update(visible=True),
            )

        btn_main_tab.click(
            _show_main_tab,
            outputs=[btn_main_tab, btn_settings_tab, tab_main, tab_settings],
        )
        btn_settings_tab.click(
            _show_settings_tab,
            outputs=[btn_main_tab, btn_settings_tab, tab_main, tab_settings],
        )

        # Event handlers
        def on_select_filetype(file_type):
            """Update visibility based on selected file type"""
            return (
                gr.update(visible=file_type == "File"),
                gr.update(visible=file_type == "Link"),
            )

        def on_select_page(choice):
            """Update page input visibility based on selection"""
            return gr.update(visible=choice == "Range")

        def on_select_service(service_name, *detail_values):
            """Update service-specific settings visibility"""
            if not detail_text_inputs:
                return
            detail_group_index = detail_text_input_index_map.get(service_name, [])
            detail_field_values = dict(
                zip(detail_text_input_field_names, detail_values, strict=False)
            )
            llm_support = LLM_support_index_map.get(service_name, False)
            siliconflow_free_acknowledgement_visible = service_name == "SiliconFlowFree"
            siliconflow_update = [
                gr.update(visible=siliconflow_free_acknowledgement_visible)
            ]
            return_list = []
            glossary_updates = [
                gr.update(visible=llm_support)
                for i in range(len(require_llm_translator_inputs))
            ]
            if len(detail_text_inputs) == 1:
                return_list = (
                    siliconflow_update
                    + glossary_updates
                    + [gr.update(visible=(0 in detail_group_index))]
                )
            else:
                return_list = (
                    siliconflow_update
                    + glossary_updates
                    + [
                        _gui_field_update(
                            detail_text_input_fields[i],
                            _gui_field_visible(
                                detail_text_input_field_names[i],
                                detail_text_input_fields[i],
                                i in detail_group_index,
                                detail_field_values,
                            ),
                            current_value=detail_field_values.get(
                                detail_text_input_field_names[i]
                            ),
                        )
                        for i in range(len(detail_text_inputs))
                    ]
                )
            return return_list

        def make_detail_dependency_change_handler(service_type, field_name, field):
            def on_dependency_change(dependency_value, service_name, current_value):
                return _gui_field_update(
                    field,
                    _gui_field_visible(
                        field_name,
                        field,
                        service_name == service_type,
                        {
                            _gui_dependency_field_name(
                                field_name,
                                _field_gui_extra(field)["visible_when"]["field"],
                            ): dependency_value
                        },
                    ),
                    current_value=current_value,
                )

            return on_dependency_change

        def on_enhance_compatibility_change(enhance_value):
            """Update compatibility options when enhance_compatibility changes."""
            return _enhance_compatibility_option_updates(enhance_value)

        def on_split_short_lines_change(split_value):
            """Update short_line_split_factor visibility based on split_short_lines value"""
            return gr.update(visible=split_value)

        def on_glossary_file_change(glossary_file):
            if glossary_file is None:
                return gr.update(visible=False)

            glossary_list = []
            for file in glossary_file:
                file_encoding = chardet.detect(file)["encoding"]
                content = file.decode(file_encoding).replace("\r\n", "\n").strip()
                with io.StringIO(content) as f:
                    csvreader = csv.reader(f, delimiter=",", doublequote=True)
                    next(csvreader)  # Skip header
                    for line in csvreader:
                        if line:
                            glossary_list.append(line)
            logger.warning(f"on_glossary_file_delete glossary_list {glossary_list}")
            if not glossary_list:
                glossary_list = ["", "", ""]
            return gr.update(visible=True, value=glossary_list)

        def on_rate_limit_mode_change(mode, service_name):
            """Update rate-limit-specific-settings visibility based on rate_limit_mode value"""
            if service_name == "SiliconFlowFree":
                return [gr.update(visible=False)] * 4  # Hide all options

            rpm_visible = mode == "RPM"
            threads_visible = mode == "Concurrent Threads"
            custom_visible = mode == "Custom"

            return [
                gr.update(visible=rpm_visible),
                gr.update(visible=threads_visible),
                gr.update(visible=custom_visible),
                gr.update(visible=custom_visible),
            ]

        def on_enable_auto_term_extraction_change(enabled: bool):
            """Update term disabled info visibility based on auto term extraction toggle"""
            return gr.update(visible=not enabled)

        def on_term_rate_limit_mode_change(mode: str):
            """Update term rate-limit controls visibility based on mode"""
            rpm_visible = mode == "RPM"
            threads_visible = mode == "Concurrent Threads"
            custom_visible = mode == "Custom"
            return [
                gr.update(visible=rpm_visible),
                gr.update(visible=threads_visible),
                gr.update(visible=custom_visible),
                gr.update(visible=custom_visible),
            ]

        def on_term_service_change(term_service_name: str, *term_detail_values):
            """Update term engine-specific settings visibility"""
            if not term_detail_text_inputs:
                return
            detail_group_index = term_detail_text_input_index_map.get(
                term_service_name, []
            )
            term_detail_field_values = dict(
                zip(
                    term_detail_text_input_field_names,
                    term_detail_values,
                    strict=False,
                )
            )
            if len(term_detail_text_inputs) == 1:
                return [gr.update(visible=(0 in detail_group_index))]
            return [
                _gui_field_update(
                    term_detail_text_input_fields[i],
                    _gui_field_visible(
                        term_detail_text_input_field_names[i],
                        term_detail_text_input_fields[i],
                        i in detail_group_index,
                        term_detail_field_values,
                    ),
                    current_value=term_detail_field_values.get(
                        term_detail_text_input_field_names[i]
                    ),
                )
                for i in range(len(term_detail_text_inputs))
            ]

        def on_service_change_with_rate_limit(mode, service_name, *detail_values):
            """Expand original on_select_service with rate-limit-UI updated"""
            original_updates = on_select_service(service_name, *detail_values)

            rate_limit_visible = service_name != "SiliconFlowFree"

            detailed_visible = [gr.update(visible=False)] * 4

            if rate_limit_visible:
                detailed_visible = on_rate_limit_mode_change(mode, service_name)

            # Add updates of rate-limit-UI
            rate_limit_updates = [
                gr.update(visible=rate_limit_visible),
            ]

            return original_updates + rate_limit_updates + detailed_visible

        def on_lang_selector_change(lang):
            _save_gui_language_settings(lang)

        # UI language change handler

        lang_selector.change(on_lang_selector_change, lang_selector)

        # State for managing translation tasks
        state = gr.State(
            {
                "session_id": None,
                "current_task": None,
                "results": {},
                "file_order": [],
                "display_map": {},
                "parent_map": {},
                "uploaded_files": [],
            }
        )

        file_input.upload(
            on_file_upload,
            inputs=[file_input, state],
            outputs=[result_file_selector, state, uploaded_files_view],
        )

        # Handle per-file removal (the small X on each row in the File(s) list)
        file_input.change(
            on_file_input_change,
            inputs=[file_input, state, result_file_selector],
            outputs=[
                result_file_selector,
                state,
                uploaded_files_view,
                preview,
                output_file_mono,
                output_file_dual,
                output_file_glossary,
                output_file_mono,  # visibility
                output_file_dual,  # visibility
                output_file_glossary,  # visibility
            ],
        )

        # Handle file clear/delete event
        file_input.clear(
            on_file_clear,
            inputs=[file_input, state],
            outputs=[
                result_file_selector,
                state,
                uploaded_files_view,
                preview,  # Clear preview
                output_file_mono,  # Clear mono download
                output_file_dual,  # Clear dual download
                output_file_glossary,  # Clear glossary download
                output_file_mono,  # Hide mono button visibility
                output_file_dual,  # Hide dual button visibility
                output_file_glossary,  # Hide glossary button visibility
            ],
        )

        # Event bindings
        file_type.select(
            on_select_filetype,
            file_type,
            [file_input, link_input],
        )

        page_range.select(
            on_select_page,
            page_range,
            page_input,
        )

        on_select_service_outputs = (
            [siliconflow_free_acknowledgement]
            + require_llm_translator_inputs
            + detail_text_inputs
        )

        service.select(
            on_service_change_with_rate_limit,
            [rate_limit_mode, service] + detail_text_inputs,
            outputs=(
                on_select_service_outputs
                if len(on_select_service_outputs) > 0
                else None
            )
            + [
                rate_limit_mode,
                rpm_input,
                concurrent_threads_input,
                custom_qps_input,
                custom_pool_max_workers_input,
            ],
        )

        rate_limit_mode.change(
            on_rate_limit_mode_change,
            inputs=[rate_limit_mode, service],
            outputs=[
                rpm_input,
                concurrent_threads_input,
                custom_qps_input,
                custom_pool_max_workers_input,
            ],
        )

        glossary_file.change(
            on_glossary_file_change,
            glossary_file,
            outputs=glossary_table,
        )

        # Add event handler for enhance_compatibility
        enhance_compatibility.change(
            on_enhance_compatibility_change,
            enhance_compatibility,
            [skip_clean, disable_rich_text_translate, dual_translate_first],
        )

        # Add event handler for split_short_lines
        split_short_lines.change(
            on_split_short_lines_change,
            split_short_lines,
            short_line_split_factor,
        )

        # Auto term extraction toggle handlers
        enable_auto_term_extraction.change(
            on_enable_auto_term_extraction_change,
            enable_auto_term_extraction,
            term_disabled_info,
        )

        # Term rate limit handlers
        term_rate_limit_mode.change(
            on_term_rate_limit_mode_change,
            term_rate_limit_mode,
            [
                term_rpm_input,
                term_concurrent_threads_input,
                term_custom_qps_input,
                term_custom_pool_max_workers_input,
            ],
        )

        # Term service change handler
        term_service.change(
            on_term_service_change,
            [term_service] + term_detail_text_inputs,
            outputs=(
                term_detail_text_inputs if len(term_detail_text_inputs) > 0 else None
            ),
        )

        for (
            service_type,
            field_name,
            field,
            dependency_input,
            dependent_input,
        ) in detail_visibility_dependency_events:
            dependency_input.change(
                make_detail_dependency_change_handler(service_type, field_name, field),
                [
                    dependency_input,
                    service,
                    dependent_input,
                ],
                dependent_input,
            )

        for (
            service_type,
            field_name,
            field,
            dependency_input,
            dependent_input,
        ) in term_detail_visibility_dependency_events:
            dependency_input.change(
                make_detail_dependency_change_handler(service_type, field_name, field),
                [
                    dependency_input,
                    term_service,
                    dependent_input,
                ],
                dependent_input,
            )

        # UI setting controls list (shared by translate_btn and save_btn)
        ui_setting_controls = [
            service,
            lang_from,
            lang_to,
            page_range,
            page_input,
            # PDF Output Options
            no_mono,
            no_dual,
            dual_translate_first,
            use_alternating_pages_dual,
            watermark_output_mode,
            # Rate Limit Options
            rate_limit_mode,
            rpm_input,
            concurrent_threads_input,
            custom_qps_input,
            custom_pool_max_workers_input,
            # Advanced Options
            prompt,
            min_text_length,
            rpc_doclayout,
            custom_system_prompt_input,
            glossary_file,
            save_auto_extracted_glossary,
            # New advanced translation options
            enable_auto_term_extraction,
            primary_font_family,
            skip_clean,
            disable_rich_text_translate,
            enhance_compatibility,
            split_short_lines,
            short_line_split_factor,
            translate_table_text,
            skip_scanned_detection,
            max_pages_per_part,
            formular_font_pattern,
            formular_char_pattern,
            ignore_cache,
            state,
            ocr_workaround,
            auto_enable_ocr_workaround,
            only_include_translated_page,
            # BabelDOC v0.5.1 new options
            merge_alternating_line_numbers,
            remove_non_formula_lines,
            non_formula_line_iou_threshold,
            figure_table_protection_threshold,
            skip_formula_offset_calculation,
            # Term extraction engine options
            term_service,
            term_rate_limit_mode,
            term_rpm_input,
            term_concurrent_threads_input,
            term_custom_qps_input,
            term_custom_pool_max_workers_input,
            *translation_engine_arg_inputs,
            # any UI components that are used by translate/save should be listed above!
            # Extra UI components to be updated on load (not used by translate/save)
            siliconflow_free_acknowledgement,
            glossary_table,
            term_disabled_info,
        ]

        # Language swap button click handler
        swap_lang_btn.click(
            swap_languages,
            inputs=[lang_from, lang_to],
            outputs=[lang_from, lang_to],
        )

        # Translation button click handler
        translate_btn.click(
            translate_files,  # MODIFIED function name
            inputs=[
                file_type,
                file_input,
                link_input,
                *ui_setting_controls,
            ],
            outputs=[
                output_file_mono,  # Mono PDF file
                preview,  # Preview
                output_file_dual,  # Dual PDF file
                output_file_glossary,
                output_file_mono,  # Visibility of mono output
                output_file_dual,  # Visibility of dual output
                output_file_glossary,
                output_title,  # Visibility of output title
                result_file_selector,  # Result selector
                result_file_selector,  # Visibility
                output_file_zip,  # Visibility
                output_file_zip,  # Zip File
                output_file_zip_mono,  # Visibility
                output_file_zip_mono,  # File
                output_file_zip_dual,  # Visibility
                output_file_zip_dual,  # File
                output_file_zip_glossary,  # Visibility
                output_file_zip_glossary,  # File
                uploaded_files_view,  # Uploaded files view
            ],
            show_progress_on=[preview],
        )

        # ADDED: Handle result selector change
        def safe_update_preview(selected_label, state):
            """
            Wrapper for update_preview that ensures selected_label is valid before processing.
            Also returns an update for result_file_selector if the value needs to be corrected.
            """
            # Validate selected_label is in choices
            if not state or "display_map" not in state:
                choices = []
            else:
                choices = list(state.get("display_map", {}).keys())
            
            # If selected_label is not in choices, reset it
            if selected_label and selected_label not in choices:
                # Reset to first available choice or None
                corrected_label = choices[0] if choices else None
                # Return preview update + selector update
                preview_results = update_preview(corrected_label, state) if corrected_label else (
                    None, None, None, None,
                    gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)
                )
                return (
                    *preview_results,
                    gr.update(choices=choices, value=corrected_label, visible=bool(choices)),  # Fix selector
                )
            else:
                # Normal case: selected_label is valid
                preview_results = update_preview(selected_label, state)
                return (
                    *preview_results,
                    gr.update(),  # No change to selector
                )

        result_file_selector.change(
            safe_update_preview,
            inputs=[result_file_selector, state],
            outputs=[
                output_file_mono,  # Mono PDF file
                preview,  # Preview
                output_file_dual,  # Dual PDF file
                output_file_glossary,
                output_file_mono,  # Visibility of mono output
                output_file_dual,  # Visibility of dual output
                output_file_glossary,
                result_file_selector,  # Fix selector if value is invalid
            ],
        )

        # Cancel button click handler
        cancel_btn.click(
            stop_translate_file,
            inputs=[state],
        )

        # Save button click handler
        save_btn.click(
            save_config,
            inputs=ui_setting_controls,
        )

        def load_saved_config_to_ui(state):
            """Reload all settings from config and update UI components."""
            try:
                fresh_settings = settings
                update_current_languages(settings.gui_settings.ui_lang)

                updates: list = []

                # Determine selected service by cli flag
                selected_service = None
                for metadata in TRANSLATION_ENGINE_METADATA:
                    if getattr(fresh_settings, metadata.cli_flag_name, False):
                        selected_service = metadata.translate_engine_type
                        break
                if not selected_service:
                    selected_service = available_services[0]
                llm_support = LLM_support_index_map.get(selected_service, False)

                # Follow the EXACT order of ui_setting_controls
                # service
                updates.append(gr.update(value=selected_service))
                # lang_from, lang_to
                loaded_lang_from = rev_lang_map.get(
                    fresh_settings.translation.lang_in, "English"
                )
                loaded_lang_to_code = fresh_settings.translation.lang_out
                loaded_lang_to = next(
                    (k for k, v in lang_map.items() if v == loaded_lang_to_code),
                    "Simplified Chinese",
                )
                updates.append(gr.update(value=loaded_lang_from))
                updates.append(gr.update(value=loaded_lang_to))
                # page_range, page_input
                pages_setting = fresh_settings.pdf.pages
                if pages_setting is None or pages_setting == "":
                    updates.append(gr.update(value="All"))
                    updates.append(gr.update(value="", visible=False))
                else:
                    updates.append(gr.update(value="Range"))
                    updates.append(gr.update(value=str(pages_setting), visible=True))
                # PDF Output Options
                (
                    skip_clean_update,
                    disable_rich_text_translate_update,
                    dual_translate_first_update,
                ) = _enhance_compatibility_config_updates(
                    fresh_settings.pdf.enhance_compatibility,
                    fresh_settings.pdf.skip_clean,
                    fresh_settings.pdf.disable_rich_text_translate,
                    fresh_settings.pdf.dual_translate_first,
                )
                updates.append(gr.update(value=fresh_settings.pdf.no_mono))
                updates.append(gr.update(value=fresh_settings.pdf.no_dual))
                updates.append(dual_translate_first_update)
                updates.append(
                    gr.update(value=fresh_settings.pdf.use_alternating_pages_dual)
                )
                watermark_value = (
                    "Watermarked"
                    if fresh_settings.pdf.watermark_output_mode == "watermarked"
                    else "No Watermark"
                )
                updates.append(gr.update(value=watermark_value))
                # Rate Limit Options
                rate_limit_visible = selected_service != "SiliconFlowFree"
                updates.append(gr.update(value="Custom", visible=rate_limit_visible))
                updates.append(gr.update(visible=False))  # rpm_input
                updates.append(gr.update(visible=False))  # concurrent_threads_input
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.qps or 4,
                        visible=rate_limit_visible,
                    )
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.pool_max_workers,
                        visible=rate_limit_visible,
                    )
                )
                # Advanced Options
                updates.append(gr.update(value=""))  # prompt
                updates.append(
                    gr.update(value=fresh_settings.translation.min_text_length)
                )
                updates.append(
                    gr.update(value=fresh_settings.translation.rpc_doclayout or "")
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.custom_system_prompt or ""
                    )
                )
                updates.append(
                    gr.update(visible=llm_support)
                )  # glossary_file visibility
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.save_auto_extracted_glossary
                    )
                )
                # enable_auto_term_extraction is the inverse of no_auto_extract_glossary
                updates.append(
                    gr.update(
                        value=not fresh_settings.translation.no_auto_extract_glossary
                    )
                )
                primary_font_display = (
                    "Auto"
                    if not fresh_settings.translation.primary_font_family
                    else fresh_settings.translation.primary_font_family
                )
                updates.append(gr.update(value=primary_font_display))
                updates.append(skip_clean_update)
                updates.append(disable_rich_text_translate_update)
                updates.append(
                    gr.update(value=fresh_settings.pdf.enhance_compatibility)
                )
                updates.append(gr.update(value=fresh_settings.pdf.split_short_lines))
                updates.append(
                    gr.update(
                        value=fresh_settings.pdf.short_line_split_factor,
                        visible=fresh_settings.pdf.split_short_lines,
                    )
                )
                updates.append(gr.update(value=fresh_settings.pdf.translate_table_text))
                updates.append(
                    gr.update(value=fresh_settings.pdf.skip_scanned_detection)
                )
                updates.append(gr.update(value=fresh_settings.pdf.max_pages_per_part))
                updates.append(
                    gr.update(value=fresh_settings.pdf.formular_font_pattern or "")
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.formular_char_pattern or "")
                )
                updates.append(gr.update(value=fresh_settings.translation.ignore_cache))
                updates.append(state)  # state, keep unchanged
                updates.append(gr.update(value=fresh_settings.pdf.ocr_workaround))
                updates.append(
                    gr.update(value=fresh_settings.pdf.auto_enable_ocr_workaround)
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.only_include_translated_page)
                )
                # BabelDOC
                updates.append(
                    gr.update(
                        value=not fresh_settings.pdf.no_merge_alternating_line_numbers
                    )
                )
                updates.append(
                    gr.update(value=not fresh_settings.pdf.no_remove_non_formula_lines)
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.non_formula_line_iou_threshold)
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.pdf.figure_table_protection_threshold
                    )
                )
                updates.append(
                    gr.update(value=fresh_settings.pdf.skip_formula_offset_calculation)
                )
                # Term extraction engine basic settings
                term_engine_enabled = (
                    not fresh_settings.translation.no_auto_extract_glossary
                )
                selected_term_service = "Follow main translation engine"
                for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
                    term_flag_name = f"term_{term_metadata.cli_flag_name}"
                    if getattr(fresh_settings, term_flag_name, False):
                        selected_term_service = term_metadata.translate_engine_type
                        break
                updates.append(gr.update(value=selected_term_service))
                # Term rate limit: use Custom mode by default
                updates.append(gr.update(value="Custom"))
                updates.append(gr.update(visible=False))  # term_rpm_input
                updates.append(
                    gr.update(visible=False)
                )  # term_concurrent_threads_input
                updates.append(
                    gr.update(
                        value=(
                            fresh_settings.translation.term_qps
                            or fresh_settings.translation.qps
                            or 4
                        ),
                        visible=True,
                    )
                )
                updates.append(
                    gr.update(
                        value=fresh_settings.translation.term_pool_max_workers,
                        visible=True,
                    )
                )
                # Translation engine detail fields (ordered)
                disable_sensitive_gui = (
                    fresh_settings.gui_settings.disable_gui_sensitive_input
                )
                for service_name in available_services:
                    metadata = TRANSLATION_ENGINE_METADATA_MAP[service_name]
                    if not metadata.cli_detail_field_name:
                        continue
                    detail_settings = getattr(
                        fresh_settings, metadata.cli_detail_field_name
                    )
                    for (
                        field_name,
                        field,
                    ) in metadata.setting_model_type.model_fields.items():
                        if disable_sensitive_gui:
                            if field_name in GUI_SENSITIVE_FIELDS:
                                continue
                            if field_name in GUI_PASSWORD_FIELDS:
                                continue
                        if field.default_factory:
                            continue
                        if (
                            field_name == "translate_engine_type"
                            or field_name == "support_llm"
                        ):
                            continue
                        value = getattr(detail_settings, field_name)
                        field_values = {
                            name: getattr(detail_settings, name)
                            for name in metadata.setting_model_type.model_fields
                        }
                        visible = _gui_field_visible(
                            field_name,
                            field,
                            metadata.translate_engine_type == selected_service,
                            field_values,
                        )
                        value = _gui_field_value(field, value)
                        updates.append(gr.update(value=value, visible=visible))

                # Term extraction engine detail fields (ordered)
                for term_metadata in TERM_EXTRACTION_ENGINE_METADATA:
                    if not term_metadata.cli_detail_field_name:
                        continue
                    term_detail_field_name = (
                        f"term_{term_metadata.cli_detail_field_name}"
                    )
                    term_detail_settings = getattr(
                        fresh_settings, term_detail_field_name
                    )
                    for (
                        field_name,
                        field,
                    ) in term_metadata.term_setting_model_type.model_fields.items():
                        if field.default_factory:
                            continue
                        if field_name in ("translate_engine_type", "support_llm"):
                            continue
                        base_field_name = field_name
                        if base_field_name.startswith("term_"):
                            base_name = base_field_name[len("term_") :]
                        else:
                            base_name = base_field_name
                        if disable_sensitive_gui:
                            if base_name in GUI_SENSITIVE_FIELDS:
                                continue
                            if base_name in GUI_PASSWORD_FIELDS:
                                continue
                        value = getattr(term_detail_settings, field_name)
                        term_field_values = {
                            name: getattr(term_detail_settings, name)
                            for name in term_metadata.term_setting_model_type.model_fields
                        }
                        visible = _gui_field_visible(
                            field_name,
                            field,
                            term_metadata.translate_engine_type == selected_term_service,
                            term_field_values,
                        )
                        value = _gui_field_value(field, value)
                        updates.append(gr.update(value=value, visible=visible))

                # Extra UI components at the end of ui_setting_controls
                siliconflow_free_ack_visible = selected_service == "SiliconFlowFree"
                updates.append(gr.update(visible=siliconflow_free_ack_visible))
                updates.append(
                    gr.update(visible=llm_support)
                )  # glossary_table visibility
                updates.append(
                    gr.update(
                        visible=fresh_settings.translation.no_auto_extract_glossary
                    )
                )  # term_disabled_info visibility

                return updates
            except Exception as e:
                logger.warning(f"Could not reload config on page load: {e}")
                return [None] * len(ui_setting_controls)

        # Use ui_setting_controls as outputs for page load
        demo.load(load_saved_config_to_ui, inputs=[state], outputs=ui_setting_controls)

        # Initialize result_file_selector on page load to ensure choices and value are consistent
        def init_result_file_selector(state):
            """Initialize result_file_selector with empty choices and None value on page load."""
            # Always start with empty state to avoid Gradio validation errors
            # The actual choices will be populated when files are uploaded
            try:
                if not state or not state.get("display_map"):
                    return gr.update(choices=[], value=None, visible=False)
                choices = list(state.get("display_map", {}).keys())
                if choices:
                    # Ensure the value is in choices
                    current_value = None
                    # Try to preserve current selection if valid
                    if state.get("display_map"):
                        # Use first choice as default
                        current_value = choices[0]
                    return gr.update(choices=choices, value=current_value, visible=True)
                else:
                    return gr.update(choices=[], value=None, visible=False)
            except Exception as e:
                logger.warning(f"Error initializing result_file_selector: {e}")
                # Fallback: always return safe empty state
                return gr.update(choices=[], value=None, visible=False)

        # Initialize result_file_selector FIRST on page load (before any other load handlers)
        # This ensures it's always in a valid state
        demo.load(
            init_result_file_selector,
            inputs=[state],
            outputs=[result_file_selector],
        )

        # JavaScript: 动态调整 PDF canvas 缩放，确保完全适配容器高度
        # 使用兼容性更好的语法，避免 ES6 特性导致解析错误
        demo.load(
            None,
            None,
            None,
            js="""
            (function() {
                'use strict';

            // Fix PDF worker URL - replace jsdelivr CDN with GitHub raw URL
            function fixPDFWorkerURL() {
                try {
                    var originalWorkerSrc = 'https://cdn.jsdelivr.net/gh/freddyaboulton/gradio-pdf@main/pdf.worker.min.mjs';
                    var newWorkerSrc = 'https://raw.githubusercontent.com/freddyaboulton/gradio-pdf/main/pdf.worker.min.mjs';
                    
                    // Method 1: Override PDF.js GlobalWorkerOptions if available
                    if (typeof window !== 'undefined') {
                        if (window.pdfjsLib && window.pdfjsLib.GlobalWorkerOptions) {
                            window.pdfjsLib.GlobalWorkerOptions.workerSrc = newWorkerSrc;
                        }
                        
                        // Method 2: Use MutationObserver to intercept script execution
                        var observer = new MutationObserver(function(mutations) {
                            mutations.forEach(function(mutation) {
                                mutation.addedNodes.forEach(function(node) {
                                    if (node.nodeType === 1) { // Element node
                                        if (node.tagName === 'SCRIPT') {
                                            if (node.textContent && node.textContent.indexOf(originalWorkerSrc) !== -1) {
                                                var escapedUrl = originalWorkerSrc.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
                                                node.textContent = node.textContent.replace(new RegExp(escapedUrl, 'g'), newWorkerSrc);
                                            }
                                        }
                                        // Also check for inline scripts in the node
                                        var scripts = node.querySelectorAll && node.querySelectorAll('script');
                                        if (scripts) {
                                            for (var i = 0; i < scripts.length; i++) {
                                                if (scripts[i].textContent && scripts[i].textContent.indexOf(originalWorkerSrc) !== -1) {
                                                    var escapedUrl2 = originalWorkerSrc.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
                                                    scripts[i].textContent = scripts[i].textContent.replace(new RegExp(escapedUrl2, 'g'), newWorkerSrc);
                                                }
                                            }
                                        }
                                    }
                                });
                            });
                        });
                        observer.observe(document.body || document.documentElement, {
                            childList: true,
                            subtree: true
                        });
                        
                        // Method 3: Intercept fetch requests for the worker file
                        var originalFetch = window.fetch;
                        window.fetch = function() {
                            var url = arguments[0];
                            if (typeof url === 'string' && url.indexOf(originalWorkerSrc) !== -1) {
                                arguments[0] = url.replace(originalWorkerSrc, newWorkerSrc);
                            }
                            return originalFetch.apply(this, arguments);
                        };
                    }
                } catch (e) {
                    console.warn('Failed to fix PDF worker URL:', e);
                }
            }
            
            // Run fix immediately and also on DOM ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', fixPDFWorkerURL);
            } else {
                fixPDFWorkerURL();
            }

            function adjustPDFCanvasScale() {
                    var previewContainers = document.querySelectorAll('.pdf-preview-fixed');
                    for (var i = 0; i < previewContainers.length; i++) {
                        var container = previewContainers[i];
                        var canvas = container.querySelector('canvas');
                    if (!canvas) {
                            continue;
                    }
                    
                        var containerRect = container.getBoundingClientRect();
                        var containerHeight = containerRect.height - 24;
                        var containerWidth = containerRect.width - 24;
                        
                        var canvasWidth = canvas.naturalWidth || canvas.width || canvas.offsetWidth;
                        var canvasHeight = canvas.naturalHeight || canvas.height || canvas.offsetHeight;
                    
                        if (!canvasWidth || !canvasHeight) {
                            continue;
                        }
                        
                        var scaleHeight = containerHeight / canvasHeight;
                        var scaleWidth = containerWidth / canvasWidth;
                        var scale = Math.min(scaleHeight, scaleWidth);
                        
                        var scaledWidth = canvasWidth * scale;
                        var scaledHeight = canvasHeight * scale;
                    
                    canvas.style.width = scaledWidth + 'px';
                    canvas.style.height = scaledHeight + 'px';
                    canvas.style.maxWidth = '100%';
                    canvas.style.maxHeight = '100%';
                    
                    // 深色模式下：为 canvas 添加包装器，使背景大小精确匹配 PDF 内容
                    var bodyStyle = window.getComputedStyle(document.body);
                    var bgColor = bodyStyle.backgroundColor;
                    var isDarkMode = document.body.classList.contains('dark') || 
                                     document.documentElement.getAttribute('data-theme') === 'dark' ||
                                     document.documentElement.classList.contains('dark') ||
                                     (bgColor && (bgColor.indexOf('rgb(30') === 0 || 
                                                  bgColor.indexOf('rgb(31') === 0 || 
                                                  bgColor.indexOf('rgb(32') === 0 ||
                                                  bgColor.indexOf('#1') === 0 ||
                                                  bgColor.indexOf('#2') === 0));
                    
                    if (isDarkMode) {
                        // 检查是否已有包装器
                        var wrapper = canvas.parentElement;
                        var needsWrapper = !wrapper.classList || !wrapper.classList.contains('pdf-canvas-wrapper');
                        
                        if (needsWrapper && wrapper !== container) {
                            // 创建包装器
                            var newWrapper = document.createElement('div');
                            newWrapper.className = 'pdf-canvas-wrapper';
                            wrapper.insertBefore(newWrapper, canvas);
                            newWrapper.appendChild(canvas);
                            wrapper = newWrapper;
                        } else if (wrapper === container || !wrapper.classList.contains('pdf-canvas-wrapper')) {
                            // 如果 canvas 直接是 container 的子元素，创建包装器
                            var newWrapper = document.createElement('div');
                            newWrapper.className = 'pdf-canvas-wrapper';
                            container.insertBefore(newWrapper, canvas);
                            newWrapper.appendChild(canvas);
                            wrapper = newWrapper;
                        }
                        
                        // 设置包装器大小，稍微大一点以包含 padding 和阴影
                        if (wrapper && wrapper.classList.contains('pdf-canvas-wrapper')) {
                            wrapper.style.width = (scaledWidth + 16) + 'px';  // 8px padding * 2
                            wrapper.style.height = (scaledHeight + 16) + 'px';
                            wrapper.style.maxWidth = '100%';
                            wrapper.style.maxHeight = '100%';
                            wrapper.style.margin = '0 auto';
                            wrapper.style.display = 'inline-block';
                        }
                        
                        // 确保 canvas 本身没有额外的背景
                        canvas.style.background = 'transparent';
                    } else {
                        // 浅色模式下移除包装器样式
                        canvas.style.background = '#ffffff';
                    }
                    }
                }
                
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', adjustPDFCanvasScale);
            } else {
                adjustPDFCanvasScale();
            }
            
                var observer = new MutationObserver(adjustPDFCanvasScale);
            observer.observe(document.body, { childList: true, subtree: true });
            
            window.addEventListener('resize', adjustPDFCanvasScale);
            })();
            """
        )


def parse_user_passwd(file_path: str, welcome_page: str) -> tuple[list, str]:
    """
    This function parses a user password file.

    Inputs:
        - file_path: The path to the file

    Returns:
        - A tuple containing the user list and HTML
    """
    content = ""
    tuple_list = None
    if welcome_page:
        try:
            path = Path(welcome_page)
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"Error: File '{welcome_page}' not found.")
    if file_path:
        try:
            path = Path(file_path)
            tuple_list = [
                tuple(line.strip().split(","))
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except FileNotFoundError:
            tuple_list = None
    return tuple_list, content


def setup_gui(
    share: bool = False,
    auth_file: str | None = None,
    welcome_page: str | None = None,
    server_port=7860,
    inbrowser: bool = True,
) -> None:
    """
    This function sets up the GUI for the application.

    Inputs:
        - share: Whether to share the GUI
        - auth_file: The authentication file
        - server_port: The port to run the server on

    Returns:
        - None
    """

    user_list = None
    html = None

    user_list, html = parse_user_passwd(auth_file, welcome_page)

    if not auth_file or not user_list:
        try:
            demo.launch(
                server_name="0.0.0.0",
                debug=True,
                inbrowser=inbrowser,
                share=share,
                server_port=server_port,
                allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
            )
        except Exception:
            print(
                "Error launching GUI using 0.0.0.0.\nThis may be caused by global mode of proxy software."
            )
            try:
                demo.launch(
                    server_name="127.0.0.1",
                    debug=True,
                    inbrowser=inbrowser,
                    share=share,
                    server_port=server_port,
                    allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
                )
            except Exception:
                print(
                    "Error launching GUI using 127.0.0.1.\nThis may be caused by global mode of proxy software."
                )
                demo.launch(
                    debug=True,
                    inbrowser=inbrowser,
                    share=True,
                    server_port=server_port,
                    allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
                )
    else:
        try:
            demo.launch(
                server_name="0.0.0.0",
                debug=True,
                inbrowser=inbrowser,
                share=share,
                auth=user_list,
                auth_message=html,
                server_port=server_port,
                allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
            )
        except Exception:
            print(
                "Error launching GUI using 0.0.0.0.\nThis may be caused by global mode of proxy software."
            )
            try:
                demo.launch(
                    server_name="127.0.0.1",
                    debug=True,
                    inbrowser=inbrowser,
                    share=share,
                    auth=user_list,
                    auth_message=html,
                    server_port=server_port,
                    allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
                )
            except Exception:
                print(
                    "Error launching GUI using 127.0.0.1.\nThis may be caused by global mode of proxy software."
                )
                demo.launch(
                    debug=True,
                    inbrowser=inbrowser,
                    share=True,
                    auth=user_list,
                    auth_message=html,
                    server_port=server_port,
                    allowed_paths=[str(p) for p in pdf_preview_allowed_paths],
                )


# For auto-reloading while developing
if __name__ == "__main__":
    from rich.logging import RichHandler

    # disable httpx, openai, httpcore, http11 logs
    logging.getLogger("httpx").setLevel("CRITICAL")
    logging.getLogger("httpx").propagate = False
    logging.getLogger("openai").setLevel("CRITICAL")
    logging.getLogger("openai").propagate = False
    logging.getLogger("httpcore").setLevel("CRITICAL")
    logging.getLogger("httpcore").propagate = False
    logging.getLogger("http11").setLevel("CRITICAL")
    logging.getLogger("http11").propagate = False
    logging.basicConfig(level=logging.INFO, handlers=[RichHandler()])
    setup_gui(inbrowser=False)
