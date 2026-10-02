"""RL CAD tools for a language model (MCP or any tool-calling loop).

Same contract as RL PCB: the model never edits geometry directly. It edits the *spec* (parts, parameters, printer,
decisions); RL CAD builds the geometry, runs the engineering checks, and exports. Every tool returns JSON; errors come
back as {"error": ...} with a hint, never as a crash.
"""
from __future__ import annotations

import dataclasses
import json
import os
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from .. import catalog as C
from .. import calc


class UserError(Exception):
    pass


@dataclass
class Tool:
    name: str
    description: str
    schema: Dict[str, Any]
    fn: Callable
    writes: bool = False


def S(props: Dict[str, Any], required: Optional[List[str]] = None) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


STR, NUM, BOOL, OBJ = {"type": "string"}, {"type": "number"}, {"type": "boolean"}, {"type": "object"}


class Session:
    def __init__(self, folder: Optional[str] = None):
        self.folder: Optional[str] = None
        self.spec = None
        self.model = None
        self.result = None
        self.dirty = True
        self.exported = False
        if folder:
            self.open(folder)

    def open(self, folder):
        from ..project import Spec
        self.folder = os.path.abspath(folder)
        self.spec = Spec.load(self.folder)
        self.model, self.result, self.dirty, self.exported = None, None, True, False
        # resume the last build's results if the spec has not changed since (the geometry is rebuilt lazily)
        cp = os.path.join(self.folder, "out", "checks.json")
        try:
            with open(cp, encoding="utf-8") as f:
                last = json.load(f)
            if abs(last.get("spec_updated", -1) - self.spec.updated) < 1e-6:
                self.result, self.dirty = last["result"], False
                self.exported = last.get("exported", False)
        except (OSError, ValueError, KeyError):
            pass

    def save_state(self):
        d = os.path.join(self.folder, "out")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "checks.json"), "w", encoding="utf-8") as f:
            json.dump({"spec_updated": self.spec.updated, "result": self.result, "exported": self.exported}, f,
                      default=str)

    def need(self):
        if not self.spec:
            raise UserError("No project open. Call project_create (new) or project_open (existing folder) first.")
        return self.spec

    def changed(self):
        self.spec.save(self.folder)
        self.dirty, self.exported = True, False


TOOLS: List[Tool] = []


def tool(name: str, description: str, schema: Dict[str, Any], writes: bool = False):
    def deco(fn):
        TOOLS.append(Tool(name, description, schema, fn, writes))
        return fn
    return deco


# parameter documentation the model can read before changing anything
PARAM_DOCS = {
    "tip_gap": "prop tip to duct wall, mm (≥1.2 printed; smaller = more duct thrust, more risk of rubbing)",
    "duct_wall": "duct wall thickness, mm", "duct_lip_r": "inlet lip radius, mm (5–10 % of prop D)",
    "duct_z0": "duct bottom height above the frame bottom, mm (must clear the arm rib)",
    "duct_depth": "duct height, mm (≥30 % of prop D for thrust gain)",
    "duct_dx": "duct centres at x = ±duct_dx, mm (front/back spacing)",
    "fus_half_w": "fuselage half-width at the chine, mm (sets duct y spacing too)",
    "duct_to_fus_gap": "gap between duct outer wall and fuselage side, mm",
    "frame_t": "frame plate thickness, mm", "plate_half_w": "frame centre plate half-width, mm",
    "plate_x": "frame centre plate x range [min, max], mm (also where the fuselage splits into nose/centre/tail)",
    "arm_w": "arm width, mm", "rib_w": "arm stiffening rib width, mm", "rib_h": "arm stiffening rib height, mm",
    "stack_x": "FC/ESC stack centre x, mm", "stack_pattern": "stack hole spacing, mm (30.5 or 20)",
    "skin_t": "fuselage skin thickness, mm", "wing_t": "wing/tail plate thickness, mm",
    "wing_z": "wing plate bottom height, mm", "wing_sweep_deg": "wing leading-edge sweep, deg",
    "wing_le_root_ahead": "wing root LE ahead of the front duct centre, mm", "wing_tip_chord": "wing tip chord, mm",
    "tail_sweep_deg": "tailplane LE sweep, deg", "tail_tip_chord": "tailplane tip chord, mm",
    "nose_x": "nose tip x, mm", "tail_x": "tail end x, mm", "fus_top_z": "fuselage spine height, mm",
    "chine_z": "chine height, mm", "fin_cant_deg": "vertical fin cant, deg", "fin_h": "fin height, mm",
    "fit_clear": "slip-fit clearance between printed parts, mm",
    "usb_port": "[x, z] where the FC's USB-C is brought out to the left side with an extension; [] = hole at the "
                "FC's own connector (blocked by the front-left duct on this layout — connector_access checks it)",
}


# ------------------------------------------------------------------------------- environment / catalog
@tool("rlcad_environment", "Versions (build123d/OpenCascade), printers, materials, kicad-cli location and Onshape "
      "credential status.", S({}))
def t_env(s: Session):
    import build123d
    from ..adapters.kicad import find_kicad_cli
    return {"build123d": build123d.__version__, "printers": C.PRINTERS, "materials": C.MATERIALS,
            "kicad_cli": find_kicad_cli(), "onshape_keys_set": bool(os.environ.get("ONSHAPE_ACCESS_KEY")),
            "project": s.folder}


