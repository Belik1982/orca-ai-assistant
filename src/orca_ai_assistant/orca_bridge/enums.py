from __future__ import annotations

import re
from typing import Any

# ============================================================================
# ORCASLICER 2.5.2 VERIFIED SETTINGS CATALOG, CUSTOM G-CODE KEYS & ENUM RULES
# ============================================================================

# Multilingual OrcaSlicer settings catalog:
# (group_ru, group_uk, group_en) -> [(key, label_ru, label_uk, label_en, category), ...]
SLICER_SETTINGS_I18N: list[tuple[tuple[str, str, str], list[tuple[str, str, str, str, str]]]] = [
    (
        ("Слои и периметры (process)", "Шари та периметри (process)", "Layers & Perimeters (process)"),
        [
            ("layer_height", "Высота слоя (мм)", "Висота шару (мм)", "Layer height (mm)", "process"),
            ("initial_layer_print_height", "Высота первого слоя (мм)", "Висота першого шару (мм)", "First layer height (mm)", "process"),
            ("wall_loops", "Количество стенок (периметров)", "Кількість стінок (периметрів)", "Wall loops (perimeters)", "process"),
            ("top_shell_layers", "Верхние сплошные слои", "Верхні суцільні шари", "Top shell layers", "process"),
            ("bottom_shell_layers", "Нижние сплошные слои", "Нижні суцільні шари", "Bottom shell layers", "process"),
            ("top_shell_thickness", "Толщина крышки (мм)", "Товщина кришки (мм)", "Top shell thickness (mm)", "process"),
            ("bottom_shell_thickness", "Толщина дна (мм)", "Товщина дна (мм)", "Bottom shell thickness (mm)", "process"),
            ("wall_generator", "Генератор стенок (classic/arachne)", "Генератор стінок (classic/arachne)", "Wall generator (classic/arachne)", "process"),
            ("wall_sequence", "Порядок печати стенок", "Порядок друку стінок", "Wall printing order", "process"),
            ("inner_wall_line_width", "Ширина линии внутренней стенки", "Ширина лінії внутрішньої стінки", "Inner wall line width", "process"),
            ("outer_wall_line_width", "Ширина линии внешней стенки", "Ширина лінії зовнішньої стінки", "Outer wall line width", "process"),
            ("initial_layer_line_width", "Ширина линии первого слоя", "Ширина лінії першого шару", "First layer line width", "process"),
            ("seam_position", "Позиция шва (aligned/aligned_back/nearest/back/random)", "Позиція шва (aligned/aligned_back/nearest/back/random)", "Seam position (aligned/aligned_back/nearest/back/random)", "process"),
            ("seam_slope_type", "Шарф-шов (Scarf joint: none/external/all)", "Шарф-шов (Scarf joint: none/external/all)", "Scarf joint seam (none/external/all)", "process"),
            ("detect_thin_wall", "Обнаружение тонких стенок", "Виявлення тонких стінок", "Detect thin walls", "process"),
            ("only_one_wall_top", "Одна стенка на верхних поверхностях", "Одна стінка на верхніх поверхнях", "Only one wall on top surfaces", "process"),
            ("ironing_type", "Глажка поверхностей (no ironing/top/topmost/solid)", "Прасування поверхонь (no ironing/top/topmost/solid)", "Ironing type (no ironing/top/topmost/solid)", "process"),
            ("fuzzy_skin", "Пушистая кожа (disabled_fuzzy/none/external/hole/all/allwalls)", "Пухнаста шкіра (disabled_fuzzy/none/external/hole/all/allwalls)", "Fuzzy skin (disabled_fuzzy/none/external/hole/all/allwalls)", "process"),
            ("print_sequence", "Последовательность печати (by layer/by object)", "Послідовність друку (by layer/by object)", "Print sequence (by layer/by object)", "process"),
        ],
    ),
    (
        ("Заполнение и прочность (process)", "Заповнення та міцність (process)", "Infill & Strength (process)"),
        [
            ("sparse_infill_density", "Плотность заполнения (%)", "Щільність заповнення (%)", "Sparse infill density (%)", "process"),
            ("sparse_infill_pattern", "Шаблон заполнения", "Шаблон заповнення", "Sparse infill pattern", "process"),
            ("top_surface_pattern", "Шаблон верхней поверхности", "Шаблон верхньої поверхні", "Top surface pattern", "process"),
            ("bottom_surface_pattern", "Шаблон нижней поверхности", "Шаблон нижньої поверхні", "Bottom surface pattern", "process"),
            ("internal_solid_infill_pattern", "Шаблон внутреннего сплошного заполнения", "Шаблон внутрішнього суцільного заповнення", "Internal solid infill pattern", "process"),
            ("infill_wall_overlap", "Перекрытие заполнения и стенок (%)", "Перекриття заповнення та стінок (%)", "Infill/wall overlap (%)", "process"),
            ("infill_combination", "Комбинирование заполнения", "Комбінування заповнення", "Infill combination", "process"),
            ("minimum_sparse_infill_area", "Мин. площадь разреженного заполнения", "Мін. площа розрідженого заповнення", "Minimum sparse infill area", "process"),
        ],
    ),
    (
        ("Скорости и ускорения (process)", "Швидкості та прискорення (process)", "Speeds & Accelerations (process)"),
        [
            ("initial_layer_speed", "Скорость первого слоя (мм/с)", "Швидкість першого шару (мм/с)", "First layer speed (mm/s)", "process"),
            ("initial_layer_infill_speed", "Скорость заполнения 1-го слоя (мм/с)", "Швидкість заповнення 1-го шару (мм/с)", "First layer infill speed (mm/s)", "process"),
            ("outer_wall_speed", "Скорость внешней стенки (мм/с)", "Швидкість зовнішньої стінки (мм/с)", "Outer wall speed (mm/s)", "process"),
            ("inner_wall_speed", "Скорость внутренней стенки (мм/с)", "Швидкість внутрішньої стінки (мм/с)", "Inner wall speed (mm/s)", "process"),
            ("sparse_infill_speed", "Скорость заполнения (мм/с)", "Швидкість заповнення (мм/с)", "Sparse infill speed (mm/s)", "process"),
            ("internal_solid_infill_speed", "Скорость сплошного заполнения (мм/с)", "Швидкість суцільного заповнення (мм/с)", "Internal solid infill speed (mm/s)", "process"),
            ("top_surface_speed", "Скорость верхней поверхности (мм/с)", "Швидкість верхньої поверхні (мм/с)", "Top surface speed (mm/s)", "process"),
            ("bridge_speed", "Скорость мостов (мм/с)", "Швидкість мостів (мм/с)", "Bridge speed (mm/s)", "process"),
            ("gap_infill_speed", "Скорость заполнения зазоров (мм/с)", "Швидкість заповнення проміжків (мм/с)", "Gap infill speed (mm/s)", "process"),
            ("support_speed", "Скорость поддержек (мм/с)", "Швидкість підтримок (мм/с)", "Support speed (mm/s)", "process"),
            ("travel_speed", "Скорость холостых перемещений (мм/с)", "Швидкість холостих переміщень (мм/с)", "Travel speed (mm/s)", "process"),
            ("enable_overhang_speed", "Замедление на нависаниях (0/1)", "Уповільнення на нависаннях (0/1)", "Slow down for overhangs (0/1)", "process"),
            ("default_acceleration", "Стандартное ускорение (мм/с²)", "Стандартне прискорення (мм/с²)", "Default acceleration (mm/s²)", "process"),
            ("outer_wall_acceleration", "Ускорение внешней стенки (мм/с²)", "Прискорення зовнішньої стінки (мм/с²)", "Outer wall acceleration (mm/s²)", "process"),
            ("initial_layer_acceleration", "Ускорение первого слоя (мм/с²)", "Прискорення першого шару (мм/с²)", "First layer acceleration (mm/s²)", "process"),
        ],
    ),
    (
        ("Поддержки и адгезия к столу (process)", "Підтримки та адгезія до столу (process)", "Supports & Bed Adhesion (process)"),
        [
            ("enable_support", "Поддержки включены (0/1)", "Підтримки увімкнено (0/1)", "Enable support (0/1)", "process"),
            ("support_type", "Тип поддержек (normal(auto)/tree(auto)/normal(manual)/tree(manual))", "Тип підтримок (normal(auto)/tree(auto)/normal(manual)/tree(manual))", "Support type (normal(auto)/tree(auto)/normal(manual)/tree(manual))", "process"),
            ("support_style", "Стиль поддержек", "Стиль підтримок", "Support style", "process"),
            ("support_threshold_angle", "Пороговый угол поддержек (°)", "Пороговий кут підтримок (°)", "Support threshold angle (°)", "process"),
            ("support_on_build_plate_only", "Поддержки только от стола (0/1)", "Підтримки тільки від столу (0/1)", "Support on build plate only (0/1)", "process"),
            ("support_top_z_distance", "Верхний Z-зазор поддержек (мм)", "Верхній Z-зазор підтримок (мм)", "Support top Z distance (mm)", "process"),
            ("support_bottom_z_distance", "Нижний Z-зазор поддержек (мм)", "Нижній Z-зазор підтримок (мм)", "Support bottom Z distance (mm)", "process"),
            ("support_object_xy_distance", "XY-зазор поддержки до модели (мм)", "XY-зазор підтримки до моделі (мм)", "Support object XY distance (mm)", "process"),
            ("support_interface_top_layers", "Верхние интерфейсные слои поддержек", "Верхні інтерфейсні шари підтримок", "Support interface top layers", "process"),
            ("brim_type", "Тип каймы (no_brim/outer_only/inner_only/outer_and_inner/auto_brim/brim_ears)", "Тип кайми (no_brim/outer_only/inner_only/outer_and_inner/auto_brim/brim_ears)", "Brim type (no_brim/outer_only/inner_only/outer_and_inner/auto_brim/brim_ears)", "process"),
            ("brim_width", "Ширина каймы (мм)", "Ширина кайми (мм)", "Brim width (mm)", "process"),
            ("brim_object_gap", "Зазор каймы до детали (мм)", "Зазор кайми до деталі (мм)", "Brim object gap (mm)", "process"),
            ("skirt_loops", "Петли юбки (Skirt)", "Петлі спідниці (Skirt)", "Skirt loops", "process"),
            ("raft_layers", "Слои рафта (Raft)", "Шари рафта (Raft)", "Raft layers", "process"),
            ("enable_prime_tower", "Башня очистки (Prime tower, 0/1)", "Вежа очищення (Prime tower, 0/1)", "Enable prime tower (0/1)", "process"),
            ("flush_multiplier", "Множитель продувки (Flush multiplier)", "Множник продувки (Flush multiplier)", "Flush multiplier", "process"),
        ],
    ),
    (
        ("Филамент, температуры и обдув (filament)", "Філамент, температури та обдув (filament)", "Filament, Temperatures & Cooling (filament)"),
        [
            ("filament_type", "Тип пластика", "Тип пластику", "Filament type", "filament"),
            ("filament_vendor", "Производитель филамента", "Виробник філаменту", "Filament vendor", "filament"),
            ("nozzle_temperature", "Температура сопла (°C)", "Температура сопла (°C)", "Nozzle temperature (°C)", "filament"),
            ("nozzle_temperature_initial_layer", "Температура сопла 1-й слой (°C)", "Температура сопла 1-й шар (°C)", "Nozzle temp first layer (°C)", "filament"),
            ("hot_plate_temp", "Температура стола (°C)", "Температура столу (°C)", "Hot plate temp (°C)", "filament"),
            ("hot_plate_temp_initial_layer", "Температура стола 1-й слой (°C)", "Температура столу 1-й шар (°C)", "Hot plate temp first layer (°C)", "filament"),
            ("textured_plate_temp", "Температура текстур. стола (°C)", "Температура текстур. столу (°C)", "Textured plate temp (°C)", "filament"),
            ("textured_plate_temp_initial_layer", "Темп. текстур. стола 1-й слой (°C)", "Темп. текстур. столу 1-й шар (°C)", "Textured plate temp 1st layer (°C)", "filament"),
            ("cool_plate_temp", "Температура холодного стола (°C)", "Температура холодного столу (°C)", "Cool plate temp (°C)", "filament"),
            ("eng_plate_temp", "Температура инж. стола (°C)", "Температура інж. столу (°C)", "Engineering plate temp (°C)", "filament"),
            ("filament_flow_ratio", "Коэффициент потока (Flow Ratio)", "Коефіцієнт потоку (Flow Ratio)", "Filament flow ratio", "filament"),
            ("filament_max_volumetric_speed", "Макс. объёмная скорость (мм³/с)", "Макс. об'ємна швидкість (мм³/с)", "Max volumetric speed (mm³/s)", "filament"),
            ("enable_pressure_advance", "Pressure Advance включён (0/1)", "Pressure Advance увімкнено (0/1)", "Enable Pressure Advance (0/1)", "filament"),
            ("pressure_advance", "Значение Pressure Advance", "Значення Pressure Advance", "Pressure Advance value", "filament"),
            ("fan_max_speed", "Макс. скорость обдува (%)", "Макс. швидкість обдуву (%)", "Max fan speed (%)", "filament"),
            ("fan_min_speed", "Мин. скорость обдува (%)", "Мін. швидкість обдуву (%)", "Min fan speed (%)", "filament"),
            ("overhang_fan_speed", "Обдув нависаний и мостов (%)", "Обдув нависань та мостів (%)", "Overhang fan speed (%)", "filament"),
            ("close_fan_the_first_x_layers", "Отключить обдув на первых N слоях", "Вимкнути обдув на перших N шарах", "Disable fan for first N layers", "filament"),
            ("fan_cooling_layer_time", "Порог времени слоя для макс. обдува (с)", "Поріг часу шару для макс. обдуву (с)", "Fan cooling layer time threshold (s)", "filament"),
            ("slow_down_for_layer_cooling", "Замедление для охлаждения слоя (0/1)", "Уповільнення для охолодження шару (0/1)", "Slow down for layer cooling (0/1)", "filament"),
            ("slow_down_layer_time", "Мин. время печати слоя (с)", "Мін. час друку шару (с)", "Slow down layer time (s)", "filament"),
            ("slow_down_min_speed", "Мин. скорость при замедлении (мм/с)", "Мін. швидкість при уповільненні (мм/с)", "Min print speed when slowing down (mm/s)", "filament"),
        ],
    ),
    (
        ("Принтер и ретракт (printer)", "Принтер та ретракт (printer)", "Printer & Retraction (printer)"),
        [
            ("printer_model", "Модель принтера", "Модель принтера", "Printer model", "printer"),
            ("gcode_flavor", "Диалект G-code (marlin/marlin2/klipper/reprapfirmware/repetier)", "Діалект G-code (marlin/marlin2/klipper/reprapfirmware/repetier)", "G-code flavor (marlin/marlin2/klipper/reprapfirmware/repetier)", "printer"),
            ("nozzle_diameter", "Диаметр сопла (мм)", "Діаметр сопла (мм)", "Nozzle diameter (mm)", "printer"),
            ("printable_height", "Высота области печати (мм)", "Висота області друку (мм)", "Printable height (mm)", "printer"),
            ("curr_bed_type", "Текущий тип стола", "Поточний тип столу", "Current bed type", "printer"),
            ("retraction_length", "Длина ретракта (мм)", "Довжина ретракту (мм)", "Retraction length (mm)", "printer"),
            ("retraction_speed", "Скорость ретракта (мм/с)", "Швидкість ретракту (мм/с)", "Retraction speed (mm/s)", "printer"),
            ("deretraction_speed", "Скорость возврата ретракта (мм/с)", "Швидкість повернення ретракту (мм/с)", "Deretraction speed (mm/s)", "printer"),
            ("z_hop", "Подъём Z при ретракте (Z-hop, мм)", "Підйом Z при ретракті (Z-hop, мм)", "Z-hop when retracting (mm)", "printer"),
            ("z_hop_types", "Тип Z-hop (Auto Lift/Normal Lift/Slope Lift/Spiral Lift)", "Тип Z-hop (Auto Lift/Normal Lift/Slope Lift/Spiral Lift)", "Z-hop type (Auto Lift/Normal Lift/Slope Lift/Spiral Lift)", "printer"),
            ("retract_when_changing_layer", "Ретракт при смене слоя", "Ретракт при зміні шару", "Retract when changing layer", "printer"),
            ("wipe", "Протирка сопла (Wipe)", "Витирання сопла (Wipe)", "Wipe nozzle", "printer"),
        ],
    ),
]

