"""Start the packaged home server and open its UI in the Windows default browser."""

import asyncio
import ctypes
import errno
import json
import logging
import os
import secrets
import socket
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn
from fastapi.responses import JSONResponse

from backend.instance import launcher_lock, open_browser, open_existing, ready
from backend.paths import migrate_legacy, windows_data_dir
from backend.server import create_app


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
        expected = request.headers.get("x-esportsim-instance")
        if (
            request.url.path == "/api/host/shutdown"
            and expected is not None
            and not secrets.compare_digest(expected.encode(), nonce.encode())
        ):
            return JSONResponse(
                {"detail": "Экземпляр сервера изменился"}, status_code=409
            )
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

    async def run_server():
        try:
            await server.serve(sockets=[listener])
        except SystemExit as exc:
            # Uvicorn exits on lifespan failure. Propagate the concrete save error
            # to the launcher dialog before SystemExit reaches the event loop.
            raise RuntimeError(
                getattr(app.state, "load_error", "Ошибка запуска сервера")
            ) from exc

    task = asyncio.create_task(run_server())
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
        logging.info("Сервер готов на loopback, порт %s. Открываем браузер.", port)
        open_url(f"http://127.0.0.1:{port}/")
        await task
    finally:
        server.should_exit = True
        await task
        descriptor.unlink(missing_ok=True)


def launch(data, open_url, legacy_source=None):
    data.mkdir(parents=True, exist_ok=True)
    descriptor = data / "instance.json"
    deadline = time.monotonic() + 30
    while True:
        with launcher_lock(data / "launcher.lock") as owner:
            if owner:
                handler = RotatingFileHandler(
                    data / "launcher.log",
                    maxBytes=512_000,
                    backupCount=1,
                    encoding="utf-8",
                )
                logging.basicConfig(level=logging.INFO, handlers=[handler])
                descriptor.unlink(missing_ok=True)
                if legacy_source is not None:
                    migrate_legacy(legacy_source, data / "scenario.sqlite")
                with reserve_listener() as listener:
                    asyncio.run(serve(data, descriptor, listener, open_url))
                return
            if open_existing(descriptor, open_url):
                return
        # A previous owner may be starting or shutting down. Acquire ownership
        # after its exit instead of opening a dead URL or starting another clock.
        if time.monotonic() >= deadline:
            raise RuntimeError("Запущенный экземпляр не ответил в течение 30 секунд.")
        time.sleep(0.15)


def main():
    if sys.argv[1:2] == ["--prepare-head"]:
        if len(sys.argv) != 4:
            return 2
        output = Path(sys.argv[3])
        try:
            from backend.portrait_processing import PortraitProcessor

            processor = PortraitProcessor()
            try:
                output.write_bytes(processor.render(Path(sys.argv[2]).read_bytes()))
            finally:
                processor.close()
        except Exception:
            import traceback

            Path(str(output) + ".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            return 1
        return 0
    try:
        data = windows_data_dir()
        directory = (
            Path(sys.executable).parent
            if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[1]
        )
        launch(data, open_browser, directory / "runtime-data" / "scenario.sqlite")
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
