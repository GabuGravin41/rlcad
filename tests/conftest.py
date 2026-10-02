import os

# The engine tests drive the tools directly, as an engineer-approved "do" session would. Gating (modes, proposals)
# is covered in test_copilot.py, which sets its own mode.
os.environ.setdefault("RLCAD_DEFAULT_MODE", "do")
