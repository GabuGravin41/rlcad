"""Local bridge so RL CAD's agent (MCP server) can drive the running FreeCAD, like KiCad's IPC API for RL PCB.

An XML-RPC server listens on 127.0.0.1 (port from ~/.rlcad/config.json, default 49717). Calls are queued and run
on FreeCAD's GUI thread by a Qt timer, because FreeCAD documents must only be touched from that thread.
"""
import os
import queue
import threading
import traceback
from xmlrpc.server import SimpleXMLRPCRequestHandler, SimpleXMLRPCServer

import FreeCAD as App

from . import core

DEFAULT_PORT = 49717
_server = None
_thread = None
_timer = None
_jobs = queue.Queue()


class _Quiet(SimpleXMLRPCRequestHandler):
    rpc_paths = ("/RPC2", "/")

    def log_message(self, *a):
        pass


def _on_gui(fn, *args, timeout=1200):
    """Run fn on the GUI thread (or inline in headless FreeCAD) and wait for its result."""
    if _timer is None:
        return fn(*args)
    box = {}
    done = threading.Event()
    _jobs.put((fn, args, box, done))
    if not done.wait(timeout):
        raise RuntimeError("FreeCAD did not finish the request in time")
    if "error" in box:
        raise RuntimeError(box["error"])
    return box["value"]


def _pump():
    while True:
        try:
            fn, args, box, done = _jobs.get_nowait()
        except queue.Empty:
            return
        try:
            box["value"] = fn(*args)
        except Exception as e:  # noqa
            box["error"] = "%s: %s\n%s" % (type(e).__name__, e, traceback.format_exc()[-1500:])
        done.set()


# ------------------------------------------------------------------------------------------ RPC methods
def _status():
    docs = []
    for d in App.listDocuments().values():
        docs.append({"name": d.Name, "label": d.Label, "file": d.FileName, "rlcad_folder": core.design_folder(d)})
    return {"freecad": ".".join(App.Version()[:3]), "documents": docs,
            "active": App.ActiveDocument.Name if App.ActiveDocument else None}


def _screenshot(path, view="iso", width=1600, height=1000):
    import FreeCADGui as Gui
    v = Gui.ActiveDocument.ActiveView
    {"iso": v.viewIsometric, "top": v.viewTop, "front": v.viewFront, "right": v.viewRight,
     "left": v.viewLeft, "rear": v.viewRear, "bottom": v.viewBottom}.get(view, v.viewIsometric)()
    v.fitAll()
    v.saveImage(path, int(width), int(height), "White")
    return {"path": path}


class API:
    def ping(self):
        return "pong"

    def status(self):
        return _on_gui(_status)

    def open_design(self, folder, rebuild=False):
        return _on_gui(core.open_design, folder, bool(rebuild))

    def params(self, folder=""):
        def f():
            d = core.find_doc(folder or None) or App.ActiveDocument
            return core.read_params(d)
        return _on_gui(f)

    def set_params(self, values, folder=""):
        return _on_gui(lambda: core.set_params(values, folder=folder or None))

    def sync(self, folder=""):
        return _on_gui(lambda: core.sync(folder=folder or None))

    def integrate(self, folder=""):
        return _on_gui(lambda: core.integrate(folder=folder or None))

    def screenshot(self, path, view="iso"):
        return _on_gui(_screenshot, path, view)


def start(port=None, gui=True):
    global _server, _thread, _timer
    if _server is not None:
        return _server.server_address[1]
    port = int(port or core.config().get("bridge_port") or DEFAULT_PORT)
    _server = SimpleXMLRPCServer(("127.0.0.1", port), requestHandler=_Quiet, allow_none=True, logRequests=False)
    _server.register_instance(API())
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    if gui:
        from PySide import QtCore
        _timer = QtCore.QTimer()
        _timer.timeout.connect(_pump)
        _timer.start(100)
    App.Console.PrintMessage("RL CAD bridge listening on 127.0.0.1:%d\n" % port)
    return port


def stop():
    global _server, _timer
    if _server is not None:
        _server.shutdown()
        _server.server_close()
        _server = None
    if _timer is not None:
        _timer.stop()
        _timer = None
