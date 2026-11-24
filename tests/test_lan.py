import asyncio
import ipaddress
import os
import socket
import ssl

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.x509.oid import ExtendedKeyUsageOID
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from backend import lan


def sample_app(origin):
    app = FastAPI()

    @app.get("/origin")
    async def endpoint():
        return {"origin": origin}

    @app.websocket("/events")
    async def events(ws: WebSocket):
        await ws.accept()
        await ws.send_text(origin)
        try:
            await ws.receive_text()
        except WebSocketDisconnect:
            pass

    return app


def test_lan_tls_lifecycle_and_active_revocation(tmp_path, monkeypatch):
    # CI runners can lack private NICs. Use their loopback only in this test case.
    ips = lan.lan_addresses()
    address = os.getenv("R0_TEST_LAN_IP") or (ips[0] if ips else "127.0.0.1")
    if address == "127.0.0.1":
        monkeypatch.setattr(lan, "lan_addresses", lambda: [address])
        monkeypatch.setattr(lan, "_PRIVATE_RANGES", (*lan._PRIVATE_RANGES, ipaddress.ip_network("127.0.0.0/8")))

    async def scenario():
        access = lan.LanAccess(tmp_path, sample_app, port=0)
        await access.restore()
        assert not access.status()["enabled"]
        assert not access.ca_file.exists()
        with pytest.raises(ValueError):
            await access.enable("0.0.0.0")
        state = await access.enable(address)
        try:
            origin = state["origin"]
            ca_bytes = access.ca_file.read_bytes()
            ca = x509.load_der_x509_certificate(ca_bytes)
            assert ca.fingerprint(hashes.SHA256()).hex(":").upper() == state["fingerprint"]
            assert ca.extensions.get_extension_for_class(x509.BasicConstraints).value.path_length == 0
            leaf = x509.load_pem_x509_certificate((tmp_path/"lan-identity"/"server.pem").read_bytes())
            names = leaf.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            assert names.get_values_for_type(x509.IPAddress) == [ipaddress.ip_address(address)]
            assert ExtendedKeyUsageOID.SERVER_AUTH in leaf.extensions.get_extension_for_class(x509.ExtendedKeyUsage).value
            trust = ssl.create_default_context(cadata=ca_bytes)
            async with httpx.AsyncClient(verify=trust, trust_env=False) as client:
                reply = await client.get(origin + "/origin")
                assert reply.json() == {"origin": origin}
            async with httpx.AsyncClient(trust_env=False) as unpaired_os:
                with pytest.raises(httpx.ConnectError):
                    await unpaired_os.get(origin + "/origin")
            async with connect(origin.replace("https:", "wss:") + "/events", ssl=trust, proxy=None) as stream:
                assert await asyncio.wait_for(stream.recv(), 4) == origin
                await access.close()
                async with asyncio.timeout(4):
                    with pytest.raises(ConnectionClosed):
                        await stream.recv()
            async with httpx.AsyncClient(verify=trust, trust_env=False) as client:
                with pytest.raises(httpx.ConnectError):
                    await client.get(origin + "/origin")
            # The opt-in and CA survive an ordinary server restart.
            await access.restore()
            assert access.status()["enabled"]
            assert access.ca_file.read_bytes() == ca_bytes
            assert access.status()["fingerprint"] == state["fingerprint"]
            await asyncio.gather(access.disable(), access.disable())
            await access.restore()
            assert not access.status()["enabled"]
        finally:
            await access.close()

    asyncio.run(scenario())


def test_invalid_restore_and_port_collision_keep_local_host_available(tmp_path):
    (tmp_path/"lan.json").write_text('{"address":"203.0.113.71"}')
    available = lan.lan_addresses()

    async def scenario():
        with socket.socket() as occupied:
            host = available[0] if available else "127.0.0.1"
            occupied.bind((host, 0))
            occupied.listen()
            access = lan.LanAccess(tmp_path, sample_app, occupied.getsockname()[1])
            await access.restore()
            assert not access.status()["enabled"]
            assert access.status()["error"]
            if available:
                with pytest.raises(OSError):
                    await access.enable(host)
                assert not access.status()["enabled"]
                assert not access.ca_file.exists()
            await access.disable()
            assert not access.status()["error"]

    asyncio.run(scenario())
