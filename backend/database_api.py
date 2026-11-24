"""Authenticated editor context; package content never travels on the game stream."""

from uuid import uuid4
import base64
from fastapi.responses import Response, RedirectResponse

from fastapi import APIRouter, HTTPException, Request

from . import database as data, valve_import


def editor_router(app):
    router = APIRouter(prefix="/api/database")

    @router.get("")
    async def catalog():
        return data.installed(app.state.store.db)

    @router.get("/{key}/{revision}")
    async def package(key: str, revision: int):
        try:
            p = data.get(app.state.store.db, key, revision)
            return dict(
                data.envelope(p),
                portraits=app.state.store.portraits.index(p["players"]),
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/{key}/{revision}/ratings/{player}")
    async def ratings(key: str, revision: int, player: str):
        try:
            p = data.get(app.state.store.db, key, revision)["players"][player]
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "Игрок или редакция не найдены") from exc
        values = {
            r: data.skills.role_rating(p["skills"], r) for r in data.world.ROLE_NAMES
        }
        return dict(roles=values, overall=round(sum(values.values()) / len(values)))

    @router.get("/{key}/{revision}/media/{group}/{ident}")
    async def media(key: str, revision: int, group: str, ident: str):
        if group not in ("teams", "players", "organizations", "staff", "appearance"):
            raise HTTPException(404)
        try:
            record = data.get(app.state.store.db, key, revision)[
                "players" if group == "appearance" else group
            ][ident]
            asset = (
                record.get("appearance")
                if group == "appearance"
                else record.get("logo") or record.get("photo")
            )
            if asset == "zywoo-chicago-2019":
                return RedirectResponse(
                    "https://commons.wikimedia.org/wiki/Special:FilePath/IEM_Chicago_Final_Edits-9731_ZywOo_%2848353577846%29_%28cropped%29.jpg?width=250"
                )
            if not asset:
                raise HTTPException(404)
            image = asset["image"]
            if image.startswith("https://"):
                return RedirectResponse(image)
            header, payload = image.split(",", 1)
            return Response(
                base64.b64decode(payload),
                media_type=header[5:].split(";")[0],
                headers={"Cache-Control": "private, max-age=86400"},
            )
        except (KeyError, ValueError):
            raise HTTPException(404)

    @router.post("/import")
    async def upload(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > 24 * 1024 * 1024:
                raise HTTPException(413, "Пакет больше 24 МиБ")
        store = app.state.store
        try:
            if request.headers.get("content-type") == "application/zip":
                pack = valve_import.import_zip(content)
                content = data.encode(data.envelope(pack))
            with store.transaction():
                return data.install(store.db, content)
        except (ValueError, TypeError, KeyError, RecursionError) as exc:
            raise HTTPException(422, f"Ошибка импорта: {exc}") from exc

    @router.post("/{key}/{revision}/copy")
    async def fork(key: str, revision: int, body: dict):
        store = app.state.store
        try:
            with store.transaction():
                p = data.get(store.db, key, revision)
                p.update(id=str(uuid4()), revision=1, title=body["title"])
                data.put(store.db, p)
                return dict(id=p["id"], revision=1)
        except (KeyError, ValueError) as exc:
            raise HTTPException(422, f"Пакет не скопирован: {exc}") from exc

    @router.post("/{key}/{revision}/{group}/{ident}")
    async def change(key: str, revision: int, group: str, ident: str, body: dict):
        store = app.state.store
        try:
            with store.transaction():
                data.require(
                    type(body.get("create")) is bool, "Не указан тип изменения"
                )
                return data.edit(
                    store.db,
                    key,
                    revision,
                    group,
                    ident,
                    body["record"],
                    body["create"],
                )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise HTTPException(422, f"Изменение отклонено: {exc}") from exc

    return router
