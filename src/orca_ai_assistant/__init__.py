"""Orca AI Assistant v3.0.0 — OrcaSlicer 2.5+ plugin entry point."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Any

# Cross-platform OrcaSlicer bundled Python packages path (for numpy, etc.)
def _attach_orcaslicer_packages_path() -> None:
    try:
        py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
        candidates: list[Path] = []
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA")
            if appdata:
                candidates.append(Path(appdata) / "OrcaSlicer" / "python" / "packages" / py_tag)
        elif sys.platform == "darwin":
            candidates.append(
                Path.home() / "Library" / "Application Support" / "OrcaSlicer" / "python" / "packages" / py_tag
            )
        else:
            xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
            candidates.append(Path(xdg) / "OrcaSlicer" / "python" / "packages" / py_tag)

        for pkg_dir in candidates:
            if pkg_dir.is_dir() and str(pkg_dir) not in sys.path:
                sys.path.append(str(pkg_dir))
    except Exception:
        pass


_attach_orcaslicer_packages_path()

try:
    import orca
    import orca.host
except Exception:  # pragma: no cover - imported outside OrcaSlicer (e.g. pytest / CI)
    orca = None  # type: ignore

from orca_ai_assistant.controller.controller import (
    AssistantController,
    get_controller,
    load_asset,
    load_ui_html,
)
from orca_ai_assistant.core.constants import MCP_DEFAULT_PORT, PLUGIN_ID, PLUGIN_VERSION
from orca_ai_assistant.core.storage import get_plugin_storage_dir


def _orca_submodule(name: str) -> Any:
    if orca is None:
        return None
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

_NETWORK_HTTP_HOSTS: list[str] = [
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
    "https://api.together.xyz",
    "http://localhost",
    "http://127.0.0.1",
]

_CONFIG_UI_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<style>
  :root {{
    color-scheme: dark light;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13px;
    margin: 0;
    padding: 14px 16px;
    background: var(--orca-bg, #181c20);
    color: var(--orca-fg, #e6edf3);
  }}
  h3 {{ margin: 0 0 10px 0; font-size: 15px; }}
  .item {{
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: 10px 0;
    padding: 10px;
    border-radius: 8px;
    background: rgba(127, 127, 127, 0.1);
  }}
  .item input[type="checkbox"] {{ margin-top: 2px; }}
  .desc {{ display: block; font-size: 12px; opacity: 0.78; margin-top: 3px; }}
  .actions {{ display: flex; align-items: center; gap: 10px; margin-top: 14px; }}
  button {{
    padding: 6px 14px;
    border-radius: 6px;
    border: none;
    background: #0f968b;
    color: #fff;
    font-weight: 600;
    cursor: pointer;
  }}
  button:hover {{ opacity: 0.92; }}
  #status {{ font-size: 12px; opacity: 0.85; }}
</style>
</head>
<body>
  <h3>Orca AI Assistant v{PLUGIN_VERSION}</h3>
  <label class="item">
    <input type="checkbox" id="preflight_notifications" />
    <span>
      <strong>Pre-Flight warning notifications</strong>
      <span class="desc">Show a native OrcaSlicer banner after slicing when critical Pre-Flight issues are detected.</span>
    </span>
  </label>
  <label class="item">
    <input type="checkbox" id="enable_slicing_audit" />
    <span>
      <strong>Automatic AI G-code audit on slice</strong>
      <span class="desc">Automatically send a sliced G-code summary to AI chat during the G-code post-process step.</span>
    </span>
  </label>
  <div class="actions">
    <button id="saveBtn" type="button">Save</button>
    <span id="status"></span>
  </div>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
let currentCfg = {{ preflight_notifications: true, enable_slicing_audit: false }};
if (window.orca && typeof window.orca.onConfig === "function") {{
  window.orca.onConfig((cfg) => {{
    currentCfg = Object.assign({{}}, currentCfg, cfg || {{}});
    $("preflight_notifications").checked = currentCfg.preflight_notifications !== false;
    $("enable_slicing_audit").checked = !!currentCfg.enable_slicing_audit;
  }});
}}
$("saveBtn").addEventListener("click", () => {{
  const next = Object.assign({{}}, currentCfg, {{
    preflight_notifications: $("preflight_notifications").checked,
    enable_slicing_audit: $("enable_slicing_audit").checked,
  }});
  if (window.orca && typeof window.orca.saveConfig === "function") {{
    window.orca.saveConfig(next);
  }}
  $("status").textContent = "Saved";
}});
</script>
</body>
</html>
"""


def _resolve_icon_path() -> str:
    """Return a stable static path to `icon.svg`, writing it at most once if bundled."""
    # 1) On-disk modular package asset
    try:
        pkg_file = Path(__file__).resolve()
        if pkg_file.is_file():
            static_svg = pkg_file.parent / "assets" / "icon.svg"
            if static_svg.is_file():
                return str(static_svg)
    except Exception:
        pass

    # 2) Single-file bundle: materialize once into plugin storage directory if missing
    try:
        storage_icon = get_plugin_storage_dir() / "icon.svg"
        if not storage_icon.is_file() or storage_icon.stat().st_size == 0:
            svg_text = load_asset("assets/icon.svg")
            storage_icon.parent.mkdir(parents=True, exist_ok=True)
            storage_icon.write_text(svg_text, encoding="utf-8")
        return str(storage_icon)
    except Exception:
        return ""


