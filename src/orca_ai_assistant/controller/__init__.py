"""Controller and settings-parser layer for Orca AI Assistant."""

from __future__ import annotations

from orca_ai_assistant.controller.controller import (
    AssistantController,
    get_controller,
    load_asset,
    load_ui_html,
)
from orca_ai_assistant.controller.settings_parser import extract_suggested_settings

__all__ = [
    "AssistantController",
    "extract_suggested_settings",
    "get_controller",
    "load_asset",
    "load_ui_html",
]
