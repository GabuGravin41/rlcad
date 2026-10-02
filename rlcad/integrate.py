"""One command that makes the PCB side and the CAD side agree.

    rlcad integrate <design folder>

1. Refresh each board's mech.json from its .kicad_pcb (RL PCB), place the boards in the airframe, run every check.
2. Write enclosure.json into each board's KiCad project (the space the product gives that board).
3. Check each board against its envelope with RL PCB's `mech_check` rules, and the cables between boards with
   RL PCB's `system_check` (electronics/system.json), when RL PCB is installed.
4. Write out/integration.md and out/integration.json.
"""
from __future__ import annotations

import json
import os
from typing import Dict


def run(folder: str) -> Dict:
    from . import checks
    from .mech import check_with_rlpcb, write_envelope
    from .project import Spec, build_model
    folder = os.path.abspath(folder)
    spec = Spec.load(folder)
    model = build_model(spec, base_dir=folder)
    res = checks.run(model, print_audit=False)      # the PCB <-> CAD questions do not need the slicer audit
    report = {"design": spec.name, "cad": {"summary": res["summary"],
                                           "findings": [f for f in res["findings"] if f["rule"].startswith(("board_", "connector_"))]},
              "boards": {}, "system": None}
    from .interface import mark_seen, unseen
    for slot, bd in model.boards.items():
        env = res["metrics"]["boards"][slot]["envelope"]
        pdir = bd["mech"]["project_dir"]
        from_pcb = unseen(pdir, "cad")                 # what the electronics side changed since we last looked
        path = write_envelope(bd["mech"], env)
        pcb_side = check_with_rlpcb(bd["mech"], env)
        board_findings = [f for f in res["findings"] if f["rule"].startswith(("board_", "connector_"))
                          and f["severity"] != "info"]
        if from_pcb:
            mark_seen(pdir, "cad", [e["id"] for e in from_pcb],
                      "checked by rlcad integrate: " + (f"{len(board_findings)} board findings" if board_findings
                                                        else "board still fits"))
        report["boards"][slot] = {"project": bd["mech"]["project_dir"], "pcb": bd["mech"].get("pcb"),
                                  "mech": {k: bd["mech"][k] for k in ("outline_mm", "height_mm", "mounting_holes")},
                                  "connectors": [{k: c.get(k) for k in ("ref", "mate", "edge", "populated")}
                                                 for c in bd["mech"]["connectors"]],
                                  "envelope_file": path, "envelope": env,
                                  "changes_from_electronics": from_pcb,
                                  "changes_sent_to_electronics": bd["mech"].get("_envelope_notice"),
                                  "pcb_check": pcb_side or {"skipped": "RL PCB not installed in this Python"}}
    sysjson = os.path.join(folder, "electronics", "system.json")
    if os.path.exists(sysjson):
        try:
            from rlpcb.agent.tools import Session as PSession, run_tool as prun
            r = prun(PSession(), "system_check", {"folder": os.path.dirname(sysjson)})
            report["system"] = {"summary": r.get("summary"), "findings": r.get("findings"), "error": r.get("error")}
        except ImportError:
            report["system"] = {"skipped": "RL PCB not installed in this Python"}
    errs = res["summary"]["error"] + sum((b["pcb_check"].get("summary") or {}).get("error", 0)
                                         for b in report["boards"].values()) + \
        ((report["system"] or {}).get("summary") or {}).get("error", 0)
    report["ok"] = errs == 0
    out = os.path.join(folder, "out")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "integration.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1, default=str)
    with open(os.path.join(out, "integration.md"), "w", encoding="utf-8") as f:
        f.write(_markdown(report, folder))
    report["files"] = [os.path.join(out, "integration.json"), os.path.join(out, "integration.md")]
    return report


def _markdown(r: Dict, folder: str = "") -> str:
    def rel(path):
        try:
            return os.path.relpath(path, folder).replace(os.sep, "/") if folder else path
        except ValueError:
            return path

    L = [f"# {r['design']}: PCB ↔ CAD integration", "", f"Result: {'OK' if r['ok'] else 'problems found'}", ""]
    L += ["## Airframe side (RL CAD)", ""]
    for f in r["cad"]["findings"]:
        L.append(f"- **{f['severity']}** {f['rule']}: {f['message']}")
    for slot, b in r["boards"].items():
        env = b["envelope"]
        L += ["", f"## Board slot `{slot}`", "",
              f"- KiCad project: `{rel(b['project'])}`",
              f"- Board: {b['mech']['outline_mm']['size'][0]}×{b['mech']['outline_mm']['size'][1]} mm, parts "
              f"{b['mech']['height_mm']['bottom']} mm below / {b['mech']['height_mm']['top']} mm above",
              f"- Space the airframe gives it: {env['max_outline_mm'][0]}×{env['max_outline_mm'][1]} mm, "
              f"{env['keepout_height_mm']['bottom']} mm below / {env['keepout_height_mm']['top']} mm above, "
              f"{env['mount_pattern_mm']} mm mounting pattern",
              f"- Edges that can reach outside: {', '.join(env['reachable_edges']) or 'none'}",
              f"- Envelope written to `{rel(b['envelope_file'])}` (RL PCB `mech_check` reads it)", "",
              "| Connector | Mate | Faces | Populated |", "|---|---|---|---|"]
        for c in b["connectors"]:
            L.append(f"| {c['ref']} | {c['mate'] or ''} | {c['edge'] or ''} | {'yes' if c['populated'] else 'no'} |")
        if b.get("changes_from_electronics"):
            L += ["", "Changes from the electronics side since the last check (now reviewed):", ""]
            for e in b["changes_from_electronics"]:
                for c in e["changes"]:
                    L.append(f"- {e['date']}: {c['what']}: {c['detail']} (affects {', '.join(c['affects'])})")
        if b.get("changes_sent_to_electronics"):
            L += ["", "Changes this design made to the board's space (logged for RL PCB):", ""]
            for c in b["changes_sent_to_electronics"]["changes"]:
                L.append(f"- {c['what']}: {c['detail']}")
        pc = b["pcb_check"]
        L += ["", "PCB side (RL PCB `mech_check`):", ""]
        if "skipped" in pc:
            L.append(f"- skipped: {pc['skipped']}")
        else:
            for f in pc["findings"]:
                L.append(f"- **{f['severity']}** {f['rule']}: {f['message']}")
    if r["system"]:
        L += ["", "## Cables between boards (RL PCB `system_check`)", ""]
        if "skipped" in r["system"]:
            L.append(f"- skipped: {r['system']['skipped']}")
        else:
            L.append(f"- summary: {r['system'].get('summary')}")
            for f in r["system"].get("findings") or []:
                L.append(f"- **{f['severity']}** {f['rule']}: {f['message']}")
    return "\n".join(L) + "\n"
