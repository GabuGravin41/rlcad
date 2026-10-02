"""RL CAD: AI-assisted mechanical design."""
import logging as _logging

# ezdxf (pulled in by build123d's exporters) scans every installed font on its first import to build a font cache.
# fontTools then warns about fonts with small header errors ("'name' table stringOffset incorrect"), which is noise:
# RL CAD uses no fonts. Only real errors are shown.
_logging.getLogger("fontTools").setLevel(_logging.ERROR)
