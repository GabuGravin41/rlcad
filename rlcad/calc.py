"""Engineering calculators for small multirotors. Each result states its formula and assumptions.

Propeller model (static, momentum-free coefficient form):
    T = Ct · ρ · n² · D⁴          P_shaft = Cp · ρ · n³ · D⁵          (n in rev/s, D in m, ρ in kg/m³)
Loaded rpm is estimated as KV · V · k_load (k_load ≈ 0.80 for a well-matched motor/prop at full throttle).
"""
from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

RHO = 1.225          # kg/m³, sea level ISA
G = 9.80665


def prop_static(ct: float, cp: float, d_mm: float, rpm: float, rho: float = RHO) -> Dict:
    n = rpm / 60.0
    d = d_mm / 1000.0
    t = ct * rho * n ** 2 * d ** 4
    p = cp * rho * n ** 3 * d ** 5
    return {"thrust_n": t, "thrust_g": t / G * 1000, "shaft_power_w": p}


def rpm_for_thrust(ct: float, d_mm: float, thrust_g: float, rho: float = RHO) -> float:
    t = thrust_g / 1000 * G
    d = d_mm / 1000.0
    return math.sqrt(t / (ct * rho * d ** 4)) * 60


def propulsion(motor: Dict, prop: Dict, battery: Dict, n_motors: int, auw_g: float, duct_factor: float = 1.0,
               k_load: float = 0.80, eta_drive: float = 0.70, usable_fraction: float = 0.80) -> Dict:
    """Max thrust, thrust-to-weight, hover throttle/current and hover flight time."""
    v = battery["cells"] * 3.7
    v_full = battery["cells"] * 4.2
    rpm_max = motor["kv"] * v * k_load
    mx = prop_static(prop["ct"], prop["cp"], prop["diameter_mm"], rpm_max)
    t_max_g = mx["thrust_g"] * duct_factor
    t_hover_each = auw_g / n_motors
    rpm_h = rpm_for_thrust(prop["ct"], prop["diameter_mm"], t_hover_each / duct_factor)
    hov = prop_static(prop["ct"], prop["cp"], prop["diameter_mm"], rpm_h)
    p_elec_each = hov["shaft_power_w"] / eta_drive
    i_hover = p_elec_each * n_motors / v
    i_max_each = mx["shaft_power_w"] / eta_drive / v
    t_min = battery["capacity_mah"] / 1000 * usable_fraction / i_hover * 60 if i_hover else 0
    tw = t_max_g * n_motors / auw_g
    return {
        "inputs": {"kv": motor["kv"], "prop_d_mm": prop["diameter_mm"], "ct": prop["ct"], "cp": prop["cp"],
                   "cells": battery["cells"], "capacity_mah": battery["capacity_mah"], "auw_g": round(auw_g, 1),
                   "duct_factor": duct_factor, "k_load": k_load, "eta_drive": eta_drive},
        "max_rpm_est": round(rpm_max), "max_thrust_per_motor_g": round(t_max_g),
        "total_max_thrust_g": round(t_max_g * n_motors), "thrust_to_weight": round(tw, 2),
        "hover_rpm": round(rpm_h), "hover_throttle_est_pct": round(100 * rpm_h / rpm_max),
        "hover_current_a": round(i_hover, 2), "max_current_per_motor_a": round(i_max_each, 1),
        "hover_flight_time_min": round(t_min, 1),
        "battery_c_needed": round(i_max_each * n_motors / (battery["capacity_mah"] / 1000), 1),
        "method": "T = Ct·ρ·n²·D⁴, P = Cp·ρ·n³·D⁵; n_max = KV·V·k_load; P_elec = P_shaft/η; "
                  "t_hover = 0.8·C / I_hover",
        "assessment": ("good: T/W ≥ 3 is agile, ≥ 2 flies calmly" if tw >= 3 else
                       "marginal: T/W between 2 and 3 flies but has little margin for wind and mass growth" if tw >= 2
                       else "too heavy: T/W < 2 — reduce mass or use bigger props/higher KV"),
        "caveats": ["Ct/Cp are typical values; a thrust-stand table for your exact motor/prop replaces this estimate.",
                    "Ducts can add thrust with a tight tip gap and a rounded inlet lip; duct_factor 1.0 assumes no gain.",
                    f"Voltage used: {v:.1f} V nominal ({v_full:.1f} V full)."],
    }


def duct(prop_d_mm: float, tip_gap_mm: float = 1.5, wall_mm: float = 1.6, lip_r_mm: float = 4.0,
         depth_mm: float = 24.0) -> Dict:
    """Duct geometry for a prop; guidance from ducted-fan practice."""
    inner_d = prop_d_mm + 2 * tip_gap_mm
    notes = []
    if tip_gap_mm < 1.0:
        notes.append("tip gap < 1 mm: printed ducts and flexing props will rub — keep ≥ 1.2 mm")
    if tip_gap_mm > 0.02 * prop_d_mm:
        notes.append("tip gap above ~2 % of diameter: most of the duct's thrust benefit is lost (it still guards the prop)")
    if depth_mm < 0.25 * prop_d_mm:
        notes.append("shallow duct (< 25 % of D): little benefit beyond protection")
    return {"inner_d_mm": round(inner_d, 2), "outer_d_mm": round(inner_d + 2 * wall_mm, 2), "depth_mm": depth_mm,
            "inlet_lip_r_mm": lip_r_mm, "tip_gap_pct": round(100 * tip_gap_mm / prop_d_mm, 2), "notes": notes,
            "method": "inner D = prop D + 2·tip gap; inlet lip radius ≈ 5–10 % of D; depth ≥ 30 % of D for thrust gain"}


def mass_budget(items: Sequence[Tuple[str, float]]) -> Dict:
    total = sum(m for _, m in items)
    return {"items": [{"name": n, "mass_g": round(m, 1), "pct": round(100 * m / total, 1) if total else 0}
                      for n, m in sorted(items, key=lambda x: -x[1])],
            "total_g": round(total, 1)}


def centre_of_gravity(items: Sequence[Tuple[str, float, Tuple[float, float, float]]]) -> Dict:
    m = sum(x[1] for x in items)
    if not m:
        return {"cg_mm": [0, 0, 0], "total_g": 0}
    cg = [sum(x[1] * x[2][i] for x in items) / m for i in range(3)]
    return {"cg_mm": [round(c, 2) for c in cg], "total_g": round(m, 1)}


def battery_position_for_cg(items, battery_mass: float, target_x: float) -> float:
    """x position of the battery that puts the CG at target_x (items exclude the battery)."""
    m = sum(x[1] for x in items)
    mx = sum(x[1] * x[2][0] for x in items)
    return (target_x * (m + battery_mass) - mx) / battery_mass
