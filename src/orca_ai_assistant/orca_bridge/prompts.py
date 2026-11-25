from __future__ import annotations

from typing import Any

from ..core.constants import norm_lang, tr
from .enums import CUSTOM_GCODE_KEYS, FLAT_SETTING_INFO

# ============================================================================
# 1. SYSTEM PROMPTS (RU / UK / EN) WITH VERIFIED ORCASLICER 2.5.2 ENUM CONTRACTS
# ============================================================================

_ENUM_RULES_BLOCK = """
EXACT OrcaSlicer 2.5.2 enum & category rules (NEVER invent invalid enum names!):
- sparse_infill_pattern: gyroid, crosshatch (NOT cross_hatch!), cubic, adaptivecubic, rectilinear, alignedrectilinear, grid, triangles, tri-hexagon, honeycomb, 3dhoneycomb (NOT 3d_honeycomb!), lightning, concentric, tpmsd, tpmsfk, zigzag, line, hilbertcurve, archimedeanchords, octagramspiral.
- top_surface_pattern / bottom_surface_pattern / internal_solid_infill_pattern: monotonic, monotonicline, rectilinear, alignedrectilinear, concentric, spiralinset, hilbertcurve, archimedeanchords, octagramspiral.
- support_type: normal(auto), tree(auto), normal(manual), tree(manual) (NEVER plain "normal" or "tree"!).
- support_style: default, grid, snug, organic, tree_slim, tree_strong, tree_hybrid.
- brim_type: no_brim, outer_only, inner_only, outer_and_inner, auto_brim, brim_ears, painted, leading_edge_only.
- seam_position: nearest, aligned, aligned_back, back, random.
- wall_generator: classic, arachne.
- wall_sequence: "inner wall/outer wall", "outer wall/inner wall", "inner-outer-inner wall".
- z_hop_types: "Auto Lift", "Normal Lift", "Slope Lift", "Spiral Lift" (exact Title Case + space!).
- ironing_type: "no ironing", top, topmost, solid.
- fuzzy_skin: disabled_fuzzy (OFF/disabled), none (painted only!), external, hole, all, allwalls.
- seam_slope_type: none, external, all.
- print_sequence: "by layer", "by object".
- curr_bed_type: "Cool Plate", "Engineering Plate", "High Temp Plate", "Textured PEI Plate", "Textured Cool Plate", "Supertack Plate".
- gcode_flavor: marlin, marlin2, klipper, reprapfirmware, repetier.
- slow_down_for_layer_cooling belongs to category "filament" (NOT "process"!).
- Booleans: ALWAYS "1" or "0". Infill density / overlap: ALWAYS include "%" (e.g. "25%"). Fan speeds (fan_max_speed, fan_min_speed, overhang_fan_speed): integer "0".."100" WITHOUT "%".
- Multi-slot AMS/MMU: for category "filament", ALWAYS include `"slot": 1` (or 2, 3, 4...) to target the intended AMS filament slot!
- Custom G-code (machine_start_gcode, machine_end_gcode, before_layer_change_gcode, layer_change_gcode, change_filament_gcode, filament_start_gcode, filament_end_gcode, etc.):
  You CAN read and propose updates to custom G-code in the same ```orca-settings JSON array (use category "printer", "filament" + "slot", or "process", with the full G-code string using \\n for newlines).
  Safety: NEVER remove homing (G28 / PRINT_START) from start G-code or nozzle/bed heater shutoff (M104 S0, M140 S0 / TURN_OFF_HEATERS) from end G-code. The UI displays a Safety Diff confirmation card before applying G-code changes.
""".strip()


