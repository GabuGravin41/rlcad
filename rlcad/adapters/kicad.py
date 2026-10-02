"""KiCad → 3D: export a board (e.g. an RL PCB flight controller) to STEP with kicad-cli so its real outline,
holes and components sit in the airframe model."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from typing import Optional


def find_kicad_cli() -> Optional[str]:
    exe = shutil.which("kicad-cli")
    if exe:
        return exe
    pats = [r"C:\Program Files\KiCad\*\bin\kicad-cli.exe", "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
            "/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"]
    for pat in pats:
        hits = sorted(glob.glob(pat), reverse=True)
        if hits:
            return hits[0]
    return None


def board_to_step(kicad_pcb: str, out_step: str, include_models: bool = True) -> dict:
    """Run `kicad-cli pcb export step`. Component 3D models are included when the KiCad libraries have them."""
    cli = find_kicad_cli()
    if not cli:
        return {"error": "kicad-cli not found; install KiCad 8+ or pass a STEP file exported from KiCad instead"}
    if not os.path.exists(kicad_pcb):
        return {"error": f"{kicad_pcb} does not exist"}
    os.makedirs(os.path.dirname(os.path.abspath(out_step)), exist_ok=True)
    cmd = [cli, "pcb", "export", "step", "-f", "-o", out_step]
    if include_models:
        cmd.insert(4, "--subst-models")
    cmd.append(kicad_pcb)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    ok = r.returncode == 0 and os.path.exists(out_step)
    return {"ok": ok, "step": out_step if ok else None, "cmd": " ".join(cmd),
            "log": (r.stdout + r.stderr)[-1500:]}
