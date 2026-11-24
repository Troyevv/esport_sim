"""Persistent, single-worker portrait import; simulation and browser stay responsive."""

from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4
from threading import Event, Lock, Thread

from .portrait_processing import PortraitProcessor, Unsuitable, VERSION
from .portrait_sources import discover, fetch, Unavailable


def identity(pid, player):
    return hashlib.sha256(
        json.dumps(
            [pid, player["name"].casefold(), player.get("realName") or ""],
            ensure_ascii=False,
        ).encode()
    ).hexdigest()


def people(pack):
    teams = {}
    for lineup in sorted(pack["rosters"].values(), key=lambda r: r["date"]):
        for pid in lineup["players"]:
            teams[pid] = pack["teams"][lineup["team"]]["name"]
    records = []
    for pid, p in pack["players"].items():
        if p.get("appearance"):
            continue
        records.append(
            dict(
                pid=pid,
                identity=identity(pid, p),
                name=p["name"],
                realName=p.get("realName"),
                team=teams.get(pid, ""),
                rating=(p.get("performance") or {}).get("rating", 0),
            )
        )
    return sorted(records, key=lambda x: (not x["realName"], -x["rating"], x["pid"]))


class PortraitLibrary:
    def __init__(
        self, path: Path, search=discover, download=fetch, processor=PortraitProcessor
    ):
        self.path = path
        self.search, self.download, self.processor = search, download, processor
        self.lock = Lock()
        self.stop = Event()
        self.thread = None
        with closing(self.connection()) as db:
            db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS job(id INTEGER PRIMARY KEY CHECK(id=1), pack TEXT, rev INTEGER, mode TEXT, state TEXT, message TEXT, token TEXT);
            CREATE TABLE IF NOT EXISTS task(seq INTEGER PRIMARY KEY, identity TEXT, person TEXT, state TEXT, attempts INTEGER DEFAULT 0, message TEXT DEFAULT '');
            CREATE TABLE IF NOT EXISTS asset(digest TEXT PRIMARY KEY, bytes BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS portrait(identity TEXT PRIMARY KEY, version TEXT, digest TEXT REFERENCES asset, credit TEXT);
            CREATE TABLE IF NOT EXISTS raw(asset_key TEXT PRIMARY KEY, bytes BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS rejected(identity TEXT, asset_key TEXT, version TEXT, reason TEXT, PRIMARY KEY(identity,asset_key,version));
            """)

    def connection(self):
        return sqlite3.connect(self.path, timeout=12, isolation_level=None)

    def resume(self):
        with self.lock:
            with closing(self.connection()) as db:
                if not db.execute("SELECT 1 FROM job WHERE state='running'").fetchone():
                    return
            if self.thread and self.thread.is_alive():
                return
            self.stop.clear()
            self.thread = Thread(target=self.work, name="scene-portraits", daemon=True)
            self.thread.start()

    def close(self):
        self.stop.set()
        thread = self.thread
        if thread:
            thread.join(timeout=16)

    def start(self, pack, mode):
        if mode not in ("pilot", "all", "retry"):
            raise ValueError("Неизвестный режим импорта")
        with closing(self.connection()) as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT pack,rev,state FROM job").fetchone()
            if previous and previous[2] == "running":
                raise ValueError("Импорт уже идёт")
            if mode == "retry":
                if not previous or previous[:2] != (pack["id"], pack["revision"]):
                    raise ValueError("Для этого среза нет очереди")
                db.execute(
                    "DELETE FROM rejected WHERE identity IN (SELECT identity FROM task WHERE state!='done')"
                )
                db.execute(
                    "UPDATE task SET state='queued',message='',attempts=0 WHERE state!='done'"
                )
                db.execute(
                    "UPDATE job SET state='running',message='',token=?", (uuid4().hex,)
                )
            else:
                db.execute("DELETE FROM task")
                tasks = people(pack)
                if mode == "pilot":
                    tasks = tasks[:3]
                db.executemany(
                    "INSERT INTO task(seq,identity,person,state) VALUES(?,?,?,'queued')",
                    [
                        (i, p["identity"], json.dumps(p, ensure_ascii=False))
                        for i, p in enumerate(tasks)
                    ],
                )
                db.execute(
                    "INSERT OR REPLACE INTO job VALUES(1,?,?,?,'running','',?)",
                    (pack["id"], pack["revision"], mode, uuid4().hex),
                )
            db.commit()
        self.resume()
        return self.status()

    def status(self):
        with closing(self.connection()) as db:
            job = db.execute("SELECT pack,rev,mode,state,message FROM job").fetchone()
            if not job:
                return dict(state="idle", counts={}, recent=[])
            recent = db.execute(
                "SELECT person,state,message FROM task WHERE state!='queued' ORDER BY seq DESC LIMIT 5"
            )
            return dict(
                zip(("pack", "revision", "mode", "state", "message"), job),
                counts=dict(
                    db.execute("SELECT state,count(*) FROM task GROUP BY state")
                ),
                recent=[
                    dict(name=json.loads(p)["name"], state=s, reason=m)
                    for p, s, m in recent
                ],
            )

    def pause(self):
        with closing(self.connection()) as db:
            db.execute(
                "UPDATE job SET state='paused',message='Приостановлено' WHERE state='running'"
            )
        return self.status()

    def index(self, records):
        with closing(self.connection()) as db:
            lookup = {
                key: (digest, json.loads(credit))
                for key, digest, credit in db.execute(
                    "SELECT identity,digest,credit FROM portrait WHERE version=?",
                    (VERSION,),
                )
            }
        result = {}
        for pid, p in records.items():
            item = lookup.get(identity(pid, p))
            if item:
                result[pid] = dict(item[1], image="/api/portraits/image/" + item[0])
        return result

    def image(self, digest):
        with closing(self.connection()) as db:
            hit = db.execute(
                "SELECT bytes FROM asset WHERE digest=?", (digest,)
            ).fetchone()
            return hit[0] if hit else None

    def work(self):
        engine = None
        try:
            with closing(self.connection()) as db:
                while not self.stop.is_set():
                    job = db.execute("SELECT state,token FROM job").fetchone()
                    if not job or job[0] != "running":
                        break
                    row = db.execute(
                        "SELECT seq,identity,person,attempts FROM task WHERE state='queued' ORDER BY seq LIMIT 1"
                    ).fetchone()
                    if not row:
                        db.execute("UPDATE job SET state='finished',message=''")
                        break

                    def active():
                        return (
                            not self.stop.is_set()
                            and db.execute(
                                "SELECT 1 FROM job WHERE state='running' AND token=?",
                                (job[1],),
                            ).fetchone()
                        )

                    seq, key, metadata, attempts = row
                    person = json.loads(metadata)
                    if db.execute(
                        "SELECT 1 FROM portrait WHERE identity=? AND version=?",
                        (key, VERSION),
                    ).fetchone():
                        db.execute(
                            "UPDATE task SET state='done',message='Из локального кеша' WHERE seq=?",
                            (seq,),
                        )
                        continue
                    reason = (
                        "Источник не подтвердил студийный снимок, личность и лицензию"
                    )
                    try:

                        def delay(seconds):
                            for _ in range(int(seconds)):
                                if not active() or self.stop.wait(1):
                                    raise InterruptedError()

                        def read(url, hosts, size):
                            if not active():
                                raise InterruptedError()
                            return fetch(url, hosts, size)

                        candidates = (
                            discover(person, read, delay)
                            if self.search is discover
                            else self.search(person)
                        )
                        for candidate in candidates:
                            if not active():
                                break
                            ck = candidate["assetKey"]
                            rejected = db.execute(
                                "SELECT reason FROM rejected WHERE identity=? AND asset_key=? AND version=?",
                                (key, ck, VERSION),
                            ).fetchone()
                            if rejected:
                                reason = rejected[0]
                                continue
                            hit = db.execute(
                                "SELECT bytes FROM raw WHERE asset_key=?", (ck,)
                            ).fetchone()
                            try:
                                raw = (
                                    hit[0]
                                    if hit
                                    else self.download(
                                        candidate["image"],
                                        set(candidate["hosts"]),
                                        8_000_000,
                                    )
                                )
                                if not raw:
                                    raise Unsuitable("Снимок удалён источником")
                                if not hit:
                                    db.execute(
                                        "INSERT OR IGNORE INTO raw VALUES(?,?)",
                                        (ck, raw),
                                    )
                                if engine is None:
                                    engine = self.processor()
                                head = engine.render(raw)
                            except (Unsuitable, ValueError) as exc:
                                reason = str(exc)
                                db.execute(
                                    "INSERT OR REPLACE INTO rejected VALUES(?,?,?,?)",
                                    (key, ck, VERSION, reason),
                                )
                                continue
                            digest = hashlib.sha256(head).hexdigest()
                            credit = {
                                k: candidate[k] for k in ("author", "source", "license")
                            }
                            credit["changes"] = (
                                "Удалены фон и одежда, выровнены голова и шея · "
                                + VERSION
                            )
                            db.execute("BEGIN IMMEDIATE")
                            if not active():
                                db.rollback()
                                break
                            db.execute(
                                "INSERT OR IGNORE INTO asset VALUES(?,?)",
                                (digest, head),
                            )
                            db.execute(
                                "INSERT OR REPLACE INTO portrait VALUES(?,?,?,?)",
                                (
                                    key,
                                    VERSION,
                                    digest,
                                    json.dumps(credit, ensure_ascii=False),
                                ),
                            )
                            db.execute(
                                "UPDATE task SET state='done',message='Портрет сохранён' WHERE seq=?",
                                (seq,),
                            )
                            db.commit()
                            break
                        else:
                            if active():
                                db.execute(
                                    "UPDATE task SET state='skipped',message=? WHERE seq=?",
                                    (reason, seq),
                                )
                    except InterruptedError:
                        continue
                    except Unavailable as exc:
                        if not active():
                            continue
                        db.execute(
                            "UPDATE task SET attempts=attempts+1,message=? WHERE seq=?",
                            (str(exc), seq),
                        )
                        if attempts >= 1:
                            db.execute(
                                "UPDATE job SET state='blocked',message=?", (str(exc),)
                            )
                            break
                        db.execute(
                            "UPDATE job SET message=?",
                            (str(exc) + " · повтор после паузы",),
                        )
                        for _ in range(max(1, exc.delay)):
                            if not active() or self.stop.wait(1):
                                break
                    if self.stop.wait(0.2):
                        break
        except Exception as exc:
            with closing(self.connection()) as db:
                db.execute(
                    "UPDATE job SET state='blocked',message=?", (str(exc)[:240],)
                )
        finally:
            if engine:
                engine.close()
            with self.lock:
                self.thread = None
            if not self.stop.is_set():
                self.resume()
