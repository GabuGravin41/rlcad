"""Exports: STEP assembly (named, coloured parts — opens in Onshape, FreeCAD, Fusion, SolidWorks), one STEP and one
print-oriented STL per printed part, the frame outline as DXF (for CNC carbon), BOM (CSV + Markdown), a JSON
design record and a Markdown report.

Everything is written into <folder>/out/ so the design folder stays tidy:
    out/assembly.step          whole aircraft, one named body per part, components included
    out/parts/<name>.step      each printed part on its own (edit in CAD)
    out/print/<name>.stl       each printed part laid flat for the slicer
    out/frame.dxf              frame outline at mid-thickness (carbon plate alternative)
    out/bom.csv, out/bom.md    what to buy and what to print
    out/design.json            spec + checks + metrics (machine-readable)
    out/report.md              human-readable summary
    out/render.png             four-view render
"""
from __future__ import annotations

import copy
import csv
import json
import math
import os
from typing import Dict, List, Optional

from . import catalog as C


def _outdir(folder: str, *sub) -> str:
    d = os.path.join(folder, "out", *sub)
    os.makedirs(d, exist_ok=True)
    return d


# ------------------------------------------------------------------------------------------- STEP
def step_assembly(model, path: str, include_components: bool = True) -> str:
    from build123d import Color, Compound, export_step
    children = []
    for it in model.items:
        if it.shape is None or (it.kind == "component" and not include_components):
            continue
        sh = copy.copy(it.shape)          # a Compound adopts its children; keep the model's shapes untouched
        sh.label = it.name
        sh.color = Color(*it.colour)
        children.append(sh)
    asm = Compound(label=model.spec.name or "assembly", children=children)
    export_step(asm, path)
    return path


def step_parts(model, folder: str) -> List[str]:
    from build123d import export_step
    out = []
    d = _outdir(folder, "parts")
    for it in model.printable:
        p = os.path.join(d, f"{it.name}.step")
        sh = copy.copy(print_shape(model, it))
        sh.label = it.name
        export_step(sh, p)
        out.append(p)
    names = {f"{it.name}.step" for it in model.printable}
    for f in os.listdir(d):
        if f.endswith(".step") and f not in names:
            os.remove(os.path.join(d, f))
    return out


# ------------------------------------------------------------------------------------------- print orientation
def _candidates(shape=None):
    """Orientations to try: each face of the bounding box down, plus each large flat face of the part down (so a
    canted fin can lie on its flat side)."""
    from build123d import Rot, Vector
    # Rot(0, -90, 0) takes +x to +z, so the part's -x end lands on the bed (and Rot(0, 90, 0) the +x end)
    c = {"as modelled": Rot(0, 0, 0), "standing on its aft face (-x down)": Rot(0, -90, 0), "standing on its forward face (+x down)": Rot(0, 90, 0),
         "on its left side (+y down)": Rot(90, 0, 0), "on its right side (-y down)": Rot(-90, 0, 0), "upside down": Rot(180, 0, 0)}
    if shape is not None:
        planar = [f for f in shape.faces() if f.geom_type.name == "PLANE"]
        planar.sort(key=lambda f: -f.area)
        for i, f in enumerate(planar[:4]):
            n = f.normal_at()
            if abs(abs(n.Z) - 1) < 1e-6 or abs(abs(n.X) - 1) < 1e-6 or abs(abs(n.Y) - 1) < 1e-6:
                continue                      # already covered by a box face
            # rotation taking n to -Z
            axis = n.cross(Vector(0, 0, -1))
            ang = math.degrees(math.acos(max(-1.0, min(1.0, -n.Z))))
            from build123d import Location
            c["lying on its flat side" if i == 0 else f"on flat face {i + 1}"] = Location((0, 0, 0), (axis.X, axis.Y, axis.Z), ang) if axis.length > 1e-9 \
                else Rot(0, 0, 0)
    return c


