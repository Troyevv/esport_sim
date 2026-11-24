"""One authoritative scenario, its manual snapshot and durable command receipts."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from . import engine


class Conflict(ValueError):
    pass


def validate_snapshot(state):
    world = state.get("world", {})
    if (state.get("version"), world.get("version"), world.get("map_version")) != (
        1,
        engine.VERSION,
        engine.MAP["version"],
    ):
        raise Conflict("Несовместимая версия снимка, ядра или геометрии")


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS active (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS slot (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS receipt (id TEXT PRIMARY KEY, request TEXT NOT NULL, result TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS device (digest TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS invitation (digest TEXT PRIMARY KEY, expires INTEGER NOT NULL);
        """)
        existing = self.db.execute("SELECT body FROM active WHERE id=1").fetchone()
        if existing:
            try:
                validate_snapshot(json.loads(existing[0]))
            except (ValueError, TypeError, AttributeError):
                self.db.close()
                raise
        else:
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
        self.db.execute(
            "INSERT OR REPLACE INTO active VALUES(1,?)", (json.dumps(state),)
        )

    def tick(self):
        with self.transaction():
            state = self.read()
            if not state["running"]:
                return False
            for _ in range(state["speed"]):
                engine.advance(state["world"])
            state["sequence"] += 1
            self.write(state)
        return True

    def snapshot(self, view):
        state = self.read()
        state["world"] = engine.project(state["world"], view)
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
            if kind in ("start", "pause"):
                state["running"] = kind == "start"
            elif kind == "speed":
                if value not in (1, 2, 4, 8):
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
                saved = json.loads(row[0])
                validate_snapshot(saved)
                state.update(saved)
                state["context"] = str(uuid4())
            elif kind == "reset":
                if value is None or not 0 <= value <= 2147483647:
                    raise ValueError("Seed должен быть целым числом от 0 до 2147483647")
                state.update(
                    world=engine.initial(value), running=False, context=str(uuid4())
                )
            state["revision"] += 1
            state["sequence"] += 1
            self.write(state)
            result = {key: state[key] for key in ("context", "revision")}
            self.db.execute(
                "INSERT INTO receipt VALUES(?,?,?)",
                (command["id"], request, json.dumps(result)),
            )
            return result
