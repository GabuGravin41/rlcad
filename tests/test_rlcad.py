"""RL CAD tests. The geometry build takes ~20 s, so it is built once per module."""
import os

import pytest

from rlcad import calc, catalog as C, checks
from rlcad.agent.tools import Session, run_tool
from rlcad.geom.mesh import mesh
from rlcad.project import Spec, build_model


# ------------------------------------------------------------------ pure calculations
def test_prop_static_scales_with_rpm_squared():
    a = calc.prop_static(0.13, 0.075, 76.2, 20000)["thrust_g"]
    b = calc.prop_static(0.13, 0.075, 76.2, 40000)["thrust_g"]
    assert b / a == pytest.approx(4.0, rel=1e-6)


def test_rpm_for_thrust_inverts_prop_static():
    rpm = calc.rpm_for_thrust(0.13, 76.2, 60.0)
    assert calc.prop_static(0.13, 0.075, 76.2, rpm)["thrust_g"] == pytest.approx(60.0, rel=1e-6)


def test_battery_position_puts_cg_on_target():
    items = [("a", 100.0, (10.0, 0, 0)), ("b", 50.0, (-4.0, 0, 0))]
    x = calc.battery_position_for_cg(items, 60.0, 0.0)
    cg = calc.centre_of_gravity(items + [("bat", 60.0, (x, 0, 0))])
    assert cg["cg_mm"][0] == pytest.approx(0.0, abs=1e-6)


def test_catalog_overrides_do_not_mutate_catalog():
    p = C.get("lipo_3s_650", mass_g=70.0, capacity_mah=700)
    assert p.mass_g == 70.0 and p.data["capacity_mah"] == 700
    assert C.get("lipo_3s_650").mass_g == 59.0


# ------------------------------------------------------------------ geometry + checks
@pytest.fixture(scope="module")
def model():
    return build_model(Spec(name="t"))


@pytest.fixture(scope="module")
def result(model):
    return checks.run(model)


def test_every_printed_part_is_one_valid_meshable_solid(model):
    for it in model.printable:
        assert len(it.shape.solids()) == 1, it.name
        assert it.shape.is_valid, it.name
        assert mesh(it.shape, 0.5)[2] == 0, it.name


def test_default_design_has_no_errors(result):
    assert result["summary"]["error"] == 0, [f for f in result["findings"] if f["severity"] == "error"]


def test_default_design_balances_and_flies(result):
    m = result["metrics"]
    assert abs(m["cg"]["cg_mm"][0]) <= 3 and abs(m["cg"]["cg_mm"][1]) <= 1.5
    assert m["propulsion"]["thrust_to_weight"] >= 2.8


def test_every_part_fits_the_a1_mini(result):
    assert all(v["fits"] for v in result["metrics"]["print_orientation"].values())


def test_small_bed_is_reported(model):
    r = checks.run(model, printer_bed=(100, 100, 100))
    assert any(f["rule"] == "bed_fit" and f["severity"] == "error" for f in r["findings"])


def test_heavy_battery_fails_thrust_to_weight():
    spec = Spec(name="heavy")
    spec.parts["battery"] = {"id": "lipo_3s_650", "mass_g": 900.0}
    r = checks.run(build_model(spec))
    assert any(f["rule"] == "propulsion" and f["severity"] == "error" for f in r["findings"])


def test_tight_tip_gap_is_an_error():
    spec = Spec(name="tight", airframe={"tip_gap": 0.5})
    r = checks.run(build_model(spec))
    assert any(f["rule"] == "prop_clearance" and f["severity"] == "error" for f in r["findings"])


# ------------------------------------------------------------------ agent tools
def test_tool_flow_and_exports(tmp_path):
    s = Session()
    folder = str(tmp_path / "f35")
    assert "error" not in run_tool(s, "project_create", {"folder": folder, "requirements": {"x": "y"}})
    assert "error" in run_tool(s, "spec_set_params", {"params": {"no_such_param": 1}})
    assert "error" in run_tool(s, "spec_set_part", {"role": "motor", "part_id": "lipo_3s_650"})
    assert run_tool(s, "next_step", {})["step"] == "build_and_check"
    r = run_tool(s, "build_and_check", {})
    assert r["summary"]["error"] == 0
    e = run_tool(s, "export", {})
    files = e["files"]
    for k in ("assembly_step", "frame_dxf", "bom_csv", "report_md", "design_json"):
        assert os.path.getsize(files[k]) > 0, k
    assert len(files["stls"]) == 10          # the canopy prints as part of the nose
    # the frame DXF has every hole as a full circle (the two motor patterns must not merge into slots)
    import ezdxf
    circles = [c for c in ezdxf.readfile(files["frame_dxf"]).modelspace() if c.dxftype() == "CIRCLE"]
    assert len(circles) == 4 * (1 + 4 + 1) + 4 + 4   # centre, XING2 9x9 M2 (4), pod post; stack 4; shell 4
    # a new session resumes the last build without rebuilding
    s2 = Session(folder)
    assert not s2.dirty and s2.exported


def test_usb_port_blocked_without_extension():
    r = checks.run(build_model(Spec(name="noext", airframe={"usb_port": []})))
    assert any(f["rule"] == "connector_access" and f["severity"] == "error" for f in r["findings"])


def test_usb_extension_port_is_reachable(result):
    assert any(f["rule"] == "connector_access" and f["severity"] == "info" for f in result["findings"])


