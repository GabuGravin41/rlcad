"""Client for the RL CAD bridge running inside FreeCAD (see adapters/freecad/RLCAD)."""
from __future__ import annotations

import json
import os
import socket
import xmlrpc.client

CONFIG = os.path.join(os.path.expanduser("~"), ".rlcad", "config.json")


def port() -> int:
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return int(json.load(f).get("bridge_port", 49717))
    except (OSError, ValueError):
        return 49717


def proxy(timeout: float = 1500):
    class _T(xmlrpc.client.Transport):
        def make_connection(self, host):
            c = super().make_connection(host)
            c.timeout = timeout
            return c
    return xmlrpc.client.ServerProxy(f"http://127.0.0.1:{port()}", allow_none=True, transport=_T())


def available() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port()), timeout=1.0):
            return True
    except OSError:
        return False


def call(method: str, *args):
    if not available():
        raise ConnectionError("FreeCAD is not running with the RL CAD workbench (bridge port %d closed). Start FreeCAD; "
                              "the bridge starts automatically, or use RL CAD > Start AI bridge." % port())
    try:
        return getattr(proxy(), method)(*args)
    except xmlrpc.client.Fault as e:
        raise RuntimeError(e.faultString.split("\n")[0][:600])