def support_stats(shape, tol: float = 0.6, overhang_deg: float = 45.0):
    """(overhang area needing support, bed contact area, height) of a shape as it sits (z up, lowest point = bed)."""
    import numpy as np
    from .geom.mesh import mesh
    v, t, _ = mesh(shape, tol, 0.6)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    nrm = np.cross(b - a, c - a)
    area = np.linalg.norm(nrm, axis=1) / 2
    nz = nrm[:, 2] / np.maximum(np.linalg.norm(nrm, axis=1), 1e-12)
    cz = (a[:, 2] + b[:, 2] + c[:, 2]) / 3
    zmin = v[:, 2].min()
    over = (nz < -math.cos(math.radians(overhang_deg))) & (cz > zmin + 0.3)
    bed = (nz < -0.99) & (cz < zmin + 0.05)
    return float(area[over].sum()), float(area[bed].sum()), float(v[:, 2].max() - zmin)


def print_orientation(shape, bed, prefer: Optional[str] = None):
    """Choose how a part sits on the bed: it must fit; then least support, then most bed contact, then lowest.
    A known-good orientation for the part (`prefer`) wins if it fits. Returns (placed_shape, info)."""
    import numpy as np
    from build123d import Pos, Rot
    from .checks import _min_rect
    from .geom.mesh import mesh
    best = None
    cands = _candidates(shape)
    if prefer in cands:                      # a known-good orientation: use it if it fits, skip the search
        cands = {prefer: cands[prefer], **{k: v for k, v in cands.items() if k != prefer}}
    for name, r in cands.items():
        s = r * shape
        v = mesh(s, 0.8, 0.8)[0]
        h = float(np.ptp(v[:, 2]))
        w, dpt, ang = _min_rect(v[:, :2])
        fits = w <= max(bed[:2]) and dpt <= min(bed[:2]) and h <= bed[2]
        over, contact, _ = support_stats(s)
        key = (not fits, 0 if name == prefer else 1, round(over / 100), -round(contact / 100), round(h))
        if best is None or key < best[0]:
            best = (key, name, r, ang, fits, over, contact)
        if name == prefer and fits:
            break
    _, name, r, ang, fits, over, contact = best
    s = Rot(0, 0, -ang) * (r * shape)
    bb = s.bounding_box()
    if bb.size.X < bb.size.Y:
        s = Rot(0, 0, 90) * s
        bb = s.bounding_box()
    s = Pos(bed[0] / 2 - bb.center().X, bed[1] / 2 - bb.center().Y, -bb.min.Z) * s
    bb = s.bounding_box()
    return s, {"orientation": name, "footprint_mm": [round(bb.size.X, 1), round(bb.size.Y, 1)],
               "height_mm": round(bb.size.Z, 1), "fits": bool(fits), "support_area_mm2": round(over),
               "bed_contact_mm2": round(contact)}


# Parts whose print orientation is chosen by design. The fuselage pieces stand on a cut face: their walls are then
# vertical, the cavity closures are steep cones, and nothing needs support inside a closed shell.
PREFERRED = {"fuselage_nose": "standing on its aft face (-x down)", "fuselage_tail": "standing on its forward face (+x down)",
             "fuselage_centre": "standing on its aft face (-x down)", "frame": "as modelled",
             "pod_front_left": "as modelled", "pod_front_right": "as modelled", "pod_rear_left": "as modelled",
             "pod_rear_right": "as modelled", "fin_left": "lying on its flat side", "fin_right": "lying on its flat side",
             "base": "as modelled", "lid": "upside down"}

# Items printed as part of another part (same print; a second colour by filament change / AMS, or paint).
PRINT_WITH = {"fuselage_nose": ["canopy"]}


def placed_for_print(model, it, bed):
    """(placed shape, info) for a printable item, cached on the model (checks and export both need it)."""
    cache = model.__dict__.setdefault("_print_cache", {})
    key = (it.name, tuple(bed))
    if key not in cache:
        cache[key] = print_orientation(print_shape(model, it), bed, PREFERRED.get(it.name))
    placed, inf = cache[key]
    return placed, dict(inf)


def print_shape(model, it):
    """The solid that is actually printed for a printable item (with any parts printed together with it)."""
    sh = it.shape
    for extra in PRINT_WITH.get(it.name, []):
        try:
            sh = sh + model.item(extra).shape
        except StopIteration:
            pass
    return sh


