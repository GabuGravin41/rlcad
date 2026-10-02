"""RL CAD workbench commands (kept in a module: FreeCAD runs InitGui.py in a way that hides its module-level
names from the workbench's methods)."""
import os

import FreeCAD as App
import FreeCADGui as Gui


def _core():
    from rlcad_freecad import core
    return core


def _report(title, res):
    import json
    App.Console.PrintMessage("RL CAD %s: %s\n" % (title, json.dumps(res, default=str)[:3000]))


class _OpenDesign:
    def GetResources(self):
        return {"MenuText": "Open design...", "ToolTip": "Open an RL CAD design folder (contains rlcad.json)"}

    def Activated(self):
        from PySide import QtGui
        folder = QtGui.QFileDialog.getExistingDirectory(None, "RL CAD design folder (contains rlcad.json)")
        if folder:
            try:
                _report("open", _core().open_design(folder))
            except Exception as e:
                App.Console.PrintError("RL CAD: %s\n" % e)

    def IsActive(self):
        return True


class _Sync:
    def GetResources(self):
        return {"MenuText": "Sync", "ToolTip": "Apply the edited parameters (RLCAD_Params, column B), rebuild, "
                                               "check and reload the model"}

    def Activated(self):
        try:
            res = _core().sync()
            _report("sync", res)
            s = res.get("summary") or {}
            App.Console.PrintMessage("RL CAD: %s errors, %s warnings. See RLCAD_Checks.\n"
                                     % (s.get("error"), s.get("warning")))
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)

    def IsActive(self):
        return App.ActiveDocument is not None


class _Rebuild:
    def GetResources(self):
        return {"MenuText": "Rebuild from RL CAD", "ToolTip": "Re-run RL CAD on the design folder and reload "
                                                              "(use after the AI agent changed the design)"}

    def Activated(self):
        try:
            core = _core()
            folder = core.design_folder(App.ActiveDocument)
            _report("rebuild", core.open_design(folder, rebuild=True))
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)

    def IsActive(self):
        return App.ActiveDocument is not None


class _Integrate:
    def GetResources(self):
        return {"MenuText": "PCB <-> CAD check", "ToolTip": "Check the RL PCB boards against the airframe (mounting, "
                                                             "heights, fit, connector reach, cables); see RLCAD_Integration"}

    def Activated(self):
        try:
            _report("integrate", _core().integrate())
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)

    def IsActive(self):
        return App.ActiveDocument is not None


class _Bridge:
    def GetResources(self):
        return {"MenuText": "Start AI bridge", "ToolTip": "Let the RL CAD agent (Claude Desktop MCP) drive FreeCAD"}

    def Activated(self):
        from rlcad_freecad import bridge
        bridge.start()

    def IsActive(self):
        return True


def _qt():
    try:
        from PySide import QtGui, QtWidgets  # noqa
        return QtWidgets
    except ImportError:
        from PySide import QtGui
        return QtGui


class _Mode:
    def GetResources(self):
        return {"MenuText": "AI mode...", "ToolTip": "How much the AI may do: teach, advise, propose (you accept each "
                                                    "change) or do (it changes the design; you can undo)"}

    def Activated(self):
        W = _qt()
        try:
            st = _core().tool("copilot_status")
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)
            return
        modes = ["teach", "advise", "propose", "do"]
        m, ok = W.QInputDialog.getItem(None, "RL CAD: AI mode",
                                       "Mode for the whole design (now: %s).\n"
                                       "teach: explains only\nadvise: guidelines, you edit\n"
                                       "propose: AI prepares changes, you accept each\ndo: AI edits, you can undo"
                                       % st.get("mode"), modes, modes.index(st.get("mode", "propose")), False)
        if ok:
            _report("mode", _core().tool("copilot_mode", {"mode": m}))

    def IsActive(self):
        return App.ActiveDocument is not None


