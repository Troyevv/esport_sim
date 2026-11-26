"""Scouting on the career calendar. Public performances and club dossiers have separate owners."""

import base64
import json
import zlib
from collections import defaultdict

from . import scout_sources as sources
from . import database, scout_reports as reports, skills, staff, training
from .database import require

KINDS = {"player", "team", "tournament", "compare", "search"}
PUBLIC_FILTERS = {
    "name",
    "region",
    "country",
    "role",
    "language",
    "free",
    "minAge",
    "maxAge",
    "current",
    "potential",
    "skill",
    "minimum",
}


def new():
    return dict(
        version=1, clubs={}, public={}, private={}, trials=[], invitations={}, serial=0
    )


def org(pack, team):
    return pack["teams"][team]["organization"] or "@team-" + team


def department():
    return dict(
        tasks=[],
        trials=[],
        dossiers={},
        lists={},
        regions={},
        workload={},
        cost=0,
        dispatchCost=0,
    )


def employed(c, pack, team, pid):
    roster = membership(pack).get(pid)
    return (
        roster is not None
        and org(pack, roster) == org(pack, team)
        or team in c["teams"]
        and pid in training.members(c, pack, team)
        or pid in c.get("circuit", {}).get("bench", {}).get(team, [])
    )


def visible(c, pack, team, club, pid, day):
    view = knowledge(club, pack, day, pid)
    if employed(c, pack, team, pid):
        player = pack["players"][pid]
        current = player["skills"] | training.lookup(c["training"], "players", pid).get(
            "skills", {}
        )
        values = {k: round(current[k]) for k in training.PUBLIC}
        rating = skills.role_rating(values, player["role"] or "rifler")
        view.update(
            inSquad=True,
            current=[rating, rating],
            skills={k: [v, v] for k, v in values.items()},
        )
    return view


def read_club(c, pack, team):
    saved = c["scouting"]["clubs"].get(org(pack, team))
    if isinstance(saved, str):
        return json.loads(zlib.decompress(base64.b64decode(saved)))
    return saved if saved is not None else department()


def write_club(c, pack, team, club):
    key = org(pack, team)
    c["scouting"]["clubs"][key] = (
        club if key == org(pack, c["team"]) else sources.encode(club)
    )


def serial(c):
    c["scouting"]["serial"] += 1
    return c["scouting"]["serial"]


def notice(c, day, title, body):
    c["milestones"].append(
        dict(
            id=f"scout/{serial(c)}",
            date=day,
            sender="Скаутский отдел",
            title=title,
            body=body,
            matches=None,
        )
    )


def membership(pack):
    # Latest published roster wins, including incomplete rosters outside the calendar.
    global _indexed_pack, _membership
    if _indexed_pack is not pack:
        members = {}
        latest = {}
        for r in sorted(pack["rosters"].values(), key=lambda x: x["date"]):
            if r["date"] <= pack["asOf"]:
                latest[r["team"]] = r
        for r in sorted(latest.values(), key=lambda x: x["date"]):
            for pid in r["players"]:
                if pack["players"][pid]["contract"] != "free":
                    members[pid] = r["team"]
        _indexed_pack, _membership = pack, members
    return _membership


_indexed_pack, _membership = None, {}


def squad(c, pack, team):
    if team in c["teams"]:
        return training.members(c, pack, team)
    return [pid for pid, tid in membership(pack).items() if tid == team]


def identity(pack, pid, day):
    p = pack["players"][pid]
    tid = membership(pack).get(pid)
    age = training.age_on(p, pack["asOf"], day) if p["born"] else p.get("ageEstimate")
    if not p["born"] and type(age) is int:
        age += (reports.ordinal(day) - reports.ordinal(pack["asOf"])) // 365
    if type(age) is not int:
        age = None
    return dict(
        id=pid,
        name=p["name"],
        team=tid,
        region=pack["teams"][tid]["region"] if tid else None,
        country=p["nationality"],
        role=p["role"],
        language=reports.LANGUAGES.get(p["nationality"]),
        free=p["contract"] == "free",
        age=age,
    )


