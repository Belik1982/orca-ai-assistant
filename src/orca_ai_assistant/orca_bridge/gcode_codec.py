from __future__ import annotations

import difflib
import re
from typing import Any

from ..core.constants import norm_lang, tr

# ============================================================================
# ORCASLICER C-STYLE G-CODE SERIALIZATION CODEC (coString & coStrings)
# Verified against OrcaSlicer.dll v2.5.2 (escape_string_cstyle / escape_strings_cstyle)
# ============================================================================


def unescape_orca_string(s: str) -> str:
    """
    Decode an OrcaSlicer `coString` value serialized by `escape_string_cstyle`.
    Single-pass scanner so literal `\\\\n` does not get corrupted into backslash + newline.
    """
    if not s:
        return ""
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
                i += 2
                continue
            if nxt == "r":
                out.append("\r")
                i += 2
                continue
            if nxt == "t":
                out.append("\t")
                i += 2
                continue
            if nxt == "\\":
                out.append("\\")
                i += 2
                continue
            if nxt == '"':
                out.append('"')
                i += 2
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def escape_orca_string(s: str) -> str:
    """
    Encode a raw multiline string into OrcaSlicer `coString` C-style wire format
    for `PresetTransaction.set(key, value)` (consumed by `unescape_string_cstyle`).
    """
    if not s:
        return ""
    return (
        s.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )


def unescape_orca_strings_single(s: str) -> str:
    """
    Decode a single-slot OrcaSlicer `coStrings` value serialized by `escape_strings_cstyle`.

    In OrcaSlicer, `escape_strings_cstyle` joins vector elements with `;` and wraps
    elements containing `;`, `\\n`, `\\r`, `"`, or `\\` in double quotes `"..."` with
    C-style escapes. When read from a single filament preset (`preset.config_value(key)`),
    there is one element; if a multi-slot `;`-joined string is passed, this extracts
    and unescapes the first element cleanly.
    """
    if not s:
        return ""

    # Quoted C-style string element: parse up to matching unescaped closing quote
    if s[0] == '"':
        buf: list[str] = []
        i = 1
        n = len(s)
        while i < n:
            ch = s[i]
            if ch == "\\" and i + 1 < n:
                nxt = s[i + 1]
                if nxt == "n":
                    buf.append("\n")
                elif nxt == "r":
                    buf.append("\r")
                elif nxt == "t":
                    buf.append("\t")
                elif nxt == "\\":
                    buf.append("\\")
                elif nxt == '"':
                    buf.append('"')
                else:
                    buf.append("\\")
                    buf.append(nxt)
                i += 2
                continue
            if ch == '"':
                return "".join(buf)
            buf.append(ch)
            i += 1
        # Unterminated quote fallback: return decoded content accumulated so far
        return "".join(buf)

    # Unquoted element: if joined with `;`, take first element, then unescape C-style
    first = s.split(";", 1)[0]
    return unescape_orca_string(first)


def escape_orca_strings_single(s: str) -> str:
    """
    Encode a single-slot filament G-code string for OrcaSlicer `coStrings` (`tx.set()`).

    CRITICAL: OrcaSlicer's `unescape_strings_cstyle` splits unquoted strings on `;`
    (the G-code comment character!). Always wrap in double quotes `"..."` and apply
    C-style escaping so semicolons, quotes, backslashes, and newlines survive intact.
    """
    raw = "" if s is None else str(s)
    return '"' + escape_orca_string(raw) + '"'


# ============================================================================
# STATIC G-CODE SAFETY LINTER & UNIFIED DIFF
# ============================================================================

