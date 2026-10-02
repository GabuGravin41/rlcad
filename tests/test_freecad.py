"""FreeCAD workbench core, run inside FreeCAD's own Python. Set RLCAD_FREECADCMD to freecadcmd to enable."""
import json
import os
import shutil
import subprocess
import sys

import pytest

FCCMD = os.environ.get("RLCAD_FREECADCMD")
ADDON = os.path.join(os.path.dirname(__file__), "..", "rlcad", "adapters", "freecad", "RLCAD")


@pytest.mark.skipif(not FCCMD, reason="set RLCAD_FREECADCMD to run FreeCAD tests")
def test_open_set_sync_in_freecad(tmp_path):
    src = os.path.join(os.path.dirname(__file__), "..", "examples", "f35_ducted_quad")
    d = tmp_path / "design"
    shutil.copytree(src, d)
    script = tmp_path / "t.py"
    script.write_text(f"""
import sys, json
sys.path.insert(0, {os.path.abspath(ADDON)!r})
from rlcad_freecad import core
import FreeCAD as App
core.open_design({str(d)!r})
doc = App.ActiveDocument
core.set_params({{"fin_h": 44}}, doc=doc)
r = core.sync(doc=doc)
open({str(tmp_path / 'out.json')!r}, 'w').write(json.dumps({{"applied": r["applied"], "summary": r["summary"],
    "fin_h": core.read_params(doc)["fin_h"]}}))
""")
    env = dict(os.environ, RLCAD_PYTHON=sys.executable)
    subprocess.run([FCCMD, str(script)], check=True, timeout=900, env=env, capture_output=True)
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["applied"] == {"fin_h": 44.0} and out["fin_h"] == 44.0 and out["summary"]["error"] == 0


@pytest.mark.skipif(not FCCMD, reason="set RLCAD_FREECADCMD to run FreeCAD tests")
def test_engineer_accepts_ai_proposal_in_freecad(tmp_path):
    """The AI proposes a change (MCP side); the engineer accepts it from FreeCAD; the model reloads."""
    ex = os.path.join(os.path.dirname(__file__), "..", "examples")
    shutil.copytree(os.path.join(ex, "fc_enclosure"), tmp_path / "fc_enclosure", ignore=shutil.ignore_patterns("out", ".rlcad"))
    shutil.copytree(os.path.join(ex, "f35_ducted_quad", "electronics"), tmp_path / "f35_ducted_quad" / "electronics")
    d = tmp_path / "fc_enclosure"
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from rlcad.agent.tools import Session, run_tool
    s = Session(str(d))
    run_tool(s, "copilot_mode", {"mode": "propose"}, actor="engineer")
    pid = run_tool(s, "spec_set_params", {"params": {"wall": 2.4}})["proposal"]
    script = tmp_path / "t.py"
    script.write_text(f"""
import sys, json
sys.path.insert(0, {os.path.abspath(ADDON)!r})
from rlcad_freecad import core
import FreeCAD as App
core.open_design({str(d)!r})
doc = App.ActiveDocument
st = core.tool("copilot_status", doc=doc)
r = core.accept_proposal({pid!r}, doc=doc)
open({str(tmp_path / 'out.json')!r}, 'w').write(json.dumps({{"pending": len(st["pending_proposals"]), "accepted": r.get("accepted"),
    "wall": core.read_params(doc)["wall"], "summary": r.get("summary")}}))
""")
    env = dict(os.environ, RLCAD_PYTHON=sys.executable)
    subprocess.run([FCCMD, str(script)], check=True, timeout=900, env=env, capture_output=True)
    out = json.loads((tmp_path / "out.json").read_text())
    assert out["pending"] == 1 and out["accepted"] == pid and out["wall"] == 2.4 and out["summary"]["error"] == 0


@pytest.mark.skipif(not os.environ.get("RLCAD_FREECAD_GUI"), reason="set RLCAD_FREECAD_GUI to the FreeCAD GUI executable "
                                                                    "(runs under xvfb-run on Linux)")
def test_workbench_registers_commands_in_gui(tmp_path):
    """The workbench loads in the FreeCAD GUI and registers every command (InitGui.py runs in a restricted scope)."""
    import tempfile
    ud = tmp_path / "ud"
    mod = ud / "Mod" / "RLCAD"
    shutil.copytree(ADDON, mod)
    out = tmp_path / "gui.json"
    script = tmp_path / "g.py"
    script.write_text(f"""
import os, json
import FreeCADGui as Gui
Gui.activateWorkbench("RLCADWorkbench")
open({str(out)!r}, "w").write(json.dumps([c for c in Gui.listCommands() if c.startswith("RLCAD")]))
os._exit(0)
""")
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    env["FREECAD_USER_HOME"] = str(ud)
    cmd = [os.environ["RLCAD_FREECAD_GUI"], str(script)]
    if sys.platform.startswith("linux") and not env.get("DISPLAY"):
        cmd = ["xvfb-run", "-a"] + cmd
    subprocess.run(cmd, timeout=180, env=env, capture_output=True)
    cmds = json.loads(out.read_text())
    assert {"RLCAD_Open", "RLCAD_Sync", "RLCAD_Proposals", "RLCAD_Mode", "RLCAD_Undo", "RLCAD_Review"} <= set(cmds)