@tool("catalog_search", "Search the parts catalog (motors, props, ESCs, flight controllers, receivers, batteries). "
      "Every entry states its data source.", S({"kind": STR, "text": STR}))
def t_catalog(s: Session, kind: str = "", text: str = ""):
    return {"parts": C.search(kind or None, text)}


@tool("calc_propulsion", "What-if propulsion estimate without geometry: thrust, T/W, hover throttle/current, flight "
      "time for a motor/prop/battery at an all-up weight.",
      S({"motor": STR, "prop": STR, "battery": STR, "auw_g": NUM, "n_motors": NUM}, ["auw_g"]))
def t_calc_prop(s: Session, auw_g: float, motor: str = "motor_xing2_1404_4600kv", prop: str = "prop_gemfan_3016_3",
                battery: str = "lipo_3s_650", n_motors: int = 4):
    return calc.propulsion(C.get(motor).data, C.get(prop).data, C.get(battery).data, int(n_motors), auw_g)


# ------------------------------------------------------------------------------- project
KINDS = {"ducted_quad_f35": "F-35-style ducted quadcopter airframe around an RL PCB flight controller",
         "enclosure": "printed two-part enclosure built around any RL PCB board (link it with spec_set_board, slot "
                      "'main')"}


@tool("project_create", "Create a design folder with a spec (rlcad.json). kind: ducted_quad_f35 | enclosure. "
      "printer: one of the printers in rlcad_environment.",
      S({"folder": STR, "name": STR, "kind": STR, "printer": STR, "requirements": OBJ}, ["folder"]), writes=True)
def t_create(s: Session, folder: str, name: str = "", kind: str = "ducted_quad_f35", printer: str = "bambu_a1_mini",
             requirements: Optional[Dict] = None):
    from ..project import Spec
    if kind not in KINDS:
        raise UserError(f"unknown kind {kind}; RL CAD builds: {KINDS}")
    if printer not in C.PRINTERS:
        raise UserError(f"unknown printer {printer}; choose from {list(C.PRINTERS)}")
    os.makedirs(folder, exist_ok=True)
    sp = Spec(name=name or os.path.basename(os.path.abspath(folder)), kind=kind, printer=printer,
              requirements=requirements or {})
    sp.save(folder)
    s.open(folder)
    nxt = ("spec_set_board(project='<KiCad project folder>', slot='main'), then build_and_check" if kind == "enclosure"
           else "project_show, then build_and_check")
    return {"created": Spec.path(folder), "spec": s.spec.__dict__, "next": nxt}


@tool("project_open", "Open an existing design folder.", S({"folder": STR}, ["folder"]))
def t_open(s: Session, folder: str):
    s.open(folder)
    return {"spec": s.spec.__dict__}


@tool("project_show", "The spec: chosen parts (with catalog data), airframe parameters (current value + meaning), "
      "printer, materials, decisions.", S({}))
def _params_class(sp):
    if sp.kind == "enclosure":
        from ..families.enclosure import EnclosureParams
        return EnclosureParams
    from ..geom.airframe import AirframeParams
    return AirframeParams


def _param_docs(sp):
    if sp.kind == "enclosure":
        from ..families.enclosure import PARAM_DOCS as D
        return D
    return PARAM_DOCS


def t_show(s: Session):
    from ..project import airframe_params
    sp = s.need()
    p = airframe_params(sp, base_dir=s.folder)
    docs = _param_docs(sp)
    params = {k: {"value": v, "meaning": docs.get(k, "")} for k, v in dataclasses.asdict(p).items() if k != "port_holes"}
    if sp.kind == "enclosure":
        return {"spec": sp.__dict__, "kind": "enclosure", "params": params, "derived": p.to_dict(),
                "boards": sp.boards}
    return {"spec": sp.__dict__, "parts": {r: sp.part(r).to_dict() for r in ("motor", "prop", "esc", "fc", "receiver", "battery")},
            "airframe_params": params, "derived": {"duct_ri": p.duct_ri, "duct_ro": p.duct_ro, "duct_centres": p.duct_centres,
                                                   "span_y": p.span_y, "prop_z": p.prop_z}}


@tool("spec_set_part", "Choose a catalog part for a role (motor, prop, esc, fc, receiver, battery). overrides replace "
      "catalog fields with datasheet values for the exact part you buy, e.g. {\"mass_g\": 10.2}.",
      S({"role": STR, "part_id": STR, "overrides": OBJ}, ["role", "part_id"]), writes=True)
def t_set_part(s: Session, role: str, part_id: str, overrides: Optional[Dict] = None):
    sp = s.need()
    if role not in ("motor", "prop", "esc", "fc", "receiver", "battery"):
        raise UserError("role must be motor, prop, esc, fc, receiver or battery")
    p = C.get(part_id, **(overrides or {}))
    if p.kind != role:
        raise UserError(f"{part_id} is a {p.kind}, not a {role}")
    sp.parts[role] = {"id": part_id, **(overrides or {})}
    s.changed()
    return {"set": role, "part": p.to_dict()}


@tool("spec_set_params", "Change airframe parameters (see project_show for names, values and meaning). Unknown names "
      "are rejected. Rebuild with build_and_check afterwards.", S({"params": OBJ}, ["params"]), writes=True)
