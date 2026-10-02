"""Enclosure family: a printed two-part box built around a board designed with RL PCB.

The board's mech.json (outline, mounting holes, part heights, connectors and the edge each faces) drives everything:
the inside follows the board with a clearance, standoffs sit under its mounting holes, the walls get an opening in
front of every fitted connector, and the lid screws into corner columns clear of the board. Change the board in KiCad
and the enclosure follows on the next build; the checks say if something no longer fits.

Frame: board frame of rl-mech/1 (origin at the board outline centre, +x right, +y towards the KiCad top edge), z up
from the bottom of the base.
"""
from __future__ import annotations

import math
import os
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple

EDGE_DIR = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}


@dataclass
class EnclosureParams:
    wall: float = 2.0             # side wall, mm (≥ 2 lines of 0.4 mm, 2 mm is sturdy)
    floor: float = 2.0            # base floor, mm
    lid_t: float = 2.0            # lid plate, mm
    corner_r: float = 4.0         # outside corner radius, mm
    clearance: float = 1.5        # board edge to inner wall, mm
    gap_below: float = 0.0        # extra room under the board beyond its bottom-side parts, mm
    gap_above: float = 3.0        # room above the tallest top-side part, mm
    standoff_od: float = 6.0      # board standoff outside diameter, mm
    standoff_hole: float = 2.5    # pilot for an M3 self-tapping screw (4.0 for a heat-set insert)
    column_od: float = 7.0        # lid screw columns in the corners, mm
    column_hole: float = 2.5      # pilot for the lid screws
    lid_hole: float = 3.4         # clearance hole in the lid for M3
    lip_h: float = 2.5            # locating lip under the lid, mm
    lip_t: float = 1.2            # lip thickness, mm
    fit_clear: float = 0.25       # lip to wall clearance, mm
    cutout_margin: float = 1.0    # around each connector opening, mm
    vents: bool = True            # slots in the lid above the board
    vent_w: float = 2.0
    port_holes: Tuple = ()        # derived
    # filled from the board
    board_w: float = 50.0
    board_l: float = 40.0
    board_t: float = 1.6
    h_top: float = 5.0
    h_bottom: float = 1.0

    @property
    def board_z(self) -> float:
        """Height of the board's bottom face above the base bottom."""
        return self.floor + max(self.h_bottom + 1.0, 3.0) + self.gap_below

    @property
    def inner_half(self) -> Tuple[float, float]:
        hx = self.board_w / 2 + self.clearance
        hy = self.board_l / 2 + self.clearance
        # grow until the corner columns clear the board's corners by 0.5 mm
        r = self.column_od / 2
        for _ in range(200):
            cx, cy = hx - r + 0.6, hy - r + 0.6
            dx, dy = cx - self.board_w / 2, cy - self.board_l / 2
            clear = (dx >= r + 0.5) or (dy >= r + 0.5) or (dx > 0 and dy > 0 and math.hypot(dx, dy) >= r + 0.5)
            if clear:
                break
            hx += 0.25
            hy += 0.25
        return hx, hy

    @property
    def height(self) -> float:
        """Base height (the lid sits on top)."""
        return self.board_z + self.board_t + self.h_top + self.gap_above

    @property
    def columns(self) -> List[Tuple[float, float]]:
        hx, hy = self.inner_half
        r = self.column_od / 2
        return [(sx * (hx - r + 0.6), sy * (hy - r + 0.6)) for sx in (-1, 1) for sy in (-1, 1)]

    def to_dict(self):
        d = asdict(self)
        hx, hy = self.inner_half
        d.update(inner_mm=[round(2 * hx, 2), round(2 * hy, 2)], outer_mm=[round(2 * (hx + self.wall), 2),
                 round(2 * (hy + self.wall), 2), round(self.height + self.lid_t, 2)], board_z=round(self.board_z, 2))
        return d


