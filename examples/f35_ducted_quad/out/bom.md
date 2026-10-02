| Type | Role | Item | Qty | Mass each (g) | Source | Notes |
|---|---|---|---|---|---|---|
| make (RL PCB) | fc | RL-FC F405 flight controller (designed with RL PCB) | 1 | 7.0 | RL PCB example examples/drone_fc: 36×36 mm 4-layer 1.6 mm, 30.5×30.5 mm M3 mounting; mass estimated from board area (FR4 1.85 g/cm³) plus components. |  |
| buy | esc | Racerstar Shot30A 4-in-1 ESC, 30.5 mm, 3–6S, BLHeli_S | 1 | 10.0 | Racerstar product page (Shot30A): 36×36 mm board, 30.5×30.5 mm M3 mounting, 10 g, 30 A continuous / 35 A peak, 3–6S, BLHeli_S, current and voltage sensor. Height 5.5 mm with components is an estimate. |  |
| buy | motor | iFlight XING2 1404 4600KV (unibell, 1.5 mm shaft) | 4 | 9.1 | iFlight product page (shop.iflight.com, XING2 1404 Toothpick Ultralight, 4600KV): φ19.9 × 18.4 mm overall, 9.1 g with wire, 9×9 mm φ2 mm mounting holes, 120 mm 26 AWG leads, 3–4S, peak 17.99 A / 287.8 W; iFlight EU page: body φ19.9 × 13.5 mm; GetFPV: 1.5 mm shaft, M2×7 screws supplied. base_d is an estimate. |  |
| buy | prop | Gemfan Hurricane 3016 tri-blade, 1.5 mm shaft | 8 | 1.2 | GetFPV listing (Gemfan Hurricane 3016 Durable 3-Blade, 1.5 mm shaft): 76.49 mm, pitch 1.6", 3 blades, 1.5 mm bore, 1.18–1.20 g, 5.5 mm hub thickness, 8.84 mm max blade width, PC. Ct/Cp are estimates for a low-pitch 3" tri-blade (no published thrust data); hub_d is an estimate. | 4 + 4 spares, 2 CW + 2 CCW |
| buy | receiver | RadioMaster RP1 V2 ExpressLRS 2.4 GHz nano receiver | 1 | 2.2 | RadioMaster product page (RP1 V2): 13×11×3 mm, 2.2 g with antenna, UFL with 65 mm T antenna, CRSF, 5 V. |  |
| buy | battery | Tattu 3S1P 650 mAh 75C LiPo, XT30 | 1 | 59.0 | Gens Tattu product page (3S1P 75C 11.1V 650 mAh, XT30): 58 (±5) × 31 (±2) × 16 (±2) mm, 59 g, 16 AWG discharge lead 45 mm, XT30, balance JST-XHR-4P 45 mm. The fit checks use the upper tolerance. |  |
| buy | fasteners | M2×6 self-tapping (skin, pods) ×12; M2×5 motor screws ×16; M3×20 stack standoffs/screws ×4; M3 silicone grommets ×4 | 1 | 6.0 |  |  |
| buy | usb extension | USB-C extension, 50–100 mm, right-angle plug to panel-mount socket | 1 | 3.0 | nominal: FPV USB-C extension/pigtail boards weigh 2–4 g; socket needs a ≈9.5 × 3.5 mm opening. | FC J2 → socket in the left side of the centre shell (x = 0.0 mm); glue the socket in its opening |
| buy | battery strap | 12 mm Velcro strap, 200 mm ×2 | 2 | 1.0 |  | through the frame strap slots |
| print | structure: carries motors, stack, battery | frame | 1 | 29.3 | out/print/frame.stl | PETG, as modelled, 154.3×130.0×10.5 mm |
| print | duct (prop guard) + wing/tail | pod_front_left | 1 | 14.9 | out/print/pod_front_left.stl | LW-PLA, as modelled, 127.5×91.5×26.0 mm |
| print | duct (prop guard) + wing/tail | pod_front_right | 1 | 14.9 | out/print/pod_front_right.stl | LW-PLA, as modelled, 127.5×91.5×26.0 mm |
| print | duct (prop guard) + wing/tail | pod_rear_left | 1 | 13.7 | out/print/pod_rear_left.stl | LW-PLA, as modelled, 103.5×90.7×26.0 mm |
| print | duct (prop guard) + wing/tail | pod_rear_right | 1 | 13.7 | out/print/pod_rear_right.stl | LW-PLA, as modelled, 103.5×90.7×26.0 mm |
| print | skin / electronics cover | fuselage_nose (+ canopy) | 1 | 13.9 | out/print/fuselage_nose.stl | LW-PLA, standing on its aft face (-x down), 50.0×48.5×112.5 mm |
| print | skin / electronics cover | fuselage_centre | 1 | 10.3 | out/print/fuselage_centre.stl | LW-PLA, standing on its aft face (-x down), 46.7×41.6×142.0 mm |
| print | skin / electronics cover | fuselage_tail | 1 | 4.2 | out/print/fuselage_tail.stl | LW-PLA, standing on its forward face (+x down), 46.7×45.1×53.6 mm |
| print | cosmetic | fin_left | 1 | 1.0 | out/print/fin_left.stl | LW-PLA, lying on its flat side, 50.0×31.5×2.4 mm |
| print | cosmetic | fin_right | 1 | 1.0 | out/print/fin_right.stl | LW-PLA, lying on its flat side, 50.0×31.5×2.4 mm |
