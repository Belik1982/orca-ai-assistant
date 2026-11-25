"""Built-in local MCP Server (Streamable HTTP, JSON-RPC 2.0) for OrcaSlicer 2.5+.

Runs purely on the Python standard library inside OrcaSlicer's sandbox with
explicit `network_socket` + `threading` permission grants, reusing the
plugin's `orca_bridge` and `AssistantController` operations.
"""

from __future__ import annotations

import datetime as dt
import hmac
import http.server
import json
import secrets
import threading
import urllib.parse
from collections import deque
from typing import TYPE_CHECKING, Any

from orca_ai_assistant.core.constants import MCP_DEFAULT_HOST, MCP_DEFAULT_PORT, PLUGIN_VERSION
from orca_ai_assistant.orca_bridge.enums import CUSTOM_GCODE_KEYS
from orca_ai_assistant.orca_bridge.gcode_codec import lint_custom_gcode, make_unified_diff
from orca_ai_assistant.orca_bridge.presets import read_live_setting_value
from orca_ai_assistant.orca_bridge.prompts import build_context_markdown

if TYPE_CHECKING:
    from orca_ai_assistant.controller.controller import AssistantController

_SUPPORTED_PROTOCOL_VERSIONS = ("2025-03-26", "2024-11-05")
_MAX_BODY_BYTES = 2 * 1024 * 1024  # 2 MiB
_ALLOWED_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})

