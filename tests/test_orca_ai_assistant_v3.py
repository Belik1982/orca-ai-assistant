"""Comprehensive automated test suite for Orca AI Assistant v3.0.0.

Compatible with both ``pytest`` and ``python -m unittest discover -s tests -v``.
"""

from __future__ import annotations

import ast
import http.server
import json
import os
import re
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import types
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import orca_ai_assistant.orca_bridge.geometry as geometry_mod
from orca_ai_assistant.controller.controller import (
    AssistantController,
    load_asset,
    load_ui_html,
)
from orca_ai_assistant.controller.settings_parser import extract_suggested_settings
from orca_ai_assistant.core.constants import (
    PLUGIN_ID,
    PLUGIN_VERSION,
    RETIRED_MODEL_MIGRATIONS,
    detect_default_language,
    norm_lang,
)
from orca_ai_assistant.core.storage import StorageManager
from orca_ai_assistant.orca_bridge.enums import (
    CUSTOM_GCODE_KEYS,
    ENUM_VALID_VALUES,
    FLAT_SETTING_INFO,
    normalize_and_validate_setting,
    normalize_setting_category,
)
from orca_ai_assistant.orca_bridge.gcode_analyzer import (
    compute_slice_delta,
    summarize_gcode_file,
    summarize_gcode_text,
)
from orca_ai_assistant.orca_bridge.gcode_codec import (
    escape_orca_string,
    escape_orca_strings_single,
    lint_custom_gcode,
    make_unified_diff,
    unescape_orca_string,
    unescape_orca_strings_single,
)
from orca_ai_assistant.orca_bridge.preflight import run_preflight_checks
from orca_ai_assistant.orca_bridge.presets import (
    apply_settings_to_orcaslicer,
    capture_full_preset_snapshot,
    inspect_slicer_presets,
    read_live_setting_value,
)
from orca_ai_assistant.orca_bridge.prompts import (
    DEFECT_CATALOG,
    build_context_markdown,
    calculate_calibration_values,
    get_system_prompt,
)
from orca_ai_assistant.providers.client import (
    CancelToken,
    _sanitize_anthropic_messages,
    fetch_provider_models,
    send_chat_completion,
)
from orca_ai_assistant.providers.registry import PROVIDER_PRESETS, is_chat_model

HAS_NUMPY = geometry_mod.np is not None
HAS_NODE = shutil.which("node") is not None


# ============================================================================
# Mock OrcaSlicer Host Infrastructure
# ============================================================================

class FakePresetObj:
    def __init__(self, name: str, values: dict[str, Any], is_dirty: bool = False) -> None:
        self.name = name
        self._values = dict(values)
        self.is_dirty = is_dirty

    def config_value(self, key: str) -> Any:
        return self._values.get(key)

    def config_keys(self) -> list[str]:
        return list(self._values.keys())


class FakePresetTransaction:
    def __init__(self, store: dict[str, Any], fail_keys: set[str] | None = None) -> None:
        self._store = store
        self._fail_keys = fail_keys or set()
        self._staged: dict[str, str] = {}

    def set(self, key: str, value: str) -> None:
        self._staged[key] = value

    def commit(self) -> None:
        # Mirror OrcaSlicer.dll all-or-nothing batch validation on commit()
        for k in self._staged:
            if k in self._fail_keys:
                raise RuntimeError(f"OrcaSlicer rejected invalid key/value: {k}={self._staged[k]}")
        self._store.update(self._staged)


class FakePresetEditor:
    def __init__(self, targets: dict[int, dict[str, Any]], fail_keys: set[str] | None = None) -> None:
        self._targets = targets
        self._fail_keys = fail_keys or set()
        self.begin_calls: list[int] = []

    def begin_update(self, slot: int = 0) -> FakePresetTransaction:
        self.begin_calls.append(slot)
        store = self._targets.setdefault(slot, {})
        return FakePresetTransaction(store, fail_keys=self._fail_keys)


class FakeOrcaEnvironment:
    """In-memory mock of ``orca`` / ``orca.host`` matching OrcaSlicer 2.5.2 APIs."""

    def __init__(self, fail_keys: set[str] | None = None) -> None:
        self.fail_keys = set(fail_keys or ())
        self.process_values: dict[str, Any] = {
            "layer_height": "0.2",
            "initial_layer_print_height": "0.2",
            "wall_loops": "3",
            "top_shell_layers": "4",
            "bottom_shell_layers": "4",
            "sparse_infill_density": "15%",
            "sparse_infill_pattern": "gyroid",
            "enable_support": "0",
            "support_type": "normal(auto)",
            "brim_type": "no_brim",
            "wall_generator": "arachne",
            "outer_wall_speed": "120",
            "inner_wall_speed": "150",
            "sparse_infill_speed": "180",
            "default_acceleration": "3000",
        }
        self.printer_values: dict[str, Any] = {
            "printer_model": "Bambu Lab X1C",
            "gcode_flavor": "marlin2",
            "nozzle_diameter": "0.4",
            "curr_bed_type": "Textured PEI Plate",
            "retraction_length": "0.8",
            "z_hop_types": "Auto Lift",
            "machine_start_gcode": escape_orca_string("G28 ; home all\nG1 Z5 F3000\nM109 S[nozzle_temperature_initial_layer]"),
            "machine_end_gcode": escape_orca_string("M104 S0 ; nozzle off\nM140 S0 ; bed off\nG28 X Y"),
            "layer_change_gcode": escape_orca_string(";LAYER:[layer_num]"),
        }
        self.filament_slots: dict[int, dict[str, Any]] = {
            1: {
                "filament_type": "PLA",
                "filament_vendor": "Bambu",
                "nozzle_temperature": "215",
                "nozzle_temperature_initial_layer": "220",
                "hot_plate_temp": "55",
                "textured_plate_temp": "55",
                "filament_flow_ratio": "0.98",
                "filament_max_volumetric_speed": "21",
                "enable_pressure_advance": "1",
                "pressure_advance": "0.02",
                "fan_max_speed": "100",
                "fan_min_speed": "80",
                "close_fan_the_first_x_layers": "1",
                "slow_down_for_layer_cooling": "1",
                "filament_start_gcode": escape_orca_strings_single("; PLA Slot 1 start\nM900 K0.02 ; PA"),
                "filament_end_gcode": escape_orca_strings_single("; PLA Slot 1 end"),
            },
            2: {
                "filament_type": "PETG",
                "filament_vendor": "eSUN",
                "nozzle_temperature": "245",
                "nozzle_temperature_initial_layer": "250",
                "hot_plate_temp": "75",
                "textured_plate_temp": "75",
                "filament_flow_ratio": "0.95",
                "filament_max_volumetric_speed": "14",
                "enable_pressure_advance": "1",
                "pressure_advance": "0.035",
                "fan_max_speed": "60",
                "fan_min_speed": "30",
                "close_fan_the_first_x_layers": "2",
                "slow_down_for_layer_cooling": "1",
                "filament_start_gcode": escape_orca_strings_single("; PETG Slot 2 start\nM900 K0.035 ; PA"),
                "filament_end_gcode": escape_orca_strings_single("; PETG Slot 2 end"),
            },
            3: {
                "filament_type": "PLA",
                "filament_vendor": "Sunlu",
                "nozzle_temperature": "210",
                "nozzle_temperature_initial_layer": "215",
                "hot_plate_temp": "60",
                "textured_plate_temp": "60",
                "filament_flow_ratio": "0.97",
                "filament_max_volumetric_speed": "18",
                "enable_pressure_advance": "0",
                "pressure_advance": "0.025",
                "fan_max_speed": "100",
                "fan_min_speed": "70",
                "close_fan_the_first_x_layers": "1",
                "slow_down_for_layer_cooling": "1",
                "filament_start_gcode": escape_orca_strings_single("; Slot 3 start\nM900 K0.025"),
                "filament_end_gcode": escape_orca_strings_single("; Slot 3 end"),
            },
            4: {
                "filament_type": "TPU",
                "filament_vendor": "Generic",
                "nozzle_temperature": "225",
                "nozzle_temperature_initial_layer": "230",
                "hot_plate_temp": "40",
                "textured_plate_temp": "40",
                "filament_flow_ratio": "1.02",
                "filament_max_volumetric_speed": "3.5",
                "enable_pressure_advance": "0",
                "pressure_advance": "0",
                "fan_max_speed": "80",
                "fan_min_speed": "50",
                "close_fan_the_first_x_layers": "1",
                "slow_down_for_layer_cooling": "1",
                "filament_start_gcode": "",
                "filament_end_gcode": "",
            },
        }
        self.filament_names = ["Bambu PLA Basic", "eSUN PETG Black", "Sunlu PLA Matte", "Generic TPU 95A"]

        self.process_editor = FakePresetEditor({0: self.process_values}, fail_keys=self.fail_keys)
        self.printer_editor = FakePresetEditor({0: self.printer_values}, fail_keys=self.fail_keys)
        self.filament_editor = FakePresetEditor(self.filament_slots, fail_keys=self.fail_keys)

        self.notifications: list[tuple[Any, ...]] = []
        self.orca = self._build_orca_module()

    def _build_orca_module(self) -> types.SimpleNamespace:
        env = self

        class _Bundle:
            def current_printer_preset(self) -> FakePresetObj:
                return FakePresetObj("Bambu Lab X1C 0.4 nozzle", env.printer_values)

            def current_process_preset(self) -> FakePresetObj:
                return FakePresetObj("0.20mm Standard @BBL X1C", env.process_values)

            def current_filament_preset_names(self) -> list[str]:
                return list(env.filament_names)

            def current_filament_presets(self) -> list[FakePresetObj]:
                return [
                    FakePresetObj(env.filament_names[i - 1], env.filament_slots[i])
                    for i in sorted(env.filament_slots)
                ]

            def full_config_value(self, key: str) -> Any:
                if key in env.process_values:
                    return env.process_values[key]
                if key in env.printer_values:
                    return env.printer_values[key]
                if key in env.filament_slots[1]:
                    return env.filament_slots[1][key]
                return None

        bundle = _Bundle()
        preset_ns = types.SimpleNamespace(
            process=self.process_editor,
            printer=self.printer_editor,
            filament=self.filament_editor,
        )
        ui_ns = types.SimpleNamespace(
            NotificationLevel=types.SimpleNamespace(Warning=5, Info=1),
            push_notification=lambda *args: env.notifications.append(args),
        )
        host_ns = types.SimpleNamespace(
            preset_bundle=lambda: bundle,
            preset=preset_ns,
            ui=ui_ns,
            app_info=lambda: {"version": "2.5.2", "build": "test", "language": "en_US", "mode": "dark"},
            selected_printer=lambda: {"model_id": "X1C", "connection": "lan", "online": True, "connected": True},
        )
        return types.SimpleNamespace(host=host_ns)


