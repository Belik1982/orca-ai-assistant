from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import os
import re
import secrets
import shutil
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .constants import (
    MCP_DEFAULT_PORT,
    PLUGIN_ID,
    RETIRED_MODEL_MIGRATIONS,
    default_favorites,
    default_settings,
    norm_lang,
    tr,
)

logger = logging.getLogger("orca_ai_assistant.storage")

MAX_SNAPSHOTS = 30
MAX_APPLY_HISTORY = 20


def _get_orca_user_config_dir() -> Path:
    """Return cross-platform OrcaSlicer user data directory."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        return base / "OrcaSlicer"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OrcaSlicer"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else (Path.home() / ".config")
    return base / "OrcaSlicer"


def _get_orca_app_info_safe() -> dict[str, Any] | None:
    try:
        import orca.host  # type: ignore

        info = orca.host.app_info()
        if isinstance(info, dict):
            return info
    except Exception:
        pass
    return None


def get_plugin_storage_dir() -> Path:
    """Resolve persistent storage dir while preserving 100% v2.x compatibility.

    Priority:
      1. Ancestor `orca_plugins/plugin_data/orca-ai-assistant` (exact v2.x & wheel-extracted layout).
      2. Existing legacy `<orca_user_dir>/orca_plugins/plugin_data/orca-ai-assistant` if already populated.
      3. `orca.host.plugin.storage()` when provided by OrcaSlicer host.
      4. Cross-platform `<orca_user_dir>/orca_plugins/plugin_data/orca-ai-assistant` (Win/macOS/Linux).
    """
    # 1. Check ancestor `orca_plugins` directory (works for both .py and __whl_extracted__)
    candidates: list[Path] = []
    try:
        candidates.append(Path(__file__).resolve().parent)
    except Exception:
        pass
    # Also inspect __main__ file path in case of virtualized single-file bundling
    main_mod = sys.modules.get("__main__")
    main_file = getattr(main_mod, "__file__", None)
    if main_file:
        try:
            candidates.append(Path(main_file).resolve().parent)
        except Exception:
            pass

    for start_dir in candidates:
        for parent in (start_dir, *start_dir.parents):
            if parent.name == "orca_plugins":
                target = parent / "plugin_data" / PLUGIN_ID
                try:
                    target.mkdir(parents=True, exist_ok=True)
                    return target
                except Exception as exc:
                    logger.warning("Could not create plugin storage dir %s: %s", target, exc)
                    break

    platform_target = _get_orca_user_config_dir() / "orca_plugins" / "plugin_data" / PLUGIN_ID

    # 2. If v2.x storage dir already exists on this machine, prefer it for seamless migration
    try:
        if (platform_target / "settings.json").is_file() or platform_target.is_dir():
            platform_target.mkdir(parents=True, exist_ok=True)
            return platform_target
    except Exception:
        pass

    # 3. Official OrcaSlicer 2.5+ plugin storage callback
    try:
        import orca.host  # type: ignore

        plugin_ns = getattr(orca.host, "plugin", None)
        storage_fn = getattr(plugin_ns, "storage", None) if plugin_ns is not None else None
        if callable(storage_fn):
            host_dir = storage_fn()
            if host_dir:
                target = Path(str(host_dir))
                target.mkdir(parents=True, exist_ok=True)
                return target
    except Exception:
        pass

    # 4. Cross-platform OrcaSlicer default directory
    try:
        platform_target.mkdir(parents=True, exist_ok=True)
        return platform_target
    except Exception as exc:
        logger.warning("Could not create platform storage dir %s: %s", platform_target, exc)
        return Path(__file__).resolve().parent


def _try_import_legacy_printpurr_keys() -> dict[str, Any]:
    imported: dict[str, Any] = {}
    try:
        legacy_path = _get_orca_user_config_dir() / ".print_purr" / "settings.json"
        if legacy_path.is_file():
            raw = json.loads(legacy_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                keys = raw.get("api_keys")
                if isinstance(keys, dict):
                    imported["api_keys"] = {str(k): str(v) for k, v in keys.items() if v}
                urls = raw.get("base_urls")
                if isinstance(urls, dict):
                    imported["base_urls"] = {str(k): str(v) for k, v in urls.items() if v}
    except Exception as exc:
        logger.debug("Legacy PrintPurr import skipped: %s", exc)
    return imported


def _current_month_key() -> str:
    return dt.datetime.now().strftime("%Y-%m")


def _default_usage() -> dict[str, Any]:
    return {
        "total": {"msgs": 0, "input_tokens": 0, "output_tokens": 0},
        "month_key": _current_month_key(),
        "month": {"msgs": 0, "input_tokens": 0, "output_tokens": 0},
        "by_provider": {},
        "by_model": {},
        "updated_at": "",
    }


def _new_chat_id() -> str:
    return f"chat_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def _default_chat_title(lang: str) -> str:
    return tr(lang, "Новый диалог", "Новий діалог", "New Chat")


class StorageManager:
    def __init__(self, storage_dir: Path | str | None = None) -> None:
        self._lock = threading.RLock()
        self._dir = Path(storage_dir) if storage_dir is not None else get_plugin_storage_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._settings_file = self._dir / "settings.json"
        self._chats_file = self._dir / "chats.json"
        self._usage_file = self._dir / "usage.json"
        self._snapshots_file = self._dir / "snapshots.json"
        self._apply_history_file = self._dir / "apply_history.json"

        self._settings = self._load_settings()
        self._chats = self._load_chats()
        self._usage = self._load_usage()
        self._snapshots = self._load_list_file(self._snapshots_file, MAX_SNAPSHOTS)
        self._apply_history = self._load_list_file(self._apply_history_file, MAX_APPLY_HISTORY)

    @property
    def storage_dir(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Atomic JSON persistence
    # ------------------------------------------------------------------
    def _save_json(self, path: Path, payload: Any) -> bool:
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(payload, ensure_ascii=False, indent=2)
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(serialized)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, path)
            return True
        except Exception as exc:
            logger.error("Failed atomic JSON write to %s: %s", path, exc, exc_info=True)
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass
            return False

    def _backup_settings_before_migration(self) -> None:
        bak_path = self._dir / "settings.json.bak"
        if bak_path.exists() or not self._settings_file.is_file():
            return
        try:
            shutil.copy2(self._settings_file, bak_path)
        except Exception as exc:
            logger.warning("Could not create settings.json.bak before migration: %s", exc)

    # ------------------------------------------------------------------
    # Settings load & schema v1/v2/v3 -> v4 migration
    # ------------------------------------------------------------------
    def _load_settings(self) -> dict[str, Any]:
        app_info = _get_orca_app_info_safe()
        defaults = default_settings(app_info)

        if not self._settings_file.is_file():
            from ..providers.registry import PROVIDER_PRESETS

            legacy = _try_import_legacy_printpurr_keys()
            if legacy.get("api_keys"):
                for k, v in legacy["api_keys"].items():
                    if v:
                        defaults["api_keys"][k] = v
                for prov in ("anthropic", "gemini", "openai", "openrouter", "groq", "glm", "mistral"):
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
        except Exception as exc:
            logger.error("Failed to read %s (%s); preserving corrupt copy and using defaults.", self._settings_file, exc)
            try:
                corrupt_bak = self._dir / f"settings.json.corrupt.{int(time.time())}.bak"
                shutil.copy2(self._settings_file, corrupt_bak)
            except Exception:
                pass
            return defaults

        if not isinstance(data, dict):
            logger.warning("settings.json root is not a JSON object; using defaults.")
            return defaults

        try:
            old_version = int(data.get("schema_version") or 1)
        except (TypeError, ValueError):
            old_version = 1

        needs_save = old_version < 4
        if old_version < 4:
            self._backup_settings_before_migration()

        merged: dict[str, Any] = copy.deepcopy(defaults)
        for k, v in data.items():
            if k == "base_urls" and isinstance(v, dict):
                merged_urls = dict(defaults.get("base_urls", {}))
                for pk, pv in v.items():
                    if pv:
                        merged_urls[str(pk)] = str(pv)
                merged[k] = merged_urls
            elif k in ("api_keys", "model_api_keys", "cached_models") and isinstance(v, dict):
                merged[k] = {**defaults.get(k, {}), **v}
            elif k == "temperature":
                # Explicitly preserve 0.0 (never coerce 0.0 -> 0.3)
                if v is not None:
                    try:
                        merged["temperature"] = float(v)
                    except (TypeError, ValueError):
                        pass
            elif k == "max_tokens":
                if v is not None:
                    try:
                        iv = int(v)
                        if iv > 0:
                            merged["max_tokens"] = iv
                    except (TypeError, ValueError):
                        pass
            elif k == "mcp_port":
                merged["mcp_port"] = self._sanitize_mcp_port(v)
            elif k in ("mcp_enabled", "mcp_require_auth", "mcp_allow_write", "mcp_allow_gcode_write"):
                merged[k] = bool(v)
            elif k == "mcp_token":
                merged["mcp_token"] = str(v or "").strip()
            else:
                merged[k] = v

        merged["language"] = norm_lang(merged.get("language", defaults["language"]))

        # Migrate retired active model ID
        cur_model = str(merged.get("model") or "")
        if cur_model in RETIRED_MODEL_MIGRATIONS:
            merged["model"] = RETIRED_MODEL_MIGRATIONS[cur_model]
            needs_save = True

        # Migrate retired models inside favorite_models without overwriting user favorites
        raw_favs = merged.get("favorite_models")
        if isinstance(raw_favs, list):
            migrated_favs: list[dict[str, str]] = []
            seen_pairs: set[tuple[str, str]] = set()
            for fav in raw_favs:
                if not isinstance(fav, dict):
                    continue
                fav_copy = dict(fav)
                f_prov = str(fav_copy.get("provider") or "").strip()
                f_model = str(fav_copy.get("model") or "").strip()
                if f_model in RETIRED_MODEL_MIGRATIONS:
                    new_m = RETIRED_MODEL_MIGRATIONS[f_model]
                    if str(fav_copy.get("label") or "").strip() == f_model:
                        fav_copy["label"] = new_m
                    fav_copy["model"] = new_m
                    f_model = new_m
                    needs_save = True
                pair = (f_prov, f_model)
                if f_model and pair not in seen_pairs:
                    seen_pairs.add(pair)
                    migrated_favs.append(fav_copy)
            merged["favorite_models"] = migrated_favs
        else:
            merged["favorite_models"] = default_favorites()
            needs_save = True

        merged["schema_version"] = 4

        if needs_save:
            self._save_json(self._settings_file, merged)

        return merged

    def _load_chats(self) -> dict[str, Any]:
        if self._chats_file.is_file():
            try:
                data = json.loads(self._chats_file.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("sessions"), list) and data["sessions"]:
                    return data
            except Exception as exc:
                logger.error("Failed to read %s: %s", self._chats_file, exc)
        first_id = _new_chat_id()
        lang = norm_lang(self._settings.get("language", "en"))
        initial = {
            "active_id": first_id,
            "sessions": [
                {
                    "id": first_id,
                    "title": _default_chat_title(lang),
                    "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                    "messages": [],
                }
            ],
        }
        self._save_json(self._chats_file, initial)
        return initial

    def _load_usage(self) -> dict[str, Any]:
        base = _default_usage()
        if self._usage_file.is_file():
            try:
                data = json.loads(self._usage_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    base.update(data)
            except Exception as exc:
                logger.error("Failed to read %s: %s", self._usage_file, exc)
        self._rollover_usage_month(base)
        return base

    def _rollover_usage_month(self, usage: dict[str, Any]) -> bool:
        cur_month = _current_month_key()
        if usage.get("month_key") != cur_month:
            usage["month_key"] = cur_month
            usage["month"] = {"msgs": 0, "input_tokens": 0, "output_tokens": 0}
            return True
        usage.setdefault("total", {"msgs": 0, "input_tokens": 0, "output_tokens": 0})
        usage.setdefault("month", {"msgs": 0, "input_tokens": 0, "output_tokens": 0})
        usage.setdefault("by_provider", {})
        usage.setdefault("by_model", {})
        return False

    def _load_list_file(self, path: Path, limit: int) -> list[dict[str, Any]]:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return [item for item in data if isinstance(item, dict)][:limit]
            except Exception as exc:
                logger.error("Failed to read %s: %s", path, exc)
        return []

    # ------------------------------------------------------------------
    # Settings API
    # ------------------------------------------------------------------
    def get_settings(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._settings)

    def get_lang(self) -> str:
        with self._lock:
            return norm_lang(self._settings.get("language", "ru"))

    def update_settings(self, patch: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            for k, v in patch.items():
                if k == "language":
                    self._settings["language"] = norm_lang(v)
                elif k == "temperature":
                    if v is not None:
                        try:
                            self._settings["temperature"] = float(v)
                        except (TypeError, ValueError):
                            pass
                elif k == "max_tokens":
                    if v is not None:
                        try:
                            iv = int(v)
                            if iv > 0:
                                self._settings["max_tokens"] = iv
                        except (TypeError, ValueError):
                            pass
                elif k == "mcp_port":
                    self._settings["mcp_port"] = self._sanitize_mcp_port(v)
                elif k in ("mcp_enabled", "mcp_require_auth", "mcp_allow_write", "mcp_allow_gcode_write"):
                    self._settings[k] = bool(v)
                elif k == "mcp_token":
                    self._settings["mcp_token"] = str(v or "").strip()
                elif k == "model_api_keys" and isinstance(v, dict):
                    mkeys = self._settings.setdefault("model_api_keys", {})
                    for mk, mv in v.items():
                        val = str(mv or "").strip()
                        if val:
                            mkeys[str(mk)] = val
                        else:
                            mkeys.pop(str(mk), None)
                elif k in ("api_keys", "base_urls", "cached_models") and isinstance(v, dict):
                    self._settings.setdefault(k, {}).update(v)
                else:
                    self._settings[k] = copy.deepcopy(v)
            self._save_json(self._settings_file, self._settings)
            return copy.deepcopy(self._settings)

    @staticmethod
    def _sanitize_mcp_port(value: Any) -> int:
        try:
            port = int(value)
            if 1024 <= port <= 65535:
                return port
        except (TypeError, ValueError):
            pass
        return MCP_DEFAULT_PORT

    def ensure_mcp_token(self, force_new: bool = False) -> str:
        """Return the configured MCP bearer token, generating and persisting one if missing/rotated."""
        with self._lock:
            existing = str(self._settings.get("mcp_token") or "").strip()
            if existing and not force_new:
                return existing
            token = f"orca_mcp_{secrets.token_hex(16)}"
            self._settings["mcp_token"] = token
            self._save_json(self._settings_file, self._settings)
            return token

    def resolve_effective_api_key(self, provider: str, model_id: str) -> str:
        with self._lock:
            m_keys = self._settings.get("model_api_keys") or {}
            specific = str(m_keys.get(f"{provider}::{model_id}") or m_keys.get(model_id) or "").strip()
            if specific:
                return specific
            p_keys = self._settings.get("api_keys") or {}
            return str(p_keys.get(provider) or "").strip()

    def has_model_specific_api_key(self, provider: str, model_id: str) -> bool:
        with self._lock:
            m_keys = self._settings.get("model_api_keys") or {}
            return bool(str(m_keys.get(f"{provider}::{model_id}") or m_keys.get(model_id) or "").strip())

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
            return count, copy.deepcopy(self._settings)

    # ------------------------------------------------------------------
    # Chats API (chat_id-addressed to prevent cross-chat race corruption)
    # ------------------------------------------------------------------
    def get_chats(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._chats)

    def save_chats(self, chats_data: dict[str, Any]) -> None:
        with self._lock:
            self._chats = copy.deepcopy(chats_data)
            self._save_json(self._chats_file, self._chats)

    def create_chat(self, title: str = "") -> tuple[str, dict[str, Any]]:
        with self._lock:
            lang = norm_lang(self._settings.get("language", "ru"))
            chat_id = _new_chat_id()
            clean_title = str(title or "").strip() or _default_chat_title(lang)
            session = {
                "id": chat_id,
                "title": clean_title,
                "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                "messages": [],
            }
            self._chats.setdefault("sessions", []).insert(0, session)
            self._chats["active_id"] = chat_id
            self._save_json(self._chats_file, self._chats)
            return chat_id, copy.deepcopy(self._chats)

    def rename_chat(self, chat_id: str, title: str) -> dict[str, Any]:
        with self._lock:
            clean_title = re.sub(r"\s+", " ", str(title or "")).strip()[:80]
            if clean_title:
                for s in self._chats.get("sessions", []):
                    if s.get("id") == chat_id:
                        s["title"] = clean_title
                        self._save_json(self._chats_file, self._chats)
                        break
            return copy.deepcopy(self._chats)

    def append_message(
        self,
        chat_id: str,
        role: str,
        content: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append a message strictly to `chat_id` even if `active_id` changed mid-stream."""
        with self._lock:
            sessions = self._chats.setdefault("sessions", [])
            target: dict[str, Any] | None = None

            if chat_id:
                target = next((s for s in sessions if s.get("id") == chat_id), None)
                if target is None:
                    if not sessions:
                        lang = norm_lang(self._settings.get("language", "ru"))
                        target = {
                            "id": chat_id,
                            "title": _default_chat_title(lang),
                            "created_at": dt.datetime.now().strftime("%d.%m %H:%M"),
                            "messages": [],
                        }
                        sessions.insert(0, target)
                        self._chats["active_id"] = chat_id
                    else:
                        logger.warning("append_message: target chat_id=%s no longer exists; skipping write.", chat_id)
                        return copy.deepcopy(self._chats)
            else:
                active_id = self._chats.get("active_id")
                target = next((s for s in sessions if s.get("id") == active_id), None)
                if target is None:
                    lang = norm_lang(self._settings.get("language", "ru"))
                    first_id = _new_chat_id()
                    target = {
                        "id": first_id,
                        "title": _default_chat_title(lang),
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
                msg.update(copy.deepcopy(extra))
            target.setdefault("messages", []).append(msg)

            if role == "user" and target.get("title") in ("Новый диалог", "Новий діалог", "New Chat", "", None):
                clean_title = re.sub(r"\s+", " ", content).strip()[:42]
                if clean_title:
                    target["title"] = clean_title

            self._save_json(self._chats_file, self._chats)
            return copy.deepcopy(self._chats)

    def append_message_to_active(
        self,
        role: str,
        content: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            active_id = str(self._chats.get("active_id") or "")
            return self.append_message(active_id, role, content, extra=extra)

    # ------------------------------------------------------------------
    # Token / Message Usage API (`usage.json`)
    # ------------------------------------------------------------------
    def record_usage(
        self,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any]:
        in_tok = max(0, int(input_tokens or 0))
        out_tok = max(0, int(output_tokens or 0))
        prov = str(provider or "unknown").strip() or "unknown"
        mod = str(model or "unknown").strip() or "unknown"

        with self._lock:
            self._rollover_usage_month(self._usage)
            for bucket in (self._usage["total"], self._usage["month"]):
                bucket["msgs"] = int(bucket.get("msgs", 0)) + 1
                bucket["input_tokens"] = int(bucket.get("input_tokens", 0)) + in_tok
                bucket["output_tokens"] = int(bucket.get("output_tokens", 0)) + out_tok

            p_bucket = self._usage.setdefault("by_provider", {}).setdefault(
                prov, {"msgs": 0, "input_tokens": 0, "output_tokens": 0}
            )
            p_bucket["msgs"] = int(p_bucket.get("msgs", 0)) + 1
            p_bucket["input_tokens"] = int(p_bucket.get("input_tokens", 0)) + in_tok
            p_bucket["output_tokens"] = int(p_bucket.get("output_tokens", 0)) + out_tok

            m_bucket = self._usage.setdefault("by_model", {}).setdefault(
                mod, {"msgs": 0, "input_tokens": 0, "output_tokens": 0}
            )
            m_bucket["msgs"] = int(m_bucket.get("msgs", 0)) + 1
            m_bucket["input_tokens"] = int(m_bucket.get("input_tokens", 0)) + in_tok
            m_bucket["output_tokens"] = int(m_bucket.get("output_tokens", 0)) + out_tok

            self._usage["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
            self._save_json(self._usage_file, self._usage)
            return copy.deepcopy(self._usage)

    def get_usage(self) -> dict[str, Any]:
        with self._lock:
            if self._rollover_usage_month(self._usage):
                self._save_json(self._usage_file, self._usage)
            return copy.deepcopy(self._usage)

    # ------------------------------------------------------------------
    # Named Preset Snapshots API (`snapshots.json`, max 30)
    # ------------------------------------------------------------------
    def get_snapshots(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._snapshots)

    def save_snapshot(self, name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            clean_name = re.sub(r"\s+", " ", str(name or "")).strip()[:80]
            if not clean_name:
                clean_name = dt.datetime.now().strftime("Snapshot %Y-%m-%d %H:%M")
            entry: dict[str, Any] = {
                "id": f"snap_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
                "name": clean_name,
                "created_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "data": copy.deepcopy(data) if isinstance(data, dict) else {},
            }
            self._snapshots.insert(0, entry)
            self._snapshots = self._snapshots[:MAX_SNAPSHOTS]
            self._save_json(self._snapshots_file, self._snapshots)
            return copy.deepcopy(self._snapshots)

    def delete_snapshot(self, snap_id: str) -> list[dict[str, Any]]:
        with self._lock:
            before = len(self._snapshots)
            self._snapshots = [s for s in self._snapshots if s.get("id") != snap_id]
            if len(self._snapshots) != before:
                self._save_json(self._snapshots_file, self._snapshots)
            return copy.deepcopy(self._snapshots)

    # ------------------------------------------------------------------
    # Apply Undo History API (`apply_history.json`, max 20)
    # ------------------------------------------------------------------
    def get_apply_history(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._apply_history)

    def push_apply_record(self, record: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            entry = copy.deepcopy(record) if isinstance(record, dict) else {}
            if not entry.get("id"):
                entry["id"] = f"apply_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
            if not entry.get("created_at"):
                entry["created_at"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._apply_history.insert(0, entry)
            self._apply_history = self._apply_history[:MAX_APPLY_HISTORY]
            self._save_json(self._apply_history_file, self._apply_history)
            return copy.deepcopy(self._apply_history)

    def pop_apply_record(self, record_id: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            if not self._apply_history:
                return None
            idx: int | None = None
            if not record_id:
                idx = 0
            else:
                for i, rec in enumerate(self._apply_history):
                    if rec.get("id") == record_id:
                        idx = i
                        break
            if idx is None:
                return None
            popped = self._apply_history.pop(idx)
            self._save_json(self._apply_history_file, self._apply_history)
            return copy.deepcopy(popped)
