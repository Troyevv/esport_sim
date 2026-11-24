"""Acceptance tests against actual HTTP/WebSocket listeners and SQLite saves."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import asyncio
import http.client
import json
import os
import secrets
import select
import socket
import socketserver
import ssl
import subprocess
import sys
import threading
import time
from uuid import uuid4

import httpx
import pytest
import uvicorn
from websockets.asyncio.client import connect as async_connect
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.sync.client import connect

from backend.server import create_app


@contextmanager
def listener(host="127.0.0.1"):
    with socket.socket() as sock:
        sock.bind((host, 0))
        sock.listen()
        yield sock


@contextmanager
def serve(app, sock, **tls):
    """Keep one real application lifespan for all devices in a test."""
    config = uvicorn.Config(app, log_level="error", **tls)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        until = time.monotonic() + 8
        while not server.started:
            assert thread.is_alive() and time.monotonic() < until, "Uvicorn did not start"
            time.sleep(0.01)
        yield
    finally:
        server.should_exit = True
        thread.join(timeout=8)
        assert not thread.is_alive(), "Uvicorn did not stop"


@contextmanager
def local_server(db):
    with listener() as sock, serve(create_app(db), sock):
        origin = f"http://127.0.0.1:{sock.getsockname()[1]}"
        with httpx.Client(base_url=origin, headers={"Origin": origin}, trust_env=False) as client:
            yield client


def envelope(state, kind, value=None):
    command = dict(id=str(uuid4()), context=state["context"], revision=state["revision"], kind=kind)
    if value is not None:
        command["value"] = value
    return command


def snapshot(client):
    response = client.get("/api/state")
    response.raise_for_status()
    return response.json()


def send(client, kind, value=None):
    data = envelope(snapshot(client), kind, value)
    response = client.post("/api/command", json=data)
    response.raise_for_status()
    return data, response.json()


def test_conflicting_devices_share_save_and_restart(tmp_path):
    db = tmp_path / "world.sqlite3"
    with local_server(db) as client:
        original = snapshot(client)
        # httpx.Client supports concurrent requests on separate connections.
        commands = [envelope(original, "speed", speed) for speed in (2, 4)]
        with ThreadPoolExecutor(2) as pool:
            responses = list(pool.map(lambda cmd: client.post("/api/command", json=cmd), commands))
        assert sorted(response.status_code for response in responses) == [200, 409]
        winner = next(i for i, result in enumerate(responses) if result.is_success)
        assert snapshot(client)["speed"] == commands[winner]["value"]
        send(client, "start")
        until = time.monotonic() + 3
        while snapshot(client)["world"]["tick"] < 2:
            assert time.monotonic() < until
            time.sleep(0.02)
        send(client, "pause")
        send(client, "save")
        saved = snapshot(client)
        send(client, "reset", 731)
        assert snapshot(client)["context"] != saved["context"]
        load, result = send(client, "load")
        restored = snapshot(client)
        assert restored["world"] == saved["world"]
        assert restored["context"] not in (saved["context"], load["context"])
        assert client.post("/api/command", json=envelope(saved, "start")).status_code == 409

    with local_server(db) as client:
        restored_again = snapshot(client)
        assert restored_again["world"] == saved["world"]
        assert restored_again["context"] == restored["context"]
        assert client.post("/api/command", json=load).json() == result
        assert snapshot(client)["revision"] == restored_again["revision"]


def test_lost_command_responses_and_interrupted_upload(tmp_path):
    with local_server(tmp_path / "world.sqlite3") as client:
        start = snapshot(client)
        cmd = envelope(start, "speed", 2)
        origin = str(client.base_url).rstrip("/")
        body = json.dumps(cmd).encode()
        headers = {"Origin": origin, "Content-Type": "application/json", "Content-Length": str(len(body))}

        # Close the device's connection before the complete request body arrives.
        connection = http.client.HTTPConnection("127.0.0.1", client.base_url.port, timeout=4)
        connection.request("POST", "/api/command", body=body[:len(body) // 2], headers=headers)
        connection.close()
        assert client.get(f"/api/command/{cmd['id']}").status_code == 404
        assert snapshot(client)["revision"] == start["revision"]

        # Deliver the *same* command. Observe commitment on the other device,
        # then discard the original socket without reading its HTTP response.
        connection = http.client.HTTPConnection("127.0.0.1", client.base_url.port, timeout=4)
        try:
            connection.request("POST", "/api/command", body=body, headers=headers)
            until = time.monotonic() + 3
            while True:
                receipt = client.get(f"/api/command/{cmd['id']}")
                if receipt.is_success:
                    break
                assert receipt.status_code == 404 and time.monotonic() < until
                time.sleep(0.01)
        finally:
            connection.close()
        assert client.post("/api/command", json=cmd).json() == receipt.json()
        assert snapshot(client)["revision"] == start["revision"] + 1
        assert snapshot(client)["speed"] == 2
        assert client.post("/api/command", json={**cmd, "value": 4}).status_code == 409


def test_stream_reconnect_after_other_device_changes_world(tmp_path):
    with local_server(tmp_path / "world.sqlite3") as client:
        origin = str(client.base_url).rstrip("/")
        stream = origin.replace("http://", "ws://") + "/api/stream?view=full"
        with connect(stream, origin=origin, proxy=None) as device:
            initial = json.loads(device.recv(timeout=4))
            send(client, "speed", 2)
            changed = json.loads(device.recv(timeout=4))
            assert changed["speed"] == 2 and changed["sequence"] > initial["sequence"]
        send(client, "reset", 190)
        send(client, "save")
        current = snapshot(client)
        with connect(stream, origin=origin, proxy=None) as device:
            recovered = json.loads(device.recv(timeout=4))
            assert recovered == current
            assert recovered["context"] != initial["context"]
            send(client, "start")
            until = time.monotonic() + 4
            previous = recovered
            while previous["world"] == recovered["world"]:
                event = json.loads(device.recv(timeout=4))
                assert event["context"] == recovered["context"]
                assert event["sequence"] > previous["sequence"]
                previous = event
                assert time.monotonic() < until
        outsider = "https://unrelated.example"
        rejected = client.post("/api/command", json=envelope(snapshot(client), "pause"),
                               headers={"Origin": outsider})
        assert rejected.status_code in (401, 403)
        with pytest.raises(InvalidStatus):
            with connect(stream, origin=outsider, proxy=None):
                pass


class Forward(socketserver.BaseRequestHandler):
    """A layer-four route; TLS and device authentication terminate at the app."""
    def handle(self):
        with socket.create_connection(self.server.upstream, timeout=5) as target:
            peers = (target, self.request)
            while True:
                ready, _, _ = select.select(peers, (), (), 5)
                for source in ready:
                    chunk = source.recv(65536)
                    if not chunk:
                        return
                    (self.request if source is target else target).sendall(chunk)


@contextmanager
def network_route(sock, mode):
    if mode == "lan":
        yield sock.getsockname()
        return
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Forward) as route:
        route.daemon_threads = True
        route.upstream = sock.getsockname()
        worker = threading.Thread(target=route.serve_forever, daemon=True)
        worker.start()
        try:
            yield route.server_address
        finally:
            route.shutdown()
            worker.join(5)


def admin(directory, *arguments):
    command = [sys.executable, "-m", "backend.run", "--data", str(directory), *arguments]
    return subprocess.check_output(command, encoding="utf-8", timeout=6,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"}).strip()


@pytest.mark.parametrize("mode", ["lan", "remote"])
def test_network_pairing_and_stream_over_verified_tls(tmp_path, mode):
    host = os.environ.get("R0_TEST_LAN_IP", "127.0.0.1") if mode == "lan" else "127.0.0.1"
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-days", "1", "-subj", "/CN=R0-loopback-test",
                    "-addext", f"subjectAltName=IP:{host}",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    trust = ssl.create_default_context(cafile=str(cert))
    with listener(host) as sock, network_route(sock, mode) as (address, port):
        origin = f"https://{address}:{port}"
        stream = f"wss://{address}:{port}/api/stream?view=full"
        pairing = secrets.token_urlsafe(18)
        app = create_app(tmp_path / "scenario.sqlite", mode=mode, origins=(origin,), pairing_code=pairing)
        with serve(app, sock, ssl_certfile=str(cert), ssl_keyfile=str(key)):
            with httpx.Client(base_url=origin, verify=trust, headers={"Origin": origin}, trust_env=False) as device:
                assert device.get("/api/state").status_code in (401, 403)
                async def denied_stream():
                    with pytest.raises(InvalidStatus) as denied:
                        async with async_connect(stream, ssl=trust, origin=origin, proxy=None):
                            pass
                    assert denied.value.response.status_code == 403

                asyncio.run(denied_stream())
                assert device.post("/api/pair", json={"code": "incorrect-code"}).status_code in (401, 403)
                response = device.post("/api/pair", json={"code": pairing})
                response.raise_for_status()
                cookie = response.headers["set-cookie"].lower()
                assert "httponly" in cookie and "secure" in cookie
                first = snapshot(device)
                with httpx.Client(base_url=origin, verify=trust, trust_env=False) as stranger:
                    assert stranger.post("/api/pair", headers={"Origin": origin},
                                         json={"code": pairing}).status_code in (401, 403)
                first_id = admin(tmp_path, "--list-devices")
                assert len(first_id.splitlines()) == 1
                retired_code = admin(tmp_path, "--pair-new").split()[-1]
                next_code = admin(tmp_path, "--pair-new").split()[-1]
                with httpx.Client(base_url=origin, verify=trust, headers={"Origin": origin}, trust_env=False) as other:
                    assert other.post("/api/pair", json={"code": retired_code}).status_code == 403
                    other.post("/api/pair", json={"code": next_code}).raise_for_status()
                    assert snapshot(other) == first
                    devices = admin(tmp_path, "--list-devices").splitlines()
                    assert len(devices) == 2
                    other_id, = set(devices) - {first_id}
                    admin(tmp_path, "--revoke-device", other_id)
                    assert other.get("/api/state").status_code == 401
                    assert admin(tmp_path, "--list-devices") == first_id
                cookie_header = device.build_request("GET", "/api/state").headers["Cookie"]

                async def paired_then_revoked():
                    async with async_connect(stream, origin=origin, ssl=trust, proxy=None,
                                             additional_headers={"Cookie": cookie_header}) as ws:
                        assert json.loads(await asyncio.wait_for(ws.recv(), 4)) == first
                        send(device, "speed", 4)
                        assert json.loads(await asyncio.wait_for(ws.recv(), 4))["speed"] == 4
                        admin(tmp_path, "--revoke-all")
                        assert device.get("/api/state").status_code == 401
                        async with asyncio.timeout(4):
                            with pytest.raises(ConnectionClosedError) as closed:
                                while True:
                                    await ws.recv()
                            assert closed.value.rcvd.code == 1008

                asyncio.run(paired_then_revoked())

def test_cli_defaults_to_loopback_and_rejects_unauthenticated_network_start(tmp_path):
    with listener() as candidate:
        port = candidate.getsockname()[1]
    args = [sys.executable, "-m", "backend.run", "--port", str(port), "--data", str(tmp_path)]
    with subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            with httpx.Client(trust_env=False, timeout=0.5) as client:
                url = f"http://127.0.0.1:{port}/api/state"
                until = time.monotonic() + 5
                while True:
                    try:
                        response = client.get(url)
                        response.raise_for_status()
                        break
                    except httpx.ConnectError:
                        assert process.poll() is None and time.monotonic() < until
                        time.sleep(0.04)
                if lan_ip := os.environ.get("R0_TEST_LAN_IP"):
                    with pytest.raises(httpx.ConnectError):
                        client.get(f"http://{lan_ip}:{port}/api/state")
                # A second port must not start a second clock on the same world.
                with listener() as second:
                    second_port = second.getsockname()[1]
                duplicate = [sys.executable, "-m", "backend.run", "--port", str(second_port),
                             "--data", str(tmp_path)]
                assert subprocess.run(duplicate, capture_output=True, timeout=5).returncode != 0
                assert client.get(url).is_success
        finally:
            process.terminate()
    for mode in ("lan", "remote"):
        attempt = subprocess.run([*args, "--mode", mode], capture_output=True, timeout=5)
        assert attempt.returncode != 0
