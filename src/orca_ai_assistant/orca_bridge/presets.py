from __future__ import annotations

import datetime as dt
from typing import Any

from ..core.constants import norm_lang, tr
from .enums import (
    CUSTOM_GCODE_KEYS,
    FLAT_SETTING_INFO,
    SLICER_SETTINGS_I18N,
    normalize_and_validate_setting,
    normalize_setting_category,
)
from .gcode_codec import (
    escape_orca_string,
    escape_orca_strings_single,
    unescape_orca_string,
    unescape_orca_strings_single,
)

try:
    import orca  # type: ignore
    import orca.host  # type: ignore
except Exception:
    orca = None  # type: ignore


def _extract_value_str(val: Any, slot_idx: int = 0) -> str:
    """Extract a clean scalar string from an OrcaSlicer config value."""
    if val is None:
        return ""
    if isinstance(val, bool):
        return "1" if val else "0"
    if isinstance(val, (list, tuple)):
        if not val:
            return ""
        idx = slot_idx if 0 <= slot_idx < len(val) else 0
        elem = val[idx]
        if isinstance(elem, bool):
            return "1" if elem else "0"
        return str(elem)
    return str(val)


def _decode_gcode_value(key: str, raw: Any) -> str:
    if raw is None:
        return ""
    text = str(raw)
    meta = CUSTOM_GCODE_KEYS.get(key)
    if meta and meta.get("is_vector"):
        return unescape_orca_strings_single(text)
    return unescape_orca_string(text)


def _safe_preset_config_value(preset_obj: Any, key: str) -> Any:
    if preset_obj is None:
        return None
    try:
        fn = getattr(preset_obj, "config_value", None)
        if callable(fn):
            return fn(key)
    except Exception:
        return None
    return None


def _get_preset_bundle() -> Any:
    if orca is None or getattr(orca, "host", None) is None:
        return None
    try:
        return orca.host.preset_bundle()
    except Exception:
        return None


def read_live_setting_value(key: str, category: str = "", slot: int = 1) -> str:
    """
    Read the live value of any OrcaSlicer setting (including multi-slot filament
    settings and custom G-code keys, properly unescaped).
    """
    k = str(key or "").strip()
    if not k:
        return ""
    bundle = _get_preset_bundle()
    if bundle is None:
        return ""

    cat = normalize_setting_category(k, category)
    is_gcode = k in CUSTOM_GCODE_KEYS
    raw: Any = None

    try:
        if cat == "filament":
            slot_idx = max(0, int(slot or 1) - 1)
            try:
                fil_presets = list(bundle.current_filament_presets() or [])
                if slot_idx < len(fil_presets) and fil_presets[slot_idx] is not None:
                    raw = _safe_preset_config_value(fil_presets[slot_idx], k)
            except Exception:
                raw = None
            if raw is None:
                try:
                    raw = bundle.full_config_value(k)
                except Exception:
                    raw = None
            if raw is None:
                return ""
            if is_gcode:
                return _decode_gcode_value(k, raw)
            # full_config_value() for filament vectors can serialize multiple slots separated by ',' or ';'
            val_s = _extract_value_str(raw, slot_idx)
            if isinstance(raw, str) and not is_gcode:
                # If raw came from preset.config_value(k), it is a single-slot value.
                # If it looks like multi-slot comma/semicolon list and slot_idx matches, split safely.
                if "," in val_s and not val_s.startswith('"'):
                    parts = [p.strip() for p in val_s.split(",")]
                    if slot_idx < len(parts):
                        return parts[slot_idx]
                    return parts[0]
            return val_s

        if cat == "printer":
            try:
                pr = bundle.current_printer_preset()
                raw = _safe_preset_config_value(pr, k)
            except Exception:
                raw = None
            if raw is None:
                try:
                    raw = bundle.full_config_value(k)
                except Exception:
                    raw = None
            if raw is None:
                return ""
            return _decode_gcode_value(k, raw) if is_gcode else _extract_value_str(raw)

        # process
        try:
            proc = bundle.current_process_preset()
            raw = _safe_preset_config_value(proc, k)
        except Exception:
            raw = None
        if raw is None:
            try:
                raw = bundle.full_config_value(k)
            except Exception:
                raw = None
        if raw is None:
            return ""
        return _decode_gcode_value(k, raw) if is_gcode else _extract_value_str(raw)
    except Exception:
        return ""


