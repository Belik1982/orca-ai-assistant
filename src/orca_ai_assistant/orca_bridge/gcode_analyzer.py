from __future__ import annotations

import collections
import io
import re
import zipfile
from pathlib import Path
from typing import Any, Iterable

_RE_DURATION_PART = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
_RE_NOZZLE_TEMP = re.compile(r"\bS(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_RE_Z_MOVE = re.compile(r"\bZ(\d+(?:\.\d+)?)\b", re.IGNORECASE)
_RE_NUM_LIST = re.compile(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)")

# OrcaSlicer / Bambu Studio / PrusaSlicer comment matchers
_RE_EST_TIME_NORMAL = re.compile(
    r";\s*estimated printing time\s*(?:\(normal mode\))?\s*[:=]\s*(.+)$", re.IGNORECASE
)
_RE_EST_TIME_SILENT = re.compile(
    r";\s*estimated printing time\s*\(silent mode\)\s*[:=]\s*(.+)$", re.IGNORECASE
)
_RE_TOTAL_EST_TIME = re.compile(
    r"total estimated time\s*[:=]\s*([^;]+)", re.IGNORECASE
)
_RE_TOTAL_FILAMENT_G = re.compile(
    r";\s*(?:total\s+filament\s+(?:weight|used)|filament\s+used)\s*\[g\]\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
_RE_FLUSH_G = re.compile(
    r";\s*(?:total\s+)?(?:flush(?:ed)?(?:\s+filament)?|filament_flushed)\s*\[g\]\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
_RE_TOWER_G = re.compile(
    r";\s*(?:wipe|prime)\s+tower(?:\s+filament)?\s*\[g\]\s*[:=]\s*(.+)$",
    re.IGNORECASE,
)
_RE_TOTAL_LAYERS = re.compile(r";\s*total layer number\s*[:=]\s*(\d+)", re.IGNORECASE)
_RE_MAX_Z_COMMENT = re.compile(r";\s*(?:Z_HEIGHT|max_z_height)\s*[:=]\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_RE_FILAMENT_CHANGES_COMMENT = re.compile(r";\s*total filament change\s*[:=]\s*(\d+)", re.IGNORECASE)
_RE_TOOL_CMD = re.compile(r"^T(\d+)\b")


def parse_duration_to_seconds(text: str) -> int:
    """Parse duration strings like '1d 3h 42m 15s' into integer seconds."""
    if not text:
        return 0
    total = 0
    for val_s, unit in _RE_DURATION_PART.findall(str(text)):
        val = int(val_s)
        u = unit.lower()
        if u == "d":
            total += val * 86400
        elif u == "h":
            total += val * 3600
        elif u == "m":
            total += val * 60
        elif u == "s":
            total += val
    return total


def format_duration(seconds: int, signed: bool = False) -> str:
    """Format integer seconds into concise 'Xh Ym' / 'Ym Zs' string."""
    sign = ""
    if signed:
        sign = "+" if seconds > 0 else ("-" if seconds < 0 else "")
    elif seconds < 0:
        sign = "-"
    rem = abs(int(seconds))
    days, rem = divmod(rem, 86400)
    hours, rem = divmod(rem, 3600)
    mins, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins or (not parts and secs == 0):
        parts.append(f"{mins}m")
    if not days and not hours and secs:
        parts.append(f"{secs}s")
    return f"{sign}{' '.join(parts)}"


def _extract_floats(raw: str) -> list[float]:
    out: list[float] = []
    for tok in _RE_NUM_LIST.findall(raw):
        try:
            out.append(float(tok))
        except ValueError:
            pass
    return out


def _summarize_gcode_lines(
    lines: Iterable[str],
    filename: str = "sliced.gcode",
    size_bytes: int | None = None,
) -> dict[str, Any]:
    """Stream-analyze G-code lines in O(1) memory using collections.deque."""
    head_lines: list[str] = []
    tail_lines: collections.deque[str] = collections.deque(maxlen=90)

    layer_count = 0
    declared_layers = 0
    max_z = 0.0
    m104_set: set[str] = set()
    m140_set: set[str] = set()
    has_pause = False

    est_time_str = ""
    est_time_silent_str = ""
    total_filament_g = 0.0
    filament_per_slot: list[float] = []
    flush_g = 0.0
    tower_g = 0.0
    declared_changes = -1
    tool_changes = 0
    last_tool: str | None = None
    counted_bytes = 0

    for idx, raw_line in enumerate(lines):
        if size_bytes is None:
            counted_bytes += len(raw_line.encode("utf-8", errors="ignore"))
        s = raw_line.strip()
        if not s:
            continue

        if s[0] == ";":
            if idx < 220 and len(s) > 2:
                head_lines.append(s)
            if len(s) > 2:
                tail_lines.append(s)

            if s.startswith("; CHANGE_LAYER") or s.startswith(";LAYER:"):
                layer_count += 1
                continue

            m_z = _RE_MAX_Z_COMMENT.match(s)
            if m_z:
                try:
                    max_z = max(max_z, float(m_z.group(1)))
                except ValueError:
                    pass
                continue

            m_tl = _RE_TOTAL_LAYERS.match(s)
            if m_tl:
                try:
                    declared_layers = max(declared_layers, int(m_tl.group(1)))
                except ValueError:
                    pass
                continue

            m_tn = _RE_EST_TIME_NORMAL.match(s)
            if m_tn:
                cand = m_tn.group(1).strip()
                if parse_duration_to_seconds(cand) > 0:
                    est_time_str = cand
                continue

            m_ts = _RE_EST_TIME_SILENT.match(s)
            if m_ts:
                cand = m_ts.group(1).strip()
                if parse_duration_to_seconds(cand) > 0:
                    est_time_silent_str = cand
                continue

            if "total estimated time" in s.lower():
                m_te = _RE_TOTAL_EST_TIME.search(s)
                if m_te:
                    cand = m_te.group(1).strip()
                    if parse_duration_to_seconds(cand) > 0 and not est_time_str:
                        est_time_str = cand
                continue

            m_fl = _RE_FLUSH_G.match(s)
            if m_fl:
                vals = _extract_floats(m_fl.group(1))
                if vals:
                    flush_g = round(sum(vals), 2)
                continue

            m_tw = _RE_TOWER_G.match(s)
            if m_tw:
                vals = _extract_floats(m_tw.group(1))
                if vals:
                    tower_g = round(sum(vals), 2)
                continue

            m_fg = _RE_TOTAL_FILAMENT_G.match(s)
            if m_fg:
                vals = _extract_floats(m_fg.group(1))
                if vals:
                    low = s.lower()
                    if len(vals) > 1 or ("filament used [g]" in low and "total" not in low):
                        filament_per_slot = [round(v, 2) for v in vals]
                        if total_filament_g <= 0:
                            total_filament_g = round(sum(vals), 2)
                    else:
                        total_filament_g = round(vals[0], 2)
                continue

            m_fc = _RE_FILAMENT_CHANGES_COMMENT.match(s)
            if m_fc:
                try:
                    declared_changes = int(m_fc.group(1))
                except ValueError:
                    pass
                continue

            continue

        # Non-comment G-code commands
        if s.startswith(("M104 ", "M109 ")):
            m = _RE_NOZZLE_TEMP.search(s)
            if m:
                try:
                    if float(m.group(1)) > 50.0:
                        m104_set.add(m.group(1))
                except ValueError:
                    pass
        elif s.startswith(("M140 ", "M190 ")):
            m = _RE_NOZZLE_TEMP.search(s)
            if m:
                try:
                    if float(m.group(1)) > 20.0:
                        m140_set.add(m.group(1))
                except ValueError:
                    pass
        elif s.startswith(("M600", "M25", "PAUSE")):
            has_pause = True
        elif s.startswith(("G0 ", "G1 ")) and "Z" in s:
            m_zm = _RE_Z_MOVE.search(s)
            if m_zm:
                try:
                    zv = float(m_zm.group(1))
                    if 0.0 <= zv <= 2000.0:
                        max_z = max(max_z, zv)
                except ValueError:
                    pass
        else:
            m_t = _RE_TOOL_CMD.match(s)
            if m_t:
                t_id = m_t.group(1)
                if last_tool is not None and t_id != last_tool:
                    tool_changes += 1
                last_tool = t_id

    final_time_str = est_time_str or est_time_silent_str
    final_time_sec = parse_duration_to_seconds(final_time_str)
    final_layers = declared_layers if declared_layers > 0 else layer_count
    if total_filament_g <= 0 and filament_per_slot:
        total_filament_g = round(sum(filament_per_slot), 2)
    if not filament_per_slot and total_filament_g > 0:
        filament_per_slot = [round(total_filament_g, 2)]

    waste_g = round(flush_g + tower_g, 2)
    waste_pct = round((waste_g / total_filament_g) * 100.0, 1) if total_filament_g > 0 else 0.0
    model_g = round(max(0.0, total_filament_g - waste_g), 2) if total_filament_g > 0 else 0.0
    changes_count = declared_changes if declared_changes >= 0 else tool_changes

    total_bytes = size_bytes if size_bytes is not None else counted_bytes

    def _float_sort_key(v: str) -> float:
        try:
            return float(v)
        except ValueError:
            return 0.0

    tail_list = list(tail_lines)
    return {
        "ok": True,
        "filename": filename,
        "size_mb": round(total_bytes / (1024 * 1024), 2),
        "estimated_time_str": final_time_str,
        "estimated_time_sec": final_time_sec,
        "total_filament_g": round(total_filament_g, 2),
        "model_filament_g": model_g,
        "filament_used_g_per_slot": filament_per_slot,
        "flush_g": round(flush_g, 2),
        "tower_g": round(tower_g, 2),
        "waste_g": waste_g,
        "waste_pct": waste_pct,
        "filament_changes": changes_count,
        "header_comments": head_lines[:60],
        "footer_comments": tail_list[-80:],
        "layer_count": final_layers,
        "max_z": round(max_z, 2),
        "m104_temps": sorted(m104_set, key=_float_sort_key),
        "m140_temps": sorted(m140_set, key=_float_sort_key),
        "has_m600_pause": has_pause,
    }


def summarize_gcode_text(gcode_text: str, filename: str = "sliced.gcode") -> dict[str, Any]:
    """Summarize G-code from an in-memory string."""
    text = "" if gcode_text is None else str(gcode_text)
    size_bytes = len(text.encode("utf-8", errors="ignore"))
    return _summarize_gcode_lines(io.StringIO(text), filename=filename, size_bytes=size_bytes)


def summarize_gcode_file(path: str | Path) -> dict[str, Any]:
    """
    Stream-summarize a `.gcode` or `.gcode.3mf` file directly from disk
    without loading large files into RAM.
    """
    p = Path(path)
    if not p.is_file():
        return {"ok": False, "filename": p.name, "error": f"File not found: {p}"}

    size_bytes = p.stat().st_size

    # Support `.gcode.3mf` (ZIP archive containing Metadata/plate_*.gcode)
    if p.suffix.lower() == ".3mf" or zipfile.is_zipfile(p):
        try:
            with zipfile.ZipFile(p, "r") as zf:
                names = zf.namelist()
                plate_gcodes = sorted(
                    n for n in names
                    if re.match(r"^Metadata/plate_\d+\.gcode$", n, re.IGNORECASE)
                )
                if not plate_gcodes:
                    plate_gcodes = sorted(n for n in names if n.lower().endswith(".gcode"))
                if not plate_gcodes:
                    return {
                        "ok": False,
                        "filename": p.name,
                        "error": "No embedded plate_*.gcode found inside 3MF archive.",
                    }

                def _iter_zip_lines() -> Iterable[str]:
                    for member in plate_gcodes:
                        with zf.open(member, "r") as raw_stream:
                            text_stream = io.TextIOWrapper(raw_stream, encoding="utf-8", errors="replace")
                            yield from text_stream

                res = _summarize_gcode_lines(_iter_zip_lines(), filename=p.name, size_bytes=size_bytes)
                res["embedded_gcode_files"] = plate_gcodes
                return res
        except Exception as exc:
            return {"ok": False, "filename": p.name, "error": f"Failed to read 3MF G-code: {exc}"}

    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            return _summarize_gcode_lines(fh, filename=p.name, size_bytes=size_bytes)
    except Exception as exc:
        return {"ok": False, "filename": p.name, "error": f"Failed to read G-code file: {exc}"}


def compute_slice_delta(
    baseline: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """
    Compute Before -> After slicing impact deltas (time, total filament grams, purge/tower waste).
    """
    if not isinstance(baseline, dict) or not isinstance(current, dict):
        return None
    if not baseline.get("ok") or not current.get("ok"):
        return None

    base_sec = int(baseline.get("estimated_time_sec") or 0)
    cur_sec = int(current.get("estimated_time_sec") or 0)
    time_delta_sec: int | None = (cur_sec - base_sec) if (base_sec > 0 and cur_sec > 0) else None
    time_delta_str = format_duration(time_delta_sec, signed=True) if time_delta_sec is not None else ""

    base_g = float(baseline.get("total_filament_g") or 0.0)
    cur_g = float(current.get("total_filament_g") or 0.0)
    grams_delta: float | None = round(cur_g - base_g, 2) if (base_g > 0 and cur_g > 0) else None

    base_waste = float(baseline.get("waste_g") or 0.0)
    cur_waste = float(current.get("waste_g") or 0.0)
    waste_delta_g: float | None = round(cur_waste - base_waste, 2) if (base_waste > 0 or cur_waste > 0) else None

    parts: list[str] = []
    if time_delta_sec is not None:
        parts.append(
            f"{format_duration(base_sec)} -> {format_duration(cur_sec)} ({time_delta_str})"
        )
    if grams_delta is not None:
        sign = "+" if grams_delta > 0 else ""
        parts.append(f"{base_g:.1f}g -> {cur_g:.1f}g ({sign}{grams_delta:.1f}g)")
    if waste_delta_g is not None and (base_waste > 0 or cur_waste > 0):
        wsign = "+" if waste_delta_g > 0 else ""
        parts.append(f"waste {base_waste:.1f}g -> {cur_waste:.1f}g ({wsign}{waste_delta_g:.1f}g)")

    return {
        "time_delta_sec": time_delta_sec,
        "time_delta_str": time_delta_str,
        "baseline_time_str": baseline.get("estimated_time_str") or (format_duration(base_sec) if base_sec > 0 else ""),
        "current_time_str": current.get("estimated_time_str") or (format_duration(cur_sec) if cur_sec > 0 else ""),
        "grams_delta": grams_delta,
        "baseline_grams": round(base_g, 2),
        "current_grams": round(cur_g, 2),
        "waste_delta_g": waste_delta_g,
        "baseline_waste_g": round(base_waste, 2),
        "current_waste_g": round(cur_waste, 2),
        "summary": " | ".join(parts),
    }
