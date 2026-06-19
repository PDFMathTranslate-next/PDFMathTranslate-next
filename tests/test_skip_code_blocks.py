from types import SimpleNamespace

import pytest
from pdf2zh_next import high_level as high_level_module
from pdf2zh_next.config.cli_env_model import CLIEnvSettingsModel
from pdf2zh_next.translator import base_translator as base_translator_module
from pdf2zh_next.translator.base_translator import BaseTranslator
from pdf2zh_next.translator.base_translator import _classify_code_block
from pdf2zh_next.translator.base_translator import _looks_like_code_block


class FakeCache:
    def __init__(self, *args, **kwargs):
        self.get_call_count = 0
        self.set_call_count = 0

    def get(self, text):
        self.get_call_count += 1
        return None

    def set(self, text, translation):
        self.set_call_count += 1


class FakeRateLimiter:
    def __init__(self):
        self.wait_call_count = 0

    def wait(self, rate_limit_params=None):
        self.wait_call_count += 1


class FakeParagraphTracker:
    def __init__(self):
        self.output = None

    def set_output(self, text):
        self.output = text


class DummyTranslator(BaseTranslator):
    name = "dummy"
    model = "dummy"

    def __init__(self, settings, rate_limiter):
        self.do_translate_call_count = 0
        self.do_llm_translate_call_count = 0
        self.llm_response = None
        self.llm_exception = None
        super().__init__(settings, rate_limiter)

    def do_translate(self, text, rate_limit_params=None):
        self.do_translate_call_count += 1
        return f"translated:{text}"

    def do_llm_translate(self, text, rate_limit_params=None):
        self.do_llm_translate_call_count += 1
        if self.llm_exception:
            raise self.llm_exception
        if self.llm_response is not None:
            return self.llm_response
        return f"llm:{text}"


def build_translator(
    monkeypatch,
    skip_code_blocks=False,
    skip_code_blocks_llm=False,
    llm_response=None,
    llm_exception=None,
):
    fake_cache = FakeCache()

    def fake_cache_factory(*_args, **_kwargs):
        return fake_cache

    monkeypatch.setattr(
        base_translator_module,
        "TranslationCache",
        fake_cache_factory,
    )
    settings = CLIEnvSettingsModel(
        siliconflowfree=True,
        pdf={
            "skip_code_blocks": skip_code_blocks,
            "skip_code_blocks_llm": skip_code_blocks_llm,
        },
    ).to_settings_model()
    rate_limiter = FakeRateLimiter()
    translator = DummyTranslator(settings, rate_limiter)
    translator.llm_response = llm_response
    translator.llm_exception = llm_exception
    return translator, rate_limiter, fake_cache


def build_babeldoc_prompt(text):
    return f"""You are a professional zh-CN native translator who needs to fluently translate text into zh-CN.

Follow all rules strictly.

## Rules

1. Keep the structure exactly unchanged: do NOT add/remove/reorder any tags, placeholders, or tokens.
2. Keep all tags unchanged (e.g., <style>, <b>, </style>).
   - Translate human-readable text inside tags.
   - Do NOT translate text inside <code>...</code>.
3. Do NOT translate or alter placeholders: {{v1}}, {{name}}, %s, %d, [[...]], %%...%%.

## Output

Output ONLY the translated zh-CN text. No explanations, no backticks, no extra text.

Now translate the following text:

{text}"""


def test_code_block_detector_matches_markdown_fence():
    text = "```python\nprint('hello')\n```"

    assert _looks_like_code_block(text) is True


