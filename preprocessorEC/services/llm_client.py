"""Shared OpenAI-compatible client construction.

Extracted from ``llm_review`` so the corporate-network SSL handling (custom CA
bundle, Windows system trust store via ``truststore``) lives in exactly one
place. Both the preprocessor's match review and Quick Discovery use it.

``build_client()`` takes an explicit settings dict rather than reading
``current_app``, so a caller can construct one client on the request thread and
hand it to worker threads that have no Flask application context.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def chat_completion_model_kwargs(model: str, *, temperature: float) -> dict:
    """Return model-compatible Chat Completions tuning parameters.

    GPT-5.6 only accepts its default sampling temperature.  Explicitly keep the
    prior GPT-5.4 mini reasoning baseline instead of sending the unsupported
    ``temperature=0`` value used by this application.
    """
    normalized_model = (model or "").strip().lower()
    if normalized_model == "gpt-5.6" or normalized_model.startswith("gpt-5.6-"):
        return {"reasoning_effort": "none"}
    return {"temperature": temperature}


def client_settings_from_config(config) -> dict:
    """Snapshot the LLM settings out of a Flask config into a plain dict."""
    return {
        "api_key": config.get("OPENAI_API_KEY", ""),
        "timeout": config.get("OPENAI_TIMEOUT_SECONDS", 30.0),
        "max_retries": config.get("OPENAI_MAX_RETRIES", 2),
        "disable_ssl_verify": bool(config.get("OPENAI_DISABLE_SSL_VERIFY", False)),
        "ca_bundle": (config.get("OPENAI_CA_BUNDLE", "") or "").strip(),
        "use_system_ca_store": bool(config.get("OPENAI_USE_SYSTEM_CA_STORE", False)),
        "base_url": config.get("OPENAI_BASE_URL", ""),
        "organization": config.get("OPENAI_ORGANIZATION", ""),
        "project": config.get("OPENAI_PROJECT", ""),
        "azure_endpoint": config.get("AZURE_OPENAI_ENDPOINT", ""),
        "azure_api_version": config.get("AZURE_OPENAI_API_VERSION", ""),
        "model": config.get("OPENAI_MODEL", "gpt-5.6-luna"),
        "max_tokens": config.get("LLM_MAX_TOKENS", 1024),
        "temperature": config.get("LLM_TEMPERATURE", 0.0),
    }


def build_ssl_verify(settings: dict) -> Any:
    """Resolve httpx's ``verify`` argument for this environment."""
    if settings.get("disable_ssl_verify"):
        return False

    ca_bundle = (settings.get("ca_bundle") or "").strip()
    if ca_bundle:
        return ca_bundle

    if not settings.get("use_system_ca_store"):
        return True

    try:
        import importlib
        import ssl

        truststore = importlib.import_module("truststore")
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:
        logger.warning("truststore not installed; falling back to certifi CA bundle.")
        return True


def build_client(settings: dict) -> Optional[Any]:
    """Construct an OpenAI or AzureOpenAI client, or None if unavailable.

    Returns None rather than raising when no API key is configured or the
    ``openai`` package is missing, so callers can degrade to human review.

    The returned client is safe to share across threads; reuse one per batch
    instead of building a fresh ``httpx.Client`` per request.
    """
    api_key = settings.get("api_key", "")
    if not api_key:
        return None

    timeout = settings.get("timeout", 30.0)
    max_retries = settings.get("max_retries", 2)
    azure_endpoint = settings.get("azure_endpoint", "")

    try:
        import httpx
        from openai import AzureOpenAI, OpenAI

        http_client = httpx.Client(timeout=timeout, verify=build_ssl_verify(settings))

        if azure_endpoint:
            azure_api_version = settings.get("azure_api_version", "")
            if not azure_api_version:
                logger.error(
                    "AZURE_OPENAI_ENDPOINT is set but AZURE_OPENAI_API_VERSION is missing."
                )
                return None
            return AzureOpenAI(
                api_key=api_key,
                azure_endpoint=azure_endpoint,
                api_version=azure_api_version,
                timeout=timeout,
                max_retries=max_retries,
                http_client=http_client,
            )

        client_kwargs = {
            "api_key": api_key,
            "timeout": timeout,
            "max_retries": max_retries,
            "http_client": http_client,
        }
        if settings.get("base_url"):
            client_kwargs["base_url"] = settings["base_url"]
        if settings.get("organization"):
            client_kwargs["organization"] = settings["organization"]
        if settings.get("project"):
            client_kwargs["project"] = settings["project"]

        return OpenAI(**client_kwargs)
    except ImportError:
        logger.warning("openai package not installed; LLM features unavailable.")
        return None
