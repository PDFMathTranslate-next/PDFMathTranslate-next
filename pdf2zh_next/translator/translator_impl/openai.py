import logging

import httpx
import openai
from babeldoc.utils.atomic_integer import AtomicInteger
from pdf2zh_next.config.model import SettingsModel
from pdf2zh_next.translator.base_rate_limiter import BaseRateLimiter
from pdf2zh_next.translator.base_translator import BaseTranslator
from tenacity import before_sleep_log
from tenacity import retry
from tenacity import retry_if_exception_type
from tenacity import stop_after_attempt
from tenacity import wait_exponential

logger = logging.getLogger(__name__)


class OpenAITranslator(BaseTranslator):
    # https://github.com/openai/openai-python
    name = "openai"

    def __init__(
        self,
        settings: SettingsModel,
        rate_limiter: BaseRateLimiter,
    ):
        super().__init__(settings, rate_limiter)
        self.timeout = settings.translate_engine_settings.openai_timeout
        self.client = openai.OpenAI(
            base_url=settings.translate_engine_settings.openai_base_url,
            api_key=settings.translate_engine_settings.openai_api_key,
            timeout=float(self.timeout) if self.timeout else openai.NOT_GIVEN,
            http_client=httpx.Client(
                limits=httpx.Limits(
                    max_connections=None, max_keepalive_connections=None
                )
            ),
        )
        self.options = {}
        self.temperature = settings.translate_engine_settings.openai_temperature
        self.reasoning_effort = (
            settings.translate_engine_settings.openai_reasoning_effort
        )
        self.send_temperature = (
            settings.translate_engine_settings.openai_send_temprature
        )
        self.send_reasoning_effort = (
            settings.translate_engine_settings.openai_send_reasoning_effort
        )
        self.extra_body = settings.translate_engine_settings._openai_extra_body

        if self.send_temperature and self.temperature:
            self.add_cache_impact_parameters("temperature", self.temperature)
            self.options["temperature"] = float(self.temperature)
        if self.send_reasoning_effort and self.reasoning_effort:
            self.add_cache_impact_parameters("reasoning_effort", self.reasoning_effort)
            self.options["reasoning_effort"] = self.reasoning_effort
        if self.extra_body:
            self.add_cache_impact_parameters("extra_body", self.extra_body)
            self.options["extra_body"] = self.extra_body

        self.model = settings.translate_engine_settings.openai_model
        self.add_cache_impact_parameters("model", self.model)
        self.add_cache_impact_parameters("prompt", self.prompt(""))
        self.token_count = AtomicInteger()
        self.prompt_token_count = AtomicInteger()
        self.completion_token_count = AtomicInteger()
        self.cache_hit_prompt_token_count = AtomicInteger()

        self.enable_json_mode = (
            settings.translate_engine_settings.openai_enable_json_mode
        )
        if self.enable_json_mode:
            self.add_cache_impact_parameters("enable_json_mode", self.enable_json_mode)
        self.use_stream = settings.translate_engine_settings.openai_use_stream

    def _build_options(self, rate_limit_params: dict = None) -> dict:
        options = self.options.copy()
        if (
            self.enable_json_mode
            and rate_limit_params
            and rate_limit_params.get("request_json_mode", False)
        ):
            options["response_format"] = {"type": "json_object"}
        return options

    def _record_token_usage(self, usage) -> None:
        try:
            if usage:
                if hasattr(usage, "total_tokens"):
                    self.token_count.inc(usage.total_tokens)
                if hasattr(usage, "prompt_tokens"):
                    self.prompt_token_count.inc(usage.prompt_tokens)
                if hasattr(usage, "completion_tokens"):
                    self.completion_token_count.inc(usage.completion_tokens)
                if hasattr(usage, "prompt_cache_hit_tokens"):
                    self.cache_hit_prompt_token_count.inc(usage.prompt_cache_hit_tokens)
                elif hasattr(usage, "prompt_tokens_details") and hasattr(
                    usage.prompt_tokens_details, "cached_tokens"
                ):
                    self.cache_hit_prompt_token_count.inc(
                        usage.prompt_tokens_details.cached_tokens
                    )
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")

    def _create_completion_text(self, messages: list[dict], options: dict) -> str:
        if self.use_stream:
            return self._create_stream_completion_text(messages, options)

        response = self.client.chat.completions.create(
            model=self.model,
            **options,
            messages=messages,
        )
        self._record_token_usage(getattr(response, "usage", None))
        return response.choices[0].message.content.strip()

    def _create_stream_completion_text(self, messages: list[dict], options: dict) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            **options,
            messages=messages,
            stream=True,
        )
        parts = []
        for chunk in response:
            self._record_token_usage(getattr(chunk, "usage", None))
            choices = getattr(chunk, "choices", None)
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            content = getattr(delta, "content", None)
            if content:
                parts.append(content)
        return "".join(parts).strip()

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        options = self._build_options(rate_limit_params)
        message = self._create_completion_text(self.prompt(text), options)
        message = self._remove_cot_content(message)
        return message

    @retry(
        retry=retry_if_exception_type(openai.RateLimitError),
        stop=stop_after_attempt(100),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        if text is None:
            return None
        options = self._build_options(rate_limit_params)
        message = self._create_completion_text(
            [
                {
                    "role": "user",
                    "content": text,
                },
            ],
            options,
        )
        message = self._remove_cot_content(message)
        return message
