"""Physical parts catalog: real envelopes, masses and mounting data for the components a small drone is built from.

Every entry records where its numbers come from. "nominal" means a typical value for the class of part; replace it
with the datasheet of the exact part you buy (``add_part`` accepts overrides). Dimensions in mm, masses in g.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


@dataclass
class Part:
    id: str
    kind: str                      # motor | prop | esc | fc | receiver | battery | hardware | vtx | camera
    name: str
    mass_g: float
    envelope_mm: tuple             # bounding box (x, y, z) in the part's own frame
    source: str
    data: Dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["envelope_mm"] = list(self.envelope_mm)
        return d


CATALOG: Dict[str, Part] = {}


def _add(p: Part):
    CATALOG[p.id] = p


# ---------------------------------------------------------------- motors
_add(Part("motor_1404_4600kv", "motor", "1404 brushless motor, ~4600 KV (3\" on 3S)", 11.0, (18.0, 18.0, 15.0),
          "nominal: 1404 class; 1404 3800KV weighs 9.66 g (BetaFPV). KV per Oscar Liang's prop/motor table "
          "(3\" tri-blade on 3S: 1303/1404/1407, 4000–5000 KV).",
          {"kv": 4600, "bell_d": 18.0, "height": 15.0, "shaft_d": 1.5, "mount_pattern_mm": 9.0,
           "mount_alt_pattern_mm": 12.0, "mount_screw": "M2", "base_d": 18.0, "max_current_a": 12}))
_add(Part("motor_1404_3800kv", "motor", "1404 brushless motor, 3800 KV (3–4S)", 9.66, (18.0, 18.0, 15.0),
          "BetaFPV 1404 3800KV product page: 9.66 g, M2 mounting, φ1.5 shaft, 3\" props, 3–4S.",
          {"kv": 3800, "bell_d": 18.0, "height": 15.0, "shaft_d": 1.5, "mount_pattern_mm": 9.0,
           "mount_alt_pattern_mm": 12.0, "mount_screw": "M2", "base_d": 18.0, "max_current_a": 10}))

_add(Part("motor_xing2_1404_4600kv", "motor", "iFlight XING2 1404 4600KV (unibell, 1.5 mm shaft)", 9.1,
          (19.9, 19.9, 18.4),
          "iFlight product page (shop.iflight.com, XING2 1404 Toothpick Ultralight, 4600KV): φ19.9 × 18.4 mm overall, "
          "9.1 g with wire, 9×9 mm φ2 mm mounting holes, 120 mm 26 AWG leads, 3–4S, peak 17.99 A / 287.8 W; iFlight "
          "EU page: body φ19.9 × 13.5 mm; GetFPV: 1.5 mm shaft, M2×7 screws supplied. base_d is an estimate.",
          {"kv": 4600, "bell_d": 19.9, "height": 13.5, "total_h": 18.4, "shaft_d": 1.5, "shaft_len": 4.9,
           "mount_pattern_mm": 9.0, "mount_alt_pattern_mm": 0.0, "mount_hole_d": 2.0, "mount_screw": "M2",
           "base_d": 15.0, "base_h": 1.5, "max_current_a": 11.8, "peak_current_a": 17.99, "cells": [3, 4],
           "lead_mm": 120, "lead_awg": 26}))

# ---------------------------------------------------------------- props (Ct, Cp: static coefficients, n in rev/s)
_add(Part("prop_3in_tri", "prop", "3\" tri-blade prop (3018–3020 class, 1.5 mm shaft)", 2.5, (76.2, 76.2, 7.0),
          "nominal: 3\" tri-blade; Ct/Cp are typical static coefficients for tri-blade FPV props (estimate).",
          {"diameter_mm": 76.2, "pitch_in": 2.0, "blades": 3, "ct": 0.13, "cp": 0.075, "hub_h": 7.0}))

_add(Part("prop_gemfan_3016_3", "prop", "Gemfan Hurricane 3016 tri-blade, 1.5 mm shaft", 1.2, (76.49, 76.49, 5.5),
          "GetFPV listing (Gemfan Hurricane 3016 Durable 3-Blade, 1.5 mm shaft): 76.49 mm, pitch 1.6\", 3 blades, "
          "1.5 mm bore, 1.18–1.20 g, 5.5 mm hub thickness, 8.84 mm max blade width, PC. Ct/Cp are estimates for a "
          "low-pitch 3\" tri-blade (no published thrust data); hub_d is an estimate.",
          {"diameter_mm": 76.49, "pitch_in": 1.6, "blades": 3, "ct": 0.12, "cp": 0.062, "hub_h": 5.5, "hub_d": 6.5,
           "bore_d": 1.5, "max_chord_mm": 8.84}))

# ---------------------------------------------------------------- electronics
_add(Part("fc_rl_f405", "fc", "RL-FC F405 flight controller (designed with RL PCB)", 7.0, (36.0, 36.0, 6.0),
          "RL PCB example examples/drone_fc: 36×36 mm 4-layer 1.6 mm, 30.5×30.5 mm M3 mounting; mass estimated from "
          "board area (FR4 1.85 g/cm³) plus components.",
          {"mount_pattern_mm": 30.5, "mount_hole_d": 3.2, "board_t": 1.6, "input": "2–6S",
           "kicad_project": "rlpcb/examples/drone_fc/output/rl_fc_f405",
           # connector the user must reach with the airframe closed: offset from board centre (x, y, z above the
           # board's bottom face), pointing direction, and the plug's cross-section (USB-C overmould ≈ 12 × 6.5 mm)
           "ports": {"usb_c": {"offset_mm": [1.5, 19.0, 3.2], "dir": [0, 1, 0], "plug_mm": [12.5, 7.0],
                               "source": "J2 (GCT USB4105) at the board's top edge in rl_fc_f405.kicad_pcb"}}}))
_add(Part("esc_4in1_30x30", "esc", "4-in-1 ESC, 30.5×30.5 mm, 2–4S, 25 A class", 9.0, (36.0, 36.0, 5.0),
          "nominal: 30.5 mm BLHeli_S/AM32 4-in-1 boards are typically 36×36 mm and 8–11 g.",
          {"mount_pattern_mm": 30.5, "mount_hole_d": 3.2, "cont_current_a": 25}))
_add(Part("esc_racerstar_shot30a", "esc", "Racerstar Shot30A 4-in-1 ESC, 30.5 mm, 3–6S, BLHeli_S", 10.0, (36.0, 36.0, 5.5),
          "Racerstar product page (Shot30A): 36×36 mm board, 30.5×30.5 mm M3 mounting, 10 g, 30 A continuous / 35 A "
          "peak, 3–6S, BLHeli_S, current and voltage sensor. Height 5.5 mm with components is an estimate.",
          {"mount_pattern_mm": 30.5, "mount_hole_d": 3.2, "cont_current_a": 30, "peak_current_a": 35, "cells": [3, 6]}))
_add(Part("rx_radiomaster_rp1", "receiver", "RadioMaster RP1 V2 ExpressLRS 2.4 GHz nano receiver", 2.2, (13.0, 11.0, 3.0),
          "RadioMaster product page (RP1 V2): 13×11×3 mm, 2.2 g with antenna, UFL with 65 mm T antenna, CRSF, 5 V.",
          {"antenna_mm": 65, "voltage": 5.0}))
_add(Part("rx_elrs_nano", "receiver", "ExpressLRS 2.4 GHz nano receiver", 1.0, (13.0, 11.0, 3.5),
          "nominal: ELRS nano receivers are ~11×13 mm, 0.5–1.5 g plus antenna.",
          {"antenna": "T or dipole, 2.4 GHz"}))

# ---------------------------------------------------------------- batteries
_add(Part("lipo_3s_650", "battery", "Tattu 3S1P 650 mAh 75C LiPo, XT30", 59.0, (58.0, 31.0, 16.0),
          "Gens Tattu product page (3S1P 75C 11.1V 650 mAh, XT30): 58 (±5) × 31 (±2) × 16 (±2) mm, 59 g, 16 AWG "
          "discharge lead 45 mm, XT30, balance JST-XHR-4P 45 mm. The fit checks use the upper tolerance.",
          {"cells": 3, "capacity_mah": 650, "v_nominal": 11.1, "c_rating": 75, "connector": "XT30",
           "envelope_max_mm": [63.0, 33.0, 18.0], "lead_mm": 45, "lead_awg": 16, "balance": "JST-XHR-4P"}))
_add(Part("lipo_3s_450", "battery", "3S 450 mAh LiPo, XT30", 40.0, (55.0, 30.0, 12.0),
          "nominal: 3S 450 mAh packs are typically 38–45 g; verify the dimensions of the pack you buy.",
          {"cells": 3, "capacity_mah": 450, "v_nominal": 11.1, "c_rating": 75, "connector": "XT30"}))

# ---------------------------------------------------------------- hardware / allowances
_add(Part("wiring_allowance", "hardware", "Wiring, XT30 pigtail, heat-shrink, straps", 10.0, (0, 0, 0),
          "allowance: typical for a 3\" build."))
_add(Part("xt30_pair", "hardware", "XT30 connector (plug + socket, mated)", 2.0, (16.0, 10.2, 5.2),
          "Amass XT30 datasheet class: housing ≈10.2 × 5.2 mm, mated length ≈16 mm; rated 15 A continuous, 30 A burst.",
          {"cont_current_a": 15, "burst_current_a": 30}))
_add(Part("usb_c_panel_ext", "hardware", "USB-C extension, 50–100 mm, right-angle plug to panel-mount socket", 3.0,
          (14.0, 10.0, 6.0), "nominal: FPV USB-C extension/pigtail boards weigh 2–4 g; socket needs a ≈9.5 × 3.5 mm opening.",
          {"socket_mm": [9.5, 3.6]}))
_add(Part("fasteners_m2_m3", "hardware", "M2/M3 screws, standoffs, grommets", 6.0, (0, 0, 0), "allowance."))

MATERIALS = {
    "PLA": {"density": 1.24, "note": "stiff, easy to print"},
    "PETG": {"density": 1.27, "note": "tougher than PLA, better for motor mounts"},
    "LW-PLA": {"density": 0.60, "note": "foaming PLA; ~0.5–0.7 g/cm³ at typical foaming settings, light shells"},
    "PETG-CF": {"density": 1.29, "note": "carbon-filled PETG: stiffer arms (E ≈ 4 GPa, supplier data varies), hardened nozzle"},
    "TPU95A": {"density": 1.21, "note": "flexible bumpers"},
}

PRINTERS = {
    "bambu_a1_mini": {"bed_mm": (180, 180, 180), "name": "Bambu Lab A1 mini"},
    "bambu_a1": {"bed_mm": (256, 256, 256), "name": "Bambu Lab A1"},
    "bambu_p1s": {"bed_mm": (256, 256, 256), "name": "Bambu Lab P1S / X1C"},
    "prusa_mk4": {"bed_mm": (250, 210, 220), "name": "Prusa MK4"},
    "ender3": {"bed_mm": (220, 220, 250), "name": "Creality Ender-3"},
}


def get(part_id: str, **overrides) -> Part:
    if part_id not in CATALOG:
        raise KeyError(f"Unknown part '{part_id}'. Available: {', '.join(sorted(CATALOG))}")
    p = CATALOG[part_id]
    if not overrides:
        return p
    d = p.to_dict()
    data = dict(d["data"])
    for k, v in overrides.items():
        if k in ("mass_g", "name", "source"):
            d[k] = v
        elif k == "envelope_mm":
            d[k] = tuple(v)
        else:
            data[k] = v
    d["data"] = data
    d["envelope_mm"] = tuple(d["envelope_mm"])
    return Part(**d)


def search(kind: Optional[str] = None, text: str = "") -> List[Dict]:
    t = text.lower()
    return [p.to_dict() for p in CATALOG.values()
            if (not kind or p.kind == kind) and (not t or t in (p.id + " " + p.name).lower())]
