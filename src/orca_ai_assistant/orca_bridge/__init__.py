from __future__ import annotations

from .enums import (
    BOOL_KEYS,
    CUSTOM_GCODE_KEYS,
    ENUM_ALIASES,
    ENUM_VALID_VALUES,
    FLAT_SETTING_INFO,
    INT_PERCENT_KEYS,
    PERCENT_KEYS,
    SLICER_SETTINGS_I18N,
    normalize_and_validate_setting,
    normalize_setting_category,
)
from .gcode_analyzer import (
    compute_slice_delta,
    format_duration,
    parse_duration_to_seconds,
    summarize_gcode_file,
    summarize_gcode_text,
)
from .gcode_codec import (
    escape_orca_string,
    escape_orca_strings_single,
    lint_custom_gcode,
    make_unified_diff,
    unescape_orca_string,
    unescape_orca_strings_single,
)
from .geometry import (
    analyze_object_meshes_numpy,
    inspect_plate_geometry,
)
from .preflight import run_preflight_checks
from .presets import (
    apply_settings_to_orcaslicer,
    capture_full_preset_snapshot,
    inspect_slicer_presets,
    read_live_setting_value,
)
from .prompts import (
    CALIBRATION_STAGES,
    DEFECT_CATALOG,
    build_calibration_prompt,
    build_context_markdown,
    build_defect_prompt,
    build_full_context_markdown,
    calculate_calibration_values,
    get_system_prompt,
)

__all__ = [
    # enums
    "SLICER_SETTINGS_I18N",
    "FLAT_SETTING_INFO",
    "CUSTOM_GCODE_KEYS",
    "ENUM_VALID_VALUES",
    "ENUM_ALIASES",
    "BOOL_KEYS",
    "PERCENT_KEYS",
    "INT_PERCENT_KEYS",
    "normalize_setting_category",
    "normalize_and_validate_setting",
    # gcode_codec
    "unescape_orca_string",
    "escape_orca_string",
    "unescape_orca_strings_single",
    "escape_orca_strings_single",
    "lint_custom_gcode",
    "make_unified_diff",
    # presets
    "read_live_setting_value",
    "inspect_slicer_presets",
    "apply_settings_to_orcaslicer",
    "capture_full_preset_snapshot",
    # geometry
    "analyze_object_meshes_numpy",
    "inspect_plate_geometry",
    # preflight
    "run_preflight_checks",
    # gcode_analyzer
    "parse_duration_to_seconds",
    "format_duration",
    "summarize_gcode_text",
    "summarize_gcode_file",
    "compute_slice_delta",
    # prompts
    "DEFECT_CATALOG",
    "CALIBRATION_STAGES",
    "get_system_prompt",
    "build_context_markdown",
    "build_full_context_markdown",
    "build_defect_prompt",
    "calculate_calibration_values",
    "build_calibration_prompt",
]
