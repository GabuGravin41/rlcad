"""RL CAD inside FreeCAD: load a design, show its parameters in a spreadsheet, and keep the two in sync.

FreeCAD's Python cannot import RL CAD itself (different interpreter, build123d wheels), so every geometry operation
runs in RL CAD's own Python through the `rlcad` CLI; FreeCAD shows the result and owns the parameter sheet.

Document layout (saved as <design>/out/<name>.FCStd):
    RLCAD_Params   spreadsheet: parameter | value | meaning (value cells carry the parameter name as alias)
    RLCAD_Checks   spreadsheet: severity | rule | message, then the key metrics
    RLCAD_Model    group with the imported assembly (named, coloured parts)
The document stores the design folder in the property RLCAD_Params.Label2 ("rlcad:<folder>").
"""
import json
import os
import subprocess
import sys
import time

import FreeCAD as App

CONFIG = os.path.join(os.path.expanduser("~"), ".rlcad", "config.json")
SKIP = {"port_holes"}


# --------------------------------------------------------------------------------------------- RL CAD process
def config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def rlcad_python():
    py = os.environ.get("RLCAD_PYTHON") or config().get("python")
    if not py or not os.path.exists(py):
        raise RuntimeError("RL CAD's Python is not configured. Run install_windows.ps1 (it writes %s) or set "
                           "RLCAD_PYTHON." % CONFIG)
    return py


def run_rlcad(*args, timeout=900):
    """Run `python -m rlcad <args>` and return the JSON it prints last."""
    py = rlcad_python()
    # FreeCAD's own Python settings must not leak into RL CAD's interpreter
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
                        "APPDIR", "APPIMAGE", "CONDA_PREFIX", "PYTHONNOUSERSITE")}
    root = config().get("repo")
    if root:
        env["PYTHONPATH"] = root
    flags = 0x08000000 if sys.platform == "win32" else 0          # CREATE_NO_WINDOW
    r = subprocess.run([py, "-m", "rlcad"] + list(args), capture_output=True, text=True, timeout=timeout, env=env,
                       creationflags=flags)
    lines = [l for l in r.stdout.splitlines() if l.strip().startswith("{")]
    if not lines:
        raise RuntimeError("rlcad %s failed:\n%s" % (" ".join(args[:1]), (r.stderr or r.stdout)[-2000:]))
    return json.loads(lines[-1])


# --------------------------------------------------------------------------------------------- document helpers
def _fmt(v):
    if isinstance(v, (list, tuple)):
        return json.dumps(list(v))
    return v


def _parse(text):
    if isinstance(text, (int, float)):
        return float(text)
    t = str(text).strip()
    if t.startswith("'"):
        t = t[1:]
    try:
        return json.loads(t)
    except ValueError:
        try:
            return float(t)
        except ValueError:
            return t


def design_folder(doc):
    sheet = doc.getObject("RLCAD_Params")
    if sheet is None or not str(sheet.Label2).startswith("rlcad:"):
        return None
    return str(sheet.Label2)[6:]


def find_doc(folder=None):
    """The open document that belongs to an RL CAD design (optionally a specific folder)."""
    for d in App.listDocuments().values():
        f = design_folder(d)
        if f and (folder is None or os.path.normcase(os.path.abspath(f)) == os.path.normcase(os.path.abspath(folder))):
            return d
    return None


def _sheet(doc, name):
    s = doc.getObject(name)
    if s is None:
        s = doc.addObject("Spreadsheet::Sheet", name)
    return s


def write_params(doc, folder, params):
    s = _sheet(doc, "RLCAD_Params")
    s.Label2 = "rlcad:" + os.path.abspath(folder)
    s.clearAll()
    s.set("A1", "parameter")
    s.set("B1", "value")
    s.set("C1", "meaning (edit column B, then RL CAD > Sync)")
    for c in ("A1", "B1", "C1"):
        s.setStyle(c, "bold")
    row = 2
    for name, d in params.items():
        if name in SKIP:
            continue
        v = _fmt(d["value"])
        s.set("A%d" % row, name)
        if isinstance(v, str):
            s.set("B%d" % row, "'" + v)
        else:
            s.set("B%d" % row, str(v))
            try:
                s.setAlias("B%d" % row, name)
            except Exception:
                pass
        s.set("C%d" % row, "'" + (d.get("meaning") or ""))
        row += 1
    s.setColumnWidth("A", 150)
    s.setColumnWidth("C", 520)
    doc.recompute()


def read_params(doc):
    s = doc.getObject("RLCAD_Params")
    out = {}
    if s is None:
        return out
    row = 2
    while True:
        try:
            name = s.get("A%d" % row)
        except Exception:
            break
        if not name:
            break
        try:
            out[str(name)] = _parse(s.get("B%d" % row))
        except Exception:
            pass
        row += 1
    return out