FLAT_SETTING_INFO: dict[str, dict[str, str]] = {}
for (_grp_ru, _grp_uk, _grp_en), _items in SLICER_SETTINGS_I18N:
    for _key, _l_ru, _l_uk, _l_en, _cat in _items:
        FLAT_SETTING_INFO[_key] = {
            "ru": _l_ru,
            "uk": _l_uk,
            "en": _l_en,
            "category": _cat,
        }


# Verified OrcaSlicer 2.5.2 custom G-code keys (from PrintConfigDef in OrcaSlicer.dll)
# is_vector=False -> coString (escape_string_cstyle / unescape_string_cstyle)
# is_vector=True  -> coStrings (escape_strings_cstyle / unescape_strings_cstyle; MUST quote on write!)
CUSTOM_GCODE_KEYS: dict[str, dict[str, Any]] = {
    # Printer (coString)
    "machine_start_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "Стартовый G-code принтера",
        "uk": "Стартовий G-code принтера",
        "en": "Machine start G-code",
    },
    "machine_end_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "Финишный G-code принтера",
        "uk": "Фінішний G-code принтера",
        "en": "Machine end G-code",
    },
    "before_layer_change_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code перед сменой слоя",
        "uk": "G-code перед зміною шару",
        "en": "Before layer change G-code",
    },
    "layer_change_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code смены слоя",
        "uk": "G-code зміни шару",
        "en": "Layer change G-code",
    },
    "change_filament_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code смены филамента",
        "uk": "G-code зміни філаменту",
        "en": "Change filament G-code",
    },
    "machine_pause_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code паузы принтера",
        "uk": "G-code паузи принтера",
        "en": "Machine pause G-code",
    },
    "time_lapse_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code таймлапса",
        "uk": "G-code таймлапсу",
        "en": "Time-lapse G-code",
    },
    "printing_by_object_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code между объектами (пообъектная печать)",
        "uk": "G-code між об'єктами (пооб'єктний друк)",
        "en": "Printing by object G-code",
    },
    "template_custom_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "Шаблонный пользовательский G-code",
        "uk": "Шаблонний користувацький G-code",
        "en": "Template custom G-code",
    },
    "change_extrusion_role_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code смены роли экструзии (принтер)",
        "uk": "G-code зміни ролі екструзії (принтер)",
        "en": "Change extrusion role G-code (printer)",
    },
    "file_start_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code начала файла",
        "uk": "G-code початку файлу",
        "en": "File start G-code",
    },
    "wrapping_detection_gcode": {
        "category": "printer",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code детекции наматывания",
        "uk": "G-code детекції намотування",
        "en": "Wrapping detection G-code",
    },
    # Filament (coStrings — per-slot vector!)
    "filament_start_gcode": {
        "category": "filament",
        "is_vector": True,
        "option_type": "coStrings",
        "ru": "Стартовый G-code филамента",
        "uk": "Стартовий G-code філаменту",
        "en": "Filament start G-code",
    },
    "filament_end_gcode": {
        "category": "filament",
        "is_vector": True,
        "option_type": "coStrings",
        "ru": "Финишный G-code филамента",
        "uk": "Фінішний G-code філаменту",
        "en": "Filament end G-code",
    },
    "filament_change_extrusion_role_gcode": {
        "category": "filament",
        "is_vector": True,
        "option_type": "coStrings",
        "ru": "G-code смены роли экструзии (филамент)",
        "uk": "G-code зміни ролі екструзії (філамент)",
        "en": "Filament change extrusion role G-code",
    },
    # Process (coString)
    "process_change_extrusion_role_gcode": {
        "category": "process",
        "is_vector": False,
        "option_type": "coString",
        "ru": "G-code смены роли экструзии (процесс)",
        "uk": "G-code зміни ролі екструзії (процес)",
        "en": "Process change extrusion role G-code",
    },
}


