"""Install curated, transparent head layers from the owner's offline portrait pack."""

import json
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from PIL import Image

from .portrait_library import identity
from .portrait_processing import VERSION
from .portrait_sources import previously_rejected

MAX_PACK = 96 * 1024 * 1024
CATALOG = Path(__file__).with_name("data") / "personal-portrait-sources.json"


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["portraits"]


def install(library, pack, content):
    if len(content) > MAX_PACK:
        raise ValueError("Личный пакет превышает 96 МиБ")
    known = {
        entry["sha256"]: (pid, entry)
        for pid, entry in catalog().items()
        if pid in pack["players"]
        and entry["name"].casefold() == pack["players"][pid]["name"].casefold()
    }
    with closing(library.connection()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM job WHERE state='running'").fetchone():
            raise ValueError("Сначала приостановите поиск студийных портретов")
        seen = set()
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if (
                    not members
                    or len(members) > len(known)
                    or sum(m.file_size for m in members) > MAX_PACK
                ):
                    raise ValueError("Пакет не соответствует выбранной базе игроков")
                for member in members:
                    digest = member.filename.removesuffix(".png")
                    if (
                        digest not in known
                        or member.filename != digest + ".png"
                        or digest in seen
                        or not 0 < member.file_size <= 2 * 1024 * 1024
                    ):
                        raise ValueError(
                            "Неизвестный, повторный или слишком большой слой внешности"
                        )
                    raw = archive.read(member)
                    pid, entry = known[digest]
                    if sha256(raw).hexdigest() != digest or previously_rejected(
                        entry["source"]
                    ):
                        raise ValueError(
                            "Проверка происхождения или контрольной суммы не пройдена"
                        )
                    with Image.open(BytesIO(raw)) as im:
                        if (
                            im.format != "PNG"
                            or im.mode != "RGBA"
                            or im.size != (480, 560)
                        ):
                            raise ValueError("Неверный формат слоя внешности")
                        im.verify()
                    player = pack["players"][pid]
                    credit = {
                        "author": entry["publisher"],
                        "source": entry["source"],
                        "license": "Личная копия",
                        "changes": "Студийный портрет · отделены волосы, голова и шея. Форма зависит от команды.",
                    }
                    db.execute("INSERT OR IGNORE INTO asset VALUES(?,?)", (digest, raw))
                    db.execute(
                        "INSERT OR REPLACE INTO portrait VALUES(?,?,?,?)",
                        (
                            identity(pid, player),
                            VERSION,
                            digest,
                            json.dumps(credit, ensure_ascii=False),
                        ),
                    )
                    seen.add(digest)
        except (BadZipFile, OSError, RuntimeError) as exc:
            raise ValueError("Личный пакет повреждён") from exc
        db.commit()
    return {"installed": len(seen)}
