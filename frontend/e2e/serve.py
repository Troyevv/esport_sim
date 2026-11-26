"""One isolated home per browser suite. The fast suite also covers legacy Depo careers."""
import sys
import tempfile
from pathlib import Path
import uvicorn

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root))
from backend.server import create_app

with tempfile.TemporaryDirectory(prefix="esport-r0-playwright-") as data:
    uvicorn.run(create_app(Path(data) / "scenario.sqlite"), host="127.0.0.1", port=8766,
                proxy_headers=False, access_log=False)