class RecordingView:
    def __init__(self, open_state: bool = True) -> None:
        self.messages: list[dict[str, Any]] = []
        self._open = open_state

    def is_open(self) -> bool:
        return self._open

    def post_message(self, payload: dict[str, Any]) -> None:
        if not self._open:
            raise RuntimeError("View is closed")
        self.messages.append(payload)


def _wait_until(predicate, timeout: float = 4.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# ============================================================================
# 1. Cross-Layer IPC, Locale & Import Contract Audit
# ============================================================================

class TestCrossLayerContracts(unittest.TestCase):
    def test_every_frontend_send_action_handled_in_controller(self) -> None:
        ui_dir = SRC_DIR / "orca_ai_assistant" / "ui"
        app_js = (ui_dir / "app.js").read_text(encoding="utf-8")
        tpl_html = (ui_dir / "template.html").read_text(encoding="utf-8")
        ctrl_py = (SRC_DIR / "orca_ai_assistant" / "controller" / "controller.py").read_text(encoding="utf-8")

        js_actions = set(re.findall(r'sendAction\(\s*["\']([^"\']+)["\']', app_js))
        html_actions = set(re.findall(r'sendAction\(\s*["\']([^"\']+)["\']', tpl_html))
        all_ui_actions = js_actions | html_actions

        py_actions = set(re.findall(r'action\s*==\s*["\']([^"\']+)["\']', ctrl_py))
        for m in re.finditer(r"action\s+in\s*\(([^)]+)\)", ctrl_py):
            py_actions.update(re.findall(r'["\']([^"\']+)["\']', m.group(1)))

        missing = sorted(all_ui_actions - py_actions)
        self.assertEqual(missing, [], f"UI actions missing in controller.py: {missing}")

        # Verify critical payload field names exist on both sides
        required_fields = [
            "allow_gcode",
            "include_gcode",
            "request_id",
            "chat_id",
            "card_id",
            "record_id",
            "snap_id",
            "stage",
            "measurements",
            "slot",
            "symptom_id",
            "ask_ai",
            "key_source",
            "compact_context",
        ]
        for field in required_fields:
            self.assertIn(field, app_js, f"Expected payload field '{field}' in app.js")
            self.assertIn(field, ctrl_py, f"Expected payload field '{field}' in controller.py")

    def test_every_controller_emitted_type_handled_in_frontend(self) -> None:
        app_js = (SRC_DIR / "orca_ai_assistant" / "ui" / "app.js").read_text(encoding="utf-8")
        ctrl_py = (SRC_DIR / "orca_ai_assistant" / "controller" / "controller.py").read_text(encoding="utf-8")

        py_types = set(re.findall(r'"type"\s*:\s*"([^"]+)"', ctrl_py))
        js_types = set(re.findall(r'msg\.type\s*===\s*"([^"]+)"', app_js))

        self.assertEqual(sorted(py_types - js_types), [], "Controller emitted types missing in app.js")
        self.assertEqual(sorted(js_types - py_types), [], "Frontend handles unknown types not emitted by controller")

    def test_locales_valid_parity_and_all_ui_keys_present(self) -> None:
        loc_dir = SRC_DIR / "orca_ai_assistant" / "assets" / "locales"
        locales: dict[str, dict[str, str]] = {}
        for code in ("ru", "uk", "en"):
            data = json.loads((loc_dir / f"{code}.json").read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)
            self.assertGreater(len(data), 250)
            locales[code] = data

        self.assertEqual(set(locales["en"]), set(locales["ru"]))
        self.assertEqual(set(locales["en"]), set(locales["uk"]))

        ui_dir = SRC_DIR / "orca_ai_assistant" / "ui"
        html = (ui_dir / "template.html").read_text(encoding="utf-8")
        app_js = (ui_dir / "app.js").read_text(encoding="utf-8")
        md_js = (ui_dir / "markdown.js").read_text(encoding="utf-8")

        used_keys: set[str] = set()
        used_keys.update(re.findall(r'data-i18n(?:-(?:placeholder|title))?="([^"]+)"', html))
        for k in re.findall(r'\bt\(\s*["\']([^"\']+)["\']', app_js):
            if not k.endswith("_"):
                used_keys.add(k)
        used_keys.update(re.findall(r'_mdLabel\(\s*["\']([^"\']+)["\']', md_js))
        used_keys.update(re.findall(r'i18n:\s*["\']([^"\']+)["\']', app_js))
        used_keys.update(re.findall(r'descKey:\s*["\']([^"\']+)["\']', app_js))
        for defect in DEFECT_CATALOG:
            used_keys.add(f"def_name_{defect['id']}")
            used_keys.add(f"def_desc_{defect['id']}")

        for code in ("ru", "uk", "en"):
            missing = sorted(used_keys - set(locales[code]))
            self.assertEqual(missing, [], f"Missing i18n keys in {code}.json: {missing}")

    def test_icon_svg_and_cross_module_imports(self) -> None:
        svg_text = load_asset("assets/icon.svg")
        root = ET.fromstring(svg_text)
        self.assertTrue(root.tag.endswith("svg"))

        pkg_root = SRC_DIR / "orca_ai_assistant"
        for py_file in sorted(pkg_root.rglob("*.py")):
            if "__pycache__" in py_file.parts:
                continue
            ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))

        # Verify all submodules import cleanly
        import importlib

        for mod_name in (
            "orca_ai_assistant",
            "orca_ai_assistant.core",
            "orca_ai_assistant.core.constants",
            "orca_ai_assistant.core.storage",
            "orca_ai_assistant.providers",
            "orca_ai_assistant.providers.registry",
            "orca_ai_assistant.providers.client",
            "orca_ai_assistant.orca_bridge",
            "orca_ai_assistant.orca_bridge.enums",
            "orca_ai_assistant.orca_bridge.gcode_codec",
            "orca_ai_assistant.orca_bridge.presets",
            "orca_ai_assistant.orca_bridge.geometry",
            "orca_ai_assistant.orca_bridge.preflight",
            "orca_ai_assistant.orca_bridge.gcode_analyzer",
            "orca_ai_assistant.orca_bridge.prompts",
            "orca_ai_assistant.controller",
            "orca_ai_assistant.controller.settings_parser",
            "orca_ai_assistant.controller.controller",
        ):
            mod = importlib.import_module(mod_name)
            self.assertIsNotNone(mod)


# ============================================================================
# 2. User Bug #1 — Custom G-code Access, Codec, Safety Linter & Gate
# ============================================================================

class TestCustomGcodeBug1(unittest.TestCase):
    def test_costring_and_costrings_roundtrip_and_semicolon_quoting(self) -> None:
        raw_printer = 'G28 ; home axes\nM117 "Printing"\n; literal backslash \\n check\nG1 Z5 F3000'
        encoded_str = escape_orca_string(raw_printer)
        self.assertNotIn("\n", encoded_str)
        self.assertIn("\\n", encoded_str)
        self.assertIn("\\\\n", encoded_str)
        self.assertEqual(unescape_orca_string(encoded_str), raw_printer)

        # coStrings MUST wrap in double quotes so OrcaSlicer never splits on G-code ';' comments!
        raw_filament = '; filament start; keep semicolon\nM900 K0.03 ; PA\nM106 S0'
        encoded_vec = escape_orca_strings_single(raw_filament)
        self.assertTrue(encoded_vec.startswith('"') and encoded_vec.endswith('"'))
        self.assertEqual(unescape_orca_strings_single(encoded_vec), raw_filament)

        # Ensure key metadata distinguishes coString vs coStrings
        self.assertFalse(CUSTOM_GCODE_KEYS["machine_start_gcode"]["is_vector"])
        self.assertTrue(CUSTOM_GCODE_KEYS["filament_start_gcode"]["is_vector"])
        self.assertTrue(CUSTOM_GCODE_KEYS["filament_end_gcode"]["is_vector"])

    def test_static_gcode_safety_linter_and_unified_diff(self) -> None:
        # Empty wipe -> danger
        empty_w = lint_custom_gcode("machine_start_gcode", "   \n  ", lang="en", old_text="G28")
        self.assertTrue(any(w["level"] == "danger" for w in empty_w))

        # Motion before G28 -> danger
        crash_w = lint_custom_gcode("machine_start_gcode", "G1 X50 Y50 F3000\nG28", lang="en")
        self.assertTrue(any(w["level"] == "danger" and "BEFORE" in w["text"] for w in crash_w))

        # Missing G28 -> danger
        no_home_w = lint_custom_gcode("machine_start_gcode", "M104 S210\nM140 S60", lang="en")
        self.assertTrue(any(w["level"] == "danger" and "G28" in w["text"] for w in no_home_w))

        # Safe start G-code -> 0 warnings
        safe_start = lint_custom_gcode("machine_start_gcode", "G28 ; home\nG1 Z5 F3000\nM109 S215", lang="en")
        self.assertEqual(safe_start, [])

        # End G-code missing heaters off -> danger (nozzle) + warn (bed)
        unsafe_end = lint_custom_gcode("machine_end_gcode", "G1 Z100 F3000\nM84", lang="en")
        levels = {w["level"] for w in unsafe_end}
        self.assertIn("danger", levels)
        self.assertIn("warn", levels)

        # Safe end G-code -> 0 warnings
        safe_end = lint_custom_gcode("machine_end_gcode", "M104 S0\nM140 S0\nG28 X Y", lang="en")
        self.assertEqual(safe_end, [])

        # Extreme temperatures -> danger for both nozzle >320 and bed >130
        hot_w = lint_custom_gcode("machine_start_gcode", "G28\nM109 S360\nM190 S150", lang="en")
        danger_texts = [w["text"] for w in hot_w if w["level"] == "danger"]
        self.assertTrue(any("360" in t for t in danger_texts))
        self.assertTrue(any("150" in t for t in danger_texts))

        # Unbalanced OrcaSlicer brackets -> warn
        br_w = lint_custom_gcode("layer_change_gcode", ";LAYER:[layer_num\n{if layer_num > 1", lang="en")
        self.assertEqual(len(br_w), 2)
        self.assertTrue(all(w["level"] == "warn" for w in br_w))

        # Unified diff
        diff = make_unified_diff("G28\nG1 Z5", "G28\nG29\nG1 Z5", label="machine_start_gcode")
        self.assertIn("--- machine_start_gcode (current)", diff)
        self.assertIn("+++ machine_start_gcode (proposed)", diff)
        self.assertIn("+G29", diff)
        self.assertEqual(make_unified_diff("G28", "G28"), "")

    def test_gcode_read_parse_and_allow_gcode_safety_gate(self) -> None:
        env = FakeOrcaEnvironment()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.orca_bridge.presets.orca", env.orca), \
             mock.patch("orca_ai_assistant.controller.controller.orca", env.orca):
            presets = inspect_slicer_presets("en", include_gcode=True)
            self.assertIn("G28 ; home all\nG1 Z5 F3000", presets["custom_gcode"]["machine_start_gcode"])
            self.assertIn("M104 S0", presets["custom_gcode"]["machine_end_gcode"])
            self.assertIn(";LAYER:[layer_num]", presets["custom_gcode"]["layer_change_gcode"])
            self.assertIn("M900 K0.035 ; PA", presets["filament_slots"][1]["start_gcode"])

            # Parse block containing multiline raw newline & trailing comma in custom G-code
            ai_reply = (
                "Here is the updated start G-code:\n"
                "```orca-settings\n"
                "[\n"
                '  {"category": "printer", "key": "machine_start_gcode", '
                '"value": "G28 ; home\nG29 ; bed mesh\nG1 Z5 F3000", "reason": "Add bed mesh"},\n'
                '  {"category": "filament", "slot": 2, "key": "filament_start_gcode", '
                '"value": "; PETG S2\nM900 K0.04 ; tuned", "reason": "Tune PA"},\n'
                "]\n"
                "```"
            )
            parsed = extract_suggested_settings(ai_reply, presets, lang="en")
            self.assertEqual(parsed["parse_error"], "")
            self.assertEqual(parsed["suggestions"], [])
            self.assertEqual(len(parsed["gcode_changes"]), 2)
            self.assertIn("+G29 ; bed mesh", parsed["gcode_changes"][0]["diff"])
            self.assertEqual(parsed["gcode_changes"][1]["slot"], 2)

            # Controller allow_gcode gate
            ctrl = AssistantController(storage=StorageManager(td))
            view = RecordingView()
            ctrl.register_page(view)

            # 1) Blocked when allow_gcode=False
            ctrl.handle_message_on_ui(
                {
                    "action": "apply_settings",
                    "changes": parsed["gcode_changes"],
                    "allow_gcode": False,
                    "card_id": "gc_0",
                },
                source_view=view,
            )
            self.assertTrue(_wait_until(lambda: any(m.get("type") == "settings_applied" for m in view.messages)))
            blocked = [m for m in view.messages if m.get("type") == "settings_applied"][-1]
            self.assertFalse(blocked["ok"])
            self.assertTrue(blocked.get("gcode_confirmation_required"))
            self.assertNotIn("G29", unescape_orca_string(env.printer_values["machine_start_gcode"]))

            # 2) Allowed when allow_gcode=True
            view.messages.clear()
            ctrl.handle_message_on_ui(
                {
                    "action": "apply_settings",
                    "changes": parsed["gcode_changes"],
                    "allow_gcode": True,
                    "card_id": "gc_0",
                },
                source_view=view,
            )
            self.assertTrue(_wait_until(lambda: any(m.get("type") == "settings_applied" for m in view.messages)))
            applied_evt = [m for m in view.messages if m.get("type") == "settings_applied"][-1]
            self.assertTrue(applied_evt["ok"])
            self.assertEqual(applied_evt["card_id"], "gc_0")
            self.assertTrue(applied_evt["record_id"])
            self.assertIn("G29 ; bed mesh", unescape_orca_string(env.printer_values["machine_start_gcode"]))
            # Verify coStrings slot 2 was quoted with ";" intact!
            raw_slot2_wire = env.filament_slots[2]["filament_start_gcode"]
            self.assertTrue(raw_slot2_wire.startswith('"') and raw_slot2_wire.endswith('"'))
            self.assertEqual(unescape_orca_strings_single(raw_slot2_wire), "; PETG S2\nM900 K0.04 ; tuned")


