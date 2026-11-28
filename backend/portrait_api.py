from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from . import lineup_photos, database, personal_portraits, scene_portraits


def portrait_router(app):
    routes = APIRouter(prefix="/api/portraits")

    @routes.get("/status")
    async def status():
        library = app.state.store.portraits
        return dict(library.status(), lineupCount=len(lineup_photos.index(library)))

    @routes.post("/pause")
    async def pause():
        return app.state.store.portraits.pause()

    @routes.post("/{key}/{revision}/start")
    async def start(key: str, revision: int, body: dict):
        store = app.state.store
        try:
            return store.portraits.start(
                database.get(store.db, key, revision), body.get("mode")
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.post("/{key}/{revision}/offline")
    async def offline(key: str, revision: int, request: Request):
        store = app.state.store
        try:
            pack = database.get(store.db, key, revision)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > personal_portraits.MAX_PACK:
                raise HTTPException(413, "Личный пакет превышает 96 МиБ")
            content.extend(chunk)
        try:
            return await run_in_threadpool(
                personal_portraits.install, store.portraits, pack, content
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.get("/{key}/{revision}/index")
    async def index(key: str, revision: int):
        store = app.state.store
        try:
            return scene_portraits.index(database.get(store.db, key, revision), store.portraits)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

    @routes.post("/lineup-photos")
    async def install_lineup_photos(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            if len(content) + len(chunk) > lineup_photos.MAX_ARCHIVE:
                raise HTTPException(413, "Размер ZIP превышает 80 МиБ")
            content.extend(chunk)
        try:
            return await run_in_threadpool(lineup_photos.install, app.state.store.portraits, content)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @routes.get("/lineup-photos.zip")
    def export_lineup_photos():
        try:
            data = lineup_photos.export(app.state.store.portraits)
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(data, media_type="application/zip", headers={
            "Content-Disposition": 'attachment; filename="R5.7-private-lineup-photos.zip"', "Cache-Control":"private, no-store"})

    @routes.get("/kit-index")
    async def kit_index():
        return personal_portraits.installed_kits(app.state.store.portraits)

    @routes.get("/generated/{digest}")
    def generated(digest: str):
        data = scene_portraits.read(digest)
        if not data:
            raise HTTPException(404)
        return Response(data, media_type="image/webp", headers={"Cache-Control": "private, immutable, max-age=31536000"})

    @routes.get("/image/{digest}")
    async def image(digest: str):
        data = app.state.store.portraits.image(digest) if len(digest) == 64 else None
        if not data:
            raise HTTPException(404)
        return Response(
            data,
            media_type="image/png",
            headers={"Cache-Control": "private, immutable, max-age=31536000"},
        )

    return routes
