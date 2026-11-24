"""Standard-library Windows launcher discovery shared by the EXE and source scripts."""
import errno
import http.client
import json
import logging
import os
import subprocess
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def launcher_lock(path):
    """Lock ownership follows the process lifetime, including abrupt termination."""
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as err:
                if err.errno not in (errno.EACCES, errno.EAGAIN):
                    raise
                yield False
                return
        else:
            import fcntl

            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
        yield True


def ready(port, nonce):
    """Verify a live owner directly on loopback, ignoring system proxy settings."""
    client = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        client.request("GET", "/api/desktop/instance")
        response = client.getresponse()
        return response.status == 200 and response.read(256) == nonce.encode("ascii")
    except (OSError, http.client.HTTPException):
        return False
    finally:
        client.close()


def open_browser(url):
    """Use the user's HTTP association, or an installed browser if it is broken."""
    import winreg

    try:
        os.startfile(url)
        return
    except OSError as error:
        logging.warning("Windows не смогла открыть ссылку через браузер по умолчанию: %s", error)

    app_paths = r"Software\Microsoft\Windows\CurrentVersion\App Paths"
    for name in ("msedge.exe", "chrome.exe", "firefox.exe"):
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(hive, app_paths + "\\" + name) as key:
                    value, kind = winreg.QueryValueEx(key, None)
                if kind not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    continue
                executable = Path(os.path.expandvars(value).strip('"'))
                if executable.is_absolute() and executable.is_file():
                    subprocess.Popen([str(executable), url], close_fds=True)
                    return
            except OSError:
                continue
    raise RuntimeError("Выберите установленный браузер по умолчанию в настройках Windows и откройте EsportSim снова.")


def open_existing(descriptor, open_url):
    try:
        data = json.loads(descriptor.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return False
    if ready(data["port"], data["nonce"]):
        open_url(f"http://127.0.0.1:{data['port']}/")
        return True
    return False
