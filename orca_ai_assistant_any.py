# /// script
# name = "orca-ai-assistant"
# version = "2.3.1"
# requires-python = ">=3.12"
# dependencies = []
#
# [tool.orcaslicer.plugin]
# name = "Orca AI Assistant"
# description = "Multilingual (EN / UA / RU) interactive AI assistant for OrcaSlicer: streaming responses, fast Gemini thinking mode, 3D model geometry & overhang analysis, slicer settings audit, 1-click parameter application, photo defect diagnostics, and G-code audit."
# author = "Anton & Antigravity"
# version = "2.3.1"
# ///

from __future__ import annotations

import base64
import datetime as dt
import importlib
import json
import math
import os
import re
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import orca
import orca.host

# Подключаем пакетный каталог OrcaSlicer (где установлен numpy cp312), если он ещё не в sys.path
try:
    _pkg_dir = Path(os.environ.get("APPDATA", str(Path.home()))) / "OrcaSlicer" / "python" / "packages" / "cp312"
    if _pkg_dir.is_dir() and str(_pkg_dir) not in sys.path:
        sys.path.append(str(_pkg_dir))
except Exception:
    pass

try:
    import numpy as np
except Exception:
    np = None  # type: ignore


def _orca_submodule(name: str) -> Any:
    sub = getattr(orca, name, None)
    if sub is None:
        try:
            sub = importlib.import_module(f"orca.{name}")
        except ImportError:
            sub = None
    return sub


_pages = _orca_submodule("pages")
_PAGES_BASE = getattr(_pages, "PagesPluginCapabilityBase", None) if _pages is not None else None

_script = _orca_submodule("script")
_SCRIPT_BASE = getattr(_script, "ScriptPluginCapabilityBase", None) if _script is not None else None

_slicing = _orca_submodule("slicing")
_PIPELINE_BASE = getattr(_slicing, "SlicingPipelineCapabilityBase", None) if _slicing is not None else None
_GCODE_STEP = getattr(getattr(_slicing, "Step", None), "psGCodePostProcess", None)
if _GCODE_STEP is None:
    _PIPELINE_BASE = None


# ============================================================================
# 1. КОНСТАНТЫ, МУЛЬТИЯЗЫЧНОСТЬ (RU / UK / EN), ПРОВАЙДЕРЫ И МОДЕЛИ (2026)
# ============================================================================

PLUGIN_ID = "orca-ai-assistant"
PLUGIN_VERSION = "2.3.1"
SUPPORTED_LANGUAGES = ("ru", "uk", "en")

TAB_ICON_PATH = Path(__file__).resolve().with_name(".orca_ai_assistant_icon.svg")
TAB_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 20 20">
<rect x="3" y="4.5" width="14" height="11" rx="3" fill="none" stroke="#13b2a5" stroke-width="1.6"/>
<line x1="10" y1="1.8" x2="10" y2="4.5" stroke="#13b2a5" stroke-width="1.6" stroke-linecap="round"/>
<circle cx="7.2" cy="9.5" r="1.3" fill="#ffffff"/>
<circle cx="12.8" cy="9.5" r="1.3" fill="#ffffff"/>
<path d="M6.8 12.8c1.8 1.2 4.6 1.2 6.4 0" fill="none" stroke="#13b2a5" stroke-width="1.4" stroke-linecap="round"/>
</svg>"""


def norm_lang(lang: Any) -> str:
    s = str(lang or "ru").strip().lower()
    if s in ("ua", "uk", "ukr"):
        return "uk"
    if s in ("en", "eng"):
        return "en"
    return "ru"


def tr(lang: str, ru: str, uk: str, en: str) -> str:
    l = norm_lang(lang)
    if l == "uk":
        return uk
    if l == "en":
        return en
    return ru


# Устаревшие ID моделей, которые автоматически заменяются при миграции настроек
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

PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "name": "Anthropic Claude",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "default_model": "claude-opus-5-5",
        "needs_key": True,
        "key_placeholder": "sk-ant-api03-...",
        "hint": "Прямой API Anthropic (/v1/messages). Укажите ваш ключ sk-ant-...",
        "hint_i18n": {
            "ru": "Прямой API Anthropic (/v1/messages). Для загрузки списка моделей с сервера укажите ваш ключ sk-ant-...",
            "uk": "Прямий API Anthropic (/v1/messages). Для завантаження списку моделей із сервера вкажіть ваш ключ sk-ant-...",
            "en": "Direct Anthropic API (/v1/messages). Enter your sk-ant-... API key to chat and fetch live models.",
        },
        "suggested_models": [
            {"id": "claude-fable-5-2", "name": "Claude Fable 5.2 (Max Reasoning)"},
            {"id": "claude-opus-5-5", "name": "Claude Opus 5.5 (Flagship)"},
            {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5 (Fast & Smart)"},
            {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5 (Ultra Fast)"},
            {"id": "claude-sonnet-5", "name": "Claude Sonnet 5"},
            {"id": "claude-opus-4-8", "name": "Claude Opus 4.8"},
            {"id": "claude-haiku-4-5", "name": "Claude Haiku 4.5"},
        ],
    },
    "openai": {
        "name": "OpenAI (GPT-5 / o-series)",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5.2",
        "needs_key": True,
        "key_placeholder": "sk-proj-...",
        "hint": "Официальный API OpenAI. Ключ: platform.openai.com/api-keys",
        "hint_i18n": {
            "ru": "Официальный API OpenAI. Ключ: platform.openai.com/api-keys",
            "uk": "Офіційний API OpenAI. Ключ: platform.openai.com/api-keys",
            "en": "Official OpenAI API. Get your key at platform.openai.com/api-keys",
        },
        "suggested_models": [
            {"id": "gpt-5.2", "name": "GPT-5.2 (Flagship)"},
            {"id": "gpt-5.1", "name": "GPT-5.1"},
            {"id": "gpt-5-mini", "name": "GPT-5 Mini (Fast)"},
            {"id": "gpt-5-nano", "name": "GPT-5 Nano"},
            {"id": "o4-mini", "name": "o4-mini (Reasoning)"},
            {"id": "o3", "name": "o3 (Deep Analysis)"},
        ],
    },
    "gemini": {
        "name": "Google Gemini API",
        "protocol": "openai",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-3.8-flash",
        "needs_key": True,
        "key_placeholder": "AIzaSy...",
        "hint": "Google AI Studio API (есть бесплатный тариф). Ключ: aistudio.google.com/apikey",
        "hint_i18n": {
            "ru": "Google AI Studio API (есть бесплатный тариф). Ключ: aistudio.google.com/apikey",
            "uk": "Google AI Studio API (є безкоштовний тариф). Ключ: aistudio.google.com/apikey",
            "en": "Google AI Studio API (Free tier available). Key: aistudio.google.com/apikey",
        },
        "suggested_models": [
            {"id": "gemini-3.8-pro", "name": "Gemini 3.8 Pro (Flagship)"},
            {"id": "gemini-3.8-flash", "name": "Gemini 3.8 Flash (Fast & Accurate)"},
            {"id": "gemini-3.5-pro", "name": "Gemini 3.5 Pro"},
            {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash"},
            {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite"},
        ],
    },
    "openrouter": {
        "name": "OpenRouter (All Models + Free)",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "anthropic/claude-opus-5.5",
        "needs_key": True,
        "key_placeholder": "sk-or-v1-...",
        "hint": "Единый ключ ко всем моделям мира (Claude 5.5, GPT-5.2, Gemini 3.8, DeepSeek, Qwen).",
        "hint_i18n": {
            "ru": "Единый ключ ко всем моделям мира (Claude 5.5, GPT-5.2, Gemini 3.8, DeepSeek, Qwen). Список моделей по API грузится даже без ключа!",
            "uk": "Єдиний ключ до всіх моделей світу (Claude 5.5, GPT-5.2, Gemini 3.8, DeepSeek, Qwen). Список моделей по API завантажується навіть без ключа!",
            "en": "Single API key for all models (Claude 5.5, GPT-5.2, Gemini 3.8, DeepSeek, Qwen). Model list can be fetched even without a key!",
        },
        "suggested_models": [
            {"id": "anthropic/claude-opus-5.5", "name": "Claude Opus 5.5 (OpenRouter)"},
            {"id": "anthropic/claude-sonnet-5.5", "name": "Claude Sonnet 5.5 (OpenRouter)"},
            {"id": "openai/gpt-5.2", "name": "OpenAI GPT-5.2 (OpenRouter)"},
            {"id": "openai/gpt-5.1", "name": "OpenAI GPT-5.1 (OpenRouter)"},
            {"id": "google/gemini-3.8-pro", "name": "Google Gemini 3.8 Pro (OpenRouter)"},
            {"id": "google/gemini-3.8-flash", "name": "Google Gemini 3.8 Flash (OpenRouter)"},
            {"id": "deepseek/deepseek-r1", "name": "DeepSeek R1"},
            {"id": "deepseek/deepseek-chat-v3-0324:free", "name": "DeepSeek V3 (Free :free)"},
            {"id": "meta-llama/llama-3.3-70b-instruct:free", "name": "Llama 3.3 70B (Free :free)"},
        ],
    },
    "deepseek": {
        "name": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "needs_key": True,
        "key_placeholder": "sk-...",
        "hint": "Официальный API DeepSeek. Ключ: platform.deepseek.com",
        "hint_i18n": {
            "ru": "Официальный API DeepSeek. Ключ: platform.deepseek.com",
            "uk": "Офіційний API DeepSeek. Ключ: platform.deepseek.com",
            "en": "Official DeepSeek API. Key: platform.deepseek.com",
        },
        "suggested_models": [
            {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
            {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1)"},
        ],
    },
    "glm": {
        "name": "GLM / Zhipu AI",
        "protocol": "openai",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4.6",
        "needs_key": True,
        "key_placeholder": "Zhipu GLM API Key...",
        "hint": "API Zhipu BigModel (GLM-4.6 / GLM-4.5-Air).",
        "hint_i18n": {
            "ru": "API Zhipu BigModel (GLM-4.6 / GLM-4.5-Air).",
            "uk": "API Zhipu BigModel (GLM-4.6 / GLM-4.5-Air).",
            "en": "Zhipu BigModel API (GLM-4.6 / GLM-4.5-Air).",
        },
        "suggested_models": [
            {"id": "glm-4.6", "name": "GLM-4.6 (Flagship)"},
            {"id": "glm-4.5-air", "name": "GLM-4.5 Air (Free/Fast)"},
        ],
    },
    "groq": {
        "name": "Groq Cloud (Fast / Free Tier)",
        "protocol": "openai",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "needs_key": True,
        "key_placeholder": "gsk_...",
        "hint": "Сверхбыстрый инференс на LPU Groq. Ключ: console.groq.com",
        "hint_i18n": {
            "ru": "Сверхбыстрый инференс на LPU Groq (есть бесплатный тариф). Ключ: console.groq.com",
            "uk": "Надшвидкий інференс на LPU Groq (є безкоштовний тариф). Ключ: console.groq.com",
            "en": "Ultra-fast LPU inference on Groq (Free tier available). Key: console.groq.com",
        },
        "suggested_models": [
            {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
            {"id": "deepseek-r1-distill-llama-70b", "name": "DeepSeek R1 Distill Llama 70B"},
            {"id": "qwen-qwq-32b", "name": "Qwen QwQ 32B"},
        ],
    },
    "cerebras": {
        "name": "Cerebras (Ultra-Fast)",
        "protocol": "openai",
        "base_url": "https://api.cerebras.ai/v1",
        "default_model": "llama3.3-70b",
        "needs_key": True,
        "key_placeholder": "csk-...",
        "hint": "API Cerebras Cloud. Ключ: cloud.cerebras.ai",
        "hint_i18n": {
            "ru": "API Cerebras Cloud (бесплатный быстрый тариф). Ключ: cloud.cerebras.ai",
            "uk": "API Cerebras Cloud (безкоштовний швидкий тариф). Ключ: cloud.cerebras.ai",
            "en": "Cerebras Cloud API (fast free tier). Key: cloud.cerebras.ai",
        },
        "suggested_models": [
            {"id": "llama3.3-70b", "name": "Llama 3.3 70B"},
            {"id": "qwen-3-32b", "name": "Qwen 3 32B"},
        ],
    },
    "xai": {
        "name": "xAI (Grok)",
        "protocol": "openai",
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-4",
        "needs_key": True,
        "key_placeholder": "xai-...",
        "hint": "API xAI Grok. Ключ: console.x.ai",
        "hint_i18n": {
            "ru": "API xAI Grok. Ключ: console.x.ai",
            "uk": "API xAI Grok. Ключ: console.x.ai",
            "en": "xAI Grok API. Key: console.x.ai",
        },
        "suggested_models": [
            {"id": "grok-4", "name": "Grok 4"},
            {"id": "grok-3", "name": "Grok 3"},
            {"id": "grok-3-mini", "name": "Grok 3 Mini"},
        ],
    },
    "ollama": {
        "name": "Ollama (Local PC)",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:11434/v1",
        "default_model": "qwen3:14b",
        "needs_key": False,
        "key_placeholder": "No key required",
        "hint": "Локальный сервер Ollama (127.0.0.1:11434).",
        "hint_i18n": {
            "ru": "Локальный сервер Ollama. Нажмите «🔄 Загрузить по API», чтобы подтянуть установленные у вас локальные модели.",
            "uk": "Локальний сервер Ollama. Натисніть «🔄 Завантажити по API», щоб підтягнути встановлені локальні моделі.",
            "en": "Local Ollama server. Click '🔄 Fetch via API' to load your locally installed models.",
        },
        "suggested_models": [
            {"id": "qwen3:32b", "name": "Qwen 3 32B (Local)"},
            {"id": "qwen3:14b", "name": "Qwen 3 14B (Local)"},
            {"id": "deepseek-r1:14b", "name": "DeepSeek R1 14B (Local)"},
            {"id": "gemma3:12b", "name": "Gemma 3 12B (Local)"},
        ],
    },
    "lmstudio": {
        "name": "LM Studio / vLLM (Local)",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:1234/v1",
        "default_model": "local-model",
        "needs_key": False,
        "key_placeholder": "No key required",
        "hint": "Локальный сервер LM Studio, vLLM или LocalAI.",
        "hint_i18n": {
            "ru": "Локальный сервер LM Studio, vLLM или LocalAI с OpenAI-совместимым API.",
            "uk": "Локальний сервер LM Studio, vLLM або LocalAI з OpenAI-сумісним API.",
            "en": "Local LM Studio, vLLM, or LocalAI server with OpenAI-compatible API.",
        },
        "suggested_models": [
            {"id": "local-model", "name": "LM Studio Active Model"},
        ],
    },
    "custom": {
        "name": "Custom API / Proxy",
        "protocol": "openai",
        "base_url": "https://api.openai.com/v1",
        "default_model": "",
        "needs_key": False,
        "key_placeholder": "API Key...",
        "hint": "Любой собственный сервер или прокси (OpenAI / Anthropic).",
        "hint_i18n": {
            "ru": "Любой собственный endpoint, корпоративный шлюз или прокси с поддержкой протокола OpenAI (/chat/completions) или Anthropic (/messages).",
            "uk": "Будь-який власний endpoint, корпоративний шлюз або проксі з підтримкою протоколу OpenAI (/chat/completions) або Anthropic (/messages).",
            "en": "Any custom endpoint, gateway, or proxy supporting OpenAI (/chat/completions) or Anthropic (/messages) protocol.",
        },
        "suggested_models": [],
    },
}

# Мультиязычный справочник настроек OrcaSlicer:
# (group_ru, group_uk, group_en) -> [(key, label_ru, label_uk, label_en, category), ...]
SLICER_SETTINGS_I18N: list[tuple[tuple[str, str, str], list[tuple[str, str, str, str, str]]]] = [
    (
        ("Слои и периметры (process)", "Шари та периметри (process)", "Layers & Perimeters (process)"),
        [
            ("layer_height", "Высота слоя (мм)", "Висота шару (мм)", "Layer height (mm)", "process"),
            ("initial_layer_print_height", "Высота первого слоя (мм)", "Висота першого шару (мм)", "First layer height (mm)", "process"),
            ("wall_loops", "Количество стенок (периметров)", "Кількість стінок (периметрів)", "Wall loops (perimeters)", "process"),
            ("top_shell_layers", "Верхние сплошные слои", "Верхні суцільні шари", "Top shell layers", "process"),
            ("bottom_shell_layers", "Нижние сплошные слои", "Нижні суцільні шари", "Bottom shell layers", "process"),
            ("top_shell_thickness", "Толщина крышки (мм)", "Товщина кришки (мм)", "Top shell thickness (mm)", "process"),
            ("bottom_shell_thickness", "Толщина дна (мм)", "Товщина дна (мм)", "Bottom shell thickness (mm)", "process"),
            ("wall_generator", "Генератор стенок (classic/arachne)", "Генератор стінок (classic/arachne)", "Wall generator (classic/arachne)", "process"),
            ("inner_wall_line_width", "Ширина линии внутренней стенки", "Ширина лінії внутрішньої стінки", "Inner wall line width", "process"),
            ("outer_wall_line_width", "Ширина линии внешней стенки", "Ширина лінії зовнішньої стінки", "Outer wall line width", "process"),
            ("initial_layer_line_width", "Ширина линии первого слоя", "Ширина лінії першого шару", "First layer line width", "process"),
            ("seam_position", "Позиция шва (aligned/nearest/back/random)", "Позиція шва (aligned/nearest/back/random)", "Seam position (aligned/nearest/back/random)", "process"),
            ("detect_thin_wall", "Обнаружение тонких стенок", "Виявлення тонких стінок", "Detect thin walls", "process"),
            ("only_one_wall_top", "Одна стенка на верхних поверхностях", "Одна стінка на верхніх поверхнях", "Only one wall on top surfaces", "process"),
        ],
    ),
    (
        ("Заполнение и прочность (process)", "Заповнення та міцність (process)", "Infill & Strength (process)"),
        [
            ("sparse_infill_density", "Плотность заполнения (%)", "Щільність заповнення (%)", "Sparse infill density (%)", "process"),
            ("sparse_infill_pattern", "Шаблон заполнения", "Шаблон заповнення", "Sparse infill pattern", "process"),
            ("top_surface_pattern", "Шаблон верхней поверхности", "Шаблон верхньої поверхні", "Top surface pattern", "process"),
            ("bottom_surface_pattern", "Шаблон нижней поверхности", "Шаблон нижньої поверхні", "Bottom surface pattern", "process"),
            ("infill_wall_overlap", "Перекрытие заполнения и стенок (%)", "Перекриття заповнення та стінок (%)", "Infill/wall overlap (%)", "process"),
            ("infill_combination", "Комбинирование заполнения", "Комбінування заповнення", "Infill combination", "process"),
            ("minimum_sparse_infill_area", "Мин. площадь разреженного заполнения", "Мін. площа розрідженого заповнення", "Minimum sparse infill area", "process"),
        ],
    ),
    (
        ("Скорости и ускорения (process)", "Швидкості та прискорення (process)", "Speeds & Accelerations (process)"),
        [
            ("initial_layer_speed", "Скорость первого слоя (мм/с)", "Швидкість першого шару (мм/с)", "First layer speed (mm/s)", "process"),
            ("initial_layer_infill_speed", "Скорость заполнения 1-го слоя (мм/с)", "Швидкість заповнення 1-го шару (мм/с)", "First layer infill speed (mm/s)", "process"),
            ("outer_wall_speed", "Скорость внешней стенки (мм/с)", "Швидкість зовнішньої стінки (мм/с)", "Outer wall speed (mm/s)", "process"),
            ("inner_wall_speed", "Скорость внутренней стенки (мм/с)", "Швидкість внутрішньої стінки (мм/с)", "Inner wall speed (mm/s)", "process"),
            ("sparse_infill_speed", "Скорость заполнения (мм/с)", "Швидкість заповнення (мм/с)", "Sparse infill speed (mm/s)", "process"),
            ("internal_solid_infill_speed", "Скорость сплошного заполнения (мм/с)", "Швидкість суцільного заповнення (мм/с)", "Internal solid infill speed (mm/s)", "process"),
            ("top_surface_speed", "Скорость верхней поверхности (мм/с)", "Швидкість верхньої поверхні (мм/с)", "Top surface speed (mm/s)", "process"),
            ("bridge_speed", "Скорость мостов (мм/с)", "Швидкість мостів (мм/с)", "Bridge speed (mm/s)", "process"),
            ("gap_infill_speed", "Скорость заполнения зазоров (мм/с)", "Швидкість заповнення проміжків (мм/с)", "Gap infill speed (mm/s)", "process"),
            ("support_speed", "Скорость поддержек (мм/с)", "Швидкість підтримок (мм/с)", "Support speed (mm/s)", "process"),
            ("travel_speed", "Скорость холостых перемещений (мм/с)", "Швидкість холостих переміщень (мм/с)", "Travel speed (mm/s)", "process"),
            ("slow_down_for_layer_cooling", "Замедление для охлаждения слоя", "Уповільнення для охолодження шару", "Slow down for layer cooling", "process"),
            ("default_acceleration", "Стандартное ускорение (мм/с²)", "Стандартне прискорення (мм/с²)", "Default acceleration (mm/s²)", "process"),
            ("outer_wall_acceleration", "Ускорение внешней стенки (мм/с²)", "Прискорення зовнішньої стінки (мм/с²)", "Outer wall acceleration (mm/s²)", "process"),
            ("initial_layer_acceleration", "Ускорение первого слоя (мм/с²)", "Прискорення першого шару (мм/с²)", "First layer acceleration (mm/s²)", "process"),
        ],
    ),
    (
        ("Поддержки и адгезия к столу (process)", "Підтримки та адгезія до столу (process)", "Supports & Bed Adhesion (process)"),
        [
            ("enable_support", "Поддержки включены (0/1)", "Підтримки увімкнено (0/1)", "Enable support (0/1)", "process"),
            ("support_type", "Тип поддержек (normal/tree)", "Тип підтримок (normal/tree)", "Support type (normal/tree)", "process"),
            ("support_style", "Стиль поддержек", "Стиль підтримок", "Support style", "process"),
            ("support_threshold_angle", "Пороговый угол поддержек (°)", "Пороговий кут підтримок (°)", "Support threshold angle (°)", "process"),
            ("support_on_build_plate_only", "Поддержки только от стола (0/1)", "Підтримки тільки від столу (0/1)", "Support on build plate only (0/1)", "process"),
            ("support_top_z_distance", "Верхний Z-зазор поддержек (мм)", "Верхній Z-зазор підтримок (мм)", "Support top Z distance (mm)", "process"),
            ("support_bottom_z_distance", "Нижний Z-зазор поддержек (мм)", "Нижній Z-зазор підтримок (мм)", "Support bottom Z distance (mm)", "process"),
            ("support_object_xy_distance", "XY-зазор поддержки до модели (мм)", "XY-зазор підтримки до моделі (мм)", "Support object XY distance (mm)", "process"),
            ("support_interface_top_layers", "Верхние интерфейсные слои поддержек", "Верхні інтерфейсні шари підтримок", "Support interface top layers", "process"),
            ("brim_type", "Тип каймы (no_brim/outer_only/inner_only/outer_and_inner/auto_brim)", "Тип кайми (brim_type)", "Brim type (no_brim/outer_only/inner_only/outer_and_inner/auto_brim)", "process"),
            ("brim_width", "Ширина каймы (мм)", "Ширина кайми (мм)", "Brim width (mm)", "process"),
            ("brim_object_gap", "Зазор каймы до детали (мм)", "Зазор кайми до деталі (мм)", "Brim object gap (mm)", "process"),
            ("skirt_loops", "Петли юбки (Skirt)", "Петлі спідниці (Skirt)", "Skirt loops", "process"),
            ("raft_layers", "Слои рафта (Raft)", "Шари рафта (Raft)", "Raft layers", "process"),
        ],
    ),
    (
        ("Филамент, температуры и обдув (filament)", "Філамент, температури та обдув (filament)", "Filament, Temperatures & Cooling (filament)"),
        [
            ("filament_type", "Тип пластика", "Тип пластику", "Filament type", "filament"),
            ("filament_vendor", "Производитель филамента", "Виробник філаменту", "Filament vendor", "filament"),
            ("nozzle_temperature", "Температура сопла (°C)", "Температура сопла (°C)", "Nozzle temperature (°C)", "filament"),
            ("nozzle_temperature_initial_layer", "Температура сопла 1-й слой (°C)", "Температура сопла 1-й шар (°C)", "Nozzle temp first layer (°C)", "filament"),
            ("hot_plate_temp", "Температура стола (°C)", "Температура столу (°C)", "Hot plate temp (°C)", "filament"),
            ("hot_plate_temp_initial_layer", "Температура стола 1-й слой (°C)", "Температура столу 1-й шар (°C)", "Hot plate temp first layer (°C)", "filament"),
            ("textured_plate_temp", "Температура текстур. стола (°C)", "Температура текстур. столу (°C)", "Textured plate temp (°C)", "filament"),
            ("textured_plate_temp_initial_layer", "Темп. текстур. стола 1-й слой (°C)", "Темп. текстур. столу 1-й шар (°C)", "Textured plate temp 1st layer (°C)", "filament"),
            ("cool_plate_temp", "Температура холодного стола (°C)", "Температура холодного столу (°C)", "Cool plate temp (°C)", "filament"),
            ("eng_plate_temp", "Температура инж. стола (°C)", "Температура інж. столу (°C)", "Engineering plate temp (°C)", "filament"),
            ("filament_flow_ratio", "Коэффициент потока (Flow Ratio)", "Коефіцієнт потоку (Flow Ratio)", "Filament flow ratio", "filament"),
            ("filament_max_volumetric_speed", "Макс. объёмная скорость (мм³/с)", "Макс. об'ємна швидкість (мм³/с)", "Max volumetric speed (mm³/s)", "filament"),
            ("enable_pressure_advance", "Pressure Advance включён (0/1)", "Pressure Advance увімкнено (0/1)", "Enable Pressure Advance (0/1)", "filament"),
            ("pressure_advance", "Значение Pressure Advance", "Значення Pressure Advance", "Pressure Advance value", "filament"),
            ("fan_max_speed", "Макс. скорость обдува (%)", "Макс. швидкість обдуву (%)", "Max fan speed (%)", "filament"),
            ("fan_min_speed", "Мин. скорость обдува (%)", "Мін. швидкість обдуву (%)", "Min fan speed (%)", "filament"),
            ("overhang_fan_speed", "Обдув нависаний и мостов (%)", "Обдув нависань та мостів (%)", "Overhang fan speed (%)", "filament"),
            ("close_fan_the_first_x_layers", "Отключить обдув на первых N слоях", "Вимкнути обдув на перших N шарах", "Disable fan for first N layers", "filament"),
            ("fan_cooling_layer_time", "Порог времени слоя для макс. обдува (с)", "Поріг часу шару для макс. обдуву (с)", "Fan cooling layer time threshold (s)", "filament"),
            ("slow_down_layer_time", "Мин. время печати слоя (с)", "Мін. час друку шару (с)", "Slow down layer time (s)", "filament"),
            ("slow_down_min_speed", "Мин. скорость при замедлении (мм/с)", "Мін. швидкість при уповільненні (мм/с)", "Min print speed when slowing down (mm/s)", "filament"),
        ],
    ),
    (
        ("Принтер и ретракт (printer)", "Принтер та ретракт (printer)", "Printer & Retraction (printer)"),
        [
            ("printer_model", "Модель принтера", "Модель принтера", "Printer model", "printer"),
            ("nozzle_diameter", "Диаметр сопла (мм)", "Діаметр сопла (мм)", "Nozzle diameter (mm)", "printer"),
            ("printable_height", "Высота области печати (мм)", "Висота області друку (мм)", "Printable height (mm)", "printer"),
            ("curr_bed_type", "Текущий тип стола", "Поточний тип столу", "Current bed type", "printer"),
            ("retraction_length", "Длина ретракта (мм)", "Довжина ретракту (мм)", "Retraction length (mm)", "printer"),
            ("retraction_speed", "Скорость ретракта (мм/с)", "Швидкість ретракту (мм/с)", "Retraction speed (mm/s)", "printer"),
            ("deretraction_speed", "Скорость возврата ретракта (мм/с)", "Швидкість повернення ретракту (мм/с)", "Deretraction speed (mm/s)", "printer"),
            ("z_hop", "Подъём Z при ретракте (Z-hop, мм)", "Підйом Z при ретракті (Z-hop, мм)", "Z-hop when retracting (mm)", "printer"),
            ("z_hop_types", "Тип Z-hop", "Тип Z-hop", "Z-hop type", "printer"),
            ("retract_when_changing_layer", "Ретракт при смене слоя", "Ретракт при зміні шару", "Retract when changing layer", "printer"),
            ("wipe", "Протирка сопла (Wipe)", "Витирання сопла (Wipe)", "Wipe nozzle", "printer"),
        ],
    ),
]

FLAT_SETTING_INFO: dict[str, dict[str, str]] = {}
for (_grp_ru, _grp_uk, _grp_en), _items in SLICER_SETTINGS_I18N:
    for _key, _l_ru, _l_uk, _l_en, _cat in _items:
        FLAT_SETTING_INFO[_key] = {
            "ru": _l_ru,
            "uk": _l_uk,
            "en": _l_en,
            "category": _cat,
        }


def get_system_prompt(lang: str) -> str:
    l = norm_lang(lang)
    if l == "uk":
        return """Ти — експертний інтерактивний ШІ-асистент всередині OrcaSlicer 2.5 («Orca AI Assistant»).
