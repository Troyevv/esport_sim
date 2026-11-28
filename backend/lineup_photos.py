"""Install the approved full-length club portraits in the private portrait library."""
from contextlib import closing
from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import BadZipFile, ZipFile

MAX_ARCHIVE = 80 * 1024 * 1024


@lru_cache(1)
def catalog():
    return json.loads(Path(__file__).with_name("data").joinpath("lineup-photo-sources.json").read_text("utf-8"))


def install(library, content):
    if len(content) > MAX_ARCHIVE:
        raise ValueError("Размер ZIP превышает 80 МиБ")
    assets = []
    try:
        with ZipFile(BytesIO(content)) as archive:
            for row in catalog().values():
                names = (row["file"], "players/"+row["file"], "r571-prototype/public/assets/players/"+row["file"])
                entries = [v for v in archive.infolist() if v.filename in names]
                if len(entries) != 1 or entries[0].file_size != row["size"]:
                    raise ValueError("В пакете отсутствует утверждённое изображение "+row["file"])
                blob = archive.read(entries[0])
                if sha256(blob).hexdigest() != row["sha256"]:
                    raise ValueError("Изображение отличается от утверждённого файла "+row["file"])
                assets.append((row["sha256"],blob))
    except (BadZipFile, RuntimeError, NotImplementedError) as exc:
        raise ValueError("Не удалось прочитать архив портретов") from exc
    with closing(library.connection()) as db, db:
        db.execute("BEGIN IMMEDIATE")
        db.executemany("INSERT OR IGNORE INTO asset(digest,bytes) VALUES(?,?)",assets)
    return {"installed":len(assets)}


def index(library):
    if library is None:
        return {}
    rows = catalog()
    with closing(library.connection()) as db:
        ids = [r["sha256"] for r in rows.values()]
        stored = {r[0] for r in db.execute("SELECT digest FROM asset WHERE digest IN ("+
                                           ",".join("?" for _ in ids)+")",ids)}
    return {pid:dict(team=row["team"],url="/api/portraits/image/"+row["sha256"]) for pid,row in rows.items() if row["sha256"] in stored}


def export(library):
    output = BytesIO()
    with closing(library.connection()) as db, ZipFile(output, "w") as archive:
        for row in catalog().values():
            stored = db.execute("SELECT bytes FROM asset WHERE digest=?", (row["sha256"],)).fetchone()
            if not stored:
                raise ValueError("Личный пакет ещё не установлен полностью")
            archive.writestr(row["file"], stored[0])
    return output.getvalue()
