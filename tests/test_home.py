import hashlib
import ipaddress
import ssl

import httpx

from backend import lan, server
from backend.paths import migrate_legacy
from tests.test_server import local_server, send, snapshot


def test_migrate_old_database_once(tmp_path):
    old = tmp_path / "old.sqlite"
    new = tmp_path / "profile" / "scenario.sqlite"
    with local_server(old) as client:
        send(client, "reset", 2026)
        send(client, "save")
        send(client, "reset", 121)
        original = snapshot(client)
    migrate_legacy(old, new)
    with local_server(new) as client:
        assert snapshot(client) == original
        send(client, "load")
        assert snapshot(client)["world"]["seed"] == 2026
    migrate_legacy(old, new)
    with local_server(new) as client:
        assert snapshot(client)["world"]["seed"] == 2026
    assert old.is_file()


def test_home_administration_uses_the_same_world_and_stays_on_loopback(
    tmp_path, monkeypatch
):
    # Real HTTPS, ephemeral port. Supply a stable interface in isolated CI environments.
    monkeypatch.setattr(lan, "_PRIVATE_RANGES", (ipaddress.ip_network("127.0.0.0/8"),))
    monkeypatch.setattr(lan, "lan_addresses", lambda: ["127.0.0.1"])
    monkeypatch.setattr(
        server, "LanAccess", lambda path, factory: lan.LanAccess(path, factory, port=0)
    )
    with local_server(tmp_path / "home.sqlite") as owner:
        assert owner.get("/api/capabilities").json()["hostSettings"]
        assert not owner.get("/api/host").json()["enabled"]
        assert owner.post("/api/host/invite").status_code == 409
        assert (
            owner.post(
                "/api/host/lan",
                json={"enabled": True},
                headers={"Origin": "https://other.invalid"},
            ).status_code
            == 403
        )
        settings = owner.post(
            "/api/host/lan", json={"enabled": True, "address": "127.0.0.1"}
        ).json()
        url = settings["url"]
        cert = owner.get("/api/host/authority.cer").content
        assert hashlib.sha256(cert).hexdigest().upper() == settings[
            "fingerprint"
        ].replace(":", "")
        ctx = ssl.create_default_context(cadata=ssl.DER_cert_to_PEM_cert(cert))
        with httpx.Client(
            verify=ctx, base_url=url, headers={"Origin": url}, trust_env=False
        ) as phone:
            assert not phone.get("/api/capabilities").json()["hostSettings"]
            assert phone.get("/api/state").status_code == 401
            invitation = owner.post("/api/host/invite").json()
            assert invitation["qrDataUrl"].startswith("data:image/svg+xml;base64,")
            assert b"<svg" in owner.get("/api/host/qr.svg").content
            assert (
                phone.post(
                    "/api/pair", json={"name": "Телефон", "code": invitation["code"]}
                ).status_code
                == 200
            )
            send(phone, "reset", 700)
            assert snapshot(phone) == snapshot(owner)
            assert phone.get("/api/host").status_code == 404
            assert phone.get("/api/host/authority.cer").status_code == 404
            assert phone.post("/api/host/shutdown").status_code in (404, 405)
            device = owner.get("/api/host").json()["devices"][0]
            assert device["name"] == "Телефон"
            assert device["pairedAt"] > 0
            assert owner.delete("/api/host/devices/" + device["id"]).status_code == 204
            assert phone.get("/api/state").status_code == 401
        assert not owner.post("/api/host/lan", json={"enabled": False}).json()[
            "enabled"
        ]
        assert owner.get("/api/state").status_code == 200
        assert owner.post("/api/host/shutdown").status_code == 409
