"""Routes registered only on the authoritative loopback application."""
import io
import secrets
from collections.abc import Callable

import segno
from fastapi import APIRouter, BackgroundTasks, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict

from .host import issue_code


class LanChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    address: str | None = None


def home_router(app, connections, on_shutdown: Callable | None):
    router = APIRouter(prefix="/api/host")

    def settings():
        lan = app.state.lan.status()
        devices = app.state.store.db.execute("""
            SELECT d.digest, m.name, m.paired_at FROM device d
            LEFT JOIN device_info m ON d.digest=m.digest ORDER BY d.rowid
        """)
        return {
            "enabled": lan["enabled"], "url": lan["origin"], "address": lan["address"],
            "addresses": lan["addresses"], "fingerprint": lan["fingerprint"], "error": lan["error"],
            "shutdownAvailable": on_shutdown is not None,
            "devices": [{"id": key[:16], "name": name or "Устройство",
                         "pairedAt": stamp, "connected": bool(connections.get(key))}
                        for key, name, stamp in devices],
        }

    @router.get("")
    async def read_settings():
        return settings()

    @router.post("/lan")
    async def change_lan(body: LanChange):
        try:
            if body.enabled:
                await app.state.lan.enable(body.address)
            else:
                await app.state.lan.disable()
                app.state.store.db.execute("DELETE FROM invitation")
        except (ValueError, RuntimeError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return settings()

    @router.post("/invite")
    async def invite():
        if not app.state.lan.status()["enabled"]:
            raise HTTPException(409, "Сначала включите доступ по локальной сети")
        code = secrets.token_urlsafe(18)
        with app.state.store.transaction():
            issue_code(app.state.store.db, code)
        return {"code": code, "expiresIn": 600}

    @router.delete("/devices/{device_id}", status_code=204)
    async def revoke(device_id: str):
        store = app.state.store
        with store.transaction():
            deleted = store.db.execute("DELETE FROM device WHERE substr(digest,1,16)=?", (device_id,))
            if not deleted.rowcount:
                raise HTTPException(404, "Устройство уже отключено")
        # Commands check access on each request. The stream rechecks on wake or heartbeat.
        return Response(status_code=204)

    @router.get("/qr.svg")
    async def connection_qr():
        url = app.state.lan.status()["origin"]
        if not url:
            raise HTTPException(409, "Сетевой доступ выключен")
        buffer = io.BytesIO()
        segno.make_qr(url, error="m").save(buffer, kind="svg", scale=5, light="white")
        return Response(buffer.getvalue(), media_type="image/svg+xml")

    @router.get("/authority.cer")
    async def authority():
        cert = app.state.lan.ca_file
        if not cert.is_file():
            raise HTTPException(404, "Сначала включите доступ по локальной сети")
        return FileResponse(cert, media_type="application/pkix-cert", filename="EsportSim-Home.cer")

    @router.post("/shutdown")
    async def shutdown(tasks: BackgroundTasks):
        if on_shutdown is None:
            raise HTTPException(409, "Остановите сервер в запустившем его процессе")
        tasks.add_task(on_shutdown)
        return {"closing": True}

    return router