# Exact verified enum values from OrcaSlicer.dll v2.5.2 (PrintConfigDef::init_fff_params)
_SURFACE_PATTERNS = [
    "monotonic",
    "monotonicline",
    "rectilinear",
    "alignedrectilinear",
    "concentric",
    "spiralinset",
    "hilbertcurve",
    "archimedeanchords",
    "octagramspiral",
]

ENUM_VALID_VALUES: dict[str, list[str]] = {
    "sparse_infill_pattern": [
        "rectilinear",
        "alignedrectilinear",
        "zigzag",
        "crosszag",
        "lockedzag",
        "line",
        "grid",
        "triangles",
        "tri-hexagon",
        "cubic",
        "adaptivecubic",
        "quartercubic",
        "supportcubic",
        "lightning",
        "honeycomb",
        "3dhoneycomb",
        "lateral-honeycomb",
        "lateral-lattice",
        "crosshatch",
        "tpmsd",
        "tpmsfk",
        "gyroid",
        "concentric",
        "hilbertcurve",
        "archimedeanchords",
        "octagramspiral",
    ],
    "top_surface_pattern": list(_SURFACE_PATTERNS),
    "bottom_surface_pattern": list(_SURFACE_PATTERNS),
    "internal_solid_infill_pattern": list(_SURFACE_PATTERNS),
    "support_type": [
        "normal(auto)",
        "tree(auto)",
        "normal(manual)",
        "tree(manual)",
    ],
    "support_style": [
        "default",
        "grid",
        "snug",
        "organic",
        "tree_slim",
        "tree_strong",
        "tree_hybrid",
    ],
    "support_base_pattern": [
        "default",
        "rectilinear",
        "rectilinear-grid",
        "honeycomb",
        "lightning",
        "hollow",
    ],
    "support_interface_pattern": [
        "auto",
        "rectilinear",
        "concentric",
        "spiralinset",
        "rectilinear_interlaced",
        "grid",
    ],
    "brim_type": [
        "auto_brim",
        "brim_ears",
        "painted",
        "outer_only",
        "inner_only",
        "outer_and_inner",
        "no_brim",
        "leading_edge_only",
    ],
    "seam_position": [
        "nearest",
        "aligned",
        "aligned_back",
        "back",
        "random",
    ],
    "wall_generator": [
        "classic",
        "arachne",
    ],
    "wall_sequence": [
        "inner wall/outer wall",
        "outer wall/inner wall",
        "inner-outer-inner wall",
    ],
    "z_hop_types": [
        "Auto Lift",
        "Normal Lift",
        "Slope Lift",
        "Spiral Lift",
    ],
    "ironing_type": [
        "no ironing",
        "top",
        "topmost",
        "solid",
    ],
    "ironing_pattern": [
        "rectilinear",
        "concentric",
    ],
    "fuzzy_skin": [
        "none",
        "external",
        "hole",
        "all",
        "allwalls",
        "disabled_fuzzy",
    ],
    "fuzzy_skin_noise_type": [
        "classic",
        "perlin",
        "billow",
        "ridgedmulti",
        "voronoi",
        "ripple",
    ],
    "seam_slope_type": [
        "none",
        "external",
        "all",
    ],
    "slicing_mode": [
        "regular",
        "even_odd",
        "close_holes",
    ],
    "draft_shield": [
        "disabled",
        "enabled",
    ],
    "print_sequence": [
        "by layer",
        "by object",
    ],
    "curr_bed_type": [
        "Cool Plate",
        "Engineering Plate",
        "High Temp Plate",
        "Textured PEI Plate",
        "Textured Cool Plate",
        "Supertack Plate",
    ],
    "gcode_flavor": [
        "marlin",
        "klipper",
        "reprapfirmware",
        "repetier",
        "marlin2",
    ],
    "timelapse_type": [
        "0",
        "1",
    ],
}

