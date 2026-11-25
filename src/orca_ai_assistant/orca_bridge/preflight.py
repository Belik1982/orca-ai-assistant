from __future__ import annotations

from typing import Any

from ..core.constants import norm_lang, tr
from .enums import FLAT_SETTING_INFO
from .gcode_codec import lint_custom_gcode


def _to_float(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    s = str(val).strip()
    if not s:
        return default
    if s.endswith("%"):
        s = s[:-1].strip()
    try:
        return float(s)
    except ValueError:
        return default


def _to_int(val: Any, default: int = 0) -> int:
    return int(round(_to_float(val, float(default))))


def _parse_line_width_mm(val: Any, nozzle_mm: float) -> float:
    s = str(val or "").strip()
    if not s:
        return nozzle_mm * 1.05
    if s.endswith("%"):
        pct = _to_float(s[:-1], 0.0)
        return (nozzle_mm * pct / 100.0) if pct > 0 else (nozzle_mm * 1.05)
    mm = _to_float(s, 0.0)
    return mm if mm > 0 else (nozzle_mm * 1.05)


def _material_family(raw_type: str) -> str:
    t = str(raw_type or "").strip().upper()
    if not t:
        return ""
    if "PETG" in t or "PCTG" in t:
        return "PETG"
    if "PLA" in t:
        return "PLA"
    if "ASA" in t:
        return "ASA"
    if "ABS" in t:
        return "ABS"
    if "TPU" in t or "TPE" in t:
        return "TPU"
    if "PA" in t or "NYLON" in t:
        return "PA"
    if "PC" in t:
        return "PC"
    return t


def _fix_item(key: str, value: str, lang: str, category: str = "", slot: int | None = None) -> dict[str, Any]:
    info = FLAT_SETTING_INFO.get(key, {})
    cat = category or info.get("category", "process")
    label = info.get(lang) or info.get("en") or key
    item: dict[str, Any] = {
        "category": cat,
        "key": key,
        "label": label,
        "value": str(value),
    }
    if cat == "filament":
        item["slot"] = max(1, int(slot or 1))
    return item


def run_preflight_checks(
    plate: dict[str, Any] | None,
    presets: dict[str, Any] | None,
    last_slice: dict[str, Any] | None = None,
    lang: str = "ru",
) -> dict[str, Any]:
    """
    Deterministic zero-token FDM pre-flight engine (<50 ms).

    Evaluates 3D geometry, process/printer settings, ALL AMS filament slots,
    custom Start/End G-code safety, and last-slice waste metrics.
    """
    l = norm_lang(lang)
    plate_d = plate if isinstance(plate, dict) else {}
    presets_d = presets if isinstance(presets, dict) else {}
    fv = presets_d.get("flat_values") if isinstance(presets_d.get("flat_values"), dict) else {}
    slots = presets_d.get("filament_slots") if isinstance(presets_d.get("filament_slots"), list) else []
    objects = plate_d.get("objects") if isinstance(plate_d.get("objects"), list) else []
    custom_gcode = presets_d.get("custom_gcode") if isinstance(presets_d.get("custom_gcode"), dict) else {}

    # Synthesize slot 1 if filament_slots wasn't populated
    if not slots and fv:
        slots = [{
            "slot": 1,
            "name": (presets_d.get("filament_presets") or ["Slot 1"])[0],
            "type": fv.get("filament_type", ""),
            "nozzle_temp": fv.get("nozzle_temperature", ""),
            "bed_temp": (
                fv.get("textured_plate_temp")
                or fv.get("hot_plate_temp")
                or fv.get("eng_plate_temp")
                or fv.get("cool_plate_temp")
                or ""
            ),
            "max_volumetric_speed": fv.get("filament_max_volumetric_speed", ""),
            "fan_max": fv.get("fan_max_speed", ""),
            "close_fan_first_layers": fv.get("close_fan_the_first_x_layers", ""),
        }]

    checks: list[dict[str, Any]] = []
    penalty = 0

    def add_check(
        rule_id: str,
        level: str,
        category: str,
        title: str,
        detail: str,
        points: int,
        fix: list[dict[str, Any]] | None = None,
        ask_prompt: str = "",
    ) -> None:
        nonlocal penalty
        penalty += points
        checks.append({
            "id": rule_id,
            "level": level,
            "category": category,
            "title": title,
            "detail": detail,
            "fix": fix or [],
            "ask_prompt": ask_prompt or detail,
        })

    # --- 1. Non-manifold / mesh errors ---
    bad_meshes = [
        o for o in objects
        if not o.get("is_manifold", True) or _to_int(o.get("mesh_errors", 0)) > 0
    ]
    if bad_meshes:
        names = ", ".join(str(o.get("name") or "object") for o in bad_meshes[:3])
        err_total = sum(_to_int(o.get("mesh_errors", 0)) for o in bad_meshes)
        add_check(
            "non_manifold_mesh",
            "danger",
            "geometry",
            tr(l, "Ошибки 3D-сетки (Non-Manifold)", "Помилки 3D-сітки (Non-Manifold)", "Non-Manifold / Mesh Errors"),
            tr(
                l,
                f"Объекты ({names}) содержат незамкнутую геометрию или ошибки сетки ({err_total}). Выполните «Исправить модель» в OrcaSlicer перед печатью.",
                f"Об'єкти ({names}) містять незамкнену геометрію або помилки сітки ({err_total}). Виконайте «Виправити модель» в OrcaSlicer перед друком.",
                f"Objects ({names}) have non-manifold geometry or mesh errors ({err_total}). Repair the model in OrcaSlicer before slicing.",
            ),
            25,
            ask_prompt=tr(
                l,
                f"На столе обнаружены ошибки сетки (non-manifold) у {names}. Как безопасно исправить это и на что обратить внимание?",
                f"На столі виявлено помилки сітки (non-manifold) у {names}. Як безпечно виправити це та на що звернути увагу?",
                f"Non-manifold mesh errors were detected on {names}. How should I repair this safely and what slicing artifacts could occur?",
            ),
        )

    # --- 2. Small first-layer bed contact without Brim ---
    brim_type = str(fv.get("brim_type") or "no_brim").strip().lower()
    has_outer_brim = brim_type in ("outer_only", "outer_and_inner", "auto_brim", "brim_ears", "painted")
    small_base_objs = [
        o for o in objects
        if _to_float(o.get("bed_contact_mm2", 9999.0), 9999.0) < 120.0
        and _to_float(o.get("size_z", 0.0)) > 15.0
    ]
    if small_base_objs and not has_outer_brim:
        o0 = small_base_objs[0]
        add_check(
            "small_bed_contact_no_brim",
            "warn",
            "adhesion",
            tr(l, "Малая площадь контакта со столом без Brim", "Мала площа контакту зі столом без Brim", "Small Bed Contact Without Brim"),
            tr(
                l,
                f"«{o0.get('name')}»: контакт 1-го слоя всего {_to_float(o0.get('bed_contact_mm2')):.0f} мм² при высоте {_to_float(o0.get('size_z')):.1f} мм, а кайма выключена ({brim_type}). Риск отрыва детали!",
                f"«{o0.get('name')}»: контакт 1-го шару лише {_to_float(o0.get('bed_contact_mm2')):.0f} мм² при висоті {_to_float(o0.get('size_z')):.1f} мм, а кайма вимкнена ({brim_type}). Ризик відриву деталі!",
                f'"{o0.get("name")}": first-layer contact is only {_to_float(o0.get("bed_contact_mm2")):.0f} mm² at height {_to_float(o0.get("size_z")):.1f} mm with brim disabled ({brim_type}). High detachment risk!',
            ),
            12,
            fix=[
                _fix_item("brim_type", "outer_only", l),
                _fix_item("brim_width", "5", l),
            ],
        )

    # --- 3. Tall / narrow part stability (H/B >= 2.8 & Z >= 40) ---
    infill_pattern = str(fv.get("sparse_infill_pattern") or "").strip().lower()
    tall_objs = [
        o for o in objects
        if _to_float(o.get("height_to_base_ratio", 0.0)) >= 2.8
        and _to_float(o.get("size_z", 0.0)) >= 40.0
    ]
    tall_triggered = False
    if tall_objs and (not has_outer_brim or infill_pattern == "grid"):
        tall_triggered = True
        o0 = tall_objs[0]
        fixes = []
        if not has_outer_brim:
            fixes.append(_fix_item("brim_type", "outer_only", l))
            fixes.append(_fix_item("brim_width", "6", l))
        if infill_pattern == "grid":
            fixes.append(_fix_item("sparse_infill_pattern", "gyroid", l))
        add_check(
            "tall_narrow_stability",
            "warn",
            "adhesion",
            tr(l, "Высокая узкая деталь — риск опрокидывания", "Висока вузька деталь — ризик перекидання", "Tall/Narrow Part Stability Risk"),
            tr(
                l,
                f"«{o0.get('name')}»: отношение высоты к базе {_to_float(o0.get('height_to_base_ratio')):.1f}:1 (Z={_to_float(o0.get('size_z')):.1f} мм). Рекомендуется внешняя кайма (outer_only) и безударное заполнение gyroid.",
                f"«{o0.get('name')}»: відношення висоти до бази {_to_float(o0.get('height_to_base_ratio')):.1f}:1 (Z={_to_float(o0.get('size_z')):.1f} мм). Рекомендується зовнішня кайма (outer_only) та безударне заповнення gyroid.",
                f'"{o0.get("name")}": height-to-base ratio {_to_float(o0.get("height_to_base_ratio")):.1f}:1 (Z={_to_float(o0.get("size_z")):.1f} mm). Enable outer brim and non-crossing gyroid infill.',
            ),
            12,
            fix=fixes,
        )

    # --- 4. Grid infill nozzle-knock risk on tall/fast prints ---
    max_obj_z = max((_to_float(o.get("size_z", 0.0)) for o in objects), default=0.0)
    infill_speed = _to_float(fv.get("sparse_infill_speed", 0.0))
    def_accel = _to_float(fv.get("default_acceleration", 0.0))
    if infill_pattern == "grid" and not tall_triggered and (max_obj_z >= 25.0 or infill_speed >= 120.0 or def_accel >= 3000.0):
        add_check(
            "grid_infill_knock_risk",
            "warn",
            "quality",
            tr(l, "Заполнение Grid — риск задевания соплом", "Заповнення Grid — ризик зачеплення соплом", "Grid Infill Nozzle-Knock Risk"),
            tr(
                l,
                "Шаблон «grid» пересекает собственные линии на одном слое, что на высоких скоростях/деталях вызывает стук сопла и отрыв модели. Лучше использовать «gyroid» или «crosshatch».",
                "Шаблон «grid» перетинає власні лінії на одному шарі, що на високих швидкостях/деталях спричиняє стукіт сопла та відрив моделі. Краще обрати «gyroid» або «crosshatch».",
                "'grid' infill crosses its own extrusions on the same layer, risking nozzle strikes and part knock-off at speed. Switch to 'gyroid' or 'crosshatch'.",
            ),
            8,
            fix=[_fix_item("sparse_infill_pattern", "gyroid", l)],
        )

    # --- 5. Critical overhangs with supports disabled ---
    enable_support = str(fv.get("enable_support") or "0").strip()
    oh60 = _to_float(plate_d.get("total_overhang_60_mm2", 0.0))
    oh45 = _to_float(plate_d.get("total_overhang_45_mm2", 0.0))
    all_painted = bool(objects) and all(bool(o.get("support_painted", False)) for o in objects)
    if enable_support == "0" and not all_painted and (oh60 > 25.0 or oh45 > 100.0):
        is_crit = oh60 > 60.0
        add_check(
            "critical_overhangs_no_support",
            "danger" if is_crit else "warn",
            "supports",
            tr(l, "Критические нависания без поддержек", "Критичні нависання без підтримок", "Critical Overhangs Without Supports"),
            tr(
                l,
                f"Обнаружены нависания >60°: {oh60:.0f} мм² (>45°: {oh45:.0f} мм²), но поддержки выключены (enable_support = 0).",
                f"Виявлено нависання >60°: {oh60:.0f} мм² (>45°: {oh45:.0f} мм²), але підтримки вимкнено (enable_support = 0).",
                f"Detected overhangs >60°: {oh60:.0f} mm² (>45°: {oh45:.0f} mm²), but supports are disabled (enable_support = 0).",
            ),
            18 if is_crit else 12,
            fix=[
                _fix_item("enable_support", "1", l),
                _fix_item("support_type", "tree(auto)", l),
            ],
        )

    # --- 6. Multi-slot AMS material / thermal clash ---
    if len(slots) >= 2:
        slot_summaries = []
        for s in slots:
            fam = _material_family(str(s.get("type") or ""))
            nt = _to_float(s.get("nozzle_temp"), 0.0)
            bt = _to_float(s.get("bed_temp"), 0.0)
            if fam or nt > 0:
                slot_summaries.append((int(s.get("slot") or 1), fam or "?", nt, bt))
        fams = {x[1] for x in slot_summaries if x[1] != "?"}
        nozzle_vals = [x[2] for x in slot_summaries if x[2] > 0]
        bed_vals = [x[3] for x in slot_summaries if x[3] > 0]
        nozzle_diff = (max(nozzle_vals) - min(nozzle_vals)) if len(nozzle_vals) >= 2 else 0.0
        bed_diff = (max(bed_vals) - min(bed_vals)) if len(bed_vals) >= 2 else 0.0

        incompatible_pair = (
            ("PLA" in fams and bool(fams & {"ABS", "ASA", "PC", "PA"}))
            or ("PLA" in fams and "PETG" in fams and (nozzle_diff >= 25.0 or bed_diff >= 15.0))
        )
        if incompatible_pair or bed_diff >= 20.0 or nozzle_diff >= 40.0:
            desc = ", ".join(
                f"Slot {sn}: {fam} ({nt:g}/{bt:g}°C)" for sn, fam, nt, bt in slot_summaries
            )
            add_check(
                "ams_material_clash",
                "warn",
                "filament",
                tr(l, "Конфликт материалов/температур в слотах AMS", "Конфлікт матеріалів/температур у слотах AMS", "Multi-Slot AMS Material/Thermal Clash"),
                tr(
                    l,
                    f"Загружены несовместимые пластики или большой разброс температур: {desc}. Убедитесь, что это намеренная интерфейсная поддержка (PLA↔PETG), иначе возможна плохая адгезия слоёв или пробка.",
                    f"Завантажено несумісні пластики або великий розкид температур: {desc}. Переконайтесь, що це навмисна інтерфейсна підтримка (PLA↔PETG), інакше можлива погана адгезія шарів або корок.",
                    f"Loaded AMS slots have mixed materials or large temperature mismatch: {desc}. Verify whether this is intentional breakaway support interface (PLA/PETG) to avoid delamination or heat creep.",
                ),
                15,
            )

    # --- 7. Thermal & Build Plate Mismatches ---
    curr_bed = str(fv.get("curr_bed_type") or "").strip()
    is_cool_plate = "cool" in curr_bed.lower()

    for s in slots:
        slot_num = int(s.get("slot") or 1)
        fam = _material_family(str(s.get("type") or ""))
        nt = _to_float(s.get("nozzle_temp"), 0.0)
        bt = _to_float(s.get("bed_temp"), 0.0)
        slot_tag = f"Slot {slot_num}"

        if is_cool_plate and fam in ("PETG", "ABS", "ASA", "PC", "PA"):
            add_check(
                f"cool_plate_mismatch_s{slot_num}",
                "danger",
                "thermal",
                tr(l, f"{fam} на Cool Plate ({slot_tag})", f"{fam} на Cool Plate ({slot_tag})", f"{fam} on Cool Plate ({slot_tag})"),
                tr(
                    l,
                    f"{slot_tag} ({fam}) выбран при активном типе стола «{curr_bed}». Высокотемпературные пластики требуют Textured PEI / High Temp / Engineering Plate.",
                    f"{slot_tag} ({fam}) обрано при активному типі столу «{curr_bed}». Високотемпературні пластики потребують Textured PEI / High Temp / Engineering Plate.",
                    f'{slot_tag} ({fam}) is paired with "{curr_bed}". High-temp materials require Textured PEI, High Temp, or Engineering Plate.',
                ),
                20,
                fix=[_fix_item("curr_bed_type", "Textured PEI Plate", l)],
            )

        if fam == "PLA":
            if bt > 70.0:
                bed_key = "textured_plate_temp" if "textured" in curr_bed.lower() else "hot_plate_temp"
                add_check(
                    f"pla_bed_too_hot_s{slot_num}",
                    "warn",
                    "thermal",
                    tr(l, f"Слишком горячий стол для PLA ({bt:g}°C, {slot_tag})", f"Занадто гарячий стіл для PLA ({bt:g}°C, {slot_tag})", f"Bed Temp Too High for PLA ({bt:g}°C, {slot_tag})"),
                    tr(
                        l,
                        f"Для PLA ({slot_tag}) стол {bt:g}°C выше температуры стеклования (~60°C) — риск «слоновьей ноги» и коробления. Рекомендуется 55–65°C.",
                        f"Для PLA ({slot_tag}) стіл {bt:g}°C вище температури склування (~60°C) — ризик «слонячої ноги» та деформації. Рекомендується 55–65°C.",
                        f"PLA ({slot_tag}) bed temp {bt:g}°C exceeds PLA glass transition (~60°C), causing elephant's foot and poor overhang cooling. Recommended: 55–65°C.",
                    ),
                    10,
                    fix=[_fix_item(bed_key, "60", l, category="filament", slot=slot_num)],
                )
            if nt > 0 and (nt < 185.0 or nt > 245.0):
                add_check(
                    f"pla_nozzle_out_of_range_s{slot_num}",
                    "warn",
                    "thermal",
                    tr(l, f"Нестандартная температура сопла для PLA ({nt:g}°C, {slot_tag})", f"Нестандартна температура сопла для PLA ({nt:g}°C, {slot_tag})", f"PLA Nozzle Temp Out of Range ({nt:g}°C, {slot_tag})"),
                    tr(
                        l,
                        f"Температура сопла {nt:g}°C для PLA ({slot_tag}) выходит за рабочий диапазон 185–245°C.",
                        f"Температура сопла {nt:g}°C для PLA ({slot_tag}) виходить за робочий діапазон 185–245°C.",
                        f"Nozzle temperature {nt:g}°C for PLA ({slot_tag}) is outside the typical 185–245°C envelope.",
                    ),
                    10,
                    fix=[_fix_item("nozzle_temperature", "210", l, category="filament", slot=slot_num)],
                )
        elif fam == "PETG":
            if (nt > 0 and nt < 220.0) or (bt > 0 and bt < 65.0):
                fixes = []
                if nt > 0 and nt < 220.0:
                    fixes.append(_fix_item("nozzle_temperature", "240", l, category="filament", slot=slot_num))
                if bt > 0 and bt < 65.0:
                    bed_key = "textured_plate_temp" if "textured" in curr_bed.lower() else "hot_plate_temp"
                    fixes.append(_fix_item(bed_key, "75", l, category="filament", slot=slot_num))
                add_check(
                    f"petg_thermal_low_s{slot_num}",
                    "warn",
                    "thermal",
                    tr(l, f"Низкие температуры для PETG ({slot_tag})", f"Низькі температури для PETG ({slot_tag})", f"Low Temperatures for PETG ({slot_tag})"),
                    tr(
                        l,
                        f"PETG ({slot_tag}): сопло {nt:g}°C / стол {bt:g}°C. Для прочной межслойной адгезии обычно требуется сопло ≥220°C и стол ≥65–80°C.",
                        f"PETG ({slot_tag}): сопло {nt:g}°C / стіл {bt:g}°C. Для міцної міжшарової адгезії зазвичай потрібно сопло ≥220°C та стіл ≥65–80°C.",
                        f"PETG ({slot_tag}): nozzle {nt:g}°C / bed {bt:g}°C. Reliable layer bonding typically needs nozzle ≥220°C and bed ≥65–80°C.",
                    ),
                    10,
                    fix=fixes,
                )
        elif fam in ("ABS", "ASA"):
            if (nt > 0 and nt < 240.0) or (bt > 0 and bt < 90.0):
                fixes = []
                if nt > 0 and nt < 240.0:
                    fixes.append(_fix_item("nozzle_temperature", "260", l, category="filament", slot=slot_num))
                if bt > 0 and bt < 90.0:
                    bed_key = "textured_plate_temp" if "textured" in curr_bed.lower() else "hot_plate_temp"
                    fixes.append(_fix_item(bed_key, "100", l, category="filament", slot=slot_num))
                add_check(
                    f"abs_asa_thermal_low_s{slot_num}",
                    "warn",
                    "thermal",
                    tr(l, f"Низкие температуры для {fam} ({slot_tag})", f"Низькі температури для {fam} ({slot_tag})", f"Low Temperatures for {fam} ({slot_tag})"),
                    tr(
                        l,
                        f"{fam} ({slot_tag}): сопло {nt:g}°C / стол {bt:g}°C. Риск расслоения и сильного коробления (обычно сопло ≥240°C, стол ≥90–105°C).",
                        f"{fam} ({slot_tag}): сопло {nt:g}°C / стіл {bt:g}°C. Ризик розшарування та сильного жолоблення (зазвичай сопло ≥240°C, стіл ≥90–105°C).",
                        f"{fam} ({slot_tag}): nozzle {nt:g}°C / bed {bt:g}°C. High warping/delamination risk (typically nozzle ≥240°C, bed ≥90–105°C).",
                    ),
                    12,
                    fix=fixes,
                )

    # --- 8. Estimated peak volumetric flow > filament_max_volumetric_speed ---
    nozzle_mm = _to_float(fv.get("nozzle_diameter", 0.4), 0.4)
    if nozzle_mm <= 0:
        nozzle_mm = 0.4
    layer_h = _to_float(fv.get("layer_height", 0.0), 0.0)
    line_w = max(
        _parse_line_width_mm(fv.get("outer_wall_line_width"), nozzle_mm),
        _parse_line_width_mm(fv.get("inner_wall_line_width"), nozzle_mm),
    )
    peak_speed = max(
        _to_float(fv.get("outer_wall_speed", 0.0)),
        _to_float(fv.get("inner_wall_speed", 0.0)),
        _to_float(fv.get("sparse_infill_speed", 0.0)),
    )
    mvs_limit = _to_float(
        (slots[0].get("max_volumetric_speed") if slots else None) or fv.get("filament_max_volumetric_speed"),
        0.0,
    )
    if layer_h > 0 and peak_speed > 0 and mvs_limit > 0:
        est_flow = line_w * layer_h * peak_speed
        if est_flow > mvs_limit * 1.05:
            add_check(
                "volumetric_flow_exceeded",
                "warn",
                "speed",
                tr(l, "Пиковый расход превышает предел филамента", "Пікова витрата перевищує ліміт філаменту", "Peak Volumetric Flow Exceeds Filament Limit"),
                tr(
                    l,
                    f"Расчётный пиковый поток {est_flow:.1f} мм³/с ({line_w:.2f} мм × {layer_h:.2f} мм × {peak_speed:.0f} мм/с) превышает лимит филамента {mvs_limit:.1f} мм³/с — слайсер обрежет скорость или возможна недоэкструзия.",
                    f"Розрахунковий піковий потік {est_flow:.1f} мм³/с ({line_w:.2f} мм × {layer_h:.2f} мм × {peak_speed:.0f} мм/с) перевищує ліміт філаменту {mvs_limit:.1f} мм³/с — слайсер обмежить швидкість або можлива недоекструзія.",
                    f"Estimated peak flow {est_flow:.1f} mm³/s ({line_w:.2f} mm × {layer_h:.2f} mm × {peak_speed:.0f} mm/s) exceeds filament max volumetric speed {mvs_limit:.1f} mm³/s — speeds will be throttled or cause under-extrusion.",
                ),
                10,
            )

    # --- 9. Classic wall generator without detect_thin_wall ---
    wall_gen = str(fv.get("wall_generator") or "").strip().lower()
    detect_thin = str(fv.get("detect_thin_wall") or "0").strip()
    if wall_gen == "classic" and detect_thin == "0":
        add_check(
            "thin_walls_classic",
            "warn",
            "quality",
            tr(l, "Генератор Classic без обнаружения тонких стенок", "Генератор Classic без виявлення тонких стінок", "Classic Wall Generator Without Thin Wall Detection"),
            tr(
                l,
                "Активен wall_generator = classic и detect_thin_wall = 0: тонкие элементы и мелкий текст могут исчезнуть при нарезке. Рекомендуется Arachne.",
                "Активний wall_generator = classic та detect_thin_wall = 0: тонкі елементи та дрібний текст можуть зникнути під час нарізки. Рекомендується Arachne.",
                "wall_generator is 'classic' with detect_thin_wall disabled: thin walls and fine text may vanish when sliced. Switch to 'arachne'.",
            ),
            6,
            fix=[_fix_item("wall_generator", "arachne", l)],
        )

    # --- 10. Layer height > 75% of nozzle diameter ---
    if layer_h > 0 and nozzle_mm > 0 and layer_h > (0.75 * nozzle_mm + 1e-6):
        is_extreme = layer_h > (0.85 * nozzle_mm + 1e-6)
        safe_lh = round(nozzle_mm * 0.70, 2)
        add_check(
            "layer_height_vs_nozzle",
            "danger" if is_extreme else "warn",
            "quality",
            tr(l, f"Высота слоя {layer_h:g} мм > 75% сопла ({nozzle_mm:g} мм)", f"Висота шару {layer_h:g} мм > 75% сопла ({nozzle_mm:g} мм)", f"Layer Height {layer_h:g} mm > 75% of Nozzle ({nozzle_mm:g} mm)"),
            tr(
                l,
                f"При высоте слоя {layer_h:g} мм для сопла {nozzle_mm:g} мм нити плохо сплющиваются и деталь расслаивается. Безопасный предел ≤ {nozzle_mm * 0.75:.2f} мм.",
                f"При висоті шару {layer_h:g} мм для сопла {nozzle_mm:g} мм нитки погано сплющуються і деталь розшаровується. Безпечна межа ≤ {nozzle_mm * 0.75:.2f} мм.",
                f"Layer height {layer_h:g} mm exceeds 75% of {nozzle_mm:g} mm nozzle diameter, causing poor layer adhesion. Keep ≤ {nozzle_mm * 0.75:.2f} mm.",
            ),
            20 if is_extreme else 12,
            fix=[_fix_item("layer_height", f"{safe_lh:g}", l)],
        )

    # --- 11. High flush / prime-tower waste in last_slice ---
    if isinstance(last_slice, dict) and last_slice.get("ok"):
        total_g = _to_float(last_slice.get("total_filament_g", 0.0))
        flush_g = _to_float(last_slice.get("flush_g", 0.0))
        tower_g = _to_float(last_slice.get("tower_g", 0.0))
        waste_g = flush_g + tower_g
        if total_g > 0 and (waste_g / total_g) > 0.35:
            waste_pct = round(waste_g / total_g * 100.0, 1)
            add_check(
                "high_flush_purge_waste",
                "warn",
                "slice",
                tr(l, f"Высокие потери на продувку/башню ({waste_pct}%)", f"Високі втрати на продувку/вежу ({waste_pct}%)", f"High Purge/Tower Waste ({waste_pct}%)"),
                tr(
                    l,
                    f"В последнем G-code отходы (flush {flush_g:.1f} г + башня {tower_g:.1f} г = {waste_g:.1f} г) составляют {waste_pct}% от общих {total_g:.1f} г. Попробуйте снизить flush_multiplier или включить flush_into_infill.",
                    f"В останньому G-code відходи (flush {flush_g:.1f} г + вежа {tower_g:.1f} г = {waste_g:.1f} г) складають {waste_pct}% від загальних {total_g:.1f} г. Спробуйте знизити flush_multiplier або увімкнути flush_into_infill.",
                    f"Last slice purge/tower waste ({flush_g:.1f}g flush + {tower_g:.1f}g tower = {waste_g:.1f}g) is {waste_pct}% of {total_g:.1f}g total. Lower flush_multiplier or enable flush-into-infill.",
                ),
                10,
                fix=[_fix_item("flush_multiplier", "0.7", l)],
            )

    # --- 12. Cooling disabled too long / too weak for PLA ---
    for s in slots:
        slot_num = int(s.get("slot") or 1)
        fam = _material_family(str(s.get("type") or ""))
        if fam != "PLA":
            continue
        close_layers = _to_int(s.get("close_fan_first_layers"), 0)
        if close_layers >= 4:
            add_check(
                f"pla_cooling_disabled_too_long_s{slot_num}",
                "warn",
                "thermal",
                tr(l, f"Обдув PLA выключен на первых {close_layers} слоях (Slot {slot_num})", f"Обдув PLA вимкнено на перших {close_layers} шарах (Slot {slot_num})", f"PLA Fan Disabled for First {close_layers} Layers (Slot {slot_num})"),
                tr(
                    l,
                    f"Для PLA (Slot {slot_num}) отключение вентилятора на {close_layers} слоях вызывает заворачивание нижних фасок и «слоновью ногу». Обычно достаточно 1 слоя.",
                    f"Для PLA (Slot {slot_num}) вимкнення вентилятора на {close_layers} шарах спричиняє загортання нижніх фасок та «слонячу ногу». Зазвичай достатньо 1 шару.",
                    f"Disabling cooling for {close_layers} layers on PLA (Slot {slot_num}) causes lower chamfer curling and elephant's foot. 1 layer is usually optimal.",
                ),
                8,
                fix=[_fix_item("close_fan_the_first_x_layers", "1", l, category="filament", slot=slot_num)],
            )
        fan_max = _to_int(s.get("fan_max"), -1)
        if 0 <= fan_max < 60:
            add_check(
                f"pla_low_fan_s{slot_num}",
                "warn",
                "thermal",
                tr(l, f"Слабый макс. обдув для PLA ({fan_max}%, Slot {slot_num})", f"Слабкий макс. обдув для PLA ({fan_max}%, Slot {slot_num})", f"Low Max Fan Speed for PLA ({fan_max}%, Slot {slot_num})"),
                tr(
                    l,
                    f"Для PLA (Slot {slot_num}) fan_max_speed = {fan_max}% слишком мал для качественных мостов и нависаний. Рекомендуется 80–100%.",
                    f"Для PLA (Slot {slot_num}) fan_max_speed = {fan_max}% замалий для якісних мостів та нависань. Рекомендується 80–100%.",
                    f"PLA (Slot {slot_num}) max fan speed {fan_max}% is too low for clean bridges and overhangs. Recommended: 80–100%.",
                ),
                8,
                fix=[_fix_item("fan_max_speed", "100", l, category="filament", slot=slot_num)],
            )

    # --- 13. Weak shell / top surface pillowing risk ---
    wall_loops = _to_int(fv.get("wall_loops"), 0)
    top_layers = _to_int(fv.get("top_shell_layers"), 0)
    if wall_loops == 1:
        add_check(
            "single_wall_loop",
            "warn",
            "quality",
            tr(l, "Всего 1 периметр (wall_loops = 1)", "Лише 1 периметр (wall_loops = 1)", "Single Wall Loop (wall_loops = 1)"),
            tr(
                l,
                "Одна стенка делает деталь хрупкой и проявляет рисунок заполнения снаружи. Для большинства деталей рекомендуется ≥ 2–3 стенки.",
                "Одна стінка робить деталь крихкою та проявляє візерунок заповнення зовні. Для більшості деталей рекомендується ≥ 2–3 стінки.",
                "A single wall loop results in fragile parts and infill ghosting. Use at least 2–3 walls for standard parts.",
            ),
            6,
            fix=[_fix_item("wall_loops", "3", l)],
        )
    if 0 < top_layers <= 2 and layer_h > 0 and layer_h <= 0.2:
        add_check(
            "thin_top_shell",
            "warn",
            "quality",
            tr(l, f"Тонкая верхняя крышка ({top_layers} слоя при {layer_h:g} мм)", f"Тонка верхня кришка ({top_layers} шари при {layer_h:g} мм)", f"Thin Top Shell ({top_layers} layers at {layer_h:g} mm)"),
            tr(
                l,
                f"Всего {top_layers} верхних слоя при высоте {layer_h:g} мм ({top_layers * layer_h:.2f} мм) часто дают «подушки» (pillowing) и просветы над заполнением. Рекомендуется ≥ 4 слоя.",
                f"Лише {top_layers} верхніх шари при висоті {layer_h:g} мм ({top_layers * layer_h:.2f} мм) часто дають «подушки» (pillowing) та просвіти над заповненням. Рекомендується ≥ 4 шари.",
                f"Only {top_layers} top layers at {layer_h:g} mm ({top_layers * layer_h:.2f} mm) often causes pillowing or gaps over infill. Use ≥ 4 layers.",
            ),
            6,
            fix=[_fix_item("top_shell_layers", "4", l)],
        )

    # --- 14. Custom Start/End G-code safety audit ---
    for gkey in ("machine_start_gcode", "machine_end_gcode"):
        gtext = custom_gcode.get(gkey)
        if not gtext:
            continue
        lint_findings = lint_custom_gcode(gkey, str(gtext), lang=l)
        for idx, lf in enumerate(lint_findings):
            lvl = "danger" if lf.get("level") == "danger" else "warn"
            add_check(
                f"gcode_{gkey}_{idx}",
                lvl,
                "gcode",
                tr(
                    l,
                    f"Предупреждение безопасности G-code ({gkey})",
                    f"Попередження безпеки G-code ({gkey})",
                    f"Custom G-code Safety Issue ({gkey})",
                ),
                str(lf.get("text") or ""),
                18 if lvl == "danger" else 8,
            )

    # Summary scoring
    score = max(0, min(100, 100 - penalty))
    danger_cnt = sum(1 for c in checks if c["level"] == "danger")
    warn_cnt = sum(1 for c in checks if c["level"] == "warn")

    if not checks:
        checks.append({
            "id": "all_clear",
            "level": "ok",
            "category": "geometry",
            "title": tr(l, "Критических проблем не обнаружено", "Критичних проблем не виявлено", "No Pre-Flight Issues Detected"),
            "detail": tr(
                l,
                "Геометрия, температуры, объёмный расход и пользовательский G-code в пределах нормы.",
                "Геометрія, температури, об'ємна витрата та користувацький G-code в межах норми.",
                "Geometry, temperatures, volumetric flow, and custom G-code all look within safe envelopes.",
            ),
            "fix": [],
            "ask_prompt": "",
        })

    ok_cnt = sum(1 for c in checks if c["level"] == "ok")
    status = "danger" if danger_cnt > 0 else ("warn" if warn_cnt > 0 else "ok")

    return {
        "score": score,
        "status": status,
        "counts": {
            "danger": danger_cnt,
            "warn": warn_cnt,
            "ok": ok_cnt,
        },
        "checks": checks,
    }
