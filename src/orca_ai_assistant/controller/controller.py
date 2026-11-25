"""Main controller coordinating OrcaSlicer UI views, snapshots, streaming, and actions."""

from __future__ import annotations

import atexit
import copy
import datetime as dt
import json
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

try:
    import orca
    import orca.host
except Exception:  # pragma: no cover - running outside OrcaSlicer host
    orca = None  # type: ignore

from orca_ai_assistant.controller.settings_parser import extract_suggested_settings
from orca_ai_assistant.core.constants import (
    MCP_DEFAULT_HOST,
    MCP_DEFAULT_PORT,
    PLUGIN_ID,
    PLUGIN_VERSION,
    detect_default_language,
    norm_lang,
    tr,
)
from orca_ai_assistant.core.storage import StorageManager, get_plugin_storage_dir
from orca_ai_assistant.mcp.server import OrcaMCPServer
from orca_ai_assistant.orca_bridge.enums import CUSTOM_GCODE_KEYS
from orca_ai_assistant.orca_bridge.gcode_analyzer import (
    compute_slice_delta,
    summarize_gcode_file,
    summarize_gcode_text,
)
from orca_ai_assistant.orca_bridge.geometry import inspect_plate_geometry
from orca_ai_assistant.orca_bridge.preflight import run_preflight_checks
from orca_ai_assistant.orca_bridge.presets import (
    apply_settings_to_orcaslicer,
    capture_full_preset_snapshot,
    inspect_slicer_presets,
)
from orca_ai_assistant.orca_bridge.prompts import (
    DEFECT_CATALOG,
    build_calibration_prompt,
    build_context_markdown,
    build_defect_prompt,
    calculate_calibration_values,
    get_system_prompt,
)
from orca_ai_assistant.providers.client import (
    CancelToken,
    fetch_provider_models,
    send_chat_completion,
)
from orca_ai_assistant.providers.registry import PROVIDER_PRESETS

_GCODE_MENTION_RE = re.compile(
    r"(start[\s_-]?g[\s_-]?code|end[\s_-]?g[\s_-]?code|layer[\s_-]?change|"
    r"machine_start_gcode|machine_end_gcode|filament_start_gcode|filament_end_gcode|"
    r"change_filament_gcode|before_layer_change_gcode|custom[\s_-]?g[\s_-]?code|"
    r"стартов\w*\s+g[\s_-]?code|конечн\w*\s+g[\s_-]?code|кінце\w*\s+g[\s_-]?code|"
    r"стартов\w*\s+гкод|конечн\w*\s+гкод|пользовательск\w*\s+g[\s_-]?code|"
    r"користувацьк\w*\s+g[\s_-]?code|g[\s_-]?code\s+принтер|g[\s_-]?code\s+филамент|"
    r"g[\s_-]?code\s+філамент)",
    re.IGNORECASE,
)

_LIFECYCLE_DEBOUNCE_SEC = 0.35
_SNAPSHOT_FRESH_TTL_SEC = 2.0


def load_asset(rel_path: str) -> str:
    """Load a static UTF-8 asset from the bundled dict or package directory."""
    rel_posix = str(rel_path).replace("\\", "/").lstrip("/")

    # 1) Single-file bundle virtual module
    try:
        import orca_ai_assistant._bundled_assets as _ba  # type: ignore

        assets_map = getattr(_ba, "ASSETS", None)
        if isinstance(assets_map, dict) and rel_posix in assets_map:
            return str(assets_map[rel_posix])
    except Exception:
        pass

    # 2) Fallback attribute attached to package root
    pkg = sys.modules.get("orca_ai_assistant")
    bundled_map = getattr(pkg, "_BUNDLED_ASSETS", None) if pkg is not None else None
    if isinstance(bundled_map, dict) and rel_posix in bundled_map:
        return str(bundled_map[rel_posix])

    # 3) Standard on-disk package tree
    pkg_root = Path(__file__).resolve().parent.parent
    disk_path = pkg_root / rel_posix
    return disk_path.read_text(encoding="utf-8")


def load_ui_html(view_mode: str = "page") -> str:
    """Assemble self-contained HTML for either the top-level Page tab or Dock panel."""
    mode = "dock" if str(view_mode).strip().lower() == "dock" else "page"
    template = load_asset("ui/template.html")
    css = load_asset("ui/styles.css")
    markdown_js = load_asset("ui/markdown.js")
    app_js = load_asset("ui/app.js")

    locales: dict[str, Any] = {}
    for code in ("ru", "uk", "en"):
        try:
            locales[code] = json.loads(load_asset(f"assets/locales/{code}.json"))
        except Exception:
            locales[code] = {}

    locales_json = json.dumps(locales, ensure_ascii=False).replace("</", "<\\/")

    html = template
    if "__VIEW_MODE__" in html:
        html = html.replace("__VIEW_MODE__", mode)
    elif "<html" in html and "data-view=" not in html:
        html = html.replace("<html", f'<html data-view="{mode}"', 1)

    html = html.replace("/* __INLINE_CSS__ */", css, 1)
    html = html.replace("__INLINE_LOCALES__", locales_json, 1)
    html = html.replace("/* __INLINE_MARKDOWN_JS__ */", markdown_js, 1)
    html = html.replace("/* __INLINE_APP_JS__ */", app_js, 1)
    return html


def _safe_app_info() -> dict[str, Any]:
    if orca is None or not hasattr(orca, "host"):
        return {}
    try:
        info = orca.host.app_info()
        return info if isinstance(info, dict) else {}
    except Exception:
        return {}


def _safe_selected_printer() -> dict[str, Any] | None:
    if orca is None or not hasattr(orca, "host"):
        return None
    try:
        printer = orca.host.selected_printer()
        return printer if isinstance(printer, dict) else None
    except Exception:
        return None


def _mentions_custom_gcode(text: str) -> bool:
    return bool(text and _GCODE_MENTION_RE.search(text))


def _is_lifecycle_ok(ctx: Any) -> bool:
    code = getattr(ctx, "code", None)
    if code is None:
        return True
    try:
        evt_code_cls = getattr(orca, "LifecycleEvtCode", None) if orca is not None else None
        if evt_code_cls is not None and hasattr(evt_code_cls, "Ok"):
            return code == evt_code_cls.Ok
    except Exception:
        pass
    name = getattr(code, "name", str(code))
    return name.lower() in ("ok", "0", "lifecycleevtcode.ok")


