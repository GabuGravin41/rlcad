"""Engineer-level features on top of a generated part: holes, bosses, pads, pockets and ribs.

The parametric family builds each part; features let the engineer (or the AI, in the mode the engineer allows) add
the local details a real product needs — a cable hole, a mounting boss for a sensor, a pad for a label, a pocket
for a magnet, a stiffening rib — without leaving the spec-driven flow. They are stored in rlcad.json under
"features", applied after the part is generated, and checked like everything else (solid, interference, print audit).

Coordinates are the assembly frame in mm (X forward, Y left, Z up), the same frame the checks report.
"""
from __future__ import annotations

import math
from typing import Dict, List

TYPES = {
    "hole": "round hole: at [x,y,z], axis x|y|z, d, depth (0 = through the part)",
    "boss": "cylindrical boss: at = centre of its base, axis, od, height, hole_d (0 = solid)",
    "pad": "rectangular extrusion: at = centre of its base, size [w, l, h] along x, y, z (h along axis z)",
    "pocket": "rectangular cut: at = centre, size [w, l, h]",
    "rib": "stiffening rib: from [x,y,z] to [x,y,z] (its base line), thickness, height (up, +z)",
}


def validate(f: Dict) -> List[str]:
    t = f.get("type")
    errs = []
    if t not in TYPES:
        return [f"type must be one of {', '.join(TYPES)}"]
    if not f.get("part"):
        errs.append("part is required (a printed part name, e.g. fuselage_centre)")
    need = {"hole": ["at", "d"], "boss": ["at", "od", "height"], "pad": ["at", "size"], "pocket": ["at", "size"],
            "rib": ["from", "to", "thickness", "height"]}[t]
    errs += [f"{k} is required for a {t}" for k in need if f.get(k) in (None, "", [])]
    if f.get("axis", "z") not in ("x", "y", "z"):
        errs.append("axis must be x, y or z")
    return errs


def _orient(axis: str):
    from build123d import Rot
    return {"z": Rot(0, 0, 0), "x": Rot(0, 90, 0), "y": Rot(-90, 0, 0)}[axis]


def apply(shape, feats: List[Dict]):
    """Apply the features (in order) to one part's shape."""
    from build123d import Align, Box, Cylinder, Pos, Rot
    for f in feats:
        t = f["type"]
        ax = f.get("axis", "z")
        if t == "hole":
            depth = f.get("depth") or 400.0
            align = (Align.CENTER, Align.CENTER, Align.CENTER if not f.get("depth") else Align.MAX)
            cut = Pos(*f["at"]) * _orient(ax) * Cylinder(f["d"] / 2, depth, align=align)
            shape = shape - cut
        elif t == "boss":
            b = Pos(*f["at"]) * _orient(ax) * Cylinder(f["od"] / 2, f["height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
            shape = shape + b
            if f.get("hole_d"):
                shape = shape - Pos(*f["at"]) * _orient(ax) * Cylinder(f["hole_d"] / 2, f["height"] + 0.2,
                                                                        align=(Align.CENTER, Align.CENTER, Align.MIN))
        elif t == "pad":
            w, l, h = f["size"]
            shape = shape + Pos(*f["at"]) * Box(w, l, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
        elif t == "pocket":
            w, l, h = f["size"]
            shape = shape - Pos(*f["at"]) * Box(w, l, h)
        elif t == "rib":
            (x0, y0, z0), (x1, y1, z1) = f["from"], f["to"]
            L = math.hypot(x1 - x0, y1 - y0)
            ang = math.degrees(math.atan2(y1 - y0, x1 - x0))
            shape = shape + Pos((x0 + x1) / 2, (y0 + y1) / 2, min(z0, z1)) * Rot(0, 0, ang) * Box(
                L, f["thickness"], f["height"], align=(Align.CENTER, Align.CENTER, Align.MIN))
    return shape
