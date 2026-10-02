"""Engineering checks on an RL CAD model. Each finding: {severity, rule, message, refs}; plus a metrics block.

  bed_fit            every printable part fits the printer (best orientation found by search)
  prop_clearance     prop discs clear every airframe part; tip gap and prop position inside the duct
  interference       components vs airframe, components vs components, airframe part vs part
  cg                 centre of gravity vs thrust centre
  propulsion         thrust-to-weight, hover throttle, flight time, current per motor
  arm_stiffness      arm tip deflection and bending stress under full thrust (beam model)
  printability       minimum wall/plate thickness vs nozzle
  mass               mass budget by group
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import Dict, List, Tuple

import numpy as np

from . import calc
from . import catalog as C

E_MPA = {"PETG-CF": 4000.0, "PETG": 2000.0, "PLA": 3300.0, "LW-PLA": 1200.0, "CF": 50000.0}
YIELD_MPA = {"PETG-CF": 50.0, "PETG": 45.0, "PLA": 55.0, "LW-PLA": 20.0, "CF": 500.0}
# pairs that are glued / slotted together and may share a little volume
JOINED = {frozenset(("canopy", "fuselage_nose")), frozenset(("fin_left", "fuselage_tail")),
          frozenset(("fin_right", "fuselage_tail"))}


def _f(sev, rule, msg, refs=()):
    return {"severity": sev, "rule": rule, "message": msg, "refs": list(refs)}


def _verts(shape, tol=0.6):
    from .geom.mesh import mesh
    return mesh(shape, tol, 0.6)[0]


def _min_rect(xy: np.ndarray) -> Tuple[float, float, float]:
    best = None
    for deg in range(0, 180, 2):
        a = math.radians(deg)
        r = xy @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        w, d = np.ptp(r[:, 0]), np.ptp(r[:, 1])
        if best is None or w * d < best[0] * best[1]:
            best = (max(w, d), min(w, d), deg)
    return best


def bed_fit(shape, bed) -> Dict:
    """Search orientations (axis-aligned + principal axes) for the one that fits the bed with the lowest height."""
    v = _verts(shape)
    v = v - v.mean(0)
    _, _, vt = np.linalg.svd(v, full_matrices=False)
    frames = [np.eye(3), np.eye(3)[[1, 2, 0]], np.eye(3)[[2, 0, 1]], vt, vt[[1, 2, 0]], vt[[2, 0, 1]]]
    bx, by, bz = sorted(bed[:2], reverse=True) + [bed[2]]
    best = None
    for fr in frames:
        pts = v @ fr.T
        h = np.ptp(pts[:, 2])
        w, d, ang = _min_rect(pts[:, :2])
        fits = w <= bx and d <= by and h <= bz
        diag_fit = (not fits) and h <= bz and _fits_rotated(pts[:, :2], bed[0], bed[1])
        cand = {"footprint_mm": [round(float(w), 1), round(float(d), 1)], "height_mm": round(float(h), 1),
                "fits": bool(fits or diag_fit), "diagonal": bool(diag_fit)}
        key = (not cand["fits"], h, w * d)
        if best is None or key < best[0]:
            best = (key, cand)
    return best[1]


def _fits_rotated(xy, bx, by):
    for deg in range(0, 180, 1):
        a = math.radians(deg)
        r = xy @ np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
        if np.ptp(r[:, 0]) <= bx and np.ptp(r[:, 1]) <= by:
            return True
    return False


def _inter_vol(a, b) -> float:
    try:
        bba, bbb = a.bounding_box(), b.bounding_box()
        if (bba.max.X < bbb.min.X or bbb.max.X < bba.min.X or bba.max.Y < bbb.min.Y or bbb.max.Y < bba.min.Y
                or bba.max.Z < bbb.min.Z or bbb.max.Z < bba.min.Z):
            return 0.0
        return (a & b).volume
    except Exception:
        return 0.0


def run(model, printer_bed=None, print_audit: bool = True) -> Dict:
    if model.spec.kind == "enclosure":
        from .families.enclosure import run_checks
        return run_checks(model, printer_bed, print_audit)
    from .project import _cyl
    spec, p = model.spec, model.params
    out: List[Dict] = []
    metrics: Dict = {}
    bed = printer_bed or C.PRINTERS[spec.printer]["bed_mm"]
    air = [i for i in model.items if i.kind == "airframe"]
    comps = [i for i in model.items if i.kind == "component" and i.shape is not None]

    # ---------------------------------------------------------------- bed fit
    fit = {}
    for it in model.printable:
        r = bed_fit(it.shape, bed)
        fit[it.name] = r
        if not r["fits"]:
            out.append(_f("error", "bed_fit", f"{it.name} does not fit the {C.PRINTERS[spec.printer]['name']} "
                                              f"({bed[0]}×{bed[1]}×{bed[2]} mm): best {r['footprint_mm'][0]}×"
                                              f"{r['footprint_mm'][1]}×{r['height_mm']} mm — split it or scale", [it.name]))
        elif r["diagonal"]:
            out.append(_f("info", "bed_fit", f"{it.name} fits only diagonally on the bed", [it.name]))
    metrics["print_orientation"] = fit

    # ---------------------------------------------------------------- props
    prop = spec.part("prop")
    tip = p.duct_ri - prop.data["diameter_mm"] / 2
    if tip < 1.0:
        out.append(_f("error", "prop_clearance", f"prop tip gap {tip:.2f} mm < 1.0 mm: printed ducts will be hit"))
    top_ok = p.duct_z0 + 2 <= p.prop_z <= p.duct_z0 + p.duct_depth - p.duct_lip_r
    if not top_ok:
        out.append(_f("warning", "prop_clearance", f"prop plane z={p.prop_z:.1f} mm is not inside the straight part of "
                                                   f"the duct ({p.duct_z0 + 2:.1f}…{p.duct_z0 + p.duct_depth - p.duct_lip_r:.1f})"))
    for it in comps:
        if not it.name.startswith("prop_"):
            continue
        cx, cy = it.cg[0], it.cg[1]
        swept = _cyl(cx, cy, p.prop_z - prop.data.get("hub_h", 7.0) / 2, prop.data["diameter_mm"] / 2 + 0.5,
                     prop.data.get("hub_h", 7.0))
        for a in air:
            v = _inter_vol(swept, a.shape)
            if v > 0.5:
                out.append(_f("error", "prop_clearance", f"{it.name} (swept disc incl. 0.5 mm margin) hits {a.name} "
                                                         f"({v:.1f} mm³)", [it.name, a.name]))
    metrics["prop"] = {"tip_gap_mm": round(tip, 2), "prop_plane_z": p.prop_z,
                       "duct_z": [p.duct_z0, p.duct_z0 + p.duct_depth]}

    # ---------------------------------------------------------------- interference
    for c in comps:
        for a in air:
            v = _inter_vol(c.shape, a.shape)
            if v > 1.0 and not c.name.startswith("prop_"):
                out.append(_f("error", "interference", f"{c.name} overlaps {a.name} by {v:.1f} mm³", [c.name, a.name]))
    for c1, c2 in combinations([c for c in comps if not c.name.startswith("prop_")], 2):
        v = _inter_vol(c1.shape, c2.shape)
        if v > 1.0:
            out.append(_f("error", "interference", f"{c1.name} overlaps {c2.name} by {v:.1f} mm³", [c1.name, c2.name]))
    for a1, a2 in combinations(air, 2):
        v = _inter_vol(a1.shape, a2.shape)
        if v > 1.0:
            joined = frozenset((a1.name, a2.name)) in JOINED
            out.append(_f("info" if joined else "error", "interference",
                          f"{a1.name} and {a2.name} share {v:.1f} mm³" + (" (glued joint)" if joined else ""),
                          [a1.name, a2.name]))

    # ---------------------------------------------------------------- connector access
    from build123d import Box, Pos
    for port in getattr(model, "ports", []):
        ox, oy, oz = port["origin"]
        w, h = port["plug_mm"]
        side = 1 if port["dir"][1] > 0 else -1
        reach = p.fus_half_w + 12 - abs(oy)
        plug = Pos(ox, oy + side * (reach / 2 + 0.5), oz) * Box(w, reach, h)
        blocked = [(a.name, _inter_vol(plug, a.shape)) for a in air]
        blocked = [(n, v) for n, v in blocked if v > 0.5]
        if blocked:
            out.append(_f("error", "connector_access", f"{port['name']}: a {w}×{h} mm plug cannot reach it from outside "
                                                       f"— blocked by {', '.join(n for n, _ in blocked)}", [port["name"]]))
        else:
            out.append(_f("info", "connector_access", f"{port['name']} reachable through the {'left' if side > 0 else 'right'} "
                                                      f"side of the fuselage ({w}×{h} mm plug path clear)", [port["name"]]))

    # ---------------------------------------------------------------- boards from RL PCB (where PCB meets CAD)
    for slot, bd in getattr(model, "boards", {}).items():
        env, fnd = board_envelope(model, slot, bd, air, comps)
        out.extend(fnd)
        metrics.setdefault("boards", {})[slot] = {"envelope": env, "outline_mm": bd["mech"]["outline_mm"]["size"],
                                                   "height_mm": bd["mech"]["height_mm"],
                                                   "mech": bd["mech"].get("path") or bd["mech"].get("source")}

    # ---------------------------------------------------------------- mass & CG
    groups = {}
    for it in model.items:
        g = it.name.split("_")[0] if it.kind == "airframe" else it.name.rstrip("0123456789_")
        groups[g] = groups.get(g, 0.0) + it.mass_g
    mb = calc.mass_budget(list(groups.items()))
    cg = calc.centre_of_gravity([(i.name, i.mass_g, i.cg) for i in model.items])
    auw = mb["total_g"]
    metrics["mass"] = mb
    metrics["cg"] = cg
    dx, dy = cg["cg_mm"][0], cg["cg_mm"][1]
    if abs(dx) > 3.0 or abs(dy) > 1.5:
        out.append(_f("error", "cg", f"CG is {dx:+.1f} mm (x) / {dy:+.1f} mm (y) from the thrust centre; keep within "
                                     "±3 mm or the front/rear motors work unevenly and hover time drops", ["battery"]))
    if cg["cg_mm"][2] > p.prop_z:
        out.append(_f("warning", "cg", f"CG height {cg['cg_mm'][2]:.1f} mm is above the prop plane ({p.prop_z:.1f} mm)"))

    # ---------------------------------------------------------------- propulsion
    pr = calc.propulsion(spec.part("motor").data, prop.data, spec.part("battery").data, 4, auw)
    metrics["propulsion"] = pr
    if pr["thrust_to_weight"] < 2.0:
        out.append(_f("error", "propulsion", f"thrust-to-weight {pr['thrust_to_weight']} < 2: too heavy to fly safely"))
    elif pr["thrust_to_weight"] < 2.8:
        out.append(_f("warning", "propulsion", f"thrust-to-weight {pr['thrust_to_weight']}: flies, little margin"))
    esc = spec.part("esc").data
    if pr["max_current_per_motor_a"] > esc.get("cont_current_a", 99):
        out.append(_f("error", "propulsion", f"max motor current ≈{pr['max_current_per_motor_a']} A exceeds the ESC's "
                                             f"{esc['cont_current_a']} A"))
    bat = spec.part("battery").data
    if pr["battery_c_needed"] > bat.get("c_rating", 999):
        out.append(_f("warning", "propulsion", f"full throttle needs ≈{pr['battery_c_needed']} C, battery is {bat['c_rating']} C"))

    # ---------------------------------------------------------------- arm stiffness (cantilever, T-section)
    mat = spec.materials.get("frame", "PETG")
    e, sy = E_MPA.get(mat, 2000.0), YIELD_MPA.get(mat, 40.0)
    b, h = p.arm_w, p.frame_t
    rw, rh = getattr(p, "rib_w", 0.0), getattr(p, "rib_h", 0.0)
    a1, a2 = b * h, rw * rh
    y1, y2 = h / 2, h + rh / 2
    yc = (a1 * y1 + a2 * y2) / (a1 + a2) if a1 + a2 else y1
    inertia = b * h ** 3 / 12 + a1 * (y1 - yc) ** 2 + rw * rh ** 3 / 12 + a2 * (y2 - yc) ** 2
    cmax = max(yc, h + rh - yc)
    cx, cy = p.duct_centres[0]
    arm_len = math.hypot(cx, cy)
    root = max(p.plate_half_w, 19.5) / (abs(cy) / arm_len)
    L = arm_len - root
    F = pr["max_thrust_per_motor_g"] / 1000 * calc.G
    defl = F * L ** 3 / (3 * e * inertia)
    stress = F * L * cmax / inertia
    m_eff = (spec.part("motor").mass_g + prop.mass_g) / 1000
    k = 3 * e * inertia / L ** 3 * 1000       # N/m
    f_n = math.sqrt(k / m_eff) / (2 * math.pi)
    metrics["arm"] = {"material": mat, "length_mm": round(L, 1), "I_mm4": round(inertia, 1), "tip_deflection_mm": round(defl, 2),
                      "bending_stress_mpa": round(stress, 1), "safety_factor": round(sy / stress, 1) if stress else None,
                      "first_mode_hz": round(f_n), "method": "cantilever: δ = F·L³/(3·E·I), σ = F·L·c/I, f = √(k/m)/2π"}
    if defl > 1.0:
        out.append(_f("warning", "arm_stiffness", f"arms deflect {defl:.2f} mm at full thrust ({mat}); stiffer arms reduce "
                                                  "vibration and oscillation — thicker ribs or a carbon frame (DXF export)",
                      ["frame"]))
    if stress and sy / stress < 2.5:
        out.append(_f("error", "arm_stiffness", f"arm bending stress {stress:.1f} MPa, safety factor {sy / stress:.1f} < 2.5",
                      ["frame"]))
    # what a 3 mm carbon plate (flat arms, no ribs — cut from the frame DXF) would give, for comparison
    i_cf = b * 3.0 ** 3 / 12
    k_cf = 3 * E_MPA["CF"] * i_cf / L ** 3 * 1000
    f_cf = math.sqrt(k_cf / m_eff) / (2 * math.pi)
    metrics["arm"]["carbon_3mm_alternative"] = {"tip_deflection_mm": round(F * L ** 3 / (3 * E_MPA["CF"] * i_cf), 2),
                                                "first_mode_hz": round(f_cf)}
    if f_n < 150:
        out.append(_f("warning", "arm_stiffness", f"arm first bending mode ≈{f_n:.0f} Hz is low; gyro noise filtering "
                                                  f"will have to work hard. Options: print the frame in PETG-CF/PA-CF, or "
                                                  f"cut it from 3 mm carbon plate (frame.dxf; ≈{f_cf:.0f} Hz)", ["frame"]))

    # ---------------------------------------------------------------- bought parts: fit and power
    out += _parts_fit(model, air, metrics)

    # ---------------------------------------------------------------- printability
    from .geom.mesh import mesh
    for it in model.printable:
        n_sol = len(it.shape.solids())
        if n_sol != 1:
            out.append(_f("error", "solid", f"{it.name} is {n_sol} separate bodies; a printed part must be one solid "
                                            "(a feature is floating or a cut split it)", [it.name]))
        if not it.shape.is_valid:
            out.append(_f("error", "solid", f"{it.name} has invalid B-rep geometry (export/print may fail)", [it.name]))
        if mesh(it.shape, 0.5, 0.6)[2]:
            out.append(_f("error", "solid", f"{it.name} has faces that cannot be triangulated (STL export would have "
                                            "holes)", [it.name]))
    for name, val, lim in (("skin_t", p.skin_t, 0.8), ("wing_t", p.wing_t, 1.2), ("duct_wall", p.duct_wall, 1.2),
                           ("frame_t", p.frame_t, 2.0)):
        if val < lim:
            out.append(_f("warning", "printability", f"{name} = {val} mm is thin for a 0.4 mm nozzle (min ≈{lim} mm)"))
    if print_audit:
        out += _print_audit(model, bed, metrics)

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda f: order[f["severity"]])
    summary = {s: sum(1 for f in out if f["severity"] == s) for s in ("error", "warning", "info")}
    return {"summary": summary, "findings": out, "metrics": metrics, "notes": model.notes}


# -------------------------------------------------------------------------------------------- board integration
def _section_inner(p, x0=None, x1=None):
    """Fuselage interior over the stretch x0..x1 (default: the centre shell): the smallest inner half-width at
    height z, and the lowest inner roof over lateral offset y, taken from the real (spline) sections."""
    from .geom.airframe import half_width_at, roof_z_at
    a, b = p.plate_x if x0 is None else (x0, x1)
    xs = [a + (b - a) * i / 6 for i in range(7)]
    t = p.skin_t + 0.2            # skin plus the loft's small deviation from the station splines

    def half_width(z):
        return min(half_width_at(p, x, z) for x in xs) - t

    def roof(y):
        return min(roof_z_at(p, x, y) for x in xs) - t
    return half_width, roof


def _parts_fit(model, air, metrics) -> List[Dict]:
    """The airframe against the datasheets of the parts it is built around: prop on the motor shaft, motor on its
    pad and screws, the battery at the top of its size tolerance, and the power chain (motor, ESC, battery, XT30)."""
    from .project import _cyl
    spec, p = model.spec, model.params
    motor, prop, esc, bat, fc = (spec.part(r) for r in ("motor", "prop", "esc", "battery", "fc"))
    md, pd, ed, bd = motor.data, prop.data, esc.data, bat.data
    out, m = [], {}
    # prop ↔ motor shaft
    bore, shaft = pd.get("bore_d"), md.get("shaft_d")
    if bore and shaft and abs(bore - shaft) > 0.05:
        out.append(_f("error", "prop_fit", f"{prop.name} has a {bore} mm bore but {motor.name} has a {shaft} mm shaft",
                      ["prop", "motor"]))
    elif bore and shaft:
        out.append(_f("info", "prop_fit", f"prop bore {bore} mm = motor shaft {shaft} mm; hub ({pd.get('hub_h')} mm) "
                                          f"sits on the bell at z {p.frame_t + md['height']:.1f} mm, prop plane "
                                          f"z {p.prop_z:.2f} mm", ["prop", "motor"]))
    # motor ↔ frame: pad covers the base, screw length
    pad_r = p.motor_base_d / 2 + 2.5
    if md.get("base_d", 0) / 2 > pad_r:
        out.append(_f("error", "motor_fit", "motor base is wider than the frame's motor pad", ["frame", "motor"]))
    screw = p.frame_t + 2.5
    m["motor_screw"] = {"length_mm": math.ceil(screw), "note": f"{md.get('mount_screw', 'M2')}×{math.ceil(screw)}: "
                        f"{p.frame_t} mm plate + ≈2.5 mm into the motor base"}
    # motor leads reach the ESC pads (routed along the arm, down through the fuselage window, to the nearest pad edge)
    lead = md.get("lead_mm")
    if lead:
        ex, ew = p.stack_x, spec.part("esc").envelope_mm[0] / 2
        need = max(math.hypot(abs(cx - ex) - ew * 0.6, abs(cy) - ew * 0.6) for cx, cy in p.duct_centres) + 15.0
        if lead < need:
            out.append(_f("warning", "motor_leads", f"motor leads ({lead} mm) are shorter than the ≈{need:.0f} mm run "
                                                    "to the ESC pads; extend them", ["motor", "esc"]))
        else:
            out.append(_f("info", "motor_leads", f"motor leads {lead} mm ≥ ≈{need:.0f} mm to the ESC pads "
                                                 "(trim to length)", ["motor", "esc"]))
    # battery at the upper size tolerance
    emax = bd.get("envelope_max_mm")
    if emax:
        b = model.item("battery")
        bx = b.cg[0]
        big = _box_at(bx, 0, p.frame_t, emax)
        hit = [a.name for a in air if _inter_vol(big, a.shape) > 1.0]
        L = emax[0]
        if hit:
            out.append(_f("warning", "battery_fit", f"a pack at the top of its tolerance ({emax[0]}×{emax[1]}×{emax[2]} "
                                                    f"mm) would touch {', '.join(hit)}; measure yours", ["battery"] + hit))
        else:
            out.append(_f("info", "battery_fit", f"{bat.name}: fits at its nominal size and at the upper tolerance "
                                                 f"({emax[0]}×{emax[1]}×{emax[2]} mm)", ["battery"]))
    # power chain
    pr = metrics.get("propulsion", {})
    i_motor = pr.get("max_current_per_motor_a", 0)
    i_total = i_motor * 4
    cont = ed.get("cont_current_a")
    if cont and max(i_motor, md.get("max_current_a", 0)) > cont:
        out.append(_f("error", "power_esc", f"{esc.name} ({cont} A) is below the motor current "
                                            f"({max(i_motor, md.get('max_current_a', 0))} A)", ["esc", "motor"]))
    elif cont:
        out.append(_f("info", "power_esc", f"ESC {cont} A per motor ≥ estimated {i_motor} A at full throttle and the "
                                           f"motor's {md.get('max_current_a')} A rating (peak {md.get('peak_current_a')} A)",
                      ["esc", "motor"]))
    cap_a = bd.get("capacity_mah", 0) / 1000 * bd.get("c_rating", 0)
    if cap_a and i_total > cap_a:
        out.append(_f("warning", "power_battery", f"full throttle ≈{i_total:.0f} A exceeds the pack's "
                                                  f"{cap_a:.0f} A rating", ["battery"]))
    elif cap_a:
        out.append(_f("info", "power_battery", f"full throttle ≈{i_total:.0f} A ≤ {cap_a:.0f} A "
                                               f"({bd['capacity_mah']} mAh × {bd['c_rating']}C)", ["battery"]))
    xt = C.get("xt30_pair").data if bd.get("connector") == "XT30" else None
    if xt and i_total > xt["burst_current_a"]:
        out.append(_f("warning", "power_connector", f"full throttle ≈{i_total:.0f} A is above the XT30's "
                                                    f"{xt['burst_current_a']} A burst rating", ["battery"]))
    elif xt:
        out.append(_f("info", "power_connector", f"XT30: {xt['cont_current_a']} A continuous / {xt['burst_current_a']} A "
                                                 f"burst; hover ≈{pr.get('hover_current_a')} A, full throttle "
                                                 f"≈{i_total:.0f} A in short bursts", ["battery"]))
    for part, lab in ((motor, "motor"), (esc, "ESC")):
        cells = part.data.get("cells")
        if cells and not (cells[0] <= bd.get("cells", 0) <= cells[-1]):
            out.append(_f("error", "power_voltage", f"{lab} {part.name} is rated {cells[0]}–{cells[-1]}S; the battery "
                                                    f"is {bd.get('cells')}S", [lab.lower()]))
    metrics["parts_fit"] = m
    return out


def _box_at(cx, cy, z0, env):
    from build123d import Align, Box, Pos
    return Pos(cx, cy, z0) * Box(*env, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _print_audit(model, bed, metrics) -> List[Dict]:
    """Slice-level audit of every printed part in the orientation it is exported in (see printcheck.py)."""
    try:
        import trimesh  # noqa: F401
    except ImportError:
        return [_f("info", "print_audit", "print audit skipped: install trimesh (pip install trimesh) to check wall "
                                          "thickness, overhangs and bed contact of the STL files")]
    from .export import placed_for_print
    from .printcheck import audit_shape, findings as print_findings
    res, out = {}, []
    for it in model.printable:
        placed, inf = placed_for_print(model, it, bed)
        r = audit_shape(placed, it.name)
        r["orientation"] = inf["orientation"]
        res[it.name] = r
    for sev, rule, msg, refs in print_findings(res):
        out.append(_f(sev, rule, msg, refs))
    metrics["print_audit"] = {n: {k: r[k] for k in ("orientation", "watertight", "min_thickness_mm", "thin_area_mm2",
                                                   "knife_area_mm2", "overhang_area_mm2", "bed_contact_mm2",
                                                   "height_mm")} | {"bridges": r.get("bridges", [])[:2]}
                              for n, r in res.items()}
    if not out:
        out.append(_f("info", "print_audit", f"all {len(res)} printed parts: closed meshes, walls ≥ 2 lines except "
                                             "small areas, no overhang that needs support, flat on the bed"))
    return out


def board_envelope(model, slot, bd, air, comps):
    """Check an RL PCB board in its slot and derive the envelope (rl-envelope/1) the product gives it."""
    from build123d import Box, Pos
    p, spec = model.params, model.spec
    mech = bd["mech"]
    cx, cy = bd["centre"]
    zb = bd["z_bottom"]
    rot = bd.get("rotation", 0)
    t = mech["thickness_mm"]
    w, l = mech["outline_mm"]["size"]
    if rot % 180:
        w, l = l, w
    htop, hbot = mech["height_mm"]["top"], mech["height_mm"]["bottom"]
    half_width, roof = _section_inner(p)
    out = []
    ref = [f"{slot}"]

    # mounting pattern (square, centred)
    pat = p.stack_pattern
    holes = mech.get("mounting_holes", [])
    want = [(sx * pat / 2, sy * pat / 2) for sx in (-1, 1) for sy in (-1, 1)]
    miss = [c for c in want if not any(abs(h["at_mm"][0] - c[0]) < 0.25 and abs(h["at_mm"][1] - c[1]) < 0.25 for h in holes)]
    if miss:
        out.append(_f("error", "board_mount", f"{slot}: the board's mounting holes do not match the {pat} mm stack pattern "
                                              f"(holes at {[h['at_mm'] for h in holes][:4]})", ref))
    else:
        out.append(_f("info", "board_mount", f"{slot}: 4 holes on the {pat} mm stack pattern "
                                             f"(Ø{min(h['drill_mm'] for h in holes)} mm)", ref))
    # vertical: below = gap to the ESC, above = fuselage roof over the board's footprint
    esc = spec.part("esc")
    gap = zb - (p.frame_t + 3.0 + esc.envelope_mm[2])
    ko_bottom = round(gap - 0.3, 2)
    worst_roof = min(roof(cy + l / 2), roof(cy - l / 2))
    ko_top = round(worst_roof - 0.5 - (zb + t), 2)
    tall_b = [c for c in mech["components"] if c["side"] == "bottom" and c["height_mm"] > ko_bottom]
    if tall_b:
        out.append(_f("error", "board_height", f"{slot}: bottom-side parts reach the ESC ({ko_bottom} mm free): "
                                               + ", ".join(f"{c['ref']} {c['height_mm']} mm" for c in tall_b[:5]), ref))
    tall_t = [c for c in mech["components"] if c["side"] == "top" and c["height_mm"] > ko_top]
    if tall_t:
        out.append(_f("error", "board_height", f"{slot}: top-side parts hit the fuselage roof ({ko_top} mm free): "
                                               + ", ".join(f"{c['ref']} {c['height_mm']} mm" for c in tall_t[:5]), ref))
    if not tall_b and not tall_t:
        out.append(_f("info", "board_height", f"{slot}: parts {hbot} mm below / {htop} mm above the board; space is "
                                              f"{ko_bottom} mm to the ESC and {ko_top} mm to the roof", ref))
    # lateral fit inside the centre shell at the board's height
    hw = min(half_width(zb - hbot), half_width(zb + t + htop))
    if l / 2 > hw - 0.3:
        out.append(_f("error", "board_fit", f"{slot}: board is {l} mm wide across the fuselage; the shell leaves "
                                            f"{2 * (hw - 0.3):.1f} mm at that height", ref))
    # free length along x: nearest other part overlapping the board's height band
    z0, z1 = zb - hbot, zb + t + htop
    front, back = p.plate_x[1] - cx, cx - p.plate_x[0]
    for c in comps:
        if c.name in ("fc",) or c.name.startswith(("prop_", "motor_")):
            continue
        bb = c.shape.bounding_box()
        if bb.max.Z <= z0 or bb.min.Z >= z1 or bb.max.Y < -l / 2 or bb.min.Y > l / 2:
            continue
        if bb.min.X >= cx:
            front = min(front, bb.min.X - cx)
        elif bb.max.X <= cx:
            back = min(back, cx - bb.max.X)
    max_len = round(2 * min(front, back) - 1.0, 1)
    if w > max_len:
        out.append(_f("error", "board_fit", f"{slot}: board is {w} mm long; neighbours leave {max_len} mm", ref))
    # which board edges can reach outside (the centre shell can get a hole; nothing else may be in the way)
    reach = []
    others = [a for a in air if a.name != "fuselage_centre"] + [c for c in comps if c.name not in ("fc",)]
    # the nose and tail are hollow: a path running inside them is not "outside", so use their solid outer bodies
    try:
        from build123d import loft
        from .geom.airframe import _section, _stations
        outer = loft([_section(p, x, sc, zz) for x, sc, zz in _stations(p)])
        big = 500
        for nm, sx in (("nose (solid)", p.plate_x[1] + big / 2), ("tail (solid)", p.plate_x[0] - big / 2)):
            class _O:
                pass
            o = _O()
            o.name, o.shape = nm, outer & Pos(sx, 0, 0) * Box(big, big, big)
            others.append(o)
    except Exception:
        pass
    for edge, (dx, dy) in (("+x", (1, 0)), ("-x", (-1, 0)), ("+y", (0, 1)), ("-y", (0, -1))):
        ex, ey = cx + dx * (w / 2), cy + dy * (l / 2)
        L = 60.0
        box = Pos(ex + dx * L / 2, ey + dy * L / 2, zb + t + 1.8) * Box(abs(dx) * L + abs(dy) * 12.5,
                                                                      abs(dy) * L + abs(dx) * 12.5, 7.0)
        if not any(_inter_vol(box, o.shape) > 0.5 for o in others):
            reach.append(edge)
    req = []
    for port in model.ports:
        if "usb" in port["name"]:
            req.append({"mate": "usb-c", "why": "flight-controller configuration from outside the airframe",
                        "via_extension": bool(port.get("extension")), "edges": reach})
    env = {"schema": "rl-envelope/1", "product": spec.name, "slot": slot, "generated_by": "RL CAD",
           "frame": "board frame of rl-mech/1 (origin outline centre, +y = KiCad top edge)",
           "rotation_deg": rot,
           "max_outline_mm": [max_len, round(2 * (hw - 0.3), 1)],
           "mount_pattern_mm": pat, "mount_hole_d_mm": 3.0,
           "keepout_height_mm": {"top": ko_top, "bottom": ko_bottom},
           "reachable_edges": reach, "required_ports": req,
           "notes": [f"stack at x = {cx} mm; board bottom face at z = {round(zb, 2)} mm in the airframe"]}
    if not reach and any(not r["via_extension"] for r in req):
        out.append(_f("error", "board_ports", f"{slot}: no board edge can reach outside the airframe; bring the USB-C "
                                              "out with an extension (usb_port) or move/rotate the board", ref))
    return env, out