_SURFACE_PATTERN_ALIASES: dict[str, str] = {
    "monotonic_line": "monotonicline",
    "monotonic-line": "monotonicline",
    "monotonic line": "monotonicline",
    "aligned_rectilinear": "alignedrectilinear",
    "aligned-rectilinear": "alignedrectilinear",
    "aligned rectilinear": "alignedrectilinear",
    "spiral_inset": "spiralinset",
    "spiral-inset": "spiralinset",
    "spiral inset": "spiralinset",
    "hilbert_curve": "hilbertcurve",
    "hilbert-curve": "hilbertcurve",
    "hilbert curve": "hilbertcurve",
    "archimedean_chords": "archimedeanchords",
    "archimedean-chords": "archimedeanchords",
    "archimedean chords": "archimedeanchords",
    "octagram_spiral": "octagramspiral",
    "octagram-spiral": "octagramspiral",
    "octagram spiral": "octagramspiral",
}

ENUM_ALIASES: dict[str, dict[str, str]] = {
    "sparse_infill_pattern": {
        "cross_hatch": "crosshatch",
        "cross-hatch": "crosshatch",
        "cross hatch": "crosshatch",
        "3d_honeycomb": "3dhoneycomb",
        "3d-honeycomb": "3dhoneycomb",
        "3d honeycomb": "3dhoneycomb",
        "aligned_rectilinear": "alignedrectilinear",
        "aligned-rectilinear": "alignedrectilinear",
        "aligned rectilinear": "alignedrectilinear",
        "adaptive_cubic": "adaptivecubic",
        "adaptive-cubic": "adaptivecubic",
        "adaptive cubic": "adaptivecubic",
        "quarter_cubic": "quartercubic",
        "quarter-cubic": "quartercubic",
        "quarter cubic": "quartercubic",
        "support_cubic": "supportcubic",
        "support-cubic": "supportcubic",
        "support cubic": "supportcubic",
        "tri_hexagon": "tri-hexagon",
        "trihexagon": "tri-hexagon",
        "tri hexagon": "tri-hexagon",
        "lateral_honeycomb": "lateral-honeycomb",
        "lateral honeycomb": "lateral-honeycomb",
        "lateral_lattice": "lateral-lattice",
        "lateral lattice": "lateral-lattice",
        "hilbert_curve": "hilbertcurve",
        "hilbert-curve": "hilbertcurve",
        "hilbert curve": "hilbertcurve",
        "archimedean_chords": "archimedeanchords",
        "archimedean-chords": "archimedeanchords",
        "archimedean chords": "archimedeanchords",
        "octagram_spiral": "octagramspiral",
        "octagram-spiral": "octagramspiral",
        "octagram spiral": "octagramspiral",
        "zig_zag": "zigzag",
        "zig-zag": "zigzag",
        "zig zag": "zigzag",
        "cross_zag": "crosszag",
        "cross-zag": "crosszag",
        "locked_zag": "lockedzag",
        "locked-zag": "lockedzag",
        "lines": "line",
        "triangle": "triangles",
        "tpms_d": "tpmsd",
        "tpms-d": "tpmsd",
        "tpms_fk": "tpmsfk",
        "tpms-fk": "tpmsfk",
    },
    "top_surface_pattern": dict(_SURFACE_PATTERN_ALIASES),
    "bottom_surface_pattern": dict(_SURFACE_PATTERN_ALIASES),
    "internal_solid_infill_pattern": dict(_SURFACE_PATTERN_ALIASES),
    "support_type": {
        "normal": "normal(auto)",
        "default": "normal(auto)",
        "auto": "normal(auto)",
        "normal_auto": "normal(auto)",
        "normal-auto": "normal(auto)",
        "normal auto": "normal(auto)",
        "tree": "tree(auto)",
        "organic": "tree(auto)",
        "tree_auto": "tree(auto)",
        "tree-auto": "tree(auto)",
        "tree auto": "tree(auto)",
        "normal_manual": "normal(manual)",
        "normal-manual": "normal(manual)",
        "normal manual": "normal(manual)",
        "manual": "normal(manual)",
        "tree_manual": "tree(manual)",
        "tree-manual": "tree(manual)",
        "tree manual": "tree(manual)",
    },
    "support_style": {
        "auto": "default",
        "tree slim": "tree_slim",
        "tree-slim": "tree_slim",
        "slim": "tree_slim",
        "tree strong": "tree_strong",
        "tree-strong": "tree_strong",
        "strong": "tree_strong",
        "tree hybrid": "tree_hybrid",
        "tree-hybrid": "tree_hybrid",
        "hybrid": "tree_hybrid",
    },
    "support_base_pattern": {
        "rectilinear_grid": "rectilinear-grid",
        "rectilinear grid": "rectilinear-grid",
    },
    "support_interface_pattern": {
        "spiral_inset": "spiralinset",
        "spiral-inset": "spiralinset",
        "spiral inset": "spiralinset",
        "rectilinear-interlaced": "rectilinear_interlaced",
        "rectilinear interlaced": "rectilinear_interlaced",
    },
    "brim_type": {
        "none": "no_brim",
        "no": "no_brim",
        "off": "no_brim",
        "disabled": "no_brim",
        "no brim": "no_brim",
        "no-brim": "no_brim",
        "outer": "outer_only",
        "outer only": "outer_only",
        "outer-only": "outer_only",
        "outside": "outer_only",
        "inner": "inner_only",
        "inner only": "inner_only",
        "inner-only": "inner_only",
        "inside": "inner_only",
        "both": "outer_and_inner",
        "outer and inner": "outer_and_inner",
        "outer-and-inner": "outer_and_inner",
        "outer_inner": "outer_and_inner",
        "auto": "auto_brim",
        "auto brim": "auto_brim",
        "auto-brim": "auto_brim",
        "ears": "brim_ears",
        "mouse_ears": "brim_ears",
        "mouse ears": "brim_ears",
        "brim ears": "brim_ears",
        "brim-ears": "brim_ears",
        "leading_edge": "leading_edge_only",
        "leading edge": "leading_edge_only",
        "leading-edge-only": "leading_edge_only",
    },
    "seam_position": {
        "aligned back": "aligned_back",
        "aligned-back": "aligned_back",
        "rear": "back",
    },
    "wall_generator": {
        "standard": "classic",
        "normal": "classic",
    },
    "wall_sequence": {
        "inner/outer": "inner wall/outer wall",
        "inner_outer": "inner wall/outer wall",
        "inner-outer": "inner wall/outer wall",
        "inner_wall_outer_wall": "inner wall/outer wall",
        "inner to outer": "inner wall/outer wall",
        "outer/inner": "outer wall/inner wall",
        "outer_inner": "outer wall/inner wall",
        "outer-inner": "outer wall/inner wall",
        "outer_wall_inner_wall": "outer wall/inner wall",
        "outer to inner": "outer wall/inner wall",
        "inner-outer-inner": "inner-outer-inner wall",
        "inner_outer_inner": "inner-outer-inner wall",
        "inner/outer/inner": "inner-outer-inner wall",
        "sandwich": "inner-outer-inner wall",
    },
    "z_hop_types": {
        "auto": "Auto Lift",
        "auto_lift": "Auto Lift",
        "auto-lift": "Auto Lift",
        "auto lift": "Auto Lift",
        "normal": "Normal Lift",
        "normal_lift": "Normal Lift",
        "normal-lift": "Normal Lift",
        "normal lift": "Normal Lift",
        "vertical": "Normal Lift",
        "slope": "Slope Lift",
        "slope_lift": "Slope Lift",
        "slope-lift": "Slope Lift",
        "slope lift": "Slope Lift",
        "sloped": "Slope Lift",
        "spiral": "Spiral Lift",
        "spiral_lift": "Spiral Lift",
        "spiral-lift": "Spiral Lift",
        "spiral lift": "Spiral Lift",
    },
    "ironing_type": {
        "no_ironing": "no ironing",
        "no-ironing": "no ironing",
        "none": "no ironing",
        "off": "no ironing",
        "disabled": "no ironing",
        "no": "no ironing",
        "top_surfaces": "top",
        "all_top": "top",
        "all top surfaces": "top",
        "topmost_surface": "topmost",
        "topmost surface": "topmost",
        "top_most": "topmost",
        "all_solid": "solid",
        "all solid layers": "solid",
    },
    "fuzzy_skin": {
        "disabled": "disabled_fuzzy",
        "off": "disabled_fuzzy",
        "false": "disabled_fuzzy",
        "0": "disabled_fuzzy",
        "disable": "disabled_fuzzy",
        "no": "disabled_fuzzy",
        "disabled fuzzy": "disabled_fuzzy",
        "disabled-fuzzy": "disabled_fuzzy",
        "painted": "none",
        "painted_only": "none",
        "painted only": "none",
        "contour": "external",
        "outside": "external",
        "outer": "external",
        "all_walls": "allwalls",
        "all-walls": "allwalls",
        "all walls": "allwalls",
        "holes": "hole",
    },
    "fuzzy_skin_noise_type": {
        "ridged_multi": "ridgedmulti",
        "ridged-multi": "ridgedmulti",
        "ridged multi": "ridgedmulti",
    },
    "seam_slope_type": {
        "off": "none",
        "disabled": "none",
        "no": "none",
        "contour": "external",
        "outer": "external",
        "contour_only": "external",
        "contour_and_hole": "all",
        "contour and hole": "all",
    },
    "slicing_mode": {
        "evenodd": "even_odd",
        "even-odd": "even_odd",
        "even odd": "even_odd",
        "closeholes": "close_holes",
        "close-holes": "close_holes",
        "close holes": "close_holes",
    },
    "draft_shield": {
        "0": "disabled",
        "false": "disabled",
        "off": "disabled",
        "none": "disabled",
        "no": "disabled",
        "1": "enabled",
        "true": "enabled",
        "on": "enabled",
        "yes": "enabled",
    },
    "print_sequence": {
        "by_layer": "by layer",
        "by-layer": "by layer",
        "layer": "by layer",
        "by_object": "by object",
        "by-object": "by object",
        "object": "by object",
        "sequential": "by object",
    },
    "curr_bed_type": {
        "cool": "Cool Plate",
        "cool_plate": "Cool Plate",
        "cool-plate": "Cool Plate",
        "engineering": "Engineering Plate",
        "engineering_plate": "Engineering Plate",
        "eng_plate": "Engineering Plate",
        "high_temp": "High Temp Plate",
        "high_temp_plate": "High Temp Plate",
        "smooth_pei": "High Temp Plate",
        "smooth pei": "High Temp Plate",
        "smooth pei plate": "High Temp Plate",
        "hot_plate": "High Temp Plate",
        "textured": "Textured PEI Plate",
        "textured_pei": "Textured PEI Plate",
        "textured_pei_plate": "Textured PEI Plate",
        "textured pei": "Textured PEI Plate",
        "textured_cool": "Textured Cool Plate",
        "textured_cool_plate": "Textured Cool Plate",
        "supertack": "Supertack Plate",
        "supertack_plate": "Supertack Plate",
        "super tack": "Supertack Plate",
    },
    "gcode_flavor": {
        "marlin_legacy": "marlin",
        "marlin 1": "marlin",
        "marlin_2": "marlin2",
        "marlin 2": "marlin2",
        "marlin-2": "marlin2",
        "rrf": "reprapfirmware",
        "reprap": "reprapfirmware",
        "reprap_firmware": "reprapfirmware",
    },
    "timelapse_type": {
        "traditional": "0",
        "standard": "0",
        "smooth": "1",
        "hyper": "1",
    },
}

