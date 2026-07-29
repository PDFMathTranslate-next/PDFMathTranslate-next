import logging
import os

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


def _build_http_client(timeout: float | None = None) -> httpx.Client:
    """Build httpx client with explicit proxy, immune to no_proxy=*."""
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    # Separate connect vs read: connect should fail fast; read allows long generations.
    read_s = float(timeout) if timeout else 180.0
    http_timeout = httpx.Timeout(connect=30.0, read=read_s, write=60.0, pool=60.0)
    disable = os.environ.get("PDF2ZH_DISABLE_PROXY", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    proxy = (
        os.environ.get("PDF2ZH_HTTP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("http_proxy")
        or ""
    ).strip()
    if disable:
        # Force direct connect; ignore env / system proxy.
        return httpx.Client(trust_env=False, limits=limits, timeout=http_timeout)
    if proxy:
        # Explicit proxy ignores no_proxy=* (set by gpt_academic main.py).
        logger.info("OpenAITranslator using proxy=%s timeout_read=%s", proxy, read_s)
        return httpx.Client(
            proxy=proxy, trust_env=False, limits=limits, timeout=http_timeout
        )
    return httpx.Client(limits=limits, timeout=http_timeout)


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
        timeout_f = float(self.timeout) if self.timeout else 180.0
        self.client = openai.OpenAI(
            base_url=settings.translate_engine_settings.openai_base_url,
            api_key=settings.translate_engine_settings.openai_api_key,
            timeout=timeout_f,
            http_client=_build_http_client(timeout_f),
            max_retries=0,  # retries handled by tenacity below
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

    @retry(
        retry=retry_if_exception_type(
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                httpx.TimeoutException,
                httpx.TransportError,
            )
        ),
        stop=stop_after_attempt(8),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_translate(self, text, rate_limit_params: dict = None) -> str:
        options = self.options.copy()
        if (
            self.enable_json_mode
            and rate_limit_params
            and rate_limit_params.get("request_json_mode", False)
        ):
            options["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(
            model=self.model,
            **options,
            messages=self.prompt(text),
        )
        try:
            if hasattr(response, "usage") and response.usage:
                if hasattr(response.usage, "total_tokens"):
                    self.token_count.inc(response.usage.total_tokens)
                if hasattr(response.usage, "prompt_tokens"):
                    self.prompt_token_count.inc(response.usage.prompt_tokens)
                if hasattr(response.usage, "completion_tokens"):
                    self.completion_token_count.inc(response.usage.completion_tokens)
                if hasattr(response.usage, "prompt_cache_hit_tokens"):
                    self.cache_hit_prompt_token_count.inc(
                        response.usage.prompt_cache_hit_tokens
                    )
                elif hasattr(response.usage, "prompt_tokens_details") and hasattr(
                    response.usage.prompt_tokens_details, "cached_tokens"
                ):
                    self.cache_hit_prompt_token_count.inc(
                        response.usage.prompt_tokens_details.cached_tokens
                    )
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            pass
        message = response.choices[0].message.content.strip()
        message = self._remove_cot_content(message)
        return message

    @retry(
        retry=retry_if_exception_type(
            (
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                httpx.TimeoutException,
                httpx.TransportError,
            )
        ),
        stop=stop_after_attempt(8),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
    def do_llm_translate(self, text, rate_limit_params: dict = None):
        if text is None:
            return None
        options = self.options.copy()
        if (
            self.enable_json_mode
            and rate_limit_params
            and rate_limit_params.get("request_json_mode", False)
        ):
            options["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(
            model=self.model,
            **options,
            messages=[
                {
                    "role": "user",
                    "content": text,
                },
            ],
        )
        try:
            if hasattr(response, "usage") and response.usage:
                if hasattr(response.usage, "total_tokens"):
                    self.token_count.inc(response.usage.total_tokens)
                if hasattr(response.usage, "prompt_tokens"):
                    self.prompt_token_count.inc(response.usage.prompt_tokens)
                if hasattr(response.usage, "completion_tokens"):
                    self.completion_token_count.inc(response.usage.completion_tokens)
                if hasattr(response.usage, "prompt_cache_hit_tokens"):
                    self.cache_hit_prompt_token_count.inc(
                        response.usage.prompt_cache_hit_tokens
                    )
                elif hasattr(response.usage, "prompt_tokens_details") and hasattr(
                    response.usage.prompt_tokens_details, "cached_tokens"
                ):
                    self.cache_hit_prompt_token_count.inc(
                        response.usage.prompt_tokens_details.cached_tokens
                    )
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            pass
        message = response.choices[0].message.content.strip()
        message = self._remove_cot_content(message)
        return message
