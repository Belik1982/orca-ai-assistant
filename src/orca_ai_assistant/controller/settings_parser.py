"""Resilient parser for ```orca-settings``` blocks emitted by AI models.

Supports JSON arrays `[...]` and single objects `{...}`, tolerates trailing
commas and raw multiline newlines inside JSON strings (common in Custom G-code
blocks), preserves multi-slot AMS `slot` numbers, looks up live values when
absent from the cached snapshot, normalizes/validates non-G-code values, and
splits `CUSTOM_GCODE_KEYS` into a dedicated `gcode_changes` list with unified
diffs and static safety-linter warnings.
"""

from __future__ import annotations

import json
import re
from typing import Any

from orca_ai_assistant.core.constants import norm_lang, tr
from orca_ai_assistant.orca_bridge.enums import (
    CUSTOM_GCODE_KEYS,
    FLAT_SETTING_INFO,
    normalize_and_validate_setting,
    normalize_setting_category,
)
from orca_ai_assistant.orca_bridge.gcode_codec import (
    lint_custom_gcode,
    make_unified_diff,
)
from orca_ai_assistant.orca_bridge.presets import read_live_setting_value

_SETTINGS_BLOCK_RE = re.compile(
    r"```(?:orca[-_]settings)\s*([\s\S]*?)```",
    re.IGNORECASE,
)

# Maps filament_slots summary aliases to canonical OrcaSlicer filament keys.
_FILAMENT_SLOT_ALIAS_MAP: dict[str, str] = {
    "nozzle_temperature": "nozzle_temp",
    "hot_plate_temp": "bed_temp",
    "textured_plate_temp": "bed_temp",
    "filament_flow_ratio": "flow_ratio",
    "filament_max_volumetric_speed": "max_volumetric_speed",
    "pressure_advance": "pressure_advance",
    "fan_max_speed": "fan_max",
    "filament_start_gcode": "start_gcode",
    "filament_end_gcode": "end_gcode",
}


def _sanitize_json_candidate(raw: str) -> str:
    """Repair common LLM JSON glitches without touching valid string payloads.

    - Escapes literal CR/LF/TAB characters that appear inside quoted strings.
    - Removes trailing commas directly preceding `]` or `}` outside strings.
    """
    text = raw.strip().lstrip("\ufeff")
    if not text:
        return ""

    # Pass 1: escape unescaped control characters inside double-quoted strings.
    out_chars: list[str] = []
    in_str = False
    escaped = False
    for ch in text:
        if in_str:
            if escaped:
                out_chars.append(ch)
                escaped = False
            elif ch == "\\":
                out_chars.append(ch)
                escaped = True
            elif ch == '"':
                out_chars.append(ch)
                in_str = False
            elif ch == "\n":
                out_chars.append("\\n")
            elif ch == "\r":
                out_chars.append("\\r")
            elif ch == "\t":
                out_chars.append("\\t")
            else:
                out_chars.append(ch)
        else:
            if ch == '"':
                in_str = True
            out_chars.append(ch)

    pass1 = "".join(out_chars)

    # Pass 2: strip trailing commas before `]` or `}` outside strings.
    cleaned: list[str] = []
    in_str = False
    escaped = False
    n = len(pass1)
    i = 0
    while i < n:
        ch = pass1[i]
        if in_str:
            cleaned.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            i += 1
            continue

        if ch == '"':
            in_str = True
            cleaned.append(ch)
            i += 1
            continue

        if ch == ",":
            j = i + 1
            while j < n and pass1[j] in " \t\r\n":
                j += 1
            if j < n and pass1[j] in "]}":
                # Drop trailing comma
                i += 1
                continue

        cleaned.append(ch)
        i += 1

    return "".join(cleaned)


def _parse_slot(raw_slot: Any) -> int:
    try:
        val = int(raw_slot)
        return val if val >= 1 else 1
    except (TypeError, ValueError):
        return 1


def _extract_slot_entry(presets: dict[str, Any], slot: int) -> dict[str, Any] | None:
    slots = presets.get("filament_slots")
    if not isinstance(slots, list):
        return None
    for entry in slots:
        if isinstance(entry, dict) and _parse_slot(entry.get("slot")) == slot:
            return entry
    if 1 <= slot <= len(slots) and isinstance(slots[slot - 1], dict):
        return slots[slot - 1]
    return None


