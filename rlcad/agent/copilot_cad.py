"""RL CAD side of the copilot: which tools change the design, the scope each touches, how a change is summarised,
and what was and was not verified. Proposals are built and checked on a copy of the design, so the engineer sees the
consequences (check results before/after) before accepting.
"""
from __future__ import annotations

import json
import os
import shutil
from typing import Any, Callable, Dict, List, Optional, Tuple

from .copilot import Copilot, gate_message

INCLUDE = ["rlcad.json", "docs/*"]
EXCLUDE = ["out/*", ".rlcad/*"]
CONTEXT_DIRS = ["electronics", "boards"]          # read by the build; copied into a proposal's work copy

PARAM_SCOPE = [("duct_", "part:pods"), ("tip_gap", "part:pods"), ("wing_", "part:pods"), ("tail_", "part:pods"),
               ("span_", "part:pods"), ("te_min", "part:pods"),
               ("fus_", "part:fuselage"), ("nose_", "part:fuselage"), ("skin_", "part:fuselage"),
               ("chine_", "part:fuselage"), ("usb_port", "part:fuselage"), ("port_holes", "part:fuselage"),
               ("fin_", "part:fins"), ("frame_", "part:frame"), ("plate_", "part:frame"), ("arm_", "part:frame"),
               ("rib_", "part:frame"), ("stack_", "layout"), ("motor_", "part:frame"), ("fit_clear", "airframe")]


def _param_scope(name: str) -> str:
    return next((s for pfx, s in PARAM_SCOPE if name.startswith(pfx)), "airframe")


def classify(name: str, args: Dict, session=None) -> Tuple[str, List[str]]:
    a = args or {}
    if name == "spec_set_params":
        return "design", sorted({_param_scope(k) for k in (a.get("params") or {})}) or ["airframe"]
    if name == "spec_set_part":
        return "design", [f"parts:{a.get('role', '')}"]
    if name == "spec_set_printer":
        return "design", ["printing"]
    if name in ("spec_set_fc_board", "spec_set_board"):
        return "design", ["boards"]
    if name in ("feature_add", "feature_remove"):
        part = a.get("part") or ""
        if not part and session is not None and session.spec:
            part = next((f["part"] for f in session.spec.features if f.get("id") == a.get("id")), "")
        kindmap = {"pod": "pods", "fin": "fins", "canopy": "fuselage"}
        k = part.split("_")[0] if part else "airframe"
        return "design", [f"part:{kindmap.get(k, k)}" if part else "airframe"]
    if name == "decision_add":
        return ("decision", ["decisions"]) if str(a.get("text", "")).upper().startswith("ACK") else ("design", ["notes"])
    if name == "try_fix":
        try:
            from .fixes import fixes_for
            f = session.result["findings"][int(a.get("finding", 0))]
            fx = (f.get("fixes") or fixes_for(f, session.spec, session.model.params if session.model else None))
            c = fx[int(a.get("fix", 0))]
            return classify(c["tool"], c["args"], session)
        except Exception:  # noqa
            return "design", ["airframe"]
    if name == "freecad_sync" and a.get("values"):
        return "design", sorted({_param_scope(k) for k in a["values"]})
    if name == "project_create":
        return "create", ["project"]
    if name == "onshape_upload":
        return "publish", ["publish"]
    return "read", []


def copilot_for_dir(folder: str) -> Copilot:
    mode = os.environ.get("RLCAD_DEFAULT_MODE", "propose")
    return Copilot(folder, os.path.join(folder, ".rlcad", "copilot"), INCLUDE, EXCLUDE, default_mode=mode)


def copilot_for(session) -> Copilot:
    session.need()
    return copilot_for_dir(session.folder)


# ------------------------------------------------------------------------------------------- summaries
def _spec(path: str) -> Dict:
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def summarize(before_root: str, after_root: str, ch: Dict) -> Dict:
    lines = []
    if "rlcad.json" in ch["changed"] + ch["added"]:
        a, b = _spec(os.path.join(before_root, "rlcad.json")), _spec(os.path.join(after_root, "rlcad.json"))
        pa, pb = a.get("airframe", {}), b.get("airframe", {})
        for k in sorted(set(pa) | set(pb)):
            if pa.get(k) != pb.get(k):
                lines.append(f"{k}: {pa.get(k, 'default')} → {pb.get(k, 'default')}")
        for role in sorted(set(a.get("parts", {})) | set(b.get("parts", {}))):
            if a.get("parts", {}).get(role) != b.get("parts", {}).get(role):
                lines.append(f"{role}: {a.get('parts', {}).get(role, {}).get('id')} → {b.get('parts', {}).get(role, {}).get('id')}")
        if a.get("printer") != b.get("printer"):
            lines.append(f"printer: {a.get('printer')} → {b.get('printer')}")
        if a.get("materials") != b.get("materials"):
            lines.append(f"materials: {b.get('materials')}")
        if a.get("boards") != b.get("boards"):
            lines.append(f"boards: {b.get('boards')}")
        fa = {f.get("id"): f for f in a.get("features", [])}
        fb = {f.get("id"): f for f in b.get("features", [])}
        for i in fb:
            if i not in fa:
                f = fb[i]
                lines.append(f"feature added: {f['type']} on {f['part']} at {f.get('at') or f.get('from')}"
                             + (f" ({f['note']})" if f.get("note") else ""))
        for i in fa:
            if i not in fb:
                lines.append(f"feature removed: {fa[i]['type']} on {fa[i]['part']}")
        dec = b.get("decisions", [])[len(a.get("decisions", [])):]
        if dec:
            lines.append("decision: " + " | ".join(dec))
    for rel in ch["added"] + ch["changed"]:
        if rel != "rlcad.json":
            lines.append(f"{'new' if rel in ch['added'] else 'changed'}: {rel}")
    return {"text": "; ".join(lines) or "no change in substance", "lines": lines}