def stl_parts(model, folder: str) -> Dict[str, Dict]:
    from build123d import export_stl
    bed = C.PRINTERS[model.spec.printer]["bed_mm"]
    d = _outdir(folder, "print")
    info = {}
    for it in model.printable:
        placed, inf = placed_for_print(model, it, bed)
        path = os.path.join(d, f"{it.name}.stl")
        export_stl(placed, path, tolerance=0.02, angular_tolerance=0.2)
        extra_g = sum(model.item(e).mass_g for e in PRINT_WITH.get(it.name, []) if any(i.name == e for i in model.items))
        inf.update(path=path, material=it.material, mass_g=round(it.mass_g + extra_g, 1))
        info[it.name] = inf
    for f in os.listdir(d):                      # drop files of parts that are no longer printed on their own
        if f.endswith(".stl") and f[:-4] not in info:
            os.remove(os.path.join(d, f))
    return info


# ------------------------------------------------------------------------------------------- DXF
def frame_dxf(model, path: str) -> str:
    """Frame outline (plate + arms + all holes) at mid-plate height, 1:1 mm, for waterjet/CNC carbon."""
    from build123d import ExportDXF, Plane, Pos, Unit, section
    fr = model.item("frame").shape
    z = model.params.frame_t / 2
    sec = Pos(0, 0, -z) * section(fr, section_by=Plane.XY.offset(z))
    ex = ExportDXF(unit=Unit.MM)
    ex.add_layer("outline")
    ex.add_shape(sec, layer="outline")
    ex.write(path)
    return path


# ------------------------------------------------------------------------------------------- BOM
def bom(model, prints: Optional[Dict] = None) -> List[Dict]:
    spec = model.spec
    rows = []
    qty = {"motor": 4, "prop": 4, "esc": 1, "fc": 1, "receiver": 1, "battery": 1}
    for role in ("fc", "esc", "motor", "prop", "receiver", "battery"):
        p = spec.part(role)
        rows.append({"type": "buy" if role != "fc" else "make (RL PCB)", "role": role, "item": p.name, "qty": qty[role] * (2 if role == "prop" else 1),
                     "mass_g_each": p.mass_g, "source": p.source, "notes": p.data.get("notes", "") if isinstance(p.data, dict) else ""})
    rows[-3]["notes"] = (rows[-3]["notes"] + "; 4 + 4 spares, 2 CW + 2 CCW").strip("; ")
    rows.append({"type": "buy", "role": "fasteners", "item": "M2×6 self-tapping (skin, pods) ×12; M2×5 motor screws ×16; "
                 "M3×20 stack standoffs/screws ×4; M3 silicone grommets ×4", "qty": 1, "mass_g_each": 6.0, "source": "", "notes": ""})
    if any(i.name == "usb_c_panel_ext" for i in model.items):
        e = C.get("usb_c_panel_ext")
        rows.append({"type": "buy", "role": "usb extension", "item": e.name, "qty": 1, "mass_g_each": e.mass_g,
                     "source": e.source, "notes": "FC J2 → socket in the left side of the centre shell (x = "
                                                   f"{model.params.usb_port[0]} mm); glue the socket in its opening"})
    rows.append({"type": "buy", "role": "battery strap", "item": "12 mm Velcro strap, 200 mm ×2", "qty": 2, "mass_g_each": 1.0,
                 "source": "", "notes": "through the frame strap slots"})
    for it in model.printable:
        pr = (prints or {}).get(it.name, {})
        rows.append({"type": "print", "role": it.role, "item": it.name + (" (+ " + ", ".join(PRINT_WITH[it.name]) + ")"
                                                                            if it.name in PRINT_WITH else ""),
                     "qty": 1, "mass_g_each": pr.get("mass_g", round(it.mass_g, 1)),
                     "source": f"out/print/{it.name}.stl", "notes": f"{it.material}" + (
                         f", {pr['orientation']}, {pr['footprint_mm'][0]}×{pr['footprint_mm'][1]}×{pr['height_mm']} mm"
                         if pr else "")})
    return rows