def _lookup_current_value(
    key: str,
    category: str,
    slot: int,
    presets: dict[str, Any],
    is_gcode: bool,
) -> str:
    """Resolve current setting value from presets snapshot or live OrcaSlicer API."""
    if isinstance(presets, dict) and isinstance(presets.get("flat_values"), dict):
        flat_values: dict[str, Any] = presets["flat_values"]
        custom_gcode: dict[str, Any] = (
            presets.get("custom_gcode") if isinstance(presets.get("custom_gcode"), dict) else {}
        )
    elif isinstance(presets, dict):
        # Backward-compat: caller passed flat_values dict directly
        flat_values = presets
        custom_gcode = {}
    else:
        flat_values = {}
        custom_gcode = {}

    if is_gcode:
        # 1) Filament slot custom G-code
        if category == "filament":
            slot_entry = _extract_slot_entry(presets, slot) if isinstance(presets, dict) else None
            if slot_entry is not None:
                for candidate_field in (key, _FILAMENT_SLOT_ALIAS_MAP.get(key, "")):
                    if candidate_field and candidate_field in slot_entry and slot_entry[candidate_field] is not None:
                        return str(slot_entry[candidate_field])

        # 2) presets["custom_gcode"] map
        if key in custom_gcode and custom_gcode[key] is not None:
            raw_cg = custom_gcode[key]
            if isinstance(raw_cg, dict) and "value" in raw_cg:
                return str(raw_cg["value"] or "")
            if isinstance(raw_cg, list):
                idx = slot - 1
                if 0 <= idx < len(raw_cg):
                    return str(raw_cg[idx] or "")
            elif isinstance(raw_cg, str):
                return raw_cg

        # 3) Live OrcaSlicer fallback
        try:
            live_val = read_live_setting_value(key, category, slot)
            if live_val is not None:
                return str(live_val)
        except Exception:
            pass
        return ""

    # Non-G-code settings
    if category == "filament":
        slot_entry = _extract_slot_entry(presets, slot) if isinstance(presets, dict) else None
        if slot_entry is not None:
            if key in slot_entry and slot_entry[key] not in (None, ""):
                return str(slot_entry[key])
            alias = _FILAMENT_SLOT_ALIAS_MAP.get(key)
            if alias and alias in slot_entry and slot_entry[alias] not in (None, ""):
                return str(slot_entry[alias])
        # For slots > 1, query live value so we don't mistakenly show Slot 1's flat value
        if slot > 1:
            try:
                live_slot_val = read_live_setting_value(key, category, slot)
                if live_slot_val not in (None, ""):
                    return str(live_slot_val)
            except Exception:
                pass

    if key in flat_values and flat_values[key] not in (None, "", "—"):
        return str(flat_values[key])

    try:
        live_val = read_live_setting_value(key, category, slot)
        if live_val not in (None, ""):
            return str(live_val)
    except Exception:
        pass

    return "—"


def _resolve_label(key: str, item_label: Any, lang: str) -> str:
    explicit = str(item_label or "").strip()
    if explicit:
        return explicit

    gcode_info = CUSTOM_GCODE_KEYS.get(key)
    if isinstance(gcode_info, dict):
        lbl = gcode_info.get(lang) or gcode_info.get("en") or gcode_info.get("ru")
        if lbl:
            return str(lbl)

    info = FLAT_SETTING_INFO.get(key)
    if isinstance(info, dict):
        lbl = info.get(lang) or info.get("ru") or info.get("en")
        if lbl:
            return str(lbl)

    return key


