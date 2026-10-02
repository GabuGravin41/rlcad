"""Where the PCB and the CAD meet.

RL PCB describes each board in <project>/<board>.mech.json ("rl-mech/1": outline, holes, connectors and the edge
they face, part heights per side, mass). RL CAD places the board, checks it against the airframe, and writes back
<project>/enclosure.json ("rl-envelope/1": the space the product gives the board). RL PCB's `mech_check` reads that.
The two tools never import each other for this; the JSON files are the contract. When RL PCB is importable, RL CAD
refreshes a stale mech.json from the .kicad_pcb itself.

Spec entry (rlcad.json):
    "boards": {"fc": {"project": "electronics/rl_fc_f405"}}
"""
from __future__ import annotations

import glob
import json
import os
from typing import Dict, Optional

ENVELOPE_SCHEMA = "rl-envelope/1"
EDGE_DIR = {"+x": (1, 0), "-x": (-1, 0), "+y": (0, 1), "-y": (0, -1)}


class MechError(RuntimeError):
    pass


def _project(folder: str, entry: Dict):
    proj = entry["project"]
    proj = proj if os.path.isabs(proj) else os.path.join(folder, proj)
    if os.path.isfile(proj):
        proj = os.path.dirname(proj)
    pcbs = [p for p in glob.glob(os.path.join(proj, "*.kicad_pcb"))
            if not any(t in os.path.basename(p) for t in (".placed.", ".routed.", ".finished."))]
    return proj, (pcbs[0] if pcbs else None)


def load_board(folder: str, entry: Dict, refresh: bool = True) -> Dict:
    """mech.json for a board slot (regenerated from the .kicad_pcb when stale and RL PCB is available)."""
    proj, pcb = _project(folder, entry)
    name = os.path.splitext(os.path.basename(pcb))[0] if pcb else entry.get("name", "board")
    mpath = os.path.join(proj, name + ".mech.json")
    stale = pcb and (not os.path.exists(mpath) or os.path.getmtime(pcb) > os.path.getmtime(mpath))
    note = None
    if stale and refresh:
        try:
            from rlpcb.pcb.mech import export_mechanical
            export_mechanical(pcb, mpath)
            note = f"{os.path.basename(mpath)} regenerated from {os.path.basename(pcb)} (RL PCB)"
        except ImportError:
            note = (f"{os.path.basename(mpath)} is older than the board and RL PCB is not installed here; run RL PCB's "
                    "mech_export")
    if not os.path.exists(mpath):
        raise MechError(f"{mpath} not found. Export it with RL PCB (mech_export) or install RL PCB alongside RL CAD.")
    with open(mpath, encoding="utf-8") as f:
        mech = json.load(f)
    if mech.get("schema") != "rl-mech/1":
        raise MechError(f"{mpath}: unknown schema {mech.get('schema')}")
    # the best 3D model available: KiCad export with component models, else the bare board
    steps = [os.path.join(proj, "fab", name + ".step"), os.path.join(proj, name + ".step"),
             os.path.join(proj, "fab", name + "_board.step")]
    mech["step"] = next((s for s in steps if os.path.exists(s)), None)
    mech["project_dir"] = proj
    mech["pcb"] = pcb
    mech["_note"] = note
    return mech


def ports_from_mech(mech: Dict):
    """Connectors a person must reach from outside (plug_mm set), in the board frame."""
    out = []
    w, l = mech["outline_mm"]["size"]
    t = mech["thickness_mm"]
    for c in mech["connectors"]:
        if not c.get("plug_mm") or not c.get("edge") or not c.get("populated", True):
            continue
        dx, dy = EDGE_DIR[c["edge"]]
        x, y = c["at_mm"]
        # the mouth sits on the board edge (plus any overhang), centred on the connector's height
        if dx:
            x = dx * (w / 2 + c.get("overhang_mm", 0))
        else:
            y = dy * (l / 2 + c.get("overhang_mm", 0))
        z = t + c["height_mm"] / 2 if c["side"] == "top" else -c["height_mm"] / 2
        out.append({"ref": c["ref"], "mate": c["mate"], "at": (x, y, z), "dir": (dx, dy, 0), "plug_mm": tuple(c["plug_mm"])})
    return out


def envelope_path(project_dir: str, product: str) -> str:
    """Where this product's envelope for the board goes.

    A board can be used in more than one product (the drone's flight controller also has its own enclosure). The
    first product to claim `enclosure.json` keeps it; every other product writes `enclosure.<product>.json`, so one
    design never overwrites another's envelope. RL PCB's mech_check checks the board against all of them.
    """
    import re
    main = os.path.join(project_dir, "enclosure.json")
    try:
        with open(main, encoding="utf-8") as f:
            owner = json.load(f).get("product")
    except (OSError, ValueError):
        owner = None
    if owner in (None, "", product):
        return main
    return os.path.join(project_dir, "enclosure.%s.json" % re.sub(r"[^A-Za-z0-9_-]+", "_", product or "product"))


def write_envelope(mech: Dict, env: Dict) -> str:
    """Write this product's envelope into the board's project (see envelope_path); a change from the previous version
    is logged for RL PCB."""
    from .interface import envelope_diff, write_with_notice
    path = envelope_path(mech["project_dir"], env.get("product") or "")
    mech["_envelope_notice"] = write_with_notice(path, env, "cad", envelope_diff)
    return path


def check_with_rlpcb(mech: Dict, env: Dict) -> Optional[Dict]:
    try:
        from rlpcb.pcb.mech import check_envelope
    except ImportError:
        return None
    return check_envelope(mech, env)