BOOL_KEYS: set[str] = {
    "enable_support",
    "support_on_build_plate_only",
    "detect_thin_wall",
    "only_one_wall_top",
    "infill_combination",
    "slow_down_for_layer_cooling",
    "enable_pressure_advance",
    "retract_when_changing_layer",
    "wipe",
    "enable_overhang_speed",
    "enable_prime_tower",
    "detect_overhang_wall",
    "reduce_infill_retraction",
    "reduce_crossing_wall",
    "spiral_mode",
    "bridge_no_support",
    "independent_support_layer_height",
    "enable_arc_fitting",
    "precise_outer_wall",
    "precise_z_height",
    "wipe_on_loops",
    "flush_into_infill",
    "flush_into_support",
    "flush_into_objects",
    "ooze_prevention",
}

# OrcaSlicer coPercent keys where canonical format includes trailing '%'
PERCENT_KEYS: set[str] = {
    "sparse_infill_density",
    "infill_wall_overlap",
    "bridge_density",
}

# OrcaSlicer coInts percentage keys (0..100 integer WITHOUT trailing '%')
INT_PERCENT_KEYS: set[str] = {
    "fan_max_speed",
    "fan_min_speed",
    "overhang_fan_speed",
    "additional_cooling_fan_speed",
    "auxiliary_fan_speed",
}

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_PERCENT_RE = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*%$")