_SERVER_INSTRUCTIONS = (
    "You are connected to a live OrcaSlicer 2.5+ instance via Orca AI Assistant MCP.\n"
    "- Read-only inspection tools (`get_scene_info`, `get_presets`, `get_setting`, "
    "`run_preflight_check`, `get_last_slice_report`, `get_custom_gcode`) query live slicer state.\n"
    "- Modify standard settings with `apply_settings` (validated & reversible via `undo_last_apply`).\n"
    "- For Printer/Filament/Layer Custom G-code (`machine_start_gcode`, `machine_end_gcode`, etc.), "
    "ALWAYS inspect first with `get_custom_gcode` and edit via `set_custom_gcode`, which runs a static "
    "safety linter and produces a unified diff.\n"
    "- Note OrcaSlicer 2.5 host API limits: slicing, sending to printer, screenshot capture, and moving "
    "3D plate meshes are not exposed in `orca.host` and still happen in the OrcaSlicer GUI."
)

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_scene_info",
        "description": (
            "Inspect live 3D objects on the active OrcaSlicer build plate: bounding box dimensions (X/Y/Z), "
            "volume (cm3), manifold/mesh error status, first-layer bed contact area (mm2), overhang areas "
            "(>45 deg and >60 deg), height-to-base ratio, AMS extruder slot assignments, and plate warnings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "get_presets",
        "description": (
            "Read active Printer, Process, and all AMS Filament slot presets (Slot 1..N), connected printer "
            "info, unsaved dirty overrides, and flat setting values."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "include_gcode": {
                    "type": "boolean",
                    "description": "Include decoded custom Start/End/Layer/Filament G-code blocks (default: false).",
                    "default": False,
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "get_setting",
        "description": (
            "Read one or multiple live OrcaSlicer setting values by exact key name (e.g. "
            "'sparse_infill_pattern', 'layer_height', 'nozzle_temperature') with optional category and AMS slot."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Single OrcaSlicer setting key."},
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of OrcaSlicer setting keys to read together.",
                },
                "category": {
                    "type": "string",
                    "enum": ["process", "filament", "printer", ""],
                    "description": "Optional preset category override.",
                },
                "slot": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based AMS filament slot number (default: 1).",
                    "default": 1,
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "run_preflight_check",
        "description": (
            "Run deterministic zero-token FDM Pre-Flight checks against live plate geometry, active presets, "
            "AMS slots, and last slice report. Returns health score (0-100) and actionable issues."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "get_last_slice_report",
        "description": (
            "Get metrics from the most recent OrcaSlicer G-code slice (print time, total & per-slot grams, "
            "purge/prime-tower waste, speeds/temps, and Before->After delta if presets were modified)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "apply_settings",
        "description": (
            "Apply validated Process/Filament/Printer setting changes directly to active OrcaSlicer presets. "
            "Automatically records Undo history and pushes a notification inside OrcaSlicer. Custom G-code keys "
            "are rejected here — use `set_custom_gcode` instead."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "changes": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "key": {"type": "string", "description": "OrcaSlicer setting key."},
                            "value": {
                                "type": ["string", "number", "boolean"],
                                "description": "Target value (normalized & enum-validated).",
                            },
                            "category": {
                                "type": "string",
                                "enum": ["process", "filament", "printer"],
                                "description": "Optional category override.",
                            },
                            "slot": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "1-based AMS filament slot (for filament settings).",
                            },
                            "reason": {"type": "string", "description": "Optional human-readable reason."},
                        },
                        "required": ["key", "value"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["changes"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "get_custom_gcode",
        "description": (
            "Read decoded custom G-code blocks (machine_start_gcode, machine_end_gcode, "
            "before_layer_change_gcode, layer_change_gcode, filament_start_gcode, filament_end_gcode, etc.)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Optional specific G-code key filter.",
                },
                "slot": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based AMS slot for filament G-code keys (default: all slots / 1).",
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "idempotentHint": True},
    },
    {
        "name": "set_custom_gcode",
        "description": (
            "Update an OrcaSlicer custom G-code block (Printer, Process, or AMS Filament slot). Runs static "
            "safety lint (G28 homing, heater cooldown, placeholder balance, empty wipe) and returns unified diff "
            "plus Undo record ID. Blocked on danger-level lint findings unless `force=true`."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "enum": sorted(CUSTOM_GCODE_KEYS.keys()),
                    "description": "Custom G-code preset key.",
                },
                "gcode": {
                    "type": "string",
                    "description": "Full replacement G-code text (newline-separated, unescaped).",
                },
                "slot": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "1-based AMS slot for filament_* G-code keys (default: 1).",
                    "default": 1,
                },
                "force": {
                    "type": "boolean",
                    "description": "Apply even if static safety linter reports danger findings (default: false).",
                    "default": False,
                },
            },
            "required": ["key", "gcode"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    {
        "name": "undo_last_apply",
        "description": (
            "Revert the most recent (or specified `record_id`) applied change batch or G-code edit back to its "
            "recorded pre-apply OrcaSlicer values and show a native notification."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "Optional specific apply history record ID; defaults to most recent.",
                },
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "manage_snapshots",
        "description": "List, save, restore, or delete named OrcaSlicer preset snapshots.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "save", "restore", "delete"],
                    "description": "Snapshot operation to perform.",
                },
                "name": {"type": "string", "description": "Snapshot name (used by action='save')."},
                "snapshot_id": {
                    "type": "string",
                    "description": "Snapshot ID (required for action='restore' or 'delete').",
                },
            },
            "required": ["action"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    {
        "name": "show_notification",
        "description": "Display a native notification banner inside the OrcaSlicer desktop window.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "minLength": 1, "description": "Notification text."},
                "level": {
                    "type": "string",
                    "enum": ["info", "warning", "error"],
                    "default": "info",
                    "description": "Notification severity level.",
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
]

_RESOURCE_DEFINITIONS: list[dict[str, Any]] = [
    {
        "uri": "orca://scene/context",
        "name": "OrcaSlicer Live Context",
        "description": "Markdown summary of current 3D build plate geometry, presets, AMS slots, Pre-Flight, and last slice.",
        "mimeType": "text/markdown",
    },
    {
        "uri": "orca://presets/current",
        "name": "Active Slicer Presets",
        "description": "JSON dump of active Printer, Process, and AMS Filament preset settings.",
        "mimeType": "application/json",
    },
    {
        "uri": "orca://preflight/scorecard",
        "name": "Pre-Flight Scorecard",
        "description": "Latest deterministic Pre-Flight health score and FDM print risk checks.",
        "mimeType": "application/json",
    },
    {
        "uri": "orca://gcode/last_slice",
        "name": "Last Slice Report",
        "description": "Metrics and Before->After deltas from the most recent OrcaSlicer slice.",
        "mimeType": "application/json",
    },
]


def _extract_host_only(raw_host: str) -> str:
    host = str(raw_host or "").strip().lower()
    if not host:
        return ""
    if host.startswith("["):
        end = host.find("]")
        return host[1:end] if end != -1 else host
    if ":" in host:
        return host.split(":", 1)[0]
    return host


def _extract_origin_host(raw_origin: str) -> str:
    origin = str(raw_origin or "").strip()
    if not origin:
        return ""
    if origin.lower() == "null":
        return "null"
    try:
        parsed = urllib.parse.urlparse(origin)
        return str(parsed.hostname or "").strip().lower()
    except Exception:
        return "__invalid__"


class _LocalMCPHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        handler_cls: type[http.server.BaseHTTPRequestHandler],
        mcp_owner: OrcaMCPServer,
    ) -> None:
        self.mcp_owner = mcp_owner
        super().__init__(server_address, handler_cls)


class _MCPRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Never spam OrcaSlicer stdout/stderr with HTTP access logs.
        return

    def _send_bytes(
        self,
        status: int,
        body: bytes = b"",
        *,
        content_type: str | None = "application/json; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        if content_type and body:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _send_json(
        self,
        status: int,
        payload: Any,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, raw, content_type="application/json; charset=utf-8", extra_headers=extra_headers)

    def _check_local_headers(self) -> bool:
        raw_host = self.headers.get("Host", "")
        if _extract_host_only(raw_host) not in _ALLOWED_LOCAL_HOSTS:
            self._send_json(403, {"error": "Forbidden: only localhost/127.0.0.1 Host allowed"})
            return False

        raw_origin = self.headers.get("Origin", "")
        if raw_origin:
            origin_host = _extract_origin_host(raw_origin)
            if origin_host not in _ALLOWED_LOCAL_HOSTS:
                self._send_json(403, {"error": "Forbidden: untrusted Origin"})
                return False
        return True

    def _check_auth(self) -> bool:
        owner: OrcaMCPServer = self.server.mcp_owner  # type: ignore[attr-defined]
        settings = owner.controller.storage.get_settings()
        if not settings.get("mcp_require_auth", True):
            return True

        expected = str(settings.get("mcp_token") or "").strip()
        if not expected:
            self._send_json(
                401,
                {"error": "Unauthorized: MCP bearer token not configured"},
                extra_headers={"WWW-Authenticate": 'Bearer realm="orca-mcp"'},
            )
            return False

        auth_header = str(self.headers.get("Authorization") or "").strip()
        presented = ""
        if auth_header.lower().startswith("bearer "):
            presented = auth_header[7:].strip()
        if not presented:
            presented = str(self.headers.get("X-Orca-MCP-Token") or "").strip()

        if not presented or not hmac.compare_digest(presented, expected):
            self._send_json(
                401,
                {"error": "Unauthorized: invalid or missing MCP bearer token"},
                extra_headers={"WWW-Authenticate": 'Bearer realm="orca-mcp"'},
            )
            return False
        return True

    def _path_only(self) -> str:
        return urllib.parse.urlparse(self.path).path

    def do_OPTIONS(self) -> None:  # noqa: N802
        if not self._check_local_headers():
            return
        self._send_bytes(
            204,
            b"",
            content_type=None,
            extra_headers={
                "Allow": "POST, DELETE, OPTIONS",
            },
        )

    def do_GET(self) -> None:  # noqa: N802
        if not self._check_local_headers():
            return
        path = self._path_only()
        if path == "/health":
            owner: OrcaMCPServer = self.server.mcp_owner  # type: ignore[attr-defined]
            self._send_json(
                200,
                {
                    "ok": True,
                    "name": "orca-ai-assistant",
                    "version": PLUGIN_VERSION,
                    "protocol": _SUPPORTED_PROTOCOL_VERSIONS[0],
                    "endpoint": "/mcp",
                    "port": owner.actual_port,
                },
            )
            return
        if path == "/mcp":
            if not self._check_auth():
                return
            self._send_json(
                405,
                {"error": "Method Not Allowed: use POST /mcp for JSON-RPC requests"},
                extra_headers={"Allow": "POST, DELETE, OPTIONS"},
            )
            return
        self._send_json(404, {"error": "Not Found"})

    def do_DELETE(self) -> None:  # noqa: N802
        if not self._check_local_headers():
            return
        if self._path_only() != "/mcp":
            self._send_json(404, {"error": "Not Found"})
            return
        if not self._check_auth():
            return
        self._send_bytes(204, b"", content_type=None)

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_local_headers():
            return
        if self._path_only() != "/mcp":
            self._send_json(404, {"error": "Not Found"})
            return
        if not self._check_auth():
            return

        raw_len = self.headers.get("Content-Length")
        try:
            content_len = int(raw_len) if raw_len is not None else 0
        except (TypeError, ValueError):
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Content-Length"}})
            return

        if content_len <= 0:
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Empty request body"}})
            return
        if content_len > _MAX_BODY_BYTES:
            self._send_json(413, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Payload too large (limit 2 MiB)"}})
            return

        raw_body = self.rfile.read(content_len)
        try:
            decoded = json.loads(raw_body.decode("utf-8"))
        except Exception as exc:
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"Parse error: {exc}"}})
            return

        owner: OrcaMCPServer = self.server.mcp_owner  # type: ignore[attr-defined]
        session_id = str(self.headers.get("Mcp-Session-Id") or owner.session_id)
        resp_headers = {"Mcp-Session-Id": session_id}

        if isinstance(decoded, list):
            if not decoded:
                self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Empty JSON-RPC batch"}}, extra_headers=resp_headers)
                return
            responses = []
            for item in decoded:
                r = owner.handle_jsonrpc(item)
                if r is not None:
                    responses.append(r)
            if not responses:
                self._send_bytes(202, b"", content_type=None, extra_headers=resp_headers)
            else:
                self._send_json(200, responses, extra_headers=resp_headers)
            return

        if not isinstance(decoded, dict):
            self._send_json(400, {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "JSON-RPC payload must be an object or array"}}, extra_headers=resp_headers)
            return

        response = owner.handle_jsonrpc(decoded)
        if response is None:
            self._send_bytes(202, b"", content_type=None, extra_headers=resp_headers)
        else:
            self._send_json(200, response, extra_headers=resp_headers)


class OrcaMCPServer:
    """In-process localhost Streamable HTTP MCP server backed by AssistantController."""

    def __init__(
        self,
        controller: AssistantController,
        host: str = MCP_DEFAULT_HOST,
        port: int = MCP_DEFAULT_PORT,
    ) -> None:
        self.controller = controller
        self.host = MCP_DEFAULT_HOST if str(host or "").strip() not in _ALLOWED_LOCAL_HOSTS else str(host).strip()
        try:
            p = int(port)
            self.requested_port = p if (p == 0 or 1024 <= p <= 65535) else MCP_DEFAULT_PORT
        except (TypeError, ValueError):
            self.requested_port = MCP_DEFAULT_PORT

        self.actual_port: int = self.requested_port
        self.session_id: str = secrets.token_hex(12)
        self._lock = threading.RLock()
        self._httpd: _LocalMCPHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._last_error: str = ""
        self._recent_calls: deque[dict[str, Any]] = deque(maxlen=30)

    @property
    def is_running(self) -> bool:
        with self._lock:
            return (
                self._httpd is not None
                and self._thread is not None
                and self._thread.is_alive()
            )

    @property
    def url(self) -> str:
        port = self.actual_port or self.requested_port or MCP_DEFAULT_PORT
        return f"http://{self.host}:{port}/mcp"

    @property
    def last_error(self) -> str:
        with self._lock:
            return self._last_error

    def start(self) -> bool:
        with self._lock:
            if self.is_running:
                return True
            self._last_error = ""
            try:
                httpd = _LocalMCPHTTPServer((self.host, self.requested_port), _MCPRequestHandler, self)
                self.actual_port = int(httpd.server_address[1])
                thread = threading.Thread(
                    target=httpd.serve_forever,
                    name=f"orca-mcp-{self.actual_port}",
                    daemon=True,
                )
                self._httpd = httpd
                self._thread = thread
                thread.start()
                return True
            except Exception as exc:
                self._last_error = str(exc)
                self._httpd = None
                self._thread = None
                return False

    def stop(self) -> None:
        with self._lock:
            httpd = self._httpd
            thread = self._thread
            self._httpd = None
            self._thread = None

        if httpd is not None:
            try:
                httpd.shutdown()
            except Exception:
                pass
            try:
                httpd.server_close()
            except Exception:
                pass
        if thread is not None and thread.is_alive():
            try:
                thread.join(timeout=2.0)
            except Exception:
                pass

    def get_recent_calls(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._recent_calls)

    def _record_call(self, method: str, tool: str, ok: bool, summary: str) -> None:
        with self._lock:
            self._recent_calls.appendleft({
                "time": dt.datetime.now().strftime("%H:%M:%S"),
                "method": method,
                "tool": tool,
                "ok": bool(ok),
                "summary": str(summary or "")[:160],
            })

    def get_status(self) -> dict[str, Any]:
        settings = self.controller.storage.get_settings()
        port = self.actual_port if self.is_running else int(settings.get("mcp_port") or MCP_DEFAULT_PORT)
        return {
            "running": self.is_running,
            "enabled": bool(settings.get("mcp_enabled", False)),
            "host": self.host,
            "port": port,
            "url": f"http://{self.host}:{port}/mcp",
            "health_url": f"http://{self.host}:{port}/health",
            "require_auth": bool(settings.get("mcp_require_auth", True)),
            "token": str(settings.get("mcp_token") or ""),
            "allow_write": bool(settings.get("mcp_allow_write", True)),
            "allow_gcode_write": bool(settings.get("mcp_allow_gcode_write", True)),
            "error": self.last_error,
            "recent_calls": self.get_recent_calls(),
        }

    # ------------------------------------------------------------------
    # JSON-RPC 2.0 & MCP Dispatch
    # ------------------------------------------------------------------

    @staticmethod
    def _rpc_ok(req_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _rpc_err(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
        err: dict[str, Any] = {"code": code, "message": str(message)}
        if data is not None:
            err["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": err}

    def handle_jsonrpc(self, msg: Any) -> dict[str, Any] | None:
        if not isinstance(msg, dict):
            return self._rpc_err(None, -32600, "Invalid Request: expected JSON object")

        has_id = "id" in msg
        req_id = msg.get("id")
        if msg.get("jsonrpc") != "2.0":
            return self._rpc_err(req_id if has_id else None, -32600, "Invalid Request: jsonrpc must be '2.0'")

        method = msg.get("method")
        if not isinstance(method, str) or not method:
            return self._rpc_err(req_id if has_id else None, -32600, "Invalid Request: missing method")

        params = msg.get("params")
        if params is None:
            params = {}
        elif not isinstance(params, dict):
            return self._rpc_err(req_id if has_id else None, -32602, "Invalid params: expected object")

        # Notifications have no `id` field -> do not produce a JSON-RPC response body.
        if not has_id or method.startswith("notifications/"):
            if method == "notifications/initialized":
                self._record_call("notifications/initialized", "", True, "Client initialized session")
            return None if not has_id else self._rpc_ok(req_id, {})

        if method == "initialize":
            client_proto = str(params.get("protocolVersion") or "").strip()
            negotiated = (
                client_proto
                if client_proto in _SUPPORTED_PROTOCOL_VERSIONS
                else _SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            client_info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
            client_name = str(client_info.get("name") or "MCP client")
            self._record_call("initialize", "", True, f"{client_name} ({negotiated})")
            return self._rpc_ok(
                req_id,
                {
                    "protocolVersion": negotiated,
                    "capabilities": {
                        "tools": {"listChanged": False},
                        "resources": {"subscribe": False, "listChanged": False},
                    },
                    "serverInfo": {
                        "name": "orca-ai-assistant",
                        "title": "Orca AI Assistant",
                        "version": PLUGIN_VERSION,
                    },
                    "instructions": _SERVER_INSTRUCTIONS,
                },
            )

        if method == "ping":
            return self._rpc_ok(req_id, {})

        if method == "tools/list":
            return self._rpc_ok(req_id, {"tools": _TOOL_DEFINITIONS})

        if method == "tools/call":
            return self._handle_tool_call(req_id, params)

        if method == "resources/list":
            return self._rpc_ok(req_id, {"resources": _RESOURCE_DEFINITIONS})

        if method == "resources/read":
            return self._handle_resource_read(req_id, params)

        if method in ("prompts/list",):
            return self._rpc_ok(req_id, {"prompts": []})

        return self._rpc_err(req_id, -32601, f"Method not found: {method}")

    def _handle_tool_call(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = str(params.get("name") or "").strip()
        if not tool_name:
            return self._rpc_err(req_id, -32602, "Invalid params: missing tool name")

        args = params.get("arguments")
        if args is None:
            args = {}
        elif not isinstance(args, dict):
            return self._rpc_err(req_id, -32602, "Invalid params: tool arguments must be an object")

        known_names = {t["name"] for t in _TOOL_DEFINITIONS}
        if tool_name not in known_names:
            return self._rpc_err(req_id, -32602, f"Unknown tool: {tool_name}")

        try:
            result, is_error, summary = self._execute_tool(tool_name, args)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            is_error = True
            summary = f"Exception: {exc}"

        self._record_call("tools/call", tool_name, not is_error, summary)
        text = json.dumps(result, ensure_ascii=False, indent=2)
        payload: dict[str, Any] = {
            "content": [{"type": "text", "text": text}],
            "isError": bool(is_error),
        }
        if isinstance(result, dict):
            payload["structuredContent"] = result
        return self._rpc_ok(req_id, payload)

    def _handle_resource_read(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        uri = str(params.get("uri") or "").strip()
        if not uri:
            return self._rpc_err(req_id, -32602, "Invalid params: missing resource uri")

        lang = self.controller.storage.get_lang()
        settings = self.controller.storage.get_settings()

        if uri == "orca://scene/context":
            plate, presets, preflight = self.controller.capture_ui_snapshots(force=True)
            _, _, _, last_slice, _ = self.controller._get_cached_snapshots()
            md = build_context_markdown(
                plate,
                presets,
                custom_instructions=str(settings.get("custom_user_instructions") or ""),
                lang=lang,
                include_gcode=bool(settings.get("include_custom_gcode", False)),
                compact=False,
                last_slice=last_slice,
                preflight=preflight,
            )
            self._record_call("resources/read", uri, True, "Read scene context markdown")
            return self._rpc_ok(req_id, {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": md}]})

        if uri == "orca://presets/current":
            _, presets, _ = self.controller.capture_ui_snapshots(force=True, include_geometry=False)
            self._record_call("resources/read", uri, True, "Read current presets JSON")
            return self._rpc_ok(
                req_id,
                {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(presets, ensure_ascii=False, indent=2)}]},
            )

        if uri == "orca://preflight/scorecard":
            _, _, preflight = self.controller.capture_ui_snapshots(force=True)
            self._record_call("resources/read", uri, True, f"Score {preflight.get('score', 100)}/100")
            return self._rpc_ok(
                req_id,
                {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(preflight, ensure_ascii=False, indent=2)}]},
            )

        if uri == "orca://gcode/last_slice":
            _, _, _, last_slice, slice_delta = self.controller._get_cached_snapshots()
            payload = {"last_slice": last_slice, "slice_delta": slice_delta}
            self._record_call("resources/read", uri, True, "Read last slice report")
            return self._rpc_ok(
                req_id,
                {"contents": [{"uri": uri, "mimeType": "application/json", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]},
            )

        return self._rpc_err(req_id, -32602, f"Unknown resource URI: {uri}")

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    def _execute_tool(self, name: str, args: dict[str, Any]) -> tuple[dict[str, Any], bool, str]:
        settings = self.controller.storage.get_settings()

        if name == "get_scene_info":
            plate, _, _ = self.controller.capture_ui_snapshots(force=True, include_geometry=True, include_presets=False)
            objs = plate.get("objects") or []
            return plate, False, f"{len(objs)} object(s)"

        if name == "get_presets":
            include_gcode = bool(args.get("include_gcode", False))
            _, presets, _ = self.controller.capture_ui_snapshots(force=True, include_geometry=False, include_presets=True)
            out = dict(presets)
            if not include_gcode:
                out.pop("custom_gcode", None)
                slots = []
                for s in out.get("filament_slots") or []:
                    if isinstance(s, dict):
                        sc = dict(s)
                        sc.pop("start_gcode", None)
                        sc.pop("end_gcode", None)
                        slots.append(sc)
                out["filament_slots"] = slots
            return out, False, f"Process={out.get('process_name', '—')}, Slots={len(out.get('filament_slots') or [])}"

        if name == "get_setting":
            category = str(args.get("category") or "").strip()
            try:
                slot = max(1, int(args.get("slot") or 1))
            except (TypeError, ValueError):
                slot = 1

            keys: list[str] = []
            if args.get("key"):
                keys.append(str(args["key"]).strip())
            if isinstance(args.get("keys"), list):
                for k in args["keys"]:
                    ks = str(k or "").strip()
                    if ks and ks not in keys:
                        keys.append(ks)

            if not keys:
                return {"ok": False, "error": "Provide 'key' or non-empty 'keys' array."}, True, "Missing key"

            values = {k: read_live_setting_value(k, category=category, slot=slot) for k in keys}
            return {"ok": True, "slot": slot, "values": values}, False, f"Read {len(keys)} key(s)"

        if name == "run_preflight_check":
            _, _, preflight = self.controller.capture_ui_snapshots(force=True, include_geometry=True, include_presets=True)
            return preflight, False, f"Score {preflight.get('score', 0)}/100"

        if name == "get_last_slice_report":
            _, _, _, last_slice, slice_delta = self.controller._get_cached_snapshots()
            if not last_slice:
                return {
                    "ok": False,
                    "has_slice": False,
                    "message": "No slice report captured yet in this session. Slice a plate in OrcaSlicer first.",
                }, False, "No slice yet"
            return {"ok": True, "has_slice": True, "last_slice": last_slice, "slice_delta": slice_delta}, False, str(last_slice.get("filename") or "sliced")

        if name == "apply_settings":
            if not settings.get("mcp_allow_write", True):
                return {"ok": False, "error": "Write access is disabled in Orca AI Assistant MCP settings (Read-Only mode)."}, True, "Blocked (read-only)"

            changes = args.get("changes")
            if not isinstance(changes, list) or not changes:
                return {"ok": False, "error": "'changes' must be a non-empty list."}, True, "Empty changes"

            gcode_keys = [
                str(ch.get("key") or "")
                for ch in changes
                if isinstance(ch, dict) and str(ch.get("key") or "") in CUSTOM_GCODE_KEYS
            ]
            if gcode_keys:
                return {
                    "ok": False,
                    "error": f"Custom G-code key(s) ({', '.join(gcode_keys)}) cannot be modified via apply_settings; use set_custom_gcode instead.",
                }, True, "Rejected custom G-code key"

            normalized_changes: list[dict[str, Any]] = []
            for ch in changes:
                if not isinstance(ch, dict) or not ch.get("key"):
                    continue
                val = ch.get("value")
                if isinstance(val, bool):
                    val_str = "1" if val else "0"
                else:
                    val_str = str(val)
                item: dict[str, Any] = {"key": str(ch["key"]).strip(), "value": val_str}
                if ch.get("category"):
                    item["category"] = str(ch["category"]).strip()
                if ch.get("slot") is not None:
                    item["slot"] = ch["slot"]
                if ch.get("reason"):
                    item["reason"] = str(ch["reason"])
                normalized_changes.append(item)

            if not normalized_changes:
                return {"ok": False, "error": "No valid setting change objects supplied."}, True, "No valid changes"

            res = self.controller.apply_changes_sync(
                normalized_changes,
                allow_gcode=False,
                source="mcp",
                notify_host=True,
            )
            ok = bool(res.get("ok"))
            applied_cnt = len(res.get("applied") or [])
            return {
                "ok": ok,
                "record_id": res.get("record_id", ""),
                "applied": res.get("applied", []),
                "errors": res.get("errors", []),
                "warnings": res.get("warnings", []),
                "preflight": res.get("preflight"),
            }, not ok, f"Applied {applied_cnt}, err {len(res.get('errors') or [])}"

        if name == "get_custom_gcode":
            key_filter = str(args.get("key") or "").strip()
            slot_arg = args.get("slot")
            if key_filter and key_filter not in CUSTOM_GCODE_KEYS:
                return {"ok": False, "error": f"Unknown custom G-code key: {key_filter}"}, True, "Unknown G-code key"

            _, presets, _ = self.controller.capture_ui_snapshots(force=True, include_geometry=False, include_presets=True)
            cg = presets.get("custom_gcode") if isinstance(presets.get("custom_gcode"), dict) else {}
            slots = presets.get("filament_slots") if isinstance(presets.get("filament_slots"), list) else []

            if key_filter:
                meta = CUSTOM_GCODE_KEYS[key_filter]
                if meta.get("category") == "filament":
                    slot_num = max(1, int(slot_arg or 1))
                    val = read_live_setting_value(key_filter, category="filament", slot=slot_num)
                    return {"ok": True, "key": key_filter, "slot": slot_num, "gcode": val}, False, f"{key_filter} (slot {slot_num})"
                val = str(cg.get(key_filter) if key_filter in cg else read_live_setting_value(key_filter))
                return {"ok": True, "key": key_filter, "gcode": val}, False, key_filter

            filament_blocks: list[dict[str, Any]] = []
            for s in slots:
                if not isinstance(s, dict):
                    continue
                s_num = int(s.get("slot") or 1)
                if slot_arg is not None and s_num != int(slot_arg):
                    continue
                filament_blocks.append({
                    "slot": s_num,
                    "name": s.get("name", ""),
                    "filament_start_gcode": s.get("start_gcode", ""),
                    "filament_end_gcode": s.get("end_gcode", ""),
                })
            return {
                "ok": True,
                "custom_gcode": cg,
                "filament_slots": filament_blocks,
            }, False, "Read all custom G-code"

        if name == "set_custom_gcode":
            if not settings.get("mcp_allow_write", True):
                return {"ok": False, "error": "Write access is disabled in Orca AI Assistant MCP settings (Read-Only mode)."}, True, "Blocked (read-only)"
            if not settings.get("mcp_allow_gcode_write", True):
                return {"ok": False, "error": "Custom G-code editing via MCP is disabled in Orca AI Assistant settings."}, True, "Blocked (gcode write off)"

            key = str(args.get("key") or "").strip()
            if key not in CUSTOM_GCODE_KEYS:
                return {"ok": False, "error": f"Invalid custom G-code key '{key}'."}, True, "Invalid G-code key"

            gcode_text = "" if args.get("gcode") is None else str(args.get("gcode"))
            try:
                slot = max(1, int(args.get("slot") or 1))
            except (TypeError, ValueError):
                slot = 1
            force = bool(args.get("force", False))

            cat = CUSTOM_GCODE_KEYS[key]["category"]
            old_text = read_live_setting_value(key, category=cat, slot=slot)
            diff_text = make_unified_diff(old_text, gcode_text, label=key)
            lint_issues = lint_custom_gcode(key, gcode_text, lang=self.controller.storage.get_lang(), old_text=old_text)
            danger_issues = [it for it in lint_issues if it.get("level") in ("danger", "error")]

            if danger_issues and not force:
                return {
                    "ok": False,
                    "blocked_by_linter": True,
                    "key": key,
                    "slot": slot,
                    "lint_issues": lint_issues,
                    "diff": diff_text,
                    "error": "Blocked by G-code safety linter. Review `lint_issues` and pass `force=true` only if intentional.",
                }, True, f"Linter blocked {key}"

            res = self.controller.apply_changes_sync(
                [{"key": key, "value": gcode_text, "category": cat, "slot": slot}],
                allow_gcode=True,
                source="mcp:gcode",
                notify_host=True,
            )
            ok = bool(res.get("ok"))
            return {
                "ok": ok,
                "key": key,
                "slot": slot,
                "record_id": res.get("record_id", ""),
                "applied": res.get("applied", []),
                "errors": res.get("errors", []),
                "warnings": res.get("warnings", []),
                "lint_issues": lint_issues,
                "diff": diff_text,
            }, not ok, f"Updated {key}" if ok else f"Failed {key}"

        if name == "undo_last_apply":
            if not settings.get("mcp_allow_write", True):
                return {"ok": False, "error": "Write access is disabled in Orca AI Assistant MCP settings (Read-Only mode)."}, True, "Blocked (read-only)"
            rec_id = str(args.get("record_id") or "").strip() or None
            res = self.controller.undo_apply_sync(record_id=rec_id, notify_host=True)
            ok = bool(res.get("ok"))
            return {
                "ok": ok,
                "record_id": res.get("record_id", ""),
                "applied": res.get("applied", []),
                "errors": res.get("errors", []),
                "warnings": res.get("warnings", []),
            }, not ok, f"Undid {len(res.get('applied') or [])} key(s)" if ok else "Undo failed"

        if name == "manage_snapshots":
            action = str(args.get("action") or "").strip().lower()
            if action == "list":
                snaps = [
                    {
                        "id": s.get("id", ""),
                        "name": s.get("name", ""),
                        "created_at": s.get("created_at", ""),
                    }
                    for s in self.controller.storage.get_snapshots()
                ]
                return {"ok": True, "snapshots": snaps}, False, f"Listed {len(snaps)} snapshot(s)"

            if not settings.get("mcp_allow_write", True):
                return {"ok": False, "error": "Write access is disabled in Orca AI Assistant MCP settings (Read-Only mode)."}, True, "Blocked (read-only)"

            if action == "save":
                snap_name = str(args.get("name") or "").strip() or dt.datetime.now().strftime("MCP Snapshot %d.%m %H:%M")
                res = self.controller.save_snapshot_sync(snap_name)
                return {"ok": True, "name": snap_name, "snapshots": [
                    {"id": s.get("id", ""), "name": s.get("name", ""), "created_at": s.get("created_at", "")}
                    for s in res
                ]}, False, f"Saved '{snap_name}'"

            if action == "restore":
                snap_id = str(args.get("snapshot_id") or "").strip()
                if not snap_id:
                    return {"ok": False, "error": "'snapshot_id' is required for restore."}, True, "Missing snapshot_id"
                res = self.controller.restore_snapshot_sync(snap_id, notify_host=True)
                ok = bool(res.get("ok"))
                return {
                    "ok": ok,
                    "snapshot_id": snap_id,
                    "record_id": res.get("record_id", ""),
                    "applied": res.get("applied", []),
                    "errors": res.get("errors", []),
                }, not ok, f"Restored {snap_id}" if ok else "Restore failed"

            if action == "delete":
                snap_id = str(args.get("snapshot_id") or "").strip()
                if not snap_id:
                    return {"ok": False, "error": "'snapshot_id' is required for delete."}, True, "Missing snapshot_id"
                snaps = self.controller.storage.delete_snapshot(snap_id)
                self.controller.emit({"type": "snapshots_updated", "snapshots": snaps})
                return {"ok": True, "deleted_id": snap_id, "remaining": len(snaps)}, False, f"Deleted {snap_id}"

            return {"ok": False, "error": f"Unsupported snapshot action: {action}"}, True, "Invalid action"

        if name == "show_notification":
            msg = str(args.get("message") or "").strip()
            if not msg:
                return {"ok": False, "error": "'message' must not be empty."}, True, "Empty message"
            level = str(args.get("level") or "info").strip().lower()
            if level not in ("info", "warning", "error"):
                level = "info"
            pushed = self.controller.push_native_notification(msg, level=level)
            return {"ok": True, "displayed_native": pushed, "level": level, "message": msg}, False, f"Notification ({level})"

        return {"ok": False, "error": f"Tool not implemented: {name}"}, True, "Not implemented"