def extract_suggested_settings(
    reply_text: str,
    presets: dict[str, Any],
    lang: str = "ru",
) -> dict[str, Any]:
    """Parse all ```orca-settings``` / ```orca_settings``` blocks in an AI reply.

    Returns:
        {
            "suggestions": list[dict[str, Any]],
            "gcode_changes": list[dict[str, Any]],
            "parse_error": str,
        }
    """
    l = norm_lang(lang)
    suggestions: list[dict[str, Any]] = []
    gcode_changes: list[dict[str, Any]] = []
    parse_errors: list[str] = []

    if not reply_text:
        return {"suggestions": [], "gcode_changes": [], "parse_error": ""}

    for match in _SETTINGS_BLOCK_RE.finditer(reply_text):
        raw_block = match.group(1) or ""
        candidate = _sanitize_json_candidate(raw_block)
        if not candidate:
            parse_errors.append(
                tr(
                    l,
                    "Обнаружен пустой блок orca-settings.",
                    "Виявлено порожній блок orca-settings.",
                    "Found an empty orca-settings block.",
                )
            )
            continue

        parsed: Any = None
        last_exc: Exception | None = None
        for attempt in (raw_block.strip(), candidate):
            if not attempt:
                continue
            try:
                parsed = json.loads(attempt)
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            detail = str(last_exc)
            parse_errors.append(
                tr(
                    l,
                    f"Не удалось разобрать JSON в блоке orca-settings: {detail}",
                    f"Не вдалося розібрати JSON у блоці orca-settings: {detail}",
                    f"Failed to parse JSON in orca-settings block: {detail}",
                )
            )
            continue

        # Normalize JSON object -> list of item dicts
        items: list[Any]
        if isinstance(parsed, list):
            items = parsed
        elif isinstance(parsed, dict):
            if isinstance(parsed.get("settings"), list):
                items = parsed["settings"]
            elif isinstance(parsed.get("changes"), list):
                items = parsed["changes"]
            elif "key" in parsed:
                items = [parsed]
            else:
                parse_errors.append(
                    tr(
                        l,
                        "Блок orca-settings имеет неожиданный формат JSON (ожидается массив или объект с полем 'key').",
                        "Блок orca-settings має неочікуваний формат JSON (очікується масив або об'єкт із полем 'key').",
                        "The orca-settings block has an unexpected JSON format (expected an array or object with 'key').",
                    )
                )
                continue
        else:
            parse_errors.append(
                tr(
                    l,
                    "Блок orca-settings должен содержать JSON-массив или объект.",
                    "Блок orca-settings має містити JSON-масив або об'єкт.",
                    "The orca-settings block must contain a JSON array or object.",
                )
            )
            continue

        for item in items:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if not key:
                continue

            raw_cat = str(item.get("category") or "").strip().lower()
            cat = normalize_setting_category(key, raw_cat)
            slot = _parse_slot(item.get("slot", 1))
            label = _resolve_label(key, item.get("label"), l)
            reason = str(item.get("reason") or "").strip()

            raw_value_obj = item.get("value", "")
            is_gcode = key in CUSTOM_GCODE_KEYS

            if is_gcode:
                new_val = "" if raw_value_obj is None else str(raw_value_obj)
                cur_val = _lookup_current_value(key, cat, slot, presets, is_gcode=True)
                diff_label = f"{key} (Slot {slot})" if cat == "filament" else key
                diff_text = make_unified_diff(cur_val, new_val, label=diff_label)
                lint_warnings = lint_custom_gcode(key, new_val, lang=l, old_text=cur_val)
                gcode_changes.append({
                    "key": key,
                    "category": cat,
                    "slot": slot,
                    "label": label,
                    "current_value": cur_val,
                    "value": new_val,
                    "reason": reason,
                    "diff": diff_text,
                    "lint_warnings": lint_warnings,
                })
                continue

            if isinstance(raw_value_obj, bool):
                raw_val = "1" if raw_value_obj else "0"
            elif raw_value_obj is None:
                raw_val = ""
            else:
                raw_val = str(raw_value_obj).strip()

            cur_val = _lookup_current_value(key, cat, slot, presets, is_gcode=False)
            norm_val, val_note, val_err = normalize_and_validate_setting(key, raw_val, cat)

            suggestions.append({
                "category": cat,
                "key": key,
                "slot": slot,
                "label": label,
                "current_value": cur_val,
                "value": norm_val,
                "raw_value": raw_val,
                "reason": reason,
                "validation_note": val_note or "",
                "validation_error": val_err or "",
            })

    return {
        "suggestions": suggestions,
        "gcode_changes": gcode_changes,
        "parse_error": " | ".join(parse_errors),
    }