# ------------------------------------------------------------------ PCB <-> CAD integration (needs RL PCB)
def test_integration_with_rl_pcb_board():
    pytest.importorskip("rlpcb")
    from rlcad.integrate import run
    folder = os.path.join(os.path.dirname(__file__), "..", "examples", "f35_ducted_quad")
    r = run(folder)
    assert r["ok"], r
    env = r["boards"]["fc"]["envelope"]
    assert env["mount_pattern_mm"] == 30.5 and env["keepout_height_mm"]["bottom"] > 2.5
    assert os.path.exists(r["boards"]["fc"]["envelope_file"])


def test_integration_catches_unreachable_usb(tmp_path):
    pytest.importorskip("rlpcb")
    import shutil
    from rlcad.integrate import run
    src = os.path.join(os.path.dirname(__file__), "..", "examples", "f35_ducted_quad")
    dst = tmp_path / "d"
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("out"))
    spec = Spec.load(str(dst))
    spec.airframe["usb_port"] = []
    spec.save(str(dst))
    r = run(str(dst))
    assert not r["ok"]
    cad_rules = {f["rule"] for f in r["cad"]["findings"] if f["severity"] == "error"}
    assert {"connector_access", "board_ports"} <= cad_rules
    pcb_rules = {f["rule"] for f in r["boards"]["fc"]["pcb_check"]["findings"] if f["severity"] == "error"}
    assert "mech_port" in pcb_rules


def test_section_helpers_match_geometry():
    """half_width_at / roof_z_at (used by checks and ports) agree with the lofted body."""
    from build123d import Plane
    from rlcad.geom import airframe as A
    p = A.AirframeParams()
    body = A.outer_loft(p)
    sec = body & Plane.YZ.offset(0.0) * __import__("build123d").Rectangle(200, 200)
    bb = sec.bounding_box()
    assert abs(A.roof_z_at(p, 0.0, 0.0) - bb.max.Z) < 0.2   # the centre section is pinned by stations every ~22 mm
    w = max(A.half_width_at(p, 0.0, z / 4) for z in range(0, 180))
    assert abs(w - bb.max.Y) < 0.2


def test_showcase_crop(tmp_path):
    from PIL import Image
    from rlcad.showcase import _crop
    im = Image.new("RGB", (400, 300), "white")
    im.paste((40, 40, 40), (100, 100, 150, 180))
    path = str(tmp_path / "a.png")
    im.save(path)
    _crop(path, margin=10)
    assert Image.open(path).size == (70, 100)


def test_print_audit_flags_knife_edges_and_overhangs():
    """The audit sees a knife edge (a 0.2 mm fin) and an unsupported shelf, and passes a plain block."""
    from build123d import Box, Pos
    from rlcad.printcheck import audit_shape, findings
    block = Box(20, 20, 10) + Pos(0, 0, 5) * Box(20, 0.2, 20)          # 0.2 mm wall: thinner than one line
    shelf = Box(10, 10, 20) + Pos(10, 0, 8) * Box(20, 10, 2)            # 15 mm cantilever shelf mid-air
    ok = Box(20, 20, 10)
    res = {"knife": audit_shape(block, "knife"), "shelf": audit_shape(shelf, "shelf"), "ok": audit_shape(ok, "ok")}
    rules = {(r[1], r[3][0]) for r in findings(res)}
    assert ("print_thin", "knife") in rules
    assert ("print_overhang", "shelf") in rules
    assert not any(n == "ok" for _, n in rules)


def test_printed_parts_need_no_support():
    """Every printed airframe part, in its export orientation, is closed, has no knife edges and needs no support."""
    from rlcad.export import PREFERRED, PRINT_WITH, print_orientation
    from rlcad.geom import airframe as A
    from rlcad.printcheck import audit_shape, findings
    p = A.AirframeParams()
    parts = A.build(p)
    res = {}
    for n in ("pod_front_left", "fin_left", "fuselage_tail"):
        sh = parts[n]["shape"]
        for e in PRINT_WITH.get(n, []):
            sh = sh + parts[e]["shape"]
        placed, _ = print_orientation(sh, (180, 180, 180), PREFERRED.get(n))
        res[n] = audit_shape(placed, n)
    bad = [f for f in findings(res) if f[0] == "error" or f[1] == "print_overhang"]
    assert not bad, bad


def test_scaffolding_fixes_and_try_fix(tmp_path):
    """A broken design comes back with ready-made fixes, and try_fix repairs it (the loop a smaller model runs)."""
    s = Session()
    folder = str(tmp_path / "f35")
    run_tool(s, "project_create", {"folder": folder, "requirements": {"x": "y"}})
    run_tool(s, "spec_set_params", {"params": {"tip_gap": 0.5}})
    r = run_tool(s, "build_and_check", {})
    i, f = next((i, f) for i, f in enumerate(r["findings"]) if f["rule"] == "prop_clearance" and f["severity"] == "error")
    assert f["fixes"][0]["tool"] == "spec_set_params"
    nxt = run_tool(s, "next_step", {})
    assert nxt["call"]["tool"] == "try_fix"
    fx = run_tool(s, "try_fix", nxt["call"]["args"])
    assert fx["kept"], fx
    assert fx["after"]["errors"] < fx["before"]["errors"]
    comp = run_tool(s, "parts_compatible", {"role": "prop"})["parts"]
    assert comp[0]["compatible"] and comp[0]["id"] == "prop_gemfan_3016_3"
    stages = run_tool(s, "design_checklist", {})["stages"]
    assert stages[0]["state"] == "done"
