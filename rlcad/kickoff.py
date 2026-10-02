"""Mechanical kickoff and teaching material.

kickoff: from an idea to the questions, the manufacturing route, the pitfalls and a design folder — and whether
RL CAD has a parametric family for it (ducted quad, enclosure) or the engineer designs it in FreeCAD/Onshape with
RL CAD reviewing the parts (review_part works on any STEP/STL).

RULES: what each check protects against and how it is usually fixed, so the AI can teach rather than just report.
"""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

PROCESS_GUIDE = [
    "1–50 parts: FDM printing (PLA for prototypes, PETG for parts that see heat or impact, ASA outdoors)",
    "50–500: printing still, or SLS nylon for strong, support-free parts; CNC aluminium for loaded parts",
    "500+: injection molding pays off (a prototype aluminium mold is a few thousand USD); design for it early: draft, "
    "even walls, no undercuts (review_part process='injection_molding' checks these)",
]

ARCHETYPES: Dict[str, Dict] = {
    "enclosure": {
        "title": "Enclosure for a circuit board", "family": "enclosure",
        "keywords": "enclosure case box housing cover shell casing board pcb electronics",
        "questions": ["Which board goes inside (its RL PCB / KiCad project)?", "Which connectors must be reachable "
                      "from outside, and which buttons, LEDs or displays must show?", "Indoor or outdoor? Splash or "
                      "dust protection (IP rating)?", "Screwed lid or snap fit? Will it be opened often?",
                      "Does anything get warm (regulators, motor drivers)?"],
        "pitfalls": ["Connector openings that do not line up after a board revision: link the board, RL CAD follows "
                     "its mech.json", "Screw bosses that crack: wall ≥ 2× the pilot hole, or heat-set inserts",
                     "PLA softening in a hot car or near a regulator: PETG or ASA"],
    },
    "drone": {
        "title": "Drone airframe", "family": "ducted_quad_f35",
        "keywords": "drone quad quadcopter uav multirotor fpv airframe frame ducted cinewhoop",
        "questions": ["Prop size and battery (they set the frame size)", "Ducted or open props?", "Flight controller "
                      "board (RL PCB project)?", "Printer bed size"],
        "pitfalls": ["Arm stiffness (gyro noise)", "CG off the thrust centre", "Connectors unreachable once closed"],
    },
    "bracket": {
        "title": "Bracket, mount or holder", "family": None,
        "keywords": "bracket mount holder clamp adapter plate stand hook clip support",
        "questions": ["What loads (direction, size, vibration)?", "What does it attach to and with which screws?",
                      "How many?"],
        "pitfalls": ["Printed layers split under loads that pull them apart: orient so the load runs along the layers",
                     "Sharp inside corners concentrate stress: fillet them", "Screw holes printed undersize: drill"],
    },
    "printer_mechanics": {
        "title": "Printer mechanics (paper path, frame, rollers)", "family": None,
        "keywords": "printer paper feed roller platen cutter print head thermal receipt laser chassis frame",
        "questions": ["Thermal (receipt/label) or laser/inkjet?", "Paper width and roll size?", "Which motors and "
                      "print head (their datasheets give the mounting and the roller geometry)?"],
        "pitfalls": ["Paper path tolerances: roller parallelism matters more than absolute size",
                     "Bearings and shafts are bought parts: design around their standard sizes",
                     "Start with a thermal printer: no fuser (mains, heat) and no high voltage"],
    },
    "robot": {
        "title": "Robot / mechanism", "family": None,
        "keywords": "robot arm gripper joint gearbox actuator mechanism linkage wheel chassis rover",
        "questions": ["Degrees of freedom, payload, speed?", "Which motors/servos (their datasheets set the "
                      "interfaces)?", "Bought bearings and shafts?"],
        "pitfalls": ["Backlash and play add up joint by joint", "Printed gears wear fast under load: buy them or "
                     "print in nylon"],
    },
}


def brief(idea: str, archetype: str = "") -> Dict:
    stop = {"a", "an", "the", "for", "my", "of", "to", "and", "with", "on", "in", "i", "want", "build", "make"}
    w = set(re.findall(r"[a-z]+", (idea or "").lower())) - stop
    ranked = sorted(((len(w & set(a["keywords"].split())), k) for k, a in ARCHETYPES.items()), reverse=True)
    aid = archetype or (ranked[0][1] if ranked and ranked[0][0] else "")
    if aid and aid not in ARCHETYPES:
        raise ValueError(f"unknown archetype {aid}; known: {', '.join(ARCHETYPES)}")
    base = {"idea": idea, "manufacturing": PROCESS_GUIDE,
            "candidates": [{"id": k, "title": ARCHETYPES[k]["title"], "score": s} for s, k in ranked if s][:3]}
    if not aid:
        return dict(base, archetype=None, questions=["What must it do, what does it attach to, what loads?",
                                                     "How many, and made how?"],
                    known=list(ARCHETYPES))
    a = ARCHETYPES[aid]
    if a["family"]:
        how = (f"RL CAD has a parametric family for this ('{a['family']}'): kickoff_apply creates the design folder; "
               "then link the board (spec_set_board) and build_and_check.")
    else:
        how = ("RL CAD has no parametric family for this yet. Design it in FreeCAD or Onshape; RL CAD reviews each "
               "part you export (review_part with a .step/.stl path: printability or moldability, with reasons). "
               "Its interface to the electronics is the board's mech.json.")
    return dict(base, archetype=aid, title=a["title"], family=a["family"], questions=a["questions"],
                pitfalls=a["pitfalls"], how=how,
                structure=["<design>/rlcad.json (the spec)", "<design>/electronics/ (or a link to the board's "
                           "KiCad project)", "<design>/docs/requirements.md", "<design>/out/ (exports, made by RL CAD)"])


