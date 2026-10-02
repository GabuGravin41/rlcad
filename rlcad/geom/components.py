"""Bought components, modelled from their datasheet dimensions (catalog data) so the airframe is designed around the
real parts: motor body, bell and shaft; propeller hub and blades; ESC and receiver boards; the battery pack with its
XT30 connector.

The models are for fit, clearance and the assembly view, not for manufacture. Each function takes the catalog
`data` dict (plus envelope/mass where needed) and returns a solid in the part's own frame:
  motor     base centred on the origin, sitting on z = 0 (the frame's top face), shaft up +z
  prop      hub mid-plane at z = 0, bore on the z axis
  battery   pack centred in x/y, bottom at z = 0, leads leaving at +x
"""
from __future__ import annotations

import math

from build123d import (Align, Box, Cylinder, Ellipse, Plane, Pos, Rot, fillet, loft)

C_MIN = (Align.CENTER, Align.CENTER, Align.MIN)


def motor(data: dict):
    """Outrunner: fixed base (with the M2 pattern underneath), rotating bell with a chamfered top, shaft."""
    base_d, base_h = data.get("base_d", 15.0), data.get("base_h", 1.5)
    bell_d, body_h = data["bell_d"], data["height"]
    shaft_d, shaft_len = data.get("shaft_d", 1.5), data.get("shaft_len", 4.5)
    gap = 0.4                                         # the bell runs just above the base
    base = Cylinder(base_d / 2, base_h, align=C_MIN)
    bell_h = body_h - base_h - gap
    bell = Pos(0, 0, base_h + gap) * Cylinder(bell_d / 2, bell_h, align=C_MIN)
    try:
        top = bell.edges().sort_by(lambda e: e.center().Z)[-1]
        bell = fillet(top, min(1.2, bell_h / 4))
    except Exception:  # noqa
        pass
    shaft = Cylinder(shaft_d / 2, body_h + shaft_len, align=C_MIN)      # runs through: one solid
    return base + bell + shaft


def prop(data: dict, cw: bool = True):
    """Tri-blade (or n-blade) prop: hub with the bore, twisted blades with the listed maximum chord."""
    d = data["diameter_mm"]
    r = d / 2
    hub_h = data.get("hub_h", 5.5)
    hub_r = data.get("hub_d", 6.5) / 2
    chord = data.get("max_chord_mm", 8.5)
    bore = data.get("bore_d", 1.5)
    blades = int(data.get("blades", 3))
    hub = Pos(0, 0, -hub_h / 2) * Cylinder(hub_r, hub_h, align=C_MIN)
    sign = 1 if cw else -1
    stations = [(hub_r * 0.8 / r, 0.55 * chord, 38.0), (0.35, chord, 25.0), (0.65, 0.92 * chord, 17.0),
                (0.90, 0.65 * chord, 12.0), (0.99, 0.28 * chord, 10.0)]
    secs = []
    for f, c, pitch in stations:
        pl = Plane(origin=(f * r, 0, 0), x_dir=(0, 1, 0), z_dir=(1, 0, 0))
        secs.append(pl * Rot(0, 0, sign * pitch) * Ellipse(c / 2, 0.6))     # 1.2 mm thick blade
    blade = loft(secs)
    body = hub
    for k in range(blades):
        body = body + Rot(0, 0, 360.0 * k / blades) * blade
    return body - Cylinder(bore / 2, hub_h + 2)


def board(env, holes: float = 0.0, hole_d: float = 3.2):
    """A PCB-sized block with its mounting holes (ESC, receiver)."""
    w, l, h = env
    b = Box(w, l, h, align=C_MIN)
    if holes:
        for sx in (-1, 1):
            for sy in (-1, 1):
                b = b - Pos(sx * holes / 2, sy * holes / 2, -1) * Cylinder(hole_d / 2, h + 2, align=C_MIN)
    return b


def battery(env, data: dict, lead_room: float = 0.0):
    """LiPo pack with rounded long edges, the discharge lead and a mated XT30 ahead of its +x end."""
    L, W, H = env
    pack = Box(L, W, H, align=C_MIN)
    try:
        pack = fillet(pack.edges().filter_by(lambda e: abs(e.tangent_at().X) > 0.9), 1.5)
    except Exception:  # noqa
        pass
    # 16 AWG lead pair leaving the pack's end, and the XT30 (mated plug + socket ≈ 16 × 10.2 × 5.2 mm)
    lead = Pos(L / 2, 0, H / 2) * Box(2.0, 6.0, 2.5, align=(Align.MIN, Align.CENTER, Align.CENTER))
    xt30 = Pos(L / 2 + 2.0, 0, H / 2) * Box(16.0, 10.2, 5.2, align=(Align.MIN, Align.CENTER, Align.CENTER))
    return pack + lead + xt30