def normalize_setting_category(key: str, raw_cat: str = "") -> str:
    """Resolve canonical OrcaSlicer preset category ('process', 'filament', or 'printer')."""
    k = str(key or "").strip()
    if k in CUSTOM_GCODE_KEYS:
        return str(CUSTOM_GCODE_KEYS[k]["category"])
    if k in FLAT_SETTING_INFO:
        return FLAT_SETTING_INFO[k]["category"]
    c = str(raw_cat or "").strip().lower()
    if c in ("filament", "filaments", "material", "materials"):
        return "filament"
    if c in ("printer", "printers", "machine", "extruder"):
        return "printer"
    return "process"


def _match_single_enum(key: str, token: str, valid_values: list[str]) -> tuple[str | None, bool]:
    """Match a single enum value token; returns (canonical_value, was_normalized)."""
    if token in valid_values:
        return token, False

    lower = token.lower()
    aliases = ENUM_ALIASES.get(key, {})
    if lower in aliases:
        return aliases[lower], True

    # Case-insensitive exact match
    for v in valid_values:
        if v.lower() == lower:
            return v, True

    # Loose punctuation/whitespace match (e.g., underscores/hyphens/spaces stripped)
    compact = re.sub(r"[\s_\-]+", "", lower)
    for v in valid_values:
        if re.sub(r"[\s_\-]+", "", v.lower()) == compact:
            return v, True

    return None, False


