from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from ..core.constants import norm_lang, tr


def _ensure_orca_packages_on_path() -> None:
    """Attach OrcaSlicer's bundled Python packages dir (cross-platform) if numpy is not already importable."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            candidates.append(Path(appdata) / "OrcaSlicer" / "python" / "packages")
    elif sys.platform == "darwin":
        candidates.append(Path.home() / "Library" / "Application Support" / "OrcaSlicer" / "python" / "packages")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else (Path.home() / ".config")
        candidates.append(base / "OrcaSlicer" / "python" / "packages")

    for pkg_root in candidates:
        if not pkg_root.is_dir():
            continue
        py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
        preferred = pkg_root / py_tag
        if preferred.is_dir() and str(preferred) not in sys.path:
            sys.path.append(str(preferred))
        try:
            for sub in sorted(pkg_root.iterdir()):
                if sub.is_dir() and sub.name.startswith("cp3") and str(sub) not in sys.path:
                    sys.path.append(str(sub))
        except OSError:
            pass


_ensure_orca_packages_on_path()

try:
    import numpy as np  # type: ignore
except Exception:
    np = None  # type: ignore

try:
    import orca  # type: ignore
    import orca.host  # type: ignore
except Exception:
    orca = None  # type: ignore


def _combine_matrices(vol_mat: Any | None, inst_mat: Any | None) -> Any:
    """Compose 4x4 volume matrix and instance matrix into world transform `inst @ vol`."""
    total = np.eye(4, dtype=np.float64)
    if vol_mat is not None:
        try:
            vm = np.asarray(vol_mat, dtype=np.float64)
            if vm.shape == (4, 4):
                total = vm @ total
        except Exception:
            pass
    if inst_mat is not None:
        try:
            im = np.asarray(inst_mat, dtype=np.float64)
            if im.shape == (4, 4):
                total = im @ total
        except Exception:
            pass
    return total


def analyze_object_meshes_numpy(
    volume_items: list[dict[str, Any]],
) -> dict[str, float] | None:
    """
    Pure-NumPy geometry analysis across ALL model-part volumes of a single ModelObject.

    Fixes all 4 v2.x geometry bugs:
      1. Mirroring normal flip: negates cross product when `det(rot) < 0` so mirrored
         parts keep outward-pointing normals (overhangs are not swapped with tops).
      2. Global object `z_min`: computes object-wide minimum Z across all volumes so
         floating upper sub-volumes are never misclassified as build-plate contact.
      3. Union bounding box: computes true min/max union extents across all volumes
         instead of taking `max(size_x, ...)`.
      4. Scaled volume: multiplies raw mesh volume by `|det(rot)|` (or uses exact
         signed tetrahedron volume of transformed triangles when raw volume is absent).

    Each item in `volume_items` is a dict:
        {
            "vertices": array-like (N, 3),
            "triangles": array-like (M, 3),
            "matrix": array-like (4, 4) | None,
            "raw_volume_mm3": float | None,
        }
    """
    if np is None or not volume_items:
        return None

    transformed_parts: list[dict[str, Any]] = []
    global_min = np.array([np.inf, np.inf, np.inf], dtype=np.float64)
    global_max = np.array([-np.inf, -np.inf, -np.inf], dtype=np.float64)

    for item in volume_items:
        try:
            verts = np.asarray(item["vertices"], dtype=np.float64)
            tris = np.asarray(item["triangles"], dtype=np.int32)
            if verts.ndim != 2 or verts.shape[1] != 3 or tris.ndim != 2 or tris.shape[1] != 3 or len(tris) == 0:
                continue

            mat = item.get("matrix")
            if mat is not None:
                m4 = np.asarray(mat, dtype=np.float64)
                if m4.shape != (4, 4):
                    m4 = np.eye(4, dtype=np.float64)
            else:
                m4 = np.eye(4, dtype=np.float64)

            rot = m4[:3, :3]
            trans = m4[:3, 3]
            det = float(np.linalg.det(rot))

            t_verts = verts @ rot.T + trans
            part_min = np.min(t_verts, axis=0)
            part_max = np.max(t_verts, axis=0)
            global_min = np.minimum(global_min, part_min)
            global_max = np.maximum(global_max, part_max)

            v0 = t_verts[tris[:, 0]]
            v1 = t_verts[tris[:, 1]]
            v2 = t_verts[tris[:, 2]]

            cross_vec = np.cross(v1 - v0, v2 - v0)
            # Fix (a): Mirroring (negative determinant) inverts triangle winding / normals
            if det < 0.0:
                cross_vec = -cross_vec

            norms = np.linalg.norm(cross_vec, axis=1)
            areas = 0.5 * norms
            valid = norms > 1e-7
            nz = np.zeros_like(norms)
            nz[valid] = cross_vec[valid, 2] / norms[valid]

            tri_z_max = np.maximum(np.maximum(v0[:, 2], v1[:, 2]), v2[:, 2])
            tri_z_min = np.minimum(np.minimum(v0[:, 2], v1[:, 2]), v2[:, 2])

            # Fix (d): Scaled volume using |det(rot)| * raw_volume_mm3, fallback signed tetrahedron volume
            raw_vol_mm3 = item.get("raw_volume_mm3")
            if raw_vol_mm3 is not None and float(raw_vol_mm3) > 0.0:
                vol_mm3 = abs(det) * float(raw_vol_mm3)
            else:
                signed_vol = float(np.sum(np.einsum("ij,ij->i", v0, cross_vec)) / 6.0)
                vol_mm3 = abs(signed_vol)

            transformed_parts.append({
                "areas": areas,
                "nz": nz,
                "tri_z_max": tri_z_max,
                "tri_z_min": tri_z_min,
                "vol_mm3": vol_mm3,
            })
        except Exception:
            continue

    if not transformed_parts or not np.all(np.isfinite(global_min)):
        return None

    # Fix (b): Global object z_min across all model-part volumes
    obj_z_min = float(global_min[2])

    # Fix (c): True union bounding box across all volumes
    size_x = max(0.0, float(global_max[0] - global_min[0]))
    size_y = max(0.0, float(global_max[1] - global_min[1]))
    size_z = max(0.0, float(global_max[2] - global_min[2]))

    total_area = 0.0
    bed_contact_area = 0.0
    overhang_45_area = 0.0
    overhang_60_area = 0.0
    total_vol_mm3 = 0.0

    for part in transformed_parts:
        areas = part["areas"]
        nz = part["nz"]
        tri_z_max = part["tri_z_max"]
        tri_z_min = part["tri_z_min"]

        total_area += float(np.sum(areas))
        total_vol_mm3 += float(part["vol_mm3"])

        bed_mask = (tri_z_max <= (obj_z_min + 0.30)) & (nz < -0.5)
        bed_contact_area += float(np.sum(areas[bed_mask]))

        above_first_layer = tri_z_min > (obj_z_min + 0.35)
        overhang_45_mask = above_first_layer & (nz < -0.7071)
        overhang_60_mask = above_first_layer & (nz < -0.8660)

        overhang_45_area += float(np.sum(areas[overhang_45_mask]))
        overhang_60_area += float(np.sum(areas[overhang_60_mask]))

    return {
        "min_x": round(float(global_min[0]), 2),
        "max_x": round(float(global_max[0]), 2),
        "min_y": round(float(global_min[1]), 2),
        "max_y": round(float(global_max[1]), 2),
        "min_z": round(float(global_min[2]), 2),
        "max_z": round(float(global_max[2]), 2),
        "size_x": round(size_x, 2),
        "size_y": round(size_y, 2),
        "size_z": round(size_z, 2),
        "volume_cm3": round(total_vol_mm3 / 1000.0, 2),
        "total_surface_mm2": round(total_area, 1),
        "bed_contact_mm2": round(bed_contact_area, 1),
        "overhang_45_mm2": round(overhang_45_area, 1),
        "overhang_60_mm2": round(overhang_60_area, 1),
        "overhang_45_pct": round((overhang_45_area / total_area * 100.0) if total_area > 0 else 0.0, 1),
        "overhang_60_pct": round((overhang_60_area / total_area * 100.0) if total_area > 0 else 0.0, 1),
    }


def _read_config_overrides(obj_or_vol: Any, max_keys: int = 30) -> dict[str, str]:
    overrides: dict[str, str] = {}
    try:
        keys_fn = getattr(obj_or_vol, "config_keys", None)
        val_fn = getattr(obj_or_vol, "config_value", None)
        if not callable(keys_fn) or not callable(val_fn):
            return overrides
        for k in list(keys_fn() or [])[:max_keys]:
            try:
                v = val_fn(k)
                if v is not None and str(v) != "":
                    overrides[str(k)] = str(v)
            except Exception:
                continue
    except Exception:
        pass
    return overrides


def _read_extruder_id(vol: Any) -> int | None:
    try:
        attr = getattr(vol, "extruder_id", None)
        val = attr() if callable(attr) else attr
        if val is not None:
            iv = int(val)
            if iv > 0:
                return iv
    except Exception:
        pass
    return None


def _extract_bbox_size(bb: Any) -> tuple[float, float, float]:
    if bb is None:
        return 0.0, 0.0, 0.0
    try:
        sz = bb.size() if callable(getattr(bb, "size", None)) else getattr(bb, "size", None)
        if sz is None:
            return 0.0, 0.0, 0.0
        if hasattr(sz, "x"):
            return round(float(sz.x), 2), round(float(sz.y), 2), round(float(sz.z), 2)
        if isinstance(sz, (list, tuple)) and len(sz) >= 3:
            return round(float(sz[0]), 2), round(float(sz[1]), 2), round(float(sz[2]), 2)
    except Exception:
        pass
    return 0.0, 0.0, 0.0


def inspect_plate_geometry(lang: str = "ru") -> dict[str, Any]:
    """
    Inspect all objects on the active OrcaSlicer build plate with full NumPy
    3D geometry analysis, overhang detection, per-part AMS extruder slots,
    and per-object / modifier setting overrides.
    """
    l = norm_lang(lang)
    summary: dict[str, Any] = {
        "has_model": False,
        "plate_index": 0,
        "material_count": 0,
        "is_mm_painted": False,
        "is_fuzzy_skin_painted": False,
        "object_count": 0,
        "total_instances": 0,
        "total_volume_cm3": 0.0,
        "total_triangles": 0,
        "total_bed_contact_mm2": 0.0,
        "total_overhang_45_mm2": 0.0,
        "total_overhang_60_mm2": 0.0,
        "objects": [],
        "warnings": [],
    }

    if orca is None or getattr(orca, "host", None) is None:
        return summary

    try:
        model = orca.host.model()
        if model is None:
            return summary

        try:
            fn = getattr(model, "current_plate_index", None)
            if callable(fn):
                summary["plate_index"] = int(fn())
        except Exception:
            pass
        try:
            fn = getattr(model, "material_count", None)
            if callable(fn):
                summary["material_count"] = int(fn())
        except Exception:
            pass
        try:
            fn = getattr(model, "is_mm_painted", None)
            if callable(fn):
                summary["is_mm_painted"] = bool(fn())
        except Exception:
            pass
        try:
            fn = getattr(model, "is_fuzzy_skin_painted", None)
            if callable(fn):
                summary["is_fuzzy_skin_painted"] = bool(fn())
        except Exception:
            pass

        objs = list(model.objects() or [])
        if not objs:
            return summary

        summary["has_model"] = True
        summary["object_count"] = len(objs)

        for idx, obj in enumerate(objs, start=1):
            default_obj_name = tr(l, f"Объект #{idx}", f"Об'єкт #{idx}", f"Object #{idx}")
            obj_name = str(getattr(obj, "name", "") or default_obj_name)
            instances = list(obj.instances() or [])
            inst_count = max(1, len(instances))
            first_inst_mat = None
            size_x = size_y = size_z = 0.0

            if instances:
                try:
                    first_inst_mat = instances[0].matrix()
                except Exception:
                    first_inst_mat = None
                try:
                    size_x, size_y, size_z = _extract_bbox_size(instances[0].bounding_box())
                except Exception:
                    pass

            if size_x == 0.0 and size_y == 0.0:
                try:
                    size_x, size_y, size_z = _extract_bbox_size(obj.raw_mesh_bounding_box())
                except Exception:
                    pass

            object_overrides = _read_config_overrides(obj)
            modifier_overrides: list[dict[str, Any]] = []
            extruder_ids_set: set[int] = set()

            vol_cm3 = 0.0
            triangles = 0
            mesh_errors = 0
            is_manifold = True
            has_modifiers = False
            support_painted = False
            seam_painted = False
            bed_contact_mm2 = 0.0
            overhang_45_mm2 = 0.0
            overhang_60_mm2 = 0.0
            total_surface_mm2 = 0.0

            numpy_vol_items: list[dict[str, Any]] = []

            for vol in list(obj.volumes() or []):
                is_mod_or_special = False
                try:
                    if (
                        vol.is_modifier()
                        or vol.is_negative_volume()
                        or vol.is_support_enforcer()
                        or vol.is_support_blocker()
                    ):
                        has_modifiers = True
                        is_mod_or_special = True
                except Exception:
                    pass

                if is_mod_or_special:
                    mod_ov = _read_config_overrides(vol)
                    mod_ext = _read_extruder_id(vol)
                    if mod_ov or mod_ext is not None:
                        mod_entry: dict[str, Any] = {
                            "name": str(getattr(vol, "name", "") or "modifier"),
                            "type": str(getattr(vol, "type", "") or ""),
                            "overrides": mod_ov,
                        }
                        if mod_ext is not None:
                            mod_entry["extruder_id"] = mod_ext
                        modifier_overrides.append(mod_entry)

                try:
                    if not vol.is_model_part():
                        continue
                except Exception:
                    pass

                ext_id = _read_extruder_id(vol)
                if ext_id is not None:
                    extruder_ids_set.add(ext_id)

                try:
                    mesh_errors += int(vol.mesh_errors_count() or 0)
                except Exception:
                    pass
                try:
                    if vol.is_fdm_support_painted():
                        support_painted = True
                    if vol.is_seam_painted():
                        seam_painted = True
                except Exception:
                    pass

                raw_mesh_vol_mm3 = 0.0
                try:
                    m = vol.mesh()
                    if m is not None:
                        raw_mesh_vol_mm3 = float(m.volume() or 0.0)
                        triangles += int(m.triangle_count() or 0)
                        if not m.is_manifold():
                            is_manifold = False

                        if np is not None:
                            v_mat = None
                            try:
                                v_mat = vol.matrix()
                            except Exception:
                                v_mat = None
                            total_mat = _combine_matrices(v_mat, first_inst_mat)
                            numpy_vol_items.append({
                                "vertices": m.vertices(),
                                "triangles": m.triangles(),
                                "matrix": total_mat,
                                "raw_volume_mm3": raw_mesh_vol_mm3 if raw_mesh_vol_mm3 > 0 else None,
                            })
                        else:
                            # Non-numpy fallback: scale raw volume by scaling_factor if available
                            scale_prod = 1.0
                            try:
                                sf_fn = getattr(vol, "scaling_factor", None)
                                sf = sf_fn() if callable(sf_fn) else sf_fn
                                if sf is not None:
                                    if hasattr(sf, "x"):
                                        scale_prod = abs(float(sf.x) * float(sf.y) * float(sf.z))
                                    elif isinstance(sf, (list, tuple)) and len(sf) >= 3:
                                        scale_prod = abs(float(sf[0]) * float(sf[1]) * float(sf[2]))
                            except Exception:
                                scale_prod = 1.0
                            vol_cm3 += (raw_mesh_vol_mm3 * scale_prod) / 1000.0
                except Exception:
                    pass

            # Run unified object-level NumPy analysis across all model-part volumes
            geo = analyze_object_meshes_numpy(numpy_vol_items)
            if geo:
                size_x = geo["size_x"]
                size_y = geo["size_y"]
                size_z = geo["size_z"]
                vol_cm3 = geo["volume_cm3"]
                bed_contact_mm2 = geo["bed_contact_mm2"]
                overhang_45_mm2 = geo["overhang_45_mm2"]
                overhang_60_mm2 = geo["overhang_60_mm2"]
                total_surface_mm2 = geo["total_surface_mm2"]

            min_base = max(0.1, min(size_x, size_y))
            height_ratio = round(size_z / min_base, 2) if (size_x > 0 and size_y > 0) else 0.0
            overhang_45_pct = round(
                (overhang_45_mm2 / total_surface_mm2 * 100.0) if total_surface_mm2 > 0 else 0.0, 1
            )

            obj_info: dict[str, Any] = {
                "name": obj_name,
                "instances": inst_count,
                "size_x": round(size_x, 2),
                "size_y": round(size_y, 2),
                "size_z": round(size_z, 2),
                "volume_cm3": round(vol_cm3, 2),
                "triangles": triangles,
                "is_manifold": is_manifold,
                "mesh_errors": mesh_errors,
                "bed_contact_mm2": round(bed_contact_mm2, 1),
                "total_surface_mm2": round(total_surface_mm2, 1),
                "overhang_45_mm2": round(overhang_45_mm2, 1),
                "overhang_60_mm2": round(overhang_60_mm2, 1),
                "overhang_45_pct": overhang_45_pct,
                "height_to_base_ratio": height_ratio,
                "has_modifiers": has_modifiers,
                "support_painted": support_painted,
                "seam_painted": seam_painted,
                "extruder_ids": sorted(extruder_ids_set),
                "object_overrides": object_overrides,
                "modifier_overrides": modifier_overrides,
            }
            summary["objects"].append(obj_info)

            summary["total_instances"] += inst_count
            summary["total_volume_cm3"] = round(summary["total_volume_cm3"] + vol_cm3 * inst_count, 2)
            summary["total_triangles"] += triangles * inst_count
            summary["total_bed_contact_mm2"] = round(
                summary["total_bed_contact_mm2"] + bed_contact_mm2 * inst_count, 1
            )
            summary["total_overhang_45_mm2"] = round(
                summary["total_overhang_45_mm2"] + overhang_45_mm2 * inst_count, 1
            )
            summary["total_overhang_60_mm2"] = round(
                summary["total_overhang_60_mm2"] + overhang_60_mm2 * inst_count, 1
            )

            if not is_manifold or mesh_errors > 0:
                summary["warnings"].append({
                    "level": "danger",
                    "text": tr(
                        l,
                        f"«{obj_name}»: незамкнутая сетка (non-manifold) или ошибки геометрии ({mesh_errors} шт.). Рекомендуется выполнить ремонт модели.",
                        f"«{obj_name}»: незамкнена сітка (non-manifold) або помилки геометрії ({mesh_errors} шт.). Рекомендується виконати ремонт моделі.",
                        f'"{obj_name}": non-manifold mesh or geometry errors ({mesh_errors}). Mesh repair is recommended.',
                    ),
                })
            if bed_contact_mm2 < 120.0 and size_z > 15.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: малая площадь контакта первого слоя со столом ({bed_contact_mm2:.0f} мм²) при высоте {size_z:.1f} мм — высокий риск отрыва, рекомендуется кайма (Brim).",
                        f"«{obj_name}»: мала площа контакту першого шару зі столом ({bed_contact_mm2:.0f} мм²) при висоті {size_z:.1f} мм — високий ризик відриву, рекомендується кайма (Brim).",
                        f'"{obj_name}": small first-layer bed contact area ({bed_contact_mm2:.0f} mm²) at height {size_z:.1f} mm — detachment risk, Brim is recommended.',
                    ),
                })
            elif height_ratio >= 2.8 and size_z >= 40.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: высокая и узкая деталь (отношение высоты к базе {height_ratio}:1) — рекомендуется кайма (Brim) и снижение ускорений.",
                        f"«{obj_name}»: висока та вузька деталь (відношення висоти до бази {height_ratio}:1) — рекомендується кайма (Brim) та зниження прискорень.",
                        f'"{obj_name}": tall and narrow part (height-to-base ratio {height_ratio}:1) — Brim and reduced accelerations recommended.',
                    ),
                })
            if overhang_60_mm2 > 25.0 or overhang_45_mm2 > 80.0:
                summary["warnings"].append({
                    "level": "warn",
                    "text": tr(
                        l,
                        f"«{obj_name}»: обнаружены нависания >45° ({overhang_45_mm2:.0f} мм², {overhang_45_pct}% поверхности; критических >60°: {overhang_60_mm2:.0f} мм²) — проверьте включение поддержек или ориентацию.",
                        f"«{obj_name}»: виявлено нависання >45° ({overhang_45_mm2:.0f} мм², {overhang_45_pct}% поверхні; критичних >60°: {overhang_60_mm2:.0f} мм²) — перевірте увімкнення підтримок або орієнтацію.",
                        f'"{obj_name}": overhangs >45° detected ({overhang_45_mm2:.0f} mm², {overhang_45_pct}% surface; critical >60°: {overhang_60_mm2:.0f} mm²) — check supports or part orientation.',
                    ),
                })
    except Exception as exc:
        summary["error"] = str(exc)

    return summary
