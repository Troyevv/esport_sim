"""One authoritative scenario, its manual snapshot and durable command receipts."""

import gzip
import json
import sqlite3
from collections import deque
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from . import cs2_maps, database, checkpoints, engine, match, tactic_library
from . import career, career_store, series, staff
from .match_rules import LEGACY_VERSION, PREVIOUS_VERSION, SCOREBOT_VERSION
from . import match_inventory, match_score


class Conflict(ValueError):
    pass


def validate_snapshot(state):
    world = state.get("world", {})
    if "series" in world:
        series.validate(world)
        if world.get("version") == 3:
            if state.get("version") != 1 or state.get("running"):
                raise Conflict("Неверный снимок вето")
            return
    model = (world.get("version"), world.get("map_version"), world.get("rules"))
    supported = (
        (engine.VERSION, engine.MAP["version"], None),
        (2, match.MAP["version"], match.VERSION),
        (2, match.MAP["version"], LEGACY_VERSION),
        (2, match.MAP["version"], PREVIOUS_VERSION),
        (2, match.MAP["version"], SCOREBOT_VERSION),
    )
    if world.get("mapId") is not None:
        if (model[:2] != (2, cs2_maps.BUILD) or model[2] not in cs2_maps.SUPPORTED_RULES) or world.get("checkpointVersion")!=7 or world["mapId"] not in cs2_maps.NAMES or state.get("version")!=1:
            raise Conflict("Несовместимая версия сохранения реальной карты")
        return
    if state.get("version") != 1 or model not in supported:
        raise Conflict("Несовместимая версия снимка, ядра или геометрии")
    if world.get("version") == 2:
        version = world.get("checkpointVersion", 1)
        if type(version) is not int or version not in (
            1,
            2,
            3,
            4,
            5,
            checkpoints.VERSION,
        ):
            raise Conflict(f"Неподдерживаемая версия сохранения BO1: {version}")
        rules = {
            4: PREVIOUS_VERSION,
            5: SCOREBOT_VERSION,
            checkpoints.VERSION: match.VERSION,
        }
        if world["rules"] != rules.get(version, LEGACY_VERSION):
            raise Conflict("Несовместимая пара версий правил и контрольной точки")


from .personal_badges import PersonalBadges
from .portrait_library import PortraitLibrary


