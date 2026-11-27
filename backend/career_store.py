"""Career checkpoints share immutable database editions, round logs and match reports."""

from copy import deepcopy
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from time import monotonic
from uuid import uuid4

from . import scout_sources, scouting, training, training_center, attention, staff, career, competition_scene, competitions, registrations, checkpoints, database, engine, match, series, veto, world
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
            pack = database.get(self.db, *source[:2])
            if len(source) > 2:
                require(source == competition_scene.source(*source[:2]), "Неизвестная редакция составов турнира")
                pack = competition_scene.extend(pack)
            self.cached = (source.copy(), pack)
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
        if not c:
            data["exhibitions"] = state.get("exhibitions", [])
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
            WHERE CASE WHEN json_valid(body) THEN
                json_extract(body,'$.world.checkpointVersion') IN (4,5) OR
                (json_type(body,'$.career')='object' AND (json_type(body,'$.career.office') IS NULL OR json_type(body,'$.career.training') IS NULL OR json_type(body,'$.career.scouting') IS NULL))
            END"""
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
            require(c.get("training", {}).get("version") == 1, "Несовместимая версия подготовки")
            require(c.get("scouting", {}).get("version") == 1, "Несовместимая версия скаутинга")
            self.pack(c["source"])
            if c.get("circuit") and game["version"] == 1:
                competitions.resolve_slots(c)
            for e in [*c["history"], *(p for p in c["training"]["practice"] if p.get("result"))]:
                self.report(e["result"])
        if game["version"] == 2:
            checkpoints.validate_current(game)
            match.validate_bindings(game)
            checkpoints.validate_round_logs(self.db, game)
        state.pop("exhibitions", None)
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
        edition = c["circuit"]["editions"][event["edition"]] if "edition" in event else None
        lineups = scouting.practice_rosters(c, pack, event) if event.get("pcw") else {}
        expected = {
            pid: tid
            for tid in event["teams"]
            for pid in (edition["registrations"][tid][-1]["players"] if edition else lineups.get(tid, pack["rosters"][c["teams"][tid]]["players"]))
        }
        teams = event["teams"]
        require(
            event["kind"] == "match" and set(report["teams"]) == set(teams),
            "Результат не соответствует встрече",
        )
        facts = None
        if "bestOf" in event:
            best = event["bestOf"]
            profile = edition["rules"] if edition else c["seriesProfile"]
            require(
                report.get("seriesVersion") == series.VERSION
                and report["bestOf"] == best
                and report["profile"] == profile
                and report["seed"] == event["seed"],
                "Регламент не соответствует встрече",
            )
            replay = dict(
                profile=profile,
                teams=teams,
                steps=veto.sequence(profile, best, teams, event["seed"]),
                actions=[],
                order=[],
                stage="veto",
            )
            for action in report["veto"]:
                require(replay["stage"] == "veto", "Лишний ход вето")
                veto.apply(replay, action.get("side", action["map"]), action["by"])
            require(
                replay["stage"] == "ready"
                and replay["actions"] == report["veto"]
                and replay["order"] == report["order"],
                "Нарушен порядок вето",
            )
            points = dict.fromkeys(teams, 0)
            for i, item in enumerate(report["maps"]):
                require(
                    i < best and max(points.values()) < best // 2 + 1,
                    "Лишняя карта серии",
                )
                map_id = replay["order"][i]["map"]
                require(item.get("simulation", series.DETAILED) == report.get("simulation", series.DETAILED), "Режим карты расходится с серией")
                if item.get("simulation", {}).get("mode") == "round":
                    require(item["firstAttackTeamId"] == replay["order"][i]["attack"], "Неверная стартовая сторона")
                series.verify_map(
                    item, teams, expected, series.map_seed(event["seed"], i), map_id
                )
                points[item["winnerTeamId"]] += 1
            require(
                max(points.values()) == best // 2 + 1
                and points == report["scoreByTeam"]
                and report["score"] == [points[t] for t in teams]
                and report["winnerTeamId"] == max(points, key=points.get)
                and report["stats"]
                == series.total_stats(r["stats"] for r in report["maps"])
                and report["rounds"]
                == [row for r in report["maps"] for row in r["rounds"]],
                "Результат серии не соответствует картам",
            )
            facts = series.scouting_record(report)
        else:
            map_id = event.get("mapId")
            if map_id == "depo" and report.get("simulation") == series.DETAILED:
                map_id = None
            points = series.verify_map(report, teams, expected, event["seed"], map_id)
        facts = dict(facts or {}, simulation=report.get("simulation", series.DETAILED))
        body = database.encode(report)
        digest = checksum(body)
        self.db.execute(
            "INSERT OR IGNORE INTO career_report VALUES(?,?)", (digest, body)
        )
        scout_sources.played(c, pack, event, report)
        training.match_practice(c, pack, event, report)
        if event.get("pcw"):
            c["training"]["practice"].append(dict(training.practice_summary(event, report), result=digest))
            c["queue"].pop(0)
            c["date"] = event["date"]
            if c["progress"]:
                c["progress"]["done"] += 1
            return
        if edition:
            facts["rosterVersions"] = {t:edition["registrations"][t][-1]["version"] for t in teams}
        if "bestOf" in event:
            staff.record(c, staff.booked(c, pack, event), event["date"])
        career.complete(c, digest, points, report["winnerTeamId"], facts)

        if edition:
            competitions.completed(c,event,report)
            if edition["status"]=="finished":
                competitions.publish(c,pack)

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
            pack = self.pack(competition_scene.source(value["id"], value["revision"]))
            new = career.create(pack, value)
            self.save(state, "auto")
            state.pop("exhibitions", None)
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
            elif kind == "career-tactic-draft":
                require(not c["progress"], "Дождитесь завершения расчёта календаря")
                staff.prepare_draft(c, self.pack(c["source"]), value)
                self.save(state,"auto")
            elif kind == "career-scouting":
                require(not c["progress"] and state["world"]["version"] == 1, "Завершите встречу или расчёт календаря")
                scouting.change(c, self.pack(c["source"]), value, self.report)
                self.save(state, "auto")
            elif kind == "career-training":
                require(not c["progress"] and state["world"]["version"] == 1, "Завершите встречу или расчёт календаря")
                training_center.change(c, self.pack(c["source"]), self.db, value)
                self.save(state, "auto")
            elif kind == "career-staff":
                require(not c["progress"] and state["world"]["version"] == 1, "Завершите встречу или расчёт календаря")
                pack = self.pack(c["source"])
                staff.change(c, pack, value)
                if value.get("duty") == "practice":
                    c["queue"] = [e for e in c["queue"] if not e.get("delegated")]
                    c["training"].pop("plannedThrough", None)
                    training.refresh_practices(c, pack)
                self.save(state, "auto")
            elif kind == "career-entry":
                require(not c["progress"] and state["world"]["version"]==1,"Завершите текущую встречу или расчёт")
                event = c.get("circuit",{}).get("editions",{}).get(value.get("edition"))
                require(event, "Неизвестное соревнование")
                pack = self.pack(c["source"])
                team = c["team"]
                action = value.get("action")
                if action in ("prioritise", "leave"):
                    if action == "leave":
                        competitions.leave(c, event, team, pack, "Решение менеджера")
                    else:
                        clashes = registrations.clashes(c, event, team)
                        require(clashes and sorted(r["id"] for r in clashes) == value.get("release"),
                                "Список конфликтов изменился. Обновите календарь.")
                        for row in clashes:
                            competitions.leave(c, c["circuit"]["editions"][row["id"]], team, pack,
                                              "Приоритет: " + event["title"])
                        if event["entries"].get(team) == "offered":
                            require(c["date"] < event["replyBy"][team], "Срок подтверждения истёк")
                            event["entries"][team] = "confirmed"
                        elif event["entries"].get(team) not in registrations.COMMITTED:
                            registrations.signup(c, event, team, pack)
                    c["error"] = None
                elif action=="accept":
                    registrations.signup(c,event,team,pack)
                elif action=="withdraw":
                    fixture=c["queue"][0]
                    require(fixture.get("edition")==event["id"] and fixture["date"]==c["date"] and
                            team in competitions.missing_players(c,fixture,pack),"Ваша пятёрка допущена или матч ещё не наступил")
                    competitions.resolve_availability(c,fixture,pack,withdraw=True)
                    c["error"]=None
                elif action=="confirm":
                    require(event["entries"].get(team)=="offered" and c["date"]<event["replyBy"][team],
                            "Срок подтверждения истёк")
                    require(not registrations.conflict_for(c,event,team), "Разрешите конфликт календаря")
                    event["entries"][team]="confirmed"
                elif action=="decline":
                    require(c["date"]<event["lock"] and event["entries"].get(team) in ("invited","accepted","offered","confirmed","qualified"),
                            "Отказ недоступен")
                    event["entries"][team]="declined"
                    if event.get("invitePools") and not event.get("inviteClosed"):
                        competitions.refill_invites(c,event)
                    competitions.process_day(c,pack)
                elif action in ("submit","replace"):
                    registrations.submit(c,event,team,pack,value.get("players"),value.get("reserves"),
                                         value.get("coach"),reason=value.get("reason","") if action=="replace" else None)
                else:
                    raise ValueError("Неизвестное действие с заявкой")
                c["error"] = None
                self.save(state,"auto")
            elif kind == "career-repair":
                require(not c["progress"], "Дождитесь остановки расчёта")
                from .map_install import activate
                activate()
                c["error"] = None
                self.save(state,"auto")
            elif kind == "career-pause":
                # The final background publication may beat the client's stop request.
                if not c["progress"] and state["world"]["version"] == 1 and isinstance(value, dict) and isinstance(value.get("runId"), str):
                    return
                require(c["progress"] and state["world"]["version"] == 1, "Расчёт календаря уже остановлен")
                if value:
                    require(isinstance(value, dict) and value.get("runId") == c["progress"].get("runId", state["context"]), "Начался другой расчёт календаря")
                c["progress"] = None
                state["context"] = str(uuid4())
                self.save(state, "auto")
            elif kind in ("career-advance", "career-retry"):
                require(state["world"]["version"] == 1, "Завершите активный матч")
                pack = self.pack(c["source"])
                career.ensure_schedule(c,pack)
                if kind == "career-retry":
                    c["error"] = None
                pending = attention.blockers(c,pack,state["world"])
                require(not pending, pending[0]["title"] if pending else "")
                career.start_advance(c, administrative=attention.autonomous_fixture(c,c["queue"][0],pack))
            elif kind=="career-watch":
                require(not c["progress"] and state["world"]["version"]==1,"Завершите текущий матч или расчёт")
                fixture=value.get("fixture")
                require(fixture is None or any(e["id"]==fixture and "edition" in e for e in c["queue"]),
                        "Матч уже сыгран или отсутствует в календаре")
                c["watchFixture"]=fixture
                self.save(state,"auto")
            elif kind == "career-quick":
                require(not c["progress"] and state["world"]["version"] == 1 and c["queue"], "Матч пока недоступен")
                e = c["queue"][0]
                pack = self.pack(c["source"])
                pending = attention.blockers(c, pack, state["world"])
                require(isinstance(value, dict) and e["id"] == value.get("fixture") and len(pending) == 1 and pending[0]["action"] == "play", "Обновите календарь и разрешите обязательные решения")
                game = career.initial(pack, c, e, detailed=False)
                self.record(c, career.simulate(game))
                self.save(state, "auto")
            elif kind == "career-play":
                e = c["queue"][0]
                require(
                    not c["progress"]
                    and e["kind"] == "match"
                    and (not e.get("pcw") or (e["watch"] and not training.unavailable(c,e)))
                    and c["date"] == e["date"]
                    and (c["team"] in e["teams"] or e["id"]==c.get("watchFixture"))
                    and state["world"]["version"] == 1,
                    "Матч пока недоступен",
                )
                require(not ("edition" in e and competitions.fixture_conflicts(c, e)), "Разрешите конфликт календаря на странице турнира")
                pack = self.pack(c["source"])
                pending = [r for r in attention.blockers(c,pack,state["world"]) if r["action"] != "play"]
                require(not pending, pending[0]["title"] if pending else "")
                state.update(
                    world=career.initial(
                        pack, c, e, self.store.badges.index(pack), self.store.portraits
                    ),
                    context=str(uuid4()),
                    running=False,
                    speed=1,
                )
                if "bestOf" in e:
                    staff.record(c, staff.booked(c, pack, e), e["date"])
                if c["team"] not in e["teams"]:
                    state["world"]["series"]["spectator"]=True
                    veto.advance(state["world"],"captain")
            elif kind == "career-finish":
                require(state["world"].get("phase") == "finished" and
                        state["world"].get("series", {}).get("stage", "finished") == "finished", "Матч ещё идёт")
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
        event = dict(teams=[own,next(t for t in c["teams"] if t!=own and set(pack["rosters"][c["teams"][own]]["players"]).isdisjoint(pack["rosters"][c["teams"][t]]["players"]))])
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
            queue=[e for e in c["queue"] if not e.get("pcw") or own in e["teams"]],
            history=c["history"],
            roster=members,
            teamRating=world.team_rating(domain,c["teams"][own],next(
                (event.get("mapId","depo").removeprefix("de_") for event in c["queue"]
                 if event["kind"]=="match" and own in event["teams"]), "depo")) ,
            competitions="circuit" in c,watchFixture=c.get("watchFixture"),
            slots=self.slots(c["id"]),
            office=staff.overview(c, pack),
            attention=attention.collect(c, pack, state["world"]),
        )
        return dict(careers=list(menu.values()), active=info)

    def work(self, state, pack=None):
        """Return a detached input; the worker never touches the server connection."""
        c = state.get("career")
        if not c or not c["progress"]:
            return None
        if not c["queue"]:
            return (state["context"], c["id"], None), None
        e = c["queue"][0]
        token = (state["context"], c["id"], e["id"])
        pack = pack if pack is not None else self.pack(c["source"])
        if attention.blockers(c,pack,state["world"]):
            return token, None
        if c["training"]["nextDay"] < e["date"]:
            # work() receives a detached read. Publish the prepared days only with
            # their validated head fixture, including its run identity.
            while c["training"]["nextDay"] < e["date"]:
                training.run_day(c, pack, c["training"]["nextDay"])
            training.freeze_day(c["training"])
            scout_sources.freeze(c["scouting"])
            token += (c["progress"].get("runId"), c["training"], c["office"], c["scouting"], c["milestones"])
        if e.get("pcw") and training.unavailable(c, e):
            return token, None
        game = (
            None if career.stops(c, e) or ("edition" in e and (competitions.fixture_conflicts(c,e) or competitions.missing_players(c,e,pack))) else career.initial(pack, c, e, detailed=False)
        )
        return token, game

    def commit_batch(self, token, report, error=None, *, prepared=None):
        """Coalesce same-day background results in one durable checkpoint."""
        if not report:
            return self.commit_work(token, report, error)
        try:
            return self.commit_work(token, report, error, batch=True, prepared=prepared)
        except (ValueError, ArithmeticError, KeyError, IndexError, OSError):
            # The transaction rolled back. Commit just the head, so a bad later
            # fixture is retried/reported under its own identity by the worker.
            return self.commit_work(token, report, error)

    def commit_work(self, token, report, error=None, *, batch=False, prepared=None):
        with self.store.transaction():
            if prepared is not None and prepared[0] != self.store.calendar_stamp():
                return False
            # The calendar owns this detached checkpoint. Reuse it only while the
            # committed world is unchanged. Recovery always starts from SQLite.
            state = prepared[1] if prepared is not None and not error else self.store.read()
            c = state.get("career")
            if (
                not c
                or not c["progress"]
                or (len(token) > 3 and token[3] != c["progress"].get("runId"))
                or token[:3] != (state["context"], c["id"], c["queue"][0]["id"] if c["queue"] else None)
            ):
                return False
            if len(token) > 3 and not error:
                c["training"], c["office"], c["scouting"], c["milestones"] = deepcopy(token[4:])
            if error:
                c.update(progress=None, error=error)
            elif not c["queue"]:
                career.ensure_schedule(c,self.pack(c["source"]))
            elif report is None:
                e = c["queue"][0]
                pack = self.pack(c["source"])
                if attention.blockers(c,pack,state["world"]):
                    c["progress"] = None
                else:
                    c["date"] = e["date"]
                    if e.get("pcw") and training.unavailable(c, e):
                        c["training"]["practice"].append(dict(e, cancelled="Официальный матч"))
                        c["queue"].pop(0)
                    elif e["kind"] == "review":
                        c["queue"].pop(0)
                        if "circuit" in c:
                            competitions.tick(c,pack)
                        else:
                            self.weekly_review(c,e)
                    elif "edition" in e and competitions.fixture_conflicts(c,e):
                        competitions.settle_fixture_conflicts(c,e,pack)
                    elif "edition" in e and competitions.missing_players(c,e,pack):
                        competitions.resolve_availability(c,e,pack)
                    else:
                        c["progress"] = None
            else:
                self.record(c, report)
                if batch:
                    deadline = monotonic() + .050
                    while c["queue"] and c["queue"][0]["date"] == c["date"] and monotonic() < deadline:
                        _, next_game = self.work(state)
                        if next_game is None:
                            break
                        self.record(c, career.simulate(next_game))
            state["sequence"] += 1
            state["revision"] += 1
            state["careerRevision"] += 1
            self.store.write(state)
            if not c["progress"]:
                self.save(state, "auto")
        return True

    @staticmethod
    def weekly_review(c,e):
        played = sum(m["id"].split("-")[0] == e["id"].split("-")[0] for m in reversed(c["history"]))
        c["milestones"].append(dict(date=e["date"], title="Итоги недели", matches=played))