def test_code_block_detector_matches_obvious_python_block():
    text = "def add(x, y):\n    return x + y\n\nprint(add(1, 2))"

    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "def compute_total(items):\n"
        "    total = 0\n"
        "    for item in items:\n"
        "        total += item.price\n"
        "    return total",
        "export function formatName(user) {\n"
        '  const name = user.name ?? "guest";\n'
        "  return name.trim();\n"
        "}",
        "type User = { id: string; active: boolean };\n"
        'const user: User = { id: "u1", active: true };\n'
        "console.log(user.id);",
        "public class Worker {\n  public int run() {\n    return 1;\n  }\n}",
        "class Worker {\n  fun run(): Int {\n    return 1\n  }\n}",
        "#include <vector>\n"
        "int main() {\n"
        "  std::vector<int> values{1, 2, 3};\n"
        "  return values.size();\n"
        "}",
        "namespace Demo {\npublic class Worker {\n  public static void Main() {}\n}\n}",
        'func main() {\n    fmt.Println("ready")\n}',
        'fn main() {\n    let value = Some(3);\n    println!("{:?}", value);\n}',
        "<?php\nrequire 'vendor/autoload.php';\necho $app->run();",
        "class Greeter\n  def call\n    puts 'hello'\n  end\nend",
        'func greet(name: String) -> String {\n    return "Hello \\(name)"\n}',
        'object Main {\n  def main(args: Array[String]): Unit = {\n    println("ready")\n  }\n}',
        'void main() {\n  final name = "demo";\n  print(name);\n}',
        "add <- function(x, y) {\n  return(x + y)\n}",
        "function add(x, y)\n    return x + y\nend",
        'local function greet(name)\n  return "hi " .. name\nend',
        'my $name = "demo";\nprint $name;\n',
    ],
)
def test_code_block_detector_matches_common_language_blocks(text):
    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "SELECT id, name\nFROM users\nWHERE active = 1",
        "WITH recent AS (\n"
        "  SELECT id, created_at FROM events\n"
        ")\n"
        "SELECT id FROM recent WHERE created_at > CURRENT_DATE",
        '{\n  "name": "demo",\n  "version": "1.0.0"\n}',
        "version: '3'\nservices:\n  app:\n    image: nginx",
        "<configuration>\n  <appSettings>\n  </appSettings>\n</configuration>",
        "[server]\nhost = localhost\nport = 8080",
        '[tool.demo]\nname = "sample"\nenabled = true',
        ".panel {\n  display: grid;\n  gap: 1rem;\n}",
        "FROM python:3.12\nCOPY . /app\nRUN pip install -e .",
        "build:\n\tpython -m build\nclean:\n\trm -rf dist",
    ],
)
def test_code_block_detector_matches_structured_config_blocks(text):
    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        '#!/usr/bin/env bash\nset -euo pipefail\nfor file in "$@"; do\n  echo "$file"\ndone',
        "param([string]$Name)\nGet-ChildItem -Path . -Recurse\nWrite-Output $Name",
        "ERROR 2026-01-01T00:00:00Z worker failed\n"
        "Traceback (most recent call last):\n"
        '  File "app.py", line 7, in <module>\n'
        "RuntimeError: boom",
    ],
)
def test_code_block_detector_matches_scripts_and_logs(text):
    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "pip install -U pdf2zh-next",
        "docker run --rm -v .:/work image:latest",
        "docker compose up -d --build",
        "kubectl apply -f deployment.yaml",
        "helm upgrade --install demo ./chart",
        "python -m pytest tests -q",
        "git switch -c feature/code-skip",
        "curl -fsSL https://example.invalid/install.sh | sh",
        'find . -name "*.py" -print',
        "tar -xzf archive.tar.gz -C /tmp/app",
        "ssh user@example.invalid 'journalctl -u app'",
        "cd C:\\work\ndir /b\ncopy a.txt b.txt",
        "robocopy C:\\src C:\\dst /MIR",
        "winget install Git.Git",
        "reg query HKCU\\Software",
        "Get-ChildItem -Recurse\nSet-Location C:\\work\nRemove-Item .\\build -Recurse",
        "Invoke-WebRequest -Uri https://example.invalid -OutFile setup.ps1",
    ],
)
def test_code_block_detector_matches_command_lines(text):
    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "aws s3 cp ./dist s3://example-bucket/dist --recursive",
        "az group list --output table",
        "gcloud compute instances list --project demo",
        "terraform plan -out=tfplan",
        "ansible-playbook site.yml -i inventory.ini",
        "systemctl status nginx",
        "journalctl -u nginx --since today",
        "psql -h localhost -U postgres -d app",
        "ffmpeg -i input.mp4 output.webm",
        "openssl x509 -in cert.pem -text -noout",
        "ip addr show",
        "schtasks /Query /TN BackupJob",
        "./configure --prefix=/usr/local",
        ".\\setup.ps1 -Verbose",
        "bazel test //pkg:all",
        "ninja -C build",
        "podman run --rm alpine echo hello",
    ],
)
def test_code_block_detector_matches_broad_command_line_syntax(text):
    assert _looks_like_code_block(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "client.connect(timeout=5)",
        "public static void main(String[] args) {",
        "service = WorkerService()",
        "git clone https://github.com/example/project.git",
        "Get-ChildItem -Recurse",
        "return response.json()",
        "SELECT id FROM users",
    ],
)
def test_code_block_detector_matches_high_confidence_split_fragments(text):
    assert _looks_like_code_block(text) is True


