from __future__ import annotations

import re
from typing import Any

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
    "mistral": {
        "name": "Mistral AI",
        "protocol": "openai",
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-large-latest",
        "needs_key": True,
        "key_placeholder": "Mistral API Key...",
        "hint": "Официальный API Mistral AI. Ключ: console.mistral.ai",
        "hint_i18n": {
            "ru": "Официальный API Mistral AI (Mistral Large / Small / Pixtral). Ключ: console.mistral.ai",
            "uk": "Офіційний API Mistral AI (Mistral Large / Small / Pixtral). Ключ: console.mistral.ai",
            "en": "Official Mistral AI API (Mistral Large / Small / Pixtral). Key: console.mistral.ai",
        },
        "suggested_models": [
            {"id": "mistral-large-latest", "name": "Mistral Large (Flagship)"},
            {"id": "mistral-medium-latest", "name": "Mistral Medium"},
            {"id": "mistral-small-latest", "name": "Mistral Small (Fast)"},
            {"id": "pixtral-large-latest", "name": "Pixtral Large (Vision)"},
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

_NON_CHAT_MODEL_RE = re.compile(
    r"(?:^|[-_/:.])(?:tts|whisper|embed|embedding|embeddings|text-embedding|dall-e|imagen|"
    r"moderation|realtime|transcribe|rerank|veo|sora|lyria|babbage|davinci|aqa)(?:$|[-_/:.0-9])"
    r"|audio-preview|text-embedding|dall-e|whisper|embedding|moderation|realtime|transcribe|imagen",
    re.IGNORECASE,
)


def is_chat_model(model_id: str) -> bool:
    """Return True if model_id appears to be a text/chat model rather than audio/image/embedding/moderation."""
    mid = str(model_id or "").strip()
    if not mid:
        return False
    return _NON_CHAT_MODEL_RE.search(mid) is None
