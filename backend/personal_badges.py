"""A private, per-installation artwork library. Scene packages contain no personal files."""

import base64
import hashlib
import re
import sqlite3
from contextlib import closing
from io import BytesIO
from pathlib import Path
from threading import Event, Lock, Thread
from urllib.parse import urlsplit
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from PIL import Image

from . import club_art
from .portrait_sources import Unavailable, fetch

LIMIT = 12 * 1024 * 1024
MEDIA_HOSTS = {"raw.githubusercontent.com", "vectorseek.com", "logotyp.us"}


sources = club_art.personal_sources


def request_file(url):
    if urlsplit(url).hostname not in MEDIA_HOSTS:
        raise ValueError("Неизвестный источник файла")
    return fetch(url, {urlsplit(url).hostname}, LIMIT)


def graphic(raw, url):
    if not raw or len(raw) > LIMIT:
        raise ValueError("Файл отсутствует или слишком велик")
    if url.endswith(".zip"):
        with ZipFile(BytesIO(raw)) as archive:
            pngs = [
                e
                for e in archive.infolist()
                if e.filename.lower().endswith(".png")
                and not e.filename.startswith("__MACOSX/")
                and not Path(e.filename).name.startswith(".")
            ]
            if len(archive.infolist()) > 100 or not pngs:
                raise ValueError("В пакете издателя нет PNG")
            # Retain the primary transparent mark before backgrounds or preview images.
            for entry in sorted(pngs, key=lambda e: (len(e.filename), e.filename)):
                if 0 < entry.file_size <= LIMIT:
                    try:
                        return graphic(archive.read(entry), "logo.png")
                    except ValueError:
                        continue
            raise ValueError("В пакете нет подходящего прозрачного PNG")
    if url.endswith(".svg"):
        if len(raw) > 1024 * 1024 or re.search(
            rb"<!DOCTYPE|<!ENTITY|<\?xml-stylesheet", raw, re.IGNORECASE
        ):
            raise ValueError("Неподдерживаемая структура SVG")
        svg = ElementTree.fromstring(raw)
        ns = "{http://www.w3.org/2000/svg}"
        tags = {
            "svg",
            "g",
            "defs",
            "clipPath",
            "mask",
            "path",
            "polygon",
            "polyline",
            "line",
            "circle",
            "ellipse",
            "rect",
            "title",
            "desc",
            "linearGradient",
            "radialGradient",
            "stop",
        }
        if svg.tag != ns + "svg" or not any(
            e.tag in {ns + t for t in ("path", "polygon", "circle", "rect")}
            for e in svg.iter()
        ):
            raise ValueError("В файле нет знака SVG")
        for node in svg.iter():
            if node.tag not in {ns + t for t in tags}:
                raise ValueError("Неподдерживаемый элемент SVG")
            for k, v in node.attrib.items():
                if (
                    k.lower().startswith("on")
                    or k.lower().endswith("href")
                    or k.lower() == "style"
                    and re.search(r"@|\\|/\*", v)
                    or re.search(
                        r"javascript:|data:|https?:|url\(\s*(?!#[\w.-]+\))",
                        v,
                        re.IGNORECASE,
                    )
                ):
                    raise ValueError("Внешнее содержимое SVG")
        # Rasterize vetted geometry only; the browser never receives third-party SVG.
        from resvg_py import svg_to_bytes

        png = svg_to_bytes(
            svg_string=ElementTree.tostring(svg, encoding="unicode"),
            width=512,
            height=512,
            skip_system_fonts=True,
        )
        return graphic(png, "logo.png")
    with Image.open(BytesIO(raw)) as img:
        if (
            img.format != "PNG"
            or img.width * img.height > 12_000_000
            or max(img.size) > 5000
            or img.is_animated
        ):
            raise ValueError("Неподходящий формат или размер PNG")
        rgba = img.convert("RGBA")
        low, high = rgba.getchannel("A").getextrema()
        if low != 0 or high < 160:
            raise ValueError("Нужен прозрачный фон и видимый знак")
        bounds = rgba.getbbox()
        rgba = rgba.crop(bounds)
        rgba.thumbnail((256, 256), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (280, 280))
        canvas.alpha_composite(
            rgba, ((280 - rgba.width) // 2, (280 - rgba.height) // 2)
        )
        data = BytesIO()
        canvas.save(data, format="PNG", optimize=True)
        return data.getvalue(), "image/png"


def stock_name(pack_id, row):
    name = club_art.ALIASES.get(row["name"], row["name"])
    info = club_art.catalog().get(name)
    if not info or info["kind"] != "game":
        return None
    original = row.get("logo")
    if original is None:
        return (
            name
            if pack_id in club_art.ARCHIVES or pack_id.startswith("scene-202611")
            else None
        )
    if (
        not isinstance(original, dict)
        or original.get("author") != "EsportSim"
        or original.get("source") != info["source"]
    ):
        return None
    value = original.get("image", "")
    if not value.startswith("data:image/png;base64,"):
        return None
    if (
        hashlib.sha256(base64.b64decode(value.partition(",")[2])).hexdigest()
        == info["sha256"]
    ):
        return name
    return None


class PersonalBadges:
    def __init__(self, path, download=request_file):
        self.path = Path(path)
        self.download = download
        self.lock = Lock()
        self.stop = Event()
        self.thread = None
        with closing(self.connect()) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS setting(id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT, running INTEGER);
                INSERT OR IGNORE INTO setting VALUES(1,'off',0);
                CREATE TABLE IF NOT EXISTS image(club TEXT PRIMARY KEY, basis TEXT, url TEXT, source TEXT, digest TEXT, mime TEXT, content BLOB);
                CREATE INDEX IF NOT EXISTS image_digest ON image(digest);
                CREATE TABLE IF NOT EXISTS failure(club TEXT PRIMARY KEY, detail TEXT);
            """)

    def connect(self):
        return sqlite3.connect(self.path, timeout=15, isolation_level=None)

    def status(self):
        with closing(self.connect()) as db:
            mode, running = db.execute("SELECT mode,running FROM setting").fetchone()
            ready = (
                db.execute(
                    "SELECT COUNT(*) FROM image WHERE basis='personal' OR ?='copy'",
                    (mode,),
                ).fetchone()[0]
                if mode != "off"
                else 0
            )
            errors = dict(db.execute("SELECT club,detail FROM failure ORDER BY club"))
        return {
            "mode": mode,
            "running": bool(running),
            "ready": ready,
            "errors": errors,
            "explicit": sum("personal" in s for s in sources().values()),
            "available": len(sources()),
        }

    def install_offline(self, payload):
        """Install a private .eslogos archive only after verifying every pinned source."""
        known = {}
        for name, options in sources().items():
            entry = options.get("copy")
            if entry:
                known.setdefault(entry["sha256"], []).append((name, entry))
        with self.lock, closing(self.connect()) as db:
            if self.thread and self.thread.is_alive():
                raise ValueError("Дождитесь окончания текущей загрузки")
            try:
                with ZipFile(BytesIO(payload)) as archive:
                    entries = archive.infolist()
                    if (
                        not 0 < len(entries) <= len(known)
                        or sum(e.file_size for e in entries) > 40 * 1024 * 1024
                    ):
                        raise ValueError("Неподдерживаемый объём личного пакета")
                    seen = set()
                    db.execute("BEGIN IMMEDIATE")
                    for entry in entries:
                        digest = entry.filename.removesuffix(".png")
                        if (
                            digest not in known
                            or digest in seen
                            or entry.filename != digest + ".png"
                            or not 0 < entry.file_size <= LIMIT
                        ):
                            raise ValueError("Неизвестный или повторный файл эмблемы")
                        seen.add(digest)
                        raw = archive.read(entry)
                        if hashlib.sha256(raw).hexdigest() != digest:
                            raise ValueError("Неверная контрольная сумма оригинала")
                        blob, mime = graphic(raw, entry.filename)
                        normalized = hashlib.sha256(blob).hexdigest()
                        for name, source in known[digest]:
                            db.execute(
                                "INSERT INTO image VALUES(?,?,?,?,?,?,?) ON CONFLICT(club) DO UPDATE SET "
                                "basis=excluded.basis,url=excluded.url,source=excluded.source,"
                                "digest=excluded.digest,mime=excluded.mime,content=excluded.content WHERE image.basis!='personal'",
                                (
                                    name,
                                    "copy",
                                    source["url"],
                                    source["page"],
                                    normalized,
                                    mime,
                                    blob,
                                ),
                            )
                            db.execute("DELETE FROM failure WHERE club=?", (name,))
                    db.execute("UPDATE setting SET mode='copy', running=0")
                    db.commit()
            except (RuntimeError, OSError, BadZipFile) as exc:
                raise ValueError("Повреждённый файл личного пакета") from exc
        return self.status()

    def start(self, mode):
        if mode not in ("personal", "copy", "off"):
            raise ValueError("Неизвестный режим личного пакета")
        with self.lock, closing(self.connect()) as db:
            if self.thread and self.thread.is_alive():
                if mode != "off":
                    return self.status()
                self.stop.set()
            db.execute(
                "UPDATE setting SET mode=?, running=?", (mode, int(mode != "off"))
            )
            if mode != "off":
                db.execute("DELETE FROM failure")
                self.launch(mode)
        return self.status()

    def launch(self, mode):
        self.stop.clear()
        self.thread = Thread(target=self.run, args=(mode,), daemon=True)
        self.thread.start()

    def resume(self):
        with self.lock, closing(self.connect()) as db:
            mode, running = db.execute("SELECT mode,running FROM setting").fetchone()
            if (
                running
                and mode != "off"
                and not (self.thread and self.thread.is_alive())
            ):
                self.launch(mode)

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=15)

    def run(self, mode):
        blocked = {}
        with closing(self.connect()) as db:
            try:
                for name, options in sorted(
                    sources().items(),
                    key=lambda it: (it[0] not in {"Fnatic", "FURIA Esports"}, it[0]),
                ):
                    if self.stop.is_set():
                        return
                    allowed = [
                        (k, options[k])
                        for k in ("personal", "copy")
                        if k in options and (mode == "copy" or k == "personal")
                    ]
                    if not allowed:
                        continue
                    cached = db.execute(
                        "SELECT basis,url FROM image WHERE club=?", (name,)
                    ).fetchone()
                    if any(cached == (basis, entry["url"]) for basis, entry in allowed):
                        continue
                    reasons = []
                    for basis, entry in allowed:
                        if self.stop.is_set():
                            return
                        url = entry["url"]
                        host = urlsplit(url).hostname
                        if host in blocked:
                            reasons.append(blocked[host])
                            continue
                        try:
                            raw = self.download(url)
                            if (
                                entry.get("sha256")
                                and hashlib.sha256(raw).hexdigest() != entry["sha256"]
                            ):
                                raise ValueError(
                                    "Контрольная сумма источника изменилась"
                                )
                            blob, mime = graphic(raw, url)
                            digest = hashlib.sha256(blob).hexdigest()
                            db.execute(
                                "INSERT OR REPLACE INTO image VALUES(?,?,?,?,?,?,?)",
                                (name, basis, url, entry["page"], digest, mime, blob),
                            )
                            break
                        except Unavailable as error:
                            blocked[host] = str(error)
                            reasons.append(str(error))
                        except (
                            RuntimeError,
                            OSError,
                            ValueError,
                            BadZipFile,
                            ElementTree.ParseError,
                            Image.DecompressionBombError,
                        ) as error:
                            reasons.append(str(error))
                    else:
                        db.execute(
                            "INSERT OR REPLACE INTO failure VALUES(?,?)",
                            (name, " · ".join(reasons)[:360]),
                        )
            finally:
                if not self.stop.is_set():
                    db.execute("UPDATE setting SET running=0")

    def index(self, pack):
        with closing(self.connect()) as db:
            mode = db.execute("SELECT mode FROM setting").fetchone()[0]
            if mode == "off":
                return {}
            ready = {
                club: (source, digest, basis)
                for club, source, digest, basis in db.execute(
                    "SELECT club,source,digest,basis FROM image WHERE basis='personal' OR ?='copy'",
                    (mode,),
                )
            }
        result = {}
        for group in ("teams", "organizations"):
            for key, row in pack[group].items():
                candidate = club_art.ALIASES.get(row["name"], row["name"])
                if candidate not in ready or not stock_name(pack["id"], row):
                    continue
                source, digest, basis = ready[candidate]
                result[group + "/" + key] = {
                    "image": "/api/database/personal-image/" + digest,
                    "author": candidate,
                    "source": source,
                    "license": "Личное использование"
                    if basis == "personal"
                    else "Личная копия",
                    "changes": "Оригинальная эмблема · личная библиотека на этом ПК.",
                }
        return result

    def image(self, digest):
        with closing(self.connect()) as db:
            return db.execute(
                "SELECT content,mime FROM image,setting WHERE digest=? AND mode!='off' AND (basis='personal' OR mode='copy') LIMIT 1",
                (digest,),
            ).fetchone()