def _read_connected_printer() -> dict[str, Any] | None:
    if orca is None or getattr(orca, "host", None) is None:
        return None
    try:
        fn = getattr(orca.host, "selected_printer", None)
        if not callable(fn):
            return None
        info = fn()
        if not info:
            return None
        if isinstance(info, dict):
            return {
                "agent": str(info.get("agent") or ""),
                "model_id": str(info.get("model_id") or ""),
                "connection": str(info.get("connection") or ""),
                "online": bool(info.get("online", False)),
                "connected": bool(info.get("connected", False)),
                "firmware": str(info.get("firmware") or ""),
            }
        # Object-style attribute fallback
        return {
            "agent": str(getattr(info, "agent", "") or ""),
            "model_id": str(getattr(info, "model_id", "") or ""),
            "connection": str(getattr(info, "connection", "") or ""),
            "online": bool(getattr(info, "online", False)),
            "connected": bool(getattr(info, "connected", False)),
            "firmware": str(getattr(info, "firmware", "") or ""),
        }
    except Exception:
        return None


def _diff_preset_pair(
    category: str,
    saved_preset: Any,
    edited_preset: Any,
    slot: int = 0,
    max_items: int = 40,
) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    if saved_preset is None or edited_preset is None:
        return diffs
    try:
        keys_fn = getattr(edited_preset, "config_keys", None)
        keys = list(keys_fn() or []) if callable(keys_fn) else []
    except Exception:
        keys = []

    for k in keys:
        if len(diffs) >= max_items:
            break
        try:
            new_raw = _safe_preset_config_value(edited_preset, k)
            old_raw = _safe_preset_config_value(saved_preset, k)
            if new_raw is None and old_raw is None:
                continue
            if k in CUSTOM_GCODE_KEYS:
                new_s = _decode_gcode_value(k, new_raw)
                old_s = _decode_gcode_value(k, old_raw)
            else:
                new_s = _extract_value_str(new_raw)
                old_s = _extract_value_str(old_raw)
            if new_s != old_s:
                diffs.append({
                    "category": category,
                    "slot": slot,
                    "key": str(k),
                    "saved": old_s,
                    "current": new_s,
                })
        except Exception:
            continue
    return diffs


def _collect_dirty_diff(bundle: Any) -> list[dict[str, Any]]:
    diffs: list[dict[str, Any]] = []
    # Process (prints)
    try:
        prints = getattr(bundle, "prints", None)
        if prints is not None:
            diffs.extend(_diff_preset_pair("process", prints.selected_preset(), prints.edited_preset(), slot=0))
    except Exception:
        pass
    # Printer (printers)
    try:
        printers = getattr(bundle, "printers", None)
        if printers is not None:
            diffs.extend(_diff_preset_pair("printer", printers.selected_preset(), printers.edited_preset(), slot=0))
    except Exception:
        pass
    # Filaments (per active slot)
    try:
        fils_coll = getattr(bundle, "filaments", None)
        cur_fils = list(bundle.current_filament_presets() or [])
        if fils_coll is not None and cur_fils:
            for idx, edited_f in enumerate(cur_fils, start=1):
                if edited_f is None:
                    continue
                if not getattr(edited_f, "is_dirty", False):
                    continue
                fname = str(getattr(edited_f, "name", "") or "")
                saved_f = None
                try:
                    if fname and callable(getattr(fils_coll, "find_preset", None)):
                        saved_f = fils_coll.find_preset(fname)
                except Exception:
                    saved_f = None
                if saved_f is not None:
                    diffs.extend(_diff_preset_pair("filament", saved_f, edited_f, slot=idx, max_items=20))
    except Exception:
        pass
    return diffs


def _pick_bed_temp_for_plate(bed_type: str, hot: str, textured: str, eng: str, cool: str) -> str:
    bt = (bed_type or "").lower()
    if "textured" in bt and "cool" not in bt and textured:
        return textured
    if "cool" in bt and cool:
        return cool
    if "eng" in bt and eng:
        return eng
    if ("high" in bt or "hot" in bt or "smooth" in bt) and hot:
        return hot
    for candidate in (textured, hot, eng, cool):
        if candidate and candidate != "0":
            return candidate
    return hot or textured or eng or cool or ""