def t_set_params(s: Session, params: Dict):
    sp = s.need()
    fields = _params_class(sp).__dataclass_fields__
    bad = [k for k in params if k not in fields]
    if bad:
        raise UserError(f"unknown parameters {bad}; valid: {sorted(k for k in fields if k != 'port_holes')}")
    sp.airframe.update(params)
    s.changed()
    return {"airframe_overrides": sp.airframe}


@tool("spec_set_printer", "Set the printer (bed size drives the part split/fit checks) and optional material "
      "overrides per part kind, e.g. {\"frame\": \"PETG\", \"pod\": \"PLA\"}.",
      S({"printer": STR, "materials": OBJ}), writes=True)
def t_set_printer(s: Session, printer: str = "", materials: Optional[Dict] = None):
    sp = s.need()
    if printer:
        if printer not in C.PRINTERS:
            raise UserError(f"unknown printer; choose from {list(C.PRINTERS)}")
        sp.printer = printer
    for k, v in (materials or {}).items():
        if v not in C.MATERIALS:
            raise UserError(f"unknown material {v}; choose from {list(C.MATERIALS)}")
        sp.materials[k] = v
    s.changed()
    return {"printer": sp.printer, "materials": sp.materials}


@tool("spec_set_fc_board", "Use a real PCB in the model: a .kicad_pcb (exported to STEP with kicad-cli) or a .step "
      "file. The board's true outline and parts are then checked for fit and interference.",
      S({"path": STR}, ["path"]), writes=True)
def t_set_fc(s: Session, path: str):
    sp = s.need()
    if path.lower().endswith(".kicad_pcb"):
        from ..adapters.kicad import board_to_step
        out = os.path.join(s.folder, "boards", os.path.splitext(os.path.basename(path))[0] + ".step")
        r = board_to_step(path, out)
        if not r.get("ok"):
            raise UserError(f"kicad-cli export failed: {r.get('error') or r.get('log')}")
        path = out
    if not os.path.exists(path):
        raise UserError(f"{path} not found")
    ap = os.path.abspath(path)
    rel = os.path.relpath(ap, s.folder)
    sp.fc_step = rel if not rel.startswith("..") else ap      # keep the folder portable when the board is inside it
    s.changed()
    return {"fc_step": sp.fc_step}


@tool("decision_add", "Record a design decision or accept a warning with a reason (\"ACK arm_stiffness: carbon frame "
      "planned\"). Acknowledged warnings stop blocking next_step.", S({"text": STR}, ["text"]), writes=True)
def t_decision(s: Session, text: str):
    sp = s.need()
    sp.decisions.append(text)
    sp.save(s.folder)
    if s.result is not None and not s.dirty:
        s.save_state()           # a decision does not change geometry; keep the last build's results valid
    return {"decisions": sp.decisions}


# ------------------------------------------------------------------------------- build / check / export
def _build(s: Session):
    from .. import checks
    from ..project import build_model
    sp = s.need()
    was_dirty = s.dirty or s.result is None
    s.model = build_model(sp, base_dir=s.folder)
    s.result = checks.run(s.model)
    s.dirty = False
    if was_dirty:
        s.exported = False       # a rebuild of an unchanged spec (e.g. for a render) keeps the exports valid
    s.save_state()
    return s.result


def _acked(sp, rule):
    return any(d.startswith(f"ACK {rule}") for d in sp.decisions)


@tool("build_and_check", "Build the geometry from the spec and run every check: bed fit, prop clearance, "
      "interference, mass/CG, propulsion, arm stiffness, solid integrity, printability. Returns findings (error / "
      "warning / info with the parts involved) and key metrics.", S({"full_metrics": BOOL}))
def t_build(s: Session, full_metrics: bool = False):
    r = _build(s)
    m = r["metrics"]
    if s.spec.kind == "enclosure":
        brief = {"mass_g": m["mass"]["total_g"], "enclosure": {k: m["enclosure"][k] for k in ("inner_mm", "outer_mm")}}
    else:
        brief = {"auw_g": m["mass"]["total_g"], "cg_mm": m["cg"]["cg_mm"],
                 "thrust_to_weight": m["propulsion"]["thrust_to_weight"],
                 "hover_min": m["propulsion"]["hover_flight_time_min"],
                 "hover_throttle_pct": m["propulsion"]["hover_throttle_est_pct"],
                 "arm": {k: m["arm"][k] for k in ("tip_deflection_mm", "safety_factor", "first_mode_hz")}}
    for f in r["findings"]:
        if f["severity"] == "warning" and _acked(s.spec, f["rule"]):
            f["acknowledged"] = True
    from .fixes import annotate
    annotate(r["findings"], s.spec, s.model.params if s.model else None)
    return {"summary": r["summary"], "findings": r["findings"], "metrics": m if full_metrics else brief,
            "notes": r["notes"],
            "how_to_fix": "each error/warning lists `fixes`: ready tool calls, most likely first. Apply one with "
                          "try_fix(finding=<index>, fix=<index>): it rebuilds and keeps the change only if the design "
                          "improved."}


@tool("showcase", "Presentation renders of the exported assembly through FreeCAD (smooth shading): hero, rear "
      "three-quarter, top, side, front and inside views in out/showcase/. Needs FreeCAD and a finished export.",
      S({}))
