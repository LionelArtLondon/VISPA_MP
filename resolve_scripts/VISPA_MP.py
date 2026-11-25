# VISPA MP bridge for the free edition of DaVinci Resolve.
# Start it from Workspace > Scripts > VISPA_MP and leave the window open.

import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from vispa_mp.resolve_host import serve

try:
    _resolve = resolve
except NameError:
    raise SystemExit("Start this script from Workspace > Scripts inside DaVinci Resolve.")

serve(_resolve, globals().get("bmd"), globals().get("fusion") or globals().get("fu"))
