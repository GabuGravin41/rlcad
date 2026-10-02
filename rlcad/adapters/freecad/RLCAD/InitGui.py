# RL CAD workbench for FreeCAD: open RL CAD designs, edit their parameters in a spreadsheet, sync with RL CAD,
# and let RL CAD's AI agent drive FreeCAD through a local bridge.
import os

import FreeCAD as App
import FreeCADGui as Gui


class RLCADWorkbench(Gui.Workbench):
    MenuText = "RL CAD"
    ToolTip = "AI-assisted design with RL CAD: parameters, checks and exports"

    def Initialize(self):
        from rlcad_freecad import commands
        cmds = commands.register()
        self.appendToolbar("RL CAD", cmds)
        self.appendMenu("RL CAD", cmds)

    def GetClassName(self):
        return "Gui::PythonWorkbench"


Gui.addWorkbench(RLCADWorkbench())

# start the bridge when FreeCAD starts (set "bridge_autostart": false in ~/.rlcad/config.json to disable)
try:
    from rlcad_freecad import bridge, core
    if core.config().get("bridge_autostart", True):
        from PySide import QtCore
        QtCore.QTimer.singleShot(1500, bridge.start)
except Exception as e:  # noqa
    App.Console.PrintWarning("RL CAD bridge not started: %s\n" % e)