Твоє завдання — допомагати користувачеві ідеально підготувати 3D-модель до друку, аналізувати геометрію деталей на столі (габарити, площу контакту першого шару, коефіцієнти стійкості, площу нависань >45° та >60°, помилки сітки), перевіряти налаштування профілю слайсера, діагностувати дефекти друку за фото та аналізувати G-code.

Правила роботи:
1. Завжди відповідай зрозумілою, грамотною УКРАЇНСЬКОЮ мовою. Будь конкретним, доброзичливим і технічно точним.
2. Спирайся на реальні дані з блоку «КОНТЕКСТ ORCASLICER» (об'єкти на столі, геометрія, нависання, активні пресети принтера, філаменту та процесу). Не вигадуй значення, якщо вони вже передані в контексті.
3. Коли ти рекомендуєш змінити конкретні параметри в OrcaSlicer, ОБОВ'ЯЗКОВО продублюй їх у кінці своєї відповіді у спеціальному блоці ```orca-settings (валідний JSON-масив), щоб користувач міг застосувати їх у профіль слайсера однією кнопкою!

Формат блоку для автоматичного застосування налаштувань:
```orca-settings
[
  {
    "category": "process",
    "key": "wall_loops",
    "label": "Кількість стінок",
    "value": "4",
    "reason": "Збільшення жорсткості навантаженої деталі"
  },
  {
    "category": "process",
    "key": "enable_support",
    "label": "Підтримки",
    "value": "1",
    "reason": "Виявлено значні нависання >45°"
  }
]
```
Важливі правила для блоку ```orca-settings:
- Поле "category" має бути одним із: "process", "filament", "printer".
- Поле "key" має бути точним внутрішнім ключем OrcaSlicer (наприклад: layer_height, wall_loops, sparse_infill_density, sparse_infill_pattern, enable_support, support_type, support_threshold_angle, brim_type, brim_width, outer_wall_speed, inner_wall_speed, initial_layer_speed, top_surface_speed, nozzle_temperature, hot_plate_temp, textured_plate_temp, fan_max_speed, overhang_fan_speed, retraction_length, z_hop, seam_position тощо).
- Поле "value" завжди передавай рядком у форматі OrcaSlicer: булеві прапорці як "1" або "0", відсотки щільності заповнення як "25%" (для sparse_infill_density), числа як "0.2" або "3".
"""
    if l == "en":
        return """You are an expert interactive AI Assistant inside OrcaSlicer 2.5 ("Orca AI Assistant").
Your job is to help the user prepare 3D models for printing, analyze build plate geometry (dimensions, first-layer bed contact area, height-to-base stability ratio, overhang areas >45° and >60°, manifold/mesh errors), audit slicer profile settings, diagnose print defects from photos, and inspect G-code.

Operating Rules:
1. Always respond in clear, natural, and technically accurate ENGLISH.
2. Rely on the real data provided in the "ORCASLICER CONTEXT" section (plated objects, geometry, overhangs, active printer/filament/process presets). Never invent parameter values if they are already provided in the context.
3. Whenever you recommend changing specific OrcaSlicer settings, ALWAYS include them at the end of your response inside a fenced ```orca-settings JSON array block so the user can apply them to OrcaSlicer in 1 click!

Format for automatic setting application:
```orca-settings
[
  {
    "category": "process",
    "key": "wall_loops",
    "label": "Wall loops",
    "value": "4",
    "reason": "Increase structural rigidity for functional part"
  },
  {
    "category": "process",
    "key": "enable_support",
    "label": "Enable support",
    "value": "1",
    "reason": "Significant overhangs >45° detected"
  }
]
```
Important rules for ```orca-settings:
- "category" must be one of: "process", "filament", "printer".
- "key" must be an exact OrcaSlicer config key (e.g. layer_height, wall_loops, sparse_infill_density, sparse_infill_pattern, enable_support, support_type, support_threshold_angle, brim_type, brim_width, outer_wall_speed, inner_wall_speed, initial_layer_speed, top_surface_speed, nozzle_temperature, hot_plate_temp, textured_plate_temp, fan_max_speed, overhang_fan_speed, retraction_length, z_hop, seam_position, etc.).
- "value" must always be a string formatted for OrcaSlicer: booleans as "1" or "0", infill density percentages as "25%" (for sparse_infill_density), numbers as "0.2" or "3".
"""
    return """Ты — экспертный интерактивный ИИ-ассистент внутри OrcaSlicer 2.5 («Orca AI Assistant»).
Твоя задача — помогать пользователю идеально подготовить 3D-модель к печати, анализировать геометрию деталей на столе (габариты, площадь контакта первого слоя, коэффициенты устойчивости, площади нависаний >45° и >60°, ошибки сетки), проверять настройки профиля слайсера, диагностировать дефекты печати по фото и анализировать G-code.

Правила работы:
1. Всегда отвечай на понятном, грамотном РУССКОМ языке. Будь конкретным, дружелюбным и технически точным.
2. Опирайся на реальные данные из блока «КОНТЕКСТ ORCASLICER» (объекты на столе, геометрия, нависания, активные пресеты принтера, филамента и процесса). Не выдумывай значения, если они уже переданы в контексте.
3. Когда ты рекомендуешь изменить конкретные параметры в OrcaSlicer, ОБЯЗАТЕЛЬНО продублируй их в конце своего ответа в специальном блоке ```orca-settings (валидный JSON-массив), чтобы пользователь мог применить их в профиль слайсера одной кнопкой!

Формат блока для автоматического применения настроек:
```orca-settings
[
  {
    "category": "process",
    "key": "wall_loops",
    "label": "Количество стенок",
    "value": "4",
    "reason": "Увеличение жёсткости нагруженной детали"
  },
  {
    "category": "process",
    "key": "enable_support",
    "label": "Поддержки",
    "value": "1",
    "reason": "Обнаружены значительные нависания >45°"
  }
]
```
Важные правила для блока ```orca-settings:
- Поле "category" должно быть одним из: "process", "filament", "printer".
- Поле "key" должно быть точным внутренним ключом OrcaSlicer (например: layer_height, wall_loops, sparse_infill_density, sparse_infill_pattern, enable_support, support_type, support_threshold_angle, brim_type, brim_width, outer_wall_speed, inner_wall_speed, initial_layer_speed, top_surface_speed, nozzle_temperature, hot_plate_temp, textured_plate_temp, fan_max_speed, overhang_fan_speed, retraction_length, z_hop, seam_position и т.д.).
- Поле "value" всегда передавай строкой в формате OrcaSlicer: булевы флаги как "1" или "0", проценты плотности заполнения как "25%" (для sparse_infill_density), числа как "0.2" или "3".
"""


# ============================================================================
# 2. ХРАНИЛИЩЕ ДАННЫХ И НАСТРОЕК (С ПОДДЕРЖКОЙ ЯЗЫКА И КЛЮЧЕЙ МОДЕЛЕЙ)
# ============================================================================

def get_plugin_storage_dir() -> Path:
    here = Path(__file__).resolve().parent
    for parent in here.parents:
        if parent.name == "orca_plugins":
            target = parent / "plugin_data" / PLUGIN_ID
            try:
                target.mkdir(parents=True, exist_ok=True)
                return target
            except Exception:
                break
    try:
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "OrcaSlicer"
        target = base / "orca_plugins" / "plugin_data" / PLUGIN_ID
        target.mkdir(parents=True, exist_ok=True)
        return target
    except Exception:
        return here


def _try_import_legacy_printpurr_keys() -> dict[str, Any]:
    imported: dict[str, Any] = {}
    try:
        base = Path(os.environ.get("APPDATA", str(Path.home()))) / "OrcaSlicer"
        legacy_path = base / ".print_purr" / "settings.json"
        if legacy_path.is_file():
            raw = json.loads(legacy_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                keys = raw.get("api_keys")
                if isinstance(keys, dict):
                    imported["api_keys"] = {str(k): str(v) for k, v in keys.items() if v}
                urls = raw.get("base_urls")
                if isinstance(urls, dict):
                    imported["base_urls"] = {str(k): str(v) for k, v in urls.items() if v}
    except Exception:
        pass
    return imported


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


def detect_default_language() -> str:
    try:
        import locale
        loc = (locale.getlocale()[0] or os.environ.get("LANG") or "").lower()
        if loc.startswith(("uk", "ua")):
            return "uk"
        if loc.startswith("ru"):
            return "ru"
    except Exception:
        pass
    return "en"


def default_settings() -> dict[str, Any]:
    return {
        "schema_version": 3,
        "language": detect_default_language(),
        "provider": "anthropic",
        "model": "claude-opus-5-5",
        "temperature": 0.3,
        "max_tokens": 4096,
        "reasoning_effort": "low",
        "auto_attach_context": True,
        "enable_slicing_audit": False,
        "custom_user_instructions": "",
        "api_keys": {p: "" for p in PROVIDER_PRESETS},
        "model_api_keys": {},  # Индивидуальные API-ключи для конкретных моделей {"provider::model": "sk-..."}
        "base_urls": {p: info["base_url"] for p, info in PROVIDER_PRESETS.items()},
        "custom_protocol": "openai",
        "favorite_models": default_favorites(),
        "cached_models": {},
    }


class StorageManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._dir = get_plugin_storage_dir()
        self._settings_file = self._dir / "settings.json"
        self._chats_file = self._dir / "chats.json"
        self._settings = self._load_settings()
        self._chats = self._load_chats()

    def _load_settings(self) -> dict[str, Any]:
        defaults = default_settings()
        if not self._settings_file.is_file():
            legacy = _try_import_legacy_printpurr_keys()
            if legacy.get("api_keys"):
                for k, v in legacy["api_keys"].items():
                    if v:
                        defaults["api_keys"][k] = v
                for prov in ("anthropic", "gemini", "openai", "openrouter", "groq", "glm"):
                    if defaults["api_keys"].get(prov):
                        defaults["provider"] = prov
                        defaults["model"] = PROVIDER_PRESETS[prov]["default_model"]
                        break
            if legacy.get("base_urls"):
                for k, v in legacy["base_urls"].items():
                    if v:
                        defaults["base_urls"][k] = v
            self._save_json(self._settings_file, defaults)
            return defaults

        try:
            data = json.loads(self._settings_file.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return defaults
            merged = dict(defaults)
            for k, v in data.items():
                if k in ("api_keys", "model_api_keys", "base_urls", "cached_models") and isinstance(v, dict):
                    merged[k] = {**defaults.get(k, {}), **v}
                else:
                    merged[k] = v

            merged["language"] = norm_lang(merged.get("language", "ru"))
            cur_model = str(merged.get("model") or "")
            if cur_model in RETIRED_MODEL_MIGRATIONS:
                merged["model"] = RETIRED_MODEL_MIGRATIONS[cur_model]
            if int(data.get("schema_version") or 1) < 2:
                merged["schema_version"] = 3
                merged["favorite_models"] = default_favorites()
                self._save_json(self._settings_file, merged)

            return merged
        except Exception:
            return defaults

    def _load_chats(self) -> dict[str, Any]:
        if self._chats_file.is_file():
            try:
                data = json.loads(self._chats_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("sessions"), list) and data["sessions"]:
                    return data
            except Exception:
                pass
        first_id = f"chat_{int(time.time() * 1000)}"
        initial = {
            "active_id": first_id,
            "sessions": [
                {
                    "id": first_id,
                    "title": "New Chat",
                    "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                    "messages": [],
                }
            ],
        }
        self._save_json(self._chats_file, initial)
        return initial

    def _save_json(self, path: Path, payload: Any) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._settings))

    def get_lang(self) -> str:
        with self._lock:
            return norm_lang(self._settings.get("language", "ru"))

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for k, v in patch.items():
                if k == "language":
                    self._settings["language"] = norm_lang(v)
                elif k in ("api_keys", "model_api_keys", "base_urls", "cached_models") and isinstance(v, dict):
                    self._settings.setdefault(k, {}).update(v)
                else:
                    self._settings[k] = v
            self._save_json(self._settings_file, self._settings)
            return json.loads(json.dumps(self._settings))

    def resolve_effective_api_key(self, provider: str, model_id: str) -> str:
        with self._lock:
            m_keys = self._settings.get("model_api_keys") or {}
            specific = str(m_keys.get(f"{provider}::{model_id}") or m_keys.get(model_id) or "").strip()
            if specific:
                return specific
            p_keys = self._settings.get("api_keys") or {}
            return str(p_keys.get(provider) or "").strip()

    def import_from_printpurr(self) -> tuple[int, dict[str, Any]]:
        with self._lock:
            legacy = _try_import_legacy_printpurr_keys()
            count = 0
            for k, v in legacy.get("api_keys", {}).items():
                if v:
                    self._settings.setdefault("api_keys", {})[k] = v
                    count += 1
            for k, v in legacy.get("base_urls", {}).items():
                if v:
                    self._settings.setdefault("base_urls", {})[k] = v
            self._save_json(self._settings_file, self._settings)
            return count, json.loads(json.dumps(self._settings))

    def get_chats(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._chats))

    def save_chats(self, chats_data: dict[str, Any]) -> None:
        with self._lock:
            self._chats = chats_data
            self._save_json(self._chats_file, self._chats)

    def append_message_to_active(self, role: str, content: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            sessions = self._chats.setdefault("sessions", [])
            active_id = self._chats.get("active_id")
            target = next((s for s in sessions if s.get("id") == active_id), None)
            if target is None:
                first_id = f"chat_{int(time.time() * 1000)}"
                target = {
                    "id": first_id,
                    "title": "New Chat",
                    "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                    "messages": [],
                }
                sessions.insert(0, target)
                self._chats["active_id"] = first_id

            msg: dict[str, Any] = {
                "role": role,
                "content": content,
                "timestamp": dt.datetime.now().strftime("%H:%M"),
            }
            if extra:
                msg.update(extra)
            target.setdefault("messages", []).append(msg)

            if role == "user" and target.get("title") in ("Новый диалог", "Новий діалог", "New Chat", "", None):
                clean_title = re.sub(r"\s+", " ", content).strip()[:42]
                if clean_title:
                    target["title"] = clean_title

            self._save_json(self._chats_file, self._chats)
            return json.loads(json.dumps(self._chats))


# ============================================================================
# 3. ГЛУБОКИЙ 3D-АНАЛИЗАТОР МОДЕЛИ, НАВИСАНИЙ И ПРОФИЛЯ ORCASLICER
# ============================================================================

def _extract_value_str(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (list, tuple)):
        if not val:
            return ""
        first = val[0]
        if isinstance(first, bool):
            return "1" if first else "0"
        return str(first)
    return str(val)


def inspect_slicer_presets(lang: str = "ru") -> dict[str, Any]:
    l = norm_lang(lang)
    not_def = tr(l, "Не определен", "Не визначено", "Not detected")
    result: dict[str, Any] = {
        "printer_preset": not_def,
        "process_preset": not_def,
        "filament_presets": [],
        "groups": {},
        "flat_values": {},
    }
    try:
        bundle = orca.host.preset_bundle()
        if bundle is None:
            return result

        try:
            pr = bundle.current_printer_preset()
            if pr and getattr(pr, "name", None):
                result["printer_preset"] = str(pr.name)
        except Exception:
            pass

        try:
            proc = bundle.current_process_preset()
            if proc and getattr(proc, "name", None):
                result["process_preset"] = str(proc.name)
        except Exception:
            pass

        try:
            fils = list(bundle.current_filament_preset_names() or [])
            result["filament_presets"] = [str(f) for f in fils if f]
        except Exception:
            pass

        idx_map = {"ru": 0, "uk": 1, "en": 2}
        lang_idx = idx_map.get(l, 0)

        for grp_titles, items in SLICER_SETTINGS_I18N:
            group_title = grp_titles[lang_idx]
            group_entries = []
            for key, l_ru, l_uk, l_en, category in items:
                try:
                    raw_val = bundle.full_config_value(key)
                except Exception:
                    raw_val = None
                val_str = _extract_value_str(raw_val)
                if val_str != "":
                    label = (l_ru, l_uk, l_en)[lang_idx]
                    result["flat_values"][key] = val_str
                    group_entries.append({
                        "key": key,
                        "label": label,
                        "category": category,
                        "value": val_str,
                    })
            if group_entries:
                result["groups"][group_title] = group_entries
    except Exception as exc:
        result["error"] = str(exc)
    return result


def _analyze_volume_geometry_numpy(vol: Any, inst_matrix: Any | None) -> dict[str, float] | None:
    if np is None:
        return None
    try:
        mesh = vol.mesh()
        if mesh is None:
            return None
        verts = np.asarray(mesh.vertices(), dtype=np.float32)
        tris = np.asarray(mesh.triangles(), dtype=np.int32)
        if verts.ndim != 2 or verts.shape[1] != 3 or tris.ndim != 2 or tris.shape[1] != 3 or len(tris) == 0:
            return None

        total_mat = np.eye(4, dtype=np.float32)
        try:
            v_mat = np.asarray(vol.matrix(), dtype=np.float32)
            if v_mat.shape == (4, 4):
                total_mat = v_mat @ total_mat
        except Exception:
            pass
        if inst_matrix is not None:
            try:
                i_mat = np.asarray(inst_matrix, dtype=np.float32)
                if i_mat.shape == (4, 4):
                    total_mat = i_mat @ total_mat
            except Exception:
                pass

        rot = total_mat[:3, :3]
        trans = total_mat[:3, 3]
        t_verts = verts @ rot.T + trans

        v0 = t_verts[tris[:, 0]]
        v1 = t_verts[tris[:, 1]]
        v2 = t_verts[tris[:, 2]]

        cross_vec = np.cross(v1 - v0, v2 - v0)
        norms = np.linalg.norm(cross_vec, axis=1)
        areas = 0.5 * norms
        valid = norms > 1e-7
        nz = np.zeros_like(norms)
        nz[valid] = cross_vec[valid, 2] / norms[valid]

        z_min = float(np.min(t_verts[:, 2]))
        z_max = float(np.max(t_verts[:, 2]))
        x_span = float(np.max(t_verts[:, 0]) - np.min(t_verts[:, 0]))
        y_span = float(np.max(t_verts[:, 1]) - np.min(t_verts[:, 1]))
        z_span = max(0.0, z_max - z_min)

        tri_z_max = np.maximum(np.maximum(v0[:, 2], v1[:, 2]), v2[:, 2])
        tri_z_min = np.minimum(np.minimum(v0[:, 2], v1[:, 2]), v2[:, 2])

        total_area = float(np.sum(areas))
        bed_mask = (tri_z_max <= (z_min + 0.30)) & (nz < -0.5)
        bed_contact_area = float(np.sum(areas[bed_mask]))

        above_first_layer = tri_z_min > (z_min + 0.35)
        overhang_45_mask = above_first_layer & (nz < -0.7071)
        overhang_60_mask = above_first_layer & (nz < -0.8660)

        overhang_45_area = float(np.sum(areas[overhang_45_mask]))
        overhang_60_area = float(np.sum(areas[overhang_60_mask]))

        return {
            "size_x": round(x_span, 2),
            "size_y": round(y_span, 2),
            "size_z": round(z_span, 2),
            "total_surface_mm2": round(total_area, 1),
            "bed_contact_mm2": round(bed_contact_area, 1),
            "overhang_45_mm2": round(overhang_45_area, 1),
            "overhang_60_mm2": round(overhang_60_area, 1),
            "overhang_45_pct": round((overhang_45_area / total_area * 100.0) if total_area > 0 else 0.0, 1),
            "overhang_60_pct": round((overhang_60_area / total_area * 100.0) if total_area > 0 else 0.0, 1),
        }
    except Exception:
        return None


def inspect_plate_geometry(lang: str = "ru") -> dict[str, Any]:
    l = norm_lang(lang)
    summary: dict[str, Any] = {
        "has_model": False,
        "object_count": 0,
        "total_instances": 0,
        "total_volume_cm3": 0.0,
        "total_triangles": 0,
        "total_bed_contact_mm2": 0.0,
        "total_overhang_45_mm2": 0.0,
        "total_overhang_60_mm2": 0.0,
        "objects": [],
        "warnings": [],
    }
    try:
        model = orca.host.model()
        if model is None:
            return summary
        objs = list(model.objects() or [])
        if not objs:
            return summary

        summary["has_model"] = True
        summary["object_count"] = len(objs)

        for idx, obj in enumerate(objs, start=1):
            default_obj_name = tr(l, f"Объект #{idx}", f"Об'єкт #{idx}", f"Object #{idx}")
            obj_name = str(getattr(obj, "name", "") or default_obj_name)
            instances = list(obj.instances() or [])
            inst_count = max(1, len(instances))
            first_inst_mat = None
            size_x = size_y = size_z = 0.0

            if instances:
                try:
                    first_inst_mat = instances[0].matrix()
                except Exception:
                    first_inst_mat = None
                try:
                    ibb = instances[0].bounding_box()
                    if ibb is not None:
                        isz = ibb.size() if callable(getattr(ibb, "size", None)) else getattr(ibb, "size", None)
                        if isz is not None:
                            if hasattr(isz, "x"):
                                size_x, size_y, size_z = round(float(isz.x), 2), round(float(isz.y), 2), round(float(isz.z), 2)
                            elif isinstance(isz, (list, tuple)) and len(isz) >= 3:
                                size_x, size_y, size_z = round(float(isz[0]), 2), round(float(isz[1]), 2), round(float(isz[2]), 2)
                except Exception:
                    pass

            if size_x == 0.0 and size_y == 0.0:
                try:
                    bb = obj.raw_mesh_bounding_box()
                    if bb is not None:
                        sz = bb.size() if callable(getattr(bb, "size", None)) else getattr(bb, "size", None)
                        if sz is not None:
                            if hasattr(sz, "x"):
                                size_x, size_y, size_z = round(float(sz.x), 2), round(float(sz.y), 2), round(float(sz.z), 2)
                            elif isinstance(sz, (list, tuple)) and len(sz) >= 3:
                                size_x, size_y, size_z = round(float(sz[0]), 2), round(float(sz[1]), 2), round(float(sz[2]), 2)
                except Exception:
                    pass

            vol_cm3 = 0.0
            triangles = 0
            mesh_errors = 0
            is_manifold = True
            has_modifiers = False
            support_painted = False
            seam_painted = False
            bed_contact_mm2 = 0.0
            overhang_45_mm2 = 0.0
            overhang_60_mm2 = 0.0
            total_surface_mm2 = 0.0

            for vol in list(obj.volumes() or []):
                try:
                    if vol.is_modifier() or vol.is_negative_volume() or vol.is_support_enforcer() or vol.is_support_blocker():
                        has_modifiers = True
                except Exception:
                    pass
                try:
                    if not vol.is_model_part():
                        continue
                except Exception:
                    pass

                try:
                    mesh_errors += int(vol.mesh_errors_count() or 0)
                except Exception:
                    pass
                try:
                    if vol.is_fdm_support_painted():
                        support_painted = True
                    if vol.is_seam_painted():
                        seam_painted = True
                except Exception:
                    pass

                try:
                    m = vol.mesh()
                    if m is not None:
                        vol_cm3 += float(m.volume() or 0.0) / 1000.0
                        triangles += int(m.triangle_count() or 0)
                        if not m.is_manifold():
                            is_manifold = False
                except Exception:
                    pass

                geo = _analyze_volume_geometry_numpy(vol, first_inst_mat)
                if geo:
                    size_x = max(size_x, geo["size_x"])
                    size_y = max(size_y, geo["size_y"])
                    size_z = max(size_z, geo["size_z"])
                    bed_contact_mm2 += geo["bed_contact_mm2"]
                    overhang_45_mm2 += geo["overhang_45_mm2"]
                    overhang_60_mm2 += geo["overhang_60_mm2"]
                    total_surface_mm2 += geo["total_surface_mm2"]

            min_base = max(0.1, min(size_x, size_y))
            height_ratio = round(size_z / min_base, 2) if min_base > 0 else 0.0
            overhang_45_pct = round((overhang_45_mm2 / total_surface_mm2 * 100.0) if total_surface_mm2 > 0 else 0.0, 1)

            obj_info = {
                "name": obj_name,
                "instances": inst_count,
                "size_x": round(size_x, 2),
                "size_y": round(size_y, 2),
                "size_z": round(size_z, 2),
                "volume_cm3": round(vol_cm3, 2),
                "triangles": triangles,
                "is_manifold": is_manifold,
                "mesh_errors": mesh_errors,
                "bed_contact_mm2": round(bed_contact_mm2, 1),
                "total_surface_mm2": round(total_surface_mm2, 1),
                "overhang_45_mm2": round(overhang_45_mm2, 1),
                "overhang_60_mm2": round(overhang_60_mm2, 1),
                "overhang_45_pct": overhang_45_pct,
                "height_to_base_ratio": height_ratio,
                "has_modifiers": has_modifiers,
                "support_painted": support_painted,
                "seam_painted": seam_painted,
            }
            summary["objects"].append(obj_info)

            summary["total_instances"] += inst_count
            summary["total_volume_cm3"] = round(summary["total_volume_cm3"] + vol_cm3 * inst_count, 2)
            summary["total_triangles"] += triangles * inst_count
            summary["total_bed_contact_mm2"] = round(summary["total_bed_contact_mm2"] + bed_contact_mm2 * inst_count, 1)
            summary["total_overhang_45_mm2"] = round(summary["total_overhang_45_mm2"] + overhang_45_mm2 * inst_count, 1)
            summary["total_overhang_60_mm2"] = round(summary["total_overhang_60_mm2"] + overhang_60_mm2 * inst_count, 1)

            if not is_manifold or mesh_errors > 0:
                summary["warnings"].append({
                    "level": "danger",
                    "text": tr(
                        l,
                        f"«{obj_name}»: незамкнутая сетка (non-manifold) или ошибки геометрии ({mesh_errors} шт.). Рекомендуется выполнить ремонт модели.",
                        f"«{obj_name}»: незамкнена сітка (non-manifold) або помилки геометрії ({mesh_errors} шт.). Рекомендується виконати ремонт моделі.",
                        f"\"{obj_name}\": non-manifold mesh or geometry errors ({mesh_errors}). Mesh repair is recommended.",
                    ),
                })
            if bed_contact_mm2 < 120.0 and size_z > 15.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: малая площадь контакта первого слоя со столом ({bed_contact_mm2:.0f} мм²) при высоте {size_z:.1f} мм — высокий риск отрыва, рекомендуется кайма (Brim).",
                        f"«{obj_name}»: мала площа контакту першого шару зі столом ({bed_contact_mm2:.0f} мм²) при висоті {size_z:.1f} мм — високий ризик відриву, рекомендується кайма (Brim).",
                        f"\"{obj_name}\": small first-layer bed contact area ({bed_contact_mm2:.0f} mm²) at height {size_z:.1f} mm — detachment risk, Brim is recommended.",
                    ),
                })
            elif height_ratio >= 2.8 and size_z >= 40.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: высокая и узкая деталь (отношение высоты к базе {height_ratio}:1) — рекомендуется кайма (Brim) и снижение ускорений.",
                        f"«{obj_name}»: висока та вузька деталь (відношення висоти до бази {height_ratio}:1) — рекомендується кайма (Brim) та зниження прискорень.",
                        f"\"{obj_name}\": tall and narrow part (height-to-base ratio {height_ratio}:1) — Brim and reduced accelerations recommended.",
                    ),
                })
            if overhang_60_mm2 > 25.0 or overhang_45_mm2 > 80.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: обнаружены нависания >45° ({overhang_45_mm2:.0f} мм², {overhang_45_pct}% поверхности; критических >60°: {overhang_60_mm2:.0f} мм²) — проверьте включение поддержек или ориентацию.",
                        f"«{obj_name}»: виявлено нависання >45° ({overhang_45_mm2:.0f} мм², {overhang_45_pct}% поверхні; критичних >60°: {overhang_60_mm2:.0f} мм²) — перевірте увімкнення підтримок або орієнтацію.",
                        f"\"{obj_name}\": overhangs >45° detected ({overhang_45_mm2:.0f} mm², {overhang_45_pct}% surface; critical >60°: {overhang_60_mm2:.0f} mm²) — check supports or part orientation.",
                    ),
                })
    except Exception as exc:
        summary["error"] = str(exc)

    return summary


def build_full_context_markdown(plate: dict[str, Any], presets: dict[str, Any], custom_instructions: str = "", lang: str = "ru") -> str:
    l = norm_lang(lang)
    lines = [tr(
        l,
        "=== КОНТЕКСТ ORCASLICER (АКТУАЛЬНОЕ СОСТОЯНИЕ) ===",
        "=== КОНТЕКСТ ORCASLICER (АКТУАЛЬНИЙ СТАН) ===",
        "=== ORCASLICER CONTEXT (LIVE STATE) ===",
    )]
    if custom_instructions.strip():
        lines.append(f"\n[{tr(l, 'Профиль и пожелания пользователя', 'Профіль та побажання користувача', 'User Printer Profile & Preferences')}]: {custom_instructions.strip()}")

    lines.append(f"\n1. {tr(l, 'АКТИВНЫЕ ПРОФИЛИ', 'АКТИВНІ ПРОФІЛІ', 'ACTIVE PRESETS')}:")
    lines.append(f"- {tr(l, 'Принтер', 'Принтер', 'Printer')}: {presets.get('printer_preset', '—')}")
    lines.append(f"- {tr(l, 'Процесс (слои/качество)', 'Процес (шари/якість)', 'Process (quality/layers)')}: {presets.get('process_preset', '—')}")
    fils = presets.get("filament_presets") or []
    lines.append(f"- {tr(l, 'Филамент', 'Філамент', 'Filament')}: {', '.join(fils) if fils else '—'}")

    lines.append(f"\n2. {tr(l, '3D-МОДЕЛИ НА СТОЛЕ', '3D-МОДЕЛІ НА СТОЛІ', '3D MODELS ON BUILD PLATE')}:")
    if not plate.get("has_model"):
        lines.append(f"- {tr(l, 'На столе сейчас нет загруженных 3D-моделей.', 'На столі зараз немає завантажених 3D-моделей.', 'No 3D models currently loaded on the build plate.')}")
    else:
        lines.append(
            f"- Objects: {plate['object_count']} (instances: {plate['total_instances']}), "
            f"volume: {plate['total_volume_cm3']} cm³, triangles: {plate['total_triangles']}, "
            f"1st-layer bed contact: {plate['total_bed_contact_mm2']} mm², "
            f"overhangs >45°: {plate['total_overhang_45_mm2']} mm² (critical >60°: {plate['total_overhang_60_mm2']} mm²)."
        )
        for o in plate.get("objects", []):
            flags = []
            if not o["is_manifold"] or o["mesh_errors"] > 0:
                flags.append(f"MESH ERRORS ({o['mesh_errors']})")
            else:
                flags.append("manifold OK")
            if o["support_painted"]:
                flags.append("painted supports")
            if o["seam_painted"]:
                flags.append("painted seam")
            if o["has_modifiers"]:
                flags.append("has modifiers")
            lines.append(
                f"  • {o['name']} (x{o['instances']}): size {o['size_x']}×{o['size_y']}×{o['size_z']} mm, "
                f"vol {o['volume_cm3']} cm³, bed contact {o['bed_contact_mm2']} mm², "
                f"H/B ratio {o['height_to_base_ratio']}:1, "
                f"overhangs >45°: {o['overhang_45_mm2']} mm² ({o['overhang_45_pct']}%), "
                f"critical >60°: {o['overhang_60_mm2']} mm² [{', '.join(flags)}]"
            )
        if plate.get("warnings"):
            lines.append(f"- {tr(l, 'Геометрические предупреждения', 'Геометричні попередження', 'Geometry warnings')}:")
            for w in plate["warnings"]:
                lines.append(f"  ! {w['text']}")

    lines.append(f"\n3. {tr(l, 'ТЕКУЩИЕ НАСТРОЙКИ СЛАЙСЕРА', 'ПОТОЧНІ НАЛАШТУВАННЯ СЛАЙСЕРА', 'CURRENT SLICER SETTINGS')}:")
    for group_name, entries in (presets.get("groups") or {}).items():
        lines.append(f"[{group_name}]")
        for item in entries:
            lines.append(f"  {item['key']} ({item['label']}) = {item['value']}")

    return "\n".join(lines)


# ============================================================================
# 4. ПРИМЕНЕНИЕ НАСТРОЕК В ПРОФИЛЬ ORCASLICER И АНАЛИЗ G-CODE
# ============================================================================

def _normalize_preset_category(key: str, raw_cat: str) -> str:
    # Если ключ известен в справочнике OrcaSlicer, его истинная категория надёжнее догадки ИИ
    if key in FLAT_SETTING_INFO:
        return FLAT_SETTING_INFO[key]["category"]
    c = (raw_cat or "").strip().lower()
    if c in ("filament", "filaments", "material", "materials"):
        return "filament"
    if c in ("printer", "printers", "machine", "extruder"):
        return "printer"
    return "process"


def apply_settings_to_orcaslicer(changes: list[dict[str, Any]], lang: str = "ru") -> dict[str, Any]:
    l = norm_lang(lang)
    applied: list[dict[str, Any]] = []
    errors: list[str] = []

    by_target: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        key = str(ch.get("key") or "").strip()
        if not key:
            continue
        cat = _normalize_preset_category(key, str(ch.get("category") or ""))
        try:
            slot_num = max(1, int(ch.get("slot") or 1)) if cat == "filament" else 0
        except Exception:
            slot_num = 1 if cat == "filament" else 0
        by_target.setdefault((cat, slot_num), []).append(ch)

    for (cat, slot_num), items in by_target.items():
        if not items:
            continue
        try:
            editor = getattr(orca.host.preset, cat, None)
            if editor is None:
                errors.append(tr(
                    l,
                    f"Редактор пресета '{cat}' недоступен.",
                    f"Редактор пресету '{cat}' недоступний.",
                    f"Preset editor '{cat}' is unavailable.",
                ))
                continue

            # В OrcaSlicer 2.5+ filament.begin_update() принимает 1-based slot_number,
            # а process/printer вызываются без аргументов.
            tx = editor.begin_update(slot_num) if cat == "filament" else editor.begin_update()
            pending: list[dict[str, Any]] = []
            for item in items:
                k = str(item["key"]).strip()
                v = str(item.get("value", "")).strip()
                try:
                    tx.set(k, v)
                    pending.append({"category": cat, "key": k, "value": v, "label": item.get("label", k)})
                except Exception as key_exc:
                    errors.append(f"{k} = {v}: {key_exc}")
            if pending:
                tx.commit()
                applied.extend(pending)
        except Exception as exc:
            errors.append(f"{cat}: {exc}")

    return {
        "ok": len(applied) > 0 and len(errors) == 0,
        "applied": applied,
        "errors": errors,
    }


def summarize_gcode_text(gcode_text: str, filename: str = "sliced.gcode") -> dict[str, Any]:
    lines = gcode_text.splitlines()
    head_lines: list[str] = []
    tail_lines: list[str] = []
    layer_count = 0
    max_z = 0.0
    m104_set: set[str] = set()
    m140_set: set[str] = set()
    has_pause = False

    for i, line in enumerate(lines):
        s = line.strip()
        if i < 220 and s.startswith(";"):
            head_lines.append(s)
        if s.startswith("; CHANGE_LAYER") or s.startswith(";LAYER:"):
            layer_count += 1
        elif s.startswith(("M104 ", "M109 ")):
            m = re.search(r"S(\d+(?:\.\d+)?)", s)
            if m and float(m.group(1)) > 50:
                m104_set.add(m.group(1))
        elif s.startswith(("M140 ", "M190 ")):
            m = re.search(r"S(\d+(?:\.\d+)?)", s)
            if m and float(m.group(1)) > 20:
                m140_set.add(m.group(1))
        elif s.startswith(("M600", "M25", "PAUSE")):
            has_pause = True
        elif s.startswith("; Z_HEIGHT:"):
            try:
                max_z = max(max_z, float(s.split(":", 1)[1].strip()))
            except Exception:
                pass
        if s.startswith(";") and len(s) > 2:
            tail_lines.append(s)
            if len(tail_lines) > 90:
                tail_lines.pop(0)

    return {
        "ok": True,
        "filename": filename,
        "size_mb": round(len(gcode_text.encode("utf-8", errors="ignore")) / (1024 * 1024), 2),
        "header_comments": [l for l in head_lines if len(l) > 2][:60],
        "footer_comments": tail_lines[-80:],
        "layer_count": layer_count,
        "max_z": round(max_z, 2),
        "m104_temps": sorted(m104_set),
        "m140_temps": sorted(m140_set),
        "has_m600_pause": has_pause,
    }


# ============================================================================
# 5. КЛИЕНТ ИИ-ПРОВАЙДЕРОВ (ЗАГРУЗКА СПИСКА МОДЕЛЕЙ И ЗАПРОСЫ К ЧАТУ)
# ============================================================================

def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


def fetch_provider_models(
    provider: str,
    base_url: str,
    api_key: str,
    custom_protocol: str = "openai",
    lang: str = "ru",
    timeout: float = 20.0,
) -> dict[str, Any]:
    l = norm_lang(lang)
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    protocol = custom_protocol if provider == "custom" else preset["protocol"]
    clean_base = (base_url or preset["base_url"]).strip().rstrip("/")
    clean_key = (api_key or "").strip()

    if preset.get("needs_key") and provider != "openrouter" and not clean_key:
        return {
            "ok": False,
            "needs_key": True,
            "error": tr(
                l,
                f"Для загрузки списка моделей с сервера «{preset['name']}» сначала введите ваш API-ключ в поле ключа ниже!",
                f"Для завантаження списку моделей із сервера «{preset['name']}» спочатку введіть ваш API-ключ у поле ключа нижче!",
                f"To fetch the model list from \"{preset['name']}\", please enter your API key in the key field below first!",
            ),
            "models": [],
        }

    models_url = f"{clean_base}/models"
    headers: dict[str, str] = {
        "Accept": "application/json",
        "User-Agent": f"OrcaAIAssistant/{PLUGIN_VERSION}",
    }

    if protocol == "anthropic":
        if clean_key:
            headers["x-api-key"] = clean_key
        headers["anthropic-version"] = "2023-06-01"
    else:
        if clean_key:
            headers["Authorization"] = f"Bearer {clean_key}"

    ctx = _create_ssl_context() if models_url.startswith("https://") else None
    req = urllib.request.Request(models_url, headers=headers, method="GET")

    models: list[dict[str, str]] = []
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw)
            items = payload.get("data") or payload.get("models") or (payload if isinstance(payload, list) else [])
            for item in items:
                if isinstance(item, str):
                    models.append({"id": item, "name": item})
                elif isinstance(item, dict):
                    mid = str(item.get("id") or item.get("name") or "").strip()
                    if not mid:
                        continue
                    if provider == "gemini" and mid.startswith("models/"):
                        mid = mid[len("models/"):]
                    mname = str(item.get("display_name") or item.get("name") or mid).strip()
                    models.append({"id": mid, "name": mname})
    except Exception as first_exc:
        if provider == "ollama" or "11434" in clean_base:
            try:
                root_url = re.sub(r"/v1$", "", clean_base)
                tags_req = urllib.request.Request(f"{root_url}/api/tags", headers=headers, method="GET")
                with urllib.request.urlopen(tags_req, timeout=timeout, context=ctx) as resp2:
                    raw2 = resp2.read().decode("utf-8", errors="replace")
                    payload2 = json.loads(raw2)
                    for item in payload2.get("models", []):
                        mid = str(item.get("name") or item.get("model") or "").strip()
                        if mid:
                            models.append({"id": mid, "name": mid})
            except Exception:
                return {
                    "ok": False,
                    "error": tr(
                        l,
                        f"Не удалось подключиться к локальной Ollama ({models_url}): {first_exc}",
                        f"Не вдалося підключитися до локальної Ollama ({models_url}): {first_exc}",
                        f"Could not connect to local Ollama ({models_url}): {first_exc}",
                    ),
                    "models": [],
                }
        else:
            err_detail = str(first_exc)
            if isinstance(first_exc, urllib.error.HTTPError):
                try:
                    err_body = first_exc.read().decode("utf-8", errors="replace")[:300]
                    err_detail = f"HTTP {first_exc.code}: {err_body}"
                except Exception:
                    pass
            return {
                "ok": False,
                "error": tr(
                    l,
                    f"Ошибка загрузки моделей ({models_url}): {err_detail}",
                    f"Помилка завантаження моделей ({models_url}): {err_detail}",
                    f"Failed to load models ({models_url}): {err_detail}",
                ),
                "models": [],
            }

    seen: set[str] = set()
    unique_models: list[dict[str, str]] = []
    for m in models:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique_models.append(m)
    unique_models.sort(key=lambda x: x["id"].lower())

    return {"ok": True, "models": unique_models, "count": len(unique_models)}


def send_chat_completion(
    provider: str,
    base_url: str,
    api_key: str,
    model_id: str,
    messages: list[dict[str, Any]],
    system_prompt: str,
    temperature: float = 0.3,
    max_tokens: int = 4096,
    custom_protocol: str = "openai",
    image_attachment: dict[str, str] | None = None,
    lang: str = "ru",
    reasoning_effort: str = "low",
    on_chunk: Any = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    l = norm_lang(lang)
    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    protocol = custom_protocol if provider == "custom" else preset["protocol"]
    clean_base = (base_url or preset["base_url"]).strip().rstrip("/")
    clean_key = (api_key or "").strip()
    clean_model = (model_id or preset["default_model"]).strip()
    clean_effort = str(reasoning_effort or "").strip().lower()
    use_stream = callable(on_chunk)

    if preset.get("needs_key") and not clean_key:
        return {
            "ok": False,
            "needs_key": True,
            "error": tr(
                l,
                f"Для модели «{clean_model}» ({preset['name']}) не введён API-ключ! Нажмите кнопку «🔑 API-ключ» в верхней панели и вставьте ваш ключ.",
                f"Для моделі «{clean_model}» ({preset['name']}) не введено API-ключ! Натисніть кнопку «🔑 API-ключ» у верхній панелі та вставте ваш ключ.",
                f"No API key entered for model \"{clean_model}\" ({preset['name']})! Click the \"🔑 API Key\" button in the top bar and paste your key.",
            ),
        }

    ctx = _create_ssl_context() if clean_base.startswith("https://") else None

    if protocol == "anthropic":
        url = f"{clean_base}/messages"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json" if use_stream else "application/json",
            "x-api-key": clean_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": f"OrcaAIAssistant/{PLUGIN_VERSION}",
        }
        anth_messages: list[dict[str, Any]] = []
        for idx, m in enumerate(messages):
            role = "assistant" if m.get("role") == "assistant" else "user"
            text_content = str(m.get("content") or "")
            is_last_user = (idx == len(messages) - 1) and role == "user"
            if is_last_user and image_attachment and image_attachment.get("base64"):
                anth_messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": image_attachment.get("mime", "image/jpeg"),
                                "data": image_attachment["base64"],
                            },
                        },
                        {"type": "text", "text": text_content},
                    ],
                })
            else:
                anth_messages.append({"role": role, "content": text_content})

        body: dict[str, Any] = {
            "model": clean_model,
            "max_tokens": int(max_tokens or 4096),
            "system": system_prompt,
            "messages": anth_messages,
        }
        if use_stream:
            body["stream"] = True
        # В современных моделях Claude (Opus/Sonnet/Haiku 5.x, Fable 5.2, Opus 4.7+) параметр temperature устарел (HTTP 400)
        if clean_model.startswith("claude-3"):
            body["temperature"] = float(temperature)
    else:
        url = f"{clean_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json" if use_stream else "application/json",
            "User-Agent": f"OrcaAIAssistant/{PLUGIN_VERSION}",
        }
        if clean_key:
            headers["Authorization"] = f"Bearer {clean_key}"
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://orcaslicer.com"
            headers["X-Title"] = "Orca AI Assistant"

        oai_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        for idx, m in enumerate(messages):
            role = m.get("role") if m.get("role") in ("user", "assistant", "system") else "user"
            text_content = str(m.get("content") or "")
            is_last_user = (idx == len(messages) - 1) and role == "user"
            if is_last_user and image_attachment and image_attachment.get("base64"):
                mime = image_attachment.get("mime", "image/jpeg")
                b64 = image_attachment["base64"]
                oai_messages.append({
                    "role": "user",
                    "content": [
                        {"type": "text", "text": text_content},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                })
            else:
                oai_messages.append({"role": role, "content": text_content})

        body = {
            "model": clean_model,
            "messages": oai_messages,
            "max_tokens": int(max_tokens or 4096),
        }
        if use_stream:
            body["stream"] = True
        model_lower = clean_model.lower()
        no_temp_prefixes = ("o1", "o3", "o4", "gpt-5", "claude-", "deepseek-reasoner", "qwq")
        if not model_lower.startswith(no_temp_prefixes) and "/claude-" not in model_lower and "/gpt-5" not in model_lower and "/o1" not in model_lower and "/o3" not in model_lower and "/o4" not in model_lower:
            body["temperature"] = float(temperature)

        # Управление глубиной thinking/reasoning (главный способ ускорить Gemini 2.5/3.x и reasoning-модели)
        if clean_effort in ("none", "minimal", "low", "medium", "high"):
            if provider == "gemini" or "gemini" in model_lower or model_lower.startswith(("o1", "o3", "o4", "gpt-5")) or "/o1" in model_lower or "/o3" in model_lower or "/o4" in model_lower or "/gpt-5" in model_lower:
                body["reasoning_effort"] = clean_effort

    def _do_post(payload_dict: dict[str, Any]) -> dict[str, Any]:
        data_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            ctype = str(resp.headers.get("Content-Type") or "").lower()
            is_sse = bool(payload_dict.get("stream")) and ("text/event-stream" in ctype or "event-stream" in ctype)
            if not payload_dict.get("stream") and not is_sse:
                raw_resp = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw_resp)

            # Читаем построчно: если сервер ответил обычным JSON вместо SSE — тоже поддерживаем
            acc_text: list[str] = []
            acc_reason: list[str] = []
            raw_non_sse: list[str] = []
            sse_error: str = ""
            last_emit = 0.0
            saw_sse = is_sse

            while True:
                raw_line = resp.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if not saw_sse and not line.startswith("data:") and not line.startswith("event:"):
                    raw_non_sse.append(line)
                    continue
                if line.startswith("event:") or line.startswith(":"):
                    saw_sse = True
                    continue
                if line.startswith("data:"):
                    saw_sse = True
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        ev = json.loads(data_str)
                    except Exception:
                        continue
                    if not isinstance(ev, dict):
                        continue
                    if ev.get("type") == "error" or ev.get("error"):
                        err_obj = ev.get("error")
                        sse_error = str(err_obj.get("message") if isinstance(err_obj, dict) else err_obj or ev)
                        continue
                    if protocol == "anthropic":
                        ev_type = ev.get("type")
                        if ev_type == "content_block_start":
                            cb = ev.get("content_block") or {}
                            if cb.get("type") == "text" and cb.get("text"):
                                acc_text.append(str(cb.get("text") or ""))
                        elif ev_type == "content_block_delta":
                            delta = ev.get("delta") or {}
                            dtype = delta.get("type")
                            if dtype == "text_delta" or (not dtype and "text" in delta):
                                acc_text.append(str(delta.get("text") or ""))
                            elif dtype == "thinking_delta":
                                acc_reason.append(str(delta.get("thinking") or ""))
                    else:
                        choices = ev.get("choices") or []
                        if choices and isinstance(choices[0], dict):
                            delta = choices[0].get("delta") or {}
                            c_piece = delta.get("content")
                            if isinstance(c_piece, str) and c_piece:
                                acc_text.append(c_piece)
                            r_piece = delta.get("reasoning_content") or delta.get("reasoning")
                            if isinstance(r_piece, str) and r_piece:
                                acc_reason.append(r_piece)

                    if use_stream and acc_text:
                        now = time.monotonic()
                        if now - last_emit >= 0.12:
                            last_emit = now
                            try:
                                on_chunk("".join(acc_text))
                            except Exception:
                                pass

            if not saw_sse and raw_non_sse:
                return json.loads("\n".join(raw_non_sse))

            joined_text = "".join(acc_text)
            joined_reason = "".join(acc_reason)
            if use_stream and joined_text:
                try:
                    on_chunk(joined_text)
                except Exception:
                    pass
            return {"_streamed": True, "_reply": joined_text, "_reasoning": joined_reason, "_error": sse_error}

    api_err_prefix = tr(l, "Ошибка API", "Помилка API", "API Error")
    conn_err_prefix = tr(l, "Ошибка соединения с", "Помилка з'єднання з", "Connection error to")

    try:
        parsed = _do_post(body)
    except urllib.error.HTTPError as http_err:
        err_text = ""
        try:
            err_text = http_err.read().decode("utf-8", errors="replace")
            err_json = json.loads(err_text)
            msg = (
                err_json.get("error", {}).get("message")
                if isinstance(err_json.get("error"), dict)
                else err_json.get("error") or err_text
            )
            err_text = str(msg)
        except Exception:
            err_text = err_text[:400] or str(http_err)

        err_lower = err_text.lower()
        retried = False
        if http_err.code == 400:
            if "temperature" in err_lower and "temperature" in body:
                body.pop("temperature", None)
                retried = True
            if "reasoning_effort" in body and ("reasoning" in err_lower or "unknown" in err_lower or "unsupported" in err_lower or "invalid" in err_lower):
                body.pop("reasoning_effort", None)
                retried = True
            if "stream" in body and "stream" in err_lower:
                body.pop("stream", None)
                retried = True
            if "max_completion_tokens" in err_lower and "max_tokens" in body:
                body["max_completion_tokens"] = body.pop("max_tokens")
                retried = True
            if retried:
                try:
                    parsed = _do_post(body)
                except urllib.error.HTTPError as retry_err:
                    retry_text = ""
                    try:
                        retry_text = retry_err.read().decode("utf-8", errors="replace")
                        retry_json = json.loads(retry_text)
                        retry_msg = (
                            retry_json.get("error", {}).get("message")
                            if isinstance(retry_json.get("error"), dict)
                            else retry_json.get("error") or retry_text
                        )
                        retry_text = str(retry_msg)
                    except Exception:
                        retry_text = retry_text[:400] or str(retry_err)
                    return {"ok": False, "error": f"{api_err_prefix} (HTTP {retry_err.code}): {retry_text}"}
                except Exception as retry_exc:
                    return {"ok": False, "error": f"{conn_err_prefix} {url}: {retry_exc}"}
            else:
                return {"ok": False, "error": f"{api_err_prefix} (HTTP {http_err.code}): {err_text}"}
        else:
            return {"ok": False, "error": f"{api_err_prefix} (HTTP {http_err.code}): {err_text}"}
    except Exception as exc:
        return {"ok": False, "error": f"{conn_err_prefix} {url}: {exc}"}

    if parsed.get("_streamed") and parsed.get("_error") and not str(parsed.get("_reply") or "").strip():
        return {"ok": False, "error": f"{api_err_prefix}: {parsed['_error']}"}

    # Если SSE-стрим вернул пустой ответ (нестандартный прокси/модель), автоматически повторяем без stream
    if parsed.get("_streamed") and not str(parsed.get("_reply") or "").strip() and not str(parsed.get("_reasoning") or "").strip():
        body.pop("stream", None)
        headers["Accept"] = "application/json"
        try:
            parsed = _do_post(body)
        except Exception:
            pass

    reply_text = ""
    reasoning_text = ""
    if parsed.get("_streamed"):
        reply_text = str(parsed.get("_reply") or "")
        reasoning_text = str(parsed.get("_reasoning") or "")
    elif protocol == "anthropic":
        for block in parsed.get("content", []):
            if isinstance(block, dict):
                if block.get("type") == "text":
                    reply_text += str(block.get("text") or "")
                elif block.get("type") == "thinking":
                    reasoning_text += str(block.get("thinking") or "")
    else:
        choices = parsed.get("choices") or []
        if choices and isinstance(choices[0], dict):
            msg_obj = choices[0].get("message") or {}
            content_val = msg_obj.get("content")
            if isinstance(content_val, str):
                reply_text = content_val
            elif isinstance(content_val, list):
                for part in content_val:
                    if isinstance(part, dict) and part.get("type") == "text":
                        reply_text += str(part.get("text") or "")
            reasoning_text = str(msg_obj.get("reasoning_content") or msg_obj.get("reasoning") or "")

    if not reply_text.strip() and reasoning_text.strip():
        reply_text = reasoning_text

    if not reply_text.strip():
        return {
            "ok": False,
            "error": tr(
                l,
                f"Пустой ответ от модели {clean_model}. Сырой ответ: {str(parsed)[:300]}",
                f"Порожня відповідь від моделі {clean_model}. Сира відповідь: {str(parsed)[:300]}",
                f"Empty response from model {clean_model}. Raw response: {str(parsed)[:300]}",
            ),
        }

    return {
        "ok": True,
        "reply": reply_text.strip(),
        "reasoning": reasoning_text.strip(),
        "model": clean_model,
    }


def extract_suggested_settings(reply_text: str, current_flat_values: dict[str, str], lang: str = "ru") -> list[dict[str, Any]]:
    l = norm_lang(lang)
    suggestions: list[dict[str, Any]] = []
    pattern = re.compile(r"```(?:orca-settings|orca_settings)\s*(\[[\s\S]*?\])\s*```", re.IGNORECASE)
    for match in pattern.finditer(reply_text):
        try:
            arr = json.loads(match.group(1))
            if not isinstance(arr, list):
                continue
            for item in arr:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key") or "").strip()
                if not key:
                    continue
                info = FLAT_SETTING_INFO.get(key, {})
                default_label = info.get(l) or info.get("ru") or key
                default_cat = info.get("category", "process")
                cat = str(item.get("category") or default_cat).strip().lower()
                if cat not in ("process", "filament", "printer"):
                    cat = default_cat
                label = str(item.get("label") or default_label).strip()
                new_val = str(item.get("value", "")).strip()
                reason = str(item.get("reason") or "").strip()
                cur_val = current_flat_values.get(key, "—")
                suggestions.append({
                    "category": cat,
                    "key": key,
                    "label": label,
                    "current_value": cur_val,
                    "value": new_val,
                    "reason": reason,
                })
        except Exception:
            continue
    return suggestions


# ============================================================================
# 6. МУЛЬТИЯЗЫЧНЫЙ ИНТЕРФЕЙС (RU / UK / EN) — HTML / CSS / JS
# ============================================================================

UI_HTML = r"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Orca AI Assistant</title>
<style>
:root {
  --bg-main: #14171a;
  --bg-panel: #1c2126;
  --bg-card: #232a31;
  --bg-input: #181d22;
  --border: #2e3740;
  --border-accent: #0f968b;
  --accent: #0f968b;
  --accent-hover: #13b2a5;
  --accent-soft: rgba(15, 150, 139, 0.16);
  --text: #e6edf3;
  --text-muted: #93a1b0;
  --danger: #e5534b;
  --warn: #d29922;
  --ok: #2ea043;
  --radius: 10px;
  --font: "Segoe UI", -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
}
* { box-sizing: border-box; }
html, body {
  margin: 0; padding: 0; width: 100%; height: 100%;
  background: var(--bg-main); color: var(--text);
  font-family: var(--font); font-size: 13.5px; line-height: 1.48;
  overflow: hidden;
}
.app-shell {
  display: flex; flex-direction: column;
  width: 100%; height: 100%;
}

/* ЕДИНАЯ ПАНЕЛЬ УПРАВЛЕНИЯ МОДЕЛЬЮ, КЛЮЧАМИ, ЯЗЫКОМ И ВКЛАДКАМИ */
.model-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; padding: 8px 12px;
  background: var(--bg-panel); border-bottom: 1px solid var(--border);
  flex-shrink: 0; flex-wrap: wrap;
}
.model-bar-left {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap; flex: 1;
}
.model-bar-right {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.model-bar label {
  font-size: 11.5px; color: var(--text-muted); font-weight: 600;
}
.ctrl-select, .ctrl-input {
  background: var(--bg-input); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 8px; font-size: 12.5px; outline: none;
}
.ctrl-select:focus, .ctrl-input:focus { border-color: var(--accent); }

.lang-select {
  background: #143532; color: #67ece0;
  border: 1px solid var(--accent); border-radius: 6px;
  padding: 4px 7px; font-size: 12px; font-weight: 700;
  cursor: pointer; outline: none;
}
.lang-select:hover { background: #194541; }

.btn {
  display: inline-flex; align-items: center; justify-content: center; gap: 5px;
  background: var(--bg-card); color: var(--text);
  border: 1px solid var(--border); border-radius: 6px;
  padding: 5px 10px; font-size: 12px; font-weight: 600;
  cursor: pointer; transition: all 0.15s; white-space: nowrap;
}
.btn:hover { border-color: var(--accent); background: #2a333c; }
.btn-primary {
  background: var(--accent); border-color: var(--accent); color: #fff;
}
.btn-primary:hover { background: var(--accent-hover); }
.btn-warn {
  background: rgba(210, 153, 34, 0.2); border-color: var(--warn); color: #ffd866;
}
.btn-warn:hover { background: rgba(210, 153, 34, 0.32); }
.btn-ok {
  background: rgba(46, 160, 67, 0.2); border-color: var(--ok); color: #7ee787;
}
.btn-sm { padding: 4px 9px; font-size: 11.5px; }
.btn-danger { border-color: rgba(229,83,75,0.4); color: #ff8e88; }
.btn-danger:hover { background: rgba(229,83,75,0.18); border-color: var(--danger); }

/* ВЫПАДАЮЩАЯ ПРЯМАЯ ПАНЕЛЬ ВВОДА API-КЛЮЧА */
.inline-key-drawer {
  display: none; flex-direction: column; gap: 8px;
  padding: 10px 14px; background: #192229;
  border-bottom: 2px solid var(--accent); flex-shrink: 0;
}
.inline-key-drawer.open { display: flex; }
.key-drawer-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
}
.key-drawer-help {
  font-size: 12px; color: #7ee787; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px;
}
.key-drawer-help.missing { color: #ffd866; }

/* ИЗБРАННЫЕ МОДЕЛИ-ЧИПСЫ */
.fav-bar {
  display: flex; align-items: center; gap: 5px; padding: 5px 12px;
  background: rgba(24, 29, 34, 0.85); border-bottom: 1px solid var(--border);
  overflow-x: auto; flex-shrink: 0;
}
.fav-chip {
  background: var(--bg-card); color: var(--text-muted);
  border: 1px solid var(--border); border-radius: 999px;
  padding: 2px 10px; font-size: 11.5px; cursor: pointer; white-space: nowrap;
}
.fav-chip:hover { color: var(--text); border-color: var(--accent); }
.fav-chip.active {
  background: var(--accent-soft); color: #5ce6da; border-color: var(--accent); font-weight: 600;
}

/* ОСНОВНЫЕ ВКЛАДКИ */
.tab-view { display: none; flex: 1; overflow: hidden; }
.tab-view.active { display: flex; flex-direction: column; }

/* ВКЛАДКА ЧАТА */
.chat-layout {
  display: flex; flex: 1; overflow: hidden;
}
.chat-sidebar {
  width: 210px; background: var(--bg-panel); border-right: 1px solid var(--border);
  display: flex; flex-direction: column; flex-shrink: 0;
}
@media (max-width: 720px) {
  .chat-sidebar { display: none; }
}
.sidebar-head {
  padding: 8px; border-bottom: 1px solid var(--border);
  display: flex; gap: 6px;
}
.session-list {
  flex: 1; overflow-y: auto; padding: 6px; display: flex; flex-direction: column; gap: 4px;
}
.session-item {
  padding: 7px 9px; border-radius: 7px; cursor: pointer;
  border: 1px solid transparent; display: flex; align-items: center; justify-content: space-between;
  color: var(--text-muted); font-size: 12px;
}
.session-item:hover { background: var(--bg-card); color: var(--text); }
.session-item.active {
  background: var(--accent-soft); border-color: var(--accent); color: var(--text); font-weight: 600;
}
.session-title {
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1;
}
.session-del {
  background: none; border: none; color: var(--text-muted); cursor: pointer;
  padding: 0 4px; font-size: 13px; visibility: hidden;
}
.session-item:hover .session-del { visibility: visible; }
.session-del:hover { color: var(--danger); }

.chat-main {
  flex: 1; display: flex; flex-direction: column; overflow: hidden;
}

/* МИНИ-СВОДКА СТОЛА И ПРОФИЛЯ НАД ЧАТОМ */
.context-strip {
  display: flex; align-items: center; justify-content: space-between;
  gap: 8px; padding: 6px 12px; background: var(--bg-card);
  border-bottom: 1px solid var(--border); font-size: 12px; flex-wrap: wrap;
}
.context-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.c-badge {
  background: var(--bg-input); border: 1px solid var(--border);
  padding: 2px 8px; border-radius: 6px; font-size: 11.5px; color: var(--text-muted);
}
.c-badge strong { color: var(--text); }
.c-badge.warn { border-color: var(--warn); color: #f2cc60; }
.c-badge.danger { border-color: var(--danger); color: #ff8e88; }
.c-badge.ok { border-color: var(--ok); color: #6bc47d; }

/* СПИСОК СООБЩЕНИЙ */
.messages-area {
  flex: 1; overflow-y: auto; padding: 14px;
  display: flex; flex-direction: column; gap: 12px;
}
.msg-row { display: flex; flex-direction: column; max-width: 92%; }
.msg-row.user { align-self: flex-end; align-items: flex-end; }
.msg-row.assistant { align-self: flex-start; align-items: flex-start; width: 92%; }
.msg-meta {
  font-size: 11px; color: var(--text-muted); margin-bottom: 3px; padding: 0 4px;
}
.msg-bubble {
  padding: 10px 13px; border-radius: 11px;
  background: var(--bg-card); border: 1px solid var(--border);
  word-wrap: break-word; overflow-x: auto; width: 100%;
}
.msg-row.user .msg-bubble {
  background: #144944; border-color: var(--accent); width: auto;
}
.msg-bubble h1, .msg-bubble h2, .msg-bubble h3, .msg-bubble h4 {
  margin: 8px 0 4px 0; color: #67ece0;
}
.msg-bubble p { margin: 5px 0; }
.msg-bubble ul, .msg-bubble ol { margin: 5px 0; padding-left: 20px; }
.msg-bubble code {
  background: rgba(0,0,0,0.35); padding: 1px 5px; border-radius: 4px;
  font-family: Consolas, monospace; font-size: 12px; color: #7ee787;
}
.msg-bubble pre {
  background: #101418; border: 1px solid var(--border); border-radius: 7px;
  padding: 8px 10px; overflow-x: auto; font-size: 12px;
}

/* КАРТОЧКА ИНТЕРАКТИВНОГО ПРИМЕНЕНИЯ НАСТРОЕК В 1 КЛИК */
.settings-apply-card {
  margin-top: 10px; background: var(--bg-input);
  border: 1px solid var(--accent); border-radius: 9px; padding: 10px 12px;
}
.settings-apply-head {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 8px; font-weight: 700; color: #67ece0; font-size: 12.5px;
}
.settings-table {
  width: 100%; border-collapse: collapse; font-size: 12px; margin-bottom: 8px;
}
.settings-table th, .settings-table td {
  border-bottom: 1px solid var(--border); padding: 5px 6px; text-align: left;
}
.settings-table th { color: var(--text-muted); font-weight: 600; }
.val-old { color: var(--text-muted); text-decoration: line-through; margin-right: 4px; }
.val-new { color: #7ee787; font-weight: 700; }

/* БЫСТРЫЕ КНОПКИ СЦЕНАРИЕВ И ВВОД */
.quick-actions {
  display: flex; gap: 6px; padding: 7px 12px;
  background: var(--bg-panel); border-top: 1px solid var(--border);
  overflow-x: auto; flex-shrink: 0;
}
.q-btn {
  background: var(--bg-card); color: var(--text);
  border: 1px solid var(--border); border-radius: 7px;
  padding: 4px 9px; font-size: 11.5px; cursor: pointer; white-space: nowrap;
}
.q-btn:hover { border-color: var(--accent); color: #67ece0; }

.composer {
  display: flex; flex-direction: column; gap: 6px;
  padding: 8px 12px 10px 12px; background: var(--bg-panel);
  border-top: 1px solid var(--border); flex-shrink: 0;
}
.attachment-bar {
  display: none; align-items: center; justify-content: space-between;
  background: var(--accent-soft); border: 1px solid var(--accent);
  border-radius: 6px; padding: 4px 10px; font-size: 12px;
}
.composer-row {
  display: flex; gap: 8px; align-items: flex-end;
}
.composer-row textarea {
  flex: 1; resize: none; height: 54px; min-height: 42px; max-height: 150px;
  background: var(--bg-input); color: var(--text);
  border: 1px solid var(--border); border-radius: 8px;
  padding: 8px 10px; font-family: var(--font); font-size: 13px; outline: none;
}
.composer-row textarea:focus { border-color: var(--accent); }
.composer-controls {
  display: flex; align-items: center; justify-content: space-between;
  font-size: 11.5px; color: var(--text-muted); flex-wrap: wrap; gap: 6px;
}

/* ВКЛАДКА ИНСПЕКТОРА И НАСТРОЕК ПРОВАЙДЕРОВ */
.scroll-page {
  flex: 1; overflow-y: auto; padding: 14px;
  display: flex; flex-direction: column; gap: 14px;
}
.card {
  background: var(--bg-panel); border: 1px solid var(--border);
  border-radius: var(--radius); padding: 14px;
}
.card-title {
  font-size: 14px; font-weight: 700; margin: 0 0 10px 0;
  display: flex; align-items: center; justify-content: space-between; color: #67ece0; flex-wrap: wrap; gap: 8px;
}
.grid-2 {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 12px;
}
.form-group {
  display: flex; flex-direction: column; gap: 4px; margin-bottom: 10px;
}
.form-group label { font-size: 12px; color: var(--text-muted); font-weight: 600; }
.hint-text { font-size: 11.5px; color: var(--text-muted); margin-top: 2px; }

.models-browser {
  max-height: 280px; overflow-y: auto; border: 1px solid var(--border);
  border-radius: 7px; background: var(--bg-input); padding: 6px;
  display: flex; flex-direction: column; gap: 4px;
}
.model-row-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 5px 8px; border-radius: 5px; font-size: 12px;
}
.model-row-item:hover { background: var(--bg-card); }

.warn-box {
  padding: 8px 11px; border-radius: 7px; font-size: 12.5px; margin-bottom: 6px;
  border-left: 4px solid var(--warn); background: rgba(210, 153, 34, 0.12);
}
.warn-box.danger {
  border-left-color: var(--danger); background: rgba(229, 83, 75, 0.14);
}
.status-toast {
  position: fixed; bottom: 16px; right: 16px;
  background: #123e3a; border: 1px solid var(--accent); color: #fff;
  padding: 9px 15px; border-radius: 8px; font-size: 12.5px; font-weight: 600;
  box-shadow: 0 6px 20px rgba(0,0,0,0.55); display: none; z-index: 9999; max-width: 520px;
}
</style>
</head>
<body>
<div class="app-shell">
  <!-- ГЛАВНАЯ ПАНЕЛЬ ВЫБОРА ПРОВАЙДЕРА, МОДЕЛИ, КЛЮЧА, ЯЗЫКА И РАЗДЕЛОВ -->
  <div class="model-bar">
    <div class="model-bar-left">
      <label data-i18n="lbl_provider">Провайдер:</label>
      <select id="topProviderSelect" class="ctrl-select" onchange="onTopProviderChange()"></select>

      <label data-i18n="lbl_model">Модель:</label>
      <select id="topModelSelect" class="ctrl-select" style="min-width:210px; max-width:300px;" onchange="onTopModelSelectChange()"></select>

      <input id="topModelCustomInput" class="ctrl-input" style="width:175px;" data-i18n-placeholder="ph_custom_model" placeholder="Или впишите ID модели..." onchange="onTopCustomModelInput()" />

      <button class="btn btn-sm btn-warn" id="btnToggleKeyDrawer" onclick="toggleKeyDrawer()">🔑 API-ключ</button>
      <button class="btn btn-sm" onclick="fetchModelsFromApi()" id="btnFetchModels" data-i18n="btn_fetch_api">🔄 Загрузить по API</button>
      <button class="btn btn-sm" onclick="addCurrentToFavorites()" data-i18n="btn_add_fav">⭐ В избранное</button>
    </div>

    <div class="model-bar-right">
      <select id="topLangSelect" class="lang-select" onchange="onChangeLanguage(this.value)" title="Язык интерфейса и ответов ИИ / Мова / Language">
        <option value="ru">🇷🇺 RU</option>
        <option value="uk">🇺🇦 UA</option>
        <option value="en">🇬🇧 EN</option>
      </select>
      <button class="btn btn-sm btn-primary" id="tabBtn-chat" onclick="switchTab('chat')" data-i18n="tab_chat">💬 Чат</button>
      <button class="btn btn-sm" id="tabBtn-inspector" onclick="switchTab('inspector')" data-i18n="tab_inspector">📊 3D-Инспектор</button>
      <button class="btn btn-sm" id="tabBtn-settings" onclick="switchTab('settings')" data-i18n="tab_settings">⚙️ Настройки</button>
      <button class="btn btn-sm" onclick="sendAction('open_dock')" data-i18n="btn_dock">📌 У 3D-стола</button>
    </div>
  </div>

  <!-- ВЫДВИЖНАЯ ПАНЕЛЬ БЫСТРОЙ НАСТРОЙКИ API-КЛЮЧА ПРЯМО ПОД МОДЕЛЬЮ -->
  <div class="inline-key-drawer" id="inlineKeyDrawer">
    <div class="key-drawer-help" id="inlineKeyStatusText">
      <span>🔑 API</span>
      <div style="display:flex; gap:6px;">
        <button class="btn btn-sm" onclick="sendAction('import_printpurr')" data-i18n="btn_import_pp">📥 Импорт из PrintPurr</button>
        <button class="btn btn-sm" onclick="switchTab('settings')" data-i18n="btn_open_mgr">⚙️ Все настройки</button>
        <button class="btn btn-sm btn-danger" onclick="toggleKeyDrawer(false)" data-i18n="btn_hide">✕ Скрыть</button>
      </div>
    </div>
    <div class="key-drawer-row">
      <label style="min-width:85px;" data-i18n="lbl_key_scope">Куда ключ:</label>
      <select id="inlineKeyScope" class="ctrl-select" onchange="syncInlineKeyBar()">
        <option value="provider" data-i18n="opt_scope_provider">На весь провайдер (все его модели)</option>
        <option value="model" data-i18n="opt_scope_model">Индивидуально только на выбранную модель</option>
      </select>

      <label data-i18n="lbl_api_key">API-ключ:</label>
      <input type="password" id="inlineApiKeyInput" class="ctrl-input" style="flex:1; min-width:210px;" placeholder="sk-ant-... / sk-... / AIza..." />
      <button class="btn btn-sm" onclick="toggleInlineKeyVis()">👁</button>

      <label data-i18n="lbl_server_url">URL сервера:</label>
      <input type="text" id="inlineBaseUrlInput" class="ctrl-input" style="width:220px;" placeholder="https://..." />

      <button class="btn btn-sm btn-primary" onclick="saveInlineKeyAndFetch(false)" data-i18n="btn_save_key">💾 Сохранить ключ</button>
      <button class="btn btn-sm btn-ok" onclick="saveInlineKeyAndFetch(true)" data-i18n="btn_save_and_fetch">🔌 Сохранить и загрузить модели</button>
    </div>
    <div style="font-size:11.5px; color:var(--text-muted);" id="inlineProviderHint"></div>
  </div>

  <!-- ПАНЕЛЬ ИЗБРАННЫХ МОДЕЛЕЙ -->
  <div class="fav-bar" id="favModelsBar"></div>

  <!-- ==================== ВКЛАДКА 1: ЧАТ ==================== -->
  <div class="tab-view active" id="view-chat">
    <div class="chat-layout">
      <!-- СПИСОК ДИАЛОГОВ -->
      <div class="chat-sidebar">
        <div class="sidebar-head">
          <button class="btn btn-primary btn-sm" style="flex:1;" onclick="sendAction('new_chat')" data-i18n="btn_new_chat">➕ Новый чат</button>
          <button class="btn btn-danger btn-sm" onclick="sendAction('clear_chat')" title="Clear">🗑</button>
        </div>
        <div class="session-list" id="sessionList"></div>
      </div>

      <!-- ОСНОВНАЯ ЗОНА ЧАТА -->
      <div class="chat-main">
        <!-- ЖИВАЯ СТРОКА СОСТОЯНИЯ СТОЛА И ПРОФИЛЯ -->
        <div class="context-strip">
          <div class="context-badges" id="contextBadges"></div>
          <div style="display:flex; align-items:center; gap:8px;">
            <button class="btn btn-sm" onclick="sendAction('refresh_context')" data-i18n="btn_refresh_plate">🔄 Обновить стол</button>
            <label style="display:flex; align-items:center; gap:5px; cursor:pointer; font-size:11.5px; color:var(--text-muted);">
              <input type="checkbox" id="chkAutoContext" checked onchange="saveQuickToggle()" />
              <span data-i18n="chk_auto_ctx">Авто-передача 3D-модели и настроек в ИИ</span>
            </label>
          </div>
        </div>

        <!-- СООБЩЕНИЯ -->
        <div class="messages-area" id="messagesArea"></div>

        <!-- БЫСТРЫЕ СЦЕНАРИИ В 1 КЛИК -->
        <div class="quick-actions">
          <button class="q-btn" onclick="runQuickPrompt('full_audit')" data-i18n="q_full_audit">🔍 Полный аудит модели и настроек</button>
          <button class="q-btn" onclick="runQuickPrompt('orientation_supports')" data-i18n="q_supports">📐 Анализ нависаний, поддержек и каймы</button>
          <button class="q-btn" onclick="runQuickPrompt('strength_functional')" data-i18n="q_strength">💪 Усилить прочность детали</button>
          <button class="q-btn" onclick="runQuickPrompt('quality_surface')" data-i18n="q_quality">✨ Идеальное качество поверхности и шва</button>
          <button class="q-btn" onclick="runQuickPrompt('speed_optimize')" data-i18n="q_speed">⚡ Ускорить печать без потери качества</button>
          <button class="q-btn" onclick="runQuickPrompt('filament_check')" data-i18n="q_filament">🧵 Проверить температуры, поток и ретракт</button>
          <input type="file" id="gcodeFileInput" accept=".gcode,.gco,.g" style="display:none" onchange="onGcodeFilePicked(event)" />
          <button class="q-btn" onclick="document.getElementById('gcodeFileInput').click()" data-i18n="q_gcode">📄 Проверить G-code файл</button>
        </div>

        <!-- ПОЛЕ ВВОДА -->
        <div class="composer">
          <div class="attachment-bar" id="attachmentBar">
            <span id="attachmentLabel">📷</span>
            <button class="btn btn-danger btn-sm" onclick="clearAttachment()" data-i18n="btn_remove_photo">✕ Убрать</button>
          </div>
          <div class="composer-row">
            <textarea id="chatInput" data-i18n-placeholder="ph_chat_input" placeholder="Задайте вопрос по подготовке модели, настройкам OrcaSlicer, пластику или дефекту печати..." onkeydown="onChatKeydown(event)"></textarea>
            <input type="file" id="photoInput" accept="image/*" style="display:none" onchange="onPhotoSelected(event)" />
            <button class="btn" onclick="document.getElementById('photoInput').click()" data-i18n="btn_photo">📷 Фото</button>
            <button class="btn btn-primary" id="btnSend" onclick="sendMessage()" data-i18n="btn_send">Отправить ➤</button>
          </div>
          <div class="composer-controls">
            <span id="statusLine"></span>
            <div style="display:flex; align-items:center; gap:6px; flex-wrap:wrap;">
              <label for="chatEffortSelect" data-i18n="lbl_speed">⚡ Скорость ИИ:</label>
              <select id="chatEffortSelect" class="ctrl-select" style="padding:2px 6px; font-size:11.5px;" onchange="onEffortChange(this.value)">
                <option value="none" data-i18n="eff_none">⚡ Мгновенно (без thinking)</option>
                <option value="low" data-i18n="eff_low">🚀 Быстро (low thinking)</option>
                <option value="medium" data-i18n="eff_med">⚖️ Баланс (medium)</option>
                <option value="high" data-i18n="eff_high">🧠 Глубоко (high)</option>
                <option value="auto" data-i18n="eff_auto">Авто (по умолчанию API)</option>
              </select>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- ==================== ВКЛАДКА 2: ИНСПЕКТОР ==================== -->
  <div class="tab-view" id="view-inspector">
    <div class="scroll-page">
      <div class="card">
        <div class="card-title">
          <span data-i18n="insp_plate_title">📐 3D-Геометрия моделей на столе (анализ сетки и нависаний)</span>
          <button class="btn btn-sm btn-primary" onclick="sendAction('refresh_context')" data-i18n="btn_rescan_plate">🔄 Пересканировать стол</button>
        </div>
        <div id="inspectorWarnings"></div>
        <div id="inspectorObjects"></div>
      </div>

      <div class="card">
        <div class="card-title">
          <span data-i18n="insp_presets_title">🎛 Активные профили и настройки слайсера</span>
          <button class="btn btn-sm" onclick="switchTab('chat'); runQuickPrompt('full_audit')" data-i18n="btn_audit_these">🤖 Запустить ИИ-аудит этих настроек</button>
        </div>
        <div id="inspectorPresets"></div>
      </div>
    </div>
  </div>

  <!-- ==================== ВКЛАДКА 3: НАСТРОЙКИ И МОДЕЛИ ==================== -->
  <div class="tab-view" id="view-settings">
    <div class="scroll-page">
      <div class="card">
        <div class="card-title">
          <span data-i18n="cfg_title_main">🔌 Управление провайдерами, API-ключами и списком моделей</span>
          <div style="display:flex; gap:6px;">
            <button class="btn btn-sm" onclick="sendAction('import_printpurr')" data-i18n="btn_import_pp">📥 Импорт из PrintPurr</button>
            <button class="btn btn-sm btn-primary" onclick="switchTab('chat')" data-i18n="btn_back_chat">💬 Вернуться в чат</button>
          </div>
        </div>
        <div class="grid-2">
          <div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_lang">0. Язык интерфейса и ответов ИИ (Language / Мова):</label>
              <select id="cfgLangSelect" class="ctrl-select" onchange="onChangeLanguage(this.value)">
                <option value="ru">🇷🇺 Русский (Russian)</option>
                <option value="uk">🇺🇦 Українська (Ukrainian)</option>
                <option value="en">🇬🇧 English</option>
              </select>
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_prov">1. Выберите провайдера ИИ:</label>
              <select id="cfgProvider" class="ctrl-select" onchange="onCfgProviderSelect()"></select>
              <div class="hint-text" id="cfgProviderHint"></div>
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_url">2. Базовый URL API (Base URL):</label>
              <input type="text" id="cfgBaseUrl" class="ctrl-input" placeholder="https://api.anthropic.com/v1" />
            </div>
            <div class="form-group" id="cfgProtocolGroup" style="display:none;">
              <label data-i18n="cfg_lbl_proto">Протокол API (для Custom сервера):</label>
              <select id="cfgCustomProtocol" class="ctrl-select">
                <option value="openai">OpenAI (/chat/completions)</option>
                <option value="anthropic">Anthropic (/v1/messages)</option>
              </select>
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_prov_key">3. API-ключ провайдера (общий для всех его моделей):</label>
              <div style="display:flex; gap:6px;">
                <input type="password" id="cfgApiKey" class="ctrl-input" style="flex:1;" placeholder="sk-ant-... / sk-... / AIza..." />
                <button class="btn btn-sm" onclick="toggleKeyVisibility('cfgApiKey')">👁</button>
              </div>
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_model">4. Выберите или впишите ID активной модели:</label>
              <input type="text" id="cfgModel" class="ctrl-input" placeholder="claude-opus-5-5" oninput="syncPerModelKeyInput()" />
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_model_key">5. Индивидуальный API-ключ конкретно для этой модели (необязательно):</label>
              <div style="display:flex; gap:6px;">
                <input type="password" id="cfgModelSpecificKey" class="ctrl-input" style="flex:1;" data-i18n-placeholder="ph_model_key" placeholder="Оставьте пустым для использования общего ключа" />
                <button class="btn btn-sm" onclick="toggleKeyVisibility('cfgModelSpecificKey')">👁</button>
              </div>
              <div class="hint-text" data-i18n="cfg_hint_model_key">Если у вас отдельные ключи под конкретные модели — укажите ключ здесь.</div>
            </div>
            <div style="display:flex; gap:8px; margin-top:8px; flex-wrap:wrap;">
              <button class="btn btn-primary" onclick="saveProviderConfig()" data-i18n="btn_save_cfg">💾 Сохранить настройки и ключи</button>
              <button class="btn btn-ok" onclick="saveProviderConfig(); fetchModelsFromApi();" data-i18n="btn_save_and_fetch">🔌 Сохранить и загрузить модели</button>
            </div>
          </div>

          <div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_browser">Доступные модели выбранного провайдера:</label>
              <input type="text" id="modelFilterInput" class="ctrl-input" data-i18n-placeholder="ph_search_model" placeholder="🔍 Поиск модели (opus, 5.5, gpt-5, gemini, free)..." oninput="renderModelsBrowser()" />
            </div>
            <div class="models-browser" id="modelsBrowser"></div>
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-title"><span data-i18n="cfg_fav_title">⭐ Избранные модели (кнопки быстрого переключения над чатом)</span></div>
        <div id="favManagerList" style="display:flex; flex-wrap:wrap; gap:6px;"></div>
      </div>

      <div class="card">
        <div class="card-title"><span data-i18n="cfg_gen_title">🧠 Параметры генерации и описание вашего 3D-принтера</span></div>
        <div class="grid-2">
          <div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_temp">Температура генерации (0.0 — точный, 0.7 — креативный):</label>
              <input type="number" step="0.05" min="0" max="1.5" id="cfgTemperature" class="ctrl-input" value="0.3" />
            </div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_tokens">Максимум токенов ответа (max_tokens):</label>
              <input type="number" step="256" min="512" max="32768" id="cfgMaxTokens" class="ctrl-input" value="4096" />
            </div>
            <div class="form-group">
              <label style="display:flex; align-items:center; gap:6px; cursor:pointer; color:var(--text);">
                <input type="checkbox" id="cfgSlicingAudit" />
                <span data-i18n="cfg_chk_slicing">Автоматически проверять G-code после каждой нарезки (Slicing Pipeline)</span>
              </label>
            </div>
          </div>
          <div>
            <div class="form-group">
              <label data-i18n="cfg_lbl_custom_instr">Дополнительная информация о вашем принтере и пластиках:</label>
              <textarea id="cfgCustomInstructions" class="ctrl-input" style="height:105px; resize:vertical;" data-i18n-placeholder="ph_custom_instr" placeholder="Например: Bambu Lab P2S, сопло 0.4 мм, печатаю функциональные детали из PLA и PETG."></textarea>
            </div>
          </div>
        </div>
        <button class="btn btn-primary" onclick="saveProviderConfig()" data-i18n="btn_save_cfg">💾 Сохранить настройки и ключи</button>
      </div>
    </div>
  </div>
</div>

<div class="status-toast" id="statusToast"></div>

<script>
const I18N = {
  ru: {
    lbl_provider: "Провайдер:",
    lbl_model: "Модель:",
    ph_custom_model: "Или свой ID модели...",
    btn_key_set: "🔑 Ключ задан ✓",
    btn_key_enter: "🔑 Ввести API-ключ!",
    btn_fetch_api: "🔄 Загрузить по API",
    btn_add_fav: "⭐ В избранное",
    tab_chat: "💬 Чат",
    tab_inspector: "📊 3D-Инспектор",
    tab_settings: "⚙️ Настройки",
    btn_dock: "📌 У 3D-стола",
    btn_import_pp: "📥 Импорт из PrintPurr",
    btn_open_mgr: "⚙️ Все настройки",
    btn_hide: "✕ Скрыть",
    lbl_key_scope: "Куда ключ:",
    opt_scope_provider: "На весь провайдер (все его модели)",
    opt_scope_model: "Индивидуально только на выбранную модель",
    lbl_api_key: "API-ключ:",
    lbl_server_url: "URL сервера:",
    btn_save_key: "💾 Сохранить ключ",
    btn_save_and_fetch: "🔌 Сохранить и загрузить модели",
    key_ok_status: "✅ API-ключ для «{prov}» ({model}) настроен.",
    key_missing_status: "⚠️ Для работы с «{prov}» вставьте ваш API-ключ ниже и нажмите «Сохранить ключ»:",
    fav_bar_label: "⭐ Быстрый выбор:",
    btn_new_chat: "➕ Новый чат",
    btn_refresh_plate: "🔄 Обновить стол",
    chk_auto_ctx: "Авто-передача 3D-модели и настроек в ИИ",
    q_full_audit: "🔍 Полный аудит модели и настроек",
    q_supports: "📐 Нависания, поддержки и кайма",
    q_strength: "💪 Усилить прочность детали",
    q_quality: "✨ Качество поверхности и шва",
    q_speed: "⚡ Ускорить печать",
    q_filament: "🧵 Температуры, поток и ретракт",
    q_gcode: "📄 Проверить G-code",
    btn_remove_photo: "✕ Убрать",
    ph_chat_input: "Задайте вопрос по подготовке модели, настройкам OrcaSlicer, пластику или дефекту печати... (Enter — отправить, Shift+Enter — новая строка)",
    btn_photo: "📷 Фото",
    btn_send: "Отправить ➤",
    btn_thinking: "⏳ Думаю...",
    status_ready: "Готов к работе",
    status_working: "ИИ анализирует модель и настройки...",
    lbl_speed: "⚡ Скорость / Thinking:",
    eff_none: "⚡ Мгновенно (без thinking)",
    eff_low: "🚀 Быстро (low thinking)",
    eff_med: "⚖️ Баланс (medium)",
    eff_high: "🧠 Глубоко (high)",
    eff_auto: "Авто (по умолчанию API)",
    tip_footer: "Совет: язык интерфейса и ответов ИИ переключается кнопкой 🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN в верхней панели!",
    insp_plate_title: "📐 3D-Геометрия моделей на столе (анализ сетки и нависаний)",
    btn_rescan_plate: "🔄 Пересканировать стол",
    insp_presets_title: "🎛 Активные профили и настройки слайсера",
    btn_audit_these: "🤖 Запустить ИИ-аудит этих настроек",
    cfg_title_main: "🔌 Управление провайдерами, API-ключами и списком моделей",
    btn_back_chat: "💬 Вернуться в чат",
    cfg_lbl_lang: "0. Язык интерфейса и ответов ИИ (Language / Мова):",
    cfg_lbl_prov: "1. Выберите провайдера ИИ:",
    cfg_lbl_url: "2. Базовый URL API (Base URL):",
    cfg_lbl_proto: "Протокол API (для Custom сервера):",
    cfg_lbl_prov_key: "3. API-ключ провайдера (общий для всех его моделей):",
    cfg_lbl_model: "4. Выберите или впишите ID активной модели:",
    cfg_lbl_model_key: "5. Индивидуальный API-ключ конкретно для этой модели (необязательно):",
    ph_model_key: "Оставьте пустым, чтобы использовать общий ключ провайдера выше",
    cfg_hint_model_key: "Если у вас разные ключи под конкретные модели — укажите ключ здесь.",
    btn_save_cfg: "💾 Сохранить настройки и ключи",
    cfg_lbl_browser: "Доступные модели выбранного провайдера:",
    ph_search_model: "🔍 Поиск модели (opus, 5.5, gpt-5, gemini, free)...",
    cfg_fav_title: "⭐ Избранные модели (кнопки быстрого переключения над чатом)",
    cfg_gen_title: "🧠 Параметры генерации и описание вашего 3D-принтера",
    cfg_lbl_temp: "Температура генерации (0.0 — точный технарь, 0.7 — креативный):",
    cfg_lbl_tokens: "Максимум токенов ответа (max_tokens):",
    cfg_chk_slicing: "Автоматически проверять G-code после каждой нарезки (Slicing Pipeline)",
    cfg_lbl_custom_instr: "Дополнительная информация о вашем принтере и пластиках:",
    ph_custom_instr: "Например: Принтер Bambu Lab P2S, сопло 0.4 мм, печатаю функциональные детали из PLA и PETG.",
    badge_printer: "🖨 Принтер:",
    badge_profile: "⚙ Профиль:",
    badge_filament: "🧵 Пластик:",
    badge_on_plate: "📦 На столе:",
    badge_pcs: "дет.",
    badge_overhangs: "📐 Нависания >45°:",
    badge_warnings: "⚠ Предупреждений:",
    badge_empty: "Стол пуст",
    mesh_ok: "✅ Геометрических проблем с сеткой не обнаружено.",
    plate_empty_hint: "На 3D-столе OrcaSlicer сейчас нет моделей. Добавьте деталь на стол и нажмите «Пересканировать стол».",
    th_obj: "Объект",
    th_dim: "Габариты (X×Y×Z)",
    th_vol: "Объём",
    th_bed: "Контакт 1-го слоя",
    th_ovh: "Нависания >45° / >60°",
    th_mesh: "Статус сетки",
    mesh_err: "Ошибки",
    welcome_title: "👋 Добро пожаловать в Orca AI Assistant!",
    welcome_desc: "1. Выберите провайдера и модель сверху (или впишите любой ID модели).<br/>2. Нажмите <strong>«🔑 API-ключ»</strong> в верхней панели, чтобы указать ключ для провайдера или модели.<br/>3. Переключайте язык (🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN) в правом верхнем углу в любой момент.",
    welcome_btn_key: "🔑 Настроить API-ключ",
    you_label: "Вы",
    ai_label: "ИИ Ассистент",
    sug_head: "⚙️ Рекомендуемые изменения профиля ({n})",
    btn_apply_sug: "⚡ Применить выбранные в OrcaSlicer",
    th_param: "Параметр",
    th_change: "Было → Станет",
    th_reason: "Причина",
    btn_select_model: "Выбрать",
    no_models_found: "Модели не найдены. Нажмите «🔄 Загрузить по API» или впишите ID модели вручную.",
    custom_model_prefix: "✏️ Своя модель: ",
    toast_key_saved: "✅ API-ключ и настройки успешно сохранены!",
    toast_enter_key_first: "🔑 Сначала вставьте API-ключ в открывшееся поле сверху!",
    toast_loading_models: "⏳ Загружаю список моделей с сервера {prov}...",
    toast_models_loaded: "✅ Загружено моделей по API: {n}!",
    toast_settings_applied: "✅ Настройки применены в профиль OrcaSlicer ({n} шт.)!",
    toast_select_one: "Выберите хотя бы один параметр для применения",
    prompt_full_audit: "Проведи полный технический аудит текущей 3D-модели на столе и активных настроек профиля OrcaSlicer. Оцени габариты, площадь первого слоя, нависания >45° и >60°, слои, стенки, заполнение, скорости, охлаждение и температуры. Укажи риски при печати и предложи оптимальные изменения настроек в блоке ```orca-settings.",
    prompt_supports: "Проанализируй геометрию детали на столе: площадь контакта первого слоя со столом, отношение высоты к базе и площадь нависаний >45° и >60°. Скажи, нужны ли поддержки (обычные или древовидные), какой зазор Z выставить, нужна ли кайма (Brim) и стоит ли повернуть деталь другой гранью на стол. Добавь рекомендуемые параметры в ```orca-settings.",
    prompt_strength: "Мне нужна максимальная механическая прочность и надёжность этой детали под нагрузку. Проанализируй текущие настройки стенок, крышки/дна, заполнения, ширины линий, температур и обдува и предложи оптимальный профиль прочности в блоке ```orca-settings.",
    prompt_quality: "Как добиться максимально аккуратного внешнего вида поверхности, незаметного шва, чётких нависаний и отсутствия дефектов на этой модели? Предложи точные изменения скоростей, ускорений, шва и обдува в блоке ```orca-settings.",
    prompt_speed: "Как безопасно ускорить печать этой модели без критической потери качества и прочности? Проверь скорости, ускорения, высоту слоя и ширину линий и предложи настройки в ```orca-settings.",
    prompt_filament: "Проверь совместимость текущих настроек температур сопла и стола, обдува, ретракта, Z-hop и объёмного расхода с выбранным филаментом. Предложи корректировки в ```orca-settings."
  },
  uk: {
    lbl_provider: "Провайдер:",
    lbl_model: "Модель:",
    ph_custom_model: "Або свій ID моделі...",
    btn_key_set: "🔑 Ключ задано ✓",
    btn_key_enter: "🔑 Ввести API-ключ!",
    btn_fetch_api: "🔄 Завантажити по API",
    btn_add_fav: "⭐ В обране",
    tab_chat: "💬 Чат",
    tab_inspector: "📊 3D-Інспектор",
    tab_settings: "⚙️ Налаштування",
    btn_dock: "📌 Біля 3D-столу",
    btn_import_pp: "📥 Імпорт із PrintPurr",
    btn_open_mgr: "⚙️ Усі налаштування",
    btn_hide: "✕ Сховати",
    lbl_key_scope: "Куди ключ:",
    opt_scope_provider: "На весь провайдер (усі його моделі)",
    opt_scope_model: "Індивідуально тільки на обрану модель",
    lbl_api_key: "API-ключ:",
    lbl_server_url: "URL сервера:",
    btn_save_key: "💾 Зберегти ключ",
    btn_save_and_fetch: "🔌 Зберегти і завантажити моделі",
    key_ok_status: "✅ API-ключ для «{prov}» ({model}) налаштовано.",
    key_missing_status: "⚠️ Для роботи з «{prov}» вставте ваш API-ключ нижче та натисніть «Зберегти ключ»:",
    fav_bar_label: "⭐ Швидкий вибір:",
    btn_new_chat: "➕ Новий чат",
    btn_refresh_plate: "🔄 Оновити стіл",
    chk_auto_ctx: "Авто-передача 3D-моделі та налаштувань у ШІ",
    q_full_audit: "🔍 Повний аудит моделі та налаштувань",
    q_supports: "📐 Нависання, підтримки та кайма",
    q_strength: "💪 Посилити міцність деталі",
    q_quality: "✨ Якість поверхні та шва",
    q_speed: "⚡ Прискорити друк",
    q_filament: "🧵 Температури, потік і ретракт",
    q_gcode: "📄 Перевірити G-code",
    btn_remove_photo: "✕ Прибрати",
    ph_chat_input: "Поставте запитання щодо підготовки моделі, налаштувань OrcaSlicer, пластику або дефекту друку... (Enter — надіслати, Shift+Enter — новий рядок)",
    btn_photo: "📷 Фото",
    btn_send: "Надіслати ➤",
    btn_thinking: "⏳ Думаю...",
    status_ready: "Готовий до роботи",
    status_working: "ШІ аналізує модель та налаштування...",
    lbl_speed: "⚡ Швидкість / Thinking:",
    eff_none: "⚡ Миттєво (без thinking)",
    eff_low: "🚀 Швидко (low thinking)",
    eff_med: "⚖️ Баланс (medium)",
    eff_high: "🧠 Глибоко (high)",
    eff_auto: "Авто (за замовчуванням API)",
    tip_footer: "Порада: мова інтерфейсу та відповідей ШІ перемикається кнопкою 🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN у верхній панелі!",
    insp_plate_title: "📐 3D-Геометрія моделей на столі (аналіз сітки та нависань)",
    btn_rescan_plate: "🔄 Пересканувати стіл",
    insp_presets_title: "🎛 Активні профілі та налаштування слайсера",
    btn_audit_these: "🤖 Запустити ШІ-аудит цих налаштувань",
    cfg_title_main: "🔌 Керування провайдерами, API-ключами та списком моделей",
    btn_back_chat: "💬 Повернутися в чат",
    cfg_lbl_lang: "0. Мова інтерфейсу та відповідей ШІ (Language / Язык):",
    cfg_lbl_prov: "1. Оберіть провайдера ШІ:",
    cfg_lbl_url: "2. Базовий URL API (Base URL):",
    cfg_lbl_proto: "Протокол API (для Custom сервера):",
    cfg_lbl_prov_key: "3. API-ключ провайдера (спільний для всіх його моделей):",
    cfg_lbl_model: "4. Оберіть або впишіть ID активної моделі:",
    cfg_lbl_model_key: "5. Індивідуальний API-ключ конкретно для цієї моделі (необов'язково):",
    ph_model_key: "Залиште порожнім, щоб використовувати спільний ключ провайдера вище",
    cfg_hint_model_key: "Якщо у вас окремі ключі під конкретні моделі — вкажіть ключ тут.",
    btn_save_cfg: "💾 Зберегти налаштування та ключі",
    cfg_lbl_browser: "Доступні моделі обраного провайдера:",
    ph_search_model: "🔍 Пошук моделі (opus, 5.5, gpt-5, gemini, free)...",
    cfg_fav_title: "⭐ Обрані моделі (кнопки швидкого перемикання над чатом)",
    cfg_gen_title: "🧠 Параметри генерації та опис вашого 3D-принтера",
    cfg_lbl_temp: "Температура генерації (0.0 — точний технар, 0.7 — креативний):",
    cfg_lbl_tokens: "Максимум токенів відповіді (max_tokens):",
    cfg_chk_slicing: "Автоматично перевіряти G-code після кожної нарізки (Slicing Pipeline)",
    cfg_lbl_custom_instr: "Додаткова інформація про ваш принтер і пластики:",
    ph_custom_instr: "Наприклад: Принтер Bambu Lab P2S, сопло 0.4 мм, друкую функціональні деталі з PLA та PETG.",
    badge_printer: "🖨 Принтер:",
    badge_profile: "⚙ Профіль:",
    badge_filament: "🧵 Пластик:",
    badge_on_plate: "📦 На столі:",
    badge_pcs: "дет.",
    badge_overhangs: "📐 Нависання >45°:",
    badge_warnings: "⚠ Попереджень:",
    badge_empty: "Стіл порожній",
    mesh_ok: "✅ Геометричних проблем із сіткою не виявлено.",
    plate_empty_hint: "На 3D-столі OrcaSlicer зараз немає моделей. Додайте деталь на стіл і натисніть «Пересканувати стіл».",
    th_obj: "Об'єкт",
    th_dim: "Габарити (X×Y×Z)",
    th_vol: "Об'єм",
    th_bed: "Контакт 1-го шару",
    th_ovh: "Нависання >45° / >60°",
    th_mesh: "Статус сітки",
    mesh_err: "Помилки",
    welcome_title: "👋 Ласкаво просимо в Orca AI Assistant!",
    welcome_desc: "1. Оберіть провайдера та модель зверху (або впишіть будь-який ID моделі).<br/>2. Натисніть <strong>«🔑 API-ключ»</strong> у верхній панелі, щоб вказати ключ для провайдера або моделі.<br/>3. Перемикайте мову (🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN) у правому верхньому куті в будь-який момент.",
    welcome_btn_key: "🔑 Налаштувати API-ключ",
    you_label: "Ви",
    ai_label: "ШІ Асистент",
    sug_head: "⚙️ Рекомендовані зміни профілю ({n})",
    btn_apply_sug: "⚡ Застосувати обрані в OrcaSlicer",
    th_param: "Параметр",
    th_change: "Було → Стане",
    th_reason: "Причина",
    btn_select_model: "Обрати",
    no_models_found: "Моделі не знайдено. Натисніть «🔄 Завантажити по API» або впишіть ID моделі вручну.",
    custom_model_prefix: "✏️ Своя модель: ",
    toast_key_saved: "✅ API-ключ та налаштування успішно збережено!",
    toast_enter_key_first: "🔑 Спочатку вставте API-ключ у відкрите поле зверху!",
    toast_loading_models: "⏳ Завантажую список моделей із сервера {prov}...",
    toast_models_loaded: "✅ Завантажено моделей по API: {n}!",
    toast_settings_applied: "✅ Налаштування застосовано в профіль OrcaSlicer ({n} шт.)!",
    toast_select_one: "Оберіть хоча б один параметр для застосування",
    prompt_full_audit: "Проведи повний технічний аудит поточної 3D-моделі на столі та активних налаштувань профілю OrcaSlicer. Оціни габарити, площу першого шару, нависання >45° та >60°, шари, стінки, заповнення, швидкості, охолодження і температури. Вкажи ризики під час друку та запропонуй оптимальні зміни налаштувань у блоці ```orca-settings.",
    prompt_supports: "Проаналізуй геометрію деталі на столі: площу контакту першого шару зі столом, відношення висоти до бази та площу нависань >45° та >60°. Скажи, чи потрібні підтримки (звичайні чи деревоподібні), який зазор Z виставити, чи потрібна кайма (Brim) і чи варто повернути деталь іншою гранню на стіл. Додай рекомендовані параметри в ```orca-settings.",
    prompt_strength: "Мені потрібна максимальна механічна міцність і надійність цієї деталі під навантаження. Проаналізуй поточні налаштування стінок, кришки/дна, заповнення, ширини ліній, температур та обдуву і запропонуй оптимальний профіль міцності в блоці ```orca-settings.",
    prompt_quality: "Як досягти максимально охайного зовнішнього вигляду поверхні, непомітного шва, чітких нависань і відсутності дефектів на цій моделі? Запропонуй точні зміни швидкостей, прискорень, шва та обдуву в блоці ```orca-settings.",
    prompt_speed: "Як безпечно прискорити друк цієї моделі без критичної втрати якості та міцності? Перевір швидкості, прискорення, висоту шару і ширину ліній та запропонуй налаштування в ```orca-settings.",
    prompt_filament: "Перевір сумісність поточних налаштувань температур сопла і столу, обдуву, ретракту, Z-hop та об'ємної витрати з обраним філаментом. Запропонуй коригування в ```orca-settings."
  },
  en: {
    lbl_provider: "Provider:",
    lbl_model: "Model:",
    ph_custom_model: "Or type custom model ID...",
    btn_key_set: "🔑 API Key Set ✓",
    btn_key_enter: "🔑 Enter API Key!",
    btn_fetch_api: "🔄 Fetch via API",
    btn_add_fav: "⭐ Favorite",
    tab_chat: "💬 Chat",
    tab_inspector: "📊 3D Inspector",
    tab_settings: "⚙️ Settings",
    btn_dock: "📌 Dock Panel",
    btn_import_pp: "📥 Import PrintPurr Keys",
    btn_open_mgr: "⚙️ All Settings",
    btn_hide: "✕ Hide",
    lbl_key_scope: "Key Scope:",
    opt_scope_provider: "Entire Provider (all its models)",
    opt_scope_model: "Specific Model Only",
    lbl_api_key: "API Key:",
    lbl_server_url: "Server URL:",
    btn_save_key: "💾 Save Key",
    btn_save_and_fetch: "🔌 Save & Fetch Models",
    key_ok_status: "✅ API key for \"{prov}\" ({model}) is configured.",
    key_missing_status: "⚠️ To use \"{prov}\", paste your API key below and click \"Save Key\":",
    fav_bar_label: "⭐ Quick Pick:",
    btn_new_chat: "➕ New Chat",
    btn_refresh_plate: "🔄 Refresh Plate",
    chk_auto_ctx: "Auto-send 3D model & slicer settings to AI",
    q_full_audit: "🔍 Full Model & Settings Audit",
    q_supports: "📐 Overhangs, Supports & Brim",
    q_strength: "💪 Maximize Part Strength",
    q_quality: "✨ Surface & Seam Quality",
    q_speed: "⚡ Speed Optimization",
    q_filament: "🧵 Temps, Flow & Retraction",
    q_gcode: "📄 Inspect G-code File",
    btn_remove_photo: "✕ Remove",
    ph_chat_input: "Ask anything about model preparation, OrcaSlicer settings, filament, or print defects... (Enter to send, Shift+Enter for new line)",
    btn_photo: "📷 Photo",
    btn_send: "Send ➤",
    btn_thinking: "⏳ Thinking...",
    status_ready: "Ready",
    status_working: "AI is analyzing model & slicer settings...",
    lbl_speed: "⚡ Speed / Thinking:",
    eff_none: "⚡ Instant (no thinking)",
    eff_low: "🚀 Fast (low thinking)",
    eff_med: "⚖️ Balanced (medium)",
    eff_high: "🧠 Deep (high)",
    eff_auto: "Auto (API default)",
    tip_footer: "Tip: switch UI & AI response language anytime using the 🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN selector in the top bar!",
    insp_plate_title: "📐 Plated 3D Model Geometry (Mesh & Overhang Analysis)",
    btn_rescan_plate: "🔄 Rescan Plate",
    insp_presets_title: "🎛 Active Slicer Presets & Parameters",
    btn_audit_these: "🤖 Run AI Audit on These Settings",
    cfg_title_main: "🔌 Manage AI Providers, API Keys & Models",
    btn_back_chat: "💬 Back to Chat",
    cfg_lbl_lang: "0. UI & AI Response Language (Language / Мова / Язык):",
    cfg_lbl_prov: "1. Select AI Provider:",
    cfg_lbl_url: "2. API Base URL:",
    cfg_lbl_proto: "API Protocol (for Custom server):",
    cfg_lbl_prov_key: "3. Provider API Key (shared across all models of this provider):",
    cfg_lbl_model: "4. Select or type active Model ID:",
    cfg_lbl_model_key: "5. Dedicated API Key for this specific model (optional):",
    ph_model_key: "Leave blank to use the shared provider API key above",
    cfg_hint_model_key: "If you use different API keys for specific models, enter the model-specific key here.",
    btn_save_cfg: "💾 Save Settings & Keys",
    cfg_lbl_browser: "Available models for selected provider:",
    ph_search_model: "🔍 Filter models (opus, 5.5, gpt-5, gemini, free)...",
    cfg_fav_title: "⭐ Favorite Models (quick switch chips above chat)",
    cfg_gen_title: "🧠 Generation Parameters & Custom Printer Notes",
    cfg_lbl_temp: "Generation Temperature (0.0 = strict technical, 0.7 = creative):",
    cfg_lbl_tokens: "Max Output Tokens (max_tokens):",
    cfg_chk_slicing: "Automatically audit G-code after each slice (Slicing Pipeline)",
    cfg_lbl_custom_instr: "Additional notes about your 3D printer & filaments:",
    ph_custom_instr: "E.g.: Bambu Lab P2S, enclosed chamber, 0.4mm nozzle, printing functional parts in PLA and PETG.",
    badge_printer: "🖨 Printer:",
    badge_profile: "⚙ Process:",
    badge_filament: "🧵 Filament:",
    badge_on_plate: "📦 On Plate:",
    badge_pcs: "pcs",
    badge_overhangs: "📐 Overhangs >45°:",
    badge_warnings: "⚠ Warnings:",
    badge_empty: "Plate is empty",
    mesh_ok: "✅ No mesh geometry errors detected.",
    plate_empty_hint: "No 3D models currently on the OrcaSlicer build plate. Add a model and click \"Rescan Plate\".",
    th_obj: "Object",
    th_dim: "Dimensions (X×Y×Z)",
    th_vol: "Volume",
    th_bed: "1st Layer Contact",
    th_ovh: "Overhangs >45° / >60°",
    th_mesh: "Mesh Status",
    mesh_err: "Errors",
    welcome_title: "👋 Welcome to Orca AI Assistant!",
    welcome_desc: "1. Choose an AI provider and model at the top (or type any custom model ID).<br/>2. Click <strong>\"🔑 API Key\"</strong> in the top bar to set your provider or model API key.<br/>3. Switch language (🇷🇺 RU / 🇺🇦 UA / 🇬🇧 EN) in the top-right corner anytime.",
    welcome_btn_key: "🔑 Configure API Key",
    you_label: "You",
    ai_label: "AI Assistant",
    sug_head: "⚙️ Recommended Slicer Changes ({n})",
    btn_apply_sug: "⚡ Apply Selected to OrcaSlicer",
    th_param: "Parameter",
    th_change: "Current → New",
    th_reason: "Reason",
    btn_select_model: "Select",
    no_models_found: "No models found. Click \"🔄 Fetch via API\" or type any model ID manually.",
    custom_model_prefix: "✏️ Custom model: ",
    toast_key_saved: "✅ API key & settings saved!",
    toast_enter_key_first: "🔑 Please paste your API key in the key drawer above first!",
    toast_loading_models: "⏳ Fetching model list from {prov}...",
    toast_models_loaded: "✅ Loaded {n} models via API!",
    toast_settings_applied: "✅ Applied {n} parameters to OrcaSlicer profile!",
    toast_select_one: "Select at least one parameter to apply",
    prompt_full_audit: "Perform a complete technical audit of the current 3D model on the build plate and active OrcaSlicer profile settings. Evaluate dimensions, first-layer contact area, overhangs >45° and >60°, layer height, walls, infill, speeds, cooling, and temperatures. Point out print risks and provide optimal setting changes in an ```orca-settings block.",
    prompt_supports: "Analyze the plated part geometry: first-layer bed contact area, height-to-base ratio, and overhang areas >45° and >60°. Tell me whether supports (normal or tree) are needed, what Z-distance to use, whether a Brim is needed, and if the part should be re-oriented. Include recommended parameters in an ```orca-settings block.",
    prompt_strength: "I need maximum mechanical strength and durability for this functional part under load. Analyze the current walls, top/bottom shells, infill, line widths, temperatures, and cooling settings, and propose an optimal strength profile in an ```orca-settings block.",
    prompt_quality: "How can I achieve the cleanest possible surface finish, minimal seam visibility, crisp overhangs, and zero artifacts on this model? Suggest exact speed, acceleration, seam, and cooling adjustments in an ```orca-settings block.",
    prompt_speed: "How can I safely speed up printing this model without sacrificing critical quality or strength? Check speeds, accelerations, layer height, and line widths, and suggest changes in an ```orca-settings block.",
    prompt_filament: "Check the compatibility of current nozzle/bed temperatures, fan cooling, retraction, Z-hop, and max volumetric speed with the selected filament. Propose adjustments in an ```orca-settings block."
  }
};