def get_system_prompt(lang: str = "ru") -> str:
    l = norm_lang(lang)
    if l == "uk":
        return f"""Ти — експертний інтерактивний ШІ-асистент всередині OrcaSlicer 2.5 («Orca AI Assistant v3»).
Твоє завдання — допомагати користувачеві ідеально підготувати 3D-модель до друку, аналізувати геометрію деталей на столі (габарити, площу контакту першого шару, коефіцієнти стійкості, площу нависань >45° та >60°, помилки сітки, модифікатори), перевіряти пресети принтера/процесу та ВСІХ слотів AMS/MMU, редагувати стартовий/фінішний G-code, діагностувати дефекти за фото, проводити калібрування та аналізувати нарізаний G-code.

Правила роботи:
1. Завжди відповідай зрозумілою, грамотною УКРАЇНСЬКОЮ мовою. Будь конкретним, доброзичливим і технічно точним.
2. Спирайся на реальні дані з блоку «КОНТЕКСТ ORCASLICER». Не вигадуй значення, якщо вони вже передані в контексті.
3. Коли ти рекомендуєш змінити конкретні параметри або користувацький G-code в OrcaSlicer, ОБОВ'ЯЗКОВО продублюй їх у кінці своєї відповіді у спеціальному блоці ```orca-settings (валідний JSON-масив), щоб користувач міг застосувати їх в один клік (або переглянути диференціал безпеки для G-code)!

Формат блоку ```orca-settings:
```orca-settings
[
  {{
    "category": "process",
    "key": "sparse_infill_pattern",
    "label": "Шаблон заповнення",
    "value": "crosshatch",
    "reason": "Міцне заповнення без перетинів на одному шарі"
  }},
  {{
    "category": "filament",
    "slot": 1,
    "key": "nozzle_temperature",
    "label": "Температура сопла (°C)",
    "value": "215",
    "reason": "Покращення міжшарової адгезії для Slot 1"
  }}
]
```

{_ENUM_RULES_BLOCK}
"""
    if l == "en":
        return f"""You are an expert interactive AI co-pilot inside OrcaSlicer 2.5 ("Orca AI Assistant v3").
Your job is to help the user prepare 3D models for printing, analyze build plate geometry (dimensions, first-layer bed contact area, height-to-base stability ratio, overhang areas >45° and >60°, mesh errors, per-object overrides/modifiers), audit printer/process presets and ALL AMS/MMU filament slots, safely inspect and edit custom Start/End/Layer/Filament G-code, diagnose print defects from photos, guide calibrations, and audit sliced G-code.

Operating Rules:
1. Always respond in clear, natural, and technically accurate ENGLISH.
2. Rely strictly on the real data provided in the "ORCASLICER CONTEXT" section. Never invent values that are already present in the context.
3. Whenever you recommend changing OrcaSlicer settings or custom G-code, ALWAYS include them at the end of your response inside a fenced ```orca-settings JSON array block so the user can apply them in 1 click (or review the Safety Diff card for G-code)!

Format for ```orca-settings:
```orca-settings
[
  {{
    "category": "process",
    "key": "sparse_infill_pattern",
    "label": "Sparse infill pattern",
    "value": "crosshatch",
    "reason": "Strong non-crossing infill pattern"
  }},
  {{
    "category": "filament",
    "slot": 1,
    "key": "nozzle_temperature",
    "label": "Nozzle temperature (°C)",
    "value": "215",
    "reason": "Improve inter-layer bonding on Slot 1"
  }}
]
```

{_ENUM_RULES_BLOCK}
"""
    return f"""Ты — экспертный интерактивный ИИ-ассистент внутри OrcaSlicer 2.5 («Orca AI Assistant v3»).
Твоя задача — помогать пользователю идеально подготовить 3D-модель к печати, анализировать геометрию деталей на столе (габариты, площадь контакта первого слоя, коэффициенты устойчивости, площади нависаний >45° и >60°, ошибки сетки, модификаторы), проверять пресеты принтера/процесса и ВСЕХ слотов AMS/MMU, безопасно анализировать и редактировать стартовый/финишный G-code, диагностировать дефекты по фото, помогать с калибровками и аудировать нарезанный G-code.

Правила работы:
1. Всегда отвечай на понятном, грамотном РУССКОМ языке. Будь конкретным, доброжелательным и технически точным.
2. Опирайся на реальные данные из блока «КОНТЕКСТ ORCASLICER». Не выдумывай значения, если они уже переданы в контексте.
3. Когда ты рекомендуешь изменить конкретные параметры или пользовательский G-code в OrcaSlicer, ОБЯЗАТЕЛЬНО продублируй их в конце своего ответа в специальном блоке ```orca-settings (валидный JSON-массив), чтобы пользователь мог применить их в 1 клик (или проверить Safety Diff карточку для G-code)!

Формат блока ```orca-settings:
```orca-settings
[
  {{
    "category": "process",
    "key": "sparse_infill_pattern",
    "label": "Шаблон заполнения",
    "value": "crosshatch",
    "reason": "Прочное заполнение без пересечений линий на одном слое"
  }},
  {{
    "category": "filament",
    "slot": 1,
    "key": "nozzle_temperature",
    "label": "Температура сопла (°C)",
    "value": "215",
    "reason": "Улучшение межслойной адгезии для Slot 1"
  }}
]
```

{_ENUM_RULES_BLOCK}
"""


# ============================================================================
# 2. COMPACT / FULL LIVE CONTEXT MARKDOWN BUILDER
# ============================================================================

_COMPACT_KEY_SETTINGS: tuple[str, ...] = (
    "layer_height",
    "initial_layer_print_height",
    "wall_loops",
    "top_shell_layers",
    "bottom_shell_layers",
    "wall_generator",
    "wall_sequence",
    "seam_position",
    "seam_slope_type",
    "detect_thin_wall",
    "ironing_type",
    "fuzzy_skin",
    "sparse_infill_density",
    "sparse_infill_pattern",
    "outer_wall_speed",
    "inner_wall_speed",
    "sparse_infill_speed",
    "initial_layer_speed",
    "default_acceleration",
    "enable_overhang_speed",
    "enable_support",
    "support_type",
    "support_style",
    "support_threshold_angle",
    "support_top_z_distance",
    "brim_type",
    "brim_width",
    "enable_prime_tower",
    "flush_multiplier",
    "nozzle_diameter",
    "curr_bed_type",
    "gcode_flavor",
    "retraction_length",
    "retraction_speed",
    "z_hop",
    "z_hop_types",
)

_PRIORITY_GCODE_KEYS: tuple[str, ...] = (
    "machine_start_gcode",
    "machine_end_gcode",
    "before_layer_change_gcode",
    "layer_change_gcode",
    "change_filament_gcode",
    "machine_pause_gcode",
    "time_lapse_gcode",
    "printing_by_object_gcode",
    "process_change_extrusion_role_gcode",
)