def candidates(club, pack, day, pid, criteria, *, career=None, team=None):
    public = identity(pack, pid, day)
    if criteria.get("name", "").casefold() not in public["name"].casefold():
        return False
    for k in ("region", "country", "role", "language", "free"):
        if k in criteria and criteria[k] != public[k]:
            return False
    age = public["age"]
    if "minAge" in criteria and (age is None or age < criteria["minAge"]):
        return False
    if "maxAge" in criteria and (age is None or age > criteria["maxAge"]):
        return False
    if {"current", "potential", "skill"} & criteria.keys():
        view = (
            visible(career, pack, team, club, pid, day)
            if career
            else knowledge(club, pack, day, pid)
        )
        for k in ("current", "potential"):
            if k in criteria and (not view[k] or reports.mid(view[k]) < criteria[k]):
                return False
        if "skill" in criteria:
            band = view["skills"].get(criteria["skill"])
            return bool(band and reports.mid(band) >= criteria.get("minimum", 0))
    return True


def knowledge(club, pack, day, pid):
    dossier = club["dossiers"].get(pid, {})
    return reports.assessment(
        dossier.get("observations", []),
        day,
        pack["players"][pid]["born"],
        pack["players"][pid]["role"],
    )


def observers(c, pack, team):
    people = staff.team_people(c, pack, team)
    # The manager can work personally, including clubs with no named personnel in the edition.
    key = "@manager-" + team
    people[key] = dict(
        id=key,
        name=c["character"] if team == c["team"] else "Менеджер клуба",
        role="head",
        **staff.profile(key, dict(role="head", preparation=48)),
    )
    return people


def scout_region(pack, team, sid):
    region = pack["teams"][team]["region"]
    if region and staff.draw(sid, "local") % 4:
        return region
    return database.REGIONS[staff.draw(sid, "region") % len(database.REGIONS)]


def scout_languages(c, pack, team, sid):
    nationality = pack["staff"].get(sid, {}).get("nationality")
    local = reports.LANGUAGES.get(nationality)
    if not local:
        local = next(
            (
                reports.LANGUAGES[p["nationality"]]
                for pid in squad(c, pack, team)
                for p in [pack["players"][pid]]
                if p["nationality"] in reports.LANGUAGES
            ),
            None,
        )
    return list(
        dict.fromkeys(
            [
                v
                for v in (
                    local,
                    "Английский" if staff.draw(sid, "english") % 3 else None,
                )
                if v
            ]
        )
    )


def make_task(c, day, kind, target, criteria, author, priority, days):
    return dict(
        id=serial(c),
        start=day,
        due=training.offset(day, days - 1),
        kind=kind,
        target=target,
        criteria=criteria,
        author=author,
        fixed=author is not None,
        priority=priority,
        cost=0,
        results=[],
        status="active",
    )


def validate_criteria(raw):
    require(
        isinstance(raw, dict) and raw.keys() <= PUBLIC_FILTERS,
        "Неизвестное условие поиска",
    )
    for key, v in raw.items():
        if key in ("minAge", "maxAge", "current", "potential", "minimum"):
            require(type(v) is int and 0 <= v <= 100, "Введите число от 0 до 100")
        elif key == "free":
            require(isinstance(v, bool), "Неверный статус игрока")
        else:
            require(isinstance(v, str) and 0 < len(v) <= 80, "Неверное условие поиска")
    require(
        raw.get("minAge", 0) <= raw.get("maxAge", 100), "Проверьте границы возраста"
    )
    require(
        "skill" not in raw or raw["skill"] in training.PUBLIC,
        "Неизвестный приоритетный навык",
    )
    return dict(raw)


