import asyncio
import ipaddress
import secrets
from collections import Counter
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictInt, Field

from .engine import TICK_SECONDS
from .host import own_clock, issue_code, digest
from .store import Conflict, Store
from .home_settings import home_router
from .lan import LanAccess

View = Literal["full", "T", "CT"]
COOKIE = "esport_device"


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    revision: StrictInt
    context: str
    kind: Literal["start", "pause", "speed", "reset", "save", "load"]
    value: StrictInt | None = None


class Pair(BaseModel):
    code: str
    name: str = Field(default="Устройство", max_length=80)


def create_app(
    db_path: Path,
    mode="local",
    origins=(),
    pairing_code=None,
    *,
    managed=True,
    on_shutdown=None,
    _shared=None,
):
    origins = frozenset(origins)
    hosts = {urlsplit(item).netloc for item in origins}
    # A second TLS listener serves the same store and wakes the same subscribers.
    # Only the owning application runs the lifespan and advances model time.
    condition, connections = (
        _shared[:2] if _shared else (asyncio.Condition(), Counter())
    )
    manages_home = mode == "local" and managed

    @asynccontextmanager
    async def lifespan(app):
        with own_clock(db_path):
            store = Store(db_path)
            app.state.store = store
            if pairing_code:
                with store.transaction():
                    issue_code(store.db, pairing_code)

            async def clock():
                loop = asyncio.get_running_loop()
                deadline = loop.time()
                while True:
                    deadline += TICK_SECONDS
                    if deadline <= loop.time():
                        # Resume from a long stall without a burst of catch-up ticks.
                        deadline = loop.time() + TICK_SECONDS
                    await asyncio.sleep(max(0, deadline - loop.time()))
                    async with condition:
                        if store.tick():
                            condition.notify_all()

            if manages_home:

                def guest_app(origin):
                    return create_app(
                        db_path,
                        "lan",
                        [origin],
                        managed=False,
                        _shared=(condition, connections, store),
                    )

                app.state.lan = LanAccess(db_path.parent, guest_app)
                await app.state.lan.restore()

            task = asyncio.create_task(clock())
            try:
                yield
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
                try:
                    if manages_home:
                        await app.state.lan.close()
                finally:
                    store.db.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    if _shared:
        app.state.store = _shared[2]

    def trusted(conn, require_origin):
        host = conn.headers.get("host", "")
        origin = conn.headers.get("origin")
        if mode == "local":
            try:
                name = urlsplit("//" + host).hostname
                loopback = ipaddress.ip_address(conn.client.host).is_loopback and (
                    name == "localhost" or ipaddress.ip_address(name).is_loopback
                )
            except (TypeError, ValueError):
                return False
            return loopback and (
                origin == "http://" + host or (not require_origin and origin is None)
            )
        if mode == "lan":
            try:
                if not ipaddress.ip_address(conn.client.host).is_private:
                    return False
            except (ValueError, AttributeError):
                return False
        return (
            conn.url.scheme in ("https", "wss")
            and host in hosts
            and (origin in origins or (not require_origin and origin is None))
        )

    def paired(conn):
        if mode == "local":
            return True
        token = conn.cookies.get(COOKIE, "")
        return bool(
            token
            and app.state.store.db.execute(
                "SELECT 1 FROM device WHERE digest=?", (digest(token),)
            ).fetchone()
        )

    @app.middleware("http")
    async def access(request, call_next):
        if not trusted(request, request.method not in ("GET", "HEAD")):
            return JSONResponse(
                {"detail": "Источник запроса не разрешён"}, status_code=403
            )
        if (
            request.url.path.startswith("/api/")
            and request.url.path not in ("/api/pair", "/api/capabilities")
            and not paired(request)
        ):
            return JSONResponse(
                {"detail": "Подтвердите устройство на домашнем сервере"},
                status_code=401,
            )
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/capabilities")
    async def capabilities():
        return {"hostSettings": manages_home}

    if manages_home:
        app.include_router(home_router(app, connections, on_shutdown))

    @app.post("/api/pair")
    async def pair(body: Pair):
        store = app.state.store
        with store.transaction():
            valid = (
                store.db.execute(
                    "DELETE FROM invitation WHERE digest=? AND expires>unixepoch()",
                    (digest(body.code),),
                ).rowcount
                if mode != "local"
                else 0
            )
            if valid != 1:
                raise HTTPException(403, "Неверный или использованный код устройства")
            token = secrets.token_urlsafe(32)
            key = digest(token)
            store.db.execute("INSERT INTO device VALUES(?)", (key,))
            store.db.execute(
                "INSERT INTO device_info VALUES(?, ?, unixepoch())",
                (key, body.name.strip() or "Устройство"),
            )
        response = JSONResponse({"paired": True})
        response.set_cookie(
            COOKIE,
            token,
            secure=True,
            httponly=True,
            samesite="strict",
            max_age=2592000,
        )
        return response

    @app.get("/api/state")
    async def state(view: View = "full"):
        return app.state.store.snapshot(view)

    @app.get("/api/command/{command_id}")
    async def result(command_id: UUID):
        found = app.state.store.result(str(command_id))
        if found is None:
            raise HTTPException(404, "Команда ещё не принята")
        return found

    @app.post("/api/command")
    async def command(body: Command):
        async with condition:
            try:
                response = app.state.store.apply(body.model_dump(mode="json"))
            except Conflict as err:
                raise HTTPException(409, str(err)) from err
            except ValueError as err:
                raise HTTPException(422, str(err)) from err
            condition.notify_all()
            return response

    @app.websocket("/api/stream")
    async def stream(ws: WebSocket, view: View = "full"):
        if not trusted(ws, True) or not paired(ws):
            await ws.close(code=1008)
            return
        await ws.accept()
        key = digest(ws.cookies.get(COOKIE, "")) if mode != "local" else None
        if key:
            connections[key] += 1
        previous = None
        last = -1
        try:
            while True:
                if not paired(ws):
                    await ws.close(code=1008)
                    return
                async with condition:
                    snapshot = app.state.store.snapshot(view, previous)
                    if snapshot["sequence"] == last:
                        try:
                            await asyncio.wait_for(condition.wait(), timeout=1)
                            continue
                        except TimeoutError:
                            pass
                # Each message is a complete projection. Slow readers can skip frames.
                await ws.send_json(snapshot)
                last = snapshot["sequence"]
                previous = snapshot["context"], snapshot["world"]["tick"]
        except (WebSocketDisconnect, OSError):
            pass
        finally:
            if key:
                connections[key] -= 1
                if not connections[key]:
                    del connections[key]

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True))
    return app
