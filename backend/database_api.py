"""Authenticated editor context; package content never travels on the game stream."""

import base64
import re
from uuid import uuid4

from . import scene_portraits
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from . import club_art, valve_import
from . import database as data
from .portrait_sources import previously_rejected


def editor_router(app):
    router = APIRouter(prefix="/api/database")

    @router.get("")
    async def catalog():
        return data.installed(app.state.store.db)

    @router.get("/personal-badges/status")
    async def personal_status():
        return app.state.store.badges.status()

    @router.post("/personal-badges/action")
    async def personal_action(body: dict):
        try:
            return app.state.store.badges.start(body.get("mode"))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.post("/personal-badges/offline")
    async def personal_offline(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > 24 * 1024 * 1024:
                raise HTTPException(413, "Личный пакет больше 24 МиБ")
            content.extend(chunk)
        try:
            return await run_in_threadpool(
                app.state.store.badges.install_offline, content
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @router.get("/personal-image/{digest}")
    async def personal_image(digest: str):
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise HTTPException(404)
        result = app.state.store.badges.image(digest)
        if not result:
            raise HTTPException(404)
        return Response(
            result[0],
            media_type=result[1],
            headers={
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.get("/{key}/{revision}/club-index")
    async def club_index(key: str, revision: int):
        try:
            p = data.get(app.state.store.db, key, revision)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {**club_art.archive_index(p), **app.state.store.badges.index(p)}

    @router.get("/club-art/{filename}")
    async def club_image(filename: str):
        if not re.fullmatch(r"[0-9a-f]{64}\.png", filename):
            raise HTTPException(404)
        file = club_art.ROOT / filename
        if not file.is_file():
            raise HTTPException(404)
        return Response(
            file.read_bytes(),
            media_type="image/png",
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @router.get("/{key}/{revision}")
    async def package(key: str, revision: int):
        try:
            p = data.get(app.state.store.db, key, revision)
            return dict(
                data.envelope(p),
                portraits=scene_portraits.index(p, app.state.store.portraits),
                clubArt={
                    **club_art.archive_index(p),
                    **app.state.store.badges.index(p),
                },
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/{key}/{revision}/ratings/{player}")
    async def ratings(key: str, revision: int, player: str):
        try:
            p = data.get_record(app.state.store.db, key, revision, "players", player)
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
            record = data.get_record(
                app.state.store.db,
                key,
                revision,
                "players" if group == "appearance" else group,
                ident,
            )
            asset = (
                record.get("appearance")
                if group == "appearance"
                else record.get("logo") or record.get("photo")
            )
            if group in ("teams", "organizations"):
                lookup = {
                    "id": key,
                    "teams": {},
                    "organizations": {},
                    group: {ident: record},
                }
                override = app.state.store.badges.index(lookup).get(group + "/" + ident)
                if override:
                    return RedirectResponse(
                        override["image"], headers={"Cache-Control": "no-store"}
                    )
                fallback = club_art.archive_badge(key, record)
                if fallback:
                    return RedirectResponse(fallback["image"])
            if asset == "zywoo-chicago-2019" or (
                group in ("players", "appearance")
                and isinstance(asset, dict)
                and previously_rejected(asset.get("source", ""))
            ):
                raise HTTPException(404)
            if not asset:
                raise HTTPException(404)
            image = asset["image"]
            if image.startswith("https://"):
                return RedirectResponse(image)
            header, payload = image.split(",", 1)
            return Response(
                base64.b64decode(payload),
                media_type=header[5:].split(";")[0],
                headers={
                    "Cache-Control": "private, no-store"
                    if group in ("teams", "organizations")
                    else "private, max-age=86400"
                },
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