let STATE = {
  providers: {},
  settings: {
    language: "ru",
    provider: "anthropic",
    model: "claude-opus-5-5",
    temperature: 0.3,
    max_tokens: 4096,
    auto_attach_context: true,
    enable_slicing_audit: false,
    custom_user_instructions: "",
    api_keys: {},
    model_api_keys: {},
    base_urls: {},
    custom_protocol: "openai",
    favorite_models: [],
    cached_models: {}
  },
  chats: { active_id: "", sessions: [] },
  plate: { has_model: false, objects: [], warnings: [] },
  presets: { groups: {}, flat_values: {} },
  busy: false
};

let ATTACHED_IMAGE = null;
let LAST_SUGGESTIONS_MAP = {};

['dragover', 'drop'].forEach(evName => window.addEventListener(evName, e => { e.preventDefault(); }, true));

function curLang() {
  const l = (STATE.settings && STATE.settings.language) || "ru";
  return (l === "uk" || l === "en") ? l : "ru";
}

function t(key, vars) {
  const dict = I18N[curLang()] || I18N.ru;
  let str = dict[key] !== undefined ? dict[key] : (I18N.ru[key] || key);
  if (vars) {
    Object.keys(vars).forEach(k => {
      str = str.replace(new RegExp("\\{" + k + "\\}", "g"), vars[k]);
    });
  }
  return str;
}