PARAM_DOCS = {
    "wall": "side wall thickness, mm", "floor": "base floor thickness, mm", "lid_t": "lid thickness, mm",
    "corner_r": "outside corner radius, mm", "clearance": "board edge to inner wall, mm",
    "gap_below": "extra room under the board, mm", "gap_above": "room above the tallest top-side part, mm",
    "standoff_od": "board standoff diameter, mm", "standoff_hole": "standoff pilot hole, mm (2.5 M3 self-tap, 4.0 "
                                                                   "heat-set insert)",
    "column_od": "lid screw column diameter, mm", "column_hole": "column pilot hole, mm", "lid_hole": "lid screw "
                                                                                                   "clearance hole, mm",
    "lip_h": "lid locating lip height, mm", "fit_clear": "lip-to-wall clearance, mm",
    "cutout_margin": "space around each connector opening, mm", "vents": "ventilation slots in the lid (true/false)",
}


def params_for(spec, base_dir: Optional[str] = None, mech: Optional[Dict] = None) -> EnclosureParams:
    p = EnclosureParams(**{k: v for k, v in spec.airframe.items() if k in EnclosureParams.__dataclass_fields__})
    if mech is None and base_dir:
        mech = board_mech(spec, base_dir)
    if mech:
        p.board_w, p.board_l = mech["outline_mm"]["size"]
        p.board_t = mech.get("thickness_mm", 1.6)
        p.h_top, p.h_bottom = mech["height_mm"]["top"], mech["height_mm"]["bottom"]
    return p


def board_slot(spec) -> Optional[str]:
    return next(iter(spec.boards), None)


def board_mech(spec, base_dir: Optional[str]) -> Optional[Dict]:
    slot = board_slot(spec)
    if not slot or not base_dir:
        return None
    from ..mech import load_board
    return load_board(base_dir, spec.boards[slot])


def _rrect(w, l, r, h, z0=0.0):
    from build123d import Align, Pos, RectangleRounded, extrude
    r = max(0.3, min(r, w / 2 - 0.1, l / 2 - 0.1))
    return Pos(0, 0, z0) * extrude(RectangleRounded(w, l, r), h)


def openings(p: EnclosureParams, mech: Dict) -> List[Dict]:
    """One wall opening per fitted connector that faces an edge."""
    out = []
    for c in mech.get("connectors", []):
        if not c.get("edge") or not c.get("populated", True):
            continue
        x0, y0, x1, y1 = c["bbox_mm"]
        plug = c.get("plug_mm")
        top = c.get("side", "top") == "top"
        h_conn = max(c.get("height_mm") or 0.0, 1.5)
        if c["edge"] in ("+x", "-x"):
            span = abs(y1 - y0)
            centre = (y0 + y1) / 2
        else:
            span = abs(x1 - x0)
            centre = (x0 + x1) / 2
        w = max(span, plug[0] if plug else 0.0) + 2 * p.cutout_margin
        h = max(h_conn, plug[1] if plug else 0.0) + 2 * p.cutout_margin
        z_mid = (p.board_z + p.board_t + h_conn / 2) if top else (p.board_z - h_conn / 2)
        out.append({"ref": c["ref"], "mate": c.get("mate"), "edge": c["edge"], "centre": round(centre, 2),
                    "z": round(z_mid, 2), "w": round(w, 2), "h": round(h, 2), "plug": plug})
    return out