def change(c, pack, value, read_report=None):
    state, team, day = c["scouting"], c["team"], c["date"]
    club = read_club(c, pack, team)
    action, pid = value.get("action"), value.get("player")
    if action == "task":
        kind, target = value.get("kind"), value.get("target")
        require(isinstance(kind, str) and kind in KINDS, "Неизвестный тип задания")
        if kind in ("player", "compare"):
            require(
                isinstance(target, list)
                and all(isinstance(p, str) and p in pack["players"] for p in target)
                and len(set(target)) == len(target)
                and (len(target) == 1 if kind == "player" else 2 <= len(target) <= 8),
                "Выберите разных кандидатов",
            )
        elif kind != "search":
            options = (
                pack["teams"]
                if kind == "team"
                else c.get("circuit", {}).get("editions", {})
            )
            require(
                isinstance(target, str) and target in options,
                "Выберите команду или турнир",
            )
        else:
            target = None
        sid, days, priority = (
            value.get("author"),
            value.get("days"),
            value.get("priority"),
        )
        require(
            sid is None or isinstance(sid, str) and sid in observers(c, pack, team),
            "Выберите сотрудника клуба",
        )
        require(
            type(days) is int
            and 1 <= days <= 90
            and type(priority) is int
            and 1 <= priority <= 3,
            "Проверьте приоритет и срок",
        )
        club["tasks"].append(
            make_task(
                c,
                day,
                kind,
                target,
                validate_criteria(value.get("criteria", {})),
                sid,
                priority,
                days,
            )
        )
        if read_report and kind != "search":
            teams = (
                {target}
                if kind == "team"
                else (
                    {membership(pack).get(p) for p in target}
                    if isinstance(target, list)
                    else set()
                )
            )
            task = club["tasks"][-1]
            task["archive"] = sources.assignment_archive(
                c, pack, task, teams, read_report
            )
    elif action == "cancel":
        task = next(
            (
                t
                for t in club["tasks"]
                if t["id"] == value.get("id") and t["status"] == "active"
            ),
            None,
        )
        require(task, "Задание уже закрыто")
        task["status"] = "cancelled"
        task.pop("archive", None)
    elif action in ("category", "list", "remove"):
        name = value.get("category")
        require(
            isinstance(name, str) and 0 < len(name.strip()) <= 48,
            "Введите название категории",
        )
        name = name.strip()
        if action == "category":
            require(name not in club["lists"], "Категория уже существует")
            club["lists"][name] = []
        else:
            require(
                name in club["lists"]
                and isinstance(pid, str)
                and pid in pack["players"],
                "Выберите категорию и игрока",
            )
            ids = club["lists"][name]
            if action == "list" and pid not in ids:
                ids.append(pid)
            elif action == "remove" and pid in ids:
                ids.remove(pid)
    elif action in ("renameCategory", "deleteCategory"):
        name = value.get("category")
        require(isinstance(name, str) and name in club["lists"], "Категория не найдена")
        if action == "deleteCategory":
            require(not club["lists"][name], "Сначала удалите кандидатов из категории")
            del club["lists"][name]
        else:
            new_name = value.get("name")
            require(
                isinstance(new_name, str)
                and 0 < len(new_name.strip()) <= 48
                and new_name.strip() not in club["lists"],
                "Укажите свободное название до 48 знаков",
            )
            club["lists"][new_name.strip()] = club["lists"].pop(name)
    elif action in ("permit", "deny"):
        request = next(
            (
                t
                for t in state["trials"]
                if t["id"] == value.get("id")
                and t["status"] == "requested"
                and org(pack, t["origin"]) == org(pack, team)
            ),
            None,
        )
        require(request, "Запрос уже закрыт")
        request["permission"] = action == "permit"
        if request["permission"]:
            duration = reports.ordinal(request["end"]) - reports.ordinal(
                request["start"]
            )
            request["start"] = max(day, request["start"])
            request.update(
                status="active", end=training.offset(request["start"], duration)
            )
        else:
            request["status"] = "blocked"
            host = read_club(c, pack, request["host"])
            host["trials"].append(request)
            state["trials"].remove(request)
            write_club(c, pack, request["host"], host)
    elif action == "trial":
        require(isinstance(pid, str) and pid in pack["players"], "Выберите игрока")
        invite(c, pack, team, pid, day, value.get("days"), club)
    else:
        raise ValueError("Неизвестное действие скаутского отдела")
    write_club(c, pack, team, club)


