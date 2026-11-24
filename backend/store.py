"""One authoritative scenario, its manual snapshot and durable command receipts."""

import gzip
import json
import sqlite3
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from . import database, checkpoints, engine, match, tactic_library
from .match_rules import LEGACY_VERSION


class Conflict(ValueError):
    pass


def validate_snapshot(state):
    world = state.get("world", {})
    model = (world.get("version"), world.get("map_version"), world.get("rules"))
    supported = (
        (engine.VERSION, engine.MAP["version"], None),
        (2, match.MAP["version"], match.VERSION),
        (2, match.MAP["version"], LEGACY_VERSION),
    )
    if state.get("version") != 1 or model not in supported:
        raise Conflict("Несовместимая версия снимка, ядра или геометрии")
    if world.get("version") == 2:
        version = world.get("checkpointVersion", 1)
        if type(version) is not int or version not in (1, 2, 3, checkpoints.VERSION):
            raise Conflict(f"Неподдерживаемая версия сохранения BO1: {version}")
        if (version == checkpoints.VERSION) != (world["rules"] == match.VERSION):
            raise Conflict("Несовместимая пара версий правил и контрольной точки")


class Store:
    def __init__(self, path: Path):
        self.motion = deque(maxlen=6)  # Recent committed poses, never part of a save.
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS round_log (digest TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS slot (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS data_pack (id TEXT, revision INTEGER, title TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(id,revision));
            CREATE TABLE IF NOT EXISTS tactic (id TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT,
                PRIMARY KEY(id, revision));
            CREATE TABLE IF NOT EXISTS tactic_mastery (id TEXT, revision INTEGER, familiarity INTEGER NOT NULL,
                PRIMARY KEY(id, revision));
            CREATE TABLE IF NOT EXISTS receipt (id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device (digest TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS device_info (digest TEXT PRIMARY KEY, name TEXT NOT NULL, paired_at INTEGER NOT NULL);
            CREATE TRIGGER IF NOT EXISTS remove_device_info AFTER DELETE ON device
                BEGIN DELETE FROM device_info WHERE digest=OLD.digest; END;
            CREATE TABLE IF NOT EXISTS invitation (digest TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        """)
        try:
            with self.transaction():
                if not self.db.execute(
                    "SELECT 1 FROM data_pack WHERE id=? AND revision=1",
                    ("austin-registration",),
                ).fetchone():
                    database.install(self.db, database.STARTER.read_bytes())
                if not self.db.execute(
                    "SELECT 1 FROM data_pack WHERE id=? AND revision=1",
                    ("scene-202611",),
                ).fetchone():
                    database.install(
                        self.db, gzip.decompress(database.RELEASE.read_bytes())
                    )
                for table in ("active", "slot"):
                    row = self.db.execute(
                        f"SELECT body FROM {table} WHERE id=1"
                    ).fetchone()
                    if row:
                        self.restore_checkpoint(table, row[0])
                    elif table == "active":
                        self.write(
                            dict(
                                version=1,
                                context=str(uuid4()),
                                revision=0,
                                sequence=0,
                                running=False,
                                speed=1,
                                world=engine.initial(42),
                                hasSave=False,
                            )
                        )
        except BaseException:
            self.db.close()
            raise

    def restore_checkpoint(self, table, body):
        """Caller owns the transaction. Keep original JSON and immutable log blocks."""
        label = "активный сценарий" if table == "active" else "ручное сохранение"
        try:
            state = json.loads(body)
            validate_snapshot(state)
            world = state["world"]
            if (
                world["version"] == 2
                and world.get("checkpointVersion", 1) < checkpoints.VERSION
            ):
                if world.get("checkpointVersion", 1) == 1:
                    checkpoints.upgrade_match(self.db, world)
                match.migrate_legacy(world)
                world["checkpointVersion"] = checkpoints.VERSION
                self.db.execute("""CREATE TABLE IF NOT EXISTS checkpoint_backup (
                    source TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(source, body))""")
                self.db.execute(
                    "INSERT OR IGNORE INTO checkpoint_backup VALUES(?,?)", (table, body)
                )
                self.db.execute(
                    f"UPDATE {table} SET body=? WHERE id=1", (json.dumps(state),)
                )
            if world["version"] == 2:
                checkpoints.validate_current(world)
                match.validate_bindings(world)
            return state
        except (ValueError, TypeError, AttributeError, KeyError, IndexError) as exc:
            raise Conflict(f"Не удалось прочитать {label}: {exc}") from exc

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def read(self):
        return json.loads(
            self.db.execute("SELECT body FROM active WHERE id=1").fetchone()[0]
        )

    def write(self, state):
        # Completed rounds are immutable and shared by the active game and save slot.
        # Only their hashes travel with the checkpoint, including after a load/fork.
        world = state["world"]
        if world.get("archive"):
            for events in world["archive"]:
                world.setdefault("logs", []).append(
                    checkpoints.put_round(self.db, events)
                )
            world["archive"] = []
        self.db.execute(
            "INSERT OR REPLACE INTO active VALUES(1,?)", (json.dumps(state),)
        )

    def tick(self):
        with self.transaction():
            state = self.read()
            if not state["running"]:
                return False
            world = state["world"]
            start = world["tick"]
            samples = []
            is_match = world["version"] == 2
            step = match.advance if is_match else engine.advance
            for _ in range(state["speed"]):
                if state["speed"] <= 8:
                    samples.append(engine.motion_sample(world))
                step(world)
                if is_match and world["phase"] in ("finished", "timeout"):
                    state["running"] = False
                    break
            state["sequence"] += 1
            self.write(state)
        self.motion.append((state["context"], start, world["tick"], samples))
        return True

    def snapshot(self, view, previous=None):
        state = self.read()
        model = match if state["world"]["version"] == 2 else engine
        state["world"] = model.project(state["world"], view)
        world = state["world"]
        if self.motion and state["running"]:
            context, start, end, samples = self.motion[-1]
            if context != state["context"] or end != world["tick"]:
                return state
            if previous and previous[0] == context and previous[1] < start:
                # Backfill a slow subscriber only across contiguous batches of
                # the same playback speed. Otherwise send a fresh projection.
                batch_size = end - start
                for prior_context, left, right, batch in reversed(
                    list(self.motion)[:-1]
                ):
                    if (
                        prior_context != context
                        or right != start
                        or right - left != batch_size
                    ):
                        break
                    start, samples = left, batch + samples
                    if start <= previous[1]:
                        break
            if len(samples) > 1:
                # A side only receives tracks that were continuously observable.
                tracks = {}
                for agent in world["agents"]:
                    ident = agent["id"]
                    if all(
                        view == "full" or view in sample[ident][1] for sample in samples
                    ):
                        tracks[ident] = [sample[ident][0] for sample in samples]
                world["motion"] = {"startTick": start, "tracks": tracks}
        return state

    def result(self, command_id):
        row = self.db.execute(
            "SELECT result FROM receipt WHERE id=?", (command_id,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def apply(self, command):
        request = json.dumps(command, sort_keys=True)
        with self.transaction():
            previous = self.db.execute(
                "SELECT request,result FROM receipt WHERE id=?", (command["id"],)
            ).fetchone()
            if previous:
                if request != previous[0]:
                    raise Conflict("Идентификатор уже использован для другой команды")
                return json.loads(previous[1])
            state = self.read()
            if (command["context"], command["revision"]) != (
                state["context"],
                state["revision"],
            ):
                raise Conflict(
                    "Другое устройство уже изменило состояние. Проверьте данные и повторите действие."
                )
            kind, value = command["kind"], command.get("value")
            if kind in ("tactic-save", "tactic-delete", "tactic-assign"):
                try:
                    if kind == "tactic-assign":
                        if state["world"]["version"] != 2:
                            raise ValueError("Сначала откройте матч BO1")
                        match.assign(
                            state["world"], tactic_library.resolve(self.db, value)
                        )
                    else:
                        tactic_library.change(self.db, kind, value)
                        state["libraryRevision"] = state.get("libraryRevision", 0) + 1
                except tactic_library.StalePlan as err:
                    raise Conflict(str(err)) from err
            elif kind in ("start", "pause"):
                if kind == "start" and state["world"].get("phase") in (
                    "finished",
                    "timeout",
                ):
                    raise ValueError("Просмотр остановлен на границе матча")
                state["running"] = kind == "start"
                if state["running"] and state["world"]["version"] == 2:
                    state["world"]["started"] = True
            elif kind == "speed":
                if value not in (
                    (1, 2, 4, 8, 128)
                    if state["world"]["version"] == 2
                    else (1, 2, 4, 8)
                ):
                    raise ValueError("Недопустимая скорость")
                state["speed"] = value
            elif kind == "save":
                saved = {
                    key: state[key] for key in ("world", "speed", "running", "version")
                }
                self.db.execute(
                    "INSERT OR REPLACE INTO slot VALUES(1,?)", (json.dumps(saved),)
                )
                state["hasSave"] = True
            elif kind == "load":
                row = self.db.execute("SELECT body FROM slot").fetchone()
                if not row:
                    raise Conflict("Нет сохранения")
                saved = self.restore_checkpoint("slot", row[0])
                state.update(saved)
                state["context"] = str(uuid4())
            elif kind in ("timeout", "call", "resume"):
                if state["world"]["version"] != 2:
                    raise ValueError("Сначала откройте матч BO1")
                match.command(state["world"], kind, value)
                if state["world"]["phase"] == "timeout":
                    state["running"] = False
                elif kind == "resume":
                    state["running"] = True
            elif kind == "database-match":
                if not isinstance(value, dict) or set(value) != {
                    "id",
                    "revision",
                    "rosters",
                    "seed",
                }:
                    raise ValueError("Укажите редакцию пакета, составы и seed")
                seed = value["seed"]
                database.require(
                    type(seed) is int and 0 <= seed <= 2147483647, "Некорректный seed"
                )
                database.valid_id(value["id"])
                database.require(
                    type(value["revision"]) is int, "Некорректная редакция"
                )
                pack = database.get(self.db, value["id"], value["revision"])
                domain = database.match_input(pack, value["rosters"])
                state.update(
                    world=match.initial(seed, domain, value["rosters"]),
                    running=False,
                    speed=1,
                    context=str(uuid4()),
                )
            elif kind in ("reset", "match"):
                if type(value) is not int or not 0 <= value <= 2147483647:
                    raise ValueError("Seed должен быть целым числом от 0 до 2147483647")
                state.update(
                    world=(match if kind == "match" else engine).initial(value),
                    running=False,
                    speed=min(8, state["speed"]) if kind == "reset" else 1,
                    context=str(uuid4()),
                )
            else:
                raise ValueError("Неизвестная команда")
            state["revision"] += 1
            state["sequence"] += 1
            self.write(state)
            result = {key: state[key] for key in ("context", "revision")}
            self.db.execute(
                "INSERT INTO receipt VALUES(?,?,?)",
                (command["id"], request, json.dumps(result)),
            )
            return result