# ------------------------------------------------------------------------------------------- assurance
STATIC_GAPS = [
    "Aerodynamics: not modelled (the wings are cosmetic on a multirotor); duct thrust gain not counted",
    "Structure: arms are checked as cantilevers; there is no FEA of the shells or joints",
    "Propulsion: prop coefficients are typical values, not thrust-stand data for the exact motor and prop",
    "Printing: the print audit approximates a slicer (wall thickness by ray casting, 45° overhang rule); check the "
    "slicer preview before printing",
    "Fits: slip fits and screw bosses use nominal clearances; printer tolerance varies, print one joint first",
]


def unverified(session) -> List[str]:
    from .. import catalog as C
    out = []
    sp = session.spec
    if not sp:
        return out
    for role in ("motor", "prop", "esc", "receiver", "battery", "fc"):
        try:
            p = sp.part(role)
        except Exception:  # noqa
            continue
        src = (p.source or "").lower()
        if any(w in src for w in ("nominal", "estimate", "typical", "allowance")):
            out.append(f"{role} '{p.name}': some numbers are nominal or estimated ({p.source[:120]}…)")
    if sp.features:
        out.append(f"{len(sp.features)} engineer/AI features are checked for solid, interference and printing, but "
                   "not for strength")
    return out


def assurance(session, delta: Optional[Dict] = None) -> Dict:
    return {"checks_run": ["build", "bed fit", "prop clearance", "interference", "mass/CG", "propulsion",
                           "arm stiffness", "solid integrity", "print audit", "parts fit and power",
                           "PCB ↔ CAD board checks"] if delta else ["none yet: run build_and_check"],
            "result": delta, "not_verified": unverified(session) + STATIC_GAPS}


def check_delta(before: Optional[List[Dict]], after: List[Dict]) -> Dict:
    after = [f for f in after if f["severity"] in ("error", "warning")]
    out = {"errors_after": sum(f["severity"] == "error" for f in after),
           "warnings_after": sum(f["severity"] == "warning" and not f.get("acknowledged") for f in after)}
    if before is None:
        out["before"] = "not built before this change"
        out["findings_after"] = [f"{f['severity']}: {f['message']}" for f in after][:10]
        return out
    before = [f for f in before if f["severity"] in ("error", "warning")]
    key = lambda f: (f["severity"], f["rule"], f["message"])
    kb, ka = {key(f) for f in before}, {key(f) for f in after}
    out.update(errors_before=sum(f["severity"] == "error" for f in before),
               warnings_before=sum(f["severity"] == "warning" and not f.get("acknowledged") for f in before),
               new_findings=[f"{f['severity']}: {f['message']}" for f in after if key(f) not in kb][:10],
               resolved_findings=[f"{f['severity']}: {f['message']}" for f in before if key(f) not in ka][:10])
    return out


def _copy_boards_outside(src: str, work: str):
    """Boards linked by a relative path outside the design folder ('../x/board') resolve, from the work copy, to the
    same relative place next to it; copy them there (inside the proposal's folder) so the copy builds."""
    sp = _spec(os.path.join(src, "rlcad.json"))
    pdir = os.path.dirname(work)
    for entry in (sp.get("boards") or {}).values():
        rel = entry.get("project", "")
        if not rel or os.path.isabs(rel) or not rel.startswith(".."):
            continue
        source = os.path.normpath(os.path.join(src, rel))
        target = os.path.normpath(os.path.join(work, rel))
        if not target.startswith(pdir + os.sep) or os.path.exists(target):
            continue
        if os.path.isfile(source):
            source, target = os.path.dirname(source), os.path.dirname(target)
        if os.path.isdir(source):
            shutil.copytree(source, target, ignore=shutil.ignore_patterns(
                "gerbers", "jlcpcb", "*-backups", ".rlpcb", "*.kicad_prl"))


