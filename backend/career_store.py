"""Career checkpoints share immutable database editions, round logs and match reports."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from uuid import uuid4

from . import career, checkpoints, cs2_maps, database, engine, match, world
from .database import require


def prepare_migration(db, path):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    require(version in (0, 1), f"Неизвестная версия профиля: {version}")
    if version:
        return False
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='active'").fetchone():
        backup = Path(str(path) + ".pre-r33.sqlite")
        if not backup.exists():
            tmp = backup.with_suffix(".tmp")
            copy = sqlite3.connect(tmp)
            try:
                db.backup(copy)
            finally:
                copy.close()
            os.replace(tmp, backup)
    return True


def install(db):
    # The caller migrates legacy active and manual snapshots in this transaction too.
    db.execute("""CREATE TABLE career_slot (
        career TEXT, slot TEXT, summary TEXT NOT NULL, body TEXT NOT NULL, digest TEXT NOT NULL,
        PRIMARY KEY(career,slot))""")
    db.execute(
        "CREATE TABLE career_report (digest TEXT PRIMARY KEY, body TEXT NOT NULL)"
    )
    db.execute("PRAGMA user_version=1")


def checksum(body):
    return hashlib.sha256(body.encode()).hexdigest()


def summary(c):
    return {k: c[k] for k in ("id", "character", "mode", "club", "scope", "date")}


class CareerStore:
    def __init__(self, store):
        self.store = store
        self.db = store.db
        self.cached = None

    def pack(self, source):
        if not self.cached or self.cached[0] != source:
            self.cached = (source.copy(), database.get(self.db, *source))
        return self.cached[1]

    def slots(self, cid=None):
        if cid:
            rows = self.db.execute(
                "SELECT slot,summary FROM career_slot WHERE career=? ORDER BY slot",
                (cid,),
            )
        else:
            rows = self.db.execute(
                "SELECT slot,summary FROM career_slot WHERE slot='auto' AND career!='lab' ORDER BY rowid DESC"
            )
        return [dict(slot=k, **json.loads(body)) for k, body in rows]

    def save(self, state, slot):
        c = state.get("career")
        cid = c["id"] if c else "lab"
        info = summary(c) if c else {}
        data = {
            k: state[k] for k in ("world", "running", "speed", "version", "hasSave")
        }
        data["career"] = c
        body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        # Retain the preceding known-good checkpoint when replacing a slot.
        old = self.db.execute(
            "SELECT summary,body,digest FROM career_slot WHERE career=? AND slot=?",
            (cid, slot),
        ).fetchone()
        digest = checksum(body)
        if old and old[2] != digest and checksum(old[1]) == old[2]:
            self.db.execute(
                "INSERT OR REPLACE INTO career_slot VALUES(?,?,?,?,?)",
                (cid, slot + ".bak", *old),
            )
        self.db.execute(
            "INSERT OR REPLACE INTO career_slot VALUES(?,?,?,?,?)",
            (cid, slot, json.dumps(info), body, digest),
        )

    def upgrade_slots(self):
        # Upgrade parked careers, manual slots and their backups in the same transaction as active.
        rows = self.db.execute(
            """SELECT career,slot,body,digest FROM career_slot
            WHERE CASE WHEN json_valid(body) THEN json_extract(body,'$.world.checkpointVersion') END IN (4,5)"""
        )
        for cid, slot, body, digest in rows:
            if checksum(body) != digest:
                # Keep damaged slots untouched. load() reports the digest failure and allows selecting .bak.
                continue
            saved = json.loads(body)
            if self.store.upgrade_checkpoint(saved, cid + "/" + slot, body):
                updated = json.dumps(saved, ensure_ascii=False, separators=(",", ":"))
                self.db.execute(
                    "UPDATE career_slot SET body=?,digest=? WHERE career=? AND slot=?",
                    (updated, checksum(updated), cid, slot),
                )

    def load(self, state, cid, slot):
        from .store import validate_snapshot

        row = self.db.execute(
            "SELECT body,digest FROM career_slot WHERE career=? AND slot=?", (cid, slot)
        ).fetchone()
        require(
            row and checksum(row[0]) == row[1], "Сохранение отсутствует или повреждено"
        )
        saved = json.loads(row[0])
        validate_snapshot(saved)
        game, c = saved["world"], saved["career"]
        if c:
            require(c["version"] == career.VERSION, "Несовместимая версия карьеры")
            require(c["id"] == cid, "Неверный идентификатор карьеры")
            self.pack(c["source"])
            for e in c["history"]:
                self.report(e["result"])
        if game["version"] == 2:
            checkpoints.validate_current(game)
            match.validate_bindings(game)
            for key in game.get("logs", []):
                log = self.db.execute(
                    "SELECT body FROM round_log WHERE digest=?", (key,)
                ).fetchone()
                require(log and checksum(log[0]) == key, "Повреждён журнал матча")
        state.update(saved, context=str(uuid4()))
        state["hasSave"] = (
            bool(
                self.db.execute(
                    "SELECT 1 FROM career_slot WHERE career=? AND slot='1'", (cid,)
                ).fetchone()
            )
            if c
            else saved["hasSave"]
        )

    def report(self, digest):
        row = self.db.execute(
            "SELECT body FROM career_report WHERE digest=?", (digest,)
        ).fetchone()
        require(row and checksum(row[0]) == digest, "Повреждён отчёт матча")
        return json.loads(row[0])

    def record(self, c, report):
        event = c["queue"][0]
        pack = self.pack(c["source"])
        expected = {
            pid: tid
            for tid in event["teams"]
            for pid in pack["rosters"][c["teams"][tid]]["players"]
        }
        points = {
            tid: sum(r["winnerTeamId"] == tid for r in report["rounds"])
            for tid in event["teams"]
        }
        require(
            event["kind"] == "match"
            and report["seed"] == event["seed"]
            and report.get("mapId") == event.get("mapId")
            and report["rules"] in ((cs2_maps.RULES, cs2_maps.PREVIOUS_RULES) if event.get("mapId") else (match.VERSION,))
            and report["map"] == (cs2_maps.BUILD if event.get("mapId") else match.MAP["version"])
            and len(report["stats"]) == len(expected)
            and {row["player"]: row["teamId"] for row in report["stats"]} == expected
            and set(report["teams"]) == set(points)
            and report["score"] == [points[t] for t in report["teams"]]
            and points == report["scoreByTeam"]
            and len(set(points.values())) == 2
            and report["winnerTeamId"] == max(points, key=points.get)
            and sum(points.values()) == len(report["rounds"]),
            "Результат не соответствует встрече календаря",
        )
        body = database.encode(report)
        digest = checksum(body)
        self.db.execute(
            "INSERT OR IGNORE INTO career_report VALUES(?,?)", (digest, body)
        )
        career.complete(c, digest, points, report["winnerTeamId"])

    def change(self, state, kind, value):
        c = state.get("career")
        value = {} if value is None else value
        require(isinstance(value, dict), "Ожидаются параметры карьеры")
        slot = value.get("slot", "1")
        require(
            isinstance(slot, str)
            and slot in ("1", "2", "3", "auto", "1.bak", "2.bak", "3.bak", "auto.bak"),
            "Неизвестный слот",
        )
        if kind == "career-create":
            database.valid_id(value.get("id"))
            require(type(value.get("revision")) is int, "Укажите редакцию базы")
            pack = self.pack([value["id"], value["revision"]])
            new = career.create(pack, value)
            self.save(state, "auto")
            state.update(
                career=new,
                world=engine.initial(0),
                running=False,
                speed=1,
                hasSave=False,
                context=str(uuid4()),
            )
            self.save(state, "auto")
        elif kind == "career-open":
            cid = value.get("career")
            require(isinstance(cid, str) and cid != "lab", "Выберите карьеру")
            if not c or c["id"] != cid:
                self.save(state, "auto")
                self.load(state, cid, value.get("slot", "auto"))
            elif "slot" in value:
                self.load(state, cid, slot)
        elif kind == "career-lab":
            if c:
                self.save(state, "auto")
                self.load(state, "lab", "auto")
        else:
            require(c, "Сначала выберите карьеру")
            if kind in ("career-save", "save"):
                require(slot in ("1", "2", "3"), "Выберите ручной слот")
                self.save(state, slot)
                state["hasSave"] |= slot == "1"
            elif kind in ("career-load", "load"):
                self.load(state, c["id"], slot)
            elif kind == "career-advance":
                require(state["world"]["version"] == 1, "Завершите активный матч")
                career.start_advance(c)
            elif kind == "career-play":
                e = c["queue"][0]
                require(
                    not c["progress"]
                    and c["date"] == e["date"]
                    and c["team"] in e["teams"]
                    and state["world"]["version"] == 1,
                    "Матч пока недоступен",
                )
                pack = self.pack(c["source"])
                state.update(
                    world=career.initial(
                        pack, c, e, self.store.badges.index(pack), self.store.portraits
                    ),
                    context=str(uuid4()),
                    running=False,
                    speed=1,
                )
            elif kind == "career-finish":
                require(state["world"].get("phase") == "finished", "Матч ещё идёт")
                state.update(
                    world=engine.initial(0),
                    running=False,
                    speed=1,
                    context=str(uuid4()),
                )
            else:
                raise ValueError("Неизвестная команда карьеры")
        state["careerRevision"] = state.get("careerRevision", 0) + 1

    def detail(self, state):
        c = state.get("career")
        menu = {i["id"]: i for i in self.slots()}
        if not c:
            return dict(careers=list(menu.values()), active=None)
        pack = self.pack(c["source"])
        own = c["team"]
        event = next(e for e in c["queue"] if own in e["teams"])
        domain, _ = career.match_domain(
            pack, c, event, self.store.badges.index(pack), self.store.portraits
        )
        members = []
        for m in world.lineup(domain, c["teams"][own]):
            pid = m["player"]
            player = pack["players"][pid]
            members.append(
                dict(
                    **world.player_report(domain, pid),
                    role=m["role"],
                    captain=m["captain"],
                    realName=player["realName"],
                    born=player["born"],
                    visual=domain["players"][pid]["visual"],
                    form=domain["players"][pid]["form"],
                    morale=domain["players"][pid]["morale"],
                    fatigue=domain["players"][pid]["fatigue"],
                )
            )
        menu[c["id"]] = summary(c)
        team = pack["teams"][own]
        org = pack["organizations"].get(team["organization"])
        info = dict(
            **summary(c),
            team=own,
            start=c["start"],
            source=pack["title"],
            edition=c["source"][1],
            region=team["region"],
            organization=org["name"] if org else None,
            visual=domain["teams"][own]["visual"],
            progress=c["progress"],
            error=c["error"],
            teams={tid: pack["teams"][tid]["name"] for tid in c["teams"]},
            regions=c["regions"],
            milestones=c["milestones"],
            queue=c["queue"],
            history=c["history"],
            roster=members,
            teamRating=world.team_rating(domain,c["teams"][own],next(
                (event.get("mapId","depo").removeprefix("de_") for event in c["queue"]
                 if event["kind"]=="match" and own in event["teams"]), "depo")) ,
            slots=self.slots(c["id"]),
        )
        return dict(careers=list(menu.values()), active=info)

    def work(self, state):
        """Return a detached input; the worker never touches the server connection."""
        c = state.get("career")
        if not c or not c["progress"]:
            return None
        e = c["queue"][0]
        token = (state["context"], c["id"], e["id"])
        game = (
            None if career.stops(c, e) else career.initial(self.pack(c["source"]), c, e)
        )
        return token, game

    def commit_work(self, token, report, error=None):
        with self.store.transaction():
            state = self.store.read()
            c = state.get("career")
            if (
                not c
                or not c["progress"]
                or token != (state["context"], c["id"], c["queue"][0]["id"])
            ):
                return False
            if error:
                c.update(progress=None, error=error)
            elif report is None:
                e = c["queue"][0]
                c.update(progress=None, date=e["date"])
                if e["kind"] == "review":
                    c["queue"].pop(0)
                    played = sum(
                        m["id"].split("-")[0] == e["id"].split("-")[0]
                        for m in reversed(c["history"])
                    )
                    c["milestones"].append(
                        dict(date=e["date"], title="Итоги недели", matches=played)
                    )
            else:
                self.record(c, report)
            state["sequence"] += 1
            state["revision"] += 1
            state["careerRevision"] += 1
            self.store.write(state)
            if not c["progress"]:
                self.save(state, "auto")
        return True