def build(p: EnclosureParams, mech: Optional[Dict]) -> Dict[str, Dict]:
    from build123d import Align, Box, Cylinder, Pos, Rot
    hx, hy = p.inner_half
    W, L = 2 * (hx + p.wall), 2 * (hy + p.wall)
    H = p.height
    ri = max(0.5, p.corner_r - p.wall)
    base = _rrect(W, L, p.corner_r, H) - _rrect(2 * hx, 2 * hy, ri, H, p.floor)
    C = (Align.CENTER, Align.CENTER, Align.MIN)
    # board standoffs
    holes = (mech or {}).get("mounting_holes", [])
    for h in holes:
        x, y = h["at_mm"]
        st = Pos(x, y, p.floor - 0.01) * Cylinder(p.standoff_od / 2, p.board_z - p.floor + 0.01, align=C)
        base = base + st - Pos(x, y, p.floor + 0.6) * Cylinder(p.standoff_hole / 2, p.board_z, align=C)
    # lid columns in the corners (merged with the walls)
    for x, y in p.columns:
        col = Pos(x, y, p.floor - 0.01) * Cylinder(p.column_od / 2, H - p.floor - p.lip_h - 0.4 + 0.01, align=C)
        base = base + col - Pos(x, y, H - p.lip_h - 9.0) * Cylinder(p.column_hole / 2, 12, align=C)
    # connector openings
    ops = openings(p, mech or {})
    cuts = []
    for o in ops:
        dx, dy = EDGE_DIR[o["edge"]]
        z0, z1 = o["z"] - o["h"] / 2, o["z"] + o["h"] / 2
        if z1 > H - 1.6:            # too close to the rim: a sliver would be left above it, so notch the rim instead
            z1 = H + p.lid_t + 1
        zc, hh = (z0 + z1) / 2, z1 - z0
        depth = p.wall + p.lip_t + p.fit_clear + 2.0          # through the wall and the lid's lip behind it
        if dx:
            cut = Pos(dx * (hx + p.wall - depth / 2 + 0.5), o["centre"], zc) * Box(depth + 1, o["w"], hh)
        else:
            cut = Pos(o["centre"], dy * (hy + p.wall - depth / 2 + 0.5), zc) * Box(o["w"], depth + 1, hh)
        o["notch"] = z1 > H
        cuts.append(cut)
        base = base - cut
    # lid: plate, locating lip just inside the walls, screw holes, vents
    lid = _rrect(W, L, p.corner_r, p.lid_t, H)
    lo_w, lo_l = 2 * (hx - p.fit_clear), 2 * (hy - p.fit_clear)
    lip = _rrect(lo_w, lo_l, max(0.5, ri - p.fit_clear), p.lip_h, H - p.lip_h) - \
        _rrect(lo_w - 2 * p.lip_t, lo_l - 2 * p.lip_t, max(0.3, ri - p.fit_clear - p.lip_t), p.lip_h + 0.1, H - p.lip_h - 0.05)
    lid = lid + lip
    rim = Pos(0, 0, -1) * Box(W + 10, L + 10, H + 1 - 0.01, align=C)     # only the lip, never the lid plate
    for cut in cuts:
        lid = lid - (cut & rim)
    for x, y in p.columns:
        # the lip stops short of the corner columns: cut the whole corner square (a round notch leaves slivers)
        rr = p.column_od / 2 + p.fit_clear
        sx, sy = (1 if x > 0 else -1), (1 if y > 0 else -1)
        cx0, cx1 = sorted((x - sx * rr, sx * (hx + p.wall)))
        cy0, cy1 = sorted((y - sy * rr, sy * (hy + p.wall)))
        lid = lid - Pos((cx0 + cx1) / 2, (cy0 + cy1) / 2, H - p.lip_h - 0.1) * Box(cx1 - cx0, cy1 - cy0, p.lip_h + 0.1,
                                                                                   align=C)
        lid = lid - Pos(x, y, H - p.lip_h - 1) * Cylinder(p.lid_hole / 2, p.lip_h + p.lid_t + 2, align=C)
    if p.vents:
        n = max(0, int((p.board_w * 0.6) // (p.vent_w * 2.5)))
        vl = max(6.0, p.board_l * 0.45)
        for k in range(n):
            x = (k - (n - 1) / 2) * p.vent_w * 2.5
            lid = lid - Pos(x, 0, H - 0.1) * Box(p.vent_w, vl, p.lid_t + 0.2, align=C)
    return {
        "base": {"shape": base, "material": "PETG", "colour": (0.28, 0.30, 0.33), "role": "enclosure base: holds the board"},
        "lid": {"shape": lid, "material": "PETG", "colour": (0.62, 0.65, 0.68), "role": "enclosure lid"},
    }, ops


# ------------------------------------------------------------------------------------------- model
def build_model(spec, base_dir: Optional[str] = None):
    from build123d import Pos, Rot, import_step
    from .. import catalog as Cat
    from ..project import Item, Model, _box
    mech = board_mech(spec, base_dir)
    notes = []
    if not mech:
        raise ValueError("an enclosure needs a board: spec_set_board(project='<KiCad project folder>', slot='main')")
    if mech.get("_note"):
        notes.append(mech["_note"])
    p = params_for(spec, mech=mech)
    parts, ops = build(p, mech)
    if spec.features:
        from ..geom.features import apply as apply_features
        for part in {f["part"] for f in spec.features}:
            if part in parts:
                parts[part]["shape"] = apply_features(parts[part]["shape"], [f for f in spec.features if f["part"] == part])
            else:
                notes.append(f"features on '{part}' skipped: parts are base, lid")
    items = []
    for name, d in parts.items():
        mat = spec.materials.get(name, d["material"])
        dens = Cat.MATERIALS[mat]["density"]
        sh = d["shape"]
        items.append(Item(name, "airframe", sh, sh.volume / 1000 * dens, mat, d["colour"], d["role"], True,
                          (sh.center().X, sh.center().Y, sh.center().Z)))
    slot = board_slot(spec)
    rotation = (spec.boards.get(slot) or {}).get("rotation", 0)
    board_sh = None
    if mech.get("step") and os.path.exists(mech["step"]):
        try:
            b = import_step(mech["step"])
            kx, ky = mech.get("kicad_centre_mm") or (0, 0)
            board_sh = Pos(0, 0, p.board_z) * Pos(-kx, ky, 0) * b
            notes.append(f"board geometry from {os.path.basename(mech['step'])}")
        except Exception as e:  # noqa
            notes.append(f"could not import the board STEP: {e}")
    if board_sh is None:
        board_sh = _box(0, 0, p.board_z, p.board_w, p.board_l, p.board_t)
    items.append(Item(slot, "component", board_sh, mech.get("mass_g_est", 5.0), colour=(0.05, 0.35, 0.12),
                      role="board (RL PCB)", cg=(0, 0, p.board_z)))
    # top-side and bottom-side part envelopes as blocks, for clearance checks against the lid and floor
    if p.h_top > 0:
        items.append(Item(f"{slot}_parts_top", "component", _box(0, 0, p.board_z + p.board_t, p.board_w - 0.4,
                                                                 p.board_l - 0.4, p.h_top), 0.0, colour=(0.2, 0.2, 0.2),
                          role="tallest top-side parts (envelope)", cg=(0, 0, 0)))
    ports = []
    for o in ops:
        dx, dy = EDGE_DIR[o["edge"]]
        hx, hy = p.inner_half
        origin = (dx * (hx + p.wall + 0.4), o["centre"], o["z"]) if dx else (o["centre"], dy * (hy + p.wall + 0.4), o["z"])
        if o.get("plug"):
            ports.append({"name": f"{o['ref']} ({o['mate']})", "origin": origin, "dir": (dx, dy, 0),
                          "plug_mm": tuple(o["plug"]), "source": "mech.json"})
    p.port_holes = tuple(ops)
    boards = {slot: {"mech": mech, "centre": (0.0, 0.0), "z_bottom": p.board_z, "rotation": rotation}}
    for pid, pos in (("fasteners_m2_m3", (0, 0, 1)),):
        part = Cat.get(pid)
        items.append(Item(pid, "component", None, part.mass_g, role=part.name, cg=pos))
    return Model(spec, p, items, notes, ports, boards)


# ------------------------------------------------------------------------------------------- checks
def run_checks(model, printer_bed=None, print_audit: bool = True) -> Dict:
    from build123d import Box, Pos
    from .. import catalog as Cat
    from ..checks import _f, _inter_vol, _print_audit, bed_fit
    from ..geom.mesh import mesh
    spec, p = model.spec, model.params
    out, metrics = [], {}
    bed = printer_bed or Cat.PRINTERS[spec.printer]["bed_mm"]
    air = [i for i in model.items if i.kind == "airframe"]
    comps = [i for i in model.items if i.kind == "component" and i.shape is not None]
    fit = {}
    for it in model.printable:
        r = bed_fit(it.shape, bed)
        fit[it.name] = r
        if not r["fits"]:
            out.append(_f("error", "bed_fit", f"{it.name} does not fit the {Cat.PRINTERS[spec.printer]['name']}: best "
                                              f"{r['footprint_mm'][0]}×{r['footprint_mm'][1]}×{r['height_mm']} mm", [it.name]))
    metrics["print_orientation"] = fit
    # the board and its parts against the shell
    for c in comps:
        for a in air:
            v = _inter_vol(c.shape, a.shape)
            lim = 2.0 if c.name.endswith("_parts_top") else 0.5
            if v > lim:
                out.append(_f("error", "interference", f"{c.name} overlaps {a.name} by {v:.1f} mm³", [c.name, a.name]))
    # lid lip and columns against the base (they interlock with clearance)
    v = _inter_vol(model.item("base").shape, model.item("lid").shape)
    if v > 0.5:
        out.append(_f("error", "interference", f"lid and base overlap by {v:.1f} mm³ (the lip must clear the walls)",
                      ["base", "lid"]))
    # connectors reachable from outside, through their openings
    for port in model.ports:
        ox, oy, oz = port["origin"]
        w, h = port["plug_mm"]
        dx, dy, _ = port["dir"]
        reach = 15.0
        if dx:
            plug = Pos(ox - dx * (p.wall + 1.0) + dx * reach / 2, oy, oz) * Box(reach, w, h)
        else:
            plug = Pos(ox, oy - dy * (p.wall + 1.0) + dy * reach / 2, oz) * Box(w, reach, h)
        blocked = [(a.name, _inter_vol(plug, a.shape)) for a in air]
        blocked = [n for n, vv in blocked if vv > 0.5]
        if blocked:
            out.append(_f("error", "connector_access", f"{port['name']}: a {w}×{h} mm plug is blocked by "
                                                       f"{', '.join(blocked)}", [port["name"]]))
        else:
            out.append(_f("info", "connector_access", f"{port['name']}: plug path through its opening is clear",
                          [port["name"]]))
    # board slot: mount, heights, envelope for RL PCB
    slot, bd = next(iter(model.boards.items()))
    mech = bd["mech"]
    hx, hy = p.inner_half
    holes = mech.get("mounting_holes", [])
    if not holes:
        out.append(_f("warning", "board_mount", f"{slot}: the board has no mounting holes; it will rest loose on the "
                                                "floor (add holes in KiCad, or glue it)", [slot]))
    else:
        out.append(_f("info", "board_mount", f"{slot}: {len(holes)} standoffs under the board's holes "
                                             f"(Ø{p.standoff_hole} mm pilot)", [slot]))
    room_top = p.height - p.lip_h - (p.board_z + p.board_t)
    if mech["height_mm"]["top"] > room_top - 0.3:
        out.append(_f("error", "board_height", f"{slot}: top-side parts are {mech['height_mm']['top']} mm tall but the "
                                               f"lid's lip leaves {room_top:.1f} mm", [slot]))
    else:
        out.append(_f("info", "board_height", f"{slot}: {room_top:.1f} mm above the board (tallest part "
                                              f"{mech['height_mm']['top']} mm)", [slot]))
    env = {"schema": "rl-envelope/1", "product": spec.name, "slot": slot, "generated_by": "RL CAD (enclosure)",
           "frame": "board frame of rl-mech/1 (origin outline centre, +y = KiCad top edge)", "rotation_deg": 0,
           "max_outline_mm": [round(2 * (hx - 0.5), 2), round(2 * (hy - 0.5), 2)],
           "mount_pattern_mm": None, "mount_hole_d_mm": 2.5,
           "mount_holes_mm": [h["at_mm"] for h in holes],
           "keepout_height_mm": {"top": round(room_top - 0.3, 2), "bottom": round(p.board_z - p.floor - 0.3, 2)},
           "reachable_edges": sorted(EDGE_DIR),
           "required_ports": [{"mate": pt["name"].split("(")[-1].rstrip(")"), "why": "opening in the enclosure wall",
                               "edges": []} for pt in model.ports],
           "notes": [f"enclosure inner {2 * hx:.1f}×{2 * hy:.1f} mm; board bottom {p.board_z:.1f} mm above the base "
                     "bottom; standoffs follow the board's holes on every rebuild"]}
    for r in env["required_ports"]:
        r["edges"] = sorted({o["edge"] for o in p.port_holes if (o.get("mate") or "") == r["mate"]})
    metrics.setdefault("boards", {})[slot] = {"envelope": env, "outline_mm": mech["outline_mm"]["size"],
                                              "height_mm": mech["height_mm"]}
    metrics["mass"] = {"total_g": round(sum(i.mass_g for i in model.items), 1),
                       "items": [{"name": i.name, "mass_g": round(i.mass_g, 1)} for i in model.items]}
    metrics["enclosure"] = p.to_dict()
    for it in model.printable:
        n_sol = len(it.shape.solids())
        if n_sol != 1:
            out.append(_f("error", "solid", f"{it.name} is {n_sol} separate bodies", [it.name]))
        if not it.shape.is_valid:
            out.append(_f("error", "solid", f"{it.name} has invalid geometry", [it.name]))
        if mesh(it.shape, 0.5, 0.6)[2]:
            out.append(_f("error", "solid", f"{it.name} has faces that cannot be triangulated", [it.name]))
    for name, val, lim in (("wall", p.wall, 1.2), ("floor", p.floor, 1.2), ("lid_t", p.lid_t, 1.2)):
        if val < lim:
            out.append(_f("warning", "printability", f"{name} = {val} mm is thin (min ≈{lim} mm)"))
    if print_audit:
        out += _print_audit(model, bed, metrics)
    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda f: order[f["severity"]])
    summary = {s: sum(1 for f in out if f["severity"] == s) for s in ("error", "warning", "info")}
    return {"summary": summary, "findings": out, "metrics": metrics, "notes": model.notes}


def bom_rows(model, prints: Optional[Dict] = None) -> List[Dict]:
    p = model.params
    slot = next(iter(model.boards))
    rows = [{"type": "make (RL PCB)", "role": "board", "item": slot, "qty": 1, "mass_g_each": 0, "source":
             model.boards[slot]["mech"].get("pcb") or "", "notes": "fabricate from the KiCad project"},
            {"type": "buy", "role": "fasteners", "item": f"M3×6 self-tapping (board) ×{len(model.boards[slot]['mech'].get('mounting_holes', []))}; "
             f"M3×{int(round(p.lip_h + p.lid_t + 6))} self-tapping (lid) ×4", "qty": 1, "mass_g_each": 3.0,
             "source": "", "notes": f"pilots Ø{p.standoff_hole} / Ø{p.column_hole} mm"}]
    for it in model.printable:
        pr = (prints or {}).get(it.name, {})
        rows.append({"type": "print", "role": it.role, "item": it.name, "qty": 1, "mass_g_each": round(it.mass_g, 1),
                     "source": f"out/print/{it.name}.stl", "notes": f"{it.material}, {pr.get('orientation', '')}"})
    return rows


def report(model, result: Dict, prints: Dict, path: str) -> str:
    p = model.params
    d = p.to_dict()
    L = [f"# {model.spec.name}: enclosure", "",
         f"Board {p.board_w}×{p.board_l} mm; inside {d['inner_mm'][0]}×{d['inner_mm'][1]} mm; outside "
         f"{d['outer_mm'][0]}×{d['outer_mm'][1]}×{d['outer_mm'][2]} mm.", "",
         f"Checks: {result['summary']['error']} errors, {result['summary']['warning']} warnings.", ""]
    for f in result["findings"]:
        L.append(f"- **{f['severity']}** ({f['rule']}): {f['message']}")
    L += ["", "## Openings", ""] + [f"- {o['ref']} ({o['mate'] or 'connector'}) on the {o['edge']} wall: "
                                     f"{o['w']}×{o['h']} mm" for o in p.port_holes]
    L += ["", "## Printing", "", "| Part | Orientation | Size (mm) |", "|---|---|---|"]
    for n, pr in prints.items():
        L.append(f"| {n} | {pr['orientation']} | {pr['footprint_mm'][0]}×{pr['footprint_mm'][1]}×{pr['height_mm']} |")
    L += ["", "Assembly: screw the board onto the standoffs (M3 self-tapping), close the lid, four screws in the "
              "corners.", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    return path