# ============================================================================
# 3. User Bug #2 — Dock Panel UX & View Isolation
# ============================================================================

class TestDockPanelBug2(unittest.TestCase):
    def test_load_ui_html_dock_vs_page_and_no_placeholders(self) -> None:
        dock_html = load_ui_html("dock")
        page_html = load_ui_html("page")

        self.assertIn('data-view="dock"', dock_html)
        self.assertIn('data-view="page"', page_html)

        for placeholder in (
            "__VIEW_MODE__",
            "__INLINE_CSS__",
            "__INLINE_LOCALES__",
            "__INLINE_MARKDOWN_JS__",
            "__INLINE_APP_JS__",
        ):
            self.assertNotIn(placeholder, dock_html)
            self.assertNotIn(placeholder, page_html)

        # Dock controls present
        self.assertIn('id="btnDockNewChat"', dock_html)
        self.assertIn('onclick="createNewChat()"', dock_html)
        self.assertIn('id="btnDockHistory"', dock_html)
        self.assertIn('id="historyDrawer"', dock_html)
        self.assertIn('id="drawerSessionList"', dock_html)

        # CSS hides redundant Dock button and desktop chrome in dock mode
        self.assertRegex(dock_html, r'html\[data-view="dock"\][^{]*#btnOpenDock[^{]*\{\s*display:\s*none\s*!important;')
        self.assertIn('html[data-view="dock"] .dock-header { display: flex; }', dock_html)
        self.assertIn('html[data-view="dock"] .settings-stacked-list { display: flex; }', dock_html)

    def test_tab_and_dock_init_isolation_and_dead_view_pruning(self) -> None:
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.controller.controller.inspect_plate_geometry", return_value={"has_model": False, "objects": [], "warnings": []}), \
             mock.patch("orca_ai_assistant.controller.controller.inspect_slicer_presets", return_value={"groups": {}, "flat_values": {}, "filament_slots": [], "custom_gcode": {}}):
            ctrl = AssistantController(storage=StorageManager(td))
            page_view = RecordingView(open_state=True)
            dock_view = RecordingView(open_state=True)
            dead_view = RecordingView(open_state=False)

            ctrl.register_page(page_view)
            ctrl.register_page(dead_view)
            ctrl._dock_panel = dock_view

            # Dock sends init -> ONLY dock receives full_state (page stream is never wiped!)
            ctrl.handle_message_on_ui({"action": "init"}, source_view=dock_view)
            self.assertEqual(len(dock_view.messages), 1)
            self.assertEqual(dock_view.messages[0]["type"], "full_state")
            self.assertEqual(len(page_view.messages), 0)

            # save_settings broadcasts to all open views and prunes dead views
            ctrl.handle_message_on_ui({"action": "save_settings", "settings": {"compact_context": False}}, source_view=dock_view)
            self.assertEqual(len(page_view.messages), 1)
            self.assertEqual(page_view.messages[0]["type"], "settings_updated")
            self.assertNotIn(dead_view, ctrl._page_views)


# ============================================================================
# 4. User Bug #3 — Enum Normalization, Batch Fallback & Undo
# ============================================================================

class TestEnumValidationAndUndoBug3(unittest.TestCase):
    def test_enum_normalization_category_and_rejection(self) -> None:
        self.assertGreaterEqual(len(ENUM_VALID_VALUES), 24)
        self.assertEqual(FLAT_SETTING_INFO["slow_down_for_layer_cooling"]["category"], "filament")
        self.assertEqual(normalize_setting_category("slow_down_for_layer_cooling", "process"), "filament")

        val, note, err = normalize_and_validate_setting("sparse_infill_pattern", "cross_hatch")
        self.assertEqual(val, "crosshatch")
        self.assertIsNotNone(note)
        self.assertIsNone(err)

        val, note, err = normalize_and_validate_setting("support_type", "tree")
        self.assertEqual(val, "tree(auto)")
        self.assertIsNone(err)

        val, note, err = normalize_and_validate_setting("support_type", "normal")
        self.assertEqual(val, "normal(auto)")
        self.assertIsNone(err)

        val, _, err = normalize_and_validate_setting("z_hop_types", "auto_lift")
        self.assertEqual(val, "Auto Lift")
        self.assertIsNone(err)

        val, _, err = normalize_and_validate_setting("sparse_infill_density", "25")
        self.assertEqual(val, "25%")
        self.assertIsNone(err)

        val, _, err = normalize_and_validate_setting("fan_max_speed", "85%")
        self.assertEqual(val, "85")
        self.assertIsNone(err)

        val, _, err = normalize_and_validate_setting("enable_support", "true")
        self.assertEqual(val, "1")
        self.assertIsNone(err)

        # Unknown enum rejected with valid list
        _, _, err = normalize_and_validate_setting("sparse_infill_pattern", "magical_unicorn_pattern")
        self.assertIsNotNone(err)
        self.assertIn("crosshatch", err or "")

        # Deprecated key rejected
        _, _, err = normalize_and_validate_setting("overhang_speed_classic", "1")
        self.assertIsNotNone(err)
        self.assertIn("enable_overhang_speed", err or "")

    def test_batch_rollback_per_key_fallback_and_undo_apply(self) -> None:
        # Force OrcaSlicer commit() to reject 'wall_loops' while accepting other process keys
        env = FakeOrcaEnvironment(fail_keys={"wall_loops"})
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.orca_bridge.presets.orca", env.orca), \
             mock.patch("orca_ai_assistant.controller.controller.orca", env.orca):
            res = apply_settings_to_orcaslicer(
                [
                    {"category": "process", "key": "sparse_infill_pattern", "value": "cross_hatch"},
                    {"category": "process", "key": "support_type", "value": "tree"},
                    {"category": "process", "key": "wall_loops", "value": "4"},
                ],
                lang="en",
            )
            # Valid keys committed via per-key fallback; bad key reported in errors
            self.assertFalse(res["ok"])
            applied_keys = {a["key"] for a in res["applied"]}
            self.assertEqual(applied_keys, {"sparse_infill_pattern", "support_type"})
            self.assertEqual(env.process_values["sparse_infill_pattern"], "crosshatch")
            self.assertEqual(env.process_values["support_type"], "tree(auto)")
            self.assertEqual(env.process_values["wall_loops"], "3")  # unchanged
            self.assertTrue(any("wall_loops" in e for e in res["errors"]))
            self.assertEqual(len(res["rollback_changes"]), 2)

            # Now test full controller apply + undo_apply + snapshot save/restore
            env.fail_keys.clear()
            env.process_editor._fail_keys.clear()
            ctrl = AssistantController(storage=StorageManager(td))
            view = RecordingView()
            ctrl.register_page(view)

            # Save snapshot before changes
            ctrl.handle_message_on_ui({"action": "save_snapshot", "name": "Baseline"}, source_view=view)
            snaps = ctrl.storage.get_snapshots()
            self.assertEqual(len(snaps), 1)
            snap_id = snaps[0]["id"]

            # Apply change
            view.messages.clear()
            ctrl.handle_message_on_ui(
                {
                    "action": "apply_settings",
                    "changes": [{"category": "process", "key": "layer_height", "value": "0.12"}],
                    "card_id": "sug_0",
                },
                source_view=view,
            )
            self.assertTrue(_wait_until(lambda: any(m.get("type") == "settings_applied" for m in view.messages)))
            self.assertEqual(env.process_values["layer_height"], "0.12")
            rec_id = [m for m in view.messages if m.get("type") == "settings_applied"][-1]["record_id"]
            self.assertTrue(rec_id)

            # Undo by record_id -> restores 0.2
            view.messages.clear()
            ctrl.handle_message_on_ui({"action": "undo_apply", "record_id": rec_id}, source_view=view)
            self.assertTrue(_wait_until(lambda: any(m.get("type") == "settings_applied" and m.get("undone") for m in view.messages)))
            self.assertEqual(env.process_values["layer_height"], "0.2")

            # Mutate then restore snapshot -> restores Baseline
            env.process_values["layer_height"] = "0.28"
            view.messages.clear()
            ctrl.handle_message_on_ui({"action": "restore_snapshot", "snap_id": snap_id}, source_view=view)
            self.assertTrue(_wait_until(lambda: any(m.get("type") == "settings_applied" for m in view.messages)))
            self.assertEqual(env.process_values["layer_height"], "0.2")

            # Delete snapshot
            ctrl.handle_message_on_ui({"action": "delete_snapshot", "snap_id": snap_id}, source_view=view)
            self.assertEqual(ctrl.storage.get_snapshots(), [])