def write_checks(doc, result):
    s = _sheet(doc, "RLCAD_Checks")
    s.clearAll()
    summ = result.get("summary", {})
    s.set("A1", "checks")
    s.set("B1", "'%s errors, %s warnings, %s info" % (summ.get("error", 0), summ.get("warning", 0), summ.get("info", 0)))
    s.setStyle("A1", "bold")
    row = 3
    for f in result.get("findings", []):
        s.set("A%d" % row, f["severity"] + (" (ack)" if f.get("acknowledged") else ""))
        s.set("B%d" % row, f["rule"])
        s.set("C%d" % row, "'" + f["message"])
        if f["severity"] == "error":
            s.setForeground("A%d" % row, (0.8, 0.0, 0.0))
        row += 1
    row += 1
    m = result.get("metrics", {})
    for k in ("auw_g", "thrust_to_weight", "hover_min", "hover_throttle_pct", "cg_mm", "arm"):
        if k in m:
            s.set("A%d" % row, k)
            s.set("B%d" % row, "'" + json.dumps(m[k]))
            row += 1
    for n in result.get("notes", []):
        s.set("A%d" % row, "note")
        s.set("C%d" % row, "'" + n)
        row += 1
    s.setColumnWidth("C", 700)
    doc.recompute()


def load_geometry(doc, folder):
    """(Re)import out/assembly.step into the RLCAD_Model group."""
    step = os.path.join(folder, "out", "assembly.step")
    if not os.path.exists(step):
        raise RuntimeError("%s not found; run a sync first" % step)
    grp = doc.getObject("RLCAD_Model")
    if grp is not None:
        names = [o.Name for o in grp.OutListRecursive]
        doc.removeObject("RLCAD_Model")
        for n in names:
            if doc.getObject(n) is not None:
                try:
                    doc.removeObject(n)
                except Exception:
                    pass
    before = set(o.Name for o in doc.Objects)
    try:
        import ImportGui
        ImportGui.insert(step, doc.Name)
    except Exception:
        import Import
        Import.insert(step, doc.Name)
    new = [o for o in doc.Objects if o.Name not in before]
    grp = doc.addObject("App::DocumentObjectGroup", "RLCAD_Model")
    grp.Label = "RL CAD model"
    tops = [o for o in new if not o.InList and o.TypeId != "App::Origin"]
    for o in tops:
        try:
            grp.addObject(o)
        except Exception:
            pass
    doc.recompute()
    return len(new)


def _save(doc, folder):
    name = os.path.basename(os.path.normpath(folder))
    path = os.path.join(folder, "out", name + ".FCStd")
    try:
        doc.saveAs(path)
    except Exception:
        pass
    return path


def _fit_view():
    try:
        import FreeCADGui as Gui
        v = Gui.ActiveDocument.ActiveView
        v.viewIsometric()
        v.fitAll()
    except Exception:
        pass


# --------------------------------------------------------------------------------------------- public operations
def open_design(folder, rebuild=False):
    """Open (or refresh) an RL CAD design in FreeCAD. rebuild=True runs RL CAD first."""
    folder = os.path.abspath(folder)
    t0 = time.time()
    result = run_rlcad("sync", folder) if (rebuild or not os.path.exists(os.path.join(folder, "out", "assembly.step"))) \
        else _last_result(folder)
    params = run_rlcad("params", folder)["params"]
    doc = find_doc(folder)
    if doc is None:
        name = "RLCAD_" + "".join(c if c.isalnum() else "_" for c in os.path.basename(folder))
        doc = App.newDocument(name)
    write_params(doc, folder, params)
    n = load_geometry(doc, folder)
    if result:
        write_checks(doc, result)
    path = _save(doc, folder)
    _fit_view()
    return {"document": doc.Name, "file": path, "objects": n, "params": len(params),
            "summary": (result or {}).get("summary"), "seconds": round(time.time() - t0, 1)}


def _last_result(folder):
    cj = os.path.join(folder, "out", "checks.json")
    try:
        with open(cj, encoding="utf-8") as f:
            r = json.load(f)["result"]
        m = r.get("metrics", {})
        brief = {"auw_g": m.get("mass", {}).get("total_g"), "cg_mm": m.get("cg", {}).get("cg_mm"),
                 "thrust_to_weight": m.get("propulsion", {}).get("thrust_to_weight"),
                 "hover_min": m.get("propulsion", {}).get("hover_flight_time_min")}
        return {"summary": r["summary"], "findings": r["findings"], "metrics": brief, "notes": r.get("notes", [])}
    except (OSError, ValueError, KeyError):
        return None