class _Proposals:
    def GetResources(self):
        return {"MenuText": "Proposals...", "ToolTip": "Changes the AI prepared on a copy of the design, with their "
                                                      "check results: accept or reject them"}

    def Activated(self):
        W = _qt()
        core = _core()
        try:
            ps = core.tool("proposals").get("proposals", [])
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)
            return
        if not ps:
            W.QMessageBox.information(None, "RL CAD", "No proposals waiting.")
            return
        dlg = W.QDialog()
        dlg.setWindowTitle("RL CAD: proposals")
        lay = W.QVBoxLayout(dlg)
        lst = W.QListWidget()
        for p in ps:
            c = p.get("checks") or {}
            chk = ""
            if "errors_after" in c:
                chk = "  [errors %s→%s, warnings %s→%s]" % (c.get("errors_before", "?"), c["errors_after"],
                                                             c.get("warnings_before", "?"), c["warnings_after"])
            lst.addItem("%s  %s: %s%s" % (p["id"], p["action"], p["summary"], chk))
        lay.addWidget(lst)
        detail = W.QTextEdit()
        detail.setReadOnly(True)
        lay.addWidget(detail)

        def show(i):
            if 0 <= i < len(ps):
                c = ps[i].get("checks") or {}
                detail.setPlainText("%s\n\nNew findings:\n%s\n\nResolved:\n%s" % (
                    ps[i]["summary"], "\n".join(c.get("new_findings") or ["none"]),
                    "\n".join(c.get("resolved_findings") or ["none"])))
        lst.currentRowChanged.connect(show)
        row = W.QHBoxLayout()
        b_acc, b_rej, b_close = W.QPushButton("Accept"), W.QPushButton("Reject..."), W.QPushButton("Close")
        for b in (b_acc, b_rej, b_close):
            row.addWidget(b)
        lay.addLayout(row)

        def accept():
            i = lst.currentRow()
            if i < 0:
                return
            r = core.accept_proposal(ps[i]["id"])
            _report("accept", r)
            dlg.accept()

        def reject():
            i = lst.currentRow()
            if i < 0:
                return
            why, ok = W.QInputDialog.getText(None, "Reject", "Why? (the AI follows this next time)")
            if ok:
                _report("reject", core.tool("proposal_reject", {"id": ps[i]["id"], "reason": why}))
                lst.takeItem(i)
                ps.pop(i)
        b_acc.clicked.connect(accept)
        b_rej.clicked.connect(reject)
        b_close.clicked.connect(dlg.reject)
        dlg.resize(760, 420)
        dlg.exec_()

    def IsActive(self):
        return App.ActiveDocument is not None


class _Undo:
    def GetResources(self):
        return {"MenuText": "Undo last design change", "ToolTip": "Undo the last change made by the AI (do mode) or "
                                                                 "the last accepted proposal, then rebuild"}

    def Activated(self):
        try:
            core = _core()
            r = core.tool("undo")
            _report("undo", r)
            if not r.get("error"):
                core.sync()
        except Exception as e:
            App.Console.PrintError("RL CAD: %s\n" % e)

    def IsActive(self):
        return App.ActiveDocument is not None


class _Review:
    def GetResources(self):
        return {"MenuText": "Review selected part...", "ToolTip": "Manufacturability review (3D printing or injection "
                                                                "molding) of the selected RL CAD part, with reasons"}

    def Activated(self):
        W = _qt()
        sel = Gui.Selection.getSelection()
        if not sel:
            W.QMessageBox.information(None, "RL CAD", "Select a part in the model tree first.")
            return
        name = sel[0].Label
        proc, ok = W.QInputDialog.getItem(None, "RL CAD: review", "Process for %s" % name,
                                          ["fdm", "injection_molding"], 0, False)
        if not ok:
            return
        r = _core().tool("review_part", {"part": name, "process": proc})
        if r.get("error"):
            App.Console.PrintError("RL CAD: %s\n" % r["error"])
            return
        lines = ["%s [%s] %s\n    why: %s%s" % (p["level"].upper(), p["category"], p["message"], p["why"],
                                                 ("\n    try: " + p["suggestion"]) if p.get("suggestion") else "")
                 for p in r["points"]]
        W.QMessageBox.information(None, "RL CAD: %s (%s)" % (name, proc), "\n\n".join(lines))

    def IsActive(self):
        return App.ActiveDocument is not None



COMMANDS = [("RLCAD_Open", _OpenDesign), ("RLCAD_Sync", _Sync), ("RLCAD_Rebuild", _Rebuild),
            ("RLCAD_Integrate", _Integrate), ("RLCAD_Mode", _Mode), ("RLCAD_Proposals", _Proposals),
            ("RLCAD_Undo", _Undo), ("RLCAD_Review", _Review), ("RLCAD_Bridge", _Bridge)]


def register():
    for name, cls in COMMANDS:
        Gui.addCommand(name, cls())
    return [n for n, _ in COMMANDS]