# ============================================================================
# 5. P0 Critical Fixes (Busy Lock, Stream Isolation, CancelToken, Fast Clicks, AMS, Capability Names)
# ============================================================================

class TestP0CriticalFixes(unittest.TestCase):
    def test_zero_geometry_scans_on_fast_ui_clicks(self) -> None:
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.controller.controller.inspect_plate_geometry") as mock_geo, \
             mock.patch("orca_ai_assistant.controller.controller.inspect_slicer_presets", return_value={"groups": {}, "flat_values": {}, "filament_slots": [], "custom_gcode": {}}):
            ctrl = AssistantController(storage=StorageManager(td))
            view = RecordingView()
            ctrl.register_page(view)

            fast_actions = [
                {"action": "save_settings", "settings": {"compact_context": True}},
                {"action": "new_chat", "title": "Chat 2"},
                {"action": "rename_chat", "chat_id": ctrl.storage.get_chats()["active_id"], "title": "Renamed"},
                {"action": "select_chat", "chat_id": ctrl.storage.get_chats()["sessions"][0]["id"]},
                {"action": "clear_chat"},
                {"action": "delete_chat", "chat_id": ctrl.storage.get_chats()["sessions"][0]["id"]},
                {"action": "stop_generation"},
                {"action": "calc_calibration", "stage": "flow_rate", "slot": 1, "measurements": {"old_flow": 0.98, "modifier": 5}},
                {"action": "save_snapshot", "name": "FastSnap"},
            ]
            for msg in fast_actions:
                ctrl.handle_message_on_ui(msg, source_view=view)

            self.assertEqual(mock_geo.call_count, 0, "Fast UI clicks must NEVER trigger inspect_plate_geometry()")

    def test_active_request_id_busy_lock_and_midstream_chat_switch_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.controller.controller.inspect_plate_geometry", return_value={"has_model": False, "objects": [], "warnings": []}), \
             mock.patch("orca_ai_assistant.controller.controller.inspect_slicer_presets", return_value={"groups": {}, "flat_values": {}, "filament_slots": [], "custom_gcode": {}}):
            storage = StorageManager(td)
            storage.update_settings({"provider": "openai", "model": "gpt-5.2", "api_keys": {"openai": "sk-test"}})
            chat_a = storage.get_chats()["active_id"]
            chat_b, _ = storage.create_chat("Chat B")
            # Switch back to Chat A before sending
            chats = storage.get_chats()
            chats["active_id"] = chat_a
            storage.save_chats(chats)

            ctrl = AssistantController(storage=storage)
            view = RecordingView()
            ctrl.register_page(view)

            stream_started = threading.Event()
            allow_finish = threading.Event()

            def fake_completion(**kwargs: Any) -> dict[str, Any]:
                on_chunk = kwargs.get("on_chunk")
                if callable(on_chunk):
                    on_chunk("Partial chunk for A")
                stream_started.set()
                allow_finish.wait(timeout=3.0)
                return {
                    "ok": True,
                    "reply": "Final reply strictly for Chat A",
                    "reasoning": "",
                    "model": "gpt-5.2",
                    "usage": {"input_tokens": 120, "output_tokens": 45},
                }

            with mock.patch("orca_ai_assistant.controller.controller.send_chat_completion", side_effect=fake_completion):
                ctrl.handle_message_on_ui(
                    {"action": "send_chat", "text": "Hello A", "chat_id": chat_a, "request_id": "req_A1", "attach_context": False},
                    source_view=view,
                )
                self.assertTrue(stream_started.wait(timeout=2.0))

                # Initial chats_updated MUST carry active_request_id == "req_A1" (P0 #1 busy lock!)
                first_upd = [m for m in view.messages if m.get("type") == "chats_updated"][0]
                self.assertEqual(first_upd["active_request_id"], "req_A1")

                # Stream chunk MUST carry request_id & chat_id == chat_a
                chunks = [m for m in view.messages if m.get("type") == "stream_chunk"]
                self.assertTrue(chunks)
                self.assertEqual(chunks[0]["request_id"], "req_A1")
                self.assertEqual(chunks[0]["chat_id"], chat_a)

                # User switches to Chat B MID-STREAM!
                ctrl.handle_message_on_ui({"action": "select_chat", "chat_id": chat_b}, source_view=view)
                switch_upd = [m for m in view.messages if m.get("type") == "chats_updated"][-1]
                self.assertEqual(switch_upd["chats"]["active_id"], chat_b)
                self.assertEqual(switch_upd["active_request_id"], "")

                # Allow Chat A stream to finish
                allow_finish.set()
                self.assertTrue(
                    _wait_until(
                        lambda: any(
                            s["id"] == chat_a and len(s["messages"]) == 2
                            for s in storage.get_chats()["sessions"]
                        )
                    )
                )

                final_chats = storage.get_chats()
                sess_a = next(s for s in final_chats["sessions"] if s["id"] == chat_a)
                sess_b = next(s for s in final_chats["sessions"] if s["id"] == chat_b)
                self.assertEqual(final_chats["active_id"], chat_b)
                self.assertEqual(len(sess_b["messages"]), 0, "Chat B must NOT be polluted by Chat A's reply!")
                self.assertEqual(sess_a["messages"][-1]["content"], "Final reply strictly for Chat A")

    def test_cancel_token_aborts_live_sse_socket(self) -> None:
        streaming_ready = threading.Event()
        release_server = threading.Event()

        class SlowSSEHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if length:
                    self.rfile.read(length)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                chunk = json.dumps({"choices": [{"delta": {"content": "Hello "}}]})
                try:
                    self.wfile.write(f"data: {chunk}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    streaming_ready.set()
                    # Block server socket until test ends (would hang 10s without socket shutdown)
                    release_server.wait(timeout=10.0)
                except OSError:
                    pass

        class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True

        server = ThreadedHTTPServer(("127.0.0.1", 0), SlowSSEHandler)
        port = server.server_address[1]
        srv_thread = threading.Thread(target=server.serve_forever, daemon=True)
        srv_thread.start()

        try:
            token = CancelToken()
            result_box: dict[str, Any] = {}
            received_chunks: list[str] = []

            def run_req() -> None:
                result_box["res"] = send_chat_completion(
                    provider="custom",
                    base_url=f"http://127.0.0.1:{port}/v1",
                    api_key="test-key",
                    model_id="test-model",
                    messages=[{"role": "user", "content": "Hi"}],
                    system_prompt="System",
                    on_chunk=lambda t: received_chunks.append(t),
                    cancel_token=token,
                    timeout=10.0,
                )

            t0 = time.monotonic()
            worker = threading.Thread(target=run_req, daemon=True)
            worker.start()
            self.assertTrue(streaming_ready.wait(timeout=3.0))
            time.sleep(0.05)
            cancel_start = time.monotonic()
            token.cancel()
            worker.join(timeout=2.5)
            abort_elapsed = time.monotonic() - cancel_start

            self.assertFalse(worker.is_alive(), "Worker thread must exit promptly upon CancelToken.cancel()")
            self.assertLess(abort_elapsed, 2.0)
            self.assertTrue(result_box.get("res", {}).get("cancelled"))
        finally:
            release_server.set()
            server.shutdown()
            server.server_close()

    def test_multi_slot_ams_read_parse_and_apply(self) -> None:
        env = FakeOrcaEnvironment()
        with mock.patch("orca_ai_assistant.orca_bridge.presets.orca", env.orca):
            presets = inspect_slicer_presets("en", include_gcode=True)
            self.assertEqual(len(presets["filament_slots"]), 4)
            self.assertEqual(presets["filament_slots"][0]["type"], "PLA")
            self.assertEqual(presets["filament_slots"][1]["type"], "PETG")
            self.assertEqual(presets["filament_slots"][2]["nozzle_temp"], "210")
            self.assertEqual(presets["filament_slots"][3]["type"], "TPU")

            # Live read targets slot 3 specifically
            self.assertEqual(read_live_setting_value("nozzle_temperature", "filament", slot=3), "210")
            self.assertEqual(read_live_setting_value("nozzle_temperature", "filament", slot=2), "245")

            # Parser preserves slot=3 and resolves slot 3's current value (210, NOT slot 1's 215!)
            reply = '```orca-settings\n[{"category": "filament", "slot": 3, "key": "nozzle_temperature", "value": "205", "reason": "Cooler Slot 3"}]\n```'
            parsed = extract_suggested_settings(reply, presets, lang="en")
            self.assertEqual(len(parsed["suggestions"]), 1)
            sug = parsed["suggestions"][0]
            self.assertEqual(sug["slot"], 3)
            self.assertEqual(sug["current_value"], "210")

            # Apply commits strictly to slot 3 via begin_update(3)
            res = apply_settings_to_orcaslicer(parsed["suggestions"], lang="en")
            self.assertTrue(res["ok"])
            self.assertIn(3, env.filament_editor.begin_calls)
            self.assertEqual(env.filament_slots[3]["nozzle_temperature"], "205")
            self.assertEqual(env.filament_slots[1]["nozzle_temperature"], "215")  # Slot 1 untouched

    def test_stable_capability_names_independent_of_language(self) -> None:
        # Execute isolated import with mocked orca module and verify stable names across RU/UK/EN
        script = r"""
import sys, types, pathlib
sys.path.insert(0, r"%s")

registered_caps = []
requested_perms = []

class FakeBase:
    pass
class FakePagesBase:
    pass
class FakeScriptBase:
    pass
class FakePipelineBase:
    pass

orca_mod = types.ModuleType("orca")
orca_mod.base = FakeBase
orca_mod.plugin = lambda cls: cls
orca_mod.request_permissions = lambda **kw: requested_perms.append(kw)
orca_mod.register_capability = lambda cls: registered_caps.append(cls)
orca_mod.ExecutionResult = types.SimpleNamespace(success=lambda msg="": ("ok", msg))
orca_mod.pages = types.SimpleNamespace(PagesPluginCapabilityBase=FakePagesBase)
orca_mod.script = types.SimpleNamespace(ScriptPluginCapabilityBase=FakeScriptBase)
orca_mod.slicing = types.SimpleNamespace(
    SlicingPipelineCapabilityBase=FakePipelineBase,
    Step=types.SimpleNamespace(psGCodePostProcess=7),
)
orca_mod.host = types.SimpleNamespace(
    app_info=lambda: {"language": "ru_RU"},
)
sys.modules["orca"] = orca_mod
sys.modules["orca.host"] = orca_mod.host

import orca_ai_assistant as pkg
plugin = pkg.OrcaAIAssistantPlugin()
plugin.register_capabilities()
names = [cls().get_name() for cls in registered_caps]
assert names == ["Orca AI Assistant", "Orca AI: Dock Panel", "Orca AI: G-code Audit"], names
assert requested_perms and requested_perms[0]["threading"] is True
assert len(requested_perms[0]["network_http"]) == 13
print("STABLE_CAPS_OK")
""" % str(SRC_DIR)
        with tempfile.TemporaryDirectory() as td:
            # Redirect all user-data roots so the subprocess can never touch real OrcaSlicer data
            env = dict(os.environ, APPDATA=td, XDG_CONFIG_HOME=td, HOME=td, USERPROFILE=td)
            proc = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, env=env, check=False)
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        self.assertIn("STABLE_CAPS_OK", proc.stdout)


