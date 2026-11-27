"""Launch the current VISPA MP source tree independently of the working directory."""
import os
from pathlib import Path
import runpy
import sys
import tempfile
import time


def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    sys.path.insert(0, str(root))
    sys.dont_write_bytecode = True
    # Read current source even when an old .pyc has the same timestamp and size.
    # The unique prefix is never created because bytecode writes are disabled.
    sys.pycache_prefix = str(Path(tempfile.gettempdir()) / f"vispa-live-{os.getpid()}-{time.time_ns()}")
    runpy.run_module("vispa_mp", run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    main()