_RE_HOMING = re.compile(
    r"(?:^|\s)(?:G28\b|G32\b|_?CG28\b|PRINT_START\b|START_PRINT\b|HOME\b|G29\b)",
    re.IGNORECASE,
)
_RE_MOTION_XYZ = re.compile(
    r"^\s*G0?1?\b(?=.*\b[XYZ][-+]?(?:\d|\.|\[))",
    re.IGNORECASE,
)
_RE_NOZZLE_OFF = re.compile(
    r"(?:\bM10[49]\b[^;]*\bS0(?:\.0+)?\b|\bTURN_OFF_HEATERS\b|\bPRINT_END\b|\bEND_PRINT\b|"
    r"\bSET_HEATER_TEMPERATURE\b[^;]*\bHEATER=extruder\b[^;]*\bTARGET=0(?:\.0+)?\b)",
    re.IGNORECASE,
)
_RE_BED_OFF = re.compile(
    r"(?:\bM1[49]0\b[^;]*\bS0(?:\.0+)?\b|\bTURN_OFF_HEATERS\b|\bPRINT_END\b|\bEND_PRINT\b|"
    r"\bSET_HEATER_TEMPERATURE\b[^;]*\bHEATER=heater_bed\b[^;]*\bTARGET=0(?:\.0+)?\b)",
    re.IGNORECASE,
)
_RE_NOZZLE_TEMP_LIT = re.compile(r"\bM10[49]\b[^;]*\bS(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_RE_BED_TEMP_LIT = re.compile(r"\bM1[49]0\b[^;]*\bS(\d+(?:\.\d+)?)\b", re.IGNORECASE)


def _strip_gcode_comment(line: str) -> str:
    """Strip inline `;` comment from a G-code line."""
    idx = line.find(";")
    return line[:idx] if idx >= 0 else line


def _check_balanced_delimiters(text: str, open_ch: str, close_ch: str) -> bool:
    depth = 0
    for ch in text:
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def lint_custom_gcode(
    key: str,
    gcode_text: str,
    lang: str = "ru",
    old_text: str | None = None,
) -> list[dict[str, str]]:
    """
    Run static safety checks on proposed OrcaSlicer custom G-code.

    Returns:
        List of `{"level": "danger" | "warn", "text": str}` findings.
    """
    l = norm_lang(lang)
    warnings: list[dict[str, str]] = []
    text = "" if gcode_text is None else str(gcode_text)
    stripped = text.strip()
    k = str(key or "").strip()

    # 1. Empty wipe check
    if not stripped:
        had_previous = bool(old_text and str(old_text).strip())
        if had_previous or k in ("machine_start_gcode", "machine_end_gcode"):
            warnings.append({
                "level": "danger",
                "text": tr(
                    l,
                    f"Поле «{k}» будет полностью очищено! Пустой стартовый/финишный G-code может оставить принтер без парковки или с включёнными нагревателями.",
                    f"Поле «{k}» буде повністю очищено! Порожній стартовий/фінішний G-code може залишити принтер без паркування або з увімкненими нагрівачами.",
                    f"'{k}' will be wiped completely empty! Empty start/end G-code can leave the printer unhomed or heaters running.",
                ),
            })
        return warnings

    lines = text.splitlines()
    code_lines = [_strip_gcode_comment(ln).strip() for ln in lines]
    non_empty_code = [ln for ln in code_lines if ln]

    # 2. Start G-code: homing (G28) check before X/Y/Z motion
    if k == "machine_start_gcode":
        seen_homing = False
        motion_before_homing = False
        for ln in non_empty_code:
            if _RE_HOMING.search(ln):
                seen_homing = True
            elif not seen_homing and _RE_MOTION_XYZ.match(ln):
                motion_before_homing = True
                break
        if motion_before_homing:
            warnings.append({
                "level": "danger",
                "text": tr(
                    l,
                    "В стартовом G-code обнаружено перемещение (G0/G1) ДО команды парковки G28 — риск столкновения головы!",
                    "У стартовому G-code виявлено переміщення (G0/G1) ДО команди паркування G28 — ризик зіткнення голови!",
                    "Start G-code performs a G0/G1 motion BEFORE homing (G28) — risk of toolhead crash!",
                ),
            })
        elif not seen_homing:
            warnings.append({
                "level": "danger",
                "text": tr(
                    l,
                    "В стартовом G-code не найдена команда парковки (G28 / PRINT_START).",
                    "У стартовому G-code не знайдено команду паркування (G28 / PRINT_START).",
                    "Start G-code does not contain a homing command (G28 / PRINT_START).",
                ),
            })

    # 3. End G-code: heater shutoff check
    if k == "machine_end_gcode":
        joined_code = "\n".join(non_empty_code)
        if not _RE_NOZZLE_OFF.search(joined_code):
            warnings.append({
                "level": "danger",
                "text": tr(
                    l,
                    "В финишном G-code не найдено выключение нагрева сопла (M104 S0 / M109 S0 / TURN_OFF_HEATERS)!",
                    "У фінішному G-code не знайдено вимкнення нагріву сопла (M104 S0 / M109 S0 / TURN_OFF_HEATERS)!",
                    "End G-code is missing nozzle heater shutoff (M104 S0 / M109 S0 / TURN_OFF_HEATERS)!",
                ),
            })
        if not _RE_BED_OFF.search(joined_code):
            warnings.append({
                "level": "warn",
                "text": tr(
                    l,
                    "В финишном G-code не найдено выключение нагрева стола (M140 S0 / M190 S0 / TURN_OFF_HEATERS).",
                    "У фінішному G-code не знайдено вимкнення нагріву столу (M140 S0 / M190 S0 / TURN_OFF_HEATERS).",
                    "End G-code is missing bed heater shutoff (M140 S0 / M190 S0 / TURN_OFF_HEATERS).",
                ),
            })

    # 4. Extreme hardcoded temperatures
    max_nozzle = 0.0
    max_bed = 0.0
    for ln in non_empty_code:
        for m in _RE_NOZZLE_TEMP_LIT.finditer(ln):
            try:
                max_nozzle = max(max_nozzle, float(m.group(1)))
            except ValueError:
                pass
        for m in _RE_BED_TEMP_LIT.finditer(ln):
            try:
                max_bed = max(max_bed, float(m.group(1)))
            except ValueError:
                pass

    if max_nozzle > 320.0:
        warnings.append({
            "level": "danger",
            "text": tr(
                l,
                f"Обнаружена экстремальная температура сопла ({max_nozzle:g}°C > 320°C) в G-code!",
                f"Виявлено екстремальну температуру сопла ({max_nozzle:g}°C > 320°C) у G-code!",
                f"Extreme nozzle temperature ({max_nozzle:g}°C > 320°C) detected in G-code!",
            ),
        })
    if max_bed > 130.0:
        warnings.append({
            "level": "danger",
            "text": tr(
                l,
                f"Обнаружена экстремальная температура стола ({max_bed:g}°C > 130°C) в G-code!",
                f"Виявлено екстремальну температуру столу ({max_bed:g}°C > 130°C) у G-code!",
                f"Extreme bed temperature ({max_bed:g}°C > 130°C) detected in G-code!",
            ),
        })

    # 5. Unbalanced OrcaSlicer template placeholders [...] and {...}
    if not _check_balanced_delimiters(text, "[", "]"):
        warnings.append({
            "level": "warn",
            "text": tr(
                l,
                "Обнаружены несбалансированные скобки [...] шаблонов OrcaSlicer — нарезка может завершиться ошибкой синтаксиса.",
                "Виявлено незбалансовані дужки [...] шаблонів OrcaSlicer — нарізка може завершитися помилкою синтаксису.",
                "Unbalanced OrcaSlicer template brackets [...] detected — slicing may fail with a placeholder syntax error.",
            ),
        })
    if not _check_balanced_delimiters(text, "{", "}"):
        warnings.append({
            "level": "warn",
            "text": tr(
                l,
                "Обнаружены несбалансированные фигурные скобки {...} в условных выражениях G-code.",
                "Виявлено незбалансовані фігурні дужки {...} в умовних виразах G-code.",
                "Unbalanced curly braces {...} detected in G-code conditional expressions.",
            ),
        })

    return warnings


def make_unified_diff(old_text: str, new_text: str, label: str = "") -> str:
    """Build a standard unified diff between current and proposed G-code text."""
    old_str = "" if old_text is None else str(old_text)
    new_str = "" if new_text is None else str(new_text)
    if old_str == new_str:
        return ""
    tag = label or "gcode"
    diff_iter = difflib.unified_diff(
        old_str.splitlines(),
        new_str.splitlines(),
        fromfile=f"{tag} (current)",
        tofile=f"{tag} (proposed)",
        lineterm="",
    )
    return "\n".join(diff_iter)
