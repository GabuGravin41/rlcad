# RL CAD architecture

## Aim

RL PCB and RL CAD test one idea. A language model can do real engineering design if three conditions hold:

- it works on a structured specification rather than on raw geometry or wires;
- a deterministic engine turns that specification into the design;
- engineering checks tell it, in plain terms, what is wrong.

The model decides and the engine executes. The checks are the ground truth. The engineer can read, edit and override
every step.

| | RL PCB | RL CAD |
|---|---|---|
| Host tool | KiCad (schematic + PCB) | Any STEP-capable CAD; FreeCAD workbench with a live bridge; Onshape API |
| Specification | design plan (components, nets, blocks) | `rlcad.json` (requirements, parts, parameters, printer, decisions) |
| Engine | KiCad file writer + connectivity engine | build123d / OpenCascade parametric geometry |
| Pre-verified units | circuit blocks (buck, LDO, MCU core, IMU…) | parts catalog + parametric airframe modules |
| Checks | ~20 plan rules, ERC/DRC, board checks | bed fit, clearance, interference, mass/CG, propulsion, structure, solid integrity, print audit of the STLs |
| Output | KiCad project, Gerbers, JLCPCB files | STEP, STL, DXF, BOM, report |
| Interface | MCP / CLI / web | MCP / CLI / FreeCAD workbench |
| Meeting point | `<board>.mech.json` (what the board is) | `enclosure.json` (what space the product gives it) |

The two tools meet at the flight controller. RL PCB designs the board. `kicad-cli pcb export step` turns it into a
STEP file. RL CAD places that board in the airframe and checks it against everything around it.

## Modules

```
rlcad/
  catalog.py        parts with mass, envelope, mounting data and a stated source; materials; printers
  calc.py           propulsion (Ct/Cp prop model), duct sizing, mass budget, CG, battery placement
  project.py        Spec (rlcad.json) → Model (airframe parts + placed components with masses and CGs)
  geom/airframe.py  parametric F-35-style ducted quad: frame, duct pods, fuselage (3 parts), canopy, fins
  geom/mesh.py      face-by-face tessellation (used by checks, renders, bed fit)
  geom/components.py  bought parts modelled from their datasheets (motor, prop, ESC, receiver, battery + XT30)
  checks.py         all engineering checks → findings (error/warning/info, parts involved) + metrics
  printcheck.py     print audit of each part as it will be sliced: closed mesh, wall thickness (ray casting),
                    knife edges, overhangs needing support (bridges and short ledges excepted), bed contact
  export.py         STEP assembly/parts, print-oriented STL, DXF, BOM, design.json, report.md
  render.py         quick multi-view PNG previews (headless matplotlib, for the model and the checks loop)
  showcase.py       presentation renders through FreeCAD (smooth shading, hero/inside/orthographic views)
  agent/tools.py    tool registry (project, spec, build_and_check, try_fix, parts_compatible, design_checklist,
                    render, showcase, export, onshape_upload, next_step)
  agent/fixes.py    fix playbook: for every check rule, ready tool calls that usually resolve it
  agent/prompt.py   system prompt
  agent/mcp_server.py  MCP stdio server
  adapters/kicad.py    kicad-cli board → STEP
  adapters/onshape.py  Onshape REST: create document, upload + translate STEP
  adapters/freecad/RLCAD/         FreeCAD workbench: parameter sheet, Sync, checks, local XML-RPC bridge
  adapters/freecad_client.py      bridge client used by the freecad_* agent tools
  mech.py, integrate.py           PCB <-> CAD: read mech.json, write enclosure.json, run both sides' checks
  cli.py            command line
  families/enclosure.py  parametric enclosure around any board (base, standoffs, lid, openings from mech.json)
  geom/features.py  engineer/AI-added features (hole, boss, pad, pocket, rib) kept in the spec
  dfm.py            manufacturability review: FDM, injection molding (draft, undercuts, wall uniformity)
  kickoff.py        idea → questions, process, pitfalls, design folder; RULES for explain
  interface.py      interface_log.json change notices between PCB and CAD (same file in RL PCB)
  agent/copilot.py  modes, proposals, journal, undo (same file in RL PCB)
  agent/copilot_cad.py  scopes per tool/parameter, spec diff, check deltas, "not verified" list; gate()
  adapters/freecad/rlcad_freecad/commands.py  workbench commands (Open, Sync, Mode, Proposals, Undo, Review)
```

