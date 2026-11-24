"""Run the production entry point with a database private to this Playwright run."""
import runpy
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
with tempfile.TemporaryDirectory(prefix="esport-r0-playwright-") as data:
    sys.argv = ["backend.run", "--port", "8766", "--data", data]
    runpy.run_module("backend.run", run_name="__main__")
