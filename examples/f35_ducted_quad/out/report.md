# f35_ducted_quad: design report

Kind: ducted_quad_f35. Printer: Bambu Lab A1 mini (180×180×180 mm).

## Checks

0 errors, 2 warnings, 11 notes.

- **warning** (arm_stiffness): arm first bending mode ≈142 Hz is low; gyro noise filtering will have to work hard. Options: print the frame in PETG-CF/PA-CF, or cut it from 3 mm carbon plate (frame.dxf; ≈221 Hz)
- **warning** (power_connector): full throttle ≈32 A is above the XT30's 30 A burst rating
- **info** (interference): fuselage_tail and fin_left share 4.5 mm³ (glued joint)
- **info** (interference): fuselage_tail and fin_right share 4.6 mm³ (glued joint)
- **info** (connector_access): fc.usb_c (J2) (extension socket) reachable through the left side of the fuselage (12.5×7.0 mm plug path clear)
- **info** (board_mount): fc: 4 holes on the 30.5 mm stack pattern (Ø3.2 mm)
- **info** (board_height): fc: parts 2.5 mm below / 3.31 mm above the board; space is 3.7 mm to the ESC and 15.38 mm to the roof
- **info** (prop_fit): prop bore 1.5 mm = motor shaft 1.5 mm; hub (5.5 mm) sits on the bell at z 16.0 mm, prop plane z 18.75 mm
- **info** (motor_leads): motor leads 120 mm ≥ ≈104 mm to the ESC pads (trim to length)
- **info** (battery_fit): Tattu 3S1P 650 mAh 75C LiPo, XT30: fits at its nominal size and at the upper tolerance (63.0×33.0×18.0 mm)
- **info** (power_esc): ESC 30 A per motor ≥ estimated 8.1 A at full throttle and the motor's 11.8 A rating (peak 17.99 A)
- **info** (power_battery): full throttle ≈32 A ≤ 49 A (650 mAh × 75C)
- **info** (print_audit): all 10 printed parts: closed meshes, walls ≥ 2 lines except small areas, no overhang that needs support, flat on the bed

## Flight performance (estimate)

- All-up weight: 255.6 g
- Max thrust: 951 g (238 g per motor); thrust-to-weight 3.72
- Hover: ≈52 % throttle, 4.5 A, ≈6.9 min
- Max current per motor ≈8.1 A; battery needs ≈49.7 C
- Method: T = Ct·ρ·n²·D⁴, P = Cp·ρ·n³·D⁵; n_max = KV·V·k_load; P_elec = P_shaft/η; t_hover = 0.8·C / I_hover

Assumptions: Ct/Cp are typical values; a thrust-stand table for your exact motor/prop replaces this estimate. Ducts can add thrust with a tight tip gap and a rounded inlet lip; duct_factor 1.0 assumes no gain. Voltage used: 11.1 V nominal (12.6 V full).

## Mass and balance

| Group | g | % |
|---|---|---|
| battery | 59.0 | 23.1 |
| pod | 57.1 | 22.4 |
| motor | 36.4 | 14.2 |
| frame | 29.3 | 11.5 |
| fuselage | 27.3 | 10.7 |
| esc | 10.0 | 3.9 |
| wiring_allowance | 10.0 | 3.9 |
| fc | 7.3 | 2.9 |
| fasteners_m2_m | 6.0 | 2.3 |
| prop | 4.8 | 1.9 |
| usb_c_panel_ext | 3.0 | 1.2 |
| receiver | 2.2 | 0.9 |
| fin | 1.9 | 0.8 |
| canopy | 1.2 | 0.5 |

CG at x 0.0, y 0.21, z 13.78 mm (thrust centre is x 0, y 0).

## Frame arms

PETG, cantilever length 58.8 mm: tip deflection 0.28 mm at full thrust, stress 3.1 MPa (safety factor 14.7), first mode ≈142 Hz. A 3 mm carbon plate cut from frame.dxf: 0.12 mm, ≈221 Hz.