def t_showcase(s: Session):
    from ..showcase import showcase
    r = showcase(s.folder)
    if "error" in r:
        raise UserError(r["error"])
    return {"image_paths": r["images"], "freecad": r["freecad"]}


@tool("render", "Render the design (shaded views) to a PNG you can look at. what: assembly | airframe | inside "
      "(frame + electronics) | a part name.", S({"what": STR, "views": {"type": "array", "items": STR}}))
def t_render(s: Session, what: str = "assembly", views: Optional[List[str]] = None):
    from ..render import render
    if s.dirty or s.model is None:
        _build(s)
    items = s.model.items
    if what == "airframe":
        sel = [i for i in items if i.kind == "airframe"]
    elif what == "inside":
        sel = [i for i in items if i.name == "frame" or (i.kind == "component" and not i.name.startswith("prop"))]
    elif what == "assembly":
        sel = [i for i in items if not i.name.startswith("prop")]
    else:
        sel = [i for i in items if i.name == what]
        if not sel:
            raise UserError(f"no part named {what}; parts: {[i.name for i in items]}")
    d = os.path.join(s.folder, "out")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"render_{what}.png")
    render([(i.shape, i.colour) for i in sel if i.shape is not None], path, views=views or ("iso", "top", "side", "front"),
           title=f"{s.spec.name}: {what}")
    return {"image_paths": [path], "path": path}


@tool("export", "Write STEP assembly (named, coloured parts), one STEP and one print-oriented STL per printed part, "
      "frame DXF, BOM (CSV/Markdown), design.json and report.md into <folder>/out. Refuses while checks have errors "
      "unless force=true.", S({"force": BOOL}), writes=True)
def t_export(s: Session, force: bool = False):
    from .. import export
    if s.dirty or s.model is None:
        _build(s)
    if s.result["summary"]["error"] and not force:
        raise UserError(f"{s.result['summary']['error']} check errors — fix them first (build_and_check) or pass force=true")
    res = export.export_all(s.model, s.result, s.folder)
    s.exported = True
    s.save_state()
    return {"files": res["files"], "print": {k: {kk: v[kk] for kk in ("orientation", "footprint_mm", "height_mm", "material", "mass_g")}
                                              for k, v in res["print"].items()}}


@tool("onshape_upload", "Upload the exported STEP files to a new Onshape document (needs ONSHAPE_ACCESS_KEY / "
      "ONSHAPE_SECRET_KEY). Returns the document URL.", S({"name": STR, "parts": BOOL}), writes=True)
def t_onshape(s: Session, name: str = "", parts: bool = False):
    from ..adapters import onshape
    s.need()
    if not s.exported and not os.path.exists(os.path.join(s.folder, "out", "assembly.step")):
        raise UserError("export first")
    try:
        return onshape.upload_design(s.folder, name or s.spec.name, parts=parts)
    except onshape.OnshapeError as e:
        raise UserError(str(e))


# ------------------------------------------------------------------------------- FreeCAD (live)
def _fc(method, *args):
    from ..adapters import freecad_client
    try:
        return freecad_client.call(method, *args)
    except (ConnectionError, RuntimeError) as e:
        raise UserError(str(e))


@tool("freecad_status", "Is FreeCAD running with the RL CAD bridge? Lists open documents and which design each shows.", S({}))
def t_fc_status(s: Session):
    from ..adapters import freecad_client
    if not freecad_client.available():
        return {"running": False, "hint": "Start FreeCAD (the RL CAD workbench starts the bridge automatically)."}
    return {"running": True, **_fc("status")}


@tool("freecad_open", "Show the current design in FreeCAD: parameter sheet (RLCAD_Params), check results (RLCAD_Checks) "
      "and the model, saved as out/<name>.FCStd. rebuild=true re-runs RL CAD first.",
      S({"rebuild": BOOL}))
def t_fc_open(s: Session, rebuild: bool = False):
    s.need()
    return _fc("open_design", s.folder, bool(rebuild))


@tool("freecad_read_params", "Read the parameter sheet in FreeCAD (including edits the engineer typed but has not synced).",
      S({}))
def t_fc_params(s: Session):
    s.need()
    return {"params": _fc("params", s.folder)}


@tool("freecad_sync", "Apply the FreeCAD parameter sheet to the design (the engineer's edits, or values you set with "
      "freecad_set_params), rebuild, check, export, and reload FreeCAD. Returns applied changes and findings.",
      S({"values": OBJ}), writes=True)
def t_fc_sync(s: Session, values: Optional[Dict] = None):
    s.need()
    if values:
        r = _fc("set_params", values, s.folder)
        if r.get("unknown"):
            raise UserError(f"unknown parameters {r['unknown']}")
    res = _fc("sync", s.folder)
    s.open(s.folder)                     # the spec and results changed on disk
    return res


@tool("freecad_view", "Screenshot of the FreeCAD view (iso, top, front, right, left, rear, bottom) to look at the model "
      "as the engineer sees it.", S({"view": STR}))
def t_fc_view(s: Session, view: str = "iso"):
    s.need()
    d = os.path.join(s.folder, "out")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"freecad_{view}.png")
    _fc("screenshot", path, view)
    return {"image_paths": [path], "path": path}


