from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from . import database


def portrait_router(app):
    routes = APIRouter(prefix="/api/portraits")

    @routes.get("/status")
    async def status():
        return app.state.store.portraits.status()

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

    @routes.get("/{key}/{revision}/index")
    async def index(key: str, revision: int):
        store = app.state.store
        try:
            return store.portraits.index(
                database.get(store.db, key, revision)["players"]
            )
        except ValueError as exc:
            raise HTTPException(404, str(exc)) from exc

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