# ============================================================================
# 6. P1/P2 Fixes (Markdown, Temp=0.0, Real Data Migration, NumPy Geometry,
#    Pre-Flight, Streaming G-code/3MF, Calibration, Slash Cmds, Anthropic/HTTP)
# ============================================================================

class TestP1P2Features(unittest.TestCase):
    @unittest.skipUnless(HAS_NODE, "node runtime not available")
    def test_markdown_js_code_fences_tables_streaming_and_xss(self) -> None:
        md_js_path = SRC_DIR / "orca_ai_assistant" / "ui" / "markdown.js"
        node_script = f"""
const fs = require("fs");
const vm = require("vm");
const code = fs.readFileSync({json.dumps(str(md_js_path))}, "utf8");
const ctx = {{ window: {{ t: (k) => k }} }};
vm.createContext(ctx);
vm.runInContext(code, ctx);

// 1. Code fence with # comment and blank lines must NOT render <h1> or break fence
const r1 = ctx.renderMarkdown("```python\\n# heading inside code\\n\\nx = 1\\n```");
if (r1.includes("<h1>")) throw new Error("Code fence '#' leaked into <h1>: " + r1);
if (!r1.includes("# heading inside code\\n\\nx = 1")) throw new Error("Blank line broken in code fence: " + r1);

// 2. GFM table
const r2 = ctx.renderMarkdown("| Param | Value |\\n| :--- | ---: |\\n| Layer | 0.2 |\\n| Walls | 3 |");
if (!r2.includes("<table") || !r2.includes("text-align:right") || !r2.includes("0.2")) {{
  throw new Error("GFM table failed: " + r2);
}}

// 3. Unclosed streaming orca-settings block hidden behind preparing badge
const r3 = ctx.renderMarkdown("Adjusting now:\\n```orca-settings\\n[{{\\"key\\": \\"layer_height\\"");
if (r3.includes("layer_height") || !r3.includes("md-preparing-badge")) {{
  throw new Error("Unclosed orca-settings not hidden: " + r3);
}}

// 4. XSS escaping and javascript: link neutralization
const r4 = ctx.renderMarkdown("<script>alert('xss')</script> [click](javascript:alert(1)) [ok](https://example.com)");
if (r4.includes("<script>") || r4.includes("javascript:alert")) {{
  if (r4.includes('<a href="javascript:')) throw new Error("XSS href allowed: " + r4);
  if (r4.includes("<script>")) throw new Error("XSS script tag allowed: " + r4);
}}
if (!r4.includes("&lt;script&gt;") || !r4.includes('href="https://example.com"')) {{
  throw new Error("Escaping or safe link failed: " + r4);
}}
console.log("MARKDOWN_JS_OK");
"""
        proc = subprocess.run(["node", "-e", node_script], capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, f"stderr: {proc.stderr}\nstdout: {proc.stdout}")
        self.assertIn("MARKDOWN_JS_OK", proc.stdout)

    def test_temperature_zero_preservation_storage_and_http(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            sm = StorageManager(td)
            updated = sm.update_settings({"temperature": 0.0})
            self.assertEqual(updated["temperature"], 0.0)
            sm2 = StorageManager(td)
            self.assertEqual(sm2.get_settings()["temperature"], 0.0)

        # Verify send_chat_completion transmits temperature: 0.0 over HTTP (not coerced to 0.3)
        captured_bodies: list[dict[str, Any]] = []

        class CaptureHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
                captured_bodies.append(json.loads(raw))
                resp = json.dumps({
                    "choices": [{"message": {"content": "Deterministic reply"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                }).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)

        server = http.server.HTTPServer(("127.0.0.1", 0), CaptureHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            res = send_chat_completion(
                provider="custom",
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="test",
                model_id="llama-3.3-70b",
                messages=[{"role": "user", "content": "test"}],
                system_prompt="sys",
                temperature=0.0,
            )
            self.assertTrue(res["ok"])
            self.assertEqual(captured_bodies[0]["temperature"], 0.0)
        finally:
            server.shutdown()
            server.server_close()

    def test_storage_atomic_write_and_v2_to_v4_migration_on_temp_copy(self) -> None:
        # 1) Always test deterministic v2 -> v4 migration + .bak + retired model migration + temp=0.0
        with tempfile.TemporaryDirectory() as td_syn:
            syn_dir = Path(td_syn)
            v2_settings = {
                "schema_version": 2,
                "language": "ru",
                "provider": "anthropic",
                "model": "claude-sonnet-4-20250514",
                "temperature": 0.0,
                "api_keys": {"anthropic": "sk-ant-user-kept"},
                "favorite_models": [
                    {"provider": "anthropic", "model": "claude-sonnet-4-20250514", "label": "Old Sonnet"},
                    {"provider": "custom", "model": "my-local-model", "label": "My Custom"},
                ],
            }
            (syn_dir / "settings.json").write_text(json.dumps(v2_settings), encoding="utf-8")
            (syn_dir / "chats.json").write_text(
                json.dumps({"active_id": "chat_1", "sessions": [{"id": "chat_1", "title": "Old", "messages": []}]}),
                encoding="utf-8",
            )
            sm_syn = StorageManager(syn_dir)
            mig_syn = sm_syn.get_settings()
            self.assertTrue((syn_dir / "settings.json.bak").is_file())
            self.assertEqual(mig_syn["schema_version"], 4)
            self.assertEqual(mig_syn["temperature"], 0.0)
            self.assertEqual(mig_syn["api_keys"]["anthropic"], "sk-ant-user-kept")
            self.assertNotIn(mig_syn["model"], RETIRED_MODEL_MIGRATIONS)
            self.assertTrue(any(f.get("model") == "my-local-model" for f in mig_syn["favorite_models"]))
            self.assertEqual(list(syn_dir.glob("*.tmp")), [])

        # 2) Also test on a TEMP COPY of the user's real OrcaSlicer plugin_data (strictly READ-ONLY on originals!)
        real_dir = Path(r"C:\Users\Admin\AppData\Roaming\OrcaSlicer\orca_plugins\plugin_data\orca-ai-assistant")
        real_settings = real_dir / "settings.json"
        real_chats = real_dir / "chats.json"
        if real_settings.is_file():
            orig_settings_bytes = real_settings.read_bytes()
            orig_chats_bytes = real_chats.read_bytes() if real_chats.is_file() else None
            with tempfile.TemporaryDirectory() as td_real:
                tmp_dir = Path(td_real)
                shutil.copy2(real_settings, tmp_dir / "settings.json")
                if real_chats.is_file():
                    shutil.copy2(real_chats, tmp_dir / "chats.json")

                pre_data = json.loads((tmp_dir / "settings.json").read_text(encoding="utf-8"))
                pre_version = int(pre_data.get("schema_version") or 1)
                pre_api_keys = dict(pre_data.get("api_keys") or {})

                sm_real = StorageManager(tmp_dir)
                migrated = sm_real.get_settings()

                if pre_version < 4:
                    self.assertTrue((tmp_dir / "settings.json.bak").is_file())
                self.assertEqual(migrated["schema_version"], 4)
                for k, v in pre_api_keys.items():
                    if v:
                        self.assertEqual(migrated["api_keys"].get(k), v)
                self.assertNotIn(migrated["model"], RETIRED_MODEL_MIGRATIONS)
                for fav in migrated["favorite_models"]:
                    self.assertNotIn(fav.get("model"), RETIRED_MODEL_MIGRATIONS)
                self.assertEqual(list(tmp_dir.glob("*.tmp")), [])
                self.assertGreaterEqual(len(sm_real.get_chats()["sessions"]), 1)

            # Confirm originals were NEVER modified
            self.assertEqual(real_settings.read_bytes(), orig_settings_bytes)
            if orig_chats_bytes is not None:
                self.assertEqual(real_chats.read_bytes(), orig_chats_bytes)

    @unittest.skipUnless(HAS_NUMPY, "numpy not available")
    def test_numpy_3d_geometry_all_four_fixes(self) -> None:
        np = geometry_mod.np

        # Unit cube [0, 10]^3 with outward CCW normals (12 triangles)
        verts = np.array(
            [
                [0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
                [0, 0, 10], [10, 0, 10], [10, 10, 10], [0, 10, 10],
            ],
            dtype=np.float64,
        )
        tris = np.array(
            [
                # Bottom (z=0, normal -Z)
                [0, 2, 1], [0, 3, 2],
                # Top (z=10, normal +Z)
                [4, 5, 6], [4, 6, 7],
                # Front (y=0, normal -Y)
                [0, 1, 5], [0, 5, 4],
                # Back (y=10, normal +Y)
                [2, 3, 7], [2, 7, 6],
                # Left (x=0, normal -X)
                [0, 4, 7], [0, 7, 3],
                # Right (x=10, normal +X)
                [1, 2, 6], [1, 6, 5],
            ],
            dtype=np.int32,
        )

        # (a) Mirrored mesh (det < 0): bed contact and overhangs must match normal cube!
        normal_geo = geometry_mod.analyze_object_meshes_numpy([
            {"vertices": verts, "triangles": tris, "matrix": np.eye(4), "raw_volume_mm3": 1000.0}
        ])
        mirror_mat = np.diag([-1.0, 1.0, 1.0, 1.0])
        mirrored_geo = geometry_mod.analyze_object_meshes_numpy([
            {"vertices": verts, "triangles": tris, "matrix": mirror_mat, "raw_volume_mm3": 1000.0}
        ])
        self.assertIsNotNone(normal_geo)
        self.assertIsNotNone(mirrored_geo)
        assert normal_geo is not None and mirrored_geo is not None
        self.assertAlmostEqual(normal_geo["bed_contact_mm2"], 100.0, places=1)
        self.assertAlmostEqual(mirrored_geo["bed_contact_mm2"], 100.0, places=1)
        self.assertAlmostEqual(mirrored_geo["overhang_45_mm2"], 0.0, places=1)

        # (b) Global object z_min: upper floating volume at Z=[20..30] must NOT count as bed contact,
        #     its bottom face (100 mm^2) MUST count as critical >60 overhang!
        upper_mat = np.eye(4)
        upper_mat[2, 3] = 20.0
        stacked_geo = geometry_mod.analyze_object_meshes_numpy([
            {"vertices": verts, "triangles": tris, "matrix": np.eye(4), "raw_volume_mm3": 1000.0},
            {"vertices": verts, "triangles": tris, "matrix": upper_mat, "raw_volume_mm3": 1000.0},
        ])
        assert stacked_geo is not None
        self.assertAlmostEqual(stacked_geo["bed_contact_mm2"], 100.0, places=1)
        self.assertAlmostEqual(stacked_geo["overhang_60_mm2"], 100.0, places=1)
        self.assertAlmostEqual(stacked_geo["size_z"], 30.0, places=1)

        # (c) Union bounding box across offset volumes: [0..10] and [20..30] => size_x == 30.0
        offset_mat = np.eye(4)
        offset_mat[0, 3] = 20.0
        union_geo = geometry_mod.analyze_object_meshes_numpy([
            {"vertices": verts, "triangles": tris, "matrix": np.eye(4), "raw_volume_mm3": 1000.0},
            {"vertices": verts, "triangles": tris, "matrix": offset_mat, "raw_volume_mm3": 1000.0},
        ])
        assert union_geo is not None
        self.assertAlmostEqual(union_geo["size_x"], 30.0, places=1)

        # (d) Scaled volume: 2x2x2 scale (det=8) => 8.0 cm^3 (not 1.0 cm^3)
        scale_mat = np.diag([2.0, 2.0, 2.0, 1.0])
        scaled_geo = geometry_mod.analyze_object_meshes_numpy([
            {"vertices": verts, "triangles": tris, "matrix": scale_mat, "raw_volume_mm3": 1000.0}
        ])
        assert scaled_geo is not None
        self.assertAlmostEqual(scaled_geo["volume_cm3"], 8.0, places=2)

    def test_preflight_scorecard_clean_and_rules(self) -> None:
        clean_plate = {
            "has_model": True,
            "total_overhang_45_mm2": 0.0,
            "total_overhang_60_mm2": 0.0,
            "objects": [{
                "name": "Bracket",
                "is_manifold": True,
                "mesh_errors": 0,
                "bed_contact_mm2": 900.0,
                "size_z": 20.0,
                "height_to_base_ratio": 0.6,
            }],
        }
        clean_presets = {
            "flat_values": {
                "brim_type": "no_brim",
                "sparse_infill_pattern": "gyroid",
                "enable_support": "0",
                "curr_bed_type": "Textured PEI Plate",
                "nozzle_diameter": "0.4",
                "layer_height": "0.2",
                "outer_wall_line_width": "0.42",
                "inner_wall_line_width": "0.45",
                "outer_wall_speed": "100",
                "inner_wall_speed": "120",
                "sparse_infill_speed": "150",
                "wall_generator": "arachne",
                "wall_loops": "3",
                "top_shell_layers": "4",
            },
            "filament_slots": [{
                "slot": 1,
                "type": "PLA",
                "nozzle_temp": "210",
                "bed_temp": "60",
                "max_volumetric_speed": "20",
                "fan_max": "100",
                "close_fan_first_layers": "1",
            }],
            "custom_gcode": {
                "machine_start_gcode": "G28\nG1 Z5",
                "machine_end_gcode": "M104 S0\nM140 S0",
            },
        }
        clean_res = run_preflight_checks(clean_plate, clean_presets, lang="en")
        self.assertEqual(clean_res["score"], 100)
        self.assertEqual(clean_res["status"], "ok")

        # Trigger multiple critical & warn rules simultaneously
        risky_plate = {
            "has_model": True,
            "total_overhang_45_mm2": 200.0,
            "total_overhang_60_mm2": 120.0,
            "objects": [{
                "name": "Tower",
                "is_manifold": False,
                "mesh_errors": 4,
                "bed_contact_mm2": 50.0,
                "size_z": 80.0,
                "height_to_base_ratio": 4.2,
            }],
        }
        risky_presets = {
            "flat_values": {
                "brim_type": "no_brim",
                "sparse_infill_pattern": "grid",
                "enable_support": "0",
                "curr_bed_type": "Cool Plate",
                "nozzle_diameter": "0.4",
                "layer_height": "0.36",
                "outer_wall_line_width": "0.45",
                "inner_wall_line_width": "0.45",
                "outer_wall_speed": "250",
                "inner_wall_speed": "250",
                "sparse_infill_speed": "300",
                "wall_generator": "classic",
                "detect_thin_wall": "0",
                "wall_loops": "1",
                "top_shell_layers": "2",
            },
            "filament_slots": [
                {"slot": 1, "type": "PLA", "nozzle_temp": "210", "bed_temp": "80", "max_volumetric_speed": "12", "fan_max": "40", "close_fan_first_layers": "5"},
                {"slot": 2, "type": "ABS", "nozzle_temp": "260", "bed_temp": "100", "max_volumetric_speed": "15", "fan_max": "20", "close_fan_first_layers": "2"},
            ],
            "custom_gcode": {
                "machine_start_gcode": "G1 X10 Y10 F3000\nG28",
                "machine_end_gcode": "M84",
            },
        }
        risky_slice = {"ok": True, "total_filament_g": 100.0, "flush_g": 35.0, "tower_g": 15.0}
        risky_res = run_preflight_checks(risky_plate, risky_presets, last_slice=risky_slice, lang="en")
        ids = {c["id"] for c in risky_res["checks"]}
        self.assertEqual(risky_res["status"], "danger")
        self.assertLess(risky_res["score"], 40)
        for expected_id in (
            "non_manifold_mesh",
            "small_bed_contact_no_brim",
            "tall_narrow_stability",
            "critical_overhangs_no_support",
            "ams_material_clash",
            "cool_plate_mismatch_s2",
            "pla_bed_too_hot_s1",
            "volumetric_flow_exceeded",
            "thin_walls_classic",
            "layer_height_vs_nozzle",
            "high_flush_purge_waste",
            "pla_cooling_disabled_too_long_s1",
            "pla_low_fan_s1",
            "single_wall_loop",
        ):
            self.assertIn(expected_id, ids)

    def test_gcode_and_3mf_streaming_analyzer_and_slice_delta(self) -> None:
        gcode_v1 = "\n".join([
            "; generated by OrcaSlicer 2.5.2",
            "; total layer number: 120",
            "M140 S100",
            "M140 S60",
            "M104 S220",
            "M104 S95",
            "; CHANGE_LAYER",
            "G1 Z0.2 F1200",
            "T0",
            "G1 Z24.4 F1200",
            "T1",
            "M600",
            "; filament used [g] = 42.5, 17.5",
            "; total filament used [g] = 60.0",
            "; flushed filament [g] = 12.0",
            "; wipe tower filament [g] = 6.0",
            "; estimated printing time (normal mode) = 2h 30m 0s",
        ])
        gcode_v2 = gcode_v1.replace("2h 30m 0s", "2h 0m 0s").replace("60.0", "52.0").replace("12.0", "6.0")

        s1 = summarize_gcode_text(gcode_v1, "part_v1.gcode")
        self.assertTrue(s1["ok"])
        self.assertEqual(s1["layer_count"], 120)
        self.assertEqual(s1["max_z"], 24.4)
        self.assertEqual(s1["estimated_time_sec"], 9000)
        self.assertEqual(s1["total_filament_g"], 60.0)
        self.assertEqual(s1["filament_used_g_per_slot"], [42.5, 17.5])
        self.assertEqual(s1["waste_g"], 18.0)
        self.assertEqual(s1["waste_pct"], 30.0)
        self.assertTrue(s1["has_m600_pause"])
        # Verify numeric float sorting (60 before 100; 95 before 220)
        self.assertEqual(s1["m140_temps"], ["60", "100"])
        self.assertEqual(s1["m104_temps"], ["95", "220"])

        # Test .gcode and .gcode.3mf streaming from disk
        with tempfile.TemporaryDirectory() as td:
            gp = Path(td) / "part_v2.gcode"
            gp.write_text(gcode_v2, encoding="utf-8")
            s2 = summarize_gcode_file(gp)
            self.assertTrue(s2["ok"])
            self.assertEqual(s2["estimated_time_sec"], 7200)

            tmf = Path(td) / "plate.gcode.3mf"
            with zipfile.ZipFile(tmf, "w") as zf:
                zf.writestr("Metadata/plate_1.gcode", gcode_v2)
            s3 = summarize_gcode_file(tmf)
            self.assertTrue(s3["ok"])
            self.assertEqual(s3["embedded_gcode_files"], ["Metadata/plate_1.gcode"])
            self.assertEqual(s3["total_filament_g"], 52.0)

        delta = compute_slice_delta(s1, s2)
        assert delta is not None
        self.assertEqual(delta["time_delta_sec"], -1800)
        self.assertEqual(delta["time_delta_str"], "-30m")
        self.assertEqual(delta["grams_delta"], -8.0)
        self.assertEqual(delta["waste_delta_g"], -6.0)

    def test_calibration_formulas_all_five_stages(self) -> None:
        r1 = calculate_calibration_values("temp_tower", {"best_temp": 205, "initial_layer_offset": 5}, slot=2, lang="en")
        self.assertEqual(r1["values"]["nozzle_temperature"], 205)
        self.assertEqual(r1["values"]["nozzle_temperature_initial_layer"], 210)
        self.assertEqual(r1["changes"][0]["slot"], 2)

        r2 = calculate_calibration_values("max_volumetric_speed", {"start": 5, "height": 20, "step": 0.5, "safety_margin_pct": 15}, slot=1, lang="en")
        self.assertAlmostEqual(r2["values"]["raw_max_volumetric_speed"], 15.0)
        self.assertAlmostEqual(r2["values"]["filament_max_volumetric_speed"], 12.75)

        r3 = calculate_calibration_values("pressure_advance", {"start": 0, "height": 15, "step": 0.002}, slot=3, lang="en")
        self.assertAlmostEqual(r3["values"]["pressure_advance"], 0.03)
        self.assertEqual(r3["changes"][1]["slot"], 3)

        r4 = calculate_calibration_values("flow_rate", {"old_flow": 0.98, "modifier": -5}, slot=1, lang="en")
        self.assertAlmostEqual(r4["values"]["filament_flow_ratio"], 0.931)

        r5 = calculate_calibration_values("retraction", {"start": 0.2, "height": 6, "step": 0.1}, slot=1, lang="en")
        self.assertAlmostEqual(r5["values"]["retraction_length"], 0.8)
        self.assertEqual(r5["changes"][0]["category"], "printer")

    def test_slash_commands_zero_llm_calls(self) -> None:
        env = FakeOrcaEnvironment()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.orca_bridge.presets.orca", env.orca), \
             mock.patch("orca_ai_assistant.controller.controller.orca", env.orca), \
             mock.patch("orca_ai_assistant.controller.controller.inspect_plate_geometry", return_value={"has_model": False, "objects": [], "warnings": []}), \
             mock.patch("orca_ai_assistant.controller.controller.get_plugin_storage_dir", return_value=Path(tempfile.gettempdir())), \
             mock.patch("orca_ai_assistant.controller.controller.send_chat_completion") as mock_llm:
            ctrl = AssistantController(storage=StorageManager(td))
            view = RecordingView()
            ctrl.register_page(view)

            for cmd in ("/context", "/gcode", "/debug"):
                ctrl.handle_message_on_ui({"action": "send_chat", "text": cmd}, source_view=view)

            sessions = ctrl.storage.get_chats()["sessions"]
            msgs = sessions[0]["messages"]
            self.assertEqual(len(msgs), 6)  # 3 user + 3 local assistant replies
            self.assertIn("ORCASLICER", msgs[1]["content"].upper())
            self.assertIn("machine_start_gcode", msgs[3]["content"])
            self.assertIn(PLUGIN_VERSION, msgs[5]["content"])

            # /undo with empty history responds locally without LLM
            ctrl.handle_message_on_ui({"action": "send_chat", "text": "/undo"}, source_view=view)
            self.assertTrue(_wait_until(lambda: len(ctrl.storage.get_chats()["sessions"][0]["messages"]) == 8))

            # /clear clears messages
            ctrl.handle_message_on_ui({"action": "send_chat", "text": "/clear"}, source_view=view)
            self.assertEqual(ctrl.storage.get_chats()["sessions"][0]["messages"], [])
            self.assertEqual(mock_llm.call_count, 0)

    def test_anthropic_sanitizer_multipass_400_retry_and_per_model_key_isolation(self) -> None:
        # 1. Anthropic role sanitizer: strip leading assistant + merge consecutive roles + attach image
        sanitized = _sanitize_anthropic_messages(
            [
                {"role": "assistant", "content": "Stray greeting"},
                {"role": "user", "content": "First question"},
                {"role": "user", "content": "Follow-up detail"},
                {"role": "assistant", "content": "Answer 1"},
                {"role": "assistant", "content": "Answer 2"},
                {"role": "user", "content": "See photo"},
            ],
            image_attachment={"mime": "image/jpeg", "base64": "AAAA"},
        )
        self.assertEqual([m["role"] for m in sanitized], ["user", "assistant", "user"])
        self.assertIn("First question", sanitized[0]["content"])
        self.assertIn("Follow-up detail", sanitized[0]["content"])
        self.assertIn("Answer 1", sanitized[1]["content"])
        self.assertIn("Answer 2", sanitized[1]["content"])
        self.assertIsInstance(sanitized[2]["content"], list)
        self.assertEqual(sanitized[2]["content"][0]["type"], "image")

        # 2. Multi-pass HTTP 400 retry (3 distinct passes -> 4 HTTP requests -> 200 OK)
        seen_bodies: list[dict[str, Any]] = []

        class Retry400Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8")
                body = json.loads(raw)
                seen_bodies.append(body)
                if "stream_options" in body:
                    self._send_json(400, {"error": {"message": "Extra field stream_options rejected"}})
                    return
                if "reasoning_effort" in body:
                    self._send_json(400, {"error": {"message": "Parameter reasoning_effort rejected"}})
                    return
                if "max_tokens" in body:
                    self._send_json(400, {"error": {"message": "Use max_completion_tokens instead of max_tokens"}})
                    return
                self._send_json(200, {
                    "choices": [{"message": {"content": "Recovered after 3 passes"}}],
                    "usage": {"prompt_tokens": 22, "completion_tokens": 11},
                })

            def _send_json(self, code: int, obj: dict[str, Any]) -> None:
                data = json.dumps(obj).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = http.server.HTTPServer(("127.0.0.1", 0), Retry400Handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        try:
            res = send_chat_completion(
                provider="openai",
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="sk-test",
                model_id="gpt-5.2",
                messages=[{"role": "user", "content": "hi"}],
                system_prompt="sys",
                reasoning_effort="low",
                on_chunk=lambda _: None,
            )
            self.assertTrue(res["ok"], f"Expected retry recovery, got: {res}")
            self.assertEqual(res["reply"], "Recovered after 3 passes")
            self.assertEqual(len(seen_bodies), 4)
            self.assertIn("max_completion_tokens", seen_bodies[-1])
        finally:
            server.shutdown()
            server.server_close()

        # 2b. Anthropic SSE streaming with thinking_delta + text_delta + usage
        class AnthropicSSEHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                if length:
                    self.rfile.read(length)
                events = [
                    {"type": "message_start", "message": {"usage": {"input_tokens": 140}}},
                    {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "Checking overhang angle..."}},
                    {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Enable tree(auto) supports."}},
                    {"type": "message_delta", "usage": {"output_tokens": 35}},
                    {"type": "message_stop"},
                ]
                payload = "".join(f"data: {json.dumps(ev)}\n\n" for ev in events).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        anth_srv = http.server.HTTPServer(("127.0.0.1", 0), AnthropicSSEHandler)
        anth_port = anth_srv.server_address[1]
        t_anth = threading.Thread(target=anth_srv.serve_forever, daemon=True)
        t_anth.start()
        try:
            got_chunks: list[str] = []
            got_thinking: list[str] = []
            anth_res = send_chat_completion(
                provider="anthropic",
                base_url=f"http://127.0.0.1:{anth_port}/v1",
                api_key="sk-ant-test",
                model_id="claude-sonnet-5-5",
                messages=[{"role": "assistant", "content": "ignored"}, {"role": "user", "content": "audit"}],
                system_prompt="sys",
                on_chunk=lambda s: got_chunks.append(s),
                on_thinking=lambda s: got_thinking.append(s),
            )
            self.assertTrue(anth_res["ok"])
            self.assertEqual(anth_res["reply"], "Enable tree(auto) supports.")
            self.assertEqual(anth_res["reasoning"], "Checking overhang angle...")
            self.assertEqual(anth_res["usage"], {"input_tokens": 140, "output_tokens": 35})
            self.assertTrue(got_chunks)
            self.assertTrue(got_thinking)
        finally:
            anth_srv.shutdown()
            anth_srv.server_close()

        # 3. fetch_models MUST NOT overwrite api_keys[provider] with a per-model key (P1 #16)
        with tempfile.TemporaryDirectory() as td:
            sm = StorageManager(td)
            sm.update_settings({
                "provider": "openai",
                "model": "gpt-5.2",
                "api_keys": {"openai": "sk-provider-original"},
                "model_api_keys": {"openai::gpt-5.2": "sk-model-secret"},
            })
            ctrl = AssistantController(storage=sm)
            view = RecordingView()
            ctrl.register_page(view)

            with mock.patch(
                "orca_ai_assistant.controller.controller.fetch_provider_models",
                return_value={"ok": True, "models": [{"id": "gpt-5.2", "name": "GPT-5.2"}], "count": 1},
            ):
                ctrl.handle_message_on_ui(
                    {
                        "action": "fetch_models",
                        "provider": "openai",
                        "model": "gpt-5.2",
                        "api_key": "sk-model-secret",
                        "key_source": "model",
                    },
                    source_view=view,
                )
                self.assertTrue(_wait_until(lambda: any(m.get("type") == "models_loaded" for m in view.messages)))
                self.assertEqual(sm.get_settings()["api_keys"]["openai"], "sk-provider-original")

        # 4. Registry check: Mistral added + non-chat filter
        self.assertIn("mistral", PROVIDER_PRESETS)
        self.assertFalse(is_chat_model("text-embedding-3-large"))
        self.assertFalse(is_chat_model("whisper-1"))
        self.assertTrue(is_chat_model("claude-opus-5-5"))

    def test_anthropic_adaptive_thinking_headroom_recovery_and_400_strip(self) -> None:
        recorded_bodies: list[dict[str, Any]] = []

        class ThinkingHandler(http.server.BaseHTTPRequestHandler):
            mode = "sse_omitted_then_recover"

            def log_message(self, format: str, *args: Any) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                body = json.loads(raw.decode("utf-8"))
                recorded_bodies.append(body)
                call_idx = len(recorded_bodies)

                if ThinkingHandler.mode == "sse_omitted_then_recover":
                    if call_idx == 1:
                        events = [
                            {"type": "message_start", "message": {"usage": {"input_tokens": 500}}},
                            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
                            {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "sig_abc"}},
                            {"type": "content_block_stop", "index": 0},
                            {"type": "message_delta", "delta": {"stop_reason": "max_tokens"}, "usage": {"output_tokens": 8192}},
                            {"type": "message_stop"},
                        ]
                        payload = "".join(f"data: {json.dumps(ev)}\n\n" for ev in events).encode("utf-8")
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Content-Length", str(len(payload)))
                        self.end_headers()
                        self.wfile.write(payload)
                        return
                    resp = {
                        "id": "msg_rec_1",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Recovered SSE answer"}],
                        "usage": {"input_tokens": 500, "output_tokens": 25},
                    }
                elif ThinkingHandler.mode == "nonstream_omitted_then_recover":
                    if call_idx == 1:
                        resp = {
                            "id": "msg_empty_think",
                            "type": "message",
                            "role": "assistant",
                            "stop_reason": "max_tokens",
                            "content": [{"type": "thinking", "thinking": "", "signature": "sig_only"}],
                            "usage": {"input_tokens": 400, "output_tokens": 8192},
                        }
                    else:
                        resp = {
                            "id": "msg_rec_2",
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "Recovered non-stream answer"}],
                            "usage": {"input_tokens": 400, "output_tokens": 30},
                        }
                else:  # reject_400_then_ok
                    if call_idx == 1 and ("output_config" in body or "thinking" in body):
                        err = {"error": {"message": "Extra inputs are not permitted: output_config, thinking"}}
                        raw_err = json.dumps(err).encode("utf-8")
                        self.send_response(400)
                        self.send_header("Content-Type", "application/json")
                        self.send_header("Content-Length", str(len(raw_err)))
                        self.end_headers()
                        self.wfile.write(raw_err)
                        return
                    resp = {
                        "id": "msg_ok_400",
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Fallback OK after 400 strip"}],
                        "usage": {"input_tokens": 100, "output_tokens": 15},
                    }

                raw_out = json.dumps(resp).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw_out)))
                self.end_headers()
                self.wfile.write(raw_out)

        srv = http.server.HTTPServer(("127.0.0.1", 0), ThinkingHandler)
        port = srv.server_address[1]
        thr = threading.Thread(target=srv.serve_forever, daemon=True)
        thr.start()
        try:
            # A. SSE omitted thinking -> output_config.effort=low, max_tokens>=8192 -> recovers with thinking disabled + 16384
            ThinkingHandler.mode = "sse_omitted_then_recover"
            recorded_bodies.clear()
            res_sse = send_chat_completion(
                provider="anthropic",
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="sk-ant-test",
                model_id="claude-opus-5-5",
                messages=[{"role": "user", "content": "audit 49 parts"}],
                system_prompt="sys",
                max_tokens=4096,
                reasoning_effort="low",
                on_chunk=lambda _t: None,
            )
            self.assertTrue(res_sse["ok"], res_sse)
            self.assertEqual(res_sse["reply"], "Recovered SSE answer")
            self.assertEqual(len(recorded_bodies), 2)
            self.assertEqual(recorded_bodies[0].get("output_config"), {"effort": "low"})
            self.assertGreaterEqual(recorded_bodies[0]["max_tokens"], 8192)
            self.assertEqual(recorded_bodies[1].get("thinking"), {"type": "disabled"})
            self.assertNotIn("output_config", recorded_bodies[1])
            self.assertGreaterEqual(recorded_bodies[1]["max_tokens"], 16384)

            # B. Non-stream omitted thinking -> recovers cleanly
            ThinkingHandler.mode = "nonstream_omitted_then_recover"
            recorded_bodies.clear()
            res_ns = send_chat_completion(
                provider="anthropic",
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="sk-ant-test",
                model_id="claude-opus-5-5",
                messages=[{"role": "user", "content": "audit"}],
                system_prompt="sys",
                max_tokens=4096,
                reasoning_effort="medium",
            )
            self.assertTrue(res_ns["ok"], res_ns)
            self.assertEqual(res_ns["reply"], "Recovered non-stream answer")
            self.assertEqual(recorded_bodies[0].get("output_config"), {"effort": "medium"})
            self.assertGreaterEqual(recorded_bodies[0]["max_tokens"], 16384)
            self.assertEqual(recorded_bodies[1].get("thinking"), {"type": "disabled"})

            # C. effort="none" sends thinking.disabled; HTTP 400 rejecting thinking/output_config strips and succeeds
            ThinkingHandler.mode = "reject_400_then_ok"
            recorded_bodies.clear()
            res_400 = send_chat_completion(
                provider="anthropic",
                base_url=f"http://127.0.0.1:{port}/v1",
                api_key="sk-ant-test",
                model_id="claude-opus-5-5",
                messages=[{"role": "user", "content": "hello"}],
                system_prompt="sys",
                max_tokens=4096,
                reasoning_effort="none",
            )
            self.assertTrue(res_400["ok"], res_400)
            self.assertEqual(res_400["reply"], "Fallback OK after 400 strip")
            self.assertEqual(recorded_bodies[0].get("thinking"), {"type": "disabled"})
            self.assertNotIn("thinking", recorded_bodies[1])
            self.assertNotIn("output_config", recorded_bodies[1])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_lifecycle_gcode_export_updates_slice_delta_and_notifications(self) -> None:
        env = FakeOrcaEnvironment()
        with tempfile.TemporaryDirectory() as td, \
             mock.patch("orca_ai_assistant.orca_bridge.presets.orca", env.orca), \
             mock.patch("orca_ai_assistant.controller.controller.orca", env.orca):
            ctrl = AssistantController(storage=StorageManager(td))
            view = RecordingView()
            ctrl.register_page(view)
            # Trigger a Pre-Flight danger so native notification fires on slice
            ctrl._last_plate_snapshot = {
                "has_model": True,
                "total_overhang_45_mm2": 0.0,
                "total_overhang_60_mm2": 0.0,
                "objects": [{"name": "Broken", "is_manifold": False, "mesh_errors": 3, "bed_contact_mm2": 500.0, "size_z": 10.0, "height_to_base_ratio": 0.5}],
                "warnings": [],
            }
            ctrl._last_presets_snapshot = inspect_slicer_presets("en", include_gcode=True)

            gcode_path = Path(td) / "exported.gcode"
            gcode_path.write_text(
                "; total layer number: 50\n; total filament used [g] = 40.0\n; estimated printing time (normal mode) = 1h 10m 0s\nG1 Z10.0\n",
                encoding="utf-8",
            )
            evt = types.SimpleNamespace(name="GCodeExportFinished")
            ctx = types.SimpleNamespace(code="Ok", msg=str(gcode_path))
            ctrl.handle_lifecycle_event(evt, ctx)

            self.assertTrue(_wait_until(lambda: any(m.get("type") == "context_updated" and m.get("last_slice") for m in view.messages)))
            upd = [m for m in view.messages if m.get("type") == "context_updated"][-1]
            self.assertEqual(upd["last_slice"]["layer_count"], 50)
            self.assertEqual(upd["last_slice"]["total_filament_g"], 40.0)
            self.assertEqual(upd["preflight"]["status"], "danger")
            self.assertEqual(len(env.notifications), 1)