def invite(c, pack, team, pid, day, duration, club):
    require(
        type(duration) is int and duration in (3, 7, 14),
        "Просмотр длится 3, 7 или 14 дней",
    )
    require(not employed(c, pack, team, pid), "Игрок уже в составе")
    trials = c["scouting"]["trials"]
    require(
        not any(t["player"] == pid for t in trials)
        and c["scouting"]["invitations"].get(pid) != day,
        "Игрок уже получил приглашение",
    )
    require(
        sum(t["host"] == team for t in trials) < 3,
        "Все места на просмотре заняты",
    )
    origin = membership(pack).get(pid)
    consent = reports.noise(pid, team, day, "player") > -0.65
    permission = (
        None if not origin else reports.noise(origin, team, pid, day, "club") > -0.35
    )
    status = (
        "declined" if not consent else "blocked" if permission is False else "active"
    )
    if (
        consent
        and origin
        and org(pack, origin) == org(pack, c["team"])
        and team != c["team"]
    ):
        status, permission = "requested", None
        notice(
            c,
            c["date"],
            "Запрос на просмотр · " + pack["players"][pid]["name"],
            pack["teams"][team]["name"]
            + " запрашивает разрешение. Ответьте в разделе просмотров.",
        )
    trial = dict(
        id=serial(c),
        host=team,
        player=pid,
        origin=origin,
        start=day,
        end=training.offset(day, duration - 1),
        consent=consent,
        permission=permission,
        status=status,
    )
    c["scouting"]["invitations"][pid] = day
    (trials if status in ("active", "requested") else club["trials"]).append(trial)
    return trial


def attendance(c, pack, day, blocked):
    """A player can visit only one club and remains available to their official registration."""
    active = [
        t
        for t in c.get("scouting", {}).get("trials", [])
        if t["status"] == "active"
        and t["start"] <= day <= t["end"]
        and t["origin"] not in blocked
    ]
    if not active:
        return {}
    busy = {
        pid
        for team in blocked
        if team in c["teams"]
        for pid in training.members(c, pack, team)
    }
    for e in c.get("circuit", {}).get("editions", {}).values():
        if e["start"] <= day <= e["end"]:
            for team in blocked.intersection(e["registrations"]):
                versions = e["registrations"][team]
                if versions:
                    busy.update(versions[-1]["players"])
    return {t["player"]: t["host"] for t in active if t["player"] not in busy}


def practice_rosters(c, pack, event):
    rosters = {t: list(training.members(c, pack, t)) for t in event["teams"]}
    if not c.get("scouting", {}).get("trials"):
        return rosters
    official, reserved = training.schedule_book(c, event["date"])
    visiting = attendance(
        c, pack, event["date"], official | reserved | set(event["teams"])
    )
    for team in event["teams"]:
        for pid, host in visiting.items():
            if host != team:
                continue
            ids = rosters[team]
            own = training.members(c, pack, team)
            eligible = [i for i, p in enumerate(ids) if p in own]
            slot = min(
                eligible,
                key=lambda i: pack["players"][ids[i]]["role"]
                != pack["players"][pid]["role"],
            )
            ids[slot] = pid
    return rosters


def dossier_report(club, pack, pid, day, version=None):
    dossier = club["dossiers"].get(pid)
    if not dossier:
        return None
    versions = dossier["versions"]
    entry = (
        versions[-1]
        if version is None
        else next((v for v in versions if v["number"] == version), None)
    )
    if not entry:
        return None
    evidence = dossier["observations"][: entry["count"]]
    if "trialStart" in entry:
        evidence = [
            o
            for o in evidence
            if o["source"] in ("practice", "training")
            and entry["trialStart"] <= o["date"] <= entry["day"]
        ]
    else:
        evidence = [o for o in evidence if o["author"] == evidence[-1]["author"]]
    view = reports.assessment(
        evidence,
        entry["day"],
        pack["players"][pid]["born"],
        pack["players"][pid]["role"],
    )
    return dict(
        **view,
        **entry["summary"],
        version=entry["number"],
        published=entry["day"],
        author=evidence[-1]["name"],
        evidence=[
            {k: o[k] for k in ("event", "source", "date", "name", "basis", "quality")}
            for o in evidence
        ],
    )


def publish(dossier, player, evidence, day, lineup, trial_start=None):
    opinion = reports.assessment(evidence, day, player["born"], player["role"])
    summary = reports.describe(
        opinion,
        player,
        evidence,
        [p["role"] for p in lineup],
        [reports.LANGUAGES.get(p["nationality"]) for p in lineup],
    )
    version = dict(
        number=len(dossier["versions"]) + 1,
        count=len(dossier["observations"]),
        basisCount=len(evidence),
        author=evidence[-1]["name"],
        day=day,
        summary=summary,
    )
    if trial_start:
        version["trialStart"] = trial_start
        summary["trialObservations"] = len(evidence)
        summary["recommendation"] = (
            "Сохранить в списке кандидатов"
            if opinion["score"] >= 38
            else "Продолжить наблюдение после просмотра"
        )
    dossier["versions"].append(version)
    return summary


