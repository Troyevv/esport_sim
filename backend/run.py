"""Launch one home server. Network modes require trusted TLS and an explicit origin."""

import argparse
import ipaddress
import os
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlsplit

import uvicorn

from .server import create_app
from .paths import migrate_legacy, windows_data_dir
from .host import issue_code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["local", "lan", "remote"], default="local")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--origin", action="append", default=[])
    parser.add_argument("--cert")
    parser.add_argument("--key")
    parser.add_argument("--data", type=Path)
    admin = parser.add_mutually_exclusive_group()
    admin.add_argument("--revoke-all", action="store_true")
    admin.add_argument("--list-devices", action="store_true")
    admin.add_argument("--revoke-device", metavar="ID")
    admin.add_argument("--pair-new", action="store_true")
    args = parser.parse_args()
    if args.data is None:
        args.data = windows_data_dir() if os.name == "nt" else Path("runtime-data")
        if os.name == "nt":
            migrate_legacy(Path("runtime-data/scenario.sqlite"), args.data / "scenario.sqlite")
    args.data.mkdir(parents=True, exist_ok=True)
    db = args.data / "scenario.sqlite"
    if args.revoke_all or args.list_devices or args.revoke_device or args.pair_new:
        if not db.is_file():
            parser.error("Сначала запустите сервер с этим каталогом данных")
        with sqlite3.connect(db) as conn:
            if args.revoke_all:
                conn.execute("DELETE FROM device")
                conn.execute("DELETE FROM invitation")
                print("Доступ подключённых устройств отозван.")
            elif args.list_devices:
                for (device_id,) in conn.execute(
                    "SELECT substr(digest,1,16) FROM device ORDER BY rowid"
                ):
                    print(device_id)
            elif args.revoke_device:
                count = conn.execute(
                    "DELETE FROM device WHERE substr(digest,1,16)=?",
                    (args.revoke_device,),
                ).rowcount
                if not count:
                    parser.error("Устройство с таким ID отсутствует")
                print("Доступ устройства отозван.")
            else:
                code = secrets.token_urlsafe(20)
                issue_code(conn, code)
                print(f"Код устройства: {code}")
        return
    code = None
    if args.mode == "local":
        if args.host != "localhost" and not ipaddress.ip_address(args.host).is_loopback:
            parser.error("Для сетевого доступа укажите --mode lan или remote")
        if args.cert or args.key or args.origin:
            parser.error("Параметры TLS и origin используются в сетевом режиме")
    else:
        if not args.cert or not args.key or not args.origin:
            parser.error("Сетевой режим требует --cert, --key и --origin")
        for origin in args.origin:
            url = urlsplit(origin)
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or origin != "https://" + url.netloc
            ):
                parser.error("--origin должен содержать точный HTTPS origin без пути")
        code = secrets.token_urlsafe(20)
        print(f"Код устройства: {code}", flush=True)
    uvicorn.run(
        create_app(db, args.mode, args.origin, code),
        host=args.host,
        port=args.port,
        ssl_certfile=args.cert,
        ssl_keyfile=args.key,
        proxy_headers=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
