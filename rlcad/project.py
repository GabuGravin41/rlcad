"""RL CAD project: the system spec (requirements, chosen parts, airframe parameters, printer, decisions) and the model
built from it (airframe parts + placed components with masses and positions).

The spec is the contract, like RL PCB's design plan: everything else (geometry, checks, exports) is derived from it.
Stored as <folder>/rlcad.json.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import calc
from . import catalog as C

SPEC_FILE = "rlcad.json"

DEFAULT_PARTS = {"motor": "motor_xing2_1404_4600kv", "prop": "prop_gemfan_3016_3", "esc": "esc_racerstar_shot30a",
                 "fc": "fc_rl_f405", "receiver": "rx_radiomaster_rp1", "battery": "lipo_3s_650"}


@dataclass
class Spec:
    name: str = "design"
    kind: str = "ducted_quad_f35"
    requirements: Dict[str, str] = field(default_factory=dict)
    printer: str = "bambu_a1_mini"
    parts: Dict[str, Dict] = field(default_factory=lambda: {k: {"id": v} for k, v in DEFAULT_PARTS.items()})
    airframe: Dict = field(default_factory=dict)          # overrides of AirframeParams
    materials: Dict[str, str] = field(default_factory=dict)  # part-kind → material override
    fc_step: str = ""                                     # KiCad board STEP (from RL PCB / kicad-cli)
    # boards designed with RL PCB, by slot: {"fc": {"project": "electronics/rl_fc_f405", "rotation": 0}}
    boards: Dict[str, Dict] = field(default_factory=dict)
    decisions: List[str] = field(default_factory=list)
    # local details on generated parts (geom/features.py): [{"id", "part", "type", ..., "note"}]
    features: List[Dict] = field(default_factory=list)
    updated: float = 0.0

    @staticmethod
    def path(folder):
        return os.path.join(folder, SPEC_FILE)

    @classmethod
    def load(cls, folder) -> "Spec":
        p = cls.path(folder)
        if not os.path.exists(p):
            return cls(name=os.path.basename(os.path.abspath(folder)))
        with open(p, encoding="utf-8-sig") as f:
            d = json.load(f)
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self, folder):
        os.makedirs(folder, exist_ok=True)
        self.updated = time.time()
        with open(self.path(folder), "w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, indent=2)
        return self.path(folder)

    def part(self, role) -> C.Part:
        entry = self.parts.get(role) or {"id": DEFAULT_PARTS[role]}
        over = {k: v for k, v in entry.items() if k != "id"}
        return C.get(entry["id"], **over)


# ------------------------------------------------------------------------------------------- model
@dataclass
class Item:
    name: str
    kind: str                  # airframe | component
    shape: object
    mass_g: float
    material: str = ""
    colour: Tuple[float, float, float] = (0.6, 0.6, 0.6)
    role: str = ""
    printable: bool = False
    cg: Tuple[float, float, float] = (0, 0, 0)


@dataclass
class Model:
    spec: Spec
    params: object
    items: List[Item]
    notes: List[str] = field(default_factory=list)
    ports: List[Dict] = field(default_factory=list)   # connectors that must stay reachable
    boards: Dict[str, Dict] = field(default_factory=dict)  # slot -> {"mech", "centre", "z_bottom", "rotation"}

    def item(self, name):
        return next(i for i in self.items if i.name == name)

    @property
    def printable(self):
        return [i for i in self.items if i.printable]


_MECH_CACHE: Dict = {}


def board_mech(spec: Spec, base_dir: Optional[str], slot: str = "fc"):
    """The RL PCB mechanical description of a board slot, or None (catalog data is used then)."""
    entry = spec.boards.get(slot)
    if not entry or not base_dir:
        return None
    from .mech import load_board
    key = (os.path.abspath(base_dir), slot, json.dumps(entry, sort_keys=True))
    m = load_board(base_dir, entry)
    _MECH_CACHE[key] = m
    return m


def _rot(x, y, deg):
    import math
    r = math.radians(deg)
    return x * math.cos(r) - y * math.sin(r), x * math.sin(r) + y * math.cos(r)


def airframe_params(spec: Spec, base_dir: Optional[str] = None, mech: Optional[Dict] = None):
    if spec.kind == "enclosure":
        from .families.enclosure import params_for
        return params_for(spec, base_dir, mech)
    from .geom.airframe import AirframeParams
    motor, prop, fc = spec.part("motor"), spec.part("prop"), spec.part("fc")
    base = dict(prop_d=prop.data["diameter_mm"], motor_h=motor.data["height"], motor_base_d=motor.data["base_d"],
                motor_bell_d=motor.data.get("bell_d", motor.data["base_d"]), prop_hub_h=prop.data.get("hub_h", 6.0),
                motor_hole_d=motor.data.get("mount_hole_d", 2.0) + 0.2,
                motor_pattern=motor.data["mount_pattern_mm"], motor_pattern_alt=motor.data.get("mount_alt_pattern_mm", 12.0),
                stack_pattern=fc.data["mount_pattern_mm"])
    base.update(spec.airframe)
    ap = AirframeParams(**{k: v for k, v in base.items() if k in AirframeParams.__dataclass_fields__})
    if mech is None and base_dir:
        mech = board_mech(spec, base_dir)
    if "port_holes" not in spec.airframe:
        ap.port_holes = tuple(h for h, _ in _port_geometry(spec, ap, mech) if h)
    return ap


def stack_heights(spec: Spec, p) -> Tuple[float, float]:
    """(z of ESC bottom, z of FC bottom): ESC on 3 mm grommets, FC 4 mm above the ESC."""
    esc = spec.part("esc")
    z_esc = p.frame_t + 3.0
    return z_esc, z_esc + esc.envelope_mm[2] + 4.0


def _port_geometry(spec: Spec, p, mech: Optional[Dict] = None):
    """Connectors on the FC that a person must reach: the fuselage hole (x, side, z, w, h) or None, and the port.
    With an RL PCB board (mech) the connectors come from the board itself; otherwise from the catalog entry.
    If the airframe brings the USB port out with an extension (p.usb_port = (x, z)), hole and reach check move there."""
    out = []
    _, z_fc = stack_heights(spec, p)
    raw = []
    if mech:
        from .mech import ports_from_mech
        rotation = (spec.boards.get("fc") or {}).get("rotation", 0)
        for c in ports_from_mech(mech):
            x, y = _rot(c["at"][0], c["at"][1], rotation)
            dx, dy = _rot(c["dir"][0], c["dir"][1], rotation)
            raw.append((c["mate"].replace("-", "_") + f" ({c['ref']})", (x, y, c["at"][2]), (round(dx), round(dy), 0),
                        c["plug_mm"], f"{c['ref']} in {os.path.basename(mech.get('pcb') or '')} (RL PCB mech.json)"))
    else:
        for name, d in (spec.part("fc").data.get("ports") or {}).items():
            raw.append((name, tuple(d["offset_mm"]), tuple(d["dir"]), tuple(d["plug_mm"]), d.get("source", "")))
    for name, (ox, oy, oz), (dx, dy, dz), (w, h), src in raw:
        if name.startswith("usb") and p.usb_port:
            px, pz = p.usb_port
            side = 1
            hole = (px, side, pz, 10.5, 4.6)          # panel-mount socket opening in the left side
            # the socket sits in the side wall; the plug starts just outside the skin
            from .geom.airframe import half_width_at
            # the plug must clear the skin over its whole height (the side bulges out towards the chine)
            wall = max(half_width_at(p, px + dxx, pz + dz_) for dz_ in (-h / 2, 0.0, h / 2) for dxx in (-w / 2, 0.0, w / 2))
            port = {"name": f"fc.{name} (extension socket)", "origin": (px, side * (wall + 0.4), pz),
                    "dir": (0, side, 0), "plug_mm": (w, h), "extension": True,
                    "source": src + "; brought to the skin with usb_c_panel_ext"}
        else:
            hole = (round(p.stack_x + ox, 2), 1 if dy > 0 else -1, round(z_fc + oz, 2), w + 1.0, h + 1.0) if dy else None
            port = {"name": f"fc.{name}", "origin": (p.stack_x + ox, oy, z_fc + oz), "dir": (dx, dy, dz),
                    "plug_mm": (w, h), "source": src}
        out.append((hole, port))
    return out


def _box(cx, cy, z0, sx, sy, sz):
    from build123d import Align, Box, Pos
    return Pos(cx, cy, z0) * Box(sx, sy, sz, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _cyl(cx, cy, z0, r, h):
    from build123d import Align, Cylinder, Pos
    return Pos(cx, cy, z0) * Cylinder(r, h, align=(Align.CENTER, Align.CENTER, Align.MIN))


def _centroid(shape):
    from build123d import CenterOf
    c = shape.center(CenterOf.MASS)
    return (c.X, c.Y, c.Z)


def build_model(spec: Spec, battery_x: Optional[float] = None, base_dir: Optional[str] = None) -> Model:
    if spec.kind == "enclosure":
        from .families.enclosure import build_model as build_enclosure
        return build_enclosure(spec, base_dir)
    from build123d import Pos, import_step
    from .geom.airframe import build as build_airframe
    mech = None
    try:
        mech = board_mech(spec, base_dir)
    except Exception as e:  # noqa
        pass
    p = airframe_params(spec, mech=mech)
    items: List[Item] = []
    notes: List[str] = []
    built = build_airframe(p)
    if spec.features:
        from .geom.features import apply as apply_features
        for part in {f["part"] for f in spec.features}:
            if part not in built:
                notes.append(f"features on '{part}' skipped: no such part ({', '.join(built)})")
                continue
            built[part]["shape"] = apply_features(built[part]["shape"], [f for f in spec.features if f["part"] == part])
    for name, d in built.items():
        kind = name.split("_")[0]
        mat = spec.materials.get(kind, d["material"])
        dens = C.MATERIALS[mat]["density"]
        vol_cm3 = d["shape"].volume / 1000
        from .export import PRINT_WITH
        printed_with = next((host for host, extra in PRINT_WITH.items() if name in extra), None)
        role = d["role"] + (f" (printed as part of {printed_with}: second colour or paint)" if printed_with else "")
        items.append(Item(name, "airframe", d["shape"], vol_cm3 * dens, mat, d["colour"], role, printed_with is None,
                          _centroid(d["shape"])))
    motor, prop, esc, fc, rx, bat = (spec.part(r) for r in ("motor", "prop", "esc", "fc", "receiver", "battery"))
    from build123d import Rot
    from .geom import components as G
    motor_sh = G.motor(motor.data)
    prop_cw, prop_ccw = G.prop(prop.data, cw=True), G.prop(prop.data, cw=False)
    for i, (cx, cy) in enumerate(p.duct_centres):
        # bought parts, modelled from their datasheets: the motor on its pad, the prop hub on top of the bell
        sh = Pos(cx, cy, p.frame_t) * motor_sh
        items.append(Item(f"motor_{i + 1}", "component", sh, motor.mass_g, colour=(0.75, 0.2, 0.2), role=motor.name,
                          cg=(cx, cy, p.frame_t + motor.data["height"] / 2)))
        psh = Pos(cx, cy, p.prop_z) * Rot(0, 0, 40.0 * i) * (prop_cw if i in (0, 3) else prop_ccw)
        items.append(Item(f"prop_{i + 1}", "component", psh, prop.mass_g, colour=(0.12, 0.12, 0.14),
                          role=prop.name + " (bought, not printed)", cg=(cx, cy, p.prop_z)))
    # stack: ESC on 3 mm grommets, FC 4 mm above it
    z_esc, _ = stack_heights(spec, p)
    esc_sh = Pos(p.stack_x, 0, z_esc) * G.board(esc.envelope_mm, esc.data.get("mount_pattern_mm", 0.0),
                                                 esc.data.get("mount_hole_d", 3.2))
    items.append(Item("esc", "component", esc_sh, esc.mass_g, colour=(0.1, 0.35, 0.15), role=esc.name, cg=_centroid(esc_sh)))
    z_fc = z_esc + esc.envelope_mm[2] + 4.0
    fc_sh = None
    fc_path = spec.fc_step
    rotation = (spec.boards.get("fc") or {}).get("rotation", 0)
    if mech:
        if mech.get("_note"):
            notes.append(mech["_note"])
        if mech.get("step"):
            fc_path = mech["step"]
    if fc_path and not os.path.isabs(fc_path) and base_dir:
        fc_path = os.path.join(base_dir, fc_path)          # relative paths are relative to the design folder
    if fc_path and not os.path.exists(fc_path):
        notes.append(f"FC board STEP {fc_path} not found; using the board outline")
    if fc_path and os.path.exists(fc_path):
        try:
            from build123d import Rot
            b = import_step(fc_path)
            if mech and mech.get("kicad_centre_mm"):
                # KiCad's STEP frame: (x, -y) of the board file, bottom face at z = 0. Place the outline centre on the
                # stack axis and the bottom face at z_fc; parts below the board (bottom side) hang under it.
                kx, ky = mech["kicad_centre_mm"]
                fc_sh = Pos(p.stack_x, 0, z_fc) * Rot(0, 0, rotation) * Pos(-kx, ky, 0) * b
            else:
                b = Rot(0, 0, rotation) * b
                bb0 = b.bounding_box()
                fc_sh = Pos(p.stack_x - bb0.center().X, -bb0.center().Y, z_fc - bb0.min.Z) * b
            bb = fc_sh.bounding_box()
            notes.append(f"FC geometry from {os.path.basename(fc_path)} ({bb.size.X:.1f}×{bb.size.Y:.1f}×{bb.size.Z:.1f} mm)")
        except Exception as e:  # noqa
            notes.append(f"Could not import {fc_path}: {e}")
    if fc_sh is None and mech:
        w, l = mech["outline_mm"]["size"]
        t = mech["thickness_mm"]
        fc_sh = _box(p.stack_x, 0, z_fc - mech["height_mm"]["bottom"], w, l, t + mech["height_mm"]["top"] + mech["height_mm"]["bottom"])
    if fc_sh is None:
        fc_sh = _box(p.stack_x, 0, z_fc, fc.envelope_mm[0], fc.envelope_mm[1], fc.envelope_mm[2])
    fc_mass = fc.mass_g
    if mech and "mass_g" not in (spec.parts.get("fc") or {}):
        fc_mass = mech.get("mass_g_est", fc.mass_g)
    items.append(Item("fc", "component", fc_sh, fc_mass, colour=(0.05, 0.3, 0.1), role=fc.name, cg=_centroid(fc_sh)))
    rx_sh = Pos(p.stack_x + 26.0, 0, p.frame_t + 1.0) * G.board(rx.envelope_mm)
    items.append(Item("receiver", "component", rx_sh, rx.mass_g, colour=(0.2, 0.2, 0.6), role=rx.name, cg=_centroid(rx_sh)))
    for pid, pos in (("wiring_allowance", (p.stack_x - 10, 0, p.frame_t + 6)), ("fasteners_m2_m3", (0.0, 0, p.frame_t))):
        part = C.get(pid)
        items.append(Item(pid, "component", None, part.mass_g, role=part.name, cg=pos))
    ports = [port for _, port in _port_geometry(spec, p, mech)]
    if any(pt.get("extension") for pt in ports):
        ext = C.get("usb_c_panel_ext")
        items.append(Item("usb_c_panel_ext", "component", None, ext.mass_g, role=ext.name,
                          cg=((p.stack_x + p.usb_port[0]) / 2, p.fus_half_w - 6, p.usb_port[1])))
        notes.append(f"USB-C brought out to the left side of the fuselage at x = {p.usb_port[0]} mm with a short "
                     "extension: the FC's own port faces the front-left duct")
    # battery: placed on the plate behind the stack so the CG lands on the thrust centre
    bl, bw, bh = bat.envelope_mm
    x_min = p.plate_x[0] + bl / 2 - 5.0          # may overhang the plate's end by 5 mm, into the tail (checked)
    from .geom.airframe import half_width_at
    boss_y = half_width_at(p, p.plate_x[0] + 3.5, p.frame_t + 1.0) - p.skin_t - 1.6 - 2.4
    if bw / 2 + 0.3 > boss_y:                    # a wide pack must also stay ahead of the rear shell screw bosses
        x_min = p.plate_x[0] + bl / 2 + 6.5
    # the pack's XT30 (lead + mated connector, 18 mm) sits between the pack and the ESC
    x_max = p.stack_x - esc.envelope_mm[0] / 2 - 1.0 - 18.0 - bl / 2
    if battery_x is None:
        others = [(i.name, i.mass_g, i.cg) for i in items]
        want = calc.battery_position_for_cg(others, bat.mass_g, 0.0)
        battery_x = max(x_min, min(x_max, want))
        if abs(battery_x - want) > 0.5:
            notes.append(f"Battery would need x = {want:.1f} mm to put the CG on the thrust centre but the bay allows "
                         f"{x_min:.1f}…{x_max:.1f} mm; placed at {battery_x:.1f} mm")
    bat_sh = Pos(battery_x, 0, p.frame_t) * G.battery(bat.envelope_mm, bat.data)
    items.append(Item("battery", "component", bat_sh, bat.mass_g, colour=(0.85, 0.75, 0.1), role=bat.name,
                      cg=(battery_x, 0.0, p.frame_t + bh / 2)))
    boards = {}
    if mech:
        boards["fc"] = {"mech": mech, "centre": (p.stack_x, 0.0), "z_bottom": z_fc, "rotation": rotation}
    return Model(spec, p, items, notes, ports, boards)
