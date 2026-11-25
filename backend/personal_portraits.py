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
from .portrait_sources import RETIRED_LAYERS, previously_rejected

MAX_PACK = 96 * 1024 * 1024
CATALOG = Path(__file__).with_name("data") / "personal-portrait-sources.json"


@lru_cache(maxsize=1)
def catalog():
    return json.loads(CATALOG.read_text(encoding="utf-8"))["portraits"]


@lru_cache(maxsize=1)
def kits():
    return json.loads(CATALOG.with_name("team-kits.json").read_text(encoding="utf-8"))


def installed_kits(library):
    with closing(library.connection()) as db:
        present = {row[0] for row in db.execute("SELECT digest FROM asset")}
    return {
        tid: {k: e[k] for k in ("sha256", "rig", "observed", "source")}
        for tid, e in kits().items()
        if e["sha256"] in present
    }


def install(library, pack, content):
    if len(content) > MAX_PACK:
        raise ValueError("Личный пакет превышает 96 МиБ")
    known = {
        entry["sha256"]: (pid, entry)
        for pid, entry in catalog().items()
        if pid in pack["players"]
        and entry["name"].casefold() == pack["players"][pid]["name"].casefold()
    }
    approved_kits = {
        "kits/" + e["sha256"] + ".png": e["sha256"]
        for tid, e in kits().items()
        if tid in pack.get("teams", {})
    }
    with closing(library.connection()) as db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM job WHERE state='running'").fetchone():
            raise ValueError("Сначала приостановите поиск студийных портретов")
        seen = set()
        cloth = set()
        try:
            with ZipFile(BytesIO(content)) as archive:
                members = archive.infolist()
                if (
                    not members
                    or len(members)
                    > len(known) + len(RETIRED_LAYERS) + len(approved_kits)
                    or sum(m.file_size for m in members) > MAX_PACK
                ):
                    raise ValueError("Пакет не соответствует выбранной базе игроков")
                for member in members:
                    if member.filename in approved_kits:
                        digest = approved_kits[member.filename]
                        if (
                            digest in cloth
                            or not 0 < member.file_size <= 2 * 1024 * 1024
                        ):
                            raise ValueError(
                                "Повторный или некорректный комплект формы"
                            )
                        raw = archive.read(member)
                        if sha256(raw).hexdigest() != digest:
                            raise ValueError("Повреждён комплект формы")
                        db.execute(
                            "INSERT OR IGNORE INTO asset VALUES(?,?)", (digest, raw)
                        )
                        cloth.add(digest)
                        continue
                    digest = member.filename.removesuffix(".png")
                    if (
                        (digest not in known and digest not in RETIRED_LAYERS)
                        or member.filename != digest + ".png"
                        or digest in seen
                        or not 0 < member.file_size <= 2 * 1024 * 1024
                    ):
                        raise ValueError(
                            "Неизвестный, повторный или слишком большой слой внешности"
                        )
                    raw = archive.read(member)
                    if digest in RETIRED_LAYERS and sha256(raw).hexdigest() == digest:
                        seen.add(digest)
                        continue
                    if digest not in known:
                        raise ValueError("Неверная контрольная сумма архивного слоя")
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
                    if "nativeWidth" in entry:
                        credit["nativeWidth"] = entry["nativeWidth"]
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
    return {
        "installed": len(seen - RETIRED_LAYERS),
        **({"kits": len(cloth)} if cloth else {}),
    }