## Design loop

1. `project_create` records the requirements.
2. `catalog_search`, `calc_propulsion` and `spec_set_part` choose the parts. Each catalog number states its source.
3. `build_and_check` builds the geometry and returns the findings and metrics.
4. For each error, change one parameter or part and rebuild. Warnings are either fixed or acknowledged with
   `decision_add("ACK <rule>: <reason>")`.
5. `export` refuses while errors remain. `onshape_upload` is optional.

## Scaffolding for smaller models

RL CAD is meant to work with models less capable than the one that built it. The design knowledge therefore sits in
the tools, not in the model:

- `next_step` reads the project state and returns the next action as a ready call (`{"tool": ..., "args": ...}`).
- Every error and open warning from `build_and_check` carries `fixes`: concrete tool calls from a playbook
  (`agent/fixes.py`), most likely first. Examples:
  - a thin wall suggests raising `skin_t`;
  - a prop that does not fit the motor lists catalog props with the right bore;
  - an arm that is too flexible suggests a taller rib, PETG-CF, or an acknowledged warning.
- `try_fix(finding, fix)` applies one fix, rebuilds, and keeps the change only if the design got better. Otherwise
  it reverts the change and says so. The model can repair a design by trying fixes in order, without judging the
  geometry itself.
- `parts_compatible(role)` checks every catalog part against what is already chosen: the shaft against the prop
  bore, cell counts, and ESC current against the motor.
- `design_checklist` shows the whole process, from requirements to export, with the state of each stage.
- The system prompt gives the procedure as numbered steps.

The geometry is rebuilt from the spec every time, so the spec is the single source of truth. Check results are saved
in `out/checks.json` and linked to the spec's timestamp. A restarted session therefore knows whether they still apply.

## Geometry notes

- The frame of reference is X forward, Y left, Z up, in millimetres. The origin is at the thrust centre, on the
  bottom of the frame plate.
- The fuselage is a loft of cross-sections, each bounded by two splines through 12 control points that meet at a
  sharp chine. The section height follows a power law of its width, so the nose closes to a point (a small cap loft
  finishes the tip). The inner skin is a loft of the same sections, offset inward in their own planes.
- `half_width_at`, `roof_z_at` and `spine_z` sample those splines. The checks, the board envelope and the port
  positions all use them, so a change to the body shape moves every clearance with it.
- Stations: the design stations are joined by smooth, overshoot-free (PCHIP) curves for width and keel height, and
  the loft uses a station every ~9 mm along them. With only the design stations the loft sagged up to 0.6 mm between
  them.
- The ducts are revolved nacelle profiles. Wings, tailplanes and fins are ruled lofts of symmetric airfoil sections
  whose thickness tapers to the tip; the panel edges are tangent to the duct circles. An earlier version used a 3D offset of the solid, but some of its surfaces could not be
  triangulated, so the STL would have had holes. The `solid` check now catches that failure.
- Parts are split at the frame plate ends so that each fits a 180 mm bed. Slip-fit collars, 0.2 mm clearance, join
  the fuselage sections.
- The duct pods screw onto posts on the arms. The fuselage centre shell sits over the frame, and the arms pass
  through slots in its walls.

## Adding a new design family

A new family needs:

- a geometry module that returns named parts;
- a `build_model` branch that places the components;
- family-specific checks, if any.

The catalog, calculators, general checks, exports, tools and integrations are shared.

See `INTEGRATION.md` for the PCB ↔ CAD contract.
