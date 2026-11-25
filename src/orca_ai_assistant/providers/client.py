from __future__ import annotations

import json
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from ..core.constants import PLUGIN_VERSION, norm_lang, tr
from .registry import PROVIDER_PRESETS, is_chat_model

# Hosts permitted by the plugin's default OrcaSlicer network_http manifest
_KNOWN_ALLOWED_HOSTS: frozenset[str] = frozenset({
    "openrouter.ai",
    "generativelanguage.googleapis.com",
    "api.openai.com",
    "api.anthropic.com",
    "api.deepseek.com",
    "open.bigmodel.cn",
    "api.groq.com",
    "api.cerebras.ai",
    "api.mistral.ai",
    "api.x.ai",
    "localhost",
    "127.0.0.1",
})

_STREAM_THROTTLE_SEC = 0.12
_MAX_HTTP400_RETRIES = 4
_TRANSIENT_BACKOFF_SEC = 1.5


def _close_response_immediately(resp: Any) -> None:
    """Force-close underlying socket and HTTPResponse so blocked reads abort immediately."""
    if resp is None:
        return
    # Attempt to locate and shutdown the raw socket to unblock readline()/read() across threads
    sock_candidates: list[Any] = []
    try:
        fp = getattr(resp, "fp", None)
        raw = getattr(fp, "raw", None) if fp is not None else None
        raw_sock = getattr(raw, "_sock", None) if raw is not None else None
        if raw_sock is not None:
            sock_candidates.append(raw_sock)
        if raw is not None and hasattr(raw, "close"):
            sock_candidates.append(raw)
    except Exception:
        pass
    try:
        direct_sock = getattr(resp, "sock", None)
        if direct_sock is not None:
            sock_candidates.append(direct_sock)
    except Exception:
        pass

    for sock in sock_candidates:
        try:
            if hasattr(sock, "shutdown"):
                sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        try:
            if hasattr(sock, "close"):
                sock.close()
        except Exception:
            pass

    try:
        resp.close()
    except Exception:
        pass


