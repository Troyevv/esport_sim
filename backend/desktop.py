"""Start the packaged home server and open its UI in the Windows default browser."""

import asyncio
import ctypes
import errno
import http.client
import json
import logging
import os
import secrets
import socket
import sys
import time
from contextlib import contextmanager
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi.responses import JSONResponse

from backend.paths import migrate_legacy, windows_data_dir
from backend.server import create_app


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


def reserve_listener():
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", 8765))
        except OSError as err:
            if err.errno not in (errno.EADDRINUSE, errno.EACCES, 10013, 10048):
                raise
            listener.bind(("127.0.0.1", 0))
        return listener
    except BaseException:
        listener.close()
        raise


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


def open_existing(descriptor, open_url):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            data = json.loads(descriptor.read_text(encoding="utf-8"))
            if ready(data["port"], data["nonce"]):
                open_url(f"http://127.0.0.1:{data['port']}/")
                return
        except (FileNotFoundError, ValueError, KeyError):
            pass
        time.sleep(0.15)
    raise RuntimeError("Запущенный экземпляр не ответил в течение 30 секунд.")


async def serve(data, descriptor, listener, open_url):
    from starlette.responses import PlainTextResponse

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    index = root / "frontend" / "dist" / "index.html"
    if not index.is_file():
        raise FileNotFoundError(
            "Файлы интерфейса отсутствуют. Распакуйте архив целиком."
        )

    port = listener.getsockname()[1]
    nonce = secrets.token_hex(24)

    def shutdown():
        server.should_exit = True

    app = create_app(data / "scenario.sqlite", managed=True, on_shutdown=shutdown)

    @app.middleware("http")
    async def desktop_ready(request, call_next):
        if request.url.path == "/api/desktop/instance":
            if (
                request.method != "GET"
                or request.headers.get("host") != f"127.0.0.1:{port}"
            ):
                return JSONResponse({"detail": "Запрос недоступен"}, status_code=403)
            return PlainTextResponse(nonce, headers={"Cache-Control": "no-store"})
        return await call_next(request)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_config=None,
        access_log=False,
        proxy_headers=False,
        http="h11",
        ws="websockets-sansio",
        lifespan="on",
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        deadline = time.monotonic() + 30
        while not server.started or not await asyncio.to_thread(ready, port, nonce):
            if task.done():
                await task
                raise RuntimeError("Сервер завершил работу во время запуска.")
            if time.monotonic() >= deadline:
                raise RuntimeError("Сервер не запустился в течение 30 секунд.")
            await asyncio.sleep(0.05)
        temporary = descriptor.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(dict(port=port, pid=os.getpid(), nonce=nonce)), encoding="utf-8"
        )
        temporary.replace(descriptor)
        open_url(f"http://127.0.0.1:{port}/")
        await task
    finally:
        server.should_exit = True
        await task
        descriptor.unlink(missing_ok=True)


def launch(data, open_url, legacy_source=None):
    data.mkdir(parents=True, exist_ok=True)
    descriptor = data / "instance.json"
    with launcher_lock(data / "launcher.lock") as owner:
        if not owner:
            open_existing(descriptor, open_url)
            return
        handler = RotatingFileHandler(
            data / "launcher.log", maxBytes=512_000, backupCount=1, encoding="utf-8"
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        descriptor.unlink(missing_ok=True)
        if legacy_source is not None:
            migrate_legacy(legacy_source, data / "scenario.sqlite")
        with reserve_listener() as listener:
            asyncio.run(serve(data, descriptor, listener, open_url))


def main():
    try:
        data = windows_data_dir()
        directory = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        launch(data, os.startfile, directory / "runtime-data" / "scenario.sqlite")
    except (Exception, SystemExit) as err:
        logging.exception("Ошибка запуска EsportSim")
        ctypes.windll.user32.MessageBoxW(
            None,
            f"Не удалось открыть EsportSim.\n\n{err}\n\n"
            "Журнал запуска: %LOCALAPPDATA%\\EsportSim\\launcher.log",
            "EsportSim",
            0x10,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