def inspect_slicer_presets(lang: str = "ru", include_gcode: bool = True) -> dict[str, Any]:
    """
    Inspect live OrcaSlicer printer, process, and ALL multi-slot filament presets,
    plus custom G-code blocks, unsaved preset diffs, and connected printer info.
    """
    l = norm_lang(lang)
    not_def = tr(l, "Не определен", "Не визначено", "Not detected")
    result: dict[str, Any] = {
        "printer_preset": not_def,
        "process_preset": not_def,
        "filament_presets": [],
        "filament_slots": [],
        "groups": {},
        "flat_values": {},
        "custom_gcode": {},
        "dirty_diff": [],
        "connected_printer": _read_connected_printer(),
    }

    bundle = _get_preset_bundle()
    if bundle is None:
        return result

    try:
        pr = None
        proc = None
        fil_preset_objs: list[Any] = []

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
            fil_names = list(bundle.current_filament_preset_names() or [])
            result["filament_presets"] = [str(f) for f in fil_names if f]
        except Exception:
            pass

        try:
            fil_preset_objs = list(bundle.current_filament_presets() or [])
        except Exception:
            fil_preset_objs = []

        idx_map = {"ru": 0, "uk": 1, "en": 2}
        lang_idx = idx_map.get(l, 0)

        # Read cataloged settings (Slot 1 for filament in flat_values / groups)
        for grp_titles, items in SLICER_SETTINGS_I18N:
            group_title = grp_titles[lang_idx]
            group_entries = []
            for key, l_ru, l_uk, l_en, category in items:
                val_str = ""
                if category == "filament" and fil_preset_objs:
                    raw_f = _safe_preset_config_value(fil_preset_objs[0], key)
                    if raw_f is not None:
                        val_str = _extract_value_str(raw_f)
                if val_str == "":
                    try:
                        raw_val = bundle.full_config_value(key)
                    except Exception:
                        raw_val = None
                    val_str = _extract_value_str(raw_val)
                    # If full_config_value returned multi-slot list string for filament, extract slot 1
                    if category == "filament" and "," in val_str and not val_str.startswith('"'):
                        val_str = val_str.split(",", 1)[0].strip()
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

        curr_bed_type = result["flat_values"].get("curr_bed_type", "")

        # Read ALL AMS/MMU filament slots via bundle.current_filament_presets()
        slots_out: list[dict[str, Any]] = []
        for slot_num, fp in enumerate(fil_preset_objs, start=1):
            if fp is None:
                continue
            fname = str(getattr(fp, "name", "") or "")
            if not fname and slot_num - 1 < len(result["filament_presets"]):
                fname = result["filament_presets"][slot_num - 1]
            hot_t = _extract_value_str(_safe_preset_config_value(fp, "hot_plate_temp"))
            tex_t = _extract_value_str(_safe_preset_config_value(fp, "textured_plate_temp"))
            eng_t = _extract_value_str(_safe_preset_config_value(fp, "eng_plate_temp"))
            cool_t = _extract_value_str(_safe_preset_config_value(fp, "cool_plate_temp"))
            bed_t = _pick_bed_temp_for_plate(curr_bed_type, hot_t, tex_t, eng_t, cool_t)

            slot_entry: dict[str, Any] = {
                "slot": slot_num,
                "name": fname or f"Slot {slot_num}",
                "type": _extract_value_str(_safe_preset_config_value(fp, "filament_type")),
                "vendor": _extract_value_str(_safe_preset_config_value(fp, "filament_vendor")),
                "nozzle_temp": _extract_value_str(_safe_preset_config_value(fp, "nozzle_temperature")),
                "nozzle_temp_initial": _extract_value_str(_safe_preset_config_value(fp, "nozzle_temperature_initial_layer")),
                "bed_temp": bed_t,
                "hot_plate_temp": hot_t,
                "textured_plate_temp": tex_t,
                "cool_plate_temp": cool_t,
                "eng_plate_temp": eng_t,
                "flow_ratio": _extract_value_str(_safe_preset_config_value(fp, "filament_flow_ratio")),
                "max_volumetric_speed": _extract_value_str(_safe_preset_config_value(fp, "filament_max_volumetric_speed")),
                "enable_pressure_advance": _extract_value_str(_safe_preset_config_value(fp, "enable_pressure_advance")),
                "pressure_advance": _extract_value_str(_safe_preset_config_value(fp, "pressure_advance")),
                "fan_max": _extract_value_str(_safe_preset_config_value(fp, "fan_max_speed")),
                "fan_min": _extract_value_str(_safe_preset_config_value(fp, "fan_min_speed")),
                "close_fan_first_layers": _extract_value_str(_safe_preset_config_value(fp, "close_fan_the_first_x_layers")),
                "slow_down_for_layer_cooling": _extract_value_str(_safe_preset_config_value(fp, "slow_down_for_layer_cooling")),
                "start_gcode": (
                    _decode_gcode_value("filament_start_gcode", _safe_preset_config_value(fp, "filament_start_gcode"))
                    if include_gcode else ""
                ),
                "end_gcode": (
                    _decode_gcode_value("filament_end_gcode", _safe_preset_config_value(fp, "filament_end_gcode"))
                    if include_gcode else ""
                ),
                "is_dirty": bool(getattr(fp, "is_dirty", False)),
            }
            slots_out.append(slot_entry)

        # Fallback if current_filament_presets() was unavailable but flat_values has slot 1 data
        if not slots_out and (result["filament_presets"] or result["flat_values"].get("filament_type")):
            fv = result["flat_values"]
            slots_out.append({
                "slot": 1,
                "name": result["filament_presets"][0] if result["filament_presets"] else "Slot 1",
                "type": fv.get("filament_type", ""),
                "vendor": fv.get("filament_vendor", ""),
                "nozzle_temp": fv.get("nozzle_temperature", ""),
                "nozzle_temp_initial": fv.get("nozzle_temperature_initial_layer", ""),
                "bed_temp": _pick_bed_temp_for_plate(
                    curr_bed_type,
                    fv.get("hot_plate_temp", ""),
                    fv.get("textured_plate_temp", ""),
                    fv.get("eng_plate_temp", ""),
                    fv.get("cool_plate_temp", ""),
                ),
                "hot_plate_temp": fv.get("hot_plate_temp", ""),
                "textured_plate_temp": fv.get("textured_plate_temp", ""),
                "cool_plate_temp": fv.get("cool_plate_temp", ""),
                "eng_plate_temp": fv.get("eng_plate_temp", ""),
                "flow_ratio": fv.get("filament_flow_ratio", ""),
                "max_volumetric_speed": fv.get("filament_max_volumetric_speed", ""),
                "enable_pressure_advance": fv.get("enable_pressure_advance", ""),
                "pressure_advance": fv.get("pressure_advance", ""),
                "fan_max": fv.get("fan_max_speed", ""),
                "fan_min": fv.get("fan_min_speed", ""),
                "close_fan_first_layers": fv.get("close_fan_the_first_x_layers", ""),
                "slow_down_for_layer_cooling": fv.get("slow_down_for_layer_cooling", ""),
                "start_gcode": "",
                "end_gcode": "",
                "is_dirty": False,
            })

        result["filament_slots"] = slots_out
        if not result["filament_presets"] and slots_out:
            result["filament_presets"] = [s["name"] for s in slots_out]

        # Custom G-code blocks (unescaped, non-empty)
        if include_gcode:
            custom_gcode: dict[str, str] = {}
            for gkey, gmeta in CUSTOM_GCODE_KEYS.items():
                gcat = gmeta["category"]
                val = ""
                if gcat == "filament":
                    if fil_preset_objs:
                        val = _decode_gcode_value(gkey, _safe_preset_config_value(fil_preset_objs[0], gkey))
                    else:
                        val = read_live_setting_value(gkey, "filament", slot=1)
                elif gcat == "printer":
                    raw_g = _safe_preset_config_value(pr, gkey)
                    if raw_g is None:
                        try:
                            raw_g = bundle.full_config_value(gkey)
                        except Exception:
                            raw_g = None
                    val = _decode_gcode_value(gkey, raw_g)
                else:
                    raw_g = _safe_preset_config_value(proc, gkey)
                    if raw_g is None:
                        try:
                            raw_g = bundle.full_config_value(gkey)
                        except Exception:
                            raw_g = None
                    val = _decode_gcode_value(gkey, raw_g)

                if val.strip():
                    custom_gcode[gkey] = val
            result["custom_gcode"] = custom_gcode

        # Dirty diff across process / printer / filaments
        result["dirty_diff"] = _collect_dirty_diff(bundle)

    except Exception as exc:
        result["error"] = str(exc)

    return result


