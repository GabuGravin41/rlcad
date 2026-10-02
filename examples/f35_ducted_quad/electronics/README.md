# Electronics: the PCB files for this drone

There is one custom PCB, the flight controller. The ESC and the receiver are bought as modules. They are
represented here only by their connectors, so the cables between the three boards can be checked.

| Board | What it is | Files |
|---|---|---|
| `rl_fc_f405/` | Flight controller designed with RL PCB: STM32F405, ICM-20602 IMU, BMP280, 128 Mbit flash, 5 V/3.3 V supplies, USB-C, 4-layer 36×36 mm, 30.5 mm mounting | KiCad project (4-sheet schematic, routed board, plan), `fab/` |
| `esc_4in1/` | 4-in-1 ESC, 30.5 mm, 25 A (bought) | interface model: its 8-pin FC connector and battery pads |
| `rx_elrs/` | ExpressLRS 2.4 GHz nano receiver (bought) | interface model: its 4 pads |
| `system.json` | the three boards, two cables (H1, H2) and the supplies | checked by RL PCB `system_check` |

## Flight controller status

- **Schematic:** 61 parts and 79 nets. It matches the design plan 100 % (174 connections). KiCad's own netlister agrees on 79 of 79 nets.
- **Board:** fully routed. KiCad DRC reports 0 errors and 0 unconnected pads, and all 239 pad nets match the plan. Some warnings remain; they are silkscreen only.
- **Design rules:** set for JLCPCB 4-layer, 1.6 mm. See `../../../rlpcb/examples/drone_fc/README.md` for how the board was finished.
- **Board STEP:** `fab/rl_fc_f405_board.step` is the bare board with pads. To get the components too, export the STEP
  in KiCad on your computer, where the 3D models are installed (see below).

### Ordering (JLCPCB)

The manufacturing files are in `rl_fc_f405/fab/`:

- `gerbers/`: 4 copper layers, masks, paste, silkscreen, outline, drill and drill map. Zip this folder and upload it.
- `jlcpcb/rl_fc_f405_BOM.csv` and `jlcpcb/rl_fc_f405_CPL.csv`: for PCB assembly. Check the part rotations in JLC's preview.

Choose 4 layers and 1.6 mm. The 0.3 mm via holes and 0.13 mm (5 mil) clearances are standard for JLCPCB 4-layer
boards.

These BOM lines have no LCSC number on purpose. Choose them when you order, or supply them yourself:

- **L1:** Bourns SRP7028A-150M, 15 µH. It was not stocked at LCSC when I checked.
- **R2:** 3.01 kΩ 1 % 0402.
- **Y1:** 8 MHz 3225 crystal with 12 pF load capacitance, which matches the 18 pF load capacitors.
  If you use a 20 pF-load crystal, change C19 and C20 to 33 pF.
- **J1 and J6:** solder pads for the battery and SWD. They are not assembled.

## Cables (system check: 0 errors, 0 warnings)

| Cable | From | To | Notes |
|---|---|---|---|
| H1 | FC J3 (8-pin JST-SH) | ESC FC connector | 1 VBAT, 2 GND, 3 CURR, 4 TLM, 5–8 M1–M4. **Check your ESC's pin order before plugging in.** If it differs, change `mapping` in `system.json` and re-run the check. |
| H2 | FC J4 (4-pin JST-SH) | RX pads | 1 → 5V, 2 → GND, 3 (FC TX) → RX, 4 (FC RX) → TX. The TX and RX wires cross over. |
| USB | FC J2 (USB-C) | socket in the fuselage's left side | Short USB-C extension. The FC's own port faces the front-left duct, and RL CAD's `connector_access` check flags that when the extension is removed. |

The check gives one note, and it is acknowledged. The FC's VBAT net is rated 3 A, which is the copper rating used to
size the tracks. The current that actually passes through the ESC cable's VBAT pin is the FC's own draw, about 0.18 A
at 3S.

## Verify on your computer (KiCad 10)

```powershell
cd "...\rlcad\examples\f35_ducted_quad\electronics\rl_fc_f405"
kicad-cli pcb drc -o drc.rpt --severity-error rl_fc_f405.kicad_pcb
kicad-cli pcb export step --subst-models -f -o fab\rl_fc_f405.step rl_fc_f405.kicad_pcb
```

Then copy `fab\rl_fc_f405.step` to `..\..\boards\rl_fc_f405.step` and run `rlcad check examples\f35_ducted_quad`.
RL CAD will then check the airframe against the real components, not just the bare board.
