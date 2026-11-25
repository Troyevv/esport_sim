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
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, StrictInt, Field

from . import cs2_maps, career, career_scene, tactic_library, tactic_preview, tactics
from .engine import TICK_SECONDS
from .host import own_clock, issue_code, digest
from .store import Conflict, Store
from .portrait_api import portrait_router
from .database_api import editor_router
from .home_settings import home_router
from .lan import LanAccess

View = Literal["full", "T", "CT"]
COOKIE = "esport_device"


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    revision: StrictInt
    context: str
    kind: Literal[
        "start",
        "pause",
        "speed",
        "reset",
        "save",
        "load",
        "match",
        "timeout",
        "call",
        "resume",
        "tactic-save",
        "tactic-delete",
        "tactic-assign",
        "database-match",
        "career-create",
        "career-open",
        "career-exhibition",
        "career-lab",
        "career-save",
        "career-load",
        "career-play",
        "career-finish",
        "career-advance",
    ]
    value: (
        StrictInt
        | Literal["Капитану", "Выход A", "Выход B", "Ускориться", "Экономить"]
        | dict
        | None
    ) = None


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
    wake_calendar = _shared[3] if _shared else asyncio.Event()
    manages_home = mode == "local" and managed

    @asynccontextmanager
    async def lifespan(app):
        with own_clock(db_path):
            try:
                store = Store(db_path)
            except Conflict as exc:
                app.state.load_error = str(exc)
                raise
            app.state.store = store
            store.portraits.resume()
            store.badges.resume()
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

            async def calendar():
                wake_calendar.set()
                while True:
                    await wake_calendar.wait()
                    async with condition:
                        work = store.careers.work(store.read())
                        if not work:
                            wake_calendar.clear()
                            continue
                    token, game = work
                    report, error = None, None
                    try:
                        if game:
                            report = await asyncio.to_thread(career.simulate, game)
                    except (ValueError, ArithmeticError, KeyError) as exc:
                        error = f"Не удалось рассчитать встречу: {exc}"
                    async with condition:
                        try:
                            changed = store.careers.commit_work(token, report, error)
                        except ValueError as exc:
                            changed = store.careers.commit_work(token, None, str(exc))
                        if changed:
                            condition.notify_all()

            if manages_home:

                def guest_app(origin):
                    return create_app(
                        db_path,
                        "lan",
                        [origin],
                        managed=False,
                        _shared=(condition, connections, store, wake_calendar),
                    )

                app.state.lan = LanAccess(db_path.parent, guest_app)
                await app.state.lan.restore()

            task = asyncio.create_task(clock())
            calendar_task = asyncio.create_task(calendar())
            try:
                yield
            finally:
                store.portraits.close()
                store.badges.close()
                calendar_task.cancel()
                with suppress(asyncio.CancelledError):
                    await calendar_task
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

    app.include_router(editor_router(app))
    app.include_router(portrait_router(app))

    @app.get("/api/career")
    async def careers():
        store = app.state.store
        return store.careers.detail(store.read())

    @app.get("/api/career/{career_id}/scene")
    async def scene_directory(career_id: str):
        store = app.state.store
        active = store.read().get("career")
        if not active or active["id"] != career_id:
            raise HTTPException(404, "Карьера уже сменилась")
        pack = store.careers.pack(active["source"])
        return career_scene.directory(pack, store.badges.index(pack), store.portraits)

    @app.get("/api/career/options/{key}/{revision}")
    async def career_options(key: str, revision: int):
        try:
            return career.choices(app.state.store.careers.pack([key, revision]))
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.get("/api/career/report/{event_id}")
    async def career_report(event_id: str):
        store = app.state.store
        c = store.read().get("career")
        for event in reversed(c["history"] if c else []):
            if event["id"] == event_id:
                return store.careers.report(event["result"])
        raise HTTPException(404, "Отчёт не найден")

    @app.get("/api/maps")
    def map_catalog():
        return [{"id":"depo","name":"Депо"}, *[
            {"id":m,"name":cs2_maps.NAMES[m]} for m in cs2_maps.installed()]]

    @app.get("/api/maps/{name}/radar")
    def radar_image(name: str, layer: Literal["default","lower"]="default"):
        if name not in cs2_maps.NAMES:
            raise HTTPException(404,"Неизвестная карта")
        path=cs2_maps.root()/name/(name+("_lower" if layer=="lower" else "")+".png")
        if not path.is_file():
            raise HTTPException(404,"Радар выбранного этажа отсутствует")
        return FileResponse(path,media_type="image/png")

    @app.post("/api/maps/{name}/surface")
    def surface_points(name: str, body: dict):
        from math import isfinite
        try:
            space=cs2_maps.get(name)
            points=body["points"]
            if not isinstance(points,list) or not 1<=len(points)<=96:
                raise ValueError("Допустимо от одной до 96 точек")
            layer=body.get("layer","default")
            z=float(body["height"])
            result=[]
            for point in points:
                x,y=float(point["x"]),float(point["y"])
                if not all(isfinite(v) for v in (x,y,z)):
                    raise ValueError("Недопустимые координаты")
                z=space.pick(x,y,layer,z)
                if body.get("plant") and not space.site_at((x,y,z)):
                    raise ValueError("Для установки выберите площадку A или B")
                result.append(dict(x=x,y=y,z=z))
            return result
        except (KeyError,TypeError,ValueError) as exc:
            raise HTTPException(422,str(exc)) from exc

    @app.post("/api/maps/{name}/routes")
    def map_routes(name: str, body: dict):
        try:
            space = cs2_maps.get(name)
            side, slots = body["side"], body["slots"]
            if side not in ("T", "CT") or not isinstance(slots, list) or len(slots) != 5:
                raise ValueError("Ожидались пять ролей одной стороны")
            result = []
            for slot, steps in enumerate(slots):
                if not isinstance(steps, list) or len(steps) > 96:
                    raise ValueError("Допустимо до 96 точек на роль")
                pos, _, area = space.spawn(side, slot)
                legs = []
                for step in steps:
                    goal = cs2_maps.xyz(step)
                    if step["kind"] not in tactics.MOVES:
                        legs.append([])
                        continue
                    target = space.locate(goal)
                    path = space.route(area, target)
                    if path is None:
                        raise ValueError("Между точками отсутствует проход NAV")
                    points = [pos]
                    for crossing in path:
                        points.extend((space.to_sim(crossing.leave), space.to_sim(crossing.enter)))
                    legs.append([dict(zip(("x","y","z"), p)) for p in [*points, goal]])
                    pos, area = goal, target
                result.append(legs)
            return result
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/tactics")
    async def library():
        store = app.state.store
        result = tactic_library.catalog(store.db)
        state = store.read()
        c = state.get("career")
        if c:
            pack = store.careers.pack(c["source"])
            ids = pack["rosters"][c["teams"][c["team"]]]["players"]
            result["players"] = [pack["players"][pid]["name"] for pid in ids]
        return result

    @app.get("/api/tactics/proposal")
    def proposal(side: Literal["T", "CT"], buy: str, map_id: str="depo"):
        try:
            return tactics.propose(side, buy, secrets.randbits(32),map_id=map_id)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

    @app.post("/api/tactics/preview")
    def preview(body: dict):
        try:
            return tactic_preview.simulate(body)
        except ValueError as err:
            raise HTTPException(422, str(err)) from err

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
            if body.kind.startswith("career-") or body.kind == "load":
                wake_calendar.set()
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