def apply_settings_to_orcaslicer(changes: list[dict[str, Any]], lang: str = "ru") -> dict[str, Any]:
    """
    Validate, normalize, capture rollback values, and commit setting changes
    to OrcaSlicer presets with automatic per-key fallback if batch commit fails.
    """
    l = norm_lang(lang)
    applied: list[dict[str, Any]] = []
    rollback_changes: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(changes, list) or not changes:
        return {
            "ok": False,
            "applied": [],
            "rollback_changes": [],
            "errors": [tr(l, "Нет настроек для применения.", "Немає налаштувань для застосування.", "No settings to apply.")],
            "warnings": [],
        }

    # Group normalized & pre-validated items by (category, slot)
    by_target: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for ch in changes:
        if not isinstance(ch, dict):
            continue
        key = str(ch.get("key") or "").strip()
        if not key:
            continue

        cat = normalize_setting_category(key, str(ch.get("category") or ""))
        try:
            slot_num = max(1, int(ch.get("slot") or 1)) if cat == "filament" else 0
        except Exception:
            slot_num = 1 if cat == "filament" else 0

        is_gcode = key in CUSTOM_GCODE_KEYS
        default_label = (
            CUSTOM_GCODE_KEYS[key].get(l)
            if is_gcode
            else FLAT_SETTING_INFO.get(key, {}).get(l)
        ) or key
        label = str(ch.get("label") or default_label)

        if is_gcode:
            # NEVER strip G-code indentation/newlines!
            raw_val = "" if ch.get("value") is None else str(ch.get("value"))
            is_vec = bool(CUSTOM_GCODE_KEYS[key].get("is_vector"))
            wire_val = escape_orca_strings_single(raw_val) if is_vec else escape_orca_string(raw_val)
            display_val = raw_val
        else:
            raw_val = "" if ch.get("value") is None else str(ch.get("value"))
            norm_val, note, err = normalize_and_validate_setting(key, raw_val, cat)
            if err:
                errors.append(f"{key}: {err}")
                continue
            if note:
                warnings.append(f"{key}: {note}")
            wire_val = norm_val
            display_val = norm_val

        prev_val = read_live_setting_value(key, cat, slot=slot_num if slot_num > 0 else 1)

        by_target.setdefault((cat, slot_num), []).append({
            "category": cat,
            "slot": slot_num,
            "key": key,
            "label": label,
            "wire_val": wire_val,
            "display_val": display_val,
            "prev_val": prev_val,
            "is_gcode": is_gcode,
        })

    if not by_target:
        return {
            "ok": False,
            "applied": [],
            "rollback_changes": [],
            "errors": errors,
            "warnings": warnings,
        }

    host_preset = getattr(getattr(orca, "host", None), "preset", None) if orca is not None else None
    if host_preset is None:
        errors.append(tr(
            l,
            "API пресетов OrcaSlicer недоступно.",
            "API пресетів OrcaSlicer недоступне.",
            "OrcaSlicer preset API is unavailable.",
        ))
        return {
            "ok": False,
            "applied": [],
            "rollback_changes": [],
            "errors": errors,
            "warnings": warnings,
        }

    def _record_success(item: dict[str, Any]) -> None:
        applied.append({
            "category": item["category"],
            "slot": item["slot"],
            "key": item["key"],
            "label": item["label"],
            "value": item["display_val"],
            "previous_value": item["prev_val"],
            "is_gcode": item["is_gcode"],
        })
        if item["prev_val"] != "" or item["is_gcode"]:
            rb: dict[str, Any] = {
                "category": item["category"],
                "key": item["key"],
                "label": item["label"],
                "value": item["prev_val"],
            }
            if item["category"] == "filament":
                rb["slot"] = item["slot"]
            rollback_changes.append(rb)

    for (cat, slot_num), items in by_target.items():
        editor = getattr(host_preset, cat, None)
        if editor is None:
            errors.append(tr(
                l,
                f"Редактор пресета '{cat}' недоступен.",
                f"Редактор пресету '{cat}' недоступний.",
                f"Preset editor '{cat}' is unavailable.",
            ))
            continue

        # Attempt fast atomic batch commit first
        try:
            tx = editor.begin_update(slot_num) if cat == "filament" else editor.begin_update()
            for item in items:
                tx.set(item["key"], item["wire_val"])
            tx.commit()
            for item in items:
                _record_success(item)
            continue
        except Exception as batch_exc:
            if len(items) == 1:
                it = items[0]
                errors.append(f"{it['key']} = {it['display_val']}: {batch_exc}")
                continue

            # Batch commit failed on multi-key transaction -> fallback to per-key commit
            warnings.append(tr(
                l,
                f"Пакетное применение ({cat}) не удалось ({batch_exc}) — выполнен поштучный откат для сохранения валидных настроек.",
                f"Пакетне застосування ({cat}) не вдалося ({batch_exc}) — виконано поштучне застосування для збереження валідних налаштувань.",
                f"Batch commit ({cat}) failed ({batch_exc}) — fell back to per-key commit so valid settings still apply.",
            ))
            for item in items:
                try:
                    tx_single = editor.begin_update(slot_num) if cat == "filament" else editor.begin_update()
                    tx_single.set(item["key"], item["wire_val"])
                    tx_single.commit()
                    _record_success(item)
                except Exception as key_exc:
                    errors.append(f"{item['key']} = {item['display_val']}: {key_exc}")

    return {
        "ok": len(applied) > 0 and len(errors) == 0,
        "applied": applied,
        "rollback_changes": rollback_changes,
        "errors": errors,
        "warnings": warnings,
    }


