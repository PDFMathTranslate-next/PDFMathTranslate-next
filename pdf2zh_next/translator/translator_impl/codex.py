import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.base_translator import BaseTranslator
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

logger = logging.getLogger(__name__)


@dataclass
class _BatchRequest:
    text: str
    event: threading.Event = field(default_factory=threading.Event)
    result: str | None = None
    error: Exception | None = None


class CodexTranslator(BaseTranslator):
    name = "codex"
    pdf2zh_next_recommended_pool_max_workers = 8

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        super().__init__(settings, rate_limiter)
        self.codex_path = settings.translate_engine_settings.codex_path
        self.codex_model = settings.translate_engine_settings.codex_model
        timeout_value = settings.translate_engine_settings.codex_timeout or "180"
        self.codex_timeout = int(float(timeout_value))
        self.codex_reasoning_effort = (
            settings.translate_engine_settings.codex_reasoning_effort or "low"
        )
        self.codex_batch_size = 8
        self.codex_batch_wait_seconds = 0.25
        self._batch_condition = threading.Condition()
        self._pending_requests: list[_BatchRequest] = []
        self._batch_worker_thread = threading.Thread(
            target=self._batch_worker,
            name="pdf2zh-codex-batcher",
            daemon=True,
        )

        if self.codex_model:
            self.add_cache_impact_parameters("model", self.codex_model)
        self.add_cache_impact_parameters(
            "reasoning_effort",
            self.codex_reasoning_effort,
        )
        self.add_cache_impact_parameters("prompt", self.prompt(""))
        self.add_cache_impact_parameters("batch_prompt_version", "v1")
        self._test_codex()
        self._batch_worker_thread.start()

    def _test_codex(self):
        try:
            result = subprocess.run(
                [self.codex_path, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                raise ValueError(f"Codex CLI error: {result.stderr}")
        except FileNotFoundError as e:
            raise ValueError(f"Codex CLI not found at '{self.codex_path}'") from e

    @retry(
        retry=retry_if_exception_type(
            (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        request = _BatchRequest(text=text)
        with self._batch_condition:
            self._pending_requests.append(request)
            self._batch_condition.notify()

        wait_timeout = self.codex_timeout + self.codex_batch_wait_seconds + 15
        if not request.event.wait(timeout=wait_timeout):
            raise subprocess.TimeoutExpired(
                [self.codex_path, "exec"],
                timeout=wait_timeout,
            )
        if request.error is not None:
            raise request.error
        if request.result is None:
            raise ValueError("No translation received from Codex")
        return request.result

    def _batch_worker(self) -> None:
        while True:
            with self._batch_condition:
                while not self._pending_requests:
                    self._batch_condition.wait()

                deadline = time.monotonic() + self.codex_batch_wait_seconds
                while len(self._pending_requests) < self.codex_batch_size:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._batch_condition.wait(timeout=remaining)

                batch = self._pending_requests[: self.codex_batch_size]
                del self._pending_requests[: len(batch)]

            try:
                self._process_batch(batch)
            except Exception as e:  # pragma: no cover - defensive worker isolation
                logger.exception("Unexpected Codex batch worker error: %s", e)
                for request in batch:
                    request.error = e
                    request.event.set()

    def _process_batch(self, batch: list[_BatchRequest]) -> None:
        texts = [request.text for request in batch]
        try:
            if len(batch) == 1:
                translations = [self._run_single_translation(texts[0])]
            else:
                translations = self._run_batch_translations(texts)
        except Exception as batch_error:
            if len(batch) == 1:
                for request in batch:
                    request.error = batch_error
                    request.event.set()
                return

            logger.warning(
                "Codex batch translation failed for %s paragraphs, fallback to single requests: %s",
                len(batch),
                batch_error,
            )
            try:
                translations = [self._run_single_translation(text) for text in texts]
            except Exception as single_error:
                for request in batch:
                    request.error = single_error
                    request.event.set()
                return

        for request, translation in zip(batch, translations, strict=True):
            request.result = translation
            request.event.set()

    def _build_codex_command(self, prompt: str) -> tuple[list[str], Path]:
        cmd = [
            self.codex_path,
            "exec",
            "-c",
            'model_provider="openai_https"',
            "-c",
            'model_providers.openai_https.name="OpenAI"',
            "-c",
            "model_providers.openai_https.requires_openai_auth=true",
            "-c",
            'model_providers.openai_https.wire_api="responses"',
            "-c",
            "model_providers.openai_https.supports_websockets=false",
            "-c",
            f'model_reasoning_effort="{self.codex_reasoning_effort}"',
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
        ]
        if self.codex_model:
            cmd.extend(["--model", self.codex_model])

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            output_path = Path(tmp.name)

        cmd.extend(["--output-last-message", str(output_path), prompt])
        return cmd, output_path

    @retry(
        retry=retry_if_exception_type(
            (subprocess.CalledProcessError, subprocess.TimeoutExpired)
        ),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=2, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def _run_codex_prompt(self, prompt: str) -> str:
        cmd, output_path = self._build_codex_command(prompt)
        try:
            logger.info("Running Codex CLI translation")
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.codex_timeout,
            )
            if process.returncode != 0:
                logger.error("Codex failed: %s", process.stderr)
                raise subprocess.CalledProcessError(
                    process.returncode,
                    cmd,
                    output=process.stdout,
                    stderr=process.stderr,
                )

            translation = output_path.read_text(encoding="utf-8").strip()
            if not translation:
                raise ValueError("No translation received from Codex")
            return translation
        finally:
            output_path.unlink(missing_ok=True)

    def _run_single_translation(self, text: str) -> str:
        prompt = self.prompt(text)[0]["content"]
        return self._run_codex_prompt(prompt)

    def _run_batch_translations(self, texts: list[str]) -> list[str]:
        prompt = self._build_batch_prompt(texts)
        raw_output = self._run_codex_prompt(prompt)
        return self._parse_batch_output(raw_output, len(texts))

    def _build_batch_prompt(self, texts: list[str]) -> str:
        payload = [{"id": idx, "input": text} for idx, text in enumerate(texts)]
        return (
            "You are a professional, authentic machine translation engine.\n\n"
            f"Translate every item's `input` field into {self.lang_out}. "
            "Return JSON ONLY as an array of objects. "
            "Each object must be in the form "
            '{"id": <same integer id>, "translation": "<translated text>"}.\n'
            "Rules:\n"
            "1. Preserve placeholders, formulas, code, and proper nouns when translation is unnecessary.\n"
            "2. Do not add explanations, comments, or markdown fences.\n"
            "3. Keep the same ids.\n"
            "4. Output one translation per input.\n\n"
            f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
        )

    def _parse_batch_output(self, output: str, expected_size: int) -> list[str]:
        cleaned_output = output.strip()
        cleaned_output = re.sub(r"^```(?:json)?\s*", "", cleaned_output)
        cleaned_output = re.sub(r"\s*```$", "", cleaned_output)
        parsed = json.loads(cleaned_output)

        if isinstance(parsed, dict):
            if isinstance(parsed.get("translations"), list):
                parsed = parsed["translations"]
            else:
                raise ValueError("Unexpected Codex batch response format")

        if not isinstance(parsed, list):
            raise ValueError("Codex batch response is not a list")

        translations_by_id: dict[int, str] = {}
        for item in parsed:
            if not isinstance(item, dict):
                raise ValueError("Codex batch response item is not an object")

            item_id = int(item["id"])
            translation = item.get("translation")
            if not isinstance(translation, str):
                raise ValueError("Codex batch response item is missing translation")
            translations_by_id[item_id] = translation.strip()

        missing_ids = [
            idx for idx in range(expected_size) if idx not in translations_by_id
        ]
        if missing_ids:
            raise ValueError(f"Codex batch response missing ids: {missing_ids}")

        return [translations_by_id[idx] for idx in range(expected_size)]
