"""Manufacturability review of a part, for the process it will be made with, with the reason behind each point.

  fdm               3D printing (the print audit's measurements, plus holes, bosses, slender parts, layer direction)
  injection_molding draft on walls parallel to the pull, undercuts that need side actions, wall-thickness uniformity

Like the PCB layout review, each point has a level (concern / suggestion / info / good), the reason, and a `basis`:
"measured" (computed from the geometry) or "rule of thumb" (design-guide practice). It works on parts of an RL CAD
design and on any STEP or STL the engineer made elsewhere (FreeCAD, Onshape, Fusion), so the AI can review
hand-made parts too.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

import numpy as np


def _pt(level, category, message, why, basis="measured", fix=""):
    d = {"level": level, "category": category, "message": message, "why": why, "basis": basis}
    if fix:
        d["suggestion"] = fix
    return d


def _mesh(shape, tol=0.08):
    import trimesh
    from .geom.mesh import mesh
    v, t, _ = mesh(shape, tol, 0.3)
    tm = trimesh.Trimesh(vertices=v, faces=t, process=True)
    tm.merge_vertices()
    return tm


def load_shape(path: str):
    """A STEP or STL file as a shape (STEP) or a trimesh (STL)."""
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("step", "stp"):
        from build123d import import_step
        return import_step(path)
    if ext == "stl":
        import trimesh
        return trimesh.load_mesh(path)
    raise ValueError("review a .step/.stp or .stl file")


def _holes(shape) -> List[Dict]:
    """Cylindrical holes (concave cylindrical faces): diameter, axis direction, centre."""
    out = []
    try:
        faces = shape.faces()
    except Exception:  # noqa  (a trimesh: no B-rep)
        return out
    for f in faces:
        if f.geom_type.name != "CYLINDER":
            continue
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            ad = BRepAdaptor_Surface(f.wrapped)
            cyl = ad.Cylinder()
            r = cyl.Radius()
            ax = cyl.Axis().Direction()
            c = f.center()
            n = f.normal_at(c)
            loc = cyl.Location()
            # concave (a hole) if the normal points towards the axis
            to_axis = np.array([loc.X() - c.X, loc.Y() - c.Y, loc.Z() - c.Z])
            dvec = np.array([ax.X(), ax.Y(), ax.Z()])
            to_axis -= dvec * to_axis.dot(dvec)
            concave = np.dot(to_axis, [n.X, n.Y, n.Z]) > 0
            if concave and r < 15:
                out.append({"d_mm": round(2 * r, 2), "axis": [round(ax.X(), 2), round(ax.Y(), 2), round(ax.Z(), 2)],
                            "at_mm": [round(c.X, 1), round(c.Y, 1), round(c.Z, 1)], "area": f.area})
        except Exception:  # noqa
            continue
    return out


def review_fdm(shape, name: str = "", audit: Optional[Dict] = None) -> List[Dict]:
    """FDM points for a part as it will be printed (z up; lowest point on the bed)."""
    from .printcheck import audit_mesh
    tm = _mesh(shape) if hasattr(shape, "wrapped") else shape
    a = audit or audit_mesh(tm, name=name)
    pts = []
    if not a["watertight"]:
        pts.append(_pt("concern", "mesh", "the mesh is not closed", "a slicer may drop or fill parts of an open mesh",
                       fix="repair in the CAD tool (boolean between touching faces is the usual cause)"))
    if a["knife_area_mm2"] > 5:
        pts.append(_pt("concern", "walls", f"{a['knife_area_mm2']} mm² thinner than one 0.4 mm line (min "
                       f"{a['min_thickness_mm']} mm)", "below one extrusion width the slicer leaves a gap or skips the "
                       "feature", fix="thicken to ≥ 0.8 mm (two lines)"))
    elif a["thin_area_mm2"] > 20:
        pts.append(_pt("suggestion", "walls", f"{a['thin_area_mm2']} mm² thinner than two lines (0.8 mm)",
                       "single-line walls are weak and often gappy"))
    else:
        pts.append(_pt("good", "walls", "walls are at least two extrusion lines thick", "solid, gap-free walls"))
    if a["overhang_area_mm2"] > 30:
        pts.append(_pt("suggestion", "overhangs", f"{a['overhang_area_mm2']} mm² of overhang beyond 45° in this "
                       "orientation", "unsupported overhangs sag; supports leave marks and cost time",
                       fix="reorient, add a 45° chamfer under the overhang, or accept supports"))
    else:
        pts.append(_pt("good", "overhangs", "no overhang needs support in this orientation", "clean surfaces, no "
                       "support removal"))
    big_bridges = [b for b in a.get("bridges", []) if b["span_mm"] > 15]
    if big_bridges:
        pts.append(_pt("info", "bridges", f"bridges up to {max(b['span_mm'] for b in big_bridges)} mm",
                       "bridges over ~15 mm droop a little; fine for hidden faces"))
    h, fp = a["height_mm"], a["footprint_mm"]
    if h > 0 and min(fp) > 0 and h / min(fp) > 3 and a["bed_contact_mm2"] < 0.15 * fp[0] * fp[1]:
        pts.append(_pt("suggestion", "adhesion", f"tall and slender on the bed ({h} mm high, {a['bed_contact_mm2']} mm² "
                       "contact)", "tall parts on a small footprint wobble and can detach late in the print",
                       fix="use a brim (5 mm) or print another way up"))
    for hole in _holes(shape) if hasattr(shape, "wrapped") else []:
        vertical = abs(hole["axis"][2]) > 0.9
        if hole["d_mm"] < 2.0:
            pts.append(_pt("suggestion", "holes", f"Ø{hole['d_mm']} mm hole at {hole['at_mm']}",
                           "small printed holes come out undersize by ~0.2–0.4 mm", fix="print it at Ø1.5 mm as a "
                                                                                       "pilot and drill to size, or let "
                                                                                       "a self-tapping screw cut it"))
        elif not vertical and hole["d_mm"] > 7:
            pts.append(_pt("suggestion", "holes", f"horizontal Ø{hole['d_mm']} mm hole at {hole['at_mm']}",
                           "the top of a horizontal hole is an overhang; above ~7 mm it sags",
                           fix="make it a teardrop (45° top) or add a flat top"))
    pts.append(_pt("info", "strength", "layers are weakest when pulled apart (along z as printed)",
                   "a printed part is 30–60 % weaker across layers than along them; loads that bend or pull the part "
                   "along z (as printed) are the ones that crack it", "rule of thumb",
                   fix="orient so the main load runs along the layers"))
    return pts


def review_molding(shape, pull=(0, 0, 1), name: str = "") -> List[Dict]:
    """Injection-molding points with the mold opening along `pull` (default z)."""
    tm = _mesh(shape) if hasattr(shape, "wrapped") else shape
    pull = np.array(pull, float)
    pull /= np.linalg.norm(pull)
    n = tm.face_normals
    a = tm.area_faces
    c = tm.triangles_center
    dot = n @ pull
    total = float(a.sum())
    pts = []
    # draft: faces almost parallel to the pull direction (vertical walls) need ≥ 0.5–1° draft
    nodraft = np.abs(dot) < math.sin(math.radians(0.5))
    area_nd = float(a[nodraft].sum())
    if area_nd > 0.02 * total:
        pts.append(_pt("concern", "draft", f"{area_nd:.0f} mm² ({100 * area_nd / total:.0f} %) of the surface is parallel "
                       "to the mold opening (no draft)", "without draft the part scrapes and sticks as the mold "
                       "opens; textured faces need even more", fix="add 1° draft to walls (2–3° for textures), "
                                                                   "outward from the parting line"))
    else:
        pts.append(_pt("good", "draft", "walls have draft", "the part releases cleanly"))
    # undercuts: faces that cannot be seen from either mold half
    off = 1e-3
    up_hit = np.zeros(len(c), bool)
    dn_hit = np.zeros(len(c), bool)
    for k in range(0, len(c), 4000):
        sl = slice(k, k + 4000)
        o = c[sl] + n[sl] * off
        d_up = np.tile(pull, (len(o), 1))
        hu = tm.ray.intersects_any(o, d_up)
        hd = tm.ray.intersects_any(o, -d_up)
        up_hit[sl], dn_hit[sl] = hu, hd
    # a face is formed by the cavity (+pull side) if it faces +pull and nothing is above it, or by the core if it
    # faces −pull and nothing is below; a face that is blocked on its own side needs a side action
    blocked = ((dot > 0.05) & up_hit) | ((dot < -0.05) & dn_hit)
    area_uc = float(a[blocked].sum())
    if area_uc > 0.005 * total:
        cen = c[blocked].mean(0)
        pts.append(_pt("concern", "undercuts", f"{area_uc:.0f} mm² cannot be reached by either mold half (around "
                       f"{[round(float(x), 1) for x in cen]})", "undercuts need side actions or lifters, which add cost to "
                       "the mold and to every cycle", fix="redesign so every face is visible from one side, or move "
                                                          "the feature into the opening direction"))
    else:
        pts.append(_pt("good", "undercuts", "no undercuts along this opening direction", "a simple two-plate mold"))
    # wall thickness uniformity
    o = c - n * 1e-3
    thick = np.full(len(c), np.nan)
    for k in range(0, len(c), 4000):
        sl = slice(k, k + 4000)
        loc, ir, _ = tm.ray.intersects_location(o[sl], -n[sl], multiple_hits=False)
        if len(ir):
            thick[k + ir] = np.linalg.norm(loc - o[sl][ir], axis=1)
    ok = np.isfinite(thick)
    if ok.any():
        w = a[ok]
        t = thick[ok]
        p10, p50, p90 = (float(np.percentile(np.repeat(t, np.maximum(1, (w / w.mean()).astype(int))), q))
                         for q in (10, 50, 90))
        lvl = "good" if p90 / max(p10, 1e-6) < 1.6 else "suggestion" if p90 / max(p10, 1e-6) < 2.5 else "concern"
        pts.append(_pt(lvl, "walls", f"wall thickness {p10:.1f}–{p90:.1f} mm (median {p50:.1f})",
                       "uneven walls cool unevenly: sink marks over thick areas, warping between thick and thin",
                       fix="" if lvl == "good" else "core out thick sections to the nominal wall; ribs at 50–60 % of "
                                                    "the wall"))
        if p50 < 0.8:
            pts.append(_pt("concern", "walls", f"median wall {p50:.1f} mm", "below ~0.8 mm most plastics do not fill "
                           "the cavity reliably"))
        if p90 > 4.5:
            pts.append(_pt("suggestion", "walls", f"walls up to {p90:.1f} mm", "walls over ~4 mm sink and take long to "
                           "cool; core them out"))
    pts.append(_pt("info", "process", "mold cost", "an aluminium prototype mold for a part this size typically costs "
                   "a few thousand USD and pays off from roughly 500–1000 parts; below that, print or machine it",
                   "rule of thumb"))
    return pts


def review(shape, process: str = "fdm", name: str = "", audit: Optional[Dict] = None, pull=(0, 0, 1)) -> Dict:
    if process == "fdm":
        pts = review_fdm(shape, name, audit)
    elif process in ("injection_molding", "molding"):
        pts = review_molding(shape, pull, name)
    else:
        raise ValueError("process must be fdm or injection_molding")
    order = {"concern": 0, "suggestion": 1, "info": 2, "good": 3}
    pts.sort(key=lambda p: order[p["level"]])
    return {"part": name, "process": process, "summary": {k: sum(p["level"] == k for p in pts) for k in order},
            "points": pts}