function getProviderHint(pInfo) {
  if (!pInfo) return "";
  if (pInfo.hint_i18n && pInfo.hint_i18n[curLang()]) {
    return pInfo.hint_i18n[curLang()];
  }
  return pInfo.hint || "";
}

function applyStaticI18n() {
  const l = curLang();
  document.documentElement.lang = l;
  document.getElementById("topLangSelect").value = l;
  document.getElementById("cfgLangSelect").value = l;

  document.querySelectorAll("[data-i18n]").forEach(el => {
    const k = el.getAttribute("data-i18n");
    if (k) el.textContent = t(k);
  });
  document.querySelectorAll("[data-i18n-placeholder]").forEach(el => {
    const k = el.getAttribute("data-i18n-placeholder");
    if (k) el.placeholder = t(k);
  });
  if (!STATE.busy) {
    document.getElementById("statusLine").textContent = t("status_ready");
    document.getElementById("btnSend").textContent = t("btn_send");
  }
}

function onChangeLanguage(newLang) {
  const clean = (newLang === "uk" || newLang === "en") ? newLang : "ru";
  STATE.settings.language = clean;
  applyStaticI18n();
  populateProvidersUI();
  renderContextAndInspector();
  renderChats();
  sendAction("change_language", { language: clean });
}

function sendToHost(payload) {
  if (window.orca && typeof window.orca.postMessage === "function") {
    window.orca.postMessage(payload);
  } else if (window.orca && typeof window.orca.sendMessage === "function") {
    window.orca.sendMessage(JSON.stringify(payload));
  }
}