class CancelToken:
    """Thread-safe cancellation token that aborts active blocking HTTP reads on cancel()."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = threading.Event()
        self._response: Any = None

    def cancel(self) -> None:
        with self._lock:
            self._cancelled.set()
            resp = self._response
            self._response = None
        if resp is not None:
            _close_response_immediately(resp)

    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def wait(self, timeout: float) -> bool:
        """Sleep up to `timeout` seconds; returns True immediately if cancelled."""
        return self._cancelled.wait(max(0.0, float(timeout)))

    def set_response(self, resp: Any) -> None:
        close_now = False
        with self._lock:
            if self._cancelled.is_set():
                self._response = None
                close_now = resp is not None
            else:
                self._response = resp
        if close_now:
            _close_response_immediately(resp)


def _create_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs()
    except Exception:
        pass
    return ctx


def _extract_http_error_text(http_err: urllib.error.HTTPError) -> str:
    raw = ""
    try:
        raw = http_err.read().decode("utf-8", errors="replace")
        err_json = json.loads(raw)
        if isinstance(err_json, dict):
            err_field = err_json.get("error")
            if isinstance(err_field, dict):
                msg = err_field.get("message") or err_field.get("type") or raw
            elif err_field:
                msg = err_field
            else:
                msg = err_json.get("message") or err_json.get("detail") or raw
            return str(msg)
    except Exception:
        pass
    return (raw[:400] if raw else str(http_err))


def _format_http_error(
    code: int,
    err_text: str,
    provider: str,
    model_id: str,
    url: str,
    lang: str,
) -> str:
    l = norm_lang(lang)
    prefix = tr(l, "Ошибка API", "Помилка API", "API Error")
    base_msg = f"{prefix} (HTTP {code}): {err_text}"
    hint = ""

    if code == 401:
        hint = tr(
            l,
            "Подсказка: проверьте корректность API-ключа (возможно, ключ неверный, отозван или не скопирован полностью).",
            "Підказка: перевірте коректність API-ключа (можливо, ключ невірний, відкликаний або скопійований не повністю).",
            "Hint: Check your API key (it may be invalid, expired, or copied incompletely).",
        )
    elif code == 403:
        hint = tr(
            l,
            f"Подсказка: доступ к {provider} запрещён — проверьте права ключа, баланс/тариф или региональные ограничения.",
            f"Підказка: доступ до {provider} заборонено — перевірте права ключа, баланс/тариф або регіональні обмеження.",
            f"Hint: Access to {provider} was denied — check key permissions, billing/tier, or regional restrictions.",
        )
    elif code == 404:
        hint = tr(
            l,
            f"Подсказка: модель «{model_id}» или адрес {url} не найдены. Нажмите «Загрузить по API», чтобы выбрать актуальный ID модели, или проверьте Base URL.",
            f"Підказка: модель «{model_id}» або адреса {url} не знайдені. Натисніть «Завантажити по API», щоб обрати актуальний ID моделі, або перевірте Base URL.",
            f"Hint: Model \"{model_id}\" or endpoint {url} was not found. Click \"Fetch via API\" to select a valid model ID, or verify Base URL.",
        )
    elif code == 429:
        hint = tr(
            l,
            "Подсказка: превышен лимит запросов или квота. Подождите немного или переключитесь на другую модель/провайдера.",
            "Підказка: перевищено ліміт запитів або квоту. Зачекайте трохи або перемкніться на іншу модель/провайдера.",
            "Hint: Rate limit or quota exceeded. Wait a moment or switch to another model/provider.",
        )
    elif code in (503, 529):
        hint = tr(
            l,
            f"Подсказка: сервер {provider} временно перегружен. Повторите запрос через несколько секунд.",
            f"Підказка: сервер {provider} тимчасово перевантажений. Повторіть запит через кілька секунд.",
            f"Hint: {provider} is temporarily overloaded. Please retry in a few seconds.",
        )

    return f"{base_msg}\n\n{hint}" if hint else base_msg


def _format_connection_error(exc: Exception, provider: str, url: str, lang: str) -> str:
    l = norm_lang(lang)
    conn_prefix = tr(l, "Ошибка соединения с", "Помилка з'єднання з", "Connection error to")
    base_msg = f"{conn_prefix} {url}: {exc}"

    host = ""
    try:
        host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        pass

    exc_lower = str(exc).lower()
    is_sandbox_err = (
        isinstance(exc, PermissionError)
        or any(tok in exc_lower for tok in ("sandbox", "not allowed", "permission", "network_http", "blocked", "denied"))
    )
    is_unlisted_custom = bool(host) and host not in _KNOWN_ALLOWED_HOSTS and (provider == "custom" or is_sandbox_err)

    hint = ""
    if is_sandbox_err or is_unlisted_custom:
        hint = tr(
            l,
            f"Подсказка: песочница плагинов OrcaSlicer разрешает сеть только для встроенных провайдеров и localhost/127.0.0.1. Домен «{host}» может быть заблокирован — используйте локальный прокси (http://127.0.0.1:...) или встроенного провайдера.",
            f"Підказка: пісочниця плагінів OrcaSlicer дозволяє мережу лише для вбудованих провайдерів і localhost/127.0.0.1. Домен «{host}» може бути заблокований — використайте локальний проксі (http://127.0.0.1:...) або вбудованого провайдера.",
            f"Hint: OrcaSlicer's plugin sandbox only allows outbound HTTP to built-in provider domains and localhost/127.0.0.1. Domain \"{host}\" may be blocked — route through a local proxy (http://127.0.0.1:...) or choose a built-in provider.",
        )
    elif host in ("127.0.0.1", "localhost") or provider in ("ollama", "lmstudio"):
        hint = tr(
            l,
            "Подсказка: убедитесь, что локальный сервер (Ollama / LM Studio) запущен и слушает указанный порт.",
            "Підказка: переконайтеся, що локальний сервер (Ollama / LM Studio) запущено і він слухає вказаний порт.",
            "Hint: Make sure your local server (Ollama / LM Studio) is running and listening on the configured port.",
        )

    return f"{base_msg}\n\n{hint}" if hint else base_msg


def _sleep_cancellable(seconds: float, cancel_token: CancelToken | None) -> bool:
    """Sleep `seconds`. Returns True if cancelled during sleep."""
    if cancel_token is not None:
        return cancel_token.wait(seconds)
    time.sleep(seconds)
    return False


def _sanitize_anthropic_messages(
    messages: list[dict[str, Any]],
    image_attachment: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build valid Anthropic messages: starts with 'user' and merges consecutive same-role messages."""
    # Find index of last user message so image attaches to it
    last_user_idx = -1
    for idx, m in enumerate(messages):
        if m.get("role") != "assistant":
            last_user_idx = idx

    raw_items: list[dict[str, Any]] = []
    for idx, m in enumerate(messages):
        role = "assistant" if m.get("role") == "assistant" else "user"
        text_content = str(m.get("content") or "")
        attach_img = (
            idx == last_user_idx
            and role == "user"
            and isinstance(image_attachment, dict)
            and bool(image_attachment.get("base64"))
        )
        if attach_img and image_attachment is not None:
            blocks: list[dict[str, Any]] = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": str(image_attachment.get("mime") or "image/jpeg"),
                        "data": str(image_attachment["base64"]),
                    },
                }
            ]
            if text_content:
                blocks.append({"type": "text", "text": text_content})
            raw_items.append({"role": "user", "content": blocks})
        elif text_content.strip():
            raw_items.append({"role": role, "content": text_content})

    # Anthropic requires the first message to be from "user"
    while raw_items and raw_items[0]["role"] != "user":
        raw_items.pop(0)

    if not raw_items:
        return [{"role": "user", "content": "Hello"}]

    # Merge consecutive same-role messages
    merged: list[dict[str, Any]] = []
    for item in raw_items:
        if not merged or merged[-1]["role"] != item["role"]:
            merged.append(item)
            continue
        prev = merged[-1]
        prev_c = prev["content"]
        curr_c = item["content"]
        if isinstance(prev_c, str) and isinstance(curr_c, str):
            prev["content"] = f"{prev_c}\n\n{curr_c}"
        else:
            prev_blocks = prev_c if isinstance(prev_c, list) else [{"type": "text", "text": prev_c}]
            curr_blocks = curr_c if isinstance(curr_c, list) else [{"type": "text", "text": curr_c}]
            prev["content"] = [*prev_blocks, *curr_blocks]

    return merged


