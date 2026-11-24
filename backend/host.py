"""OS ownership of the simulation clock; administrative commands use SQLite."""

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def own_clock(db_path: Path):
    # Keep the inode on disk. Removing it after unlock would race a new owner.
    with open(str(db_path) + ".lock", "a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as err:
                raise RuntimeError(
                    "Сервер с этим каталогом данных уже запущен"
                ) from err
        else:
            import fcntl

            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as err:
                raise RuntimeError(
                    "Сервер с этим каталогом данных уже запущен"
                ) from err
        yield


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_code(db, code):
    db.execute("DELETE FROM invitation")
    db.execute("INSERT INTO invitation VALUES(?, unixepoch()+600)", (digest(code),))
