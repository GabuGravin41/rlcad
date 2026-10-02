"""Presentation renders through FreeCAD (smooth shading, part colours from the STEP assembly).

`render.py` draws quick headless previews with matplotlib for the checks loop. This module is for images people
look at: it starts FreeCAD with a small script, loads out/assembly.step, and saves a hero view, the standard views
and an "inside" view with the skin hidden. It needs a FreeCAD executable (config `freecad` / `freecadcmd`, the
RLCAD_FREECAD variable, or a normal install); on Linux without a display it runs under xvfb-run.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional

_SCRIPT = r'''
import os, json
import FreeCAD as App, FreeCADGui as Gui, ImportGui
cfg = json.loads(os.environ["RLCAD_SHOWCASE"])
done = []
try:
    doc = App.newDocument("showcase")
    ImportGui.insert(cfg["step"], doc.Name)
    doc.recompute()
    Gui.ActiveDocument = Gui.getDocument(doc.Name)
    v = Gui.ActiveDocument.ActiveView
    shapes = [o for o in doc.Objects if hasattr(o, "Shape") and hasattr(o, "ViewObject") and o.ViewObject]
    for o in shapes:
        vo = o.ViewObject
        if hasattr(vo, "Deviation"):
            vo.Deviation = 0.05
        if hasattr(vo, "AngularDeflection"):
            vo.AngularDeflection = 6
        name = o.Label.lower()
        if name.startswith("prop"):
            vo.Transparency = 82
        if hasattr(vo, "LineWidth"):
            vo.LineWidth = 1

    def skin(visible):
        for o in shapes:
            if o.Label.lower().startswith(("fuselage", "canopy", "lid")):
                o.ViewObject.Visibility = visible

    def shot(name, rot, w, h, persp=True):
        v.setCameraType("Perspective" if persp else "Orthographic")
        if rot is None:
            {"top": v.viewTop, "side": v.viewFront, "front": v.viewRight, "rear": v.viewLeft}[name]()
        else:
            v.setCameraOrientation(rot.Q)
        v.fitAll()
        path = os.path.join(cfg["out"], "showcase_%s.png" % name)
        v.saveImage(path, w, h, "White")
        done.append(path)

    # three-quarter view from front-left, above
    hero = App.Rotation(App.Vector(0, 0, 1), 125).multiply(App.Rotation(App.Vector(1, 0, 0), 58))
    rear = App.Rotation(App.Vector(0, 0, 1), -55).multiply(App.Rotation(App.Vector(1, 0, 0), 62))
    W, H = cfg["size"]
    shot("hero", hero, W, H)
    shot("rear34", rear, W, H)
    for n in ("top", "side", "front"):
        shot(n, None, W, int(H * 0.7), persp=False)
    skin(False)
    shot("inside", hero, W, H)
    skin(True)
finally:
    open(cfg["log"], "w").write(json.dumps(done))
    os._exit(0)
'''


def find_freecad() -> Optional[str]:
    """The FreeCAD GUI executable, if one can be found."""
    cands: List[str] = []
    env = os.environ.get("RLCAD_FREECAD")
    if env:
        cands.append(env)
    try:
        cfg = json.load(open(os.path.expanduser("~/.rlcad/config.json"), encoding="utf-8"))
        if cfg.get("freecad"):
            cands.append(cfg["freecad"])
        if cfg.get("freecadcmd"):
            d = os.path.dirname(cfg["freecadcmd"])
            cands += [os.path.join(d, n) for n in ("freecad.exe", "FreeCAD.exe", "freecad", "FreeCAD")]
    except (OSError, ValueError):
        pass
    if sys.platform == "win32":
        for root in (os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
            cands += sorted(glob.glob(os.path.join(root, "FreeCAD*", "bin", "freecad.exe")), reverse=True)
    else:
        cands += ["/opt/fc/squashfs-root/AppRun", shutil.which("freecad") or "", shutil.which("FreeCAD") or "",
                  "/Applications/FreeCAD.app/Contents/MacOS/FreeCAD"]
    return next((c for c in cands if c and os.path.exists(c)), None)


def _clean_env() -> Dict[str, str]:
    drop = ("PYTHONHOME", "PYTHONPATH", "PYTHONUSERBASE", "PYTHONSTARTUP", "LD_LIBRARY_PATH", "QT_PLUGIN_PATH",
            "APPDIR", "APPIMAGE", "VIRTUAL_ENV")
    return {k: v for k, v in os.environ.items() if k not in drop}


def render_step(step: str, out_dir: str, size=(3200, 2000), freecad: Optional[str] = None,
                timeout: int = 600) -> Dict:
    """Render a STEP assembly with FreeCAD. Returns {"images": [...]} or {"error": ...}."""
    exe = freecad or find_freecad()
    if not exe:
        return {"error": "FreeCAD not found: set RLCAD_FREECAD or 'freecad' in ~/.rlcad/config.json"}
    os.makedirs(out_dir, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="rlcad_show_")
    script = os.path.join(tmp, "showcase.py")
    log = os.path.join(tmp, "done.json")
    open(script, "w", encoding="utf-8").write(_SCRIPT)
    env = _clean_env()
    env["RLCAD_SHOWCASE"] = json.dumps({"step": os.path.abspath(step), "out": os.path.abspath(out_dir),
                                        "size": list(size), "log": log})
    cmd = [exe, script]
    if sys.platform.startswith("linux") and not env.get("DISPLAY") and shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", "-s", "-screen 0 2400x1600x24"] + cmd
    try:
        subprocess.run(cmd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"error": f"FreeCAD did not finish within {timeout} s"}
    try:
        images = json.load(open(log, encoding="utf-8"))
    except (OSError, ValueError):
        return {"error": "FreeCAD ran but produced no images (check that the GUI can start)"}
    for im in images:
        _crop(im)
    return {"images": images, "freecad": exe}


def _crop(path: str, margin: int = 40):
    """Trim the white border FreeCAD's fitAll leaves around the model."""
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return
    im = Image.open(path).convert("RGB")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    box = ImageChops.difference(im, bg).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
    if box:
        l, t, r, b = box
        im.crop((max(0, l - margin), max(0, t - margin), min(im.width, r + margin), min(im.height, b + margin))).save(path)


def showcase(folder: str, **kw) -> Dict:
    step = os.path.join(folder, "out", "assembly.step")
    if not os.path.exists(step):
        return {"error": "out/assembly.step not found: run `rlcad export` first"}
    return render_step(step, os.path.join(folder, "out", "showcase"), **kw)