@tool("integration_check", "Make the PCB side and the CAD side agree: refresh each board's mech.json from KiCad "
      "(RL PCB), place it, check mounting pattern, part heights against the ESC and the fuselage roof, board fit, "
      "connector reach; write enclosure.json into the board's KiCad project for RL PCB's mech_check; run RL PCB's "
      "system_check on the cables. Writes out/integration.md.", S({}))
def t_integrate(s: Session):
    from ..integrate import run
    s.need()
    r = run(s.folder)
    return {"ok": r["ok"], "cad": r["cad"], "system": r["system"],
            "boards": {k: {"envelope": v["envelope"], "pcb_check": v["pcb_check"], "connectors": v["connectors"]}
                       for k, v in r["boards"].items()}, "files": r["files"]}


@tool("spec_set_board", "Link a board designed with RL PCB into a slot (fc): its KiCad project folder, relative to the "
      "design folder or absolute, and an optional rotation about Z (0/90/180/270) to point its connectors where the "
      "airframe can reach them.", S({"slot": STR, "project": STR, "rotation": NUM}, ["project"]), writes=True)
def t_set_board(s: Session, project: str, slot: str = "fc", rotation: float = 0):
    sp = s.need()
    ap = project if os.path.isabs(project) else os.path.join(s.folder, project)
    if not os.path.isdir(ap) and not os.path.isfile(ap):
        raise UserError(f"{ap} not found")
    rel = os.path.relpath(os.path.abspath(ap), s.folder)
    sp.boards[slot] = {"project": rel if not rel.startswith("..") else os.path.abspath(ap), "rotation": rotation}
    s.changed()
    return {"boards": sp.boards}


def _score(res):
    """Lower is better: errors dominate, then unacknowledged warnings."""
    return (res["summary"]["error"], sum(1 for f in res["findings"] if f["severity"] == "warning"
                                         and not f.get("acknowledged")))


@tool("try_fix", "Apply one suggested fix from the last build_and_check (finding index, fix index; both 0-based, in "
      "the order build_and_check listed them), rebuild, and keep it only if the design got better (fewer errors, then "
      "fewer open warnings). Returns before/after so you can report the effect.",
      S({"finding": NUM, "fix": NUM}, ["finding"]), writes=True)
def t_try_fix(s: Session, finding: int, fix: int = 0):
    import copy as _copy
    from .fixes import fixes_for
    if s.result is None or s.dirty:
        raise UserError("run build_and_check first")
    fs = s.result["findings"]
    f = fs[int(finding)]
    fx = f.get("fixes") or fixes_for(f, s.spec, s.model.params if s.model else None)
    if not fx:
        raise UserError(f"no suggested fix for rule {f['rule']}; change a parameter or part yourself")
    c = fx[int(fix)]
    for f2 in fs:
        if f2["severity"] == "warning" and _acked(s.spec, f2["rule"]):
            f2["acknowledged"] = True
    before = _score(s.result)
    saved = _copy.deepcopy(s.spec.__dict__)
    res = run_tool(s, c["tool"], c["args"])
    if "error" in res:
        return {"applied": c, "error": res["error"]}
    if c["tool"] == "decision_add":
        return {"applied": c, "kept": True, "note": "decision recorded; no rebuild needed"}
    after_r = run_tool(s, "build_and_check", {})
    if "error" in after_r:
        s.spec.__dict__.update(saved)
        s.changed()
        return {"applied": c, "kept": False, "error": after_r["error"]}
    after = _score(after_r)
    target_gone = not any(x["rule"] == f["rule"] and x["severity"] == f["severity"] and x.get("refs") == f.get("refs")
                          for x in after_r["findings"])
    if after < before or (after == before and target_gone):
        return {"applied": c, "kept": True, "before": {"errors": before[0], "warnings": before[1]},
                "after": {"errors": after[0], "warnings": after[1]}, "summary": after_r["summary"],
                "findings": [x for x in after_r["findings"] if x["severity"] != "info"]}
    s.spec.__dict__.update(saved)
    s.changed()
    s.spec.save(s.folder)
    return {"applied": c, "kept": False, "reverted": True,
            "before": {"errors": before[0], "warnings": before[1]}, "after": {"errors": after[0], "warnings": after[1]},
            "next": "try the next fix (fix index + 1) or another finding; run build_and_check to refresh"}


@tool("parts_compatible", "Catalog parts for a role (motor, prop, esc, battery, receiver, fc) checked against the parts "
      "already chosen: shaft vs prop bore, cell count vs motor/ESC range, ESC current vs motor rating. Compatible "
      "first, lightest first.", S({"role": STR}, ["role"]))
def t_parts_compatible(s: Session, role: str):
    from .fixes import compatible_parts
    return {"role": role, "parts": compatible_parts(s.need(), role)}


@tool("design_checklist", "The whole design process as a checklist with the state of each stage (done / todo / "
      "blocked) and the tool that advances it. Use it to see where the project stands.", S({}))