function sendAction(action, extra) {
  sendToHost(Object.assign({ action: action }, extra || {}));
}

function showToast(text, isError) {
  const el = document.getElementById("statusToast");
  el.textContent = text;
  el.style.background = isError ? "#5a1e1e" : "#123e3a";
  el.style.borderColor = isError ? "#e5534b" : "#0f968b";
  el.style.display = "block";
  clearTimeout(window._toastTimer);
  window._toastTimer = setTimeout(() => { el.style.display = "none"; }, 4500);
}

function switchTab(tabName) {
  ["chat", "inspector", "settings"].forEach(tab => {
    document.getElementById("view-" + tab).classList.toggle("active", tab === tabName);
    const btn = document.getElementById("tabBtn-" + tab);
    if (btn) btn.classList.toggle("btn-primary", tab === tabName);
  });
}

function escapeHtml(str) {
  return String(str || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderMarkdown(md) {
  let clean = String(md || "").replace(/```(?:orca-settings|orca_settings)[\s\S]*?```/gi, "");
  let html = escapeHtml(clean);

  html = html.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, function(_, lang, code) {
    return '<pre><code>' + code.trim() + '</code></pre>';
  });
  html = html.replace(/`([^`\n]+)`/g, '<code>$1</code>');
  html = html.replace(/^####\s+(.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  html = html.replace(/^\s*[-•]\s+(.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>[\s\S]*?<\/li>)/g, '<ul>$1</ul>');
  html = html.replace(/<\/ul>\s*<ul>/g, '');
  html = html.replace(/\n\n+/g, '</p><p>');
  html = html.replace(/\n/g, '<br/>');
  return '<p>' + html + '</p>';
}

function getEffectiveKey(provId, modelId) {
  const mKeys = STATE.settings.model_api_keys || {};
  const specific = mKeys[provId + "::" + modelId] || mKeys[modelId] || "";
  if (specific) return specific;
  const pKeys = STATE.settings.api_keys || {};
  return pKeys[provId] || "";
}

function hasKeyForCurrent() {
  const prov = STATE.settings.provider || "anthropic";
  const model = STATE.settings.model || "";
  const pInfo = STATE.providers[prov] || {};
  if (!pInfo.needs_key) return true;
  return !!getEffectiveKey(prov, model).trim();
}

function getAvailableModelsForProvider(provId) {
  const cached = (STATE.settings.cached_models && STATE.settings.cached_models[provId]) || [];
  const suggested = ((STATE.providers[provId] || {}).suggested_models || []).map(m =>
    typeof m === "string" ? { id: m, name: m } : { id: m.id, name: m.name || m.id }
  );
  const seen = new Set();
  const result = [];
  suggested.concat(cached).forEach(item => {
    const id = typeof item === "string" ? item : item.id;
    if (id && !seen.has(id)) {
      seen.add(id);
      result.push({ id: id, name: item.name || id });
    }
  });
  return result;
}

function populateProvidersUI() {
  const topSel = document.getElementById("topProviderSelect");
  const cfgSel = document.getElementById("cfgProvider");
  topSel.innerHTML = "";
  cfgSel.innerHTML = "";
  Object.keys(STATE.providers).forEach(pid => {
    const p = STATE.providers[pid];
    const opt1 = document.createElement("option");
    opt1.value = pid; opt1.textContent = p.name;
    topSel.appendChild(opt1);
    const opt2 = document.createElement("option");
    opt2.value = pid; opt2.textContent = p.name;
    cfgSel.appendChild(opt2);
  });

  const curProv = STATE.settings.provider || "anthropic";
  topSel.value = curProv;
  cfgSel.value = curProv;

  populateTopModelDropdown(curProv, STATE.settings.model || "");
  document.getElementById("chkAutoContext").checked = !!STATE.settings.auto_attach_context;
  const effEl = document.getElementById("chatEffortSelect");
  if (effEl) effEl.value = STATE.settings.reasoning_effort || "low";
  syncSettingsForm(curProv);
  syncInlineKeyBar();
  renderFavoritesBar();
  renderModelsBrowser();
}

function populateTopModelDropdown(provId, activeModelId) {
  const sel = document.getElementById("topModelSelect");
  const customInp = document.getElementById("topModelCustomInput");
  sel.innerHTML = "";

  const list = getAvailableModelsForProvider(provId);
  let foundInList = false;

  list.forEach(m => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = (m.name && m.name !== m.id) ? (m.name + " [" + m.id + "]") : m.id;
    if (m.id === activeModelId) foundInList = true;
    sel.appendChild(opt);
  });

  if (activeModelId && !foundInList) {
    const customOpt = document.createElement("option");
    customOpt.value = activeModelId;
    customOpt.textContent = t("custom_model_prefix") + activeModelId;
    sel.insertBefore(customOpt, sel.firstChild);
  }

  if (activeModelId) {
    sel.value = activeModelId;
    customInp.value = activeModelId;
  } else if (sel.options.length > 0) {
    sel.selectedIndex = 0;
    STATE.settings.model = sel.value;
    customInp.value = sel.value;
  }
}

function syncInlineKeyBar() {
  const prov = STATE.settings.provider || "anthropic";
  const model = STATE.settings.model || "";
  const pInfo = STATE.providers[prov] || {};
  const scope = document.getElementById("inlineKeyScope").value;
  const keyBtn = document.getElementById("btnToggleKeyDrawer");
  const statusEl = document.getElementById("inlineKeyStatusText");

  const mKeys = STATE.settings.model_api_keys || {};
  const pKeys = STATE.settings.api_keys || {};
  const curKey = (scope === "model")
    ? (mKeys[prov + "::" + model] || "")
    : (pKeys[prov] || "");

  document.getElementById("inlineApiKeyInput").value = curKey;
  document.getElementById("inlineApiKeyInput").placeholder = pInfo.key_placeholder || "API Key...";
  document.getElementById("inlineBaseUrlInput").value = (STATE.settings.base_urls && STATE.settings.base_urls[prov]) || pInfo.base_url || "";
  document.getElementById("inlineProviderHint").textContent = getProviderHint(pInfo);

  const effectiveKey = getEffectiveKey(prov, model);
  if (!pInfo.needs_key || effectiveKey.trim().length > 0) {
    keyBtn.className = "btn btn-sm btn-ok";
    keyBtn.textContent = t("btn_key_set");
    statusEl.className = "key-drawer-help";
    statusEl.firstElementChild.textContent = t("key_ok_status", { prov: pInfo.name || prov, model: model });
  } else {
    keyBtn.className = "btn btn-sm btn-warn";
    keyBtn.textContent = t("btn_key_enter");
    statusEl.className = "key-drawer-help missing";
    statusEl.firstElementChild.textContent = t("key_missing_status", { prov: pInfo.name || prov });
  }
}

function toggleKeyDrawer(forceState) {
  const drawer = document.getElementById("inlineKeyDrawer");
  const willOpen = (forceState !== undefined) ? forceState : !drawer.classList.contains("open");
  drawer.classList.toggle("open", willOpen);
  if (willOpen) syncInlineKeyBar();
}

function toggleInlineKeyVis() {
  const inp = document.getElementById("inlineApiKeyInput");
  inp.type = inp.type === "password" ? "text" : "password";
}

function saveInlineKeyAndFetch(doFetch) {
  const prov = STATE.settings.provider || "anthropic";
  const model = STATE.settings.model || "";
  const scope = document.getElementById("inlineKeyScope").value;
  const keyVal = document.getElementById("inlineApiKeyInput").value.trim();
  const baseUrlVal = document.getElementById("inlineBaseUrlInput").value.trim();

  if (!STATE.settings.base_urls) STATE.settings.base_urls = {};
  STATE.settings.base_urls[prov] = baseUrlVal;

  const patch = {
    provider: prov,
    model: model,
    base_urls: { [prov]: baseUrlVal }
  };

  if (scope === "model") {
    if (!STATE.settings.model_api_keys) STATE.settings.model_api_keys = {};
    STATE.settings.model_api_keys[prov + "::" + model] = keyVal;
    patch.model_api_keys = { [prov + "::" + model]: keyVal };
  } else {
    if (!STATE.settings.api_keys) STATE.settings.api_keys = {};
    STATE.settings.api_keys[prov] = keyVal;
    patch.api_keys = { [prov]: keyVal };
  }

  sendAction("save_settings", { settings: patch });
  syncSettingsForm(prov);
  syncInlineKeyBar();

  if (doFetch) {
    fetchModelsFromApi(keyVal, baseUrlVal);
  } else {
    showToast(t("toast_key_saved"));
  }
}

function syncSettingsForm(provId) {
  const p = STATE.providers[provId] || {};
  document.getElementById("cfgProvider").value = provId;
  document.getElementById("cfgProviderHint").textContent = getProviderHint(p);
  document.getElementById("cfgBaseUrl").value = (STATE.settings.base_urls && STATE.settings.base_urls[provId]) || p.base_url || "";
  document.getElementById("cfgApiKey").value = (STATE.settings.api_keys && STATE.settings.api_keys[provId]) || "";
  document.getElementById("cfgModel").value = STATE.settings.model || p.default_model || "";
  document.getElementById("cfgProtocolGroup").style.display = (provId === "custom") ? "flex" : "none";
  document.getElementById("cfgCustomProtocol").value = STATE.settings.custom_protocol || "openai";
  document.getElementById("cfgTemperature").value = STATE.settings.temperature ?? 0.3;
  document.getElementById("cfgMaxTokens").value = STATE.settings.max_tokens ?? 4096;
  document.getElementById("cfgSlicingAudit").checked = !!STATE.settings.enable_slicing_audit;
  document.getElementById("cfgCustomInstructions").value = STATE.settings.custom_user_instructions || "";
  syncPerModelKeyInput();
}

function syncPerModelKeyInput() {
  const prov = document.getElementById("cfgProvider").value || STATE.settings.provider;
  const model = document.getElementById("cfgModel").value.trim() || STATE.settings.model;
  const mKeys = STATE.settings.model_api_keys || {};
  document.getElementById("cfgModelSpecificKey").value = mKeys[prov + "::" + model] || "";
}

function renderFavoritesBar() {
  const bar = document.getElementById("favModelsBar");
  const mgr = document.getElementById("favManagerList");
  const favs = STATE.settings.favorite_models || [];
  bar.innerHTML = '<span style="font-size:11px; color:var(--text-muted); margin-right:4px;">' + escapeHtml(t("fav_bar_label")) + '</span>';
  mgr.innerHTML = "";

  favs.forEach((f, idx) => {
    const isAct = (f.provider === STATE.settings.provider && f.model === STATE.settings.model);
    const chip = document.createElement("button");
    chip.className = "fav-chip" + (isAct ? " active" : "");
    chip.textContent = f.label || f.model;
    chip.title = f.provider + " → " + f.model;
    chip.onclick = () => {
      STATE.settings.provider = f.provider;
      STATE.settings.model = f.model;
      populateProvidersUI();
      sendAction("save_settings", { settings: { provider: f.provider, model: f.model } });
    };
    bar.appendChild(chip);

    const mChip = document.createElement("div");
    mChip.className = "c-badge";
    mChip.style.display = "inline-flex";
    mChip.style.alignItems = "center";
    mChip.style.gap = "6px";
    mChip.innerHTML = '<strong>' + escapeHtml(f.label || f.model) + '</strong> <span>(' + escapeHtml(f.provider) + ')</span>';
    const delBtn = document.createElement("button");
    delBtn.className = "btn btn-danger btn-sm";
    delBtn.style.padding = "1px 5px";
    delBtn.textContent = "✕";
    delBtn.onclick = () => removeFavorite(idx);
    mChip.appendChild(delBtn);
    mgr.appendChild(mChip);
  });
}

function renderModelsBrowser() {
  const box = document.getElementById("modelsBrowser");
  if (!box) return;
  const provId = document.getElementById("cfgProvider").value || STATE.settings.provider;
  const filter = (document.getElementById("modelFilterInput").value || "").toLowerCase().trim();
  const list = getAvailableModelsForProvider(provId).filter(m =>
    !filter || m.id.toLowerCase().includes(filter) || (m.name && m.name.toLowerCase().includes(filter))
  );

  if (!list.length) {
    box.innerHTML = '<div style="padding:10px; color:var(--text-muted);">' + escapeHtml(t("no_models_found")) + '</div>';
    return;
  }

  box.innerHTML = "";
  list.slice(0, 300).forEach(m => {
    const row = document.createElement("div");
    row.className = "model-row-item";
    const left = document.createElement("div");
    left.style.overflow = "hidden";
    left.style.textOverflow = "ellipsis";
    left.innerHTML = '<strong>' + escapeHtml(m.name || m.id) + '</strong> <code style="font-size:11px; color:#7ee787;">' + escapeHtml(m.id) + '</code>';
    const right = document.createElement("div");
    right.style.display = "flex";
    right.style.gap = "4px";

    const useBtn = document.createElement("button");
    useBtn.className = "btn btn-sm btn-primary";
    useBtn.textContent = t("btn_select_model");
    useBtn.onclick = () => {
      document.getElementById("cfgModel").value = m.id;
      STATE.settings.provider = provId;
      STATE.settings.model = m.id;
      populateProvidersUI();
      sendAction("save_settings", { settings: { provider: provId, model: m.id } });
      showToast(m.id);
    };

    const favBtn = document.createElement("button");
    favBtn.className = "btn btn-sm";
    favBtn.textContent = "⭐";
    favBtn.onclick = () => addModelToFavorites(provId, m.id, m.name);

    right.appendChild(useBtn);
    right.appendChild(favBtn);
    row.appendChild(left);
    row.appendChild(right);
    box.appendChild(row);
  });
}

function onTopProviderChange() {
  const prov = document.getElementById("topProviderSelect").value;
  const p = STATE.providers[prov] || {};
  STATE.settings.provider = prov;
  STATE.settings.model = p.default_model || "";
  populateTopModelDropdown(prov, STATE.settings.model);
  syncSettingsForm(prov);
  syncInlineKeyBar();
  renderFavoritesBar();
  renderModelsBrowser();
  sendAction("save_settings", { settings: { provider: prov, model: STATE.settings.model } });

  if (!hasKeyForCurrent()) {
    toggleKeyDrawer(true);
  }
}

function onTopModelSelectChange() {
  const m = document.getElementById("topModelSelect").value;
  if (!m) return;
  STATE.settings.model = m;
  document.getElementById("topModelCustomInput").value = m;
  document.getElementById("cfgModel").value = m;
  syncInlineKeyBar();
  renderFavoritesBar();
  sendAction("save_settings", { settings: { model: m } });
}

function onTopCustomModelInput() {
  const m = document.getElementById("topModelCustomInput").value.trim();
  if (!m) return;
  STATE.settings.model = m;
  populateTopModelDropdown(STATE.settings.provider, m);
  document.getElementById("cfgModel").value = m;
  syncInlineKeyBar();
  renderFavoritesBar();
  sendAction("save_settings", { settings: { model: m } });
  showToast(m);
}

function onCfgProviderSelect() {
  const prov = document.getElementById("cfgProvider").value;
  const p = STATE.providers[prov] || {};
  syncSettingsForm(prov);
  document.getElementById("cfgModel").value = p.default_model || "";
  syncPerModelKeyInput();
  renderModelsBrowser();
}

function saveProviderConfig() {
  const prov = document.getElementById("cfgProvider").value;
  const baseUrl = document.getElementById("cfgBaseUrl").value.trim();
  const apiKey = document.getElementById("cfgApiKey").value.trim();
  const model = document.getElementById("cfgModel").value.trim();
  const modelSpecKey = document.getElementById("cfgModelSpecificKey").value.trim();
  const temp = parseFloat(document.getElementById("cfgTemperature").value) || 0.3;
  const maxTok = parseInt(document.getElementById("cfgMaxTokens").value, 10) || 4096;
  const slicingAudit = document.getElementById("cfgSlicingAudit").checked;
  const customInstr = document.getElementById("cfgCustomInstructions").value;
  const customProto = document.getElementById("cfgCustomProtocol").value;

  STATE.settings.provider = prov;
  if (model) STATE.settings.model = model;
  STATE.settings.temperature = temp;
  STATE.settings.max_tokens = maxTok;
  STATE.settings.enable_slicing_audit = slicingAudit;
  STATE.settings.custom_user_instructions = customInstr;
  STATE.settings.custom_protocol = customProto;
  STATE.settings.base_urls[prov] = baseUrl;
  STATE.settings.api_keys[prov] = apiKey;
  if (!STATE.settings.model_api_keys) STATE.settings.model_api_keys = {};
  STATE.settings.model_api_keys[prov + "::" + STATE.settings.model] = modelSpecKey;

  populateProvidersUI();
  sendAction("save_settings", {
    settings: {
      provider: prov,
      model: STATE.settings.model,
      temperature: temp,
      max_tokens: maxTok,
      enable_slicing_audit: slicingAudit,
      custom_user_instructions: customInstr,
      custom_protocol: customProto,
      base_urls: { [prov]: baseUrl },
      api_keys: { [prov]: apiKey },
      model_api_keys: { [prov + "::" + STATE.settings.model]: modelSpecKey }
    }
  });
  showToast(t("toast_key_saved"));
}

function saveQuickToggle() {
  const autoCtx = document.getElementById("chkAutoContext").checked;
  STATE.settings.auto_attach_context = autoCtx;
  sendAction("save_settings", { settings: { auto_attach_context: autoCtx } });
}

function onEffortChange(val) {
  STATE.settings.reasoning_effort = val || "low";
  sendAction("save_settings", { settings: { reasoning_effort: STATE.settings.reasoning_effort } });
}

function fetchModelsFromApi(overrideKey, overrideUrl) {
  const isSettingsTab = document.getElementById("view-settings").classList.contains("active");
  const prov = isSettingsTab ? document.getElementById("cfgProvider").value : document.getElementById("topProviderSelect").value;
  const model = STATE.settings.model || "";
  const pInfo = STATE.providers[prov] || {};

  let baseUrl = overrideUrl !== undefined ? overrideUrl : (
    isSettingsTab ? document.getElementById("cfgBaseUrl").value.trim() : (STATE.settings.base_urls[prov] || pInfo.base_url || "")
  );
  let apiKey = overrideKey !== undefined ? overrideKey : (
    isSettingsTab ? document.getElementById("cfgApiKey").value.trim() : (document.getElementById("inlineApiKeyInput").value.trim() || getEffectiveKey(prov, model))
  );

  if (pInfo.needs_key && prov !== "openrouter" && !apiKey) {
    toggleKeyDrawer(true);
    document.getElementById("inlineApiKeyInput").focus();
    showToast(t("toast_enter_key_first"), true);
    return;
  }

  const customProto = document.getElementById("cfgCustomProtocol").value;
  showToast(t("toast_loading_models", { prov: pInfo.name || prov }));
  sendAction("fetch_models", {
    provider: prov,
    base_url: baseUrl,
    api_key: apiKey,
    custom_protocol: customProto
  });
}

function addCurrentToFavorites() {
  const prov = document.getElementById("topProviderSelect").value;
  const model = document.getElementById("topModelCustomInput").value.trim() || document.getElementById("topModelSelect").value;
  if (!model) return;
  addModelToFavorites(prov, model);
}

function addModelToFavorites(prov, model, displayName) {
  const favs = STATE.settings.favorite_models || [];
  if (favs.some(f => f.provider === prov && f.model === model)) return;
  const shortLabel = displayName || (model.includes("/") ? model.split("/").pop() : model);
  favs.push({ provider: prov, model: model, label: shortLabel });
  STATE.settings.favorite_models = favs;
  renderFavoritesBar();
  sendAction("save_settings", { settings: { favorite_models: favs } });
  showToast("⭐ " + shortLabel);
}

function removeFavorite(idx) {
  const favs = STATE.settings.favorite_models || [];
  favs.splice(idx, 1);
  STATE.settings.favorite_models = favs;
  renderFavoritesBar();
  sendAction("save_settings", { settings: { favorite_models: favs } });
}

function toggleKeyVisibility(inputId) {
  const inp = document.getElementById(inputId || "cfgApiKey");
  inp.type = inp.type === "password" ? "text" : "password";
}

function renderContextAndInspector() {
  const badges = document.getElementById("contextBadges");
  const p = STATE.plate || {};
  const pr = STATE.presets || {};
  let html = "";

  html += '<span class="c-badge">' + escapeHtml(t("badge_printer")) + ' <strong>' + escapeHtml(pr.printer_preset || "—") + '</strong></span>';
  html += '<span class="c-badge">' + escapeHtml(t("badge_profile")) + ' <strong>' + escapeHtml(pr.process_preset || "—") + '</strong></span>';
  const fils = (pr.filament_presets && pr.filament_presets.length) ? pr.filament_presets.slice(0, 2).join(", ") + (pr.filament_presets.length > 2 ? " (+" + (pr.filament_presets.length - 2) + ")" : "") : "—";
  html += '<span class="c-badge">' + escapeHtml(t("badge_filament")) + ' <strong>' + escapeHtml(fils) + '</strong></span>';

  if (p.has_model) {
    html += '<span class="c-badge ok">' + escapeHtml(t("badge_on_plate")) + ' <strong>' + p.object_count + ' ' + escapeHtml(t("badge_pcs")) + ' (' + p.total_volume_cm3 + ' cm³)</strong></span>';
    if (p.total_overhang_45_mm2 > 50) {
      html += '<span class="c-badge warn">' + escapeHtml(t("badge_overhangs")) + ' <strong>' + p.total_overhang_45_mm2 + ' mm²</strong></span>';
    }
    if (p.warnings && p.warnings.length) {
      html += '<span class="c-badge warn" style="cursor:pointer" onclick="switchTab(\'inspector\')">' + escapeHtml(t("badge_warnings")) + ' <strong>' + p.warnings.length + '</strong></span>';
    }
  } else {
    html += '<span class="c-badge">' + escapeHtml(t("badge_empty")) + '</span>';
  }
  badges.innerHTML = html;

  const wBox = document.getElementById("inspectorWarnings");
  const oBox = document.getElementById("inspectorObjects");
  const prBox = document.getElementById("inspectorPresets");

  if (p.warnings && p.warnings.length) {
    wBox.innerHTML = p.warnings.map(w =>
      '<div class="warn-box ' + (w.level === "danger" ? "danger" : "") + '">⚠ ' + escapeHtml(w.text) + '</div>'
    ).join("");
  } else {
    wBox.innerHTML = p.has_model ? '<div style="color:#6bc47d; margin-bottom:8px;">' + escapeHtml(t("mesh_ok")) + '</div>' : '';
  }

  if (!p.has_model) {
    oBox.innerHTML = '<div style="color:var(--text-muted)">' + escapeHtml(t("plate_empty_hint")) + '</div>';
  } else {
    let tbl = '<table class="settings-table"><thead><tr>' +
      '<th>' + escapeHtml(t("th_obj")) + '</th>' +
      '<th>' + escapeHtml(t("th_dim")) + '</th>' +
      '<th>' + escapeHtml(t("th_vol")) + '</th>' +
      '<th>' + escapeHtml(t("th_bed")) + '</th>' +
      '<th>' + escapeHtml(t("th_ovh")) + '</th>' +
      '<th>' + escapeHtml(t("th_mesh")) + '</th>' +
      '</tr></thead><tbody>';
    (p.objects || []).forEach(o => {
      const mStatus = (!o.is_manifold || o.mesh_errors > 0)
        ? '<span style="color:var(--danger)">' + escapeHtml(t("mesh_err")) + ' (' + o.mesh_errors + ')</span>'
        : '<span style="color:#6bc47d">Manifold OK</span>';
      tbl += '<tr>' +
        '<td><strong>' + escapeHtml(o.name) + '</strong> (x' + o.instances + ')</td>' +
        '<td>' + o.size_x + ' × ' + o.size_y + ' × ' + o.size_z + ' mm (H/B ' + o.height_to_base_ratio + ':1)</td>' +
        '<td>' + o.volume_cm3 + ' cm³ (' + o.triangles + ' tri)</td>' +
        '<td>' + o.bed_contact_mm2 + ' mm²</td>' +
        '<td>' + o.overhang_45_mm2 + ' mm² (' + o.overhang_45_pct + '%) / ' + o.overhang_60_mm2 + ' mm²</td>' +
        '<td>' + mStatus + '</td>' +
        '</tr>';
    });
    tbl += '</tbody></table>';
    oBox.innerHTML = tbl;
  }

  const groups = pr.groups || {};
  let pHtml = '<div class="grid-2">';
  Object.keys(groups).forEach(gTitle => {
    const items = groups[gTitle] || [];
    pHtml += '<div style="background:var(--bg-input); border:1px solid var(--border); border-radius:8px; padding:10px;">';
    pHtml += '<div style="font-weight:700; color:#67ece0; margin-bottom:6px;">' + escapeHtml(gTitle) + '</div>';
    pHtml += '<table class="settings-table"><tbody>';
    items.forEach(it => {
      pHtml += '<tr><td style="color:var(--text-muted)">' + escapeHtml(it.label) + ' <code style="font-size:10.5px;">' + escapeHtml(it.key) + '</code></td>' +
               '<td style="text-align:right; font-weight:600;">' + escapeHtml(it.value) + '</td></tr>';
    });
    pHtml += '</tbody></table></div>';
  });
  pHtml += '</div>';
  prBox.innerHTML = pHtml;
}

function renderChats() {
  const sList = document.getElementById("sessionList");
  const mArea = document.getElementById("messagesArea");
  const sessions = (STATE.chats && STATE.chats.sessions) || [];
  const activeId = STATE.chats && STATE.chats.active_id;

  sList.innerHTML = "";
  sessions.forEach(s => {
    const item = document.createElement("div");
    item.className = "session-item" + (s.id === activeId ? " active" : "");
    const titleSpan = document.createElement("span");
    titleSpan.className = "session-title";
    titleSpan.textContent = s.title || "Chat";
    titleSpan.onclick = () => sendAction("select_chat", { chat_id: s.id });

    const delBtn = document.createElement("button");
    delBtn.className = "session-del";
    delBtn.textContent = "✕";
    delBtn.onclick = (e) => {
      e.stopPropagation();
      sendAction("delete_chat", { chat_id: s.id });
    };
    item.appendChild(titleSpan);
    item.appendChild(delBtn);
    sList.appendChild(item);
  });

  const activeSession = sessions.find(s => s.id === activeId) || sessions[0];
  const msgs = (activeSession && activeSession.messages) || [];
  mArea.innerHTML = "";
  LAST_SUGGESTIONS_MAP = {};

  if (!msgs.length) {
    mArea.innerHTML =
      '<div class="card" style="max-width:700px; margin:auto; text-align:center;">' +
      '<h3 style="margin-top:0; color:#67ece0;">' + escapeHtml(t("welcome_title")) + '</h3>' +
      '<p style="color:var(--text-muted);">' + t("welcome_desc") + '</p>' +
      '<div style="display:flex; flex-wrap:wrap; gap:8px; justify-content:center; margin-top:12px;">' +
      '<button class="btn btn-warn" onclick="toggleKeyDrawer(true)">' + escapeHtml(t("welcome_btn_key")) + '</button>' +
      '<button class="btn btn-primary" onclick="runQuickPrompt(\'full_audit\')">' + escapeHtml(t("q_full_audit")) + '</button>' +
      '<button class="btn" onclick="runQuickPrompt(\'orientation_supports\')">' + escapeHtml(t("q_supports")) + '</button>' +
      '<button class="btn" onclick="runQuickPrompt(\'strength_functional\')">' + escapeHtml(t("q_strength")) + '</button>' +
      '</div></div>';
    return;
  }

  msgs.forEach((m, msgIdx) => {
    const row = document.createElement("div");
    row.className = "msg-row " + (m.role === "user" ? "user" : "assistant");
    const meta = document.createElement("div");
    meta.className = "msg-meta";
    meta.textContent = (m.role === "user" ? t("you_label") : ("🤖 " + (m.model || t("ai_label")))) + (m.timestamp ? " • " + m.timestamp : "");
    const bubble = document.createElement("div");
    bubble.className = "msg-bubble";
    bubble.innerHTML = renderMarkdown(m.content);

    if (m.suggestions && m.suggestions.length) {
      const cardId = "sug_" + msgIdx;
      LAST_SUGGESTIONS_MAP[cardId] = m.suggestions;
      const card = document.createElement("div");
      card.className = "settings-apply-card";
      let tbl = '<div class="settings-apply-head">' +
        '<span>' + escapeHtml(t("sug_head", { n: m.suggestions.length })) + '</span>' +
        '<button class="btn btn-primary btn-sm" onclick="applySelectedSuggestions(\'' + cardId + '\')">' + escapeHtml(t("btn_apply_sug")) + '</button>' +
        '</div>';
      tbl += '<table class="settings-table"><thead><tr><th style="width:26px;"><input type="checkbox" checked onchange="toggleAllSug(\'' + cardId + '\', this.checked)" /></th>' +
        '<th>' + escapeHtml(t("th_param")) + '</th>' +
        '<th>' + escapeHtml(t("th_change")) + '</th>' +
        '<th>' + escapeHtml(t("th_reason")) + '</th></tr></thead><tbody>';
      m.suggestions.forEach((s, sIdx) => {
        const curVal = (STATE.presets && STATE.presets.flat_values && STATE.presets.flat_values[s.key]) || s.current_value || "—";
        tbl += '<tr>' +
          '<td><input type="checkbox" class="chk-' + cardId + '" data-idx="' + sIdx + '" checked /></td>' +
          '<td><strong>' + escapeHtml(s.label) + '</strong><br/><code style="font-size:10.5px;">' + escapeHtml(s.key) + '</code></td>' +
          '<td><span class="val-old">' + escapeHtml(curVal) + '</span> → <span class="val-new">' + escapeHtml(s.value) + '</span></td>' +
          '<td style="color:var(--text-muted)">' + escapeHtml(s.reason || "") + '</td>' +
          '</tr>';
      });
      tbl += '</tbody></table>';
      card.innerHTML = tbl;
      bubble.appendChild(card);
    }

    row.appendChild(meta);
    row.appendChild(bubble);
    mArea.appendChild(row);
  });

  mArea.scrollTop = mArea.scrollHeight;
}

function toggleAllSug(cardId, checked) {
  document.querySelectorAll(".chk-" + cardId).forEach(cb => { cb.checked = checked; });
}

function applySelectedSuggestions(cardId) {
  const list = LAST_SUGGESTIONS_MAP[cardId] || [];
  const selected = [];
  document.querySelectorAll(".chk-" + cardId).forEach(cb => {
    if (cb.checked) {
      const idx = parseInt(cb.getAttribute("data-idx"), 10);
      if (list[idx]) selected.push(list[idx]);
    }
  });
  if (!selected.length) {
    showToast(t("toast_select_one"), true);
    return;
  }
  sendAction("apply_settings", { changes: selected });
}

function onChatKeydown(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function onPhotoSelected(e) {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = function(ev) {
    const dataUrl = String(ev.target.result || "");
    const parts = dataUrl.split(",");
    if (parts.length === 2) {
      const mimeMatch = parts[0].match(/data:([^;]+);base64/);
      ATTACHED_IMAGE = {
        name: file.name,
        mime: mimeMatch ? mimeMatch[1] : (file.type || "image/jpeg"),
        base64: parts[1]
      };
      document.getElementById("attachmentLabel").textContent = "📷 " + file.name;
      document.getElementById("attachmentBar").style.display = "flex";
    }
  };
  reader.readAsDataURL(file);
}

function clearAttachment() {
  ATTACHED_IMAGE = null;
  document.getElementById("photoInput").value = "";
  document.getElementById("attachmentBar").style.display = "none";
}

function onGcodeFilePicked(e) {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";
  if (!file || STATE.busy) return;
  const reader = new FileReader();
  reader.onload = function(ev) {
    setBusy(true, t("status_working"));
    sendAction("audit_gcode_content", {
      filename: file.name,
      content: String(ev.target.result || "")
    });
  };
  reader.readAsText(file);
}

function setBusy(isBusy, statusText) {
  STATE.busy = isBusy;
  const btn = document.getElementById("btnSend");
  btn.disabled = isBusy;
  btn.textContent = isBusy ? t("btn_thinking") : t("btn_send");
  document.getElementById("statusLine").textContent = statusText || (isBusy ? t("status_working") : t("status_ready"));
}

function sendMessage(overrideText) {
  if (STATE.busy) return;
  const inp = document.getElementById("chatInput");
  const text = (overrideText !== undefined ? overrideText : inp.value).trim();
  if (!text) return;

  if (!hasKeyForCurrent()) {
    toggleKeyDrawer(true);
    document.getElementById("inlineApiKeyInput").focus();
    showToast(t("toast_enter_key_first"), true);
    return;
  }

  if (overrideText === undefined) inp.value = "";

  const prov = document.getElementById("topProviderSelect").value;
  const model = document.getElementById("topModelCustomInput").value.trim() || document.getElementById("topModelSelect").value;
  const attachCtx = document.getElementById("chkAutoContext").checked;

  setBusy(true, t("status_working"));
  sendAction("send_chat", {
    text: text,
    provider: prov,
    model: model,
    attach_context: attachCtx,
    image: ATTACHED_IMAGE
  });
  clearAttachment();
}

function runQuickPrompt(kind) {
  const map = {
    full_audit: t("prompt_full_audit"),
    orientation_supports: t("prompt_supports"),
    strength_functional: t("prompt_strength"),
    quality_surface: t("prompt_quality"),
    speed_optimize: t("prompt_speed"),
    filament_check: t("prompt_filament")
  };
  switchTab("chat");
  sendMessage(map[kind] || map.full_audit);
}

function handleHostPayload(msg) {
  if (!msg || typeof msg !== "object") return;
  if (msg.type === "full_state") {
    STATE.providers = msg.providers || STATE.providers;
    STATE.settings = msg.settings || STATE.settings;
    STATE.chats = msg.chats || STATE.chats;
    STATE.plate = msg.plate || STATE.plate;
    STATE.presets = msg.presets || STATE.presets;
    applyStaticI18n();
    populateProvidersUI();
    renderContextAndInspector();
    renderChats();
    setBusy(false, t("status_ready"));
    if (!hasKeyForCurrent()) {
      toggleKeyDrawer(true);
    }
  } else if (msg.type === "context_updated") {
    STATE.plate = msg.plate || STATE.plate;
    STATE.presets = msg.presets || STATE.presets;
    renderContextAndInspector();
    if (msg.toast) showToast(msg.toast);
  } else if (msg.type === "stream_chunk") {
    const mArea = document.getElementById("messagesArea");
    let row = document.getElementById("streamingBubbleRow");
    if (!row) {
      row = document.createElement("div");
      row.id = "streamingBubbleRow";
      row.className = "msg-row assistant";
      row.innerHTML = '<div class="msg-meta">🤖 ' + escapeHtml(msg.model || t("ai_label")) + ' ⏳</div><div class="msg-bubble" id="streamingBubbleBody"></div>';
      mArea.appendChild(row);
    }
    const bodyEl = document.getElementById("streamingBubbleBody");
    if (bodyEl) bodyEl.innerHTML = renderMarkdown(msg.text || "");
    mArea.scrollTop = mArea.scrollHeight;
  } else if (msg.type === "chats_updated") {
    STATE.chats = msg.chats || STATE.chats;
    if (msg.plate) STATE.plate = msg.plate;
    if (msg.presets) STATE.presets = msg.presets;
    renderContextAndInspector();
    renderChats();
    setBusy(false, t("status_ready"));
  } else if (msg.type === "models_loaded") {
    setBusy(false, t("status_ready"));
    if (msg.ok) {
      STATE.settings = msg.settings || STATE.settings;
      populateProvidersUI();
      showToast(t("toast_models_loaded", { n: msg.count || 0 }));
    } else {
      if (msg.needs_key) {
        toggleKeyDrawer(true);
        document.getElementById("inlineApiKeyInput").focus();
      }
      showToast(msg.error || "Error", true);
    }
  } else if (msg.type === "settings_applied") {
    if (msg.presets) STATE.presets = msg.presets;
    renderContextAndInspector();
    renderChats();
    if (msg.ok) {
      showToast(t("toast_settings_applied", { n: msg.applied ? msg.applied.length : 0 }));
    } else {
      showToast("⚠ " + (msg.errors || []).join("; "), true);
    }
  } else if (msg.type === "toast") {
    setBusy(false, t("status_ready"));
    showToast(msg.text || "", !!msg.is_error);
  }
}

window.onHostMessage = handleHostPayload;
if (window.orca && typeof window.orca.onMessage === "function") {
  window.orca.onMessage(handleHostPayload);
}

window.addEventListener("DOMContentLoaded", function() {
  applyStaticI18n();
  sendAction("init");
});
</script>
</body>
</html>
"""


# ============================================================================
# 7. КОНТРОЛЛЕР ПЛАГИНА И ВЗАИМОДЕЙСТВИЕ С UI ORCASLICER
# ============================================================================

class AssistantController:
    def __init__(self) -> None:
        self.storage = StorageManager()
        self._page_instances: list[Any] = []
        self._dock_panel: Any = None
        self._last_plate_snapshot: dict[str, Any] = {"has_model": False, "objects": [], "warnings": []}
        self._last_presets_snapshot: dict[str, Any] = {"groups": {}, "flat_values": {}}
        self._lock = threading.RLock()

    def register_page(self, page_obj: Any) -> None:
        with self._lock:
            if page_obj is not None and page_obj not in self._page_instances:
                self._page_instances.append(page_obj)

    def capture_ui_snapshots(self) -> tuple[dict[str, Any], dict[str, Any]]:
        lang = self.storage.get_lang()
        try:
            plate = inspect_plate_geometry(lang)
            self._last_plate_snapshot = plate
        except Exception:
            plate = self._last_plate_snapshot

        try:
            presets = inspect_slicer_presets(lang)
            self._last_presets_snapshot = presets
        except Exception:
            presets = self._last_presets_snapshot

        return plate, presets

    def emit(self, payload: dict[str, Any]) -> None:
        with self._lock:
            pages = list(self._page_instances)
            dock = self._dock_panel

        for p in pages:
            try:
                p.post_message(payload)
            except Exception:
                pass

        if dock is not None:
            try:
                dock.post(payload)
            except Exception:
                pass

    def open_dock_panel(self) -> None:
        lang = self.storage.get_lang()
        try:
            if self._dock_panel is not None and self._dock_panel.is_open():
                self._dock_panel.show()
                self._send_full_state()
                return
            self._dock_panel = orca.host.ui.create_dock_panel(
                html=UI_HTML,
                title=tr(lang, "🤖 Orca AI Ассистент", "🤖 Orca AI Асистент", "🤖 Orca AI Assistant"),
                width=460,
                height=740,
                on_message=self.handle_message_on_ui,
                on_close=self._on_dock_closed,
                dock="right",
            )
        except Exception as exc:
            self.emit({
                "type": "toast",
                "text": tr(lang, f"Не удалось открыть панель: {exc}", f"Не вдалося відкрити панель: {exc}", f"Could not open dock panel: {exc}"),
                "is_error": True,
            })

    def _on_dock_closed(self) -> None:
        self._dock_panel = None

    def handle_message_on_ui(self, raw_msg: Any) -> None:
        data: dict[str, Any] = {}
        if isinstance(raw_msg, dict):
            data = raw_msg
            if "action" not in data and isinstance(data.get("data"), dict):
                data = data["data"]
        elif isinstance(raw_msg, str):
            try:
                parsed = json.loads(raw_msg)
                if isinstance(parsed, dict):
                    data = parsed
            except Exception:
                return
        if not data:
            return

        action = str(data.get("action") or "")

        if action == "change_language":
            new_lang = norm_lang(data.get("language", "ru"))
            self.storage.update_settings({"language": new_lang})
            plate, presets = self.capture_ui_snapshots()
            self.emit({
                "type": "context_updated",
                "plate": plate,
                "presets": presets,
                "toast": tr(
                    new_lang,
                    "🇷🇺 Язык переключён на Русский (перезапустите OrcaSlicer для обновления названия вкладки)",
                    "🇺🇦 Мову перемкнено на Українську (перезапустіть OrcaSlicer для оновлення назви вкладки)",
                    "🇬🇧 Language switched to English (restart OrcaSlicer to update the top tab name)",
                ),
            })
            return

        plate, presets = self.capture_ui_snapshots()
        lang = self.storage.get_lang()

        if action == "init":
            self._send_full_state(plate, presets)
        elif action == "refresh_context":
            self.emit({
                "type": "context_updated",
                "plate": plate,
                "presets": presets,
                "toast": tr(lang, "Данные 3D-стола и профиля обновлены!", "Дані 3D-столу та профілю оновлено!", "Build plate & preset data refreshed!"),
            })
        elif action == "open_dock":
            self.open_dock_panel()
        elif action == "save_settings":
            patch = data.get("settings") or {}
            if isinstance(patch, dict):
                self.storage.update_settings(patch)
        elif action == "import_printpurr":
            cnt, new_settings = self.storage.import_from_printpurr()
            self.emit({
                "type": "full_state",
                "providers": PROVIDER_PRESETS,
                "settings": new_settings,
                "chats": self.storage.get_chats(),
                "plate": plate,
                "presets": presets,
            })
            self.emit({
                "type": "toast",
                "text": (
                    tr(lang, f"Импортировано ключей из PrintPurr: {cnt}", f"Імпортовано ключів із PrintPurr: {cnt}", f"Imported {cnt} keys from PrintPurr")
                    if cnt else
                    tr(lang, "В PrintPurr не найдено сохранённых ключей", "У PrintPurr не знайдено збережених ключів", "No saved keys found in PrintPurr")
                ),
                "is_error": cnt == 0,
            })
        elif action == "new_chat":
            chats = self.storage.get_chats()
            new_id = f"chat_{int(time.time() * 1000)}"
            chats.setdefault("sessions", []).insert(0, {
                "id": new_id,
                "title": tr(lang, "Новый диалог", "Новий діалог", "New Chat"),
                "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                "messages": [],
            })
            chats["active_id"] = new_id
            self.storage.save_chats(chats)
            self.emit({"type": "chats_updated", "chats": chats})
        elif action == "select_chat":
            cid = str(data.get("chat_id") or "")
            chats = self.storage.get_chats()
            chats["active_id"] = cid
            self.storage.save_chats(chats)
            self.emit({"type": "chats_updated", "chats": chats})
        elif action == "delete_chat":
            cid = str(data.get("chat_id") or "")
            chats = self.storage.get_chats()
            sessions = [s for s in chats.get("sessions", []) if s.get("id") != cid]
            if not sessions:
                first_id = f"chat_{int(time.time() * 1000)}"
                sessions = [{
                    "id": first_id,
                    "title": tr(lang, "Новый диалог", "Новий діалог", "New Chat"),
                    "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                    "messages": [],
                }]
            chats["sessions"] = sessions
            if chats.get("active_id") == cid:
                chats["active_id"] = sessions[0]["id"]
            self.storage.save_chats(chats)
            self.emit({"type": "chats_updated", "chats": chats})
        elif action == "clear_chat":
            chats = self.storage.get_chats()
            active_id = chats.get("active_id")
            for s in chats.get("sessions", []):
                if s.get("id") == active_id:
                    s["messages"] = []
                    s["title"] = tr(lang, "Новый диалог", "Новий діалог", "New Chat")
            self.storage.save_chats(chats)
            self.emit({"type": "chats_updated", "chats": chats})
        elif action == "fetch_models":
            threading.Thread(target=self._worker_fetch_models, args=(data,), daemon=True).start()
        elif action == "send_chat":
            threading.Thread(target=self._worker_send_chat, args=(data, plate, presets), daemon=True).start()
        elif action == "apply_settings":
            changes = data.get("changes") or []
            threading.Thread(target=self._worker_apply_settings, args=(changes,), daemon=True).start()
        elif action == "audit_gcode_content":
            fname = str(data.get("filename") or "sliced.gcode")
            gcontent = str(data.get("content") or "")
            threading.Thread(target=self._worker_audit_gcode_text, args=(fname, gcontent, plate, presets), daemon=True).start()

    def _send_full_state(self, plate: dict[str, Any] | None = None, presets: dict[str, Any] | None = None) -> None:
        if plate is None or presets is None:
            plate, presets = self.capture_ui_snapshots()
        self.emit({
            "type": "full_state",
            "providers": PROVIDER_PRESETS,
            "settings": self.storage.get_settings(),
            "chats": self.storage.get_chats(),
            "plate": plate,
            "presets": presets,
        })

    def _worker_fetch_models(self, data: dict[str, Any]) -> None:
        settings = self.storage.get_settings()
        lang = norm_lang(settings.get("language", "ru"))
        provider = str(data.get("provider") or settings.get("provider") or "anthropic")
        base_url = str(data.get("base_url") or settings.get("base_urls", {}).get(provider) or PROVIDER_PRESETS.get(provider, {}).get("base_url") or "")
        api_key = str(data.get("api_key") or self.storage.resolve_effective_api_key(provider, str(settings.get("model") or "")))
        custom_proto = str(data.get("custom_protocol") or settings.get("custom_protocol") or "openai")

        res = fetch_provider_models(provider, base_url, api_key, custom_proto, lang=lang)
        if res.get("ok"):
            patch: dict[str, Any] = {
                "cached_models": {provider: res["models"]},
                "base_urls": {provider: base_url},
            }
            if api_key:
                patch["api_keys"] = {provider: api_key}
            updated = self.storage.update_settings(patch)
            self.emit({
                "type": "models_loaded",
                "ok": True,
                "count": res.get("count", 0),
                "settings": updated,
            })
        else:
            self.emit({
                "type": "models_loaded",
                "ok": False,
                "needs_key": bool(res.get("needs_key")),
                "error": res.get("error", "Error"),
            })

    def _worker_send_chat(self, data: dict[str, Any], plate: dict[str, Any], presets: dict[str, Any]) -> None:
        user_text = str(data.get("text") or "").strip()
        if not user_text:
            return

        settings = self.storage.get_settings()
        lang = norm_lang(settings.get("language", "ru"))
        provider = str(data.get("provider") or settings.get("provider") or "anthropic")
        model_id = str(data.get("model") or settings.get("model") or PROVIDER_PRESETS.get(provider, {}).get("default_model") or "")
        attach_ctx = bool(data.get("attach_context", settings.get("auto_attach_context", True)))
        image_att = data.get("image") if isinstance(data.get("image"), dict) else None

        settings = self.storage.update_settings({"provider": provider, "model": model_id})

        chats = self.storage.append_message_to_active("user", user_text)
        self.emit({"type": "chats_updated", "chats": chats})

        base_sys_prompt = get_system_prompt(lang)
        if attach_ctx:
            ctx_md = build_full_context_markdown(plate, presets, str(settings.get("custom_user_instructions") or ""), lang=lang)
            sys_prompt = f"{base_sys_prompt}\n\n{ctx_md}"
        else:
            sys_prompt = base_sys_prompt

        active_id = chats.get("active_id")
        active_session = next((s for s in chats.get("sessions", []) if s.get("id") == active_id), None)
        history_msgs = list((active_session or {}).get("messages", []))[-16:]

        base_url = str(settings.get("base_urls", {}).get(provider) or PROVIDER_PRESETS.get(provider, {}).get("base_url") or "")
        api_key = self.storage.resolve_effective_api_key(provider, model_id)

        def _on_stream(partial_text: str) -> None:
            self.emit({"type": "stream_chunk", "model": model_id, "text": partial_text})

        resp = send_chat_completion(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            model_id=model_id,
            messages=history_msgs,
            system_prompt=sys_prompt,
            temperature=float(settings.get("temperature", 0.3)),
            max_tokens=int(settings.get("max_tokens", 4096)),
            custom_protocol=str(settings.get("custom_protocol") or "openai"),
            image_attachment=image_att,
            lang=lang,
            reasoning_effort=str(settings.get("reasoning_effort") or "low"),
            on_chunk=_on_stream,
        )

        if resp.get("ok"):
            reply_text = str(resp["reply"])
            suggestions = extract_suggested_settings(reply_text, presets.get("flat_values", {}), lang=lang)
            updated_chats = self.storage.append_message_to_active(
                "assistant",
                reply_text,
                extra={"model": model_id, "suggestions": suggestions},
            )
            self.emit({
                "type": "chats_updated",
                "chats": updated_chats,
                "plate": plate,
                "presets": presets,
            })
        else:
            err_title = tr(
                lang,
                f"❌ **Ошибка запроса к ИИ ({provider} / {model_id}):**",
                f"❌ **Помилка запиту до ШІ ({provider} / {model_id}):**",
                f"❌ **AI Request Error ({provider} / {model_id}):**",
            )
            err_msg = f"{err_title}\n\n{resp.get('error')}"
            updated_chats = self.storage.append_message_to_active("assistant", err_msg, extra={"model": model_id})
            self.emit({"type": "chats_updated", "chats": updated_chats})

    def _worker_apply_settings(self, changes: list[dict[str, Any]]) -> None:
        lang = self.storage.get_lang()
        res = apply_settings_to_orcaslicer(changes, lang=lang)
        for item in res.get("applied", []):
            self._last_presets_snapshot.setdefault("flat_values", {})[item["key"]] = item["value"]
            for grp_items in self._last_presets_snapshot.get("groups", {}).values():
                for g_it in grp_items:
                    if g_it.get("key") == item["key"]:
                        g_it["value"] = item["value"]

        self.emit({
            "type": "settings_applied",
            "ok": res["ok"],
            "applied": res["applied"],
            "errors": res["errors"],
            "presets": self._last_presets_snapshot,
        })

    def _worker_audit_gcode_text(self, filename: str, gcode_text: str, plate: dict[str, Any], presets: dict[str, Any]) -> None:
        lang = self.storage.get_lang()
        summary = summarize_gcode_text(gcode_text, filename)
        if lang == "uk":
            prompt = (
                f"Проведи технічний аудит нарізаного G-code файлу `{summary['filename']}` ({summary['size_mb']} МБ).\n"
                f"- Шарів: {summary['layer_count']}, макс. висота Z: {summary['max_z']} мм\n"
                f"- Температури сопла (M104/M109): {', '.join(summary['m104_temps']) or 'немає даних'} °C\n"
                f"- Температури столу (M140/M190): {', '.join(summary['m140_temps']) or 'немає даних'} °C\n"
                f"- Наявність пауз M600/M25: {'Так' if summary['has_m600_pause'] else 'Ні'}\n"
                f"- Коментарі заголовка:\n```text\n" + "\n".join(summary["header_comments"][:30]) + "\n```\n"
                f"- Зведення слайсера в кінці файлу:\n```text\n" + "\n".join(summary["footer_comments"][-40:]) + "\n```\n"
                "Оціни час друку, витрату пластику, коректність температур і запропонуй покращення в блоці ```orca-settings."
            )
        elif lang == "en":
            prompt = (
                f"Perform a technical audit of the sliced G-code file `{summary['filename']}` ({summary['size_mb']} MB).\n"
                f"- Layers: {summary['layer_count']}, max Z height: {summary['max_z']} mm\n"
                f"- Nozzle temperatures (M104/M109): {', '.join(summary['m104_temps']) or 'none'} °C\n"
                f"- Bed temperatures (M140/M190): {', '.join(summary['m140_temps']) or 'none'} °C\n"
                f"- M600/M25 pauses present: {'Yes' if summary['has_m600_pause'] else 'No'}\n"
                f"- Header comments:\n```text\n" + "\n".join(summary["header_comments"][:30]) + "\n```\n"
                f"- Footer slicer summary:\n```text\n" + "\n".join(summary["footer_comments"][-40:]) + "\n```\n"
                "Evaluate print time, filament usage, temperature consistency, and suggest improvements in an ```orca-settings block."
            )
        else:
            prompt = (
                f"Проведи технический аудит нарезанного G-code файла `{summary['filename']}` ({summary['size_mb']} МБ).\n"
                f"- Слоёв: {summary['layer_count']}, макс. высота Z: {summary['max_z']} мм\n"
                f"- Температуры сопла (M104/M109): {', '.join(summary['m104_temps']) or 'нет данных'} °C\n"
                f"- Температуры стола (M140/M190): {', '.join(summary['m140_temps']) or 'нет данных'} °C\n"
                f"- Наличие пауз M600/M25: {'Да' if summary['has_m600_pause'] else 'Нет'}\n"
                f"- Комментарии заголовка:\n```text\n" + "\n".join(summary["header_comments"][:30]) + "\n```\n"
                f"- Сводка слайсера в конце файла:\n```text\n" + "\n".join(summary["footer_comments"][-40:]) + "\n```\n"
                "Оцени время печати, расход пластика, корректность температур и предложи улучшения в блоке ```orca-settings."
            )
        self._worker_send_chat({"text": prompt, "attach_context": True}, plate, presets)