def _build_openai_messages(
    messages: list[dict[str, Any]],
    system_prompt: str,
    image_attachment: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    oai_messages: list[dict[str, Any]] = []
    if system_prompt:
        oai_messages.append({"role": "system", "content": system_prompt})

    last_user_idx = -1
    for idx, m in enumerate(messages):
        if m.get("role") not in ("assistant", "system"):
            last_user_idx = idx

    for idx, m in enumerate(messages):
        role = m.get("role") if m.get("role") in ("user", "assistant", "system") else "user"
        text_content = str(m.get("content") or "")
        attach_img = (
            idx == last_user_idx
            and role == "user"
            and isinstance(image_attachment, dict)
            and bool(image_attachment.get("base64"))
        )
        if attach_img and image_attachment is not None:
            mime = str(image_attachment.get("mime") or "image/jpeg")
            b64 = str(image_attachment["base64"])
            oai_messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": text_content},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            })
        else:
            oai_messages.append({"role": role, "content": text_content})
    return oai_messages


def _extract_usage(usage_obj: Any, current_in: int = 0, current_out: int = 0) -> tuple[int, int]:
    if not isinstance(usage_obj, dict):
        return current_in, current_out
    in_val = usage_obj.get("input_tokens")
    if in_val is None:
        in_val = usage_obj.get("prompt_tokens")
    out_val = usage_obj.get("output_tokens")
    if out_val is None:
        out_val = usage_obj.get("completion_tokens")

    try:
        if in_val is not None:
            current_in = max(current_in, int(in_val))
    except (TypeError, ValueError):
        pass
    try:
        if out_val is not None:
            current_out = max(current_out, int(out_val))
    except (TypeError, ValueError):
        pass
    return current_in, current_out


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
            items = (
                payload.get("data")
                or payload.get("models")
                or (payload if isinstance(payload, list) else [])
                if isinstance(payload, dict)
                else (payload if isinstance(payload, list) else [])
            )
            for item in items:
                if isinstance(item, str):
                    mid = item.strip()
                    if mid:
                        models.append({"id": mid, "name": mid})
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
                tags_url = f"{root_url}/api/tags"
                tags_ctx = _create_ssl_context() if tags_url.startswith("https://") else None
                tags_req = urllib.request.Request(tags_url, headers=headers, method="GET")
                with urllib.request.urlopen(tags_req, timeout=timeout, context=tags_ctx) as resp2:
                    raw2 = resp2.read().decode("utf-8", errors="replace")
                    payload2 = json.loads(raw2)
                    for item in payload2.get("models", []):
                        mid = str(item.get("name") or item.get("model") or "").strip()
                        if mid:
                            models.append({"id": mid, "name": mid})
            except Exception:
                return {
                    "ok": False,
                    "error": _format_connection_error(first_exc, provider, models_url, l),
                    "models": [],
                }
        else:
            if isinstance(first_exc, urllib.error.HTTPError):
                err_detail = _extract_http_error_text(first_exc)
                return {
                    "ok": False,
                    "needs_key": first_exc.code == 401,
                    "error": _format_http_error(first_exc.code, err_detail, provider, "", models_url, l),
                    "models": [],
                }
            return {
                "ok": False,
                "error": _format_connection_error(first_exc, provider, models_url, l),
                "models": [],
            }

    seen: set[str] = set()
    unique_models: list[dict[str, str]] = []
    for m in models:
        if m["id"] not in seen:
            seen.add(m["id"])
            unique_models.append(m)

    chat_models = [m for m in unique_models if is_chat_model(m["id"])]
    final_models = chat_models if chat_models else unique_models
    final_models.sort(key=lambda x: x["id"].lower())

    return {"ok": True, "models": final_models, "count": len(final_models)}


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
    on_thinking: Any = None,
    cancel_token: CancelToken | None = None,
    timeout: float = 120.0,
) -> dict[str, Any]:
    l = norm_lang(lang)
    if cancel_token is not None and cancel_token.is_cancelled():
        return {"ok": False, "cancelled": True, "partial_reply": ""}

    preset = PROVIDER_PRESETS.get(provider, PROVIDER_PRESETS["custom"])
    protocol = custom_protocol if provider == "custom" else preset["protocol"]
    clean_base = (base_url or preset["base_url"]).strip().rstrip("/")
    clean_key = (api_key or "").strip()
    clean_model = (model_id or preset["default_model"]).strip()
    clean_effort = str(reasoning_effort or "").strip().lower()
    use_stream = callable(on_chunk) or callable(on_thinking)

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
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream, application/json" if use_stream else "application/json",
            "x-api-key": clean_key,
            "anthropic-version": "2023-06-01",
            "User-Agent": f"OrcaAIAssistant/{PLUGIN_VERSION}",
        }
        anth_messages = _sanitize_anthropic_messages(messages, image_attachment=image_attachment)
        model_lower = clean_model.lower()
        is_claude3 = model_lower.startswith("claude-3")
        req_max_tokens = int(max_tokens or 4096)
        body: dict[str, Any] = {
            "model": clean_model,
            "max_tokens": req_max_tokens,
            "messages": anth_messages,
        }
        if system_prompt:
            body["system"] = system_prompt
        if use_stream:
            body["stream"] = True
        if is_claude3:
            # Claude 3.x accepts temperature; newer Claude 4.7+/5.x/Fable may reject it (also guarded by 400 retry)
            body["temperature"] = float(temperature)
        else:
            # Modern Claude adaptive thinking shares max_tokens with output text and can consume all 4096 tokens
            if clean_effort == "none":
                body["thinking"] = {"type": "disabled"}
            else:
                if clean_effort in ("low", "medium", "high"):
                    body["output_config"] = {"effort": clean_effort}
                if clean_effort == "low":
                    req_max_tokens = max(req_max_tokens, 8192)
                else:
                    req_max_tokens = max(req_max_tokens, 16384)
            body["max_tokens"] = req_max_tokens
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

        oai_messages = _build_openai_messages(messages, system_prompt, image_attachment=image_attachment)
        body = {
            "model": clean_model,
            "messages": oai_messages,
            "max_tokens": int(max_tokens or 4096),
        }
        if use_stream:
            body["stream"] = True
            body["stream_options"] = {"include_usage": True}

        model_lower = clean_model.lower()
        no_temp_prefixes = ("o1", "o3", "o4", "gpt-5", "claude-", "deepseek-reasoner", "qwq")
        is_no_temp = (
            model_lower.startswith(no_temp_prefixes)
            or "/claude-" in model_lower
            or "/gpt-5" in model_lower
            or "/o1" in model_lower
            or "/o3" in model_lower
            or "/o4" in model_lower
        )
        if not is_no_temp:
            body["temperature"] = float(temperature)

        # Reasoning effort: avoid sending "none"/"minimal" to OpenAI o-series models that reject it
        is_gemini = provider == "gemini" or "gemini" in model_lower
        is_gpt5 = model_lower.startswith("gpt-5") or "/gpt-5" in model_lower
        is_oseries = (
            model_lower.startswith(("o1", "o3", "o4"))
            or "/o1" in model_lower
            or "/o3" in model_lower
            or "/o4" in model_lower
        )
        if (is_gemini or is_gpt5) and clean_effort in ("none", "minimal", "low", "medium", "high"):
            body["reasoning_effort"] = clean_effort
        elif is_oseries and clean_effort in ("low", "medium", "high"):
            body["reasoning_effort"] = clean_effort

    def _do_post(payload_dict: dict[str, Any]) -> dict[str, Any]:
        if cancel_token is not None and cancel_token.is_cancelled():
            return {"_cancelled": True, "_reply": "", "_reasoning": ""}

        data_bytes = json.dumps(payload_dict, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")

        acc_text: list[str] = []
        acc_reason: list[str] = []
        usage_in = 0
        usage_out = 0

        resp = urllib.request.urlopen(req, timeout=timeout, context=ctx)
        if cancel_token is not None:
            cancel_token.set_response(resp)

        try:
            ctype = str(resp.headers.get("Content-Type") or "").lower()
            is_sse = bool(payload_dict.get("stream")) and ("text/event-stream" in ctype or "event-stream" in ctype)
            if not payload_dict.get("stream") and not is_sse:
                raw_resp = resp.read().decode("utf-8", errors="replace")
                if cancel_token is not None and cancel_token.is_cancelled():
                    return {"_cancelled": True, "_reply": "", "_reasoning": ""}
                return json.loads(raw_resp)

            raw_non_sse: list[str] = []
            sse_error = ""
            stop_reason = ""
            saw_thinking_block = False
            last_chunk_emit = 0.0
            last_think_emit = 0.0
            emitted_text_len = 0
            emitted_think_len = 0
            saw_sse = is_sse

            while True:
                if cancel_token is not None and cancel_token.is_cancelled():
                    return {
                        "_cancelled": True,
                        "_reply": "".join(acc_text),
                        "_reasoning": "".join(acc_reason),
                    }
                try:
                    raw_line = resp.readline()
                except Exception:
                    if cancel_token is not None and cancel_token.is_cancelled():
                        return {
                            "_cancelled": True,
                            "_reply": "".join(acc_text),
                            "_reasoning": "".join(acc_reason),
                        }
                    raise

                if not raw_line:
                    break
                if cancel_token is not None and cancel_token.is_cancelled():
                    return {
                        "_cancelled": True,
                        "_reply": "".join(acc_text),
                        "_reasoning": "".join(acc_reason),
                    }

                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if not saw_sse and not line.startswith("data:") and not line.startswith("event:"):
                    raw_non_sse.append(line)
                    continue
                if line.startswith("event:") or line.startswith(":"):
                    saw_sse = True
                    continue
                if not line.startswith("data:"):
                    continue

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
                    sse_error = str(
                        err_obj.get("message") if isinstance(err_obj, dict) else (err_obj or ev)
                    )
                    continue

                text_added = False
                think_added = False

                if protocol == "anthropic":
                    ev_type = ev.get("type")
                    if ev_type == "message_start":
                        msg_obj = ev.get("message") or {}
                        usage_in, usage_out = _extract_usage(msg_obj.get("usage"), usage_in, usage_out)
                    elif ev_type == "message_delta":
                        usage_in, usage_out = _extract_usage(ev.get("usage"), usage_in, usage_out)
                        delta_sr = (ev.get("delta") or {}).get("stop_reason")
                        if delta_sr:
                            stop_reason = str(delta_sr)
                    elif ev_type == "content_block_start":
                        cb = ev.get("content_block") or {}
                        if cb.get("type") == "text" and cb.get("text"):
                            acc_text.append(str(cb.get("text") or ""))
                            text_added = True
                        elif cb.get("type") == "thinking":
                            saw_thinking_block = True
                            if cb.get("thinking"):
                                acc_reason.append(str(cb.get("thinking") or ""))
                                think_added = True
                    elif ev_type == "content_block_delta":
                        delta = ev.get("delta") or {}
                        dtype = delta.get("type")
                        if dtype == "text_delta" or (not dtype and "text" in delta):
                            piece = str(delta.get("text") or "")
                            if piece:
                                acc_text.append(piece)
                                text_added = True
                        elif dtype in ("thinking_delta", "signature_delta"):
                            saw_thinking_block = True
                            if dtype == "thinking_delta":
                                piece = str(delta.get("thinking") or "")
                                if piece:
                                    acc_reason.append(piece)
                                    think_added = True
                else:
                    if ev.get("usage"):
                        usage_in, usage_out = _extract_usage(ev.get("usage"), usage_in, usage_out)
                    choices = ev.get("choices") or []
                    if choices and isinstance(choices[0], dict):
                        delta = choices[0].get("delta") or {}
                        c_piece = delta.get("content")
                        if isinstance(c_piece, str) and c_piece:
                            acc_text.append(c_piece)
                            text_added = True
                        elif isinstance(c_piece, list):
                            for part in c_piece:
                                if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                                    acc_text.append(str(part["text"]))
                                    text_added = True
                        r_piece = delta.get("reasoning_content") or delta.get("reasoning")
                        if isinstance(r_piece, str) and r_piece:
                            acc_reason.append(r_piece)
                            think_added = True

                now = time.monotonic()
                if think_added and callable(on_thinking) and (now - last_think_emit >= _STREAM_THROTTLE_SEC):
                    last_think_emit = now
                    joined_t = "".join(acc_reason)
                    emitted_think_len = len(joined_t)
                    try:
                        on_thinking(joined_t)
                    except Exception:
                        pass
                if text_added and callable(on_chunk) and (now - last_chunk_emit >= _STREAM_THROTTLE_SEC):
                    last_chunk_emit = now
                    joined_c = "".join(acc_text)
                    emitted_text_len = len(joined_c)
                    try:
                        on_chunk(joined_c)
                    except Exception:
                        pass

            if cancel_token is not None and cancel_token.is_cancelled():
                return {
                    "_cancelled": True,
                    "_reply": "".join(acc_text),
                    "_reasoning": "".join(acc_reason),
                }

            if not saw_sse and raw_non_sse:
                return json.loads("\n".join(raw_non_sse))

            joined_text = "".join(acc_text)
            joined_reason = "".join(acc_reason)

            if callable(on_thinking) and joined_reason and len(joined_reason) > emitted_think_len:
                try:
                    on_thinking(joined_reason)
                except Exception:
                    pass
            if callable(on_chunk) and joined_text and len(joined_text) > emitted_text_len:
                try:
                    on_chunk(joined_text)
                except Exception:
                    pass

            return {
                "_streamed": True,
                "_reply": joined_text,
                "_reasoning": joined_reason,
                "_error": sse_error,
                "_stop_reason": stop_reason,
                "_saw_thinking": saw_thinking_block,
                "_usage": {"input_tokens": usage_in, "output_tokens": usage_out},
            }
        finally:
            if cancel_token is not None:
                cancel_token.set_response(None)
            try:
                resp.close()
            except Exception:
                pass

    api_err_prefix = tr(l, "Ошибка API", "Помилка API", "API Error")

    http400_retries = 0
    transient_retries = 0
    parsed: dict[str, Any] = {}

    while True:
        if cancel_token is not None and cancel_token.is_cancelled():
            return {"ok": False, "cancelled": True, "partial_reply": ""}

        try:
            parsed = _do_post(body)
            break
        except urllib.error.HTTPError as http_err:
            if cancel_token is not None and cancel_token.is_cancelled():
                return {"ok": False, "cancelled": True, "partial_reply": ""}

            err_text = _extract_http_error_text(http_err)
            err_lower = err_text.lower()

            # Multi-pass HTTP 400 compatibility retry (up to 4 passes)
            if http_err.code == 400 and http400_retries < _MAX_HTTP400_RETRIES:
                changed = False
                if "stream_options" in body and (
                    "stream_options" in err_lower
                    or "include_usage" in err_lower
                    or ("extra" in err_lower and "stream" in err_lower)
                    or "additional properties" in err_lower
                    or "unrecognized request argument" in err_lower
                ):
                    body.pop("stream_options", None)
                    changed = True
                if "temperature" in body and "temperature" in err_lower:
                    body.pop("temperature", None)
                    changed = True
                if "output_config" in body and (
                    "output_config" in err_lower
                    or "effort" in err_lower
                    or "unknown" in err_lower
                    or "unsupported" in err_lower
                    or "unrecognized" in err_lower
                    or "extra" in err_lower
                ):
                    body.pop("output_config", None)
                    changed = True
                if "thinking" in body and (
                    "thinking" in err_lower
                    or "unknown" in err_lower
                    or "unsupported" in err_lower
                    or "unrecognized" in err_lower
                    or "extra" in err_lower
                ):
                    body.pop("thinking", None)
                    changed = True
                if "reasoning_effort" in body and (
                    "reasoning" in err_lower
                    or "unknown" in err_lower
                    or "unsupported" in err_lower
                    or "invalid" in err_lower
                    or "unrecognized" in err_lower
                ):
                    body.pop("reasoning_effort", None)
                    changed = True
                if "max_tokens" in body and "max_completion_tokens" in err_lower:
                    body["max_completion_tokens"] = body.pop("max_tokens")
                    changed = True
                if "stream" in body and "stream" in err_lower and "stream_options" not in err_lower:
                    body.pop("stream", None)
                    body.pop("stream_options", None)
                    headers["Accept"] = "application/json"
                    changed = True

                # Progressive fallback if server gave a generic 400 message while optional fields exist
                if not changed:
                    if "stream_options" in body:
                        body.pop("stream_options", None)
                        changed = True
                    elif "output_config" in body:
                        body.pop("output_config", None)
                        changed = True
                    elif "thinking" in body:
                        body.pop("thinking", None)
                        changed = True
                    elif "reasoning_effort" in body:
                        body.pop("reasoning_effort", None)
                        changed = True

                if changed:
                    http400_retries += 1
                    continue

            # Backoff retry (1x after 1.5s, cancellable) on HTTP 429 / 503 / 529
            if http_err.code in (429, 503, 529) and transient_retries < 1:
                transient_retries += 1
                if _sleep_cancellable(_TRANSIENT_BACKOFF_SEC, cancel_token):
                    return {"ok": False, "cancelled": True, "partial_reply": ""}
                continue

            return {
                "ok": False,
                "needs_key": http_err.code == 401,
                "status_code": http_err.code,
                "error": _format_http_error(http_err.code, err_text, provider, clean_model, url, l),
            }
        except Exception as exc:
            if cancel_token is not None and cancel_token.is_cancelled():
                return {"ok": False, "cancelled": True, "partial_reply": ""}
            return {
                "ok": False,
                "error": _format_connection_error(exc, provider, url, l),
            }

    if parsed.get("_cancelled") or (cancel_token is not None and cancel_token.is_cancelled()):
        return {
            "ok": False,
            "cancelled": True,
            "partial_reply": str(parsed.get("_reply") or "").strip(),
        }

    # Surface mid-stream SSE errors even if partial text was streamed
    if parsed.get("_streamed") and parsed.get("_error"):
        partial = str(parsed.get("_reply") or "").strip()
        return {
            "ok": False,
            "error": f"{api_err_prefix}: {parsed['_error']}",
            "partial_reply": partial,
        }

    def _is_anthropic_thinking_exhausted(res: dict[str, Any]) -> bool:
        if protocol != "anthropic" or not isinstance(res, dict):
            return False
        if res.get("_streamed"):
            if str(res.get("_reply") or "").strip():
                return False
            return res.get("_stop_reason") == "max_tokens" or bool(res.get("_saw_thinking"))
        has_text = any(
            isinstance(b, dict) and b.get("type") == "text" and str(b.get("text") or "").strip()
            for b in (res.get("content") or [])
        )
        if has_text:
            return False
        has_thinking_block = any(
            isinstance(b, dict) and b.get("type") == "thinking"
            for b in (res.get("content") or [])
        )
        return res.get("stop_reason") == "max_tokens" or has_thinking_block

    if _is_anthropic_thinking_exhausted(parsed):
        body.pop("stream", None)
        body.pop("output_config", None)
        headers["Accept"] = "application/json"
        body["max_tokens"] = max(int(body.get("max_tokens") or 4096) * 2, 16384)
        body["thinking"] = {"type": "disabled"}
        try:
            rec_parsed = _do_post(body)
            if rec_parsed.get("_cancelled"):
                return {"ok": False, "cancelled": True, "partial_reply": ""}
            parsed = rec_parsed
        except urllib.error.HTTPError as rec_err:
            rec_err_text = _extract_http_error_text(rec_err).lower()
            if rec_err.code == 400 and ("thinking" in rec_err_text or "disabled" in rec_err_text or "unsupported" in rec_err_text or "unknown" in rec_err_text):
                body.pop("thinking", None)
                body["output_config"] = {"effort": "low"}
                try:
                    rec_parsed2 = _do_post(body)
                    if rec_parsed2.get("_cancelled"):
                        return {"ok": False, "cancelled": True, "partial_reply": ""}
                    parsed = rec_parsed2
                except Exception:
                    pass
        except Exception:
            pass

    # Automatic non-stream fallback if SSE returned empty text with no error
    if (
        parsed.get("_streamed")
        and not str(parsed.get("_reply") or "").strip()
        and not str(parsed.get("_reasoning") or "").strip()
    ):
        body.pop("stream", None)
        body.pop("stream_options", None)
        headers["Accept"] = "application/json"
        try:
            fallback_parsed = _do_post(body)
            if fallback_parsed.get("_cancelled"):
                return {"ok": False, "cancelled": True, "partial_reply": ""}
            parsed = fallback_parsed
        except Exception:
            pass

    reply_text = ""
    reasoning_text = ""
    usage_in = 0
    usage_out = 0

    if parsed.get("_streamed"):
        reply_text = str(parsed.get("_reply") or "")
        reasoning_text = str(parsed.get("_reasoning") or "")
        usage_in, usage_out = _extract_usage(parsed.get("_usage"), usage_in, usage_out)
    elif protocol == "anthropic":
        usage_in, usage_out = _extract_usage(parsed.get("usage"), usage_in, usage_out)
        for block in parsed.get("content", []):
            if isinstance(block, dict):
                if block.get("type") == "text":
                    reply_text += str(block.get("text") or "")
                elif block.get("type") == "thinking":
                    reasoning_text += str(block.get("thinking") or "")
    else:
        usage_in, usage_out = _extract_usage(parsed.get("usage"), usage_in, usage_out)
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
        "usage": {
            "input_tokens": max(0, int(usage_in)),
            "output_tokens": max(0, int(usage_out)),
        },
    }