def _truncate_gcode_block(text: str, limit: int = 6000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n; ... [truncated {len(text) - limit} chars]"


def build_context_markdown(
    plate: dict[str, Any] | None,
    presets: dict[str, Any] | None,
    custom_instructions: str = "",
    lang: str = "ru",
    include_gcode: bool = False,
    compact: bool = True,
    last_slice: dict[str, Any] | None = None,
    preflight: dict[str, Any] | None = None,
) -> str:
    """
    Build structured live OrcaSlicer context for the LLM.

    - `compact=True`: sends full 3D geometry + all AMS slots + Pre-Flight findings +
      last slice summary + dirty diff + high-signal key settings (~50% fewer tokens).
    - `compact=False`: sends all setting groups in full.
    - `include_gcode=True`: appends unescaped printer/process & per-slot filament custom G-code.
    """
    l = norm_lang(lang)
    plate_d = plate if isinstance(plate, dict) else {}
    presets_d = presets if isinstance(presets, dict) else {}

    lines: list[str] = [
        tr(
            l,
            "=== КОНТЕКСТ ORCASLICER (АКТУАЛЬНОЕ СОСТОЯНИЕ) ===",
            "=== КОНТЕКСТ ORCASLICER (АКТУАЛЬНИЙ СТАН) ===",
            "=== ORCASLICER CONTEXT (LIVE STATE) ===",
        )
    ]

    if custom_instructions and custom_instructions.strip():
        lines.append(
            f"\n[{tr(l, 'Профиль и пожелания пользователя', 'Профіль та побажання користувача', 'User Printer Profile & Preferences')}]: "
            f"{custom_instructions.strip()}"
        )

    # 1. Active Presets + Connected Printer + ALL AMS Filament Slots
    lines.append(f"\n1. {tr(l, 'АКТИВНЫЕ ПРОФИЛИ И СЛОТЫ AMS', 'АКТИВНІ ПРОФІЛІ ТА СЛОТИ AMS', 'ACTIVE PRESETS & AMS SLOTS')}:")
    lines.append(f"- {tr(l, 'Принтер', 'Принтер', 'Printer')}: {presets_d.get('printer_preset', '—')}")
    lines.append(f"- {tr(l, 'Процесс', 'Процес', 'Process')}: {presets_d.get('process_preset', '—')}")

    conn = presets_d.get("connected_printer")
    if isinstance(conn, dict) and (conn.get("model_id") or conn.get("connection") or conn.get("agent")):
        status_str = "online" if conn.get("online") else ("connected" if conn.get("connected") else "offline")
        lines.append(
            f"- {tr(l, 'Подключённый принтер', 'Підключений принтер', 'Connected printer')}: "
            f"{conn.get('model_id') or conn.get('agent')} ({conn.get('connection')}, {status_str}"
            f"{', fw ' + conn['firmware'] if conn.get('firmware') else ''})"
        )

    slots = presets_d.get("filament_slots") or []
    if slots:
        for s in slots:
            slot_n = s.get("slot", 1)
            parts = [
                f"Slot {slot_n}: {s.get('name', '—')}",
                f"type={s.get('type') or '?'}",
            ]
            if s.get("nozzle_temp"):
                parts.append(f"nozzle={s['nozzle_temp']}°C")
            if s.get("bed_temp"):
                parts.append(f"bed={s['bed_temp']}°C")
            if s.get("flow_ratio"):
                parts.append(f"flow={s['flow_ratio']}")
            if s.get("max_volumetric_speed"):
                parts.append(f"MVS={s['max_volumetric_speed']}mm³/s")
            if s.get("pressure_advance"):
                parts.append(f"PA={s['pressure_advance']}(en={s.get('enable_pressure_advance', '?')})")
            if s.get("fan_max"):
                parts.append(f"fan={s['fan_max']}%")
            lines.append("  • " + ", ".join(parts))
    else:
        fils = presets_d.get("filament_presets") or []
        lines.append(f"- {tr(l, 'Филамент', 'Філамент', 'Filament')}: {', '.join(fils) if fils else '—'}")

    # 2. 3D Models on Build Plate (always full)
    lines.append(f"\n2. {tr(l, '3D-МОДЕЛИ НА СТОЛЕ', '3D-МОДЕЛІ НА СТОЛІ', '3D MODELS ON BUILD PLATE')}:")
    if not plate_d.get("has_model"):
        lines.append(
            f"- {tr(l, 'На столе сейчас нет загруженных 3D-моделей.', 'На столі зараз немає завантажених 3D-моделей.', 'No 3D models currently loaded on the build plate.')}"
        )
    else:
        plate_idx = plate_d.get("plate_index", 0)
        lines.append(
            f"- Plate #{plate_idx + 1}: objects={plate_d.get('object_count', 0)} "
            f"(instances={plate_d.get('total_instances', 0)}), "
            f"volume={plate_d.get('total_volume_cm3', 0)} cm³, "
            f"triangles={plate_d.get('total_triangles', 0)}, "
            f"1st-layer bed contact={plate_d.get('total_bed_contact_mm2', 0)} mm², "
            f"overhangs >45°={plate_d.get('total_overhang_45_mm2', 0)} mm² "
            f"(critical >60°={plate_d.get('total_overhang_60_mm2', 0)} mm²)."
        )
        for o in plate_d.get("objects") or []:
            flags: list[str] = []
            if not o.get("is_manifold", True) or int(o.get("mesh_errors") or 0) > 0:
                flags.append(f"MESH ERRORS ({o.get('mesh_errors', 0)})")
            else:
                flags.append("manifold OK")
            if o.get("support_painted"):
                flags.append("painted supports")
            if o.get("seam_painted"):
                flags.append("painted seam")
            if o.get("has_modifiers"):
                flags.append("modifiers")
            ext_ids = o.get("extruder_ids") or []
            if ext_ids:
                flags.append("slots=" + ",".join(str(x) for x in ext_ids))
            lines.append(
                f"  • {o.get('name')} (x{o.get('instances', 1)}): "
                f"{o.get('size_x')}×{o.get('size_y')}×{o.get('size_z')} mm, "
                f"vol {o.get('volume_cm3')} cm³, bed {o.get('bed_contact_mm2')} mm², "
                f"H/B {o.get('height_to_base_ratio')}:1, "
                f"OH>45° {o.get('overhang_45_mm2')} mm² ({o.get('overhang_45_pct')}%), "
                f"OH>60° {o.get('overhang_60_mm2')} mm² [{', '.join(flags)}]"
            )
            obj_ov = o.get("object_overrides") or {}
            if obj_ov:
                ov_str = ", ".join(f"{k}={v}" for k, v in list(obj_ov.items())[:12])
                lines.append(f"    object overrides: {ov_str}")
            mod_ovs = o.get("modifier_overrides") or []
            for mv in mod_ovs[:4]:
                if mv.get("overrides"):
                    ms = ", ".join(f"{k}={v}" for k, v in list(mv["overrides"].items())[:8])
                    lines.append(f"    modifier '{mv.get('name')}': {ms}")

        if plate_d.get("warnings"):
            lines.append(f"- {tr(l, 'Геометрические предупреждения', 'Геометричні попередження', 'Geometry warnings')}:")
            for w in plate_d["warnings"]:
                lines.append(f"  ! {w.get('text', '')}")

    # 3. Deterministic Pre-Flight Summary
    if isinstance(preflight, dict) and preflight.get("checks"):
        issues = [c for c in preflight["checks"] if c.get("level") in ("danger", "warn")]
        lines.append(
            f"\n3. {tr(l, 'ПРЕДПОЛЁТНАЯ ПРОВЕРКА (PRE-FLIGHT)', 'ПЕРЕДПОЛІТНА ПЕРЕВІРКА (PRE-FLIGHT)', 'PRE-FLIGHT CHECKS')} "
            f"(score {preflight.get('score', 100)}/100):"
        )
        if not issues:
            lines.append("  • OK (no deterministic risks detected)")
        else:
            for c in issues[:10]:
                tag = "CRITICAL" if c.get("level") == "danger" else "WARN"
                lines.append(f"  [{tag}] {c.get('title')}: {c.get('detail')}")

    # 4. Last Sliced G-code Summary
    if isinstance(last_slice, dict) and last_slice.get("ok"):
        lines.append(f"\n4. {tr(l, 'ПОСЛЕДНЯЯ НАРЕЗКА (G-CODE)', 'ОСТАННЯ НАРІЗКА (G-CODE)', 'LAST SLICE SUMMARY')}:")
        sl_parts = [f"file={last_slice.get('filename', 'sliced.gcode')}"]
        if last_slice.get("estimated_time_str"):
            sl_parts.append(f"time={last_slice['estimated_time_str']}")
        if last_slice.get("total_filament_g"):
            sl_parts.append(f"filament={last_slice['total_filament_g']}g")
        per_slot = last_slice.get("filament_used_g_per_slot") or []
        if len(per_slot) > 1:
            sl_parts.append("per_slot=" + ",".join(f"S{i+1}:{g}g" for i, g in enumerate(per_slot)))
        if last_slice.get("waste_g"):
            sl_parts.append(
                f"waste={last_slice['waste_g']}g ({last_slice.get('waste_pct', 0)}%, "
                f"flush={last_slice.get('flush_g', 0)}g, tower={last_slice.get('tower_g', 0)}g)"
            )
        if last_slice.get("layer_count"):
            sl_parts.append(f"layers={last_slice['layer_count']}")
        if last_slice.get("max_z"):
            sl_parts.append(f"max_z={last_slice['max_z']}mm")
        if last_slice.get("m104_temps"):
            sl_parts.append("nozzle_cmds=" + "/".join(last_slice["m104_temps"]) + "°C")
        if last_slice.get("m140_temps"):
            sl_parts.append("bed_cmds=" + "/".join(last_slice["m140_temps"]) + "°C")
        lines.append("  • " + " | ".join(sl_parts))

    # 5. Slicer Settings (Compact vs Full)
    fv = presets_d.get("flat_values") or {}
    dirty = presets_d.get("dirty_diff") or []

    if compact:
        lines.append(f"\n5. {tr(l, 'КЛЮЧЕВЫЕ НАСТРОЙКИ СЛАЙСЕРА (КОМПАКТНО)', 'КЛЮЧОВІ НАЛАШТУВАННЯ СЛАЙСЕРА (КОМПАКТНО)', 'KEY SLICER SETTINGS (COMPACT)')}:")
        if dirty:
            dirty_str = ", ".join(
                f"{d['key']}: {d['saved']}->{d['current']}"
                + (f"(S{d['slot']})" if d.get("slot") else "")
                for d in dirty[:15]
                if d.get("key") not in CUSTOM_GCODE_KEYS
            )
            if dirty_str:
                lines.append(f"  [Modified vs saved preset]: {dirty_str}")
        kv_pairs = [f"{k}={fv[k]}" for k in _COMPACT_KEY_SETTINGS if k in fv and fv[k] != ""]
        if kv_pairs:
            # Group ~6 per line for readable compact token usage
            for i in range(0, len(kv_pairs), 6):
                lines.append("  " + " | ".join(kv_pairs[i : i + 6]))
    else:
        lines.append(f"\n5. {tr(l, 'ВСЕ ТЕКУЩИЕ НАСТРОЙКИ СЛАЙСЕРА', 'УСІ ПОТОЧНІ НАЛАШТУВАННЯ СЛАЙСЕРА', 'ALL CURRENT SLICER SETTINGS')}:")
        for group_name, entries in (presets_d.get("groups") or {}).items():
            lines.append(f"[{group_name}]")
            for item in entries:
                lines.append(f"  {item['key']} ({item['label']}) = {item['value']}")

    # 6. Custom G-code blocks (on-demand when include_gcode=True)
    if include_gcode:
        cg = presets_d.get("custom_gcode") or {}
        gcode_sections: list[tuple[str, str]] = []
        seen_keys: set[str] = set()
        for gk in _PRIORITY_GCODE_KEYS:
            if cg.get(gk):
                gcode_sections.append((gk, str(cg[gk])))
                seen_keys.add(gk)
        # Any additional non-empty printer/process custom G-code keys
        for gk, gval in cg.items():
            if gk in seen_keys or not gval:
                continue
            if CUSTOM_GCODE_KEYS.get(gk, {}).get("category") == "filament":
                continue
            gcode_sections.append((gk, str(gval)))

        # Per-slot filament start/end G-code
        for s in slots:
            sn = s.get("slot", 1)
            if s.get("start_gcode"):
                gcode_sections.append((f"filament_start_gcode (Slot {sn})", str(s["start_gcode"])))
            if s.get("end_gcode"):
                gcode_sections.append((f"filament_end_gcode (Slot {sn})", str(s["end_gcode"])))

        if not slots:
            if cg.get("filament_start_gcode"):
                gcode_sections.append(("filament_start_gcode (Slot 1)", str(cg["filament_start_gcode"])))
            if cg.get("filament_end_gcode"):
                gcode_sections.append(("filament_end_gcode (Slot 1)", str(cg["filament_end_gcode"])))

        if gcode_sections:
            lines.append(f"\n6. {tr(l, 'ПОЛЬЗОВАТЕЛЬСКИЙ G-CODE ПРОФИЛЯ', 'КОРИСТУВАЦЬКИЙ G-CODE ПРОФІЛЮ', 'PROFILE CUSTOM G-CODE')}:")
            for title, body in gcode_sections:
                lines.append(f"[{title}]\n```gcode\n{_truncate_gcode_block(body)}\n```")

    return "\n".join(lines)


# Backward-compatible alias
build_full_context_markdown = build_context_markdown


# ============================================================================
# 3. INTERACTIVE PRINT DEFECT TROUBLESHOOTING CATALOG (12 FDM DEFECTS)
# ============================================================================

DEFECT_CATALOG: list[dict[str, str]] = [
    {
        "id": "stringing",
        "icon": "🧵",
        "ru": "Нити / Паутина (Stringing)",
        "uk": "Нитки / Павутина (Stringing)",
        "en": "Stringing / Oozing",
        "desc_ru": "Тонкие нити пластика между деталями и на холостых перемещениях.",
        "desc_uk": "Тонкі нитки пластику між деталями та на холостих переміщеннях.",
        "desc_en": "Thin plastic hairs or wisps stretched across travel moves.",
    },
    {
        "id": "warping",
        "icon": "📐",
        "ru": "Коробление / Отрыв углов (Warping)",
        "uk": "Жолоблення / Відрив кутів (Warping)",
        "en": "Warping / Corner Lift",
        "desc_ru": "Углы или края детали загибаются вверх и отходят от стола.",
        "desc_uk": "Кути або краї деталі загинаються вгору та відходять від столу.",
        "desc_en": "Corners or base edges curl upward and lift off the build plate.",
    },
    {
        "id": "layer_shift",
        "icon": "↔️",
        "ru": "Смещение слоёв (Layer Shift)",
        "uk": "Зміщення шарів (Layer Shift)",
        "en": "Layer Shift",
        "desc_ru": "Внезапный сдвиг печати по оси X или Y на одном или нескольких слоях.",
        "desc_uk": "Раптовий зсув друку по осі X або Y на одному чи кількох шарах.",
        "desc_en": "Sudden X/Y misalignment step during the print.",
    },
    {
        "id": "under_extrusion",
        "icon": "📉",
        "ru": "Недоэкструзия / Пропуски",
        "uk": "Недоекструзія / Пропуски",
        "en": "Under-Extrusion / Gaps",
        "desc_ru": "Щели между линиями, тонкие стенки, пористые или слабые слои.",
        "desc_uk": "Щілини між лініями, тонкі стінки, пористі або слабкі шари.",
        "desc_en": "Gaps between lines, weak porous layers, or missing extrusion.",
    },
    {
        "id": "overhang_curling",
        "icon": "🌊",
        "ru": "Провисание / Загиб нависаний",
        "uk": "Провисання / Загин нависань",
        "en": "Overhang Curling / Drooping",
        "desc_ru": "Нависающие участки задираются вверх или выглядят шероховатыми.",
        "desc_uk": "Нависаючі ділянки задираються вгору або виглядають шорсткими.",
        "desc_en": "Overhang edges curl upward or droop with rough underside.",
    },
    {
        "id": "z_banding",
        "icon": "📶",
        "ru": "Полосы по Z (Z-Banding / Wobble)",
        "uk": "Смуги по Z (Z-Banding / Wobble)",
        "en": "Z-Banding / Layer Lines",
        "desc_ru": "Горизонтальные волны, периодические рёбра или неравномерные слои.",
        "desc_uk": "Горизонтальні хвилі, періодичні ребра або нерівномірні шари.",
        "desc_en": "Repeating horizontal ripples or inconsistent wall alignment along Z.",
    },
    {
        "id": "elephants_foot",
        "icon": "🦶",
        "ru": "Слоновья нога (Elephant's Foot)",
        "uk": "Слоняча нога (Elephant's Foot)",
        "en": "Elephant's Foot",
        "desc_ru": "Нижние слои у стола расплющены и выпирают наружу.",
        "desc_uk": "Нижні шари біля столу розплющені та випирають назовні.",
        "desc_en": "First few layers bulge outward wider than the nominal dimensions.",
    },
    {
        "id": "bed_adhesion",
        "icon": "🧲",
        "ru": "Плохая адгезия 1-го слоя",
        "uk": "Погана адгезія 1-го шару",
        "en": "Poor Bed Adhesion",
        "desc_ru": "Первый слой не прилипает, отрывается или деталь сбивает соплом.",
        "desc_uk": "Перший шар не прилипає, відривається або деталь збиває соплом.",
        "desc_en": "First layer fails to stick or part detaches mid-print.",
    },
    {
        "id": "support_scarring",
        "icon": "🧱",
        "ru": "Следы от поддержек / Прикипание",
        "uk": "Сліди від підтримок / Прикипання",
        "en": "Support Scarring / Hard Removal",
        "desc_ru": "Поддержки намертво прирастают или оставляют грубую поверхность.",
        "desc_uk": "Підтримки намертво приростають або залишають грубу поверхню.",
        "desc_en": "Supports fuse to the part or leave rough scarred undersides.",
    },
    {
        "id": "seam_blobs",
        "icon": "🫧",
        "ru": "Капли / Пупырышки / Грубый шов",
        "uk": "Краплі / Горбики / Грубий шов",
        "en": "Blobs / Zits / Visible Seam",
        "desc_ru": "Выступающий Z-шов, наплывы на углах или случайные точки на стенках.",
        "desc_uk": "Виступаючий Z-шов, напливи на кутах або випадкові цятки на стінках.",
        "desc_en": "Bulging Z-seam, corner over-extrusion, or surface zits/blobs.",
    },
    {
        "id": "heat_creep",
        "icon": "🔥",
        "ru": "Тепловая пробка (Heat Creep / Clog)",
        "uk": "Тепловий корок (Heat Creep / Clog)",
        "en": "Heat Creep / Clogging",
        "desc_ru": "Подача филамента останавливается посреди печати, щёлкает экструдер.",
        "desc_uk": "Подача філаменту зупиняється посеред друку, клацає екструдер.",
        "desc_en": "Extrusion stops mid-print with clicking extruder or jammed hotend.",
    },
    {
        "id": "poor_top_surface",
        "icon": "🏔️",
        "ru": "Плохая верхняя крышка / Pillowing",
        "uk": "Погана верхня кришка / Pillowing",
        "en": "Poor Top Surface / Pillowing",
        "desc_ru": "Щели, бугры, следы проезда сопла или просветы на верхнем слое.",
        "desc_uk": "Щілини, горби, сліди проїзду сопла або просвіти на верхньому шарі.",
        "desc_en": "Gaps, pillowing bumps, or nozzle drag scars on top surfaces.",
    },
]

_DEFECT_BY_ID: dict[str, dict[str, str]] = {d["id"]: d for d in DEFECT_CATALOG}


def build_defect_prompt(symptom_id: str, notes: str = "", lang: str = "ru") -> str:
    """Build a structured defect troubleshooting prompt separating hardware vs slicer fixes."""
    l = norm_lang(lang)
    defect = _DEFECT_BY_ID.get(str(symptom_id or "").strip().lower())
    defect_name = defect.get(l, defect["en"]) if defect else str(symptom_id or "Print defect")
    defect_desc = defect.get(f"desc_{l}", defect.get("desc_en", "")) if defect else ""
    extra = str(notes or "").strip()

    if l == "uk":
        notes_part = f"\nДодаткові нотатки користувача: {extra}" if extra else ""
        return (
            f"🔍 **Діагностика дефекту друку: {defect_name}**\n"
            f"{defect_desc}{notes_part}\n\n"
            "Проаналізуй цей дефект з урахуванням моїх поточних пресетів OrcaSlicer, геометрії моделі, останнього G-code та прикріпленого фото (якщо є). Структуруй відповідь:\n"
            "1. **Фізичні та апаратні причини** (вологість філаменту, чистота столу, ремені, камера, механіка — щоб не шукати проблему лише в слайсері).\n"
            "2. **Причини в налаштуваннях слайсера** (ранжовані за ймовірністю, із посиланням на мої поточні значення).\n"
            "3. **Готові правки в блоці ```orca-settings** для застосування в 1 клік."
        )
    if l == "en":
        notes_part = f"\nAdditional user notes: {extra}" if extra else ""
        return (
            f"🔍 **Print Defect Troubleshooting: {defect_name}**\n"
            f"{defect_desc}{notes_part}\n\n"
            "Correlate this defect against my live OrcaSlicer presets, plate geometry, last sliced G-code, and attached photo (if provided). Structure your answer into:\n"
            "1. **Physical / Hardware / Material Checks** (wet filament, bed cleanliness, mechanical play, enclosure temp — so I don't chase ghosts).\n"
            "2. **Ranked Slicer Root Causes** (referencing my exact current preset values).\n"
            "3. **1-Click Slicer Fixes** inside an ```orca-settings JSON block."
        )
    notes_part = f"\nДополнительные заметки пользователя: {extra}" if extra else ""
    return (
        f"🔍 **Диагностика дефекта печати: {defect_name}**\n"
        f"{defect_desc}{notes_part}\n\n"
        "Проанализируй этот дефект с учётом моих текущих пресетов OrcaSlicer, геометрии модели, последнего G-code и прикреплённого фото (если есть). Структурируй ответ:\n"
        "1. **Физические и аппаратные проверки** (влажность филамента, чистота стола, ремни, закрытая камера, механика — чтобы не искать причину только в слайсере).\n"
        "2. **Причины в настройках слайсера** (ранжированные по вероятности, с опорой на мои текущие значения).\n"
        "3. **Готовые правки в блоке ```orca-settings** для применения в 1 клик."
    )


# ============================================================================
# 4. GUIDED ORCASLICER CALIBRATION CO-PILOT (EXACT FORMULAS)
# ============================================================================

CALIBRATION_STAGES: list[dict[str, Any]] = [
    {
        "id": "temp_tower",
        "order": 1,
        "ru": "1. Температурная башня (Temp Tower)",
        "uk": "1. Температурна вежа (Temp Tower)",
        "en": "1. Temperature Tower",
    },
    {
        "id": "max_volumetric_speed",
        "order": 2,
        "ru": "2. Макс. объёмная скорость (Max Volumetric Speed)",
        "uk": "2. Макс. об'ємна швидкість (Max Volumetric Speed)",
        "en": "2. Max Volumetric Speed",
    },
    {
        "id": "pressure_advance",
        "order": 3,
        "ru": "3. Pressure Advance (PA)",
        "uk": "3. Pressure Advance (PA)",
        "en": "3. Pressure Advance (PA)",
    },
    {
        "id": "flow_rate",
        "order": 4,
        "ru": "4. Калибровка потока (Flow Rate)",
        "uk": "4. Калібрування потоку (Flow Rate)",
        "en": "4. Flow Rate Calibration",
    },
    {
        "id": "retraction",
        "order": 5,
        "ru": "5. Тест ретракта (Retraction)",
        "uk": "5. Тест ретракту (Retraction)",
        "en": "5. Retraction Test",
    },
]


def _fval(d: dict[str, Any], *keys: str, default: float = 0.0) -> float:
    for k in keys:
        if k in d and d[k] not in (None, ""):
            try:
                return float(str(d[k]).strip().replace(",", "."))
            except ValueError:
                continue
    return default


def _fmt_num(val: float, decimals: int = 4) -> str:
    s = f"{val:.{decimals}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _cal_change(key: str, value: str, lang: str, category: str = "filament", slot: int = 1, reason: str = "") -> dict[str, Any]:
    info = FLAT_SETTING_INFO.get(key, {})
    cat = category or info.get("category", "filament")
    label = info.get(lang) or info.get("en") or key
    ch: dict[str, Any] = {
        "category": cat,
        "key": key,
        "label": label,
        "value": value,
        "reason": reason,
    }
    if cat == "filament":
        ch["slot"] = slot
    return ch


def calculate_calibration_values(
    stage: str,
    measurements: dict[str, Any] | None,
    slot: int = 1,
    lang: str = "ru",
) -> dict[str, Any]:
    """
    Compute exact OrcaSlicer calibration values and ready-to-apply setting changes.

    Supported stages:
      - `temp_tower`
      - `max_volumetric_speed`  -> `start + height * step`, with 15% safety margin
      - `pressure_advance`      -> `start + height * step` (or direct `best_value`)
      - `flow_rate`             -> `old_flow * (100 + modifier) / 100`
      - `retraction`            -> `start + height * step`
    """
    m = measurements if isinstance(measurements, dict) else {}
    l = norm_lang(m.get("lang") or lang)
    try:
        slot_num = max(1, int(m.get("slot") or slot or 1))
    except Exception:
        slot_num = 1

    st = str(stage or "").strip().lower()
    cal_trap_warn = tr(
        l,
        "⚠️ После калибровки откройте новый проект (File → New Project), чтобы скрытые калибровочные переопределения не остались в следующем проекте!",
        "⚠️ Після калібрування відкрийте новий проєкт (File → New Project), щоб приховані калібрувальні перевизначення не залишилися в наступному проєкті!",
        "⚠️ Calibration Mode Trap: start a Fresh Project (File → New Project) after calibrating so temporary calibration overrides don't leak into normal prints!",
    )

    if st == "temp_tower":
        best_temp = _fval(m, "best_temp", "temperature", "temp", default=0.0)
        if best_temp <= 0:
            start_t = _fval(m, "start_temp", "start", default=220.0)
            step_t = _fval(m, "step_temp", "step", default=-5.0)
            section = _fval(m, "section", "index", "height", default=0.0)
            best_temp = start_t + section * step_t
        nozzle_t = int(round(best_temp))
        init_offset = int(round(_fval(m, "initial_layer_offset", default=5.0)))
        init_t = nozzle_t + init_offset

        formula = f"nozzle_temperature = {nozzle_t}°C, initial_layer = {nozzle_t} + {init_offset} = {init_t}°C"
        summary = tr(
            l,
            f"Выбрана оптимальная температура сопла: {nozzle_t}°C (1-й слой: {init_t}°C) для Slot {slot_num}.",
            f"Обрано оптимальну температуру сопла: {nozzle_t}°C (1-й шар: {init_t}°C) для Slot {slot_num}.",
            f"Selected optimal nozzle temperature: {nozzle_t}°C (1st layer: {init_t}°C) for Slot {slot_num}.",
        )
        changes = [
            _cal_change("nozzle_temperature", str(nozzle_t), l, "filament", slot_num, "Temp Tower calibration"),
            _cal_change("nozzle_temperature_initial_layer", str(init_t), l, "filament", slot_num, "Temp Tower 1st layer"),
        ]
        return {
            "ok": True,
            "stage": st,
            "slot": slot_num,
            "formula": formula,
            "result_summary": summary,
            "values": {"nozzle_temperature": nozzle_t, "nozzle_temperature_initial_layer": init_t},
            "changes": changes,
            "warning": cal_trap_warn,
        }

    if st == "max_volumetric_speed":
        start = _fval(m, "start", "start_flow", "start_speed", default=5.0)
        height = _fval(m, "height", "height_mm", "measured_height", default=0.0)
        step = _fval(m, "step", "step_flow", default=0.5)
        margin_pct = _fval(m, "safety_margin_pct", "margin_pct", default=15.0)

        raw_max = start + height * step
        safe_mvs = round(raw_max * (1.0 - margin_pct / 100.0), 2)
        formula = (
            f"raw = {start:g} + ({height:g} × {step:g}) = {raw_max:.2f} mm³/s; "
            f"safe (-{margin_pct:g}%) = {safe_mvs:.2f} mm³/s"
        )
        summary = tr(
            l,
            f"Предел до дефектов: {raw_max:.2f} мм³/с → с запасом {margin_pct:g}%: {safe_mvs:.2f} мм³/с (Slot {slot_num}).",
            f"Межа до дефектів: {raw_max:.2f} мм³/с → із запасом {margin_pct:g}%: {safe_mvs:.2f} мм³/с (Slot {slot_num}).",
            f"Failure threshold: {raw_max:.2f} mm³/s → with {margin_pct:g}% safety margin: {safe_mvs:.2f} mm³/s (Slot {slot_num}).",
        )
        changes = [
            _cal_change(
                "filament_max_volumetric_speed",
                _fmt_num(safe_mvs, 2),
                l,
                "filament",
                slot_num,
                f"MVS calibration ({raw_max:.2f} mm³/s - {margin_pct:g}% margin)",
            )
        ]
        return {
            "ok": True,
            "stage": st,
            "slot": slot_num,
            "formula": formula,
            "result_summary": summary,
            "values": {"raw_max_volumetric_speed": round(raw_max, 2), "filament_max_volumetric_speed": safe_mvs},
            "changes": changes,
            "warning": cal_trap_warn,
        }

    if st == "pressure_advance":
        best_val = m.get("best_value")
        if best_val not in (None, ""):
            pa_val = round(float(str(best_val).strip().replace(",", ".")), 4)
            formula = f"PA = {pa_val:.4f} (direct line/pattern reading)"
        else:
            start = _fval(m, "start", "start_pa", default=0.0)
            height = _fval(m, "height", "height_mm", "measured_height", default=0.0)
            step = _fval(m, "step", "step_pa", default=0.002)
            pa_val = round(start + height * step, 4)
            formula = f"PA = {start:g} + ({height:g} × {step:g}) = {pa_val:.4f}"

        pa_str = _fmt_num(pa_val, 4)
        summary = tr(
            l,
            f"Рассчитанный Pressure Advance: {pa_str} для Slot {slot_num}.",
            f"Розрахований Pressure Advance: {pa_str} для Slot {slot_num}.",
            f"Calculated Pressure Advance: {pa_str} for Slot {slot_num}.",
        )
        pa_warn = cal_trap_warn + " " + tr(
            l,
            "Убедитесь, что PA не задан одновременно жёстко в прошивке Klipper/Marlin, если включаете его в слайсере.",
            "Переконайтесь, що PA не задано одночасно жорстко в прошивці Klipper/Marlin, якщо вмикаєте його у слайсері.",
            "Verify firmware PA (Klipper/Marlin) won't conflict with slicer-emitted PA commands.",
        )
        changes = [
            _cal_change("enable_pressure_advance", "1", l, "filament", slot_num, "Enable calibrated PA"),
            _cal_change("pressure_advance", pa_str, l, "filament", slot_num, "PA tower/pattern calibration"),
        ]
        return {
            "ok": True,
            "stage": st,
            "slot": slot_num,
            "formula": formula,
            "result_summary": summary,
            "values": {"pressure_advance": pa_val, "enable_pressure_advance": 1},
            "changes": changes,
            "warning": pa_warn,
        }

    if st == "flow_rate":
        old_flow = _fval(m, "old_flow", "current_flow", "flow", default=0.98)
        modifier = _fval(m, "modifier", "modifier_pct", "delta_pct", default=0.0)
        new_flow = round(old_flow * (100.0 + modifier) / 100.0, 4)
        flow_str = _fmt_num(new_flow, 4)
        formula = f"new_flow = {old_flow:g} × (100 + ({modifier:+g})) / 100 = {flow_str}"
        summary = tr(
            l,
            f"Новый коэффициент потока (Flow Ratio): {flow_str} (было {old_flow:g}, поправка {modifier:+g}%) для Slot {slot_num}.",
            f"Новий коефіцієнт потоку (Flow Ratio): {flow_str} (було {old_flow:g}, поправка {modifier:+g}%) для Slot {slot_num}.",
            f"New Flow Ratio: {flow_str} (from {old_flow:g}, modifier {modifier:+g}%) for Slot {slot_num}.",
        )
        changes = [
            _cal_change("filament_flow_ratio", flow_str, l, "filament", slot_num, f"Flow Rate calibration ({modifier:+g}%)"),
        ]
        return {
            "ok": True,
            "stage": st,
            "slot": slot_num,
            "formula": formula,
            "result_summary": summary,
            "values": {"old_flow": old_flow, "modifier": modifier, "filament_flow_ratio": new_flow},
            "changes": changes,
            "warning": cal_trap_warn,
        }

    if st == "retraction":
        start = _fval(m, "start", "start_retraction", default=0.0)
        height = _fval(m, "height", "height_mm", "measured_height", default=0.0)
        step = _fval(m, "step", "step_retraction", default=0.1)
        ret_len = round(start + height * step, 2)
        ret_str = _fmt_num(ret_len, 2)
        use_fil_override = bool(m.get("use_filament_override", False))

        formula = f"retraction = {start:g} + ({height:g} × {step:g}) = {ret_str} mm"
        summary = tr(
            l,
            f"Оптимальная длина ретракта: {ret_str} мм.",
            f"Оптимальна довжина ретракту: {ret_str} мм.",
            f"Optimal retraction length: {ret_str} mm.",
        )
        if use_fil_override:
            changes = [
                _cal_change("filament_retraction_length", ret_str, l, "filament", slot_num, "Retraction tower calibration (filament override)"),
            ]
        else:
            changes = [
                _cal_change("retraction_length", ret_str, l, "printer", slot_num, "Retraction tower calibration"),
            ]
        return {
            "ok": True,
            "stage": st,
            "slot": slot_num,
            "formula": formula,
            "result_summary": summary,
            "values": {"retraction_length": ret_len},
            "changes": changes,
            "warning": cal_trap_warn,
        }

    return {
        "ok": False,
        "stage": st,
        "slot": slot_num,
        "formula": "",
        "result_summary": tr(
            l,
            f"Неизвестный этап калибровки: '{stage}'.",
            f"Невідомий етап калібрування: '{stage}'.",
            f"Unknown calibration stage: '{stage}'.",
        ),
        "values": {},
        "changes": [],
        "warning": "",
    }


def build_calibration_prompt(
    stage: str,
    measurements: dict[str, Any] | None,
    slot: int = 1,
    lang: str = "ru",
) -> str:
    """Build an AI verification prompt for a completed calibration calculation."""
    l = norm_lang(lang)
    calc = calculate_calibration_values(stage, measurements, slot=slot, lang=l)
    m = measurements if isinstance(measurements, dict) else {}
    meas_str = ", ".join(f"{k}={v}" for k, v in m.items() if k not in ("lang",))

    if l == "uk":
        return (
            f"🧮 **Перевірка калібрування OrcaSlicer: `{calc['stage']}` (Slot {calc['slot']})**\n"
            f"- Введені заміри: {meas_str or '—'}\n"
            f"- Формула: `{calc['formula']}`\n"
            f"- Попередній результат: {calc['result_summary']}\n\n"
            "Перевір, чи реалістичні ці значення для мого поточного принтера і типу пластику в Slot "
            f"{calc['slot']}, чи немає конфлікту з прошивкою або іншими налаштуваннями, та підтверди/скоригуй правки у блоці ```orca-settings."
        )
    if l == "en":
        return (
            f"🧮 **OrcaSlicer Calibration Verification: `{calc['stage']}` (Slot {calc['slot']})**\n"
            f"- Measurements: {meas_str or '—'}\n"
            f"- Formula: `{calc['formula']}`\n"
            f"- Computed result: {calc['result_summary']}\n\n"
            f"Verify whether these calibrated values are realistic for my active printer and filament in Slot {calc['slot']}, "
            "check for firmware or dependent-parameter conflicts, and output the confirmed changes in an ```orca-settings block."
        )
    return (
        f"🧮 **Проверка калибровки OrcaSlicer: `{calc['stage']}` (Slot {calc['slot']})**\n"
        f"- Введённые замеры: {meas_str or '—'}\n"
        f"- Формула: `{calc['formula']}`\n"
        f"- Предварительный результат: {calc['result_summary']}\n\n"
        f"Проверь, реалистичны ли эти значения для моего текущего принтера и пластика в Slot {calc['slot']}, "
        "нет ли конфликтов с прошивкой или зависимыми настройками, и выведи итоговые правки в блоке ```orca-settings."
    )