class AssistantController:
    """Central state coordinator for Orca AI Assistant v3.0.0."""

    def __init__(self, storage: StorageManager | None = None) -> None:
        self.storage = storage if storage is not None else StorageManager()
        self._lock = threading.RLock()

        self._page_views: list[Any] = []
        self._dock_panel: Any = None

        self._last_plate_snapshot: dict[str, Any] = {
            "has_model": False,
            "objects": [],
            "warnings": [],
        }
        self._last_presets_snapshot: dict[str, Any] = {
            "groups": {},
            "flat_values": {},
            "filament_slots": [],
            "custom_gcode": {},
        }
        self._last_preflight: dict[str, Any] = {
            "score": 100,
            "status": "ok",
            "counts": {"danger": 0, "warn": 0, "ok": 0},
            "checks": [],
        }
        self._last_slice: dict[str, Any] | None = None
        self._baseline_slice: dict[str, Any] | None = None
        self._slice_delta: dict[str, Any] | None = None

        self._snapshot_stale: bool = True
        self._last_snapshot_ts: float = 0.0
        self._last_lifecycle_refresh: float = 0.0

        self._active_requests: dict[str, CancelToken] = {}
        self._request_chat_map: dict[str, str] = {}
        self._mcp_lock = threading.RLock()
        self._mcp_server: OrcaMCPServer | None = None
        self._mcp_atexit_registered: bool = False

    @property
    def _page_instances(self) -> list[Any]:
        """Backward-compatible alias for registered page views."""
        return self._page_views

    # ------------------------------------------------------------------
    # View registry & targeted vs broadcast messaging (fixes P1 #8)
    # ------------------------------------------------------------------

    def register_page(self, page_obj: Any) -> None:
        if page_obj is None:
            return
        with self._lock:
            if page_obj not in self._page_views:
                self._page_views.append(page_obj)

    def unregister_page(self, page_obj: Any) -> None:
        if page_obj is None:
            return
        with self._lock:
            self._page_views = [p for p in self._page_views if p is not page_obj]

    def has_open_views(self) -> bool:
        with self._lock:
            if self._page_views:
                return True
            dock = self._dock_panel
        if dock is not None:
            try:
                is_open = getattr(dock, "is_open", None)
                return bool(is_open()) if callable(is_open) else True
            except Exception:
                return False
        return False

    def _post_to_view(self, view: Any, payload: dict[str, Any]) -> bool:
        if view is None:
            return False
        try:
            is_open = getattr(view, "is_open", None)
            if callable(is_open) and not is_open():
                return False
            if hasattr(view, "post_message") and callable(view.post_message):
                view.post_message(payload)
                return True
            if hasattr(view, "post") and callable(view.post):
                view.post(payload)
                return True
        except Exception:
            return False
        return False

    def emit(self, payload: dict[str, Any], target_view: Any | None = None) -> None:
        """Send payload to a single view (if specified) or broadcast to all open views."""
        if target_view is not None:
            ok = self._post_to_view(target_view, payload)
            if not ok:
                with self._lock:
                    if target_view is self._dock_panel:
                        self._dock_panel = None
                    elif target_view in self._page_views:
                        self._page_views = [p for p in self._page_views if p is not target_view]
            return

        with self._lock:
            pages = list(self._page_views)
            dock = self._dock_panel

        dead_pages: list[Any] = []
        for page in pages:
            if not self._post_to_view(page, payload):
                dead_pages.append(page)

        dock_dead = False
        if dock is not None and not self._post_to_view(dock, payload):
            dock_dead = True

        if dead_pages or dock_dead:
            with self._lock:
                if dead_pages:
                    self._page_views = [p for p in self._page_views if p not in dead_pages]
                if dock_dead and self._dock_panel is dock:
                    self._dock_panel = None

    def open_dock_panel(self) -> None:
        """Open (or focus) the compact Dock Panel with `data-view="dock"`."""
        lang = self.storage.get_lang()
        try:
            with self._lock:
                existing = self._dock_panel

            if existing is not None:
                is_open = getattr(existing, "is_open", None)
                if not callable(is_open) or is_open():
                    if hasattr(existing, "show"):
                        existing.show()
                    return
                with self._lock:
                    if self._dock_panel is existing:
                        self._dock_panel = None

            if orca is None or not hasattr(orca, "host") or not hasattr(orca.host, "ui"):
                return

            dock_html = load_ui_html(view_mode="dock")

            def _on_dock_msg(raw_msg: Any) -> None:
                with self._lock:
                    dock_ref = self._dock_panel
                self.handle_message_on_ui(raw_msg, source_view=dock_ref)

            panel = orca.host.ui.create_dock_panel(
                html=dock_html,
                title=tr(lang, "Orca AI Ассистент", "Orca AI Асистент", "Orca AI Assistant"),
                width=460,
                height=740,
                on_message=_on_dock_msg,
                on_close=self._on_dock_closed,
                dock="right",
            )
            with self._lock:
                self._dock_panel = panel
            # Wait for the Dock WebView's `init` / `ready` handshake so we never
            # drop the initial payload or wipe an active stream in the Page tab.
        except Exception as exc:
            self.emit({
                "type": "toast",
                "text": tr(
                    lang,
                    f"Не удалось открыть панель: {exc}",
                    f"Не вдалося відкрити панель: {exc}",
                    f"Could not open dock panel: {exc}",
                ),
                "is_error": True,
            })

    def _on_dock_closed(self) -> None:
        with self._lock:
            self._dock_panel = None

    # ------------------------------------------------------------------
    # Active request & CancelToken tracking (fixes P0 #1, P0 #2, P1 #9)
    # ------------------------------------------------------------------

    def _register_request(self, request_id: str, chat_id: str) -> CancelToken:
        token = CancelToken()
        with self._lock:
            self._active_requests[request_id] = token
            self._request_chat_map[request_id] = chat_id
        return token

    def _finish_request(self, request_id: str) -> None:
        with self._lock:
            self._active_requests.pop(request_id, None)
            self._request_chat_map.pop(request_id, None)

    def _get_active_request_for_chat(self, chat_id: str | None) -> str:
        if not chat_id:
            return ""
        with self._lock:
            for req_id, cid in self._request_chat_map.items():
                if cid == chat_id and req_id in self._active_requests:
                    return req_id
        return ""

    def _get_any_active_stream(self) -> tuple[str, str]:
        with self._lock:
            for req_id, cid in self._request_chat_map.items():
                if req_id in self._active_requests:
                    return req_id, cid
        return "", ""

    def _cancel_request(self, request_id: str | None = None) -> int:
        tokens: list[CancelToken] = []
        with self._lock:
            if request_id and request_id in self._active_requests:
                tokens.append(self._active_requests[request_id])
            elif not request_id:
                tokens.extend(self._active_requests.values())
        for tok in tokens:
            try:
                tok.cancel()
            except Exception:
                pass
        return len(tokens)

    # ------------------------------------------------------------------
    # Thread-safe snapshot management (fixes P0 #5 UI freeze)
    # ------------------------------------------------------------------

    def capture_ui_snapshots(
        self,
        force: bool = True,
        include_geometry: bool = True,
        include_presets: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Capture plate geometry, presets, and deterministic pre-flight checks.

        Only invoked for actions that genuinely need fresh slicer state, never
        on unrelated clicks like saving settings or switching chats.
        """
        lang = self.storage.get_lang()
        now = time.monotonic()

        with self._lock:
            plate = self._last_plate_snapshot
            presets = self._last_presets_snapshot
            last_slice = self._last_slice
            is_fresh = (not self._snapshot_stale) and ((now - self._last_snapshot_ts) < _SNAPSHOT_FRESH_TTL_SEC)

        if not force and is_fresh:
            with self._lock:
                return self._last_plate_snapshot, self._last_presets_snapshot, self._last_preflight

        if include_geometry:
            try:
                plate = inspect_plate_geometry(lang)
            except Exception:
                pass

        if include_presets:
            try:
                presets = inspect_slicer_presets(lang, include_gcode=True)
            except Exception:
                pass

        try:
            preflight = run_preflight_checks(plate, presets, last_slice=last_slice, lang=lang)
        except Exception:
            with self._lock:
                preflight = self._last_preflight

        with self._lock:
            if include_geometry:
                self._last_plate_snapshot = plate
            if include_presets:
                self._last_presets_snapshot = presets
            self._last_preflight = preflight
            if include_geometry and include_presets:
                self._snapshot_stale = False
                self._last_snapshot_ts = time.monotonic()

        return plate, presets, preflight

    def _get_cached_snapshots(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
        with self._lock:
            return (
                self._last_plate_snapshot,
                self._last_presets_snapshot,
                self._last_preflight,
                self._last_slice,
                self._slice_delta,
            )

    def _build_full_state(
        self,
        plate: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
    ) -> dict[str, Any]:
        chats = self.storage.get_chats()
        active_chat_id = str(chats.get("active_id") or "")
        active_req_id = self._get_active_request_for_chat(active_chat_id)
        any_req_id, any_stream_chat = self._get_any_active_stream()
        with self._lock:
            last_slice = self._last_slice
            slice_delta = self._slice_delta

        return {
            "type": "full_state",
            "version": PLUGIN_VERSION,
            "providers": PROVIDER_PRESETS,
            "settings": self.storage.get_settings(),
            "chats": chats,
            "plate": plate,
            "presets": presets,
            "preflight": preflight,
            "last_slice": last_slice,
            "slice_delta": slice_delta,
            "snapshots": self.storage.get_snapshots(),
            "apply_history": self.storage.get_apply_history(),
            "usage": self.storage.get_usage(),
            "mcp": self.get_mcp_status(),
            "defects": DEFECT_CATALOG,
            "active_request_id": active_req_id,
            "active_stream_chat_id": active_chat_id if active_req_id else any_stream_chat,
            "any_active_request_id": any_req_id,
        }

    # ------------------------------------------------------------------
    # MCP Server lifecycle
    # ------------------------------------------------------------------

    def get_mcp_status(self) -> dict[str, Any]:
        with self._mcp_lock:
            srv = self._mcp_server
        if srv is not None:
            return srv.get_status()
        settings = self.storage.get_settings()
        try:
            port = int(settings.get("mcp_port") or MCP_DEFAULT_PORT)
        except (TypeError, ValueError):
            port = MCP_DEFAULT_PORT
        return {
            "running": False,
            "enabled": bool(settings.get("mcp_enabled", False)),
            "host": MCP_DEFAULT_HOST,
            "port": port,
            "url": f"http://{MCP_DEFAULT_HOST}:{port}/mcp",
            "health_url": f"http://{MCP_DEFAULT_HOST}:{port}/health",
            "require_auth": bool(settings.get("mcp_require_auth", True)),
            "token": str(settings.get("mcp_token") or ""),
            "allow_write": bool(settings.get("mcp_allow_write", True)),
            "allow_gcode_write": bool(settings.get("mcp_allow_gcode_write", True)),
            "error": "",
            "recent_calls": [],
        }

    def sync_mcp_server(self, emit_update: bool = True) -> dict[str, Any]:
        settings = self.storage.get_settings()
        enabled = bool(settings.get("mcp_enabled", False))
        require_auth = bool(settings.get("mcp_require_auth", True))
        if (enabled or require_auth) and not str(settings.get("mcp_token") or "").strip():
            self.storage.ensure_mcp_token(force_new=False)
            settings = self.storage.get_settings()

        try:
            port = int(settings.get("mcp_port") or MCP_DEFAULT_PORT)
        except (TypeError, ValueError):
            port = MCP_DEFAULT_PORT

        with self._mcp_lock:
            if not enabled:
                if self._mcp_server is not None:
                    self._mcp_server.stop()
                    self._mcp_server = None
            else:
                if (
                    self._mcp_server is None
                    or not self._mcp_server.is_running
                    or self._mcp_server.requested_port != port
                ):
                    if self._mcp_server is not None:
                        self._mcp_server.stop()
                    srv = OrcaMCPServer(self, host=MCP_DEFAULT_HOST, port=port)
                    srv.start()
                    self._mcp_server = srv
                    if not self._mcp_atexit_registered:
                        atexit.register(self.shutdown_mcp_server)
                        self._mcp_atexit_registered = True

        status = self.get_mcp_status()
        if emit_update:
            self.emit({
                "type": "mcp_status_updated",
                "mcp": status,
                "settings": settings,
            })
        return status

    def regenerate_mcp_token(self) -> dict[str, Any]:
        self.storage.ensure_mcp_token(force_new=True)
        settings = self.storage.get_settings()
        status = self.get_mcp_status()
        self.emit({
            "type": "settings_updated",
            "settings": settings,
            "mcp": status,
            "usage": self.storage.get_usage(),
        })
        self.emit({
            "type": "mcp_status_updated",
            "mcp": status,
            "settings": settings,
        })
        return status

    def shutdown_mcp_server(self) -> None:
        with self._mcp_lock:
            srv = self._mcp_server
            self._mcp_server = None
        if srv is not None:
            srv.stop()

    def _emit_chats_updated(
        self,
        chats: dict[str, Any],
        *,
        active_request_id: str | None = None,
        active_stream_chat_id: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        active_id = str(chats.get("active_id") or "")
        if active_request_id is None:
            active_request_id = self._get_active_request_for_chat(active_id)
        payload: dict[str, Any] = {
            "type": "chats_updated",
            "chats": chats,
            "active_request_id": active_request_id or "",
        }
        if active_stream_chat_id:
            payload["active_stream_chat_id"] = active_stream_chat_id
        elif active_request_id:
            payload["active_stream_chat_id"] = active_id
        if extra:
            payload.update(extra)
        self.emit(payload)

    def sync_plugin_config(self, cfg: dict[str, Any] | None) -> None:
        """Sync OrcaSlicer's native plugin settings toggles into StorageManager."""
        if not isinstance(cfg, dict):
            return
        patch: dict[str, Any] = {}
        if "preflight_notifications" in cfg:
            patch["preflight_notifications"] = bool(cfg["preflight_notifications"])
        if "enable_slicing_audit" in cfg:
            patch["enable_slicing_audit"] = bool(cfg["enable_slicing_audit"])
        if patch:
            updated = self.storage.update_settings(patch)
            self.emit({"type": "settings_updated", "settings": updated, "usage": self.storage.get_usage()})

    # ------------------------------------------------------------------
    # Lifecycle events (OrcaSlicer 2.5+ real-time hooks)
    # ------------------------------------------------------------------

    def handle_lifecycle_event(self, event: Any, ctx: Any) -> None:
        """Handle OrcaSlicer lifecycle events without blocking the UI thread."""
        event_name = getattr(event, "name", str(event))
        if "." in event_name:
            event_name = event_name.rsplit(".", 1)[-1]

        if event_name == "GCodeExportFinished":
            if not _is_lifecycle_ok(ctx):
                return
            gcode_path = str(getattr(ctx, "msg", "") or "").strip()
            if gcode_path:
                self.handle_sliced_gcode_file(gcode_path, auto_audit=False)
            return

        if event_name in ("NewProject", "ProjectOpened"):
            with self._lock:
                self._snapshot_stale = True
                self._last_slice = None
                self._baseline_slice = None
                self._slice_delta = None
            self._maybe_refresh_on_lifecycle(include_geometry=True, include_presets=True)
            return

        if event_name in ("PlateSelected", "ObjectAdded", "ObjectDeleted", "ObjectTransformed", "ObjectChanged"):
            with self._lock:
                self._snapshot_stale = True
            self._maybe_refresh_on_lifecycle(include_geometry=True, include_presets=False)
            return

        if event_name in ("PresetSelected", "PresetSaved"):
            with self._lock:
                self._snapshot_stale = True
            self._maybe_refresh_on_lifecycle(include_geometry=False, include_presets=True)

    def _maybe_refresh_on_lifecycle(self, include_geometry: bool, include_presets: bool) -> None:
        if not self.has_open_views():
            return
        now = time.monotonic()
        with self._lock:
            if (now - self._last_lifecycle_refresh) < _LIFECYCLE_DEBOUNCE_SEC:
                return
            self._last_lifecycle_refresh = now

        plate, presets, preflight = self.capture_ui_snapshots(
            force=True,
            include_geometry=include_geometry,
            include_presets=include_presets,
        )
        with self._lock:
            last_slice = self._last_slice
            slice_delta = self._slice_delta
        self.emit({
            "type": "context_updated",
            "plate": plate,
            "presets": presets,
            "preflight": preflight,
            "last_slice": last_slice,
            "slice_delta": slice_delta,
        })

    def handle_sliced_gcode_file(self, gcode_path: str | Path, auto_audit: bool = False) -> None:
        """Analyze a sliced .gcode / .gcode.3mf file off-thread and update Pre-Flight."""
        path_str = str(gcode_path)
        threading.Thread(
            target=self._worker_on_gcode_exported,
            args=(path_str, auto_audit),
            daemon=True,
        ).start()

    def _worker_on_gcode_exported(self, gcode_path: str, auto_audit: bool = False) -> None:
        lang = self.storage.get_lang()
        try:
            summary = summarize_gcode_file(gcode_path)
        except Exception:
            return

        if not isinstance(summary, dict) or summary.get("error"):
            return

        with self._lock:
            baseline = self._baseline_slice
            plate = self._last_plate_snapshot
            presets = self._last_presets_snapshot
            delta = compute_slice_delta(baseline, summary) if baseline else None
            self._last_slice = summary
            self._slice_delta = delta

        try:
            preflight = run_preflight_checks(plate, presets, last_slice=summary, lang=lang)
        except Exception:
            with self._lock:
                preflight = self._last_preflight

        with self._lock:
            self._last_preflight = preflight

        self.emit({
            "type": "context_updated",
            "plate": plate,
            "presets": presets,
            "preflight": preflight,
            "last_slice": summary,
            "slice_delta": delta,
        })

        settings = self.storage.get_settings()
        danger_count = int((preflight.get("counts") or {}).get("danger", 0))
        if settings.get("preflight_notifications", True) and danger_count > 0:
            self._push_preflight_notification(danger_count, preflight, lang)

        if auto_audit:
            req_id = f"req_slice_{int(time.time() * 1000)}"
            prompt = self._format_slice_audit_prompt(summary, delta, lang)
            self._worker_send_chat(
                {"text": prompt, "attach_context": True, "request_id": req_id},
                plate,
                presets,
                preflight,
                req_id,
            )

    def push_native_notification(
        self,
        message: str,
        level: str = "info",
        *,
        link_text: str = "",
        on_click: Any = None,
    ) -> bool:
        """Display a native OrcaSlicer notification banner when host UI is available."""
        if orca is None or not hasattr(orca, "host") or not hasattr(orca.host, "ui"):
            return False
        push_fn = getattr(orca.host.ui, "push_notification", None)
        if not callable(push_fn):
            return False
        lvl_key = str(level or "info").strip().lower()
        try:
            level_cls = getattr(orca.host.ui, "NotificationLevel", None) or getattr(orca, "NotificationLevel", None)
            if lvl_key == "error":
                lvl_val = getattr(level_cls, "Error", getattr(level_cls, "Warning", 6)) if level_cls is not None else 6
            elif lvl_key in ("warn", "warning"):
                lvl_val = getattr(level_cls, "Warning", 5) if level_cls is not None else 5
            else:
                lvl_val = getattr(level_cls, "Info", getattr(level_cls, "Regular", 1)) if level_cls is not None else 1
            if link_text or on_click is not None:
                try:
                    push_fn(lvl_val, message, link_text or "", on_click or self.open_dock_panel)
                    return True
                except TypeError:
                    pass
            push_fn(lvl_val, message)
            return True
        except Exception:
            return False

    def _push_preflight_notification(self, danger_count: int, preflight: dict[str, Any], lang: str) -> None:
        score = preflight.get("score", 0)
        msg = tr(
            lang,
            f"Orca AI Pre-Flight: найдено критических проблем — {danger_count} (оценка {score}/100).",
            f"Orca AI Pre-Flight: знайдено критичних проблем — {danger_count} (оцінка {score}/100).",
            f"Orca AI Pre-Flight: {danger_count} critical issue(s) detected (score {score}/100).",
        )
        link_text = tr(lang, "Открыть Orca AI", "Відкрити Orca AI", "Open Orca AI")
        self.push_native_notification(msg, level="warning", link_text=link_text, on_click=self.open_dock_panel)

    # ------------------------------------------------------------------
    # Main UI message dispatcher (runs on OrcaSlicer UI thread)
    # ------------------------------------------------------------------

    def handle_message_on_ui(self, raw_msg: Any, source_view: Any | None = None) -> None:
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

        action = str(data.get("action") or "").strip()
        if not action:
            return
        lang = self.storage.get_lang()

        # ---- Fast actions: NEVER invoke inspect_plate_geometry() ----
        if action == "save_settings":
            patch = data.get("settings")
            if isinstance(patch, dict):
                has_mcp_keys = any(str(k).startswith("mcp_") for k in patch.keys())
                updated = self.storage.update_settings(patch)
                payload: dict[str, Any] = {
                    "type": "settings_updated",
                    "settings": updated,
                    "usage": self.storage.get_usage(),
                }
                if has_mcp_keys:
                    mcp_status = self.sync_mcp_server(emit_update=False)
                    payload["mcp"] = mcp_status
                    payload["settings"] = self.storage.get_settings()
                self.emit(payload)
                if has_mcp_keys:
                    self.emit({
                        "type": "mcp_status_updated",
                        "mcp": payload["mcp"],
                        "settings": payload["settings"],
                    })
            return

        if action == "mcp_get_status":
            self.emit({
                "type": "mcp_status_updated",
                "mcp": self.get_mcp_status(),
                "settings": self.storage.get_settings(),
            })
            return

        if action == "mcp_regenerate_token":
            self.regenerate_mcp_token()
            self.emit({
                "type": "toast",
                "text": tr(
                    lang,
                    "Новый MCP-токен сгенерирован.",
                    "Новий MCP-токен згенеровано.",
                    "New MCP token generated.",
                ),
            })
            return

        if action == "mcp_restart":
            with self._mcp_lock:
                if self._mcp_server is not None:
                    self._mcp_server.stop()
                    self._mcp_server = None
            status = self.sync_mcp_server(emit_update=True)
            if status.get("error"):
                self.emit({"type": "toast", "text": f"MCP error: {status['error']}", "is_error": True})
            return

        if action == "open_dock":
            self.open_dock_panel()
            return

        if action == "stop_generation":
            req_id = str(data.get("request_id") or "").strip() or None
            cancelled = self._cancel_request(req_id)
            if cancelled == 0:
                chats = self.storage.get_chats()
                self._emit_chats_updated(chats, active_request_id="")
            return

        if action == "new_chat":
            title = str(data.get("title") or "").strip() or tr(lang, "Новый диалог", "Новий діалог", "New Chat")
            _new_id, chats = self.storage.create_chat(title)
            self._emit_chats_updated(chats)
            return

        if action == "select_chat":
            cid = str(data.get("chat_id") or "").strip()
            chats = self.storage.get_chats()
            if any(s.get("id") == cid for s in chats.get("sessions", [])):
                chats["active_id"] = cid
                self.storage.save_chats(chats)
            self._emit_chats_updated(chats)
            return

        if action == "rename_chat":
            cid = str(data.get("chat_id") or "").strip()
            title = str(data.get("title") or "").strip()
            if cid and title:
                chats = self.storage.rename_chat(cid, title)
                self._emit_chats_updated(chats)
            return

        if action == "pin_chat":
            cid = str(data.get("chat_id") or "").strip()
            chats = self.storage.get_chats()
            for s in chats.get("sessions", []):
                if s.get("id") == cid:
                    s["pinned"] = bool(data["pinned"]) if "pinned" in data else not bool(s.get("pinned"))
                    break
            self.storage.save_chats(chats)
            self._emit_chats_updated(chats)
            return

        if action == "delete_chat":
            cid = str(data.get("chat_id") or "").strip()
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
            self._emit_chats_updated(chats)
            return

        if action == "clear_chat":
            cid = str(data.get("chat_id") or "").strip()
            self._clear_chat_session(cid or None, lang)
            return

        if action == "fetch_models":
            threading.Thread(target=self._worker_fetch_models, args=(data,), daemon=True).start()
            return

        if action == "import_printpurr":
            cnt, new_settings = self.storage.import_from_printpurr()
            self.emit({
                "type": "settings_updated",
                "settings": new_settings,
                "providers": PROVIDER_PRESETS,
                "usage": self.storage.get_usage(),
            })
            self.emit({
                "type": "toast",
                "text": (
                    tr(
                        lang,
                        f"Импортировано ключей из PrintPurr: {cnt}",
                        f"Імпортовано ключів із PrintPurr: {cnt}",
                        f"Imported {cnt} keys from PrintPurr",
                    )
                    if cnt
                    else tr(
                        lang,
                        "В PrintPurr не найдено сохранённых ключей",
                        "У PrintPurr не знайдено збережених ключів",
                        "No saved keys found in PrintPurr",
                    )
                ),
                "is_error": cnt == 0,
            })
            return

        if action == "save_snapshot":
            name = str(data.get("name") or "").strip()
            if not name:
                name = dt.datetime.now().strftime("Snapshot %d.%m %H:%M")
            self.save_snapshot_sync(name)
            return

        if action == "delete_snapshot":
            snap_id = str(data.get("snap_id") or data.get("snapshot_id") or data.get("id") or "").strip()
            if snap_id:
                snapshots = self.storage.delete_snapshot(snap_id)
                self.emit({"type": "snapshots_updated", "snapshots": snapshots})
            return

        if action == "calc_calibration":
            self._handle_calc_calibration(data, lang)
            return

        if action == "apply_settings":
            changes = data.get("changes") or []
            allow_gcode = bool(data.get("allow_gcode", False))
            source = str(data.get("source") or "chat")
            card_id = str(data.get("card_id") or "").strip()
            threading.Thread(
                target=self._worker_apply_settings,
                args=(changes, allow_gcode, source, card_id),
                daemon=True,
            ).start()
            return

        if action == "undo_apply":
            rec_id = str(data.get("record_id") or "").strip() or None
            threading.Thread(
                target=self._worker_undo_apply,
                args=(rec_id, None),
                daemon=True,
            ).start()
            return

        if action == "restore_snapshot":
            snap_id = str(data.get("snap_id") or data.get("snapshot_id") or data.get("id") or "").strip()
            threading.Thread(
                target=self._worker_restore_snapshot,
                args=(snap_id,),
                daemon=True,
            ).start()
            return

        # ---- Actions that refresh / require snapshots ----
        if action in ("init", "ready"):
            # Reuse fresh cache when opening Dock right after Tab so it never freezes.
            plate, presets, preflight = self.capture_ui_snapshots(force=False)
            full_state = self._build_full_state(plate, presets, preflight)
            self.emit(full_state, target_view=source_view)
            return

        if action == "change_language":
            new_lang = norm_lang(data.get("language", "ru"))
            updated = self.storage.update_settings({"language": new_lang})
            self.emit({
                "type": "settings_updated",
                "settings": updated,
                "usage": self.storage.get_usage(),
            })
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            with self._lock:
                last_slice = self._last_slice
                slice_delta = self._slice_delta
            self.emit({
                "type": "context_updated",
                "plate": plate,
                "presets": presets,
                "preflight": preflight,
                "last_slice": last_slice,
                "slice_delta": slice_delta,
                "toast": tr(
                    new_lang,
                    "🇷🇺 Язык переключён на Русский",
                    "🇺🇦 Мову перемкнено на Українську",
                    "🇬🇧 Language switched to English",
                ),
            })
            return

        if action == "refresh_context":
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            with self._lock:
                last_slice = self._last_slice
                slice_delta = self._slice_delta
            self.emit({
                "type": "context_updated",
                "plate": plate,
                "presets": presets,
                "preflight": preflight,
                "last_slice": last_slice,
                "slice_delta": slice_delta,
                "toast": tr(
                    lang,
                    "Данные 3D-стола, пресетов и Pre-Flight обновлены!",
                    "Дані 3D-столу, пресетів та Pre-Flight оновлено!",
                    "Build plate, presets, and Pre-Flight checks refreshed!",
                ),
            })
            return

        if action == "send_chat":
            self._handle_send_chat_on_ui(data, lang)
            return

        if action == "run_defect_wizard":
            symptom_id = str(data.get("symptom_id") or "").strip()
            notes = str(data.get("notes") or "").strip()
            prompt = build_defect_prompt(symptom_id, notes, lang=lang)
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
            chat_data = dict(data)
            chat_data["text"] = prompt
            chat_data["attach_context"] = True
            chat_data["request_id"] = req_id
            threading.Thread(
                target=self._worker_send_chat,
                args=(chat_data, plate, presets, preflight, req_id),
                daemon=True,
            ).start()
            return

        if action == "audit_last_slice":
            with self._lock:
                last_slice = self._last_slice
                slice_delta = self._slice_delta
            if not last_slice:
                self.emit({
                    "type": "toast",
                    "text": tr(
                        lang,
                        "Сначала нарежьте модель в OrcaSlicer или загрузите .gcode файл.",
                        "Спочатку наріжте модель в OrcaSlicer або завантажте .gcode файл.",
                        "Slice a plate in OrcaSlicer first or upload a .gcode file.",
                    ),
                    "is_error": True,
                    "clear_busy": True,
                })
                return
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
            prompt = self._format_slice_audit_prompt(last_slice, slice_delta, lang)
            chat_data = dict(data)
            chat_data["text"] = prompt
            chat_data["attach_context"] = True
            chat_data["request_id"] = req_id
            threading.Thread(
                target=self._worker_send_chat,
                args=(chat_data, plate, presets, preflight, req_id),
                daemon=True,
            ).start()
            return

        if action == "audit_gcode_content":
            fname = str(data.get("filename") or "sliced.gcode")
            gcontent = str(data.get("content") or "")
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            threading.Thread(
                target=self._worker_audit_gcode_text,
                args=(fname, gcontent, data, plate, presets, preflight),
                daemon=True,
            ).start()
            return

        if action == "audit_gcode_path":
            gpath = str(data.get("path") or "").strip()
            if not gpath:
                return
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            threading.Thread(
                target=self._worker_audit_gcode_path,
                args=(gpath, data, plate, presets, preflight),
                daemon=True,
            ).start()
            return

    # ------------------------------------------------------------------
    # Slash commands & chat entry
    # ------------------------------------------------------------------

    def _clear_chat_session(self, chat_id: str | None, lang: str) -> None:
        chats = self.storage.get_chats()
        target_id = chat_id or str(chats.get("active_id") or "")
        for s in chats.get("sessions", []):
            if s.get("id") == target_id:
                s["messages"] = []
                s["title"] = tr(lang, "Новый диалог", "Новий діалог", "New Chat")
                break
        self.storage.save_chats(chats)
        self._emit_chats_updated(chats)

    def _handle_send_chat_on_ui(self, data: dict[str, Any], lang: str) -> None:
        user_text = str(data.get("text") or "").strip()
        if not user_text:
            return

        chats = self.storage.get_chats()
        target_chat_id = str(data.get("chat_id") or chats.get("active_id") or "")
        if not target_chat_id or not any(s.get("id") == target_chat_id for s in chats.get("sessions", [])):
            target_chat_id, chats = self.storage.create_chat(
                tr(lang, "Новый диалог", "Новий діалог", "New Chat")
            )

        cmd_token = user_text.split()[0].lower() if user_text.startswith("/") else ""

        if cmd_token == "/clear":
            self._clear_chat_session(target_chat_id, lang)
            self.emit({
                "type": "toast",
                "text": tr(lang, "Диалог очищен.", "Діалог очищено.", "Chat cleared."),
            })
            return

        if cmd_token == "/undo":
            self.storage.append_message(target_chat_id, "user", user_text)
            threading.Thread(
                target=self._worker_undo_apply,
                args=(None, target_chat_id),
                daemon=True,
            ).start()
            return

        if cmd_token in ("/context", "/gcode", "/debug"):
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            self._handle_local_slash_command(
                cmd_token,
                user_text,
                target_chat_id,
                data,
                plate,
                presets,
                preflight,
                lang,
            )
            return

        settings = self.storage.get_settings()
        attach_ctx = bool(data.get("attach_context", settings.get("auto_attach_context", True)))
        if attach_ctx:
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
        else:
            plate, presets, preflight, _, _ = self._get_cached_snapshots()

        req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
        payload = dict(data)
        payload["chat_id"] = target_chat_id
        payload["request_id"] = req_id

        threading.Thread(
            target=self._worker_send_chat,
            args=(payload, plate, presets, preflight, req_id),
            daemon=True,
        ).start()

    def _handle_local_slash_command(
        self,
        cmd_token: str,
        user_text: str,
        target_chat_id: str,
        data: dict[str, Any],
        plate: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
        lang: str,
    ) -> None:
        settings = self.storage.get_settings()
        with self._lock:
            last_slice = self._last_slice

        if cmd_token == "/context":
            include_gcode = bool(
                data.get("include_gcode", settings.get("include_custom_gcode", False))
                or "gcode" in user_text.lower()
            )
            compact = bool(data.get("compact_context", settings.get("compact_context", True)))
            ctx_md = build_context_markdown(
                plate,
                presets,
                custom_instructions=str(settings.get("custom_user_instructions") or ""),
                lang=lang,
                include_gcode=include_gcode,
                compact=compact,
                last_slice=last_slice,
                preflight=preflight,
            )
            approx_tokens = max(1, len(ctx_md) // 4)
            header = tr(
                lang,
                f"### 📋 Текущий контекст для ИИ (~{approx_tokens} токенов, compact={compact}, gcode={include_gcode})",
                f"### 📋 Поточний контекст для ШІ (~{approx_tokens} токенів, compact={compact}, gcode={include_gcode})",
                f"### 📋 Current AI Context Payload (~{approx_tokens} tokens, compact={compact}, gcode={include_gcode})",
            )
            reply = f"{header}\n\n{ctx_md}"

        elif cmd_token == "/gcode":
            reply = self._format_local_gcode_report(presets, lang)

        else:  # /debug
            reply = self._format_local_debug_report(settings, presets, preflight, last_slice, lang)

        self.storage.append_message(target_chat_id, "user", user_text)
        chats = self.storage.append_message(
            target_chat_id,
            "assistant",
            reply,
            extra={"model": "local", "is_local_command": True},
        )
        self._emit_chats_updated(chats, active_request_id="")

    def _format_local_gcode_report(self, presets: dict[str, Any], lang: str) -> str:
        sections: list[str] = [
            tr(
                lang,
                "### 📜 Пользовательский G-code активных пресетов",
                "### 📜 Користувацький G-code активних пресетів",
                "### 📜 Active Preset Custom G-code",
            )
        ]
        custom_gcode = presets.get("custom_gcode") if isinstance(presets.get("custom_gcode"), dict) else {}
        found_any = False

        for key, raw_val in custom_gcode.items():
            text = ""
            if isinstance(raw_val, dict):
                text = str(raw_val.get("value") or "")
            elif isinstance(raw_val, list):
                text = "\n".join(str(x) for x in raw_val if x)
            elif isinstance(raw_val, str):
                text = raw_val
            if not text.strip():
                continue
            found_any = True
            sections.append(f"**`{key}`**\n```gcode\n{text}\n```")

        slots = presets.get("filament_slots") if isinstance(presets.get("filament_slots"), list) else []
        for s in slots:
            if not isinstance(s, dict):
                continue
            slot_num = s.get("slot", 1)
            slot_name = s.get("name") or f"Slot {slot_num}"
            for field, key_name in (("start_gcode", "filament_start_gcode"), ("end_gcode", "filament_end_gcode")):
                code = str(s.get(field) or "")
                if code.strip():
                    found_any = True
                    sections.append(f"**`{key_name}` — Slot {slot_num} ({slot_name})**\n```gcode\n{code}\n```")

        if not found_any:
            sections.append(
                tr(
                    lang,
                    "Активные пресеты не содержат непустых пользовательских блоков G-code.",
                    "Активні пресети не містять непорожніх користувацьких блоків G-code.",
                    "No non-empty custom G-code blocks found in active presets.",
                )
            )
        return "\n\n".join(sections)

    def _format_local_debug_report(
        self,
        settings: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
        last_slice: dict[str, Any] | None,
        lang: str,
    ) -> str:
        app_info = _safe_app_info()
        printer = _safe_selected_printer() or presets.get("connected_printer")
        provider = str(settings.get("provider") or "")
        model = str(settings.get("model") or "")
        effort = str(settings.get("reasoning_effort") or "low")
        storage_dir = str(get_plugin_storage_dir())
        slots = presets.get("filament_slots") if isinstance(presets.get("filament_slots"), list) else []
        usage = self.storage.get_usage()

        with self._lock:
            n_pages = len(self._page_views)
            has_dock = self._dock_panel is not None
            active_reqs = list(self._active_requests.keys())

        lines = [
            tr(
                lang,
                "### 🛠 Диагностика Orca AI Assistant",
                "### 🛠 Діагностика Orca AI Assistant",
                "### 🛠 Orca AI Assistant Diagnostics",
            ),
            f"- **Plugin**: `{PLUGIN_ID}` v`{PLUGIN_VERSION}`",
            f"- **Storage**: `{storage_dir}`",
            f"- **OrcaSlicer**: `{app_info.get('version', 'unknown')}` (build `{app_info.get('build', 'n/a')}`, lang `{app_info.get('language', 'n/a')}`, mode `{app_info.get('mode', 'n/a')}`)",
            f"- **AI Provider / Model**: `{provider}` / `{model}` (effort: `{effort}`, temp: `{settings.get('temperature')}`, compact: `{settings.get('compact_context')}`)",
            f"- **Connected Printer**: `{json.dumps(printer, ensure_ascii=False) if printer else 'None'}`",
            f"- **Open Views**: pages=`{n_pages}`, dock=`{has_dock}`, active_requests=`{active_reqs}`",
            f"- **Pre-Flight**: score=`{preflight.get('score', 100)}/100`, counts=`{preflight.get('counts', {})}`",
            f"- **Last Slice**: `{last_slice.get('filename') if isinstance(last_slice, dict) else 'None'}`",
            f"- **Usage**: `{json.dumps(usage, ensure_ascii=False)}`",
        ]

        if slots:
            lines.append("- **AMS / Filament Slots**:")
            for s in slots:
                if isinstance(s, dict):
                    lines.append(
                        f"  - Slot {s.get('slot', '?')}: `{s.get('name', '?')}` "
                        f"({s.get('type', '?')}, nozzle `{s.get('nozzle_temp', '?')}°C`, bed `{s.get('bed_temp', '?')}°C`)"
                    )
        else:
            lines.append("- **AMS / Filament Slots**: `None`")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Calibration Co-Pilot handler
    # ------------------------------------------------------------------

    def _handle_calc_calibration(self, data: dict[str, Any], lang: str) -> None:
        stage = str(data.get("stage") or "").strip()
        measurements = data.get("measurements")
        if not isinstance(measurements, dict):
            measurements = {}
        else:
            measurements = dict(measurements)

        try:
            slot = int(data.get("slot") or measurements.get("slot") or 1)
            if slot < 1:
                slot = 1
        except (TypeError, ValueError):
            slot = 1
        measurements["slot"] = slot

        try:
            result = calculate_calibration_values(stage, measurements, slot=slot, lang=lang)
        except TypeError:
            result = calculate_calibration_values(stage, measurements)
        except Exception as exc:
            result = {"ok": False, "error": str(exc), "changes": []}

        # Ensure every returned change targets the chosen AMS slot
        if isinstance(result, dict):
            result.setdefault("slot", slot)
            if isinstance(result.get("changes"), list):
                for ch in result["changes"]:
                    if isinstance(ch, dict) and ch.get("category") == "filament":
                        ch["slot"] = slot

        self.emit({
            "type": "calibration_result",
            "stage": stage,
            "slot": slot,
            "result": result,
        })

        if data.get("ask_ai"):
            plate, presets, preflight = self.capture_ui_snapshots(force=True)
            req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
            prompt = build_calibration_prompt(stage, measurements, slot=slot, lang=lang)
            chat_data = dict(data)
            chat_data["text"] = prompt
            chat_data["attach_context"] = True
            chat_data["request_id"] = req_id
            threading.Thread(
                target=self._worker_send_chat,
                args=(chat_data, plate, presets, preflight, req_id),
                daemon=True,
            ).start()

    # ------------------------------------------------------------------
    # Worker threads (Network, Apply/Undo/Restore, G-code Audit)
    # ------------------------------------------------------------------

    def _worker_fetch_models(self, data: dict[str, Any]) -> None:
        settings = self.storage.get_settings()
        lang = norm_lang(settings.get("language", "ru"))
        provider = str(data.get("provider") or settings.get("provider") or "anthropic")
        model_id = str(data.get("model") or settings.get("model") or "")
        base_url = str(
            data.get("base_url")
            or (settings.get("base_urls") or {}).get(provider)
            or PROVIDER_PRESETS.get(provider, {}).get("base_url")
            or ""
        )
        custom_proto = str(data.get("custom_protocol") or settings.get("custom_protocol") or "openai")

        # Fixes P1 #16: NEVER overwrite api_keys[provider] when the effective key
        # came from model_api_keys instead of an explicit provider-level key.
        explicit_api_key = str(data.get("api_key") or "").strip()
        key_source = str(data.get("key_source") or "").strip().lower()
        model_keys = settings.get("model_api_keys") if isinstance(settings.get("model_api_keys"), dict) else {}
        provider_keys = settings.get("api_keys") if isinstance(settings.get("api_keys"), dict) else {}
        existing_model_key = str(
            model_keys.get(f"{provider}::{model_id}") or model_keys.get(model_id) or ""
        ).strip()
        existing_provider_key = str(provider_keys.get(provider) or "").strip()

        if explicit_api_key:
            effective_key = explicit_api_key
            came_from_model_key = (
                key_source == "model"
                or (
                    bool(existing_model_key)
                    and explicit_api_key == existing_model_key
                    and explicit_api_key != existing_provider_key
                )
            )
            should_save_provider_key = not came_from_model_key
        else:
            effective_key = self.storage.resolve_effective_api_key(provider, model_id)
            should_save_provider_key = False

        res = fetch_provider_models(provider, base_url, effective_key, custom_proto, lang=lang)
        if res.get("ok"):
            patch: dict[str, Any] = {
                "cached_models": {provider: res["models"]},
                "base_urls": {provider: base_url},
            }
            if should_save_provider_key and explicit_api_key:
                patch["api_keys"] = {provider: explicit_api_key}
            updated = self.storage.update_settings(patch)
            self.emit({
                "type": "models_loaded",
                "ok": True,
                "provider": provider,
                "count": res.get("count", 0),
                "models": res.get("models", []),
                "settings": updated,
            })
        else:
            self.emit({
                "type": "models_loaded",
                "ok": False,
                "provider": provider,
                "needs_key": bool(res.get("needs_key")),
                "error": res.get("error", "Error"),
            })

    def _worker_send_chat(
        self,
        data: dict[str, Any],
        plate: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
        request_id: str,
    ) -> None:
        user_text = str(data.get("text") or "").strip()
        if not user_text:
            return

        settings = self.storage.get_settings()
        lang = norm_lang(settings.get("language", "ru"))
        provider = str(data.get("provider") or settings.get("provider") or "anthropic")
        model_id = str(
            data.get("model")
            or settings.get("model")
            or PROVIDER_PRESETS.get(provider, {}).get("default_model")
            or ""
        )
        attach_ctx = bool(data.get("attach_context", settings.get("auto_attach_context", True)))
        compact_ctx = bool(data.get("compact_context", settings.get("compact_context", True)))
        include_gcode = bool(
            data.get("include_gcode", settings.get("include_custom_gcode", False))
            or _mentions_custom_gcode(user_text)
        )
        reasoning_effort = str(data.get("reasoning_effort") or settings.get("reasoning_effort") or "low")
        image_att = data.get("image") if isinstance(data.get("image"), dict) else None

        settings = self.storage.update_settings({
            "provider": provider,
            "model": model_id,
            "reasoning_effort": reasoning_effort,
        })

        # Resolve and lock target_chat_id BEFORE streaming starts (fixes P0 #2)
        chats_snapshot = self.storage.get_chats()
        target_chat_id = str(data.get("chat_id") or chats_snapshot.get("active_id") or "")
        if not target_chat_id or not any(s.get("id") == target_chat_id for s in chats_snapshot.get("sessions", [])):
            target_chat_id, _ = self.storage.create_chat(
                tr(lang, "Новый диалог", "Новий діалог", "New Chat")
            )

        cancel_token = self._register_request(request_id, target_chat_id)

        try:
            user_extra: dict[str, Any] = {}
            if image_att:
                user_extra["has_image"] = True
                if image_att.get("name"):
                    user_extra["image_name"] = str(image_att.get("name"))
                if image_att.get("mime"):
                    user_extra["image_mime"] = str(image_att.get("mime"))

            chats = self.storage.append_message(
                target_chat_id,
                "user",
                user_text,
                extra=user_extra or None,
            )
            # Fixes P0 #1: carry active_request_id so frontend keeps busy=true & Stop active
            self._emit_chats_updated(
                chats,
                active_request_id=request_id,
                active_stream_chat_id=target_chat_id,
            )

            base_sys_prompt = get_system_prompt(lang)
            if attach_ctx:
                with self._lock:
                    last_slice = self._last_slice
                ctx_md = build_context_markdown(
                    plate,
                    presets,
                    custom_instructions=str(settings.get("custom_user_instructions") or ""),
                    lang=lang,
                    include_gcode=include_gcode,
                    compact=compact_ctx,
                    last_slice=last_slice,
                    preflight=preflight,
                )
                sys_prompt = f"{base_sys_prompt}\n\n{ctx_md}"
            else:
                sys_prompt = base_sys_prompt

            target_session = next(
                (s for s in chats.get("sessions", []) if s.get("id") == target_chat_id),
                None,
            )
            history_msgs = list((target_session or {}).get("messages", []))[-20:]

            base_url = str(
                (settings.get("base_urls") or {}).get(provider)
                or PROVIDER_PRESETS.get(provider, {}).get("base_url")
                or ""
            )
            api_key = self.storage.resolve_effective_api_key(provider, model_id)

            stream_state = {"text": "", "thinking": ""}

            def _emit_stream_chunk() -> None:
                if cancel_token.is_cancelled():
                    return
                self.emit({
                    "type": "stream_chunk",
                    "request_id": request_id,
                    "chat_id": target_chat_id,
                    "model": model_id,
                    "text": stream_state["text"],
                    "thinking": stream_state["thinking"],
                })

            def _on_chunk(partial_text: str) -> None:
                stream_state["text"] = partial_text
                _emit_stream_chunk()

            def _on_thinking(thinking_text: str) -> None:
                stream_state["thinking"] = thinking_text
                _emit_stream_chunk()

            temp_raw = settings.get("temperature", 0.3)
            temperature = float(0.3 if temp_raw is None else temp_raw)

            resp = send_chat_completion(
                provider=provider,
                base_url=base_url,
                api_key=api_key,
                model_id=model_id,
                messages=history_msgs,
                system_prompt=sys_prompt,
                temperature=temperature,
                max_tokens=int(settings.get("max_tokens", 4096)),
                custom_protocol=str(settings.get("custom_protocol") or "openai"),
                image_attachment=image_att,
                lang=lang,
                reasoning_effort=reasoning_effort,
                on_chunk=_on_chunk,
                on_thinking=_on_thinking,
                cancel_token=cancel_token,
            )

            if resp.get("ok"):
                reply_text = str(resp.get("reply") or "")
                reasoning_text = str(resp.get("reasoning") or stream_state["thinking"] or "")
                usage_raw = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
                in_tok = int(usage_raw.get("input_tokens") or 0)
                out_tok = int(usage_raw.get("output_tokens") or 0)
                usage_summary = self.storage.record_usage(provider, model_id, in_tok, out_tok)

                parsed_settings = extract_suggested_settings(reply_text, presets, lang=lang)
                updated_chats = self.storage.append_message(
                    target_chat_id,
                    "assistant",
                    reply_text,
                    extra={
                        "model": model_id,
                        "reasoning": reasoning_text,
                        "suggestions": parsed_settings["suggestions"],
                        "gcode_changes": parsed_settings["gcode_changes"],
                        "parse_error": parsed_settings["parse_error"],
                        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
                    },
                )
                self._finish_request(request_id)
                self._emit_chats_updated(
                    updated_chats,
                    extra={
                        "plate": plate,
                        "presets": presets,
                        "preflight": preflight,
                        "usage": usage_summary,
                    },
                )

            elif resp.get("cancelled") or cancel_token.is_cancelled():
                partial = str(resp.get("partial_reply") or stream_state["text"] or "").strip()
                stopped_note = tr(
                    lang,
                    "\n\n*(⏹ Генерация остановлена пользователем)*",
                    "\n\n*(⏹ Генерацію зупинено користувачем)*",
                    "\n\n*(⏹ Generation stopped by user)*",
                )
                if partial:
                    parsed_settings = extract_suggested_settings(partial, presets, lang=lang)
                    updated_chats = self.storage.append_message(
                        target_chat_id,
                        "assistant",
                        partial + stopped_note,
                        extra={
                            "model": model_id,
                            "reasoning": stream_state["thinking"],
                            "suggestions": parsed_settings["suggestions"],
                            "gcode_changes": parsed_settings["gcode_changes"],
                            "parse_error": parsed_settings["parse_error"],
                            "cancelled": True,
                        },
                    )
                else:
                    updated_chats = self.storage.get_chats()
                self._finish_request(request_id)
                self._emit_chats_updated(updated_chats)
                self.emit({
                    "type": "toast",
                    "text": tr(
                        lang,
                        "Генерация остановлена.",
                        "Генерацію зупинено.",
                        "Generation stopped.",
                    ),
                })

            else:
                err_title = tr(
                    lang,
                    f"❌ **Ошибка запроса к ИИ ({provider} / {model_id}):**",
                    f"❌ **Помилка запиту до ШІ ({provider} / {model_id}):**",
                    f"❌ **AI Request Error ({provider} / {model_id}):**",
                )
                err_msg = f"{err_title}\n\n{resp.get('error') or 'Unknown error'}"
                updated_chats = self.storage.append_message(
                    target_chat_id,
                    "assistant",
                    err_msg,
                    extra={"model": model_id, "is_error": True},
                )
                self._finish_request(request_id)
                self._emit_chats_updated(updated_chats)

        except Exception as exc:
            err_msg = tr(
                lang,
                f"❌ **Внутренняя ошибка контроллера:**\n\n{exc}",
                f"❌ **Внутрішня помилка контролера:**\n\n{exc}",
                f"❌ **Internal controller error:**\n\n{exc}",
            )
            try:
                updated_chats = self.storage.append_message(
                    target_chat_id,
                    "assistant",
                    err_msg,
                    extra={"model": model_id, "is_error": True},
                )
            except Exception:
                updated_chats = self.storage.get_chats()
            self._finish_request(request_id)
            self._emit_chats_updated(updated_chats)
        finally:
            self._finish_request(request_id)

    def save_snapshot_sync(self, name: str) -> list[dict[str, Any]]:
        lang = self.storage.get_lang()
        clean_name = str(name or "").strip() or dt.datetime.now().strftime("Snapshot %d.%m %H:%M")
        try:
            snap_data = capture_full_preset_snapshot(lang)
        except Exception:
            _, cached_presets, _, _, _ = self._get_cached_snapshots()
            snap_data = copy.deepcopy(cached_presets)
        snapshots = self.storage.save_snapshot(clean_name, snap_data)
        self.emit({
            "type": "snapshots_updated",
            "snapshots": snapshots,
            "toast": tr(
                lang,
                f"Снимок пресетов «{clean_name}» сохранён",
                f"Знімок пресетів «{clean_name}» збережено",
                f"Preset snapshot '{clean_name}' saved",
            ),
        })
        return snapshots

    def apply_changes_sync(
        self,
        changes: list[dict[str, Any]],
        *,
        allow_gcode: bool = False,
        source: str = "chat",
        card_id: str = "",
        notify_host: bool = False,
    ) -> dict[str, Any]:
        lang = self.storage.get_lang()
        if not isinstance(changes, list) or not changes:
            result = {
                "type": "settings_applied",
                "ok": False,
                "card_id": card_id,
                "applied": [],
                "errors": [
                    tr(
                        lang,
                        "Нет параметров для применения.",
                        "Немає параметрів для застосування.",
                        "No settings provided to apply.",
                    )
                ],
                "warnings": [],
                "apply_history": self.storage.get_apply_history(),
            }
            self.emit(result)
            return result

        # Safety gate: Custom G-code requires explicit confirmation
        gcode_keys_in_batch = [
            str(ch.get("key") or "")
            for ch in changes
            if isinstance(ch, dict) and str(ch.get("key") or "") in CUSTOM_GCODE_KEYS
        ]
        if gcode_keys_in_batch and not allow_gcode:
            err = tr(
                lang,
                f"Изменение пользовательского G-code ({', '.join(gcode_keys_in_batch)}) требует явного подтверждения diff!",
                f"Зміна користувацького G-code ({', '.join(gcode_keys_in_batch)}) потребує явного підтвердження diff!",
                f"Modifying custom G-code ({', '.join(gcode_keys_in_batch)}) requires explicit diff confirmation!",
            )
            result = {
                "type": "settings_applied",
                "ok": False,
                "card_id": card_id,
                "applied": [],
                "errors": [err],
                "warnings": [],
                "gcode_confirmation_required": True,
                "apply_history": self.storage.get_apply_history(),
            }
            self.emit(result)
            return result

        # Record baseline slice before modifying presets so next slice computes delta
        with self._lock:
            if self._last_slice is not None:
                self._baseline_slice = copy.deepcopy(self._last_slice)
                self._slice_delta = None

        res = apply_settings_to_orcaslicer(changes, lang=lang)
        applied = res.get("applied") if isinstance(res.get("applied"), list) else []
        rollback_changes = res.get("rollback_changes") if isinstance(res.get("rollback_changes"), list) else []

        record_id = ""
        if applied:
            now_str = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record_id = f"apply_{int(time.time() * 1000)}"
            record = {
                "id": record_id,
                "timestamp": now_str,
                "created_at": now_str,
                "source": source,
                "applied": applied,
                "rollback_changes": rollback_changes,
            }
            apply_history = self.storage.push_apply_record(record)
        else:
            apply_history = self.storage.get_apply_history()

        presets, preflight = self._refresh_presets_and_preflight_after_apply(applied, lang)

        payload = {
            "type": "settings_applied",
            "ok": bool(res.get("ok")),
            "card_id": card_id,
            "applied": applied,
            "errors": res.get("errors", []),
            "warnings": res.get("warnings", []),
            "record_id": record_id,
            "apply_history": apply_history,
            "presets": presets,
            "preflight": preflight,
        }
        self.emit(payload)

        if notify_host and applied:
            preview = ", ".join(str(a.get("key") or "") for a in applied[:3] if a.get("key"))
            if len(applied) > 3:
                preview += f" (+{len(applied) - 3})"
            msg = tr(
                lang,
                f"Orca AI MCP применил {len(applied)} парам. ({preview}). Доступен откат Undo.",
                f"Orca AI MCP застосував {len(applied)} парам. ({preview}). Доступний відкат Undo.",
                f"Orca AI MCP applied {len(applied)} setting(s) ({preview}). Reversible via Undo.",
            )
            self.push_native_notification(
                msg,
                level="info",
                link_text=tr(lang, "Открыть Orca AI", "Відкрити Orca AI", "Open Orca AI"),
                on_click=self.open_dock_panel,
            )

        return payload

    def _worker_apply_settings(
        self,
        changes: list[dict[str, Any]],
        allow_gcode: bool = False,
        source: str = "chat",
        card_id: str = "",
    ) -> None:
        self.apply_changes_sync(
            changes,
            allow_gcode=allow_gcode,
            source=source,
            card_id=card_id,
            notify_host=False,
        )

    def undo_apply_sync(
        self,
        record_id: str | None = None,
        *,
        chat_id: str | None = None,
        notify_host: bool = False,
    ) -> dict[str, Any]:
        lang = self.storage.get_lang()
        record = self.storage.pop_apply_record(record_id)
        if not record:
            msg = tr(
                lang,
                "История применений пуста — нечего отменять.",
                "Історія застосувань порожня — нічого скасовувати.",
                "Apply history is empty — nothing to undo.",
            )
            if chat_id:
                chats = self.storage.append_message(chat_id, "assistant", msg, extra={"model": "local"})
                self._emit_chats_updated(chats, active_request_id="")
            self.emit({"type": "toast", "text": msg, "is_error": True})
            return {"ok": False, "applied": [], "errors": [msg], "warnings": []}

        rollback = record.get("rollback_changes") or []
        if not rollback:
            msg = tr(
                lang,
                "В записи отката отсутствуют исходные значения.",
                "У записі відкату відсутні вихідні значення.",
                "Rollback record contains no previous values to restore.",
            )
            if chat_id:
                chats = self.storage.append_message(chat_id, "assistant", msg, extra={"model": "local"})
                self._emit_chats_updated(chats, active_request_id="")
            self.emit({"type": "toast", "text": msg, "is_error": True})
            return {"ok": False, "applied": [], "errors": [msg], "warnings": []}

        res = apply_settings_to_orcaslicer(rollback, lang=lang)
        applied = res.get("applied") if isinstance(res.get("applied"), list) else []
        if not res.get("ok") and not applied:
            self.storage.push_apply_record(record)

        presets, preflight = self._refresh_presets_and_preflight_after_apply(applied, lang)
        apply_history = self.storage.get_apply_history()

        payload = {
            "type": "settings_applied",
            "ok": bool(res.get("ok")),
            "undone": True,
            "record_id": record.get("id", ""),
            "applied": applied,
            "errors": res.get("errors", []),
            "warnings": res.get("warnings", []),
            "apply_history": apply_history,
            "presets": presets,
            "preflight": preflight,
        }
        self.emit(payload)

        if notify_host and applied:
            msg = tr(
                lang,
                f"Orca AI MCP откатил изменения ({len(applied)} парам.).",
                f"Orca AI MCP відкотив зміни ({len(applied)} парам.).",
                f"Orca AI MCP reverted {len(applied)} setting(s).",
            )
            self.push_native_notification(msg, level="info")

        if chat_id:
            if res.get("ok"):
                summary_txt = tr(
                    lang,
                    f"↩ Откат выполнен: восстановлено параметров — **{len(applied)}**.",
                    f"↩ Відкат виконано: відновлено параметрів — **{len(applied)}**.",
                    f"↩ Undo complete: restored **{len(applied)}** setting(s).",
                )
            else:
                summary_txt = tr(
                    lang,
                    f"⚠️ Откат выполнен с ошибками: {'; '.join(res.get('errors', []))}",
                    f"⚠️ Відкат виконано з помилками: {'; '.join(res.get('errors', []))}",
                    f"⚠️ Undo finished with errors: {'; '.join(res.get('errors', []))}",
                )
            chats = self.storage.append_message(chat_id, "assistant", summary_txt, extra={"model": "local"})
            self._emit_chats_updated(chats, active_request_id="")

        return payload

    def _worker_undo_apply(
        self,
        record_id: str | None = None,
        chat_id: str | None = None,
    ) -> None:
        self.undo_apply_sync(record_id, chat_id=chat_id, notify_host=False)

    def restore_snapshot_sync(self, snap_id: str, *, notify_host: bool = False) -> dict[str, Any]:
        lang = self.storage.get_lang()
        snapshots = self.storage.get_snapshots()
        target = next((s for s in snapshots if s.get("id") == snap_id), None)
        if not target:
            err = tr(lang, "Снимок пресетов не найден.", "Знімок пресетів не знайдено.", "Preset snapshot not found.")
            self.emit({"type": "toast", "text": err, "is_error": True})
            return {"ok": False, "applied": [], "errors": [err], "warnings": []}

        snap_data = target.get("data") if isinstance(target.get("data"), dict) else {}
        changes = self._snapshot_data_to_changes(snap_data)
        if not changes:
            err = tr(
                lang,
                "Снимок не содержит параметров для восстановления.",
                "Знімок не містить параметрів для відновлення.",
                "Snapshot contains no settings to restore.",
            )
            self.emit({"type": "toast", "text": err, "is_error": True})
            return {"ok": False, "applied": [], "errors": [err], "warnings": []}

        return self.apply_changes_sync(
            changes,
            allow_gcode=True,
            source=f"snapshot:{target.get('name', snap_id)}",
            notify_host=notify_host,
        )

    def _worker_restore_snapshot(self, snap_id: str) -> None:
        self.restore_snapshot_sync(snap_id, notify_host=False)

    @staticmethod
    def _snapshot_data_to_changes(snap_data: dict[str, Any]) -> list[dict[str, Any]]:
        """Convert a captured preset snapshot dict into an apply-ready changes list."""
        if isinstance(snap_data.get("changes"), list):
            return [c for c in snap_data["changes"] if isinstance(c, dict) and c.get("key")]

        changes: list[dict[str, Any]] = []
        seen: set[tuple[str, str, int]] = set()

        def _add(cat: str, key: str, val: Any, slot: int = 1) -> None:
            if not key or val is None:
                return
            sig = (cat, key, slot)
            if sig in seen:
                return
            seen.add(sig)
            changes.append({"category": cat, "key": key, "value": str(val), "slot": slot})

        # Structured categories dict (process / printer / filaments)
        for cat in ("process", "printer"):
            cat_map = snap_data.get(cat)
            if isinstance(cat_map, dict):
                for k, v in cat_map.items():
                    _add(cat, str(k), v, 1)

        filaments_list = snap_data.get("filaments") or snap_data.get("filament_slots")
        if isinstance(filaments_list, list):
            for idx, entry in enumerate(filaments_list, start=1):
                if not isinstance(entry, dict):
                    continue
                slot_num = int(entry.get("slot") or idx)
                values_map = entry.get("values") if isinstance(entry.get("values"), dict) else entry
                for k, v in values_map.items():
                    if k in ("slot", "name", "type", "vendor", "values"):
                        continue
                    _add("filament", str(k), v, slot_num)

        # Fallback: groups structure from inspect_slicer_presets()
        groups = snap_data.get("groups")
        if not changes and isinstance(groups, dict):
            for grp_items in groups.values():
                if not isinstance(grp_items, list):
                    continue
                for item in grp_items:
                    if isinstance(item, dict) and item.get("key") and item.get("value") not in (None, "—"):
                        _add(
                            str(item.get("category") or "process"),
                            str(item["key"]),
                            item["value"],
                            int(item.get("slot") or 1),
                        )

        return changes

    def _refresh_presets_and_preflight_after_apply(
        self,
        applied: list[dict[str, Any]],
        lang: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        refreshed_presets: dict[str, Any] | None = None
        try:
            refreshed_presets = inspect_slicer_presets(lang, include_gcode=True)
        except Exception:
            refreshed_presets = None

        with self._lock:
            if refreshed_presets is not None:
                self._last_presets_snapshot = refreshed_presets
            else:
                presets = self._last_presets_snapshot
                flat = presets.setdefault("flat_values", {})
                for item in applied:
                    k = item.get("key")
                    v = item.get("value")
                    if not k:
                        continue
                    if k in CUSTOM_GCODE_KEYS:
                        presets.setdefault("custom_gcode", {})[k] = v
                    else:
                        flat[k] = v
                        for grp_items in (presets.get("groups") or {}).values():
                            if isinstance(grp_items, list):
                                for g_it in grp_items:
                                    if isinstance(g_it, dict) and g_it.get("key") == k:
                                        g_it["value"] = v
            plate = self._last_plate_snapshot
            presets_cur = self._last_presets_snapshot
            last_slice = self._last_slice

        try:
            preflight = run_preflight_checks(plate, presets_cur, last_slice=last_slice, lang=lang)
        except Exception:
            with self._lock:
                preflight = self._last_preflight

        with self._lock:
            self._last_preflight = preflight

        return presets_cur, preflight

    # ------------------------------------------------------------------
    # G-code audit helpers
    # ------------------------------------------------------------------

    def _format_slice_audit_prompt(
        self,
        summary: dict[str, Any],
        delta: dict[str, Any] | None,
        lang: str,
    ) -> str:
        fname = summary.get("filename", "sliced.gcode")
        size_mb = summary.get("size_mb", 0)
        layers = summary.get("layer_count", 0)
        max_z = summary.get("max_z", 0)
        est_time = summary.get("estimated_time_str") or summary.get("print_time") or "—"
        total_g = summary.get("total_filament_g", summary.get("filament_g", "—"))
        flush_g = summary.get("flush_g", 0)
        tower_g = summary.get("tower_g", 0)
        m104 = ", ".join(str(x) for x in summary.get("m104_temps", [])) or "—"
        m140 = ", ".join(str(x) for x in summary.get("m140_temps", [])) or "—"
        has_pause = bool(summary.get("has_m600_pause"))
        headers = "\n".join(summary.get("header_comments", [])[:30])
        footers = "\n".join(summary.get("footer_comments", [])[-40:])
        delta_line = ""
        if isinstance(delta, dict) and delta.get("summary"):
            delta_line = f"\n- Before/After Delta: {delta['summary']}"

        if lang == "uk":
            return (
                f"Проведи технічний аудит нарізаного G-code файлу `{fname}` ({size_mb} МБ).\n"
                f"- Орієнтовний час друку: {est_time}, загальна витрата: {total_g} г (промивка: {flush_g} г, вежа: {tower_g} г){delta_line}\n"
                f"- Шарів: {layers}, макс. висота Z: {max_z} мм\n"
                f"- Температури сопла (M104/M109): {m104} °C\n"
                f"- Температури столу (M140/M190): {m140} °C\n"
                f"- Паузи M600/M25: {'Так' if has_pause else 'Ні'}\n"
                f"- Коментарі заголовка:\n```text\n{headers}\n```\n"
                f"- Зведення слайсера в кінці файлу:\n```text\n{footers}\n```\n"
                "Оціни час друку, витрату пластику/відходів, коректність температур і запропонуй покращення в блоці ```orca-settings."
            )
        if lang == "en":
            return (
                f"Perform a technical audit of the sliced G-code file `{fname}` ({size_mb} MB).\n"
                f"- Estimated print time: {est_time}, total filament: {total_g} g (flush: {flush_g} g, tower: {tower_g} g){delta_line}\n"
                f"- Layers: {layers}, max Z height: {max_z} mm\n"
                f"- Nozzle temperatures (M104/M109): {m104} °C\n"
                f"- Bed temperatures (M140/M190): {m140} °C\n"
                f"- M600/M25 pauses present: {'Yes' if has_pause else 'No'}\n"
                f"- Header comments:\n```text\n{headers}\n```\n"
                f"- Footer slicer summary:\n```text\n{footers}\n```\n"
                "Evaluate print time, filament/purge usage, temperature consistency, and suggest improvements in an ```orca-settings block."
            )
        return (
            f"Проведи технический аудит нарезанного G-code файла `{fname}` ({size_mb} МБ).\n"
            f"- Ориентировочное время печати: {est_time}, общий расход: {total_g} г (промывка: {flush_g} г, башня: {tower_g} г){delta_line}\n"
            f"- Слоёв: {layers}, макс. высота Z: {max_z} мм\n"
            f"- Температуры сопла (M104/M109): {m104} °C\n"
            f"- Температуры стола (M140/M190): {m140} °C\n"
            f"- Паузы M600/M25: {'Да' if has_pause else 'Нет'}\n"
            f"- Комментарии заголовка:\n```text\n{headers}\n```\n"
            f"- Сводка слайсера в конце файла:\n```text\n{footers}\n```\n"
            "Оцени время печати, расход пластика/отходов, корректность температур и предложи улучшения в блоке ```orca-settings."
        )

    def _worker_audit_gcode_text(
        self,
        filename: str,
        gcode_text: str,
        data: dict[str, Any],
        plate: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
    ) -> None:
        lang = self.storage.get_lang()
        summary = summarize_gcode_text(gcode_text, filename)
        with self._lock:
            delta = compute_slice_delta(self._baseline_slice, summary) if self._baseline_slice else None
            self._last_slice = summary
            self._slice_delta = delta
        req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
        prompt = self._format_slice_audit_prompt(summary, delta, lang)
        chat_data = dict(data)
        chat_data["text"] = prompt
        chat_data["attach_context"] = True
        chat_data["request_id"] = req_id
        self._worker_send_chat(chat_data, plate, presets, preflight, req_id)

    def _worker_audit_gcode_path(
        self,
        gcode_path: str,
        data: dict[str, Any],
        plate: dict[str, Any],
        presets: dict[str, Any],
        preflight: dict[str, Any],
    ) -> None:
        lang = self.storage.get_lang()
        summary = summarize_gcode_file(gcode_path)
        with self._lock:
            delta = compute_slice_delta(self._baseline_slice, summary) if self._baseline_slice else None
            self._last_slice = summary
            self._slice_delta = delta
        req_id = str(data.get("request_id") or f"req_{int(time.time() * 1000)}")
        prompt = self._format_slice_audit_prompt(summary, delta, lang)
        chat_data = dict(data)
        chat_data["text"] = prompt
        chat_data["attach_context"] = True
        chat_data["request_id"] = req_id
        self._worker_send_chat(chat_data, plate, presets, preflight, req_id)


CONTROLLER: AssistantController | None = None
_CONTROLLER_LOCK = threading.Lock()


def get_controller() -> AssistantController:
    """Return the process-wide singleton AssistantController."""
    global CONTROLLER
    if CONTROLLER is None:
        with _CONTROLLER_LOCK:
            if CONTROLLER is None:
                CONTROLLER = AssistantController()
    return CONTROLLER