# ============================================================================
# OrcaSlicer 2.5+ Capabilities (STABLE non-localized names — fixes P0 #7)
# ============================================================================

if _PAGES_BASE is not None:
    class OrcaAIAssistantPage(_PAGES_BASE):
        """Top-bar Page capability for Orca AI Assistant."""

        def get_name(self) -> str:
            # Stable capability name across all UI languages (fixes .install_state.json persistence)
            return "Orca AI Assistant"

        def get_ui(self) -> str:
            ctrl = get_controller()
            ctrl.register_page(self)
            self._sync_native_config(ctrl)
            ctrl.sync_mcp_server(emit_update=False)
            return load_ui_html(view_mode="page")

        def get_icon(self) -> str:
            return _resolve_icon_path()

        def has_config_ui(self) -> bool:
            return True

        def get_default_config(self) -> dict[str, Any]:
            return {
                "preflight_notifications": True,
                "enable_slicing_audit": False,
            }

        def get_config_ui(self) -> str:
            return _CONFIG_UI_HTML

        def _sync_native_config(self, ctrl: AssistantController) -> None:
            try:
                get_cfg = getattr(self, "get_config", None)
                if callable(get_cfg):
                    cfg = get_cfg()
                    if isinstance(cfg, dict) and cfg:
                        ctrl.sync_plugin_config(cfg)
            except Exception:
                pass

        def on_message(self, message: Any) -> None:
            ctrl = get_controller()
            ctrl.register_page(self)
            ctrl.handle_message_on_ui(message, source_view=self)

        def on_lifecycle_event(self, event: Any, ctx: Any) -> None:
            ctrl = get_controller()
            ctrl.handle_lifecycle_event(event, ctx)

        def on_unload(self) -> None:
            try:
                ctrl = get_controller()
                ctrl.unregister_page(self)
                if not ctrl.has_open_views():
                    ctrl.shutdown_mcp_server()
            except Exception:
                pass
else:
    OrcaAIAssistantPage = None  # type: ignore[assignment]


if _SCRIPT_BASE is not None:
    class OrcaAIDockScript(_SCRIPT_BASE):
        """Script / Speed Dial capability opening the compact Dock Panel."""

        def get_name(self) -> str:
            return "Orca AI: Dock Panel"

        def execute(self) -> Any:
            ctrl = get_controller()
            ctrl.open_dock_panel()
            return orca.ExecutionResult.success("Orca AI Assistant dock panel opened.")
else:
    OrcaAIDockScript = None  # type: ignore[assignment]


if _PIPELINE_BASE is not None:
    class OrcaAIGcodeAuditor(_PIPELINE_BASE):
        """Slicing pipeline capability capturing/auditing sliced G-code via streaming disk reads."""

        def get_name(self) -> str:
            return "Orca AI: G-code Audit"

        def execute(self, ctx: Any) -> Any:
            try:
                if ctx.step != _GCODE_STEP or not getattr(ctx, "gcode_path", None):
                    return orca.ExecutionResult.success()
                gpath = Path(str(ctx.gcode_path))
                if gpath.is_file():
                    ctrl = get_controller()
                    settings = ctrl.storage.get_settings()
                    # Stream from disk off-thread (never read full 100MB+ G-code on slicing thread!)
                    ctrl.handle_sliced_gcode_file(
                        gpath,
                        auto_audit=bool(settings.get("enable_slicing_audit", False)),
                    )
            except Exception:
                pass
            return orca.ExecutionResult.success()
else:
    OrcaAIGcodeAuditor = None  # type: ignore[assignment]


if orca is not None and hasattr(orca, "plugin") and hasattr(orca, "base"):
    @orca.plugin
    class OrcaAIAssistantPlugin(orca.base):
        """Main OrcaSlicer plugin descriptor."""

        def register_capabilities(self) -> None:
            try:
                ctrl = get_controller()
                mcp_port = int((ctrl.storage.get_settings() or {}).get("mcp_port") or MCP_DEFAULT_PORT)
            except Exception:
                mcp_port = MCP_DEFAULT_PORT
            socket_grants = [f"('127.0.0.1', {MCP_DEFAULT_PORT})"]
            if mcp_port != MCP_DEFAULT_PORT and 1024 <= mcp_port <= 65535:
                socket_grants.append(f"('127.0.0.1', {mcp_port})")
            try:
                orca.request_permissions(
                    network_http=_NETWORK_HTTP_HOSTS,
                    network_socket=socket_grants,
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
else:
    class OrcaAIAssistantPlugin:  # type: ignore[no-redef]
        """Stub plugin class when imported outside OrcaSlicer host."""

        def register_capabilities(self) -> None:
            pass


__all__ = [
    "AssistantController",
    "OrcaAIAssistantPage",
    "OrcaAIAssistantPlugin",
    "OrcaAIDockScript",
    "OrcaAIGcodeAuditor",
    "PLUGIN_ID",
    "PLUGIN_VERSION",
    "get_controller",
    "load_asset",
    "load_ui_html",
]
