"""Fix playbook: for every check rule, the concrete changes that usually resolve it.

A finding tells the model *what* is wrong; this module tells it *what to try*, as ready-to-run tool calls in the order
an experienced designer would try them. A smaller model does not have to invent a repair: it can pick the first fix
(or let `try_fix` apply it, rebuild and keep it only if the design got better).

Each fix: {"tool": <agent tool>, "args": {...}, "why": <one line>, "effect": <what should change in the numbers>}.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from .. import catalog as C

# which parameters move which parts (for interference between two named parts)
PART_PARAMS = {
    "fuselage": [("fus_half_w", +1.5, "widen the fuselage"), ("fus_top_z", +2.0, "raise the fuselage roof")],
    "canopy": [("fus_top_z", +2.0, "raise the spine the canopy sits on")],
    "pod": [("duct_dx", +2.0, "move the ducts outward along x"), ("wing_margin", +1.0, "more room around the ducts")],
    "frame": [("rib_h", -1.0, "lower the arm ribs"), ("plate_half_w", -1.0, "narrow the centre plate")],
    "fin": [("fin_cant_deg", +3.0, "cant the fins further out"), ("fin_h", -3.0, "shorter fins")],
    "esc": [("stack_x", +3.0, "move the stack forward")],
    "fc": [("stack_x", +3.0, "move the stack forward"), ("fus_top_z", +2.0, "more room above the board")],
    "receiver": [("stack_x", -2.0, "move the stack (and receiver) back")],
    "battery": [("fus_half_w", +1.5, "widen the battery bay")],
    "motor": [("duct_z0", +1.0, "raise the ducts above the motors")],
    "prop": [("tip_gap", +0.5, "more tip clearance in the duct"), ("duct_z0", -1.0, "move the duct around the prop plane")],
}


def _p(params, name, default=None):
    return getattr(params, name, default)


def _param_fix(params, name, delta, why, effect=""):
    cur = _p(params, name)
    if cur is None or isinstance(cur, (tuple, list)):
        return None
    return {"tool": "spec_set_params", "args": {"params": {name: round(cur + delta, 2)}},
            "why": f"{why} ({name} {cur} → {round(cur + delta, 2)})", "effect": effect}


def _ack(rule, reason):
    return {"tool": "decision_add", "args": {"text": f"ACK {rule}: {reason}"},
            "why": "accept the warning with a recorded reason (only if the engineer agrees)", "effect": "warning marked acknowledged"}


def compatible_parts(spec, role: str) -> List[Dict]:
    """Catalog parts for `role` that work with the other parts already chosen (shaft/bore, cells, current, size)."""
    chosen = {r: spec.part(r) for r in ("motor", "prop", "esc", "battery", "fc", "receiver")}
    out = []
    for pid, part in C.CATALOG.items():
        if part.kind != role:
            continue
        why, ok = [], True
        d = part.data
        m, pr, e, b = (chosen[r].data for r in ("motor", "prop", "esc", "battery"))
        if role == "prop" and d.get("bore_d") and m.get("shaft_d"):
            ok &= abs(d["bore_d"] - m["shaft_d"]) < 0.05
            why.append(f"bore {d['bore_d']} vs shaft {m['shaft_d']}")
        if role == "motor":
            if d.get("shaft_d") and pr.get("bore_d"):
                ok &= abs(d["shaft_d"] - pr["bore_d"]) < 0.05
                why.append(f"shaft {d['shaft_d']} vs prop bore {pr['bore_d']}")
            if d.get("cells") and b.get("cells"):
                ok &= d["cells"][0] <= b["cells"] <= d["cells"][-1]
                why.append(f"{d['cells'][0]}–{d['cells'][-1]}S vs battery {b['cells']}S")
            if e.get("cont_current_a") and d.get("max_current_a"):
                ok &= d["max_current_a"] <= e["cont_current_a"]
        if role == "esc":
            if d.get("cont_current_a") and m.get("max_current_a"):
                ok &= d["cont_current_a"] >= m["max_current_a"]
                why.append(f"{d['cont_current_a']} A vs motor {m['max_current_a']} A")
            if d.get("cells") and b.get("cells"):
                ok &= d["cells"][0] <= b["cells"] <= d["cells"][-1]
        if role == "battery":
            for other, lab in ((m, "motor"), (e, "ESC")):
                if other.get("cells") and d.get("cells"):
                    ok &= other["cells"][0] <= d["cells"] <= other["cells"][-1]
                    why.append(f"{d['cells']}S vs {lab} {other['cells'][0]}–{other['cells'][-1]}S")
        out.append({"id": pid, "name": part.name, "compatible": bool(ok), "checks": why, "mass_g": part.mass_g,
                    "envelope_mm": list(part.envelope_mm), "source": part.source})
    out.sort(key=lambda r: (not r["compatible"], r["mass_g"]))
    return out


def fixes_for(f: Dict, spec, params) -> List[Dict]:
    """Ordered candidate fixes for one finding."""
    rule, refs, msg = f["rule"], f.get("refs", []), f.get("message", "")
    fx: List[Optional[Dict]] = []
    if rule == "bed_fit":
        part = refs[0] if refs else ""
        if part.startswith("pod"):
            fx.append(_param_fix(params, "span_margin", -5.0, "shorter wing tips", "pod footprint −5 mm"))
        if part.startswith("fuselage_nose"):
            fx.append(_param_fix(params, "nose_x", -10.0, "shorter nose", "nose −10 mm"))
        if part == "frame":
            fx.append(_param_fix(params, "duct_dx", -3.0, "ducts closer together", "frame −6 mm long"))
        fx.append({"tool": "spec_set_printer", "args": {"printer": "bambu_a1"}, "why": "a bigger bed (256 mm)",
                   "effect": "every part fits"})
    elif rule == "prop_clearance":
        if "tip gap" in msg:
            fx.append(_param_fix(params, "tip_gap", +0.5, "more room between the prop tips and the duct", "tip gap +0.5 mm"))
        else:
            fx.append(_param_fix(params, "duct_depth", +3.0, "deeper duct so the prop plane is inside the straight part"))
            fx.append(_param_fix(params, "duct_z0", -1.0, "lower the duct around the prop"))
    elif rule == "interference":
        if "glued joint" in msg:
            return []
        for r in refs:
            for name, delta, why in PART_PARAMS.get(r.split("_")[0], []):
                fx.append(_param_fix(params, name, delta, f"{why} ({r})"))
        fx.append({"tool": "render", "args": {"what": "inside"}, "why": "look at where the parts meet", "effect": ""})
    elif rule in ("connector_access", "board_ports"):
        fx.append({"tool": "spec_set_params", "args": {"params": {"usb_port": [0.0, 25.0]}},
                   "why": "bring the USB-C out to the fuselage side with an extension (socket above the wing roots)",
                   "effect": "connector reachable"})
        bd = (getattr(spec, "boards", {}) or {}).get("fc")
        if bd:
            fx.append({"tool": "spec_set_board", "args": {"slot": "fc", "project": bd["project"],
                                                          "rotation": (bd.get("rotation", 0) + 90) % 360},
                       "why": "turn the board so the connector faces another side", "effect": "connector edge changes"})
    elif rule == "board_height":
        fx.append(_param_fix(params, "fus_top_z", +2.0, "raise the fuselage roof over the board"))
    elif rule == "board_fit":
        fx.append(_param_fix(params, "fus_half_w", +1.5, "widen the fuselage around the board"))
    elif rule == "board_mount":
        fx.append({"tool": "spec_set_params", "args": {"params": {"stack_pattern": 30.5}},
                   "why": "match the stack pattern to the board's holes (or move the board's holes in RL PCB)", "effect": ""})
    elif rule == "arm_stiffness":
        fx.append(_param_fix(params, "rib_h", +1.5, "taller arm rib", "first mode up ~10–15 %"))
        fx.append(_param_fix(params, "arm_w", +2.0, "wider arms"))
        fx.append({"tool": "spec_set_printer", "args": {"materials": {"frame": "PETG-CF"}}, "why": "stiffer filament",
                   "effect": "first mode ~+40 %"})
        fx.append(_ack(rule, "first flights on this frame; carbon plate from frame.dxf if the gyro trace is noisy"))
    elif rule == "solid":
        fx.append({"tool": "render", "args": {"what": refs[0] if refs else "assembly"},
                   "why": "look at the part; undo the last parameter change that affected it", "effect": ""})
    elif rule == "print_thin":
        part = refs[0] if refs else ""
        if part.startswith("fuselage"):
            fx.append(_param_fix(params, "skin_t", +0.2, "thicker skin"))
        elif part.startswith("pod"):
            fx.append(_param_fix(params, "wing_tip_t", +0.3, "thicker wing tips"))
            fx.append(_param_fix(params, "te_min", +0.2, "blunter trailing edges"))
        elif part.startswith("fin"):
            fx.append(_param_fix(params, "fin_tip_t", +0.3, "thicker fin tips"))
        fx.append(_param_fix(params, "duct_wall", +0.2, "thicker duct wall"))
    elif rule == "print_overhang":
        part = refs[0] if refs else ""
        if part.startswith("pod"):
            fx.append({"tool": "spec_set_params", "args": {"params": {"wing_z": _p(params, "duct_z0")}},
                       "why": "put the wing's flat underside on the duct exit plane, so the pod prints flat",
                       "effect": "no support under the wing"})
        fx.append(_ack(rule, "print with tree supports under the flagged area"))
    elif rule == "print_mesh":
        fx.append({"tool": "render", "args": {"what": refs[0] if refs else "assembly"},
                   "why": "an open mesh comes from a boolean between touching faces; undo the last change to this part",
                   "effect": ""})
    elif rule == "print_bed":
        fx.append(_ack(rule, "print with a brim"))
    elif rule in ("prop_fit", "motor_fit"):
        role = "prop" if rule == "prop_fit" else "motor"
        for c in [c for c in compatible_parts(spec, role) if c["compatible"]][:2]:
            fx.append({"tool": "spec_set_part", "args": {"role": role, "part_id": c["id"]},
                       "why": f"{c['name']} fits ({'; '.join(c['checks'])})", "effect": "fit error gone"})
    elif rule == "battery_fit":
        fx.append(_param_fix(params, "fus_half_w", +1.0, "a wider battery bay"))
        fx.append(_ack(rule, "measured pack is within the bay"))
    elif rule in ("power_esc", "power_voltage", "power_battery"):
        role = {"power_esc": "esc", "power_voltage": "esc", "power_battery": "battery"}[rule]
        for c in [c for c in compatible_parts(spec, role) if c["compatible"]][:2]:
            fx.append({"tool": "spec_set_part", "args": {"role": role, "part_id": c["id"]},
                       "why": f"{c['name']} ({'; '.join(c['checks'])})", "effect": "rating sufficient"})
    elif rule == "power_connector":
        fx.append(_ack(rule, "full-throttle bursts are short; XT30 is standard on this pack size"))
    elif rule == "motor_leads":
        fx.append(_ack(rule, "extend the motor leads with 26 AWG silicone wire"))
    elif rule == "cg":
        import re
        m = re.search(r"CG is ([+-][0-9.]+) mm \(x\)", msg)
        if m:
            dx = float(m.group(1))
            # the battery is already at the end of its bay: move the stack (ESC, FC, receiver) the other way
            fx.append(_param_fix(params, "stack_x", -3.0 if dx > 0 else +3.0,
                                 "move the stack to pull the CG back to the thrust centre", "CG x towards 0"))
            fx.append({"tool": "parts_compatible", "args": {"role": "battery"},
                       "why": "a heavier or lighter pack moves the CG further", "effect": ""})
        else:
            fx.append(_param_fix(params, "duct_z0", +1.0, "raise the ducts and props above the CG"))
    elif rule == "propulsion":
        if "ESC" in msg:
            role = "esc"
        elif " C, battery" in msg:
            role = "battery"
        else:
            role = "motor"
        for c in [c for c in compatible_parts(spec, role) if c["compatible"]][:3]:
            fx.append({"tool": "spec_set_part", "args": {"role": role, "part_id": c["id"]},
                       "why": f"{c['name']}", "effect": "check T/W and current again"})
        fx.append({"tool": "calc_propulsion", "args": {"auw_g": 0}, "why": "what-if before rebuilding (set auw_g)",
                   "effect": ""})
    elif rule == "printability":
        import re
        m = re.match(r"(\w+) = ([0-9.]+) mm", msg)
        if m:
            fx.append(_param_fix(params, m.group(1), +0.4, "thicker, for a 0.4 mm nozzle"))
    elif rule == "thrust":
        for c in [c for c in compatible_parts(spec, "motor") if c["compatible"]][:2]:
            fx.append({"tool": "spec_set_part", "args": {"role": "motor", "part_id": c["id"]}, "why": c["name"],
                       "effect": "more thrust"})
    return [x for x in fx if x]


def annotate(findings: List[Dict], spec, params) -> None:
    """Add a `fixes` list to every error and unacknowledged warning (in place)."""
    for f in findings:
        if f["severity"] in ("error", "warning") and not f.get("acknowledged"):
            fx = fixes_for(f, spec, params)
            if fx:
                f["fixes"] = fx
