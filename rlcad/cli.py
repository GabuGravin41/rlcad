"""Command line: rlcad <command> [folder]

    rlcad new <folder> [--name N] [--printer bambu_a1_mini]    create a design (F-35-style ducted quad)
    rlcad check <folder>                                      build + all checks
    rlcad export <folder> [--force]                           STEP / STL / DXF / BOM / report into <folder>/out
    rlcad render <folder> [--what assembly|airframe|inside|<part>]
    rlcad showcase <folder>             presentation renders through FreeCAD (after export)
    rlcad fc <folder> <board.kicad_pcb|board.step>            use a real KiCad board
    rlcad set <folder> key=value ...                           airframe parameters (numbers)
    rlcad tool <folder> <tool_name> '<json args>'             call any agent tool
    rlcad onshape <folder> [--name N]                         upload the exported STEP to Onshape
    rlcad params <folder>                                     effective airframe parameters as JSON (for CAD UIs)
    rlcad apply <folder> '<json params>'                      set parameters, rebuild, check, export (JSON result)
    rlcad sync <folder>                                       rebuild, check, export even with errors (JSON result)
    rlcad integrate <folder>                                  PCB <-> CAD: mech.json in, enclosure.json out, both checked
    rlcad tools                                               list agent tools
    rlcad mcp                                                 run the MCP server (stdio)
"""
from __future__ import annotations

import argparse
import json
import sys

from .agent.tools import TOOLS, Session, run_tool, to_json


def _print_check(res):
    if "error" in res and isinstance(res["error"], str):
        print("ERROR:", res["error"])
        return 1
    s = res["summary"]
    print(f"checks: {s['error']} errors, {s['warning']} warnings, {s['info']} info")
    for f in res["findings"]:
        ack = " (acknowledged)" if f.get("acknowledged") else ""
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}{ack}")
    m = res.get("metrics") or {}
    if "auw_g" in m:
        print(f"AUW {m['auw_g']} g · CG {m['cg_mm']} · T/W {m['thrust_to_weight']} · hover {m['hover_throttle_pct']} % "
              f"· {m['hover_min']} min · arm {m['arm']}")
    elif m:
        print(" · ".join(f"{k} {v}" for k, v in m.items() if not isinstance(v, (dict, list))))
    for n in res.get("notes", []):
        print("note:", n)
    return 1 if s["error"] else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="rlcad", description="RL CAD: AI-assisted mechanical design (spec → checked CAD)")
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--name", default="")
    ap.add_argument("--printer", default="bambu_a1_mini")
    ap.add_argument("--what", default="assembly")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--actor", default="engineer", help="who is acting: engineer (default from the command line) or ai")
    a = ap.parse_args(argv)
    if a.cmd == "tools":
        for t in TOOLS:
            print(f"{t.name:20s} {t.description[:100]}")
        return 0
    if a.cmd == "mcp":
        from .agent.mcp_server import main as mcp_main
        mcp_main()
        return 0
    if not a.args:
        ap.error("folder required")
    folder = a.args[0]
    s = Session()
    if a.cmd == "new":
        print(to_json(run_tool(s, "project_create", {"folder": folder, "name": a.name, "printer": a.printer,
                                                      "requirements": {"airframe": "F-35-style ducted quad, 3\" props",
                                                                       "fc": "RL PCB F405 (30.5 mm)",
                                                                       "battery": "3S 450–650 mAh"}})))
        return 0
    s.open(folder)
    if a.cmd == "check":
        return _print_check(run_tool(s, "build_and_check", {}))
    if a.cmd == "export":
        rc = _print_check(run_tool(s, "build_and_check", {}))
        res = run_tool(s, "export", {"force": a.force})
        print(to_json(res.get("files", res)))
        return rc if "error" not in res else 1
    if a.cmd == "render":
        print(to_json(run_tool(s, "render", {"what": a.what})))
        return 0
    if a.cmd == "fc":
        print(to_json(run_tool(s, "spec_set_fc_board", {"path": a.args[1]})))
        return 0
    if a.cmd == "set":
        params = {}
        for kv in a.args[1:]:
            k, v = kv.split("=", 1)
            params[k] = json.loads(v)
        print(to_json(run_tool(s, "spec_set_params", {"params": params}, actor=a.actor)))
        return 0
    if a.cmd == "tool":
        print(json.dumps(run_tool(s, a.args[1], json.loads(a.args[2]) if len(a.args) > 2 else {}, actor=a.actor),
                         default=str))
        return 0
    if a.cmd == "params":
        from .agent.tools import PARAM_DOCS
        from .project import airframe_params
        import dataclasses
        p = airframe_params(s.spec, base_dir=s.folder)
        print(json.dumps({"name": s.spec.name, "params": {k: {"value": v, "meaning": PARAM_DOCS.get(k, "")}
                                                            for k, v in dataclasses.asdict(p).items()
                                                            if k != "port_holes"},
                          "overrides": s.spec.airframe}, default=list))
        return 0
    if a.cmd in ("apply", "sync"):
        out = {}
        if a.cmd == "apply":
            params = json.loads(a.args[1]) if len(a.args) > 1 else {}
            if params:
                r = run_tool(s, "spec_set_params", {"params": params}, actor=a.actor)
                if "error" in r:
                    print(json.dumps({"error": r["error"]}))
                    return 1
                out["applied"] = params
        chk = run_tool(s, "build_and_check", {})
        if "error" in chk:
            print(json.dumps({"error": chk["error"]}, default=str))
            return 1
        exp = run_tool(s, "export", {"force": True})
        out.update(summary=chk["summary"], findings=chk["findings"], metrics=chk["metrics"], notes=chk.get("notes", []),
                   files={k: v for k, v in exp.get("files", {}).items() if isinstance(v, str)},
                   error=exp.get("error"))
        print(json.dumps(out, default=str))
        return 0
    if a.cmd == "integrate":
        from .integrate import run as integrate
        r = integrate(folder)
        if a.json:
            print(json.dumps(r, default=str))
        else:
            print(open(r["files"][1], encoding="utf-8").read())
        return 0 if r["ok"] else 1
    if a.cmd == "showcase":
        from .showcase import showcase
        r = showcase(folder)
        print(to_json(r))
        return 1 if "error" in r else 0
    if a.cmd == "onshape":
        print(to_json(run_tool(s, "onshape_upload", {"name": a.name})))
        return 0
    ap.error(f"unknown command {a.cmd}")


if __name__ == "__main__":
    sys.exit(main())