CONTROLLER: AssistantController | None = None


def get_controller() -> AssistantController:
    global CONTROLLER
    if CONTROLLER is None:
        CONTROLLER = AssistantController()
    return CONTROLLER


# ============================================================================
# 8. CAPABILITIES ПЛАГИНА ORCASLICER 2.5
# ============================================================================

if _PAGES_BASE is not None:
    class OrcaAIAssistantPage(_PAGES_BASE):
        def get_name(self) -> str:
            lang = get_controller().storage.get_lang()
            return tr(lang, "Orca AI Ассистент", "Orca AI Асистент", "Orca AI Assistant")

        def get_ui(self) -> str:
            get_controller().register_page(self)
            return UI_HTML

        def get_icon(self) -> str:
            try:
                TAB_ICON_PATH.write_text(TAB_ICON_SVG, encoding="utf-8")
                return str(TAB_ICON_PATH)
            except OSError:
                return ""

        def on_message(self, message: Any) -> None:
            ctrl = get_controller()
            ctrl.register_page(self)
            ctrl.handle_message_on_ui(message)
else:
    OrcaAIAssistantPage = None


if _SCRIPT_BASE is not None:
    class OrcaAIDockScript(_SCRIPT_BASE):
        def get_name(self) -> str:
            lang = get_controller().storage.get_lang()
            return tr(lang, "Orca AI: Панель у 3D-стола", "Orca AI: Панель біля 3D-столу", "Orca AI: Dock Panel")

        def execute(self) -> Any:
            ctrl = get_controller()
            ctrl.open_dock_panel()
            return orca.ExecutionResult.success("Orca AI Assistant dock panel opened.")