def t_checklist(s: Session):
    sp = s.spec
    r = s.result
    errs = [f for f in (r or {}).get("findings", []) if f["severity"] == "error"]
    warns = [f for f in (r or {}).get("findings", []) if f["severity"] == "warning" and sp and not _acked(sp, f["rule"])]
    rules = {f["rule"] for f in (r or {}).get("findings", [])}
    stages = [
        ("requirements recorded", bool(sp and sp.requirements), "project_create"),
        ("parts chosen and compatible", bool(sp) and not any(x in rules for x in ("prop_fit", "motor_fit", "power_esc",
                                                                                 "power_voltage")) or
         bool(r and not [f for f in errs if f["rule"].startswith(("prop_fit", "motor_fit", "power_"))]),
         "parts_compatible → spec_set_part"),
        ("propulsion adequate (T/W ≥ 2)", bool(sp and sp.kind == "enclosure") or
         bool(r and r["metrics"].get("propulsion", {}).get("thrust_to_weight", 0) >= 2), "calc_propulsion"),
        ("built and checked", bool(r) and not s.dirty, "build_and_check"),
        ("no errors", bool(r) and not errs, "try_fix"),
        ("warnings fixed or acknowledged", bool(r) and not warns, "try_fix / decision_add"),
        ("flight controller board linked", bool(sp and (sp.boards or sp.fc_step)), "spec_set_board"),
        ("PCB ↔ CAD integration", bool(s.folder and os.path.exists(os.path.join(s.folder, "out", "integration.json"))),
         "integration_check"),
        ("printable (print audit clean)", bool(r) and not any(f["rule"].startswith("print_") and f["severity"] != "info"
                                                              for f in r["findings"]), "try_fix"),
        ("exported (STEP, STL, BOM, report)", bool(s.exported), "export"),
    ]
    out, blocked = [], False
    for name, ok, tool_ in stages:
        state = "done" if ok else ("blocked" if blocked else "todo")
        if not ok:
            blocked = True
        out.append({"stage": name, "state": state, "tool": tool_})
    return {"stages": out, "next": next((x for x in out if x["state"] == "todo"), None)}


@tool("next_step", "What to do next, from the project state (spec, last build, findings, exports).", S({}))
def t_next(s: Session):
    if not s.spec:
        return {"step": "project_create", "why": "no project open"}
    sp = s.spec
    if not sp.requirements:
        return {"step": "project_create / decision_add", "why": "no requirements recorded — write what the aircraft must do "
                "(size, flight time, printer, what it carries) so choices can be checked against it"}
    if s.dirty or s.result is None:
        return {"step": "build_and_check", "why": "the spec changed since the last build"}
    from .fixes import fixes_for
    fs = s.result["findings"]
    errs = [i for i, f in enumerate(fs) if f["severity"] == "error"]
    if errs:
        i = errs[0]
        fx = fixes_for(fs[i], sp, s.model.params if s.model else None)
        return {"step": "fix errors", "why": f"{len(errs)} errors", "first": fs[i],
                "call": {"tool": "try_fix", "args": {"finding": i, "fix": 0}} if fx else None, "fixes": fx,
                "how": "try_fix applies a suggested fix and keeps it only if the design improves; otherwise change "
                       "parameters (spec_set_params) or parts (spec_set_part), then build_and_check"}
    warns = [i for i, f in enumerate(fs) if f["severity"] == "warning" and not _acked(sp, f["rule"])]
    if warns:
        i = warns[0]
        fx = fixes_for(fs[i], sp, s.model.params if s.model else None)
        return {"step": "fix or acknowledge warnings", "first": fs[i], "fixes": fx,
                "call": {"tool": "try_fix", "args": {"finding": i, "fix": 0}} if fx else None,
                "how": "fix, or decision_add('ACK <rule>: <reason>') if the engineer accepts it"}
    if not sp.fc_step and not sp.boards:
        return {"step": "spec_set_fc_board (optional)", "why": "the FC is a catalog box; a real KiCad board checks the true fit"}
    if not s.exported:
        return {"step": "export", "why": "checks pass"}
    return {"step": "done", "why": "exported; optional: onshape_upload, or render to review",
            "files": os.path.join(s.folder, "out")}


# =============================================================================== copilot: modes, proposals, journal
def _cp(s: Session):
    from .copilot_cad import copilot_for
    return copilot_for(s)


@tool("copilot_status", "How the engineer wants to work: the autonomy mode (teach / advise / propose / do) for the "
      "whole design and per scope (part:pods, part:fuselage, part:frame, part:fins, parts:<role>, layout, printing, "
      "boards, decisions), pending proposals, the engineer's recent accept/reject reasons, recent changes. Read it "
      "first in a session and before changing anything.", S({}))
def t_cp_status(s: Session):
    from .copilot import MODE_HELP
    st = _cp(s).status()
    st["modes"] = MODE_HELP
    return st


@tool("copilot_mode", "Set the autonomy mode for the whole design or one scope (e.g. scope='part:fuselage' "
      "mode='advise'). ONLY when the engineer asks. mode='inherit' clears a scope.",
      S({"mode": STR, "scope": STR, "note": STR}, ["mode"]))
def t_cp_mode(s: Session, mode: str, scope: str = "", note: str = ""):
    cp = _cp(s)
    cp.set_mode(mode, scope, note)
    return cp.status()


@tool("proposals", "List proposals (pending by default) with their summary and check results.",
      S({"status": STR}))
def t_proposals(s: Session, status: str = "pending"):
    ps = _cp(s).proposals("" if status == "all" else status)
    return {"proposals": [{"id": x["id"], "status": x["status"], "action": x["action"], "args": x["args"],
                           "summary": x["summary"].get("text", ""), "checks": x["summary"].get("checks"),
                           "reason": x.get("note", "")} for x in ps]}


