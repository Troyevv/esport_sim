"""User data locations and the one-time migration for earlier source checkouts."""

import os
from pathlib import Path
import sqlite3
import tempfile

from .host import own_clock


def windows_data_dir() -> Path:
    root = os.environ.get("LOCALAPPDATA")
    if not root or not Path(root).is_absolute():
        raise RuntimeError("Windows не предоставила каталог LOCALAPPDATA")
    return Path(root) / "EsportSim"


def migrate_legacy(source: Path, destination: Path):
    """Use SQLite's backup API so committed WAL records are included.

    Never replace an existing home. Preserve the old file even after success.
    """
    if (
        not source.is_file()
        or destination.exists()
        or source.resolve() == destination.resolve()
    ):
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with own_clock(destination):
        if destination.exists():
            return
        with own_clock(source):
            fd, name = tempfile.mkstemp(dir=destination.parent, suffix=".sqlite.tmp")
            os.close(fd)
            temporary = Path(name)
            try:
                origin = sqlite3.connect(
                    source.resolve().as_uri() + "?mode=ro", uri=True
                )
                try:
                    copy = sqlite3.connect(temporary)
                    try:
                        origin.backup(copy)
                        if copy.execute("PRAGMA quick_check").fetchone() != ("ok",):
                            raise ValueError("Файл сохранения повреждён")
                        row = copy.execute(
                            "SELECT body FROM active WHERE id=1"
                        ).fetchone()
                        if not row:
                            raise ValueError("В файле нет активного сценария")
                        from .store import validate_snapshot
                        import json

                        validate_snapshot(json.loads(row[0]))
                    finally:
                        copy.close()
                finally:
                    origin.close()
                temporary.replace(destination)
            finally:
                temporary.unlink(missing_ok=True)