def _normalize_single_bool(token: str) -> tuple[str | None, bool]:
    low = token.strip().lower()
    if low == "1":
        return "1", False
    if low == "0":
        return "0", False
    if low in ("true", "yes", "on", "enabled"):
        return "1", True
    if low in ("false", "no", "off", "disabled"):
        return "0", True
    return None, False


def normalize_and_validate_setting(
    key: str,
    value: str,
    category: str = "",
) -> tuple[str, str | None, str | None]:
    """
    Validate and normalize an OrcaSlicer setting value before tx.set().

    Returns:
        (normalized_value, note_if_normalized, error_if_invalid)
    """
    k = str(key or "").strip()
    if not k:
        return "", None, "Empty setting key"

    # Custom G-code must NEVER be stripped or enum-coerced
    if k in CUSTOM_GCODE_KEYS:
        return str(value if value is not None else ""), None, None

    raw = str(value if value is not None else "").strip()

    # Deprecated key guard (verified removed in OrcaSlicer 2.5.2)
    if k == "overhang_speed_classic":
        return (
            raw,
            None,
            "Key 'overhang_speed_classic' is deprecated in OrcaSlicer 2.5.2. Use 'enable_overhang_speed' instead.",
        )

    # 1. Enum validation & alias normalization
    if k in ENUM_VALID_VALUES:
        valid_values = ENUM_VALID_VALUES[k]
        matched, changed = _match_single_enum(k, raw, valid_values)
        if matched is not None:
            note = f"Normalized '{raw}' -> '{matched}'" if changed else None
            return matched, note, None

        # Multi-extruder comma-separated printer enums (e.g. z_hop_types = "Normal Lift,Normal Lift")
        if "," in raw and normalize_setting_category(k, category) == "printer":
            parts = [p.strip() for p in raw.split(",")]
            norm_parts: list[str] = []
            any_changed = False
            all_ok = True
            for p in parts:
                m_part, ch_part = _match_single_enum(k, p, valid_values)
                if m_part is None:
                    all_ok = False
                    break
                norm_parts.append(m_part)
                if ch_part:
                    any_changed = True
            if all_ok and norm_parts:
                joined = ",".join(norm_parts)
                note = f"Normalized '{raw}' -> '{joined}'" if any_changed or joined != raw else None
                return joined, note, None

        valid_str = ", ".join(valid_values)
        return (
            raw,
            None,
            f"Invalid value '{raw}' for '{k}'. Valid values: {valid_str}",
        )

    # 2. Boolean normalization ("true"/"false"/"yes"/"no" -> "1"/"0")
    if k in BOOL_KEYS:
        norm_b, changed = _normalize_single_bool(raw)
        if norm_b is not None:
            note = f"Normalized '{raw}' -> '{norm_b}'" if changed else None
            return norm_b, note, None

        if "," in raw and normalize_setting_category(k, category) == "printer":
            parts = [p.strip() for p in raw.split(",")]
            norm_parts = []
            any_changed = False
            all_ok = True
            for p in parts:
                nb, cb = _normalize_single_bool(p)
                if nb is None:
                    all_ok = False
                    break
                norm_parts.append(nb)
                if cb:
                    any_changed = True
            if all_ok and norm_parts:
                joined = ",".join(norm_parts)
                note = f"Normalized '{raw}' -> '{joined}'" if any_changed or joined != raw else None
                return joined, note, None

        return raw, None, f"Invalid boolean value '{raw}' for '{k}'. Expected '1' or '0'."

    # 3. coPercent normalization (ensure trailing '%')
    if k in PERCENT_KEYS:
        m_pct = _PERCENT_RE.match(raw)
        if m_pct:
            clean = f"{m_pct.group(1)}%"
            note = f"Normalized '{raw}' -> '{clean}'" if clean != raw else None
            return clean, note, None
        if _NUMBER_RE.match(raw):
            clean = f"{raw}%"
            return clean, f"Added '%' -> '{clean}'", None
        return raw, None, f"Invalid percentage value '{raw}' for '{k}'. Expected a value like '25%'."

    # 4. Integer percentage fan keys (strip trailing '%' if provided by AI)
    if k in INT_PERCENT_KEYS:
        m_pct = _PERCENT_RE.match(raw)
        if m_pct:
            num_str = m_pct.group(1)
            try:
                num_int = int(round(float(num_str)))
                clean = str(max(0, min(100, num_int)))
                return clean, f"Normalized '{raw}' -> '{clean}'", None
            except ValueError:
                pass
        if _NUMBER_RE.match(raw):
            try:
                num_val = float(raw)
                if num_val < 0 or num_val > 100:
                    return raw, None, f"Value '{raw}' for '{k}' is out of range (0..100)."
                clean = str(int(round(num_val)))
                note = f"Normalized '{raw}' -> '{clean}'" if clean != raw else None
                return clean, note, None
            except ValueError:
                pass

    return raw, None, None