@tool("proposal_show", "One proposal in full (what changes, the checks before/after, what is not verified); "
      "render=true draws the proposed design.", S({"id": STR, "render": BOOL}, ["id"]))
def t_proposal_show(s: Session, id: str, render: bool = False):
    cp = _cp(s)
    pr = cp.proposal(id)
    out = {k: pr.get(k) for k in ("id", "status", "action", "args", "scopes", "changes", "summary", "assurance", "note")}
    if render and pr["status"] == "pending":
        s2 = Session(cp.work_dir(id))
        s2._in_gate = True
        r = t_render(s2, "assembly")
        out["image_paths"] = r["image_paths"]
    return out


@tool("proposal_accept", "Apply a proposal. Call ONLY after the engineer said yes to it. Its build and check results "
      "carry over, so no rebuild is needed.", S({"id": STR, "note": STR, "force": BOOL}, ["id"]))
def t_proposal_accept(s: Session, id: str, note: str = "", force: bool = False):
    from .copilot_cad import accept
    r = accept(s, id, note, force)
    r["state"] = "checked (results from the proposal)" if not s.dirty else "spec changed: run build_and_check"
    return r


@tool("proposal_reject", "Discard a proposal with the engineer's reason (kept, so later proposals follow it).",
      S({"id": STR, "reason": STR}, ["id"]))
def t_proposal_reject(s: Session, id: str, reason: str = ""):
    return _cp(s).reject(id, reason)


@tool("undo", "Undo a change made in 'do' mode or an accepted proposal (default: the most recent).",
      S({"id": STR, "force": BOOL}))
def t_undo(s: Session, id: str = "", force: bool = False):
    r = _cp(s).undo(id, force)
    s.open(s.folder)
    return r


@tool("design_journal", "The design's history: who changed what (AI or engineer), in which mode; proposals and their "
      "outcomes; mode changes.", S({"limit": NUM}))
def t_journal(s: Session, limit: int = 30):
    rows = _cp(s).journal(int(limit))
    return {"entries": [{k: r.get(k) for k in ("id", "t", "actor", "action", "summary", "scopes", "proposal", "undone",
                                               "note")} for r in rows]}


@tool("assurance_report", "What the checks have verified and what they cannot vouch for (estimated part data, no FEA, "
      "no aerodynamics, slicer approximation). Show it before printing or ordering parts.", S({}))
def t_assurance(s: Session):
    from .copilot_cad import assurance
    r = s.result
    d = {"errors": r["summary"]["error"], "warnings": r["summary"]["warning"], "built": not s.dirty} if r else None
    return assurance(s, d)


# =============================================================================== features (local details)
@tool("feature_add", "Add a local feature to a generated part: hole (at, axis, d, depth), boss (at, axis, od, height, "
      "hole_d), pad (at, size [w,l,h]), pocket (at, size), rib (from, to, thickness, height). Assembly frame, mm "
      "(X forward, Y left, Z up). Give a short note saying why (it is kept with the feature). Rebuild to check it.",
      S({"part": STR, "type": STR, "at": {"type": "array"}, "axis": STR, "d": NUM, "depth": NUM, "od": NUM,
         "height": NUM, "hole_d": NUM, "size": {"type": "array"}, "from": {"type": "array"}, "to": {"type": "array"},
         "thickness": NUM, "note": STR}, ["part", "type"]), writes=True)
def t_feature_add(s: Session, part: str, type: str, note: str = "", **kw):
    import uuid
    from ..geom.features import validate
    sp = s.need()
    f = {"id": uuid.uuid4().hex[:6], "part": part, "type": type, **{k: v for k, v in kw.items() if v is not None},
         "note": note}
    errs = validate(f)
    if errs:
        raise UserError("; ".join(errs))
    sp.features.append(f)
    s.changed()
    return {"added": f, "next": "build_and_check to see its effect (solid, interference, print audit)"}


@tool("feature_remove", "Remove a feature by id (see feature_list).", S({"id": STR}, ["id"]), writes=True)
def t_feature_remove(s: Session, id: str):
    sp = s.need()
    n = len(sp.features)
    sp.features = [f for f in sp.features if f.get("id") != id]
    if len(sp.features) == n:
        raise UserError(f"no feature {id}")
    s.changed()
    return {"removed": id}


@tool("feature_list", "Features added to the generated parts, with the types available.", S({}))
def t_feature_list(s: Session):
    from ..geom.features import TYPES
    return {"features": s.need().features, "types": TYPES,
            "parts": [i.name for i in s.model.items if i.printable] if s.model else "build first to list part names"}


# =============================================================================== kickoff, teaching, interface
@tool("kickoff", "Start a mechanical design from an idea: the questions to answer, the manufacturing route for the "
      "quantity, the pitfalls, and whether RL CAD has a parametric family for it (ducted quad, enclosure) or the "
      "engineer designs it in FreeCAD/Onshape with RL CAD reviewing the parts. Read-only.",
      S({"idea": STR, "archetype": STR}, ["idea"]))
def t_kickoff(s: Session, idea: str, archetype: str = ""):
    from ..kickoff import brief
    return brief(idea, archetype)