def sync(doc=None, folder=None):
    """Push the parameter sheet's edits to RL CAD, rebuild + check + export, and reload the model."""
    doc = doc or (find_doc(folder) if folder else App.ActiveDocument)
    if doc is None:
        raise RuntimeError("No RL CAD document open")
    folder = folder or design_folder(doc)
    if not folder:
        raise RuntimeError("The active document is not an RL CAD design (no RLCAD_Params sheet)")
    t0 = time.time()
    current = {k: d["value"] for k, d in run_rlcad("params", folder)["params"].items()}
    edited = read_params(doc)
    changes = {}
    for k, v in edited.items():
        if k in current and k not in SKIP and _differs(v, current[k]):
            changes[k] = v
    result = run_rlcad("apply", folder, json.dumps(changes))
    if result.get("error") and not result.get("summary"):
        raise RuntimeError(result["error"])
    params = run_rlcad("params", folder)["params"]
    write_params(doc, folder, params)
    load_geometry(doc, folder)
    write_checks(doc, result)
    _save(doc, folder)
    _fit_view()
    return {"applied": changes, "summary": result.get("summary"), "metrics": result.get("metrics"),
            "findings": [f for f in result.get("findings", []) if f["severity"] != "info"],
            "seconds": round(time.time() - t0, 1)}


def set_params(values, doc=None, folder=None):
    """Write values into the parameter sheet (what a user would type); call sync() to apply them."""
    doc = doc or (find_doc(folder) if folder else App.ActiveDocument)
    s = doc.getObject("RLCAD_Params")
    row, done = 2, {}
    while True:
        name = s.get("A%d" % row) if _cell_exists(s, "A%d" % row) else None
        if not name:
            break
        if name in values:
            v = _fmt(values[name])
            s.set("B%d" % row, ("'" + v) if isinstance(v, str) else str(v))
            done[name] = values[name]
        row += 1
    doc.recompute()
    unknown = [k for k in values if k not in done]
    return {"set": done, "unknown": unknown}


def _cell_exists(s, cell):
    try:
        return s.get(cell) is not None
    except Exception:
        return False


def _differs(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) > 1e-9
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) != len(b) or any(_differs(x, y) for x, y in zip(a, b))
    return a != b


def integrate(doc=None, folder=None):
    """PCB <-> CAD check (rlcad integrate): results into the RLCAD_Integration sheet."""
    doc = doc or (find_doc(folder) if folder else App.ActiveDocument)
    folder = folder or design_folder(doc)
    r = run_rlcad("integrate", folder, "--json")
    s = _sheet(doc, "RLCAD_Integration")
    s.clearAll()
    s.set("A1", "PCB <-> CAD")
    s.set("B1", "'OK" if r.get("ok") else "'problems found")
    s.setStyle("A1", "bold")
    row = 3
    rows = [("cad", f) for f in r["cad"]["findings"]]
    for slot, b in r.get("boards", {}).items():
        env = b["envelope"]
        rows.append(("envelope", {"severity": "info", "rule": slot,
                                  "message": "space %sx%s mm, %s mm below / %s mm above, reachable edges: %s"
                                  % (env["max_outline_mm"][0], env["max_outline_mm"][1], env["keepout_height_mm"]["bottom"],
                                     env["keepout_height_mm"]["top"], ", ".join(env["reachable_edges"]) or "none")}))
        rows += [("pcb", f) for f in (b.get("pcb_check") or {}).get("findings", [])]
    rows += [("cables", f) for f in ((r.get("system") or {}).get("findings") or [])]
    for src, f in rows:
        s.set("A%d" % row, src)
        s.set("B%d" % row, f["severity"])
        s.set("C%d" % row, f["rule"])
        s.set("D%d" % row, "'" + f["message"])
        if f["severity"] == "error":
            s.setForeground("B%d" % row, (0.8, 0.0, 0.0))
        row += 1
    s.setColumnWidth("D", 720)
    doc.recompute()
    return {"ok": r.get("ok"), "rows": len(rows)}


# --------------------------------------------------------------------------------------------- copilot (engineer side)
def tool(name, args=None, doc=None, folder=None, timeout=1800):
    """Run an RL CAD agent tool as the engineer (mode changes, accept/reject, undo, reviews)."""
    doc = doc or (find_doc(folder) if folder else App.ActiveDocument)
    folder = folder or (design_folder(doc) if doc else None)
    if not folder:
        raise RuntimeError("The active document is not an RL CAD design")
    return run_rlcad("tool", folder, name, json.dumps(args or {}), "--actor", "engineer", timeout=timeout)


def accept_proposal(pid, doc=None, folder=None):
    """Accept a proposal, then rebuild/export and reload the model so FreeCAD shows it."""
    doc = doc or (find_doc(folder) if folder else App.ActiveDocument)
    folder = folder or design_folder(doc)
    r = tool("proposal_accept", {"id": pid}, doc, folder)
    if r.get("error"):
        return r
    result = run_rlcad("apply", folder, "{}")
    write_params(doc, folder, run_rlcad("params", folder)["params"])
    load_geometry(doc, folder)
    write_checks(doc, result)
    _save(doc, folder)
    return dict(r, summary=result.get("summary"))
