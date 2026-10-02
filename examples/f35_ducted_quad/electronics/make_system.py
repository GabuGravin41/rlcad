"""Build the drone's electronics system for RL PCB's multi-board checks.

Boards
  fc       rl_fc_f405/      the flight controller designed with RL PCB (full KiCad project)
  esc      esc_4in1/        interface model of the bought 4-in-1 ESC: only its FC connector and power pads
  rx       rx_elrs/         interface model of the bought ELRS receiver: its 4 solder pads
Harnesses
  H1  fc.J3 (8-pin JST-SH) ↔ esc.J1   the cable that ships with the ESC — CHECK ITS PIN ORDER against your ESC
  H2  fc.J4 (4-pin JST-SH) ↔ rx.J1    4 wires soldered to the receiver pads; TX/RX cross over in the cable
Supplies
  esc VBAT (battery through the ESC), fc +5V (TPS5430 buck, 2 A budget), fc +3V3 (AP2112K, 0.6 A)

Run with RL PCB installed:  python make_system.py   then   rlpcb system_check (or the system_check tool).
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RLPCB = os.environ.get("RLPCB_REPO", os.path.join(HERE, "..", "..", "..", "..", "rlpcb"))
sys.path.insert(0, os.path.abspath(RLPCB))
from rlpcb.agent.tools import Session, run_tool  # noqa: E402


def ok(r):
    if isinstance(r, dict) and "error" in r:
        raise SystemExit(f"RL PCB error: {r['error']}")
    return r


def interface_board(s, name, title, comps, nets, info):
    folder = os.path.join(HERE)
    if os.path.isdir(os.path.join(folder, name)):
        shutil.rmtree(os.path.join(folder, name))
    ok(run_tool(s, "create_project", {"folder": folder, "name": name, "title": title}))
    ok(run_tool(s, "plan_set_info", {"name": name, "description": title, "requirements": info}))
    ok(run_tool(s, "plan_add_components", {"components": comps}))
    for n in nets:
        ok(run_tool(s, "plan_connect", n))


def main():
    s = Session()
    # ------------------------------------------------------------------ the flight controller (copy of the RL PCB example)
    src = os.path.join(RLPCB, "examples", "drone_fc", "output", "rl_fc_f405")
    dst = os.path.join(HERE, "rl_fc_f405")
    if os.path.abspath(src) != os.path.abspath(dst) and os.path.isdir(src):
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns("*.dsn", "*.ses", "*-backups", "fp-info-cache", "*.kicad_prl", "backups"))

    # ------------------------------------------------------------------ 4-in-1 ESC (bought): interface only
    interface_board(
        s, "esc_4in1", "4-in-1 ESC 30.5 mm, 25 A (bought) - interface model",
        [{"ref": "J1", "lib_id": "Connector_Generic:Conn_01x08", "value": "FC 8-pin JST-SH",
          "footprint": "Connector_JST:JST_SH_SM08B-SRSS-TB_1x08-1MP_P1.00mm_Horizontal",
          "role": "harness to the FC; pin order as printed on the ESC"},
         {"ref": "J2", "lib_id": "Connector_Generic:Conn_01x02", "value": "BAT pads (XT30 pigtail)",
          "footprint": "Connector_Wire:SolderWire-1.5sqmm_1x02_P6mm_D1.7mm_OD3mm", "role": "battery lead"}],
        [{"net": "VBAT", "pins": ["J1.1", "J2.1"], "net_class": "power", "voltage_v": 12.6, "current_a": 1.0,
          "notes": "battery voltage passed to the FC (FC draws < 1 A)"},
         {"net": "GND", "pins": ["J1.2", "J2.2"], "net_class": "ground"},
         {"net": "ESC_CURR", "pins": ["J1.3"], "net_class": "analog", "voltage_v": 3.3,
          "notes": "current-sensor output, 0-3.3 V"},
         {"net": "ESC_TLM", "pins": ["J1.4"], "net_class": "signal", "voltage_v": 3.3,
          "notes": "ESC telemetry TX (to an FC UART RX)"},
         {"net": "M1", "pins": ["J1.5"], "voltage_v": 3.3}, {"net": "M2", "pins": ["J1.6"], "voltage_v": 3.3},
         {"net": "M3", "pins": ["J1.7"], "voltage_v": 3.3}, {"net": "M4", "pins": ["J1.8"], "voltage_v": 3.3}],
        {"input": "3S LiPo via XT30", "fc_connector": "8-pin JST-SH: VBAT, GND, CURR, TLM, M1, M2, M3, M4 (verify!)"})

    # ------------------------------------------------------------------ ELRS receiver (bought): interface only
    interface_board(
        s, "rx_elrs", "ExpressLRS 2.4 GHz nano receiver (bought) - interface model",
        [{"ref": "J1", "lib_id": "Connector_Generic:Conn_01x04", "value": "RX pads 5V/GND/TX/RX",
          "footprint": "Connector_PinHeader_1.27mm:PinHeader_1x04_P1.27mm_Vertical", "role": "solder pads"}],
        [{"net": "+5V", "pins": ["J1.1"], "net_class": "power", "voltage_v": 5.0, "current_a": 0.1,
          "notes": "ELRS nano: ~50-100 mA"},
         {"net": "GND", "pins": ["J1.2"], "net_class": "ground"},
         {"net": "RX_TX", "pins": ["J1.3"], "voltage_v": 3.3, "notes": "receiver TX (CRSF out)"},
         {"net": "RX_RX", "pins": ["J1.4"], "voltage_v": 3.3, "notes": "receiver RX (telemetry in)"}],
        {"protocol": "CRSF 420 kbaud on FC UART1"})

    # ------------------------------------------------------------------ system
    ok(run_tool(s, "system_create", {"folder": HERE, "name": "F-35 ducted quad electronics"}))
    ok(run_tool(s, "system_add_board", {"folder": HERE, "name": "fc", "project": "rl_fc_f405"}))
    ok(run_tool(s, "system_add_board", {"folder": HERE, "name": "esc", "project": "esc_4in1"}))
    ok(run_tool(s, "system_add_board", {"folder": HERE, "name": "rx", "project": "rx_elrs"}))
    ok(run_tool(s, "system_add_harness", {"folder": HERE, "id": "H1", "a_board": "fc", "a_ref": "J3",
                                          "b_board": "esc", "b_ref": "J1", "mapping": "straight",
                                          "pin_current_a": 1.0, "cable": "8-pin JST-SH 1.0 mm, 60-80 mm (ships with ESC)"}))
    ok(run_tool(s, "system_add_harness", {"folder": HERE, "id": "H2", "a_board": "fc", "a_ref": "J4",
                                          "b_board": "rx", "b_ref": "J1",
                                          "mapping": {"1": "1", "2": "2", "3": "4", "4": "3"},
                                          "pin_current_a": 1.0, "cable": "4-pin JST-SH pigtail, soldered to RX pads; TX↔RX crossed"}))
    ok(run_tool(s, "system_add_supply", {"folder": HERE, "board": "esc", "net": "VBAT", "capacity_a": 100.0}))
    ok(run_tool(s, "system_add_supply", {"folder": HERE, "board": "fc", "net": "+5V", "capacity_a": 2.0,
                                         "local_load_a": 0.25}))   # FC itself: 3.3 V LDO input (MCU, IMU, flash, baro), LEDs
    ok(run_tool(s, "system_add_supply", {"folder": HERE, "board": "fc", "net": "+3V3", "capacity_a": 0.6,
                                         "local_load_a": 0.2}))
    # the FC's VBAT net is annotated 3 A (its copper rating, used for track widths). What actually flows through
    # the ESC cable's VBAT pin on this drone is the FC's own draw: 5 V rail ≈0.35 A (FC 0.25 A + RX 0.1 A) →
    # 5 V × 0.35 A / 0.9 / 11.1 V ≈ 0.18 A at 3S, well inside the 1 A JST-SH pin rating.
    import json as _json
    from rlpcb.design import system as _system
    d = _system.load(HERE)
    d["acknowledged"] = [{"rule": "pin_current", "where": "H1", "match": "VBAT",
                          "reason": "3 A is the FC's VBAT copper rating; the real draw on this drone is ≈0.18 A at 3S"}]
    _system.save(HERE, d)
    r = run_tool(s, "system_check", {"folder": HERE})
    import json
    print(json.dumps({k: r[k] for k in r if k != "pins"}, indent=1, default=str))
    with open(os.path.join(HERE, "system_check.json"), "w", encoding="utf-8") as f:
        json.dump(r, f, indent=1, default=str)


if __name__ == "__main__":
    main()