def apply(folder: str, name: str, archetype: str, requirements: Optional[Dict] = None, idea: str = "",
          board: str = "") -> Dict:
    from .project import Spec
    a = ARCHETYPES.get(archetype)
    if not a or not a["family"]:
        raise ValueError(f"'{archetype}' has no RL CAD family; design it in FreeCAD/Onshape and use review_part")
    os.makedirs(folder, exist_ok=True)
    sp = Spec(name=name, kind=a["family"], requirements=dict(requirements or {}, idea=idea) if idea else
              dict(requirements or {}))
    if board:
        rel = os.path.relpath(os.path.abspath(board), folder)
        sp.boards["main" if a["family"] == "enclosure" else "fc"] = {"project": rel, "rotation": 0}
    if a["family"] == "enclosure":
        sp.parts = {}
    sp.save(folder)
    os.makedirs(os.path.join(folder, "docs"), exist_ok=True)
    with open(os.path.join(folder, "docs", "requirements.md"), "w", encoding="utf-8") as f:
        f.write(f"# {name}\n\n{idea}\n\n## Open questions\n\n" + "".join(f"- [ ] {q}\n" for q in a["questions"])
                + "\n## Pitfalls\n\n" + "".join(f"- {p}\n" for p in a["pitfalls"]))
    return {"folder": folder, "kind": a["family"], "spec": Spec.path(folder),
            "next": "build_and_check" if board or a["family"] != "enclosure" else
                    "spec_set_board(project='<KiCad project folder>', slot='main'), then build_and_check"}


RULES = {
    "bed_fit": ("every printed part fits the printer's bed in some orientation",
                "split the part, shrink it, or choose a bigger printer"),
    "prop_clearance": ("the spinning prop (as a disc, with margin) touches nothing",
                       "more tip gap, or move the duct around the prop plane"),
    "interference": ("no two parts occupy the same space (glued joints are reported as info)",
                     "move or resize one of them; the message names both"),
    "connector_access": ("a real plug can reach each connector that must be used with the product closed",
                         "an opening in line with it, an extension cable, or rotate the board"),
    "board_mount": ("the board's mounting holes line up with the product's standoffs",
                    "move the holes in KiCad or the standoffs here"),
    "board_height": ("the tallest parts on each side of the board fit the space above and below it",
                     "more room (fus_top_z / gap_above) or lower parts"),
    "board_fit": ("the board's outline fits the space at its height", "smaller board or more room"),
    "cg": ("the centre of gravity is on the thrust centre", "move the battery or the stack"),
    "propulsion": ("thrust-to-weight ≥ 2 and currents within ratings", "lighter parts, bigger props, other motors"),
    "arm_stiffness": ("the arms are stiff enough that their bending mode is above the gyro's noise band",
                      "taller rib, stiffer material, or carbon plate"),
    "solid": ("each printed part is one valid, closed body", "undo the change that split it"),
    "printability": ("walls are thick enough for the nozzle", "thicker walls"),
    "print_thin": ("no wall thinner than two extrusion lines (or one, for an error)", "thicken the area named"),
    "print_overhang": ("no overhang beyond 45° needs support in the export orientation",
                       "chamfer under it, reorient, or accept supports"),
    "print_mesh": ("the STL is closed", "undo the change that opened it"),
    "print_bed": ("enough first-layer contact for the part's height", "brim, or another orientation"),
    "prop_fit": ("the prop's bore matches the motor's shaft", "a matching prop (parts_compatible)"),
    "motor_fit": ("the motor's base sits on its pad", "a bigger pad or another motor"),
    "battery_fit": ("the battery fits even at the top of its size tolerance", "a bigger bay, or measure your pack"),
    "power_esc": ("the ESC's current covers the motors", "a stronger ESC"),
    "power_battery": ("the pack's C rating covers full throttle", "a higher-C or larger pack"),
    "power_connector": ("the battery connector's rating covers the current", "XT60 for higher currents"),
    "power_voltage": ("motor and ESC accept the battery's cell count", "matching parts"),
    "motor_leads": ("the motor wires reach the ESC", "extend them"),
}


def explain_rule(rule: str) -> Dict:
    r = RULES.get(rule)
    if not r:
        raise ValueError(f"unknown rule {rule}; known: {', '.join(sorted(RULES))}")
    return {"rule": rule, "protects_against": r[0], "usual_fixes": r[1]}
