"""Copilot in RL CAD: modes, proposals checked on a copy, accept/undo, features, reviews, kickoff, interface notices.
Uses the enclosure example (it builds in seconds)."""
import json
import os
import shutil

import pytest

from rlcad.agent.tools import Session, run_tool

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EX = os.path.join(HERE, "examples")


@pytest.fixture()
def enc(tmp_path, monkeypatch):
    monkeypatch.setenv("RLCAD_DEFAULT_MODE", "propose")
    shutil.copytree(os.path.join(EX, "fc_enclosure"), tmp_path / "fc_enclosure", ignore=shutil.ignore_patterns("out", ".rlcad"))
    shutil.copytree(os.path.join(EX, "f35_ducted_quad", "electronics"), tmp_path / "f35_ducted_quad" / "electronics",
                    ignore=shutil.ignore_patterns("gerbers", "jlcpcb", "interface_log.json"))
    s = Session(str(tmp_path / "fc_enclosure"))
    r = run_tool(s, "build_and_check", {})
    assert r["summary"]["error"] == 0, r["findings"]
    return s, tmp_path


def test_enclosure_follows_the_board(enc):
    s, tmp = enc
    m = s.model
    assert {i.name for i in m.printable} == {"base", "lid"}
    ops = {o["ref"]: o for o in m.params.port_holes}
    assert ops["J2"]["edge"] == "+y" and "J6" not in ops            # J6 is not fitted: no opening
    assert any(f["rule"] == "connector_access" and f["severity"] == "info" for f in s.result["findings"])


def test_proposal_is_checked_then_accepted_and_undone(enc):
    s, tmp = enc
    r = run_tool(s, "spec_set_params", {"params": {"gap_above": 0.2}})
    assert r["proposal"] and "gap_above" in r["summary"]
    assert r["checks"]["errors_after"] >= 1 and r["checks"]["new_findings"], "the copy must be built and checked"
    assert "gap_above" not in s.spec.airframe
    run_tool(s, "proposal_reject", {"id": r["proposal"], "reason": "too tight"}, actor="engineer")
    r = run_tool(s, "spec_set_params", {"params": {"wall": 2.4}})
    a = run_tool(s, "proposal_accept", {"id": r["proposal"]}, actor="engineer")
    assert s.spec.airframe["wall"] == 2.4 and not s.dirty, "accepted proposals keep their check results"
    run_tool(s, "undo", {"id": a["journal_id"]})
    assert "wall" not in s.spec.airframe


def test_advise_blocks_and_do_journals(enc):
    s, tmp = enc
    run_tool(s, "copilot_mode", {"mode": "advise", "scope": "part:base"}, actor="engineer")
    r = run_tool(s, "feature_add", {"part": "base", "type": "hole", "at": [0, -25, 8], "axis": "y", "d": 5})
    assert r["blocked_by_mode"] == "advise"
    run_tool(s, "copilot_mode", {"mode": "do", "scope": "part:base"}, actor="engineer")
    r = run_tool(s, "feature_add", {"part": "base", "type": "hole", "at": [0, -25, 8], "axis": "y", "d": 5,
                                    "note": "cable exit"})
    assert r["copilot"]["journal_id"] and len(s.spec.features) == 1
    b = run_tool(s, "build_and_check", {})
    assert b["summary"]["error"] == 0
    assert any(e["action"] == "feature_add" for e in run_tool(s, "design_journal", {})["entries"])


def test_reviews(enc):
    s, tmp = enc
    f = run_tool(s, "review_part", {"part": "base"})
    assert f["process"] == "fdm" and f["points"]
    m = run_tool(s, "review_part", {"part": "base", "process": "injection_molding"})
    assert any(p["category"] == "draft" and p["level"] == "concern" for p in m["points"])   # printed walls have no draft


def test_kickoff_and_explain(tmp_path):
    s = Session()
    b = run_tool(s, "kickoff", {"idea": "a case for my sensor board"})
    assert b["archetype"] == "enclosure" and b["family"] == "enclosure"
    assert run_tool(s, "kickoff", {"idea": "a wall bracket for a camera"})["family"] is None
    e = run_tool(s, "explain", {"topic": "rule:connector_access"})
    assert "plug" in e["protects_against"]


def test_interface_notices_both_ways(enc):
    s, tmp = enc
    from rlcad.interface import unseen
    proj = str(tmp / "f35_ducted_quad" / "electronics" / "rl_fc_f405")
    # the electronics side moves J2
    mp = os.path.join(proj, "rl_fc_f405.mech.json")
    mech = json.load(open(mp))
    from rlcad.interface import mech_diff, write_with_notice
    new = json.loads(json.dumps(mech))
    j2 = next(c for c in new["connectors"] if c["ref"] == "J2")
    j2["at_mm"] = [j2["at_mm"][0] + 5, j2["at_mm"][1]]
    j2["bbox_mm"] = [j2["bbox_mm"][0] + 5, j2["bbox_mm"][1], j2["bbox_mm"][2] + 5, j2["bbox_mm"][3]]
    os.utime(mp, None)
    write_with_notice(mp, new, "pcb", mech_diff)
    os.utime(mp, (os.path.getmtime(mp) + 100, os.path.getmtime(mp) + 100))   # newer than the .kicad_pcb: no regen
    assert unseen(proj, "cad")
    r = run_tool(s, "integration_check", {})
    assert not unseen(proj, "cad"), "integration_check reviews the electronics' notices"
    before = {o["ref"]: o["centre"] for o in s.model.params.port_holes}["J2"]
    run_tool(s, "copilot_mode", {"mode": "do"}, actor="engineer")
    s.dirty = True
    run_tool(s, "build_and_check", {})
    after = {o["ref"]: o["centre"] for o in s.model.params.port_holes}["J2"]
    assert abs(after - before - 5) < 0.01, "the enclosure's opening follows the connector"


def test_shared_board_keeps_one_envelope_per_product(tmp_path):
    """Two products using one board must not overwrite each other's enclosure.json."""
    import json
    from rlcad.mech import envelope_path, write_envelope
    d = str(tmp_path)
    mech = {"project_dir": d}
    p1 = write_envelope(mech, {"schema": "rl-envelope/1", "product": "drone", "max_outline_mm": [40, 40]})
    p2 = write_envelope(dict(mech), {"schema": "rl-envelope/1", "product": "box v2", "max_outline_mm": [50, 50]})
    assert p1.endswith("enclosure.json") and p2.endswith("enclosure.box_v2.json")
    assert json.load(open(p1))["product"] == "drone"
    assert envelope_path(d, "drone") == p1 and envelope_path(d, "box v2") == p2