def record_observation(c, pack, team, club, pid, person, fact, day):
    d = club["dossiers"].setdefault(pid, dict(observations=[], versions=[]))
    region = identity(pack, pid, day)["region"] or "unknown"
    coverage = club["regions"].setdefault(person["id"], {})
    local = region == scout_region(pack, team, person["id"])
    familiar = min(100, (55 if local else 10) + coverage.get(region, 0))
    lineup = [pack["players"][p] for p in squad(c, pack, team)]
    lang = reports.LANGUAGES.get(pack["players"][pid]["nationality"])
    obs = reports.observation(
        fact,
        person,
        familiar,
        lang is not None and lang in scout_languages(c, pack, team, person["id"]),
    )
    obs["reviewed"] = day
    d["observations"].append(obs)
    coverage[region] = coverage.get(region, 0) + 1
    view = knowledge(club, pack, day, pid)
    authored = [o for o in d["observations"] if o["author"] == person["id"]]
    summary = publish(d, pack["players"][pid], authored, day, lineup)
    if team == c["team"]:
        notice(
            c,
            day,
            "Новый отчёт · " + pack["players"][pid]["name"],
            person["name"]
            + " · "
            + fact["basis"]
            + ". "
            + summary["recommendation"]
            + ".",
        )
    elif view["score"] >= 25 and summary["recommendation"] != "Продолжить наблюдение":
        ids = club["lists"].setdefault("Кандидаты", [])
        if pid not in ids:
            ids.append(pid)


def target_pool(task, pool, pack):
    if task["kind"] in ("player", "compare"):
        return task["target"]
    if task["kind"] == "team":
        return [p for p in pool if membership(pack).get(p) == task["target"]]
    return pool


def find_observation(c, pack, team, club, task, person, day, pool):
    if task.get("archive"):
        pool = list(dict.fromkeys([*task["archive"], *pool]))
    targets = target_pool(task, pool, pack)
    seen = club["dossiers"]
    own = set(squad(c, pack, team))
    # Rotate mass searches without ranking by private player attributes.
    if task["kind"] in ("search", "tournament") and targets:
        start = staff.draw(team, (day, task["id"])) % len(targets)
        targets = targets[start:] + targets[:start]
    if task["kind"] == "search" and task["results"]:
        targets = [*task["results"], *targets]
    if task["kind"] == "compare":
        targets = sorted(
            targets, key=lambda p: len(seen.get(p, {}).get("observations", []))
        )
    for pid in targets:
        if task["kind"] == "search" and pid in own:
            continue
        if not candidates(club, pack, day, pid, task["criteria"], career=c, team=team):
            continue
        observed = {
            (o["author"], o["event"]) for o in seen.get(pid, {}).get("observations", [])
        }
        facts = sources.available_facts(c, pack, team, pid, day)
        facts += task.get("archive", {}).get(pid, [])
        if str(task["id"]).startswith("trial"):
            # Review both the drill and the scrim even when a new drill arrives every day.
            facts.sort(
                key=lambda f: (
                    sum(
                        o["source"] == f["source"]
                        for o in seen.get(pid, {}).get("observations", [])
                    ),
                    f["source"] != "practice",
                )
            )
        for fact in facts:
            if str(task["id"]).startswith("trial") and (
                fact["source"] not in ("practice", "training")
                or fact["date"] < task["start"]
            ):
                continue
            if task["kind"] == "tournament" and fact.get("edition") != task["target"]:
                continue
            if (person["id"], fact["id"]) not in observed:
                return pid, fact
    return None