def capture_full_preset_snapshot(lang: str = "ru") -> dict[str, Any]:
    """
    Capture a full restorable snapshot of current process, printer, multi-slot filament,
    and custom G-code settings for Preset Snapshots save/restore.
    """
    l = norm_lang(lang)
    presets = inspect_slicer_presets(lang=l, include_gcode=True)
    changes: list[dict[str, Any]] = []

    # Process & printer settings from flat_values
    for key, val in (presets.get("flat_values") or {}).items():
        info = FLAT_SETTING_INFO.get(key, {})
        cat = info.get("category", "process")
        if cat == "filament":
            continue
        changes.append({
            "category": cat,
            "key": key,
            "label": info.get(l) or key,
            "value": val,
        })

    # Per-slot filament settings
    _slot_key_map = (
        ("nozzle_temperature", "nozzle_temp"),
        ("nozzle_temperature_initial_layer", "nozzle_temp_initial"),
        ("hot_plate_temp", "hot_plate_temp"),
        ("textured_plate_temp", "textured_plate_temp"),
        ("cool_plate_temp", "cool_plate_temp"),
        ("eng_plate_temp", "eng_plate_temp"),
        ("filament_flow_ratio", "flow_ratio"),
        ("filament_max_volumetric_speed", "max_volumetric_speed"),
        ("enable_pressure_advance", "enable_pressure_advance"),
        ("pressure_advance", "pressure_advance"),
        ("fan_max_speed", "fan_max"),
        ("fan_min_speed", "fan_min"),
        ("close_fan_the_first_x_layers", "close_fan_first_layers"),
        ("slow_down_for_layer_cooling", "slow_down_for_layer_cooling"),
    )
    for slot_info in presets.get("filament_slots") or []:
        slot_num = int(slot_info.get("slot") or 1)
        for orca_key, field_name in _slot_key_map:
            val = str(slot_info.get(field_name) or "")
            if val != "":
                changes.append({
                    "category": "filament",
                    "slot": slot_num,
                    "key": orca_key,
                    "label": FLAT_SETTING_INFO.get(orca_key, {}).get(l) or orca_key,
                    "value": val,
                })
        if slot_info.get("start_gcode"):
            changes.append({
                "category": "filament",
                "slot": slot_num,
                "key": "filament_start_gcode",
                "label": CUSTOM_GCODE_KEYS["filament_start_gcode"].get(l, "filament_start_gcode"),
                "value": slot_info["start_gcode"],
            })
        if slot_info.get("end_gcode"):
            changes.append({
                "category": "filament",
                "slot": slot_num,
                "key": "filament_end_gcode",
                "label": CUSTOM_GCODE_KEYS["filament_end_gcode"].get(l, "filament_end_gcode"),
                "value": slot_info["end_gcode"],
            })

    # Printer & process custom G-code
    for gkey, gval in (presets.get("custom_gcode") or {}).items():
        gmeta = CUSTOM_GCODE_KEYS.get(gkey, {})
        gcat = gmeta.get("category", "printer")
        if gcat == "filament":
            continue
        changes.append({
            "category": gcat,
            "key": gkey,
            "label": gmeta.get(l) or gkey,
            "value": gval,
        })

    return {
        "captured_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "printer_preset": presets.get("printer_preset", ""),
        "process_preset": presets.get("process_preset", ""),
        "filament_presets": list(presets.get("filament_presets") or []),
        "filament_slots": list(presets.get("filament_slots") or []),
        "flat_values": dict(presets.get("flat_values") or {}),
        "custom_gcode": dict(presets.get("custom_gcode") or {}),
        "changes": changes,
    }