class Store:
    def __init__(self, path: Path):
        self.badges = PersonalBadges(Path(path).with_suffix(".club-originals.sqlite"))
        self.portraits = PortraitLibrary(Path(path).with_suffix(".portraits.sqlite"))
        self.motion = deque(maxlen=6)  # Recent committed poses, never part of a save.
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        migrate_profile = career_store.prepare_migration(self.db, path)
        self.careers = career_store.CareerStore(self)
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
                if migrate_profile:
                    career_store.install(self.db)
                if not self.db.execute(
                    "SELECT 1 FROM data_pack WHERE id=? AND revision=1",
                    ("austin-registration",),
                ).fetchone():
                    database.install(self.db, database.STARTER.read_bytes())
                if not self.db.execute(
                    "SELECT 1 FROM data_pack WHERE id=? AND revision=1",
                    (database.RELEASE_ID,),
                ).fetchone():
                    database.install(
                        self.db, gzip.decompress(database.RELEASE.read_bytes())
                    )
                    database.migrate_club_links(self.db)
                database.install_staff_edition(self.db)
                self.careers.upgrade_slots()
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

    def upgrade_checkpoint(self, state, source, body):
        """Validate first, then preserve the exact old payload in the caller's transaction."""
        validate_snapshot(state)
        if state.get("career") and state["career"].get("version") != career.VERSION:
            raise ValueError("Несовместимая версия карьеры")
        c = state.get("career")
        migrate_office = c is not None and "office" not in c
        if migrate_office:
            c["office"] = staff.office()
        elif c:
            database.require(c["office"].get("version") == 1, "Неизвестная версия назначений")
        game = state["world"]
        if game["version"] != 2:
            if migrate_office:
                self.backup_checkpoint(source, body)
            return migrate_office
        if "series" in game:
            checkpoints.validate_round_logs(self.db, game)
        old_version = game.get("checkpointVersion", 1)
        if old_version < checkpoints.VERSION:
            if old_version == 1:
                checkpoints.upgrade_match(self.db, game)
            if old_version < 4:
                match.migrate_legacy(game)
            else:
                game["rulesTransition"] = dict(
                    previous=game["rules"], tick=game["tick"], lastEvent=game["serial"]
                )
            if old_version < 5:
                match_score.upgrade(game)
            match_inventory.upgrade(game)
            game.update(rules=match.VERSION, checkpointVersion=checkpoints.VERSION)
        checkpoints.validate_current(game)
        match.validate_bindings(game)
        if old_version >= checkpoints.VERSION and not migrate_office:
            return False
        self.backup_checkpoint(source, body)
        return True

    def backup_checkpoint(self, source, body):
        self.db.execute("""CREATE TABLE IF NOT EXISTS checkpoint_backup (
            source TEXT NOT NULL, body TEXT NOT NULL, UNIQUE(source, body))""")
        self.db.execute(
            "INSERT OR IGNORE INTO checkpoint_backup VALUES(?,?)", (source, body)
        )

    def restore_checkpoint(self, table, body):
        label = "активный сценарий" if table == "active" else "ручное сохранение"
        try:
            state = json.loads(body)
            changed = self.upgrade_checkpoint(state, table, body)
            c = state.get("career")
            if c and c.get("circuit") and state["world"]["version"] == 1:
                from .competitions import resolve_slots
                changed = resolve_slots(c) or changed
            if changed:
                self.db.execute(
                    f"UPDATE {table} SET body=? WHERE id=1", (json.dumps(state, ensure_ascii=False, separators=(",", ":")),)
                )
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
            "INSERT OR REPLACE INTO active VALUES(1,?)", (json.dumps(state, ensure_ascii=False, separators=(",", ":")),)
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
            map_ended = world.get("phase") == "finished"
            if map_ended and "series" in world:
                series.finish_map(world)
                state["revision"] += 1
            finished = state.get("career") and map_ended and world.get("series", {}).get("stage", "finished") == "finished"
            if map_ended and not state.get("career") and world.get("series", {}).get("winner"):
                report = series.result(world)
                state.setdefault("exhibitions", []).append(dict(
                    source=world["domain"]["source"], date=world["series"]["date"],
                    teams=report["teams"], **series.scouting_record(report)))
            if finished:
                self.careers.record(state["career"], career.result(world))
                state["careerRevision"] += 1
                state["revision"] += 1
            state["sequence"] += 1
            self.write(state)
            if finished:
                self.careers.save(state, "auto")
        self.motion.append((state["context"], start, world["tick"], samples))
        return True

    def snapshot(self, view, previous=None):
        state = self.read()
        state.pop("exhibitions", None)
        c = state.pop("career", None)
        if c:
            state["careerId"] = c["id"]
            if c["progress"]:
                state["calendarProgress"] = dict(c["progress"], date=c["date"], runId=c["progress"].get("runId", state["context"]))
        model = match if state["world"]["version"] == 2 else engine
        game = state["world"]
        if game["version"] == 3:
            state["world"] = dict(seed=game["seed"], tick=0, time=0, map=engine.MAP, view=view, agents=[], events=[])
        else:
            state["world"] = model.project(game, view)
        if "series" in game:
            state["world"]["series"] = series.project(game, view)
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
            progress = (state.get("career") or {}).get("progress")
            value = command.get("value")
            same_run_pause = (
                command["kind"] == "career-pause" and progress and isinstance(value, dict)
                and value.get("runId") == progress.get("runId", state["context"])
            )
            if command["context"] != state["context"] or (
                command["revision"] != state["revision"] and not same_run_pause
            ):
                raise Conflict(
                    "Другое устройство уже изменило состояние. Проверьте данные и повторите действие."
                )
            kind, value = command["kind"], command.get("value")
            c = state.get("career")
            if state["world"].get("series",{}).get("spectator") and kind in ("timeout","call","resume","tactic-assign","series-veto"):
                raise ValueError("В режиме наблюдения решения принимают команды")
            if kind == "career-exhibition":
                # Switching away and validating the editor selection are one command.
                self.careers.change(state, "career-lab", None)
                kind, c = "database-match", None
            if kind.startswith("career-") or (c and kind in ("save", "load")):
                self.careers.change(state, kind, value)
            elif c and (
                kind in ("reset", "match", "database-match")
                or (
                    state["world"]["version"] == 1
                    and kind not in ("tactic-save", "tactic-delete")
                )
            ):
                raise ValueError("Действие недоступно в текущей карьере")
            elif kind in ("tactic-save", "tactic-delete", "tactic-assign"):
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
            elif kind in ("series-veto", "series-next"):
                game = state["world"]
                database.require("series" in game, "Серия не открыта")
                if kind == "series-veto":
                    series.command(game, value)
                else:
                    following = series.next_map(game)
                    if game["version"] == 2:
                        logs = [*game.get("logs", []), checkpoints.put_round(self.db, game["events"])]
                        following["series"].setdefault("roundLogs", []).append(logs)
                    state.update(world=following, context=str(uuid4()), running=False)
            elif kind in ("start", "pause"):
                database.require(state["world"]["version"] != 3, "Сначала завершите вето")
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
                saved["exhibitions"] = state.get("exhibitions", [])
                self.db.execute(
                    "INSERT OR REPLACE INTO slot VALUES(1,?)", (json.dumps(saved),)
                )
                state["hasSave"] = True
            elif kind == "load":
                row = self.db.execute("SELECT body FROM slot").fetchone()
                if not row:
                    raise Conflict("Нет сохранения")
                saved = self.restore_checkpoint("slot", row[0])
                state.pop("exhibitions", None)
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
                if not isinstance(value, dict) or set(value).difference({"map", "bestOf"}) != {
                    "id",
                    "revision",
                    "rosters",
                    "seed",
                }:
                    raise ValueError("Укажите редакцию пакета, составы и seed")
                database.require(
                    not ("bestOf" in value and "map" in value),
                    "Выберите одну карту или формат вето",
                )
                seed = value["seed"]
                database.require(
                    type(seed) is int and 0 <= seed <= 2147483647, "Некорректный seed"
                )
                database.valid_id(value["id"])
                database.require(
                    type(value["revision"]) is int, "Некорректная редакция"
                )
                pack = database.get(self.db, value["id"], value["revision"])
                domain = database.match_input(
                    pack, value["rosters"], self.badges.index(pack)
                )
                cached = self.portraits.index(
                    {pid: pack["players"][pid] for pid in domain["players"]}
                )
                for pid, portrait in cached.items():
                    if not pack["players"][pid].get("appearance"):
                        domain["players"][pid]["visual"]["head"] = portrait["image"]
                history = [
                    e
                    for e in state.get("exhibitions", [])
                    if e["source"] == domain["source"]
                ]
                game = (
                    series.initial(
                        seed,
                        value["bestOf"],
                        domain,
                        value["rosters"],
                        history=history,
                        today=pack["asOf"],
                    )
                    if "bestOf" in value
                    else match.initial(
                        seed, domain, value["rosters"], map_id=value.get("map", "depo")
                    )
                )
                state.update(
                    world=game,
                    running=False,
                    speed=1,
                    context=str(uuid4()),
                )
            elif kind in ("reset", "match"):
                options = value if isinstance(value, dict) and kind == "match" else {}
                if options:
                    database.require(
                        set(options) in ({"map", "seed"}, {"bestOf", "seed"}),
                        "Укажите карту или формат матча",
                    )
                    value = options["seed"]
                if type(value) is not int or not 0 <= value <= 2147483647:
                    raise ValueError("Seed должен быть целым числом от 0 до 2147483647")
                if kind == "reset":
                    game = engine.initial(value)
                elif "bestOf" in options:
                    history = [
                        e
                        for e in state.get("exhibitions", [])
                        if e["source"]["id"] == "depo-exhibition"
                    ]
                    game = series.initial(value, options["bestOf"], history=history)
                else:
                    game = match.initial(value, map_id=options.get("map", "depo"))
                state.update(
                    world=game,
                    running=False,
                    speed=min(8, state["speed"]) if kind == "reset" else 1,
                    context=str(uuid4()),
                )
            else:
                raise ValueError("Неизвестная команда")
            if state.get("career") and kind in ("series-veto", "series-next"):
                state["careerRevision"] = state.get("careerRevision", 0) + 1
            state["revision"] += 1
            state["sequence"] += 1
            self.write(state)
            if state.get("career") and kind in (
                "series-veto",
                "series-next",
                "career-play",
                "career-finish",
                "career-advance",
            ):
                self.careers.save(state, "auto")
            result = {key: state[key] for key in ("context", "revision")}
            self.db.execute(
                "INSERT INTO receipt VALUES(?,?,?)",
                (command["id"], request, json.dumps(result)),
            )
            return result
