# Where the PCB meets the CAD

RL PCB designs boards in KiCad. RL CAD designs the product around them. The two tools exchange two small JSON files.
Either tool can be used without the other; the files are the contract between them.

```
KiCad board ──RL PCB mech_export──▶ <board>.mech.json ──▶ RL CAD places the board and runs its checks
     ▲                                                              │
     └──── RL PCB mech_check ◀── enclosure.json ◀──────────────────┘
```

Both files sit in the board's KiCad project folder.

## `<board>.mech.json`: what the board is (schema `rl-mech/1`, written by RL PCB)

This file describes the board:

- outline and thickness;
- mounting holes;
- the height of the tallest part on each side, and the height of every part;
- estimated mass;
- every connector: its position, mate type (`usb-c`, `jst-sh-8`, `wire-pads`, …), which board edge it faces, how
  far it overhangs, and whether it is populated.

Part heights come from a table of footprint classes. Any footprint the table does not recognise is marked
`height_source: "est"`. A STEP file exported by KiCad with 3D models gives the exact shape; RL CAD uses it for the
3D model when it exists.

Frame:

- millimetres;
- origin at the centre of the board outline;
- +x is KiCad +x, and +y is KiCad −y, so the frame matches KiCad's STEP export;
- z = 0 on the bottom face of the board.

Edges are named `+x`, `-x`, `+y` and `-y`. `+y` is the edge at the top of the KiCad screen.

## `enclosure.json`: the space the product gives the board (schema `rl-envelope/1`, written by RL CAD)

This file gives:

- the largest outline that fits;
- the mounting pattern and hole size;
- the height allowed above and below the board, for example the gap to the ESC and to the fuselage roof;
- which board edges have a clear path to the outside;
- which connectors must be reachable, and whether the airframe brings them out with an extension cable.

RL CAD works these numbers out from the real geometry: the shell cross-section at the board's height, its
neighbours in the stack, the ducts and the solid nose and tail.

## Linking a board to a design

In `rlcad.json`:

```json
"boards": {"fc": {"project": "electronics/rl_fc_f405", "rotation": 0}}
```

The agent tool `spec_set_board` sets this. Use `rotation` to turn the board about Z so that a connector points
somewhere reachable. RL CAD then does the following:

- If RL PCB is installed and the `.kicad_pcb` is newer than `mech.json`, it regenerates `mech.json`.
- It places the board on the stack axis, with its bottom face at the stack height.
- For the 3D model, it uses the best STEP available: the KiCad export with models, otherwise the bare board.
- It takes the connectors that must be reachable from the board itself. There are no hand-entered offsets.

It then runs these checks:

| Check | Error when |
|---|---|
| `board_mount` | the board's mounting holes are not on the stack pattern |
| `board_height` | parts under the board reach the ESC, or parts on top hit the fuselage roof |
| `board_fit` | the board is wider than the shell at its height, or longer than the gap between its neighbours |
| `board_ports` / `connector_access` | a connector that must be reachable (USB-C) has no clear path to the outside and no extension |

## One command

```
rlcad integrate examples/f35_ducted_quad
```

This runs both sides and writes `out/integration.md` and `out/integration.json`:

1. It refreshes `mech.json` from KiCad.
2. It places the board and runs the airframe checks.
3. It writes `enclosure.json`.
4. It runs RL PCB's `mech_check` against that file.
5. It runs RL PCB's `system_check` on the cables in `electronics/system.json`.

The same check is available as the `integration_check` agent tool and as **RL CAD > PCB ↔ CAD check** in FreeCAD.

Running this on the example found a real problem. The flight controller's USB-C (J2) faces the `+y` edge, and at
the stack position no board edge has a clear path out: the ducts sit on both sides, the nose is ahead and the battery
is behind. So the airframe brings the port out with a short extension to a socket in the fuselage side. If you remove
the extension (`usb_port: []`), both tools report an error:

- RL CAD reports `connector_access` and `board_ports`.
- RL PCB reports `mech_port`.

## Change notices: `interface_log.json`

The board's KiCad project also holds `interface_log.json` (schema `rl-interface-log/1`). The rules are:

- Each time RL PCB writes `mech.json` with differences, it records them: connectors moved, rotated, added or
  removed, outline, holes, and the tallest parts on each side.
- Each time RL CAD writes `enclosure.json` with differences, it records them: the outline allowed, heights, the
  mounting pattern and the reachable connectors.
- Each entry names the side that made it, the changes, and the checks they affect.
- `rlcad integrate` shows the electronics side's unseen notices and marks them seen with the result of its checks.
- RL PCB's `mech_check` shows the mechanical side's unseen notices. `interface_changes(mark_seen=true)` records
  that they were reviewed.

This replaces "did anyone tell mechanical that the USB moved?" with a record both teams can read. RL PCB's
`interface_changes` tool lists it.

A board can be used in more than one product. For example, the drone's flight controller also has its own box in
`examples/fc_enclosure`. The first product to write `enclosure.json` keeps that file, and each other product writes
`enclosure.<product>.json`, so no design overwrites another's envelope. RL PCB's `mech_check` checks the board
against every envelope file and reports the findings per product.

`enclosure.json` may also give `mount_holes_mm`: explicit standoff positions in board coordinates. The enclosure
family uses this; RL PCB's `mech_check` then compares each hole to its standoff instead of to a square pattern.

## FreeCAD

The RL CAD workbench (`rlcad/adapters/freecad/RLCAD`, which `install_windows.ps1` installs) shows a design as
three things:

- a parameter sheet, `RLCAD_Params`;
- the check results, in `RLCAD_Checks` and `RLCAD_Integration`;
- the imported model, with named, coloured parts.

It saves all of this as `out/<name>.FCStd`. Edit column B of the parameter sheet and press **Sync**. RL CAD then
applies the edit, rebuilds, runs the checks, exports, and reloads the model.

When FreeCAD starts, the workbench also opens a local bridge on 127.0.0.1:49717. RL CAD's agent tools use it to
drive the same FreeCAD window, the way RL PCB drives KiCad through KiCad's API. The tools are:

- `freecad_open`
- `freecad_read_params`
- `freecad_sync`
- `freecad_view`