def test_code_block_detector_does_not_match_plain_text():
    text = (
        "This paragraph explains how a parser works across multiple lines.\n"
        "It includes punctuation, but it is still prose."
    )

    assert _looks_like_code_block(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Preparing a sample workspace",
        "Run the pip install command after creating the virtual environment.",
        "Python functions can accept arguments and return values.",
        "The package namespace helps organize related modules.",
        "Use Docker when you want reproducible development environments.",
        "Docker is useful for reproducible development environments.",
        "Git status output is described below.",
        "The kubectl command lists Kubernetes resources.",
        "PowerShell can run Get-ChildItem commands.",
        "AWS CLI helps manage cloud resources.",
        "If connect() returns false, explain the failure in the next paragraph.",
        "Open config.yaml and update the service name before continuing.",
        "The git status command shows which files changed in the workspace.",
        "The --force option is risky when the target directory contains data.",
        "A path such as C:\\work\\demo may appear in the instructions, "
        "but this sentence is prose.",
        "For example, rename the sample stream from alpha to beta:",
        "Select Items/All in the sidebar, refresh the panel, and then read the status message.",
        "After find_package(core REQUIRED), describe why the dependency is needed.",
        "SELECT is shown in uppercase here because the paragraph is explaining SQL keywords.",
        "FROM is a Dockerfile instruction, but this sentence is only documentation.",
        "RUN the installer only after you review the downloaded script.",
        "COPY is mentioned as a file operation, not as a build instruction.",
    ],
)
def test_code_block_detector_does_not_match_technical_prose(text):
    assert _looks_like_code_block(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "Tips",
        "Tip:",
        "Note:",
        "Warning: Make sure the workspace has been sourced.",
        "This tutorial uses a command-line tool to inspect services.",
    ],
)
def test_code_block_classifier_treats_callouts_and_prose_as_text(text):
    assert _classify_code_block(text) == "text"


@pytest.mark.parametrize(
    "text",
    [
        (
            "The following line creates a client:\n"
            "client = ApiClient()\n"
            "Use the client in the next step."
        ),
        (
            "Run this after saving the file:\n"
            "custom-tool deploy --dry-run\n"
            "The command prints a summary."
        ),
        (
            "The next example uses parse_config() to read a settings file.\n"
            "It also mentions output.json, but this paragraph is explanatory."
        ),
        (
            "Note\n"
            "The file name, command name, and display name can be identical.\n"
            "They still describe different concepts in the application."
        ),
        (
            "Click Services/All in the navigation pane, refresh the list twice,\n"
            "and clear the inactive-only filter if the item is hidden:"
        ),
        (
            "After configure_library(core REQUIRED), add a short explanation\n"
            "before finalize_library() so readers understand the dependency."
        ),
    ],
)
def test_code_block_classifier_treats_mixed_prose_as_text(text):
    assert _classify_code_block(text) == "text"
    assert _looks_like_code_block(text) is False


def test_code_block_classifier_marks_unknown_command_as_ambiguous():
    assert _classify_code_block("my_tool build") == "ambiguous"


def test_should_skip_code_block_does_not_call_llm_for_obvious_code(monkeypatch):
    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response='{"decision":"translate","confidence":0.99}',
    )

    assert translator.should_skip_code_block("def add(x, y):\n    return x + y")
    assert translator.do_llm_translate_call_count == 0


def test_should_skip_code_block_uses_llm_for_ambiguous_skip(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response='{"decision":"skip","confidence":0.9,"line_kinds":["command"]}',
    )

    assert translator.should_skip_code_block("my_tool build") is True
    assert translator.do_llm_translate_call_count == 1
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1