else:
    OrcaAIDockScript = None


if _PIPELINE_BASE is not None:
    class OrcaAIGcodeAuditor(_PIPELINE_BASE):
        def get_name(self) -> str:
            lang = get_controller().storage.get_lang()
            return tr(lang, "Orca AI: Аудит G-code", "Orca AI: Аудит G-code", "Orca AI: G-code Audit")

        def execute(self, ctx: Any) -> Any:
            try:
                if ctx.step != _GCODE_STEP or not getattr(ctx, "gcode_path", None):
                    return orca.ExecutionResult.success()
                ctrl = get_controller()
                settings = ctrl.storage.get_settings()
                if settings.get("enable_slicing_audit"):
                    gpath = Path(str(ctx.gcode_path))
                    if gpath.is_file():
                        raw = gpath.read_text(encoding="utf-8", errors="replace")
                        threading.Thread(
                            target=ctrl._worker_audit_gcode_text,
                            args=(gpath.name, raw, ctrl._last_plate_snapshot, ctrl._last_presets_snapshot),
                            daemon=True,
                        ).start()
            except Exception:
                pass
            return orca.ExecutionResult.success()
else:
    OrcaAIGcodeAuditor = None


@orca.plugin
class OrcaAIAssistantPlugin(orca.base):
    def register_capabilities(self) -> None:
        try:
            orca.request_permissions(
                network_http=[
                    "https://openrouter.ai",
                    "https://generativelanguage.googleapis.com",
                    "https://api.openai.com",
                    "https://api.anthropic.com",
                    "https://api.deepseek.com",
                    "https://open.bigmodel.cn",
                    "https://api.groq.com",
                    "https://api.cerebras.ai",
                    "https://api.mistral.ai",
                    "https://api.x.ai",
                    "http://localhost",
                    "http://127.0.0.1",
                ],
                threading=True,
            )
        except Exception:
            pass

        if OrcaAIAssistantPage is not None:
            orca.register_capability(OrcaAIAssistantPage)
        if OrcaAIDockScript is not None:
            orca.register_capability(OrcaAIDockScript)
        if OrcaAIGcodeAuditor is not None:
            orca.register_capability(OrcaAIGcodeAuditor)