# ------------------------------------------------------------------------------------------- the gate
def _copy_context(src: str, work: str):
    _copy_boards_outside(src, work)
    for d in CONTEXT_DIRS:
        s = os.path.join(src, d)
        if os.path.isdir(s) and not os.path.exists(os.path.join(work, d)):
            shutil.copytree(s, os.path.join(work, d), ignore=shutil.ignore_patterns(
                "gerbers", "jlcpcb", "*-backups", ".rlpcb", "*.kicad_prl", "copilot"))
    # the last build's results let the work copy report "before" without a rebuild
    o = os.path.join(src, "out", "checks.json")
    if os.path.exists(o):
        os.makedirs(os.path.join(work, "out"), exist_ok=True)
        shutil.copy2(o, os.path.join(work, "out", "checks.json"))


def gate(session, name: str, args: Dict, fn: Callable[..., Any], actor: str = "ai", build_check=None) -> Dict:
    """Run a tool call under the copilot rules. build_check(session) -> findings is used to check proposals."""
    if getattr(session, "_in_gate", False):
        return fn(session, **(args or {}))
    kind, scopes = classify(name, args, session)
    if kind in ("read", "create") or not session.folder:
        return fn(session, **(args or {}))
    cp = copilot_for(session)
    m = cp.mode_for(scopes)
    mode = m["mode"]
    if kind == "publish":
        if mode == "do" or actor == "engineer":
            return fn(session, **(args or {}))
        return dict(gate_message("advise", m["from"], name, args, scopes),
                    message="Uploading to Onshape publishes the design outside this folder; ask the engineer to "
                            "confirm (or set mode 'do').")
    if kind == "decision" and mode == "do" and actor == "ai":
        mode = "propose"
    if actor == "engineer":
        mode = "do"                            # the engineer's own edits always apply (journalled, undoable)
    if mode in ("teach", "advise"):
        cp.log(actor, "advice", {"tool": name, "args": args}, summary=f"blocked in {mode} mode", scopes=scopes)
        return gate_message(mode, m["from"], name, args, scopes)
    before = session.result["findings"] if (session.result is not None and not session.dirty) else None
    if mode == "propose":
        from .tools import Session

        def run_in(work):
            _copy_context(session.folder, work)
            s2 = Session(work)
            s2._in_gate = True
            if session.model is not None and not session.dirty:
                s2.model, s2.result, s2.dirty = session.model, session.result, False
            return fn(s2, **(args or {}))
        prop = cp.propose(actor, name, args, run_in, scopes, summarize)
        work = cp.work_dir(prop["id"])
        checks = None
        if build_check and any(prop["changes"].values()) and kind != "decision":
            s2 = Session(work)
            s2._in_gate = True
            try:
                after = build_check(s2)
                checks = check_delta(before, after)
            except Exception as e:  # noqa
                checks = {"error": f"the proposed design does not build: {e}"}
            prop["summary"]["checks"] = checks
            prop["assurance"] = assurance(s2, checks)
            cp._save_proposal(prop)
        return {"proposal": prop["id"], "mode": "propose", "scopes": scopes, "summary": prop["summary"]["text"],
                "checks": checks, "assurance": prop.get("assurance"), "tool_result": prop.get("result"),
                "next": "show the engineer what changes and what the checks say; call proposal_accept(id) only when "
                        "they agree, otherwise proposal_reject(id, reason)."}
    session._in_gate = True
    try:
        out = cp.apply(actor, name, args, lambda: fn(session, **(args or {})), scopes, summarize)
    finally:
        session._in_gate = False
    res = out["result"] if isinstance(out["result"], dict) else {"result": out["result"]}
    res = dict(res)
    if any(out["changes"].values()):
        res["copilot"] = {"mode": "do", "journal_id": out.get("journal_id"), "summary": out["summary"].get("text"),
                          "undo": out.get("undo"), "assurance": assurance(session)}
    return res


def accept(session, pid: str, note: str = "", force: bool = False) -> Dict:
    cp = copilot_for(session)
    work = cp.work_dir(pid)
    r = cp.accept(pid, note, force)
    # reuse the proposal's build results (same spec), so no rebuild is needed after accepting
    src = os.path.join(work, "out", "checks.json")
    if os.path.exists(src) and os.path.exists(os.path.join(work, "rlcad.json")):
        try:
            with open(src, encoding="utf-8") as f:
                ck = json.load(f)
            spec_t = _spec(os.path.join(session.folder, "rlcad.json")).get("updated")
            if abs((ck.get("spec_updated") or 0) - (spec_t or -1)) < 1e-6:
                os.makedirs(os.path.join(session.folder, "out"), exist_ok=True)
                ck["exported"] = False
                with open(os.path.join(session.folder, "out", "checks.json"), "w", encoding="utf-8") as f:
                    json.dump(ck, f, default=str)
        except (OSError, ValueError):
            pass
    session.open(session.folder)
    return r