@pytest.mark.parametrize(
    "llm_response",
    [
        '{"decision":"translate","confidence":0.99,"line_kinds":["text"]}',
        '{"decision":"skip","confidence":0.5,"line_kinds":["command"]}',
        "not json",
    ],
)
def test_should_skip_code_block_falls_back_to_translate_for_llm_no_skip(
    monkeypatch,
    llm_response,
):
    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response=llm_response,
    )

    assert translator.should_skip_code_block("my_tool build") is False
    assert translator.do_llm_translate_call_count == 1


def test_should_skip_code_block_falls_back_to_translate_for_llm_error(monkeypatch):
    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_exception=RuntimeError("classifier failed"),
    )

    assert translator.should_skip_code_block("my_tool build") is False
    assert translator.do_llm_translate_call_count == 1


def test_should_skip_code_block_does_not_call_llm_when_aux_switch_is_off(monkeypatch):
    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=False,
        llm_response='{"decision":"skip","confidence":0.9}',
    )

    assert translator.should_skip_code_block("my_tool build") is False
    assert translator.do_llm_translate_call_count == 0


def test_should_skip_code_block_does_not_call_llm_for_text(monkeypatch):
    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response='{"decision":"skip","confidence":0.99}',
    )
    text = (
        "The following line creates a client:\n"
        "client = ApiClient()\n"
        "Use the client in the next step."
    )

    assert translator.should_skip_code_block(text) is False
    assert translator.do_llm_translate_call_count == 0


def test_translate_skips_detected_code_block(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
    )
    text = "def add(x, y):\n    return x + y\n\nprint(add(1, 2))"

    assert translator.translate(text) == text
    assert translator.do_translate_call_count == 0
    assert rate_limiter.wait_call_count == 0
    assert fake_cache.get_call_count == 0
    assert fake_cache.set_call_count == 0


def test_translate_keeps_existing_behavior_when_switch_is_off(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=False,
    )
    text = "def add(x, y):\n    return x + y\n\nprint(add(1, 2))"

    assert translator.translate(text) == f"translated:{text}"
    assert translator.do_translate_call_count == 1
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1
    assert fake_cache.set_call_count == 1


def test_translate_keeps_mixed_prose_when_skip_is_enabled(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response='{"decision":"skip","confidence":0.99}',
    )
    text = (
        "Run this after saving the file:\n"
        "custom-tool deploy --dry-run\n"
        "The command prints a summary."
    )

    assert translator.translate(text) == f"translated:{text}"
    assert translator.do_translate_call_count == 1
    assert translator.do_llm_translate_call_count == 0
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1
    assert fake_cache.set_call_count == 1


def test_babeldoc_pre_translate_patch_skips_code_before_rewrite(monkeypatch):
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

    code_text = (
        "def run_job(config):\n"
        "    worker = JobWorker(config)\n"
        "    worker.start()\n"
        "    worker.wait()\n"
        "    return worker.status"
    )
    translate_input = object()

    def fake_pre_translate_paragraph(
        _self,
        _paragraph,
        _tracker,
        _page_font_map,
        _xobj_font_map,
    ):
        return code_text, translate_input

    monkeypatch.setattr(
        ILTranslator,
        "pre_translate_paragraph",
        fake_pre_translate_paragraph,
    )
    monkeypatch.setattr(
        high_level_module,
        "_BABELDOC_SKIP_CODE_BLOCKS_PATCHED",
        False,
    )
    high_level_module._ensure_babeldoc_skip_code_blocks_patch()

    translator = SimpleNamespace(skip_code_blocks=True)
    instance = SimpleNamespace(
        translation_config=SimpleNamespace(translator=translator)
    )
    paragraph = SimpleNamespace(debug_id="code-paragraph")
    tracker = FakeParagraphTracker()

    text, result_translate_input = ILTranslator.pre_translate_paragraph(
        instance,
        paragraph,
        tracker,
        {},
        {},
    )

    assert text is None
    assert result_translate_input is None
    assert tracker.output == code_text


