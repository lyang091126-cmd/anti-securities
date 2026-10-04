# Compatibility entry point for an older deployment setting.
# The whole app lives in APP.py. This file only runs it, so there is one copy of the code.
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "APP.py"), run_name="__main__")