def duty(c, pack, team, day, club, pool, ledger, trials, *, automatic):
    people = observers(c, pack, team)
    duties = c["office"]["duties"] if team == c["team"] else {}
    used = defaultdict(int)
    for j in ledger:
        used[j["person"]] += j["cost"]
    jobs = []

    def book(person, name, key):
        cost = staff.DUTIES[name][3]
        if used[person["id"]] + cost > staff.capacity(person):
            return False
        used[person["id"]] += cost
        jobs.append(
            dict(
                person=person["id"],
                name=person["name"],
                date=day,
                due=day,
                team=team,
                duty=name,
                event=f"scouting/{team}/{day}/{key}",
                cost=cost,
                quality=staff.quality(person, name),
            )
        )
        club["cost"] += cost
        return True

    chief = people.get(duties.get("dispatch"))
    if automatic and chief is None:
        chief = next((p for p in people.values() if p["role"] == "chief_scout"), None)
    if (
        (automatic or chief or duties.get("search"))
        and pool
        and not any(t["status"] == "active" for t in club["tasks"])
    ):
        region = pack["teams"][team]["region"]
        criteria = {"region": region} if region and staff.draw(team, day) % 3 else {}
        club["tasks"].append(make_task(c, day, "search", None, criteria, None, 1, 14))
    tasks = [t for t in club["tasks"] if t["status"] == "active" and t["due"] >= day]
    for trial in trials:
        if trial["start"] > day:
            continue
        tasks.insert(
            0,
            dict(
                id="trial-" + str(trial["id"]),
                start=trial["start"],
                kind="player",
                target=[trial["player"]],
                criteria={},
                author=None,
                priority=4,
                cost=0,
                results=[],
            ),
        )
    for task in sorted(tasks, key=lambda t: -t["priority"]):
        sid = task["author"]
        if (
            sid
            and not task.get("fixed")
            and used[sid] + staff.DUTIES["search"][3] > staff.capacity(people[sid])
        ):
            sid = None
        if sid is None:
            region = task["criteria"].get("region", pack["teams"][team]["region"])
            options = [
                p
                for p in people.values()
                if used[p["id"]] + staff.DUTIES["search"][3] <= staff.capacity(p)
            ]
            if not options:
                continue
            person = max(
                options,
                key=lambda p: staff.quality(p, "search")
                + (12 if scout_region(pack, team, p["id"]) == region else 0)
                + min(15, club["regions"].get(p["id"], {}).get(region, 0))
                + (12 if p["id"] == duties.get("search") else 0)
                - 8 * used[p["id"]],
            )
            if chief and not str(task["id"]).startswith("trial"):
                if not book(chief, "dispatch", task["id"]):
                    continue
                club["dispatchCost"] += staff.DUTIES["dispatch"][3]
            task["author"] = person["id"]
        else:
            person = people.get(sid)
        if not person or used[person["id"]] + staff.DUTIES["search"][
            3
        ] > staff.capacity(person):
            continue
        result = find_observation(c, pack, team, club, task, person, day, pool)
        if result and book(person, "search", task["id"]):
            pid, fact = result
            record_observation(c, pack, team, club, pid, person, fact, day)
            task["cost"] += staff.DUTIES["search"][3]
            if pid not in task["results"]:
                task["results"].append(pid)
    for task in club["tasks"]:
        if task["status"] == "active" and task["due"] <= day:
            task["status"] = "complete"
            task.pop("archive", None)
    for trial in trials:
        if trial["end"] <= day:
            trial["status"] = "finished"
            d = club["dossiers"].get(trial["player"], {})
            observed = [
                o
                for o in d.get("observations", [])
                if o["source"] in ("practice", "training")
                and trial["start"] <= o["date"] <= day
            ]
            if observed:
                publish(
                    d,
                    pack["players"][trial["player"]],
                    observed,
                    day,
                    [pack["players"][p] for p in squad(c, pack, team)],
                    trial["start"],
                )
            trial["report"] = d["versions"][-1]["number"] if observed else None
            c["scouting"]["trials"].remove(trial)
            club["trials"].append(trial)
            if team == c["team"]:
                name = pack["players"][trial["player"]]["name"]
                notice(
                    c,
                    day,
                    "Завершён просмотр · " + name,
                    f"Изучено занятий и пракков: {len(observed)}.",
                )
    if team == c["team"]:
        for pid in {p for ids in club["lists"].values() for p in ids}:
            view = knowledge(club, pack, day, pid)
            if view.get("age") in (30, 90):
                notice(
                    c,
                    day,
                    "Устаревает отчёт · " + pack["players"][pid]["name"],
                    f'Дней без наблюдений: {view["age"]}.',
                )
    if (
        automatic
        and team in c["teams"]
        and not trials
        and club["lists"].get("Кандидаты")
    ):
        # Revisit a possible signing after repeated evidence. Invitations share the manager's rules.
        previous = club.get("invited")
        if not previous or reports.ordinal(day) - reports.ordinal(previous) >= 90:
            for candidate in reversed(club["lists"]["Кандидаты"]):
                if knowledge(club, pack, day, candidate)["score"] < 50:
                    continue
                if (
                    employed(c, pack, team, candidate)
                    or c["scouting"]["invitations"].get(candidate)
                    == training.offset(day, 1)
                    or any(t["player"] == candidate for t in c["scouting"]["trials"])
                ):
                    continue
                invite(c, pack, team, candidate, training.offset(day, 1), 7, club)
                club["invited"] = day
                break
    for job in jobs:
        load = club["workload"].setdefault(
            job["person"], dict(cost=0, days=0, peak=0, last=None)
        )
        load["cost"] += job["cost"]
        load["days"] += int(load["last"] != day)
        load["peak"] = max(load["peak"], used[job["person"]])
        load["last"] = day
    return jobs