def test_babeldoc_pre_translate_patch_keeps_plain_text(monkeypatch):
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

    plain_text = "Preparing a sample workspace"
    translate_input = object()

    def fake_pre_translate_paragraph(
        _self,
        _paragraph,
        _tracker,
        _page_font_map,
        _xobj_font_map,
    ):
        return plain_text, translate_input

    monkeypatch.setattr(
        ILTranslator,
        "pre_translate_paragraph",
        fake_pre_translate_paragraph,
    )
    monkeypatch.setattr(
        high_level_module,
        "_BABELDOC_SKIP_CODE_BLOCKS_PATCHED",
        False,
    )
    high_level_module._ensure_babeldoc_skip_code_blocks_patch()

    translator = SimpleNamespace(skip_code_blocks=True)
    instance = SimpleNamespace(
        translation_config=SimpleNamespace(translator=translator)
    )
    tracker = FakeParagraphTracker()

    text, result_translate_input = ILTranslator.pre_translate_paragraph(
        instance,
        SimpleNamespace(debug_id="plain-paragraph"),
        tracker,
        {},
        {},
    )

    assert text == plain_text
    assert result_translate_input is translate_input
    assert tracker.output is None


def test_babeldoc_pre_translate_patch_uses_llm_for_ambiguous_code(monkeypatch):
    from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator

    ambiguous_text = "my_tool build"
    translate_input = object()

    def fake_pre_translate_paragraph(
        _self,
        _paragraph,
        _tracker,
        _page_font_map,
        _xobj_font_map,
    ):
        return ambiguous_text, translate_input

    monkeypatch.setattr(
        ILTranslator,
        "pre_translate_paragraph",
        fake_pre_translate_paragraph,
    )
    monkeypatch.setattr(
        high_level_module,
        "_BABELDOC_SKIP_CODE_BLOCKS_PATCHED",
        False,
    )
    high_level_module._ensure_babeldoc_skip_code_blocks_patch()

    translator, _rate_limiter, _fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
        skip_code_blocks_llm=True,
        llm_response='{"decision":"skip","confidence":0.9,"line_kinds":["command"]}',
    )
    instance = SimpleNamespace(
        translation_config=SimpleNamespace(translator=translator)
    )
    tracker = FakeParagraphTracker()

    text, result_translate_input = ILTranslator.pre_translate_paragraph(
        instance,
        SimpleNamespace(debug_id="ambiguous-command"),
        tracker,
        {},
        {},
    )

    assert text is None
    assert result_translate_input is None
    assert tracker.output == ambiguous_text


def test_llm_translate_does_not_skip_detected_code_block(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
    )
    text = "const answer = 42;\nfunction getAnswer() {\n  return answer;\n}"

    assert translator.llm_translate(text) == f"llm:{text}"
    assert translator.do_llm_translate_call_count == 1
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1
    assert fake_cache.set_call_count == 1


def test_llm_translate_skips_code_from_babeldoc_prompt(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
    )
    text = (
        "def run_job(config):\n"
        "    worker = JobWorker(config)\n"
        "    worker.start()\n"
        "    worker.wait()\n"
        "    return worker.status"
    )
    prompt = build_babeldoc_prompt(text)

    assert translator.llm_translate(prompt) == text
    assert translator.do_llm_translate_call_count == 0
    assert rate_limiter.wait_call_count == 0
    assert fake_cache.get_call_count == 0
    assert fake_cache.set_call_count == 0


def test_llm_translate_keeps_babeldoc_prompt_behavior_for_plain_text(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=True,
    )
    prompt = build_babeldoc_prompt("Preparing a sample workspace")

    assert _looks_like_code_block("Preparing a sample workspace") is False
    assert translator.llm_translate(prompt) == f"llm:{prompt}"
    assert translator.do_llm_translate_call_count == 1
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1
    assert fake_cache.set_call_count == 1


def test_llm_translate_keeps_babeldoc_prompt_behavior_when_switch_is_off(monkeypatch):
    translator, rate_limiter, fake_cache = build_translator(
        monkeypatch,
        skip_code_blocks=False,
    )
    text = "worker = JobWorker(config)\nworker.start()"
    prompt = build_babeldoc_prompt(text)

    assert translator.llm_translate(prompt) == f"llm:{prompt}"
    assert translator.do_llm_translate_call_count == 1
    assert rate_limiter.wait_call_count == 1
    assert fake_cache.get_call_count == 1
    assert fake_cache.set_call_count == 1