@tool("kickoff_apply", "Create the design folder agreed in kickoff (spec, docs/requirements.md); board = the KiCad "
      "project folder of the board it is built around (optional).",
      S({"folder": STR, "name": STR, "archetype": STR, "idea": STR, "requirements": OBJ, "board": STR},
        ["folder", "name", "archetype"]))
def t_kickoff_apply(s: Session, folder: str, name: str, archetype: str, idea: str = "", requirements: Optional[Dict] = None,
                    board: str = ""):
    from ..kickoff import apply
    r = apply(folder, name, archetype, requirements, idea, board)
    s.open(folder)
    return r


@tool("explain", "Teach: what a check protects against and how it is usually fixed (topic='rule:<name>'), or what a "
      "parameter does and which checks it moves (topic='param:<name>').", S({"topic": STR}, ["topic"]))
def t_explain(s: Session, topic: str):
    from ..kickoff import RULES, explain_rule
    kind, _, name = topic.partition(":")
    if kind == "rule":
        return explain_rule(name)
    if kind == "param":
        sp = s.need()
        docs = _param_docs(sp)
        if name not in _params_class(sp).__dataclass_fields__:
            raise UserError(f"unknown parameter {name}")
        from .copilot_cad import _param_scope
        return {"param": name, "meaning": docs.get(name, ""), "scope": _param_scope(name),
                "value": getattr(__import__("rlcad.project", fromlist=["airframe_params"]).airframe_params(
                    sp, base_dir=s.folder), name),
                "how_to_judge": "change it with spec_set_params (a proposal shows the check results before/after)"}
    raise UserError("topic must be 'rule:<name>' or 'param:<name>'; rules: " + ", ".join(sorted(RULES)))


@tool("interface_changes", "Change notices between this design and its boards (interface_log.json in each board's "
      "KiCad project): what the electronics side changed (moved connectors or holes, taller parts, new outline) since "
      "RL CAD last checked, and what this design changed in the space it gives each board. integration_check reviews "
      "and marks the electronics' notices as seen.", S({}))
def t_interface_changes(s: Session):
    from ..interface import read_log, unseen
    from ..mech import _project
    sp = s.need()
    out = {}
    for slot, entry in sp.boards.items():
        try:
            proj, _ = _project(s.folder, entry)
        except Exception as e:  # noqa
            out[slot] = {"error": str(e)}
            continue
        out[slot] = {"from_electronics_unreviewed": unseen(proj, "cad"),
                     "from_this_design_awaiting_pcb": [e for e in read_log(proj)["entries"] if e["from"] == "cad"
                                                       and not e.get("seen_by_other_side")]}
    return {"boards": out, "next": "integration_check reviews the electronics side's changes against this design"}


# =============================================================================== manufacturability review
@tool("review_part", "Manufacturability review of a part, with reasons: process 'fdm' (print orientation, walls, "
      "overhangs, bridges, holes, adhesion, layer strength) or 'injection_molding' (draft, undercuts, wall-thickness "
      "uniformity, mold cost). part = a part of this design, or a path to any .step/.stl the engineer made elsewhere.",
      S({"part": STR, "process": STR}, ["part"]))
def t_review_part(s: Session, part: str, process: str = "fdm"):
    from .. import dfm
    if os.path.exists(part):
        shape = dfm.load_shape(part)
        if process == "fdm" and hasattr(shape, "wrapped"):
            from ..export import print_orientation
            shape, _ = print_orientation(shape, (256, 256, 256))
        return dfm.review(shape, process, os.path.basename(part))
    if s.dirty or s.model is None:
        _build(s)
    it = next((i for i in s.model.items if i.name == part and i.printable), None)
    if not it:
        raise UserError(f"no printed part {part}; parts: {[i.name for i in s.model.items if i.printable]}")
    from ..export import placed_for_print
    from ..catalog import PRINTERS
    placed, inf = placed_for_print(s.model, it, PRINTERS[s.spec.printer]["bed_mm"])
    shape = placed if process == "fdm" else it.shape
    r = dfm.review(shape, process, part)
    if process == "fdm":
        r["orientation"] = inf["orientation"]
    return r


# =============================================================================== dispatch
TOOL_MAP = {t.name: t for t in TOOLS}


def run_tool(session: Session, name: str, args: Dict[str, Any], actor: str = "ai") -> Dict[str, Any]:
    """Run a tool. Design-changing tools go through the copilot gate (mode, proposals, journal, undo)."""
    t = TOOL_MAP.get(name)
    if t is None:
        return {"error": f"Unknown tool {name}", "tools": list(TOOL_MAP)}
    import inspect
    try:
        inspect.signature(t.fn).bind(session, **(args or {}))
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}. Expected: {list(t.schema.get('properties', {}))}"}
    try:
        from .copilot_cad import gate
        res = gate(session, name, args or {}, t.fn, actor=actor, build_check=lambda s2: t_build(s2)["findings"])
        return res if isinstance(res, dict) else {"result": res}
    except (UserError, KeyError, ValueError) as e:
        return {"error": str(e)}
    except Exception as e:  # noqa
        return {"error": f"{type(e).__name__}: {e}", "trace": traceback.format_exc()[-1500:]}


def to_json(obj: Any, limit: int = 60000) -> str:
    s = json.dumps(obj, indent=1, ensure_ascii=False, default=str)
    if len(s) > limit:
        s = s[:limit] + f"\n… (truncated {len(s) - limit} chars)"
    return s