## Printing

Every STL in print/ is already in its print orientation: load it and slice without rotating it.

| Part | Material | g | Orientation | Size on bed (mm) | Supports | Brim |
|---|---|---|---|---|---|---|
| frame | PETG | 29.3 | as modelled | 154.3×130.0×10.5 | none | no |
| pod_front_left | LW-PLA | 14.9 | as modelled | 127.5×91.5×26.0 | none | no |
| pod_front_right | LW-PLA | 14.9 | as modelled | 127.5×91.5×26.0 | none | no |
| pod_rear_left | LW-PLA | 13.7 | as modelled | 103.5×90.7×26.0 | none | no |
| pod_rear_right | LW-PLA | 13.7 | as modelled | 103.5×90.7×26.0 | none | no |
| fuselage_nose + canopy | LW-PLA | 13.9 | standing on its aft face (-x down) | 50.0×48.5×112.5 | none | yes |
| fuselage_centre | LW-PLA | 10.3 | standing on its aft face (-x down) | 46.7×41.6×142.0 | none | yes |
| fuselage_tail | LW-PLA | 4.2 | standing on its forward face (+x down) | 46.7×45.1×53.6 | none | yes |
| fin_left | LW-PLA | 1.0 | lying on its flat side | 50.0×31.5×2.4 | none | no |
| fin_right | LW-PLA | 1.0 | lying on its flat side | 50.0×31.5×2.4 | none | no |

Filament (parts only, no supports/waste): PETG 29 g, LW-PLA 86 g

How the parts are made to print without support (the print_audit check verifies it on these STLs):

- Duct pods stand on the duct exit, which ends in a flat land, and the wing or tail panel has a flat underside in the same plane, so the whole pod starts on the bed. The panels' airfoil sections have blunt leading and trailing edges (0.8 mm and 0.9 mm), two lines wide.
- Fins are plano-convex and print lying on their flat side, with the tab.
- The fuselage pieces stand on their cut faces. Their walls are then vertical; the nose cavity closes in a steep dome under a solid tip; the tail converges onto the nozzle, so its end wall is a short bridge (about 16 mm). The two front screw bosses in the centre shell sit on 45° gussets.
- The canopy is printed as part of the nose (a hollow shell open to the nose cavity). For a second colour, use a filament change or the AMS at the canopy's height, or paint it.

Settings: frame in PETG (or PETG-CF), 4 walls, 40 % gyroid. Skin parts in LW-PLA (foaming) with 2 walls, or regular PLA with 2 walls (heavier: about twice the skin mass). Layer height 0.2 mm. Use a brim where the table says so: the tall shells stand on a narrow edge.

## Assembly order

1. Press the M3 grommets into the frame stack holes; mount motors (M2×5, check screws do not touch windings).
2. Solder motors to the 4-in-1 ESC, mount ESC then FC on the stack (arrow forward), receiver ahead of the stack.
3. Strap the battery through the slots; check the CG sits on the frame centre mark (x 0).
4. Screw the four duct pods onto the arm posts (M2 from below). Spin each motor by hand: nothing may touch.
5. Slide nose and tail onto the centre shell collars (glue), fit the fins into the tail slots (glue).
6. Plug the USB-C extension into the FC and glue its socket into the opening in the centre shell's left side.
7. Place the centre shell over the frame (the arms pass through the windows in its sides) and screw it down (4× M2 from below into the bosses).

## Notes

- FC geometry from rl_fc_f405_board.step (36.0×36.0×1.6 mm)
- USB-C brought out to the left side of the fuselage at x = 0.0 mm with a short extension: the FC's own port faces the front-left duct

## Files

- assembly.step: whole aircraft (named parts) — import into Onshape/FreeCAD/Fusion
- parts/*.step: each printed part for editing
- print/*.stl: laid out for the slicer
- frame.dxf: frame outline for a carbon plate
- bom.csv / bom.md, design.json, render.png