def write_bom(rows: List[Dict], folder: str):
    d = _outdir(folder)
    cp = os.path.join(d, "bom.csv")
    with open(cp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    mp = os.path.join(d, "bom.md")
    with open(mp, "w", encoding="utf-8") as f:
        f.write("| Type | Role | Item | Qty | Mass each (g) | Source | Notes |\n|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['type']} | {r['role']} | {r['item']} | {r['qty']} | {r['mass_g_each']} | {r['source']} | {r['notes']} |\n")
    return cp, mp


# ------------------------------------------------------------------------------------------- report
def report_md(model, result: Dict, prints: Dict, path: str) -> str:
    spec, m = model.spec, result["metrics"]
    pr, arm, cg = m["propulsion"], m["arm"], m["cg"]
    mat_g: Dict[str, float] = {}
    for it in model.printable:
        mat_g[it.material] = mat_g.get(it.material, 0) + it.mass_g
    L = [f"# {spec.name}: design report", "",
         f"Kind: {spec.kind}. Printer: {C.PRINTERS[spec.printer]['name']} "
         f"({'×'.join(str(x) for x in C.PRINTERS[spec.printer]['bed_mm'])} mm).", "",
         "## Checks", "",
         f"{result['summary']['error']} errors, {result['summary']['warning']} warnings, {result['summary']['info']} notes.", ""]
    for f in result["findings"]:
        L.append(f"- **{f['severity']}** ({f['rule']}): {f['message']}")
    L += ["", "## Flight performance (estimate)", "",
          f"- All-up weight: {m['mass']['total_g']} g",
          f"- Max thrust: {pr['total_max_thrust_g']} g ({pr['max_thrust_per_motor_g']} g per motor); thrust-to-weight {pr['thrust_to_weight']}",
          f"- Hover: ≈{pr['hover_throttle_est_pct']} % throttle, {pr['hover_current_a']} A, ≈{pr['hover_flight_time_min']} min",
          f"- Max current per motor ≈{pr['max_current_per_motor_a']} A; battery needs ≈{pr['battery_c_needed']} C",
          f"- Method: {pr['method']}", ""]
    L += ["Assumptions: " + " ".join(pr["caveats"]), "",
          "## Mass and balance", "", "| Group | g | % |", "|---|---|---|"]
    for r in m["mass"]["items"]:
        L.append(f"| {r['name']} | {r['mass_g']} | {r['pct']} |")
    L += ["", f"CG at x {cg['cg_mm'][0]}, y {cg['cg_mm'][1]}, z {cg['cg_mm'][2]} mm (thrust centre is x 0, y 0).", "",
          "## Frame arms", "",
          f"{arm['material']}, cantilever length {arm['length_mm']} mm: tip deflection {arm['tip_deflection_mm']} mm at full "
          f"thrust, stress {arm['bending_stress_mpa']} MPa (safety factor {arm['safety_factor']}), first mode ≈{arm['first_mode_hz']} Hz. "
          f"A 3 mm carbon plate cut from frame.dxf: {arm['carbon_3mm_alternative']['tip_deflection_mm']} mm, "
          f"≈{arm['carbon_3mm_alternative']['first_mode_hz']} Hz.", "",
          "## Printing", "",
          "Every STL in print/ is already in its print orientation: load it and slice without rotating it.", "",
          "| Part | Material | g | Orientation | Size on bed (mm) | Supports | Brim |", "|---|---|---|---|---|---|---|"]
    audit = result["metrics"].get("print_audit", {})
    for name, p in prints.items():
        a = audit.get(name, {})
        sup = "none" if a.get("overhang_area_mm2", p.get("support_area_mm2", 0)) < 30 else \
            f"{a.get('overhang_area_mm2', p.get('support_area_mm2'))} mm²"
        brim = "yes" if p["height_mm"] > 40 and p.get("bed_contact_mm2", 1e9) < 600 else "no"
        extra = " + canopy" if name in PRINT_WITH else ""
        L.append(f"| {name}{extra} | {p['material']} | {p['mass_g']} | {p['orientation']} | "
                 f"{p['footprint_mm'][0]}×{p['footprint_mm'][1]}×{p['height_mm']} | {sup} | {brim} |")
    L += ["", "Filament (parts only, no supports/waste): " + ", ".join(f"{k} {v:.0f} g" for k, v in mat_g.items()), "",
          "How the parts are made to print without support (the print_audit check verifies it on these STLs):", "",
          "- Duct pods stand on the duct exit, which ends in a flat land, and the wing or tail panel has a flat underside "
          "in the same plane, so the whole pod starts on the bed. The panels' airfoil sections have blunt leading and "
          "trailing edges (0.8 mm and 0.9 mm), two lines wide.",
          "- Fins are plano-convex and print lying on their flat side, with the tab.",
          "- The fuselage pieces stand on their cut faces. Their walls are then vertical; the nose cavity closes in a "
          "steep dome under a solid tip; the tail converges onto the nozzle, so its end wall is a short bridge "
          "(about 16 mm). The two front screw bosses in the centre shell sit on 45° gussets.",
          "- The canopy is printed as part of the nose (a hollow shell open to the nose cavity). For a second colour, "
          "use a filament change or the AMS at the canopy's height, or paint it.", "",
          "Settings: frame in PETG (or PETG-CF), 4 walls, 40 % gyroid. Skin parts in LW-PLA (foaming) with 2 walls, "
          "or regular PLA with 2 walls (heavier: about twice the skin mass). Layer height 0.2 mm. Use a brim where the "
          "table says so: the tall shells stand on a narrow edge.", "",
          "## Assembly order", "",
          "1. Press the M3 grommets into the frame stack holes; mount motors (M2×5, check screws do not touch windings).",
          "2. Solder motors to the 4-in-1 ESC, mount ESC then FC on the stack (arrow forward), receiver ahead of the stack.",
          "3. Strap the battery through the slots; check the CG sits on the frame centre mark (x 0).",
          "4. Screw the four duct pods onto the arm posts (M2 from below). Spin each motor by hand: nothing may touch.",
          "5. Slide nose and tail onto the centre shell collars (glue), fit the fins into the tail slots (glue).",
          "6. Plug the USB-C extension into the FC and glue its socket into the opening in the centre shell's left side.",
          "7. Place the centre shell over the frame (the arms pass through the windows in its sides) and screw it "
          "down (4× M2 from below into the bosses).", ""]
    if model.notes:
        L += ["## Notes", ""] + [f"- {n}" for n in model.notes] + [""]
    L += ["## Files", "", "- assembly.step: whole aircraft (named parts) — import into Onshape/FreeCAD/Fusion",
          "- parts/*.step: each printed part for editing", "- print/*.stl: laid out for the slicer",
          "- frame.dxf: frame outline for a carbon plate", "- bom.csv / bom.md, design.json, render.png", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path


def export_all(model, result: Dict, folder: str, render: bool = True) -> Dict:
    d = _outdir(folder)
    files = {"assembly_step": step_assembly(model, os.path.join(d, "assembly.step"))}
    files["part_steps"] = step_parts(model, folder)
    prints = stl_parts(model, folder)
    files["stls"] = [p["path"] for p in prints.values()]
    try:
        files["frame_dxf"] = frame_dxf(model, os.path.join(d, "frame.dxf"))
    except Exception as e:  # noqa
        files["frame_dxf_error"] = str(e)
    enc = model.spec.kind == "enclosure"
    if enc:
        from .families.enclosure import bom_rows, report as enc_report
        files.pop("frame_dxf", None)
        files.pop("frame_dxf_error", None)
    rows = bom_rows(model, prints) if enc else bom(model, prints)
    files["bom_csv"], files["bom_md"] = write_bom(rows, folder)
    with open(os.path.join(d, "design.json"), "w", encoding="utf-8") as f:
        rel = {k: {**v, "path": os.path.relpath(v["path"], folder)} for k, v in prints.items()}
        json.dump({"spec": model.spec.__dict__, "params": model.params.to_dict(), "checks": result, "print": rel,
                   "bom": rows}, f, indent=1, default=str)
    files["design_json"] = os.path.join(d, "design.json")
    files["report_md"] = (enc_report if enc else report_md)(model, result, prints, os.path.join(d, "report.md"))
    # keep the PCB side's contract current: the space each RL PCB board gets in this airframe
    for slot, bd in getattr(model, "boards", {}).items():
        env = result.get("metrics", {}).get("boards", {}).get(slot, {}).get("envelope")
        if env:
            from .mech import write_envelope
            files[f"envelope_{slot}"] = write_envelope(bd["mech"], env)
    if render:
        from .render import render as rr
        items = [(i.shape, i.colour) for i in model.items if i.shape is not None and not i.name.startswith("prop")]
        files["render_png"] = rr(items, os.path.join(d, "render.png"), title=model.spec.name)
    return {"files": files, "print": prints}