def daily(c, pack, day):
    state = c["scouting"]
    by_team = defaultdict(list)
    for trial in state["trials"][:]:
        if trial["status"] == "requested" and day > training.offset(trial["start"], 2):
            trial["status"] = "expired"
            host = read_club(c, pack, trial["host"])
            host["trials"].append(trial)
            state["trials"].remove(trial)
            write_club(c, pack, trial["host"], host)
        if trial["status"] == "active":
            by_team[trial["host"]].append(trial)
    ledger = defaultdict(list)
    for j in c["office"]["ledger"].get("jobs", []):
        if j["date"] == day:
            ledger[j["team"]].append(j)
    pool = list(
        dict.fromkeys(
            [
                *state["public"],
                *sources.public_base(state.get("baseline", "")),
                *sources.archive_players(pack),
            ]
        )
    )
    jobs, processed = [], set()
    for team in [c["team"], *c["teams"], *pack["teams"]]:
        key = org(pack, team)
        if key in processed:
            continue
        processed.add(key)
        automatic = team != c["team"]
        # Each AI department has a different review weekday. Trial work is daily.
        if (
            automatic
            and not by_team[team]
            and (reports.ordinal(day) + zlib.crc32(key.encode())) % 7
        ):
            continue
        club = read_club(c, pack, team)
        jobs.extend(
            duty(
                c,
                pack,
                team,
                day,
                club,
                pool,
                ledger[team],
                by_team[team],
                automatic=automatic,
            )
        )
        write_club(c, pack, team, club)
    staff.record(c, jobs, day)


def center(c, pack):
    team, day = c["team"], c["date"]
    club = read_club(c, pack, team)
    people = observers(c, pack, team)
    index = {pid: identity(pack, pid, day) for pid in pack["players"]}
    for pid, row in index.items():
        if pid in club["dossiers"] or employed(c, pack, team, pid):
            row["knowledge"] = visible(c, pack, team, club, pid, day)
    return dict(
        players=index,
        publicSkills=list(training.PUBLIC),
        tasks=[
            {k: v for k, v in task.items() if k != "archive"} for task in club["tasks"]
        ],
        lists=club["lists"],
        cost=club["cost"],
        regionNames=database.REGIONS,
        incoming=[
            t
            for t in c["scouting"]["trials"]
            if t["origin"]
            and org(pack, t["origin"]) == org(pack, team)
            and t["host"] != team
        ],
        trials=sorted(
            [
                *club["trials"],
                *(t for t in c["scouting"]["trials"] if t["host"] == team),
            ],
            key=lambda t: t["id"],
        ),
        reports=[
            dict(
                player=p,
                version=v["number"],
                date=v["day"],
                count=v["basisCount"],
                author=v["author"],
            )
            for p, d in club["dossiers"].items()
            for v in d["versions"]
        ],
        coverage=club["regions"],
        workload=club["workload"],
        observers=[
            dict(
                id=s,
                name=p["name"],
                capacity=staff.capacity(p),
                region=scout_region(pack, team, s),
                languages=scout_languages(c, pack, team, s),
                quality=staff.quality(p, "search"),
                attributes={
                    k: p["attributes"][k]
                    for k in ("ability", "potential", "fit", "discovery")
                },
            )
            for s, p in people.items()
        ],
        tournaments={
            k: e["title"] for k, e in c.get("circuit", {}).get("editions", {}).items()
        },
    )