# ============================================================================
# 7. Final Single-File Bundle Gates
# ============================================================================

class TestSingleFileBundle(unittest.TestCase):
    def test_bundle_up_to_date_and_isolated_import_smoke(self) -> None:
        bundle_path = REPO_ROOT / "orca_ai_assistant_any.py"
        self.assertTrue(bundle_path.is_file(), "Root orca_ai_assistant_any.py must exist")

        chk = subprocess.run(
            [sys.executable, "-B", str(REPO_ROOT / "scripts" / "build_singlefile.py"), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(chk.returncode, 0, f"--check failed:\n{chk.stderr}\n{chk.stdout}")

        with tempfile.TemporaryDirectory() as td:
            smoke_code = f"""
import importlib.util, pathlib, sys, types

registered_caps = []
requested_perms = []

class FakeBase: pass
class FakePagesBase: pass
class FakeScriptBase: pass
class FakePipelineBase: pass

orca_mod = types.ModuleType("orca")
orca_mod.base = FakeBase
orca_mod.plugin = lambda cls: cls
orca_mod.request_permissions = lambda **kw: requested_perms.append(kw)
orca_mod.register_capability = lambda cls: registered_caps.append(cls)
orca_mod.ExecutionResult = types.SimpleNamespace(success=lambda msg="": ("ok", msg))
orca_mod.pages = types.SimpleNamespace(PagesPluginCapabilityBase=FakePagesBase)
orca_mod.script = types.SimpleNamespace(ScriptPluginCapabilityBase=FakeScriptBase)
orca_mod.slicing = types.SimpleNamespace(
    SlicingPipelineCapabilityBase=FakePipelineBase,
    Step=types.SimpleNamespace(psGCodePostProcess=7),
)
orca_mod.host = types.SimpleNamespace(
    app_info=lambda: {{"version": "2.5.2", "language": "en_US"}},
    plugin=types.SimpleNamespace(storage=lambda: r"{td}"),
)
sys.modules["orca"] = orca_mod
sys.modules["orca.host"] = orca_mod.host

spec = importlib.util.spec_from_file_location("orca_ai_assistant_any", r"{bundle_path}")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

assert mod.PLUGIN_VERSION == "3.0.1"
plugin = mod.OrcaAIAssistantPlugin()
plugin.register_capabilities()
assert len(registered_caps) == 3, len(registered_caps)

page = registered_caps[0]()
dock_script = registered_caps[1]()
auditor = registered_caps[2]()
assert page.get_name() == "Orca AI Assistant"
assert dock_script.get_name() == "Orca AI: Dock Panel"
assert auditor.get_name() == "Orca AI: G-code Audit"

page_html = page.get_ui()
dock_html = mod.load_ui_html("dock")
assert 'data-view="page"' in page_html
assert 'data-view="dock"' in dock_html
assert "__INLINE_" not in page_html and "__INLINE_" not in dock_html

icon_path = pathlib.Path(page.get_icon())
assert icon_path.is_file() and "<svg" in icon_path.read_text(encoding="utf-8")
print("ISOLATED_BUNDLE_SMOKE_OK")
"""
            isolated_env = dict(os.environ)
            isolated_env["APPDATA"] = td
            isolated_env["XDG_CONFIG_HOME"] = td
            isolated_env["HOME"] = td
            isolated_env["USERPROFILE"] = td
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-c", smoke_code],
                capture_output=True,
                text=True,
                env=isolated_env,
                check=False,
            )
            self.assertEqual(proc.returncode, 0, f"Isolated bundle import failed:\n{proc.stderr}\n{proc.stdout}")
            self.assertIn("ISOLATED_BUNDLE_SMOKE_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
