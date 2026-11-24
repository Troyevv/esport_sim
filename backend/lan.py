"""Explicit private-interface TLS listener for the existing single-player server."""
import asyncio
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
import psutil
import uvicorn


_PRIVATE_RANGES = tuple(ipaddress.ip_network(net) for net in
                        ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def lan_addresses():
    stats = psutil.net_if_stats()
    addresses = set()
    for interface, entries in psutil.net_if_addrs().items():
        if interface not in stats or not stats[interface].isup:
            continue
        for entry in entries:
            if entry.family == socket.AF_INET:
                address = ipaddress.IPv4Address(entry.address)
                if any(address in network for network in _PRIVATE_RANGES):
                    addresses.add(address)
    return [str(ip) for ip in sorted(addresses)]


def _write(path, data):
    """Publish complete files. Temporary files and private keys are owner-only."""
    fd, temp = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _pem_key(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def _name(label):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, label)])


def _certificate(name, issuer, key, issuer_key, validity_days):
    now = datetime.now(timezone.utc)
    return (x509.CertificateBuilder().subject_name(name).issuer_name(issuer)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(minutes=5)).not_valid_after(now + timedelta(days=validity_days))
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(issuer_key.public_key()), False))


class _Identity:
    def __init__(self, directory):
        self.directory = directory
        self.ca_file = directory / "esport-sim-ca.cer"
        self.server_chain = directory / "server.pem"

    def issue(self, address):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        authority = self.directory / "authority.pem"
        if authority.exists():
            pem = authority.read_bytes()
            issuer_key = serialization.load_pem_private_key(pem, password=None)
            issuer = x509.load_pem_x509_certificate(pem)
            if issuer.not_valid_after_utc < datetime.now(timezone.utc) + timedelta(days=91):
                raise ValueError("Срок доверия локального УЦ истекает. Требуется обновление УЦ на домашнем ПК и устройствах.")
        else:
            issuer_key = ec.generate_private_key(ec.SECP256R1())
            name = _name("esport_sim Home LAN CA")
            # Constrain signed TLS identities to private IPv4 networks and a reserved DNS suffix.
            names = [x509.IPAddress(network) for network in _PRIVATE_RANGES] + [x509.DNSName("esport-sim.invalid")]
            issuer = (_certificate(name, name, issuer_key, issuer_key, 3650)
                      .add_extension(x509.BasicConstraints(ca=True, path_length=0), True)
                      .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, None, None), True)
                      .add_extension(x509.NameConstraints(names, None), True)
                      .sign(issuer_key, hashes.SHA256()))
            _write(authority, _pem_key(issuer_key) + issuer.public_bytes(serialization.Encoding.PEM))
        _write(self.ca_file, issuer.public_bytes(serialization.Encoding.DER))
        server_key = ec.generate_private_key(ec.SECP256R1())
        leaf = (_certificate(_name("esport_sim Home LAN"), issuer.subject, server_key, issuer_key, 90)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), True)
                .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(address))]), False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), False)
                .add_extension(x509.KeyUsage(True, False, False, False, False, False, False, None, None), True)
                .sign(issuer_key, hashes.SHA256()))
        # OpenSSL accepts the protected key and leaf together. Only ca_file is public.
        _write(self.server_chain, leaf.public_bytes(serialization.Encoding.PEM) + _pem_key(server_key))


class _SecondaryServer(uvicorn.Server):
    def capture_signals(self):
        # Only the primary server handles process signals.
        return nullcontext()


class LanAccess:
    def __init__(self, data_dir: Path, app_factory, port=8767):
        self._settings = data_dir / "lan.json"
        self._identity = _Identity(data_dir / "lan-identity")
        self.ca_file = self._identity.ca_file
        self._factory = app_factory
        self._port = port
        self._lock = asyncio.Lock()
        self._server = None
        self._task = None
        self._renew = None
        self._address = None
        self._origin = None
        self._error = None

    def status(self):
        fingerprint = None
        error = self._error
        if self.ca_file.exists():
            try:
                cert = x509.load_der_x509_certificate(self.ca_file.read_bytes())
                fingerprint = cert.fingerprint(hashes.SHA256()).hex(":").upper()
            except (ValueError, OSError):
                error = error or "Не удалось прочитать сертификат домашнего сервера."
        return dict(enabled=self._server is not None, origin=self._origin, address=self._address,
                    addresses=lan_addresses(), fingerprint=fingerprint, error=error)

    async def _start(self, address):
        if address not in lan_addresses():
            raise ValueError("Выбранный локальный IPv4-адрес недоступен. Выберите адрес активной домашней сети.")
        if self._server is not None:
            if address == self._address:
                return
            raise ValueError("Сначала выключите доступ по текущему адресу.")
        sock = socket.socket()
        try:
            if os.name == "nt":
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((address, self._port))
            sock.listen()
            origin = f"https://{address}:{sock.getsockname()[1]}"
            self._identity.issue(address)
            application = self._factory(origin)

            async def while_enabled(scope, receive, send):
                # A slow TLS handshake can complete after the listening socket closes.
                # Only the current listener may pass requests into the shared world.
                if self._server is server and not server.should_exit:
                    await application(scope, receive, send)
                elif scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await send({"type": "http.response.start", "status": 503, "headers": []})
                    await send({"type": "http.response.body", "body": b""})

            server = _SecondaryServer(uvicorn.Config(while_enabled, lifespan="off", access_log=False,
                                      proxy_headers=False, ssl_certfile=str(self._identity.server_chain),
                                      timeout_graceful_shutdown=2, log_config=None))
            # Complete TLS validation before launching the listener task.
            server.config.load()
            task = asyncio.create_task(server.serve(sockets=[sock]))
            try:
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("Не удалось запустить сервер локальной сети.")
                    await asyncio.sleep(0.01)
            except BaseException:
                server.should_exit = True
                await task
                raise
        except BaseException:
            sock.close()
            raise
        self._address, self._origin = address, origin
        self._server, self._task = server, task
        self._renew = asyncio.create_task(self._renew_leaf(address, server))
        self._error = None

    async def _renew_leaf(self, address, server):
        delay = 60 * 86400
        while True:
            await asyncio.sleep(delay)
            try:
                self._identity.issue(address)
                server.config.ssl.load_cert_chain(str(self._identity.server_chain))
                self._error = None
                delay = 60 * 86400
            except (ValueError, OSError) as exc:
                self._error = str(exc)
                delay = 86400

    async def _stop(self):
        if self._server is None:
            return
        self._renew.cancel()
        await asyncio.gather(self._renew, return_exceptions=True)
        self._server.should_exit = True
        # Prevent new handshakes and drop active HTTP and WebSocket transports now.
        for listener in self._server.servers:
            listener.close()
        for protocol in list(self._server.server_state.connections):
            protocol.transport.abort()
        await self._task
        self._server = self._task = self._renew = None
        self._address = self._origin = None

    async def enable(self, address=None):
        async with self._lock:
            if address is None:
                addresses = lan_addresses()
                address = self._address or (addresses[0] if addresses else None)
            await self._start(address)
            try:
                _write(self._settings, json.dumps({"address": address}).encode())
            except OSError:
                await self._stop()
                raise
            return self.status()

    async def disable(self):
        async with self._lock:
            try:
                self._settings.unlink(missing_ok=True)
            finally:
                await self._stop()
            self._error = None
            return self.status()

    async def close(self):
        async with self._lock:
            await self._stop()

    async def restore(self):
        async with self._lock:
            if self._settings.is_file():
                try:
                    saved = json.loads(self._settings.read_bytes())
                    await self._start(saved["address"])
                except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                    self._error = str(exc)
