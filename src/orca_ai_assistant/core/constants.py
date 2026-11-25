from __future__ import annotations

import os
from typing import Any

PLUGIN_ID = "orca-ai-assistant"
PLUGIN_VERSION = "3.0.1"
SUPPORTED_LANGUAGES = ("ru", "uk", "en")

# Retired model IDs automatically migrated when loading settings (both active model and favorites)
RETIRED_MODEL_MIGRATIONS: dict[str, str] = {
    "claude-sonnet-4-20250514": "claude-sonnet-5-5",
    "claude-3-7-sonnet-latest": "claude-sonnet-5-5",
    "claude-3-5-sonnet-latest": "claude-sonnet-5-5",
    "gemini-2.5-flash": "gemini-3.8-flash",
    "gemini-2.5-pro": "gemini-3.8-pro",
    "google/gemini-2.5-flash": "google/gemini-3.8-flash",
    "google/gemini-2.5-pro": "google/gemini-3.8-pro",
    "anthropic/claude-sonnet-4": "anthropic/claude-sonnet-5.5",
    "gpt-4.1-mini": "gpt-5.1",
    "openai/gpt-4.1": "openai/gpt-5.2",
}


def norm_lang(lang: Any) -> str:
    s = str(lang or "ru").strip().lower()
    if s in ("ua", "uk", "ukr") or s.startswith(("uk_", "uk-", "ua_", "ua-")):
        return "uk"
    if s in ("en", "eng") or s.startswith(("en_", "en-")):
        return "en"
    return "ru"


def tr(lang: str, ru: str, uk: str, en: str) -> str:
    l = norm_lang(lang)
    if l == "uk":
        return uk
    if l == "en":
        return en
    return ru


def detect_default_language(orca_app_info: dict[str, Any] | None = None) -> str:
    """Detect initial UI language: OrcaSlicer app_info first, then OS locale."""
    if isinstance(orca_app_info, dict):
        app_lang = str(orca_app_info.get("language") or "").strip().lower()
        if app_lang:
            if app_lang.startswith(("uk", "ua")):
                return "uk"
            if app_lang.startswith("ru"):
                return "ru"
            return "en"

    try:
        import locale

        loc = (locale.getlocale()[0] or os.environ.get("LANG") or os.environ.get("LC_ALL") or "").strip().lower()
        if loc.startswith(("uk", "ua")):
            return "uk"
        if loc.startswith("ru"):
            return "ru"
    except Exception:
        pass
    return "en"


def default_favorites() -> list[dict[str, str]]:
    return [
        {"provider": "anthropic", "model": "claude-opus-5-5", "label": "Claude Opus 5.5"},
        {"provider": "anthropic", "model": "claude-sonnet-5-5", "label": "Claude Sonnet 5.5"},
        {"provider": "anthropic", "model": "claude-fable-5-2", "label": "Claude Fable 5.2"},
        {"provider": "openai", "model": "gpt-5.2", "label": "GPT-5.2"},
        {"provider": "gemini", "model": "gemini-3.8-pro", "label": "Gemini 3.8 Pro"},
        {"provider": "gemini", "model": "gemini-3.8-flash", "label": "Gemini 3.8 Flash"},
        {"provider": "openrouter", "model": "deepseek/deepseek-chat-v3-0324:free", "label": "DeepSeek V3 (Free)"},
        {"provider": "glm", "model": "glm-4.6", "label": "GLM-4.6"},
    ]


def default_settings(orca_app_info: dict[str, Any] | None = None) -> dict[str, Any]:
    from ..providers.registry import PROVIDER_PRESETS

    return {
        "schema_version": 4,
        "language": detect_default_language(orca_app_info),
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "temperature": 0.3,
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "auto_attach_context": True,
        "compact_context": True,
        "include_custom_gcode": False,
        "enable_slicing_audit": False,
        "preflight_notifications": True,
        "custom_user_instructions": "",
        "api_keys": {p: "" for p in PROVIDER_PRESETS},
        "model_api_keys": {},
        "base_urls": {p: info["base_url"] for p, info in PROVIDER_PRESETS.items()},
        "custom_protocol": "openai",
        "favorite_models": default_favorites(),
        "cached_models": {},
    }
