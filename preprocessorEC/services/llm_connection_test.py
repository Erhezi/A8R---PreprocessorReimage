"""Focused OpenAI connectivity test for debug and diagnosis."""

from __future__ import annotations

import time
from urllib.parse import urljoin

from flask import current_app

from .llm_client import build_client, build_ssl_verify, client_settings_from_config


def _describe_exception(exc: Exception) -> dict:
    cause = exc.__cause__ or exc.__context__
    return {
        "error_type": exc.__class__.__name__,
        "message": str(exc),
        "exception_repr": repr(exc),
        "cause_type": cause.__class__.__name__ if cause else None,
        "cause_message": str(cause) if cause else None,
        "cause_repr": repr(cause) if cause else None,
    }


def test_openai_connection() -> dict:
    """Exercise the configured OpenAI client with a tiny chat completion."""
    api_key = current_app.config.get("OPENAI_API_KEY", "")
    model = current_app.config.get("OPENAI_MODEL", "gpt-4.1-mini")
    base_url = current_app.config.get("OPENAI_BASE_URL", "")
    azure_endpoint = current_app.config.get("AZURE_OPENAI_ENDPOINT", "")
    disable_ssl_verify = bool(current_app.config.get("OPENAI_DISABLE_SSL_VERIFY", False))
    timeout = current_app.config.get("OPENAI_TIMEOUT_SECONDS", 30.0)
    endpoint_mode = "azure" if azure_endpoint else "openai"
    resolved_base_url = base_url or "https://api.openai.com/v1"
    settings = client_settings_from_config(current_app.config)

    if not api_key:
        return {
            "ok": False,
            "error_type": "missing_api_key",
            "message": "OPENAI_API_KEY is not configured.",
            "model": model,
        }

    probe_result = {
        "ok": False,
        "status_code": None,
        "url": None,
        "error_type": None,
        "message": None,
        "cause_type": None,
        "cause_message": None,
    }

    try:
        import httpx

        models_url = urljoin(f"{resolved_base_url}/", "models")
        probe_started = time.perf_counter()
        with httpx.Client(timeout=timeout, verify=build_ssl_verify(settings)) as probe_client:
            probe_response = probe_client.get(
                models_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        probe_result = {
            "ok": probe_response.is_success,
            "status_code": probe_response.status_code,
            "url": str(probe_response.request.url),
            "elapsed_ms": round((time.perf_counter() - probe_started) * 1000, 2),
            "message": "HTTP probe succeeded." if probe_response.is_success else probe_response.text[:300],
            "error_type": None,
            "cause_type": None,
            "cause_message": None,
        }
    except Exception as exc:
        probe_result = {
            "ok": False,
            "status_code": None,
            "url": urljoin(f"{resolved_base_url}/", "models"),
            "elapsed_ms": None,
            **_describe_exception(exc),
        }

    client = build_client(settings)
    if client is None:
        return {
            "ok": False,
            "error_type": "client_unavailable",
            "message": "OpenAI client could not be created from current config.",
            "model": model,
            "endpoint_mode": endpoint_mode,
            "base_url": base_url or None,
            "azure_endpoint": azure_endpoint or None,
            "ssl_verify_disabled": disable_ssl_verify,
            "http_probe": probe_result,
        }

    started = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a connection test. Return only the word OK."},
                {"role": "user", "content": "Reply with OK."},
            ],
            max_completion_tokens=5,
            temperature=0,
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        content = response.choices[0].message.content if response.choices else ""
        return {
            "ok": True,
            "message": "OpenAI connection succeeded.",
            "model": model,
            "endpoint_mode": endpoint_mode,
            "base_url": base_url or None,
            "azure_endpoint": azure_endpoint or None,
            "ssl_verify_disabled": disable_ssl_verify,
            "elapsed_ms": elapsed_ms,
            "http_probe": probe_result,
            "response_preview": (content or "")[:100],
        }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        return {
            "ok": False,
            **_describe_exception(exc),
            "model": model,
            "endpoint_mode": endpoint_mode,
            "base_url": base_url or None,
            "azure_endpoint": azure_endpoint or None,
            "ssl_verify_disabled": disable_ssl_verify,
            "elapsed_ms": elapsed_ms,
            "http_probe": probe_result,
        }