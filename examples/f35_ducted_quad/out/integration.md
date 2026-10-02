# f35_ducted_quad: PCB ↔ CAD integration

Result: OK

## Airframe side (RL CAD)

- **info** connector_access: fc.usb_c (J2) (extension socket) reachable through the left side of the fuselage (12.5×7.0 mm plug path clear)
- **info** board_mount: fc: 4 holes on the 30.5 mm stack pattern (Ø3.2 mm)
- **info** board_height: fc: parts 2.5 mm below / 3.31 mm above the board; space is 3.7 mm to the ESC and 15.38 mm to the roof

## Board slot `fc`

- KiCad project: `electronics/rl_fc_f405`
- Board: 36.0×36.0 mm, parts 2.5 mm below / 3.31 mm above
- Space the airframe gives it: 46.8×43.0 mm, 3.7 mm below / 15.38 mm above, 30.5 mm mounting pattern
- Edges that can reach outside: none
- Envelope written to `electronics/rl_fc_f405/enclosure.json` (RL PCB `mech_check` reads it)

| Connector | Mate | Faces | Populated |
|---|---|---|---|
| J6 | header-04 | +x | no |
| J1 | wire-pads | -y | no |
| J5 | jst-sh-04 | +x | yes |
| J3 | jst-sh-08 | -y | yes |
| J2 | usb-c | +y | yes |
| J4 | jst-sh-04 | -x | yes |

PCB side (RL PCB `mech_check`):

- **info** mech_height: top side: tallest part 3.31 mm ≤ 15.38 mm allowed
- **info** mech_height: bottom side: tallest part 2.5 mm ≤ 3.7 mm allowed
- **info** mech_port: J2 (usb-c) is brought out by an extension cable: flight-controller configuration from outside the airframe

## Cables between boards (RL PCB `system_check`)

- summary: {'info': 1}
- **info** pin_current: H1 pin 1↔1 (fc.J3.1 ↔ esc.J1.1): VBAT carries ≈3.00 A per pin; connector rated 1 A per pin — use more pins or a bigger connector
