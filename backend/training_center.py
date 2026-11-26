"""Manager commands and public projections for the weekly training centre."""

from copy import deepcopy
import json

from . import (
    competitions,
    database,
    skills,
    staff,
    tactic_library,
    tactics,
    training as tr,
)
from .database import require


def day_value(value):
    require(isinstance(value, str), "Выберите дату")
    database.day(value)
    return value


def selection(value, allowed, limit):
    require(
        isinstance(value, list)
        and len(value) <= limit
        and all(isinstance(k, str) and k in allowed for k in value)
        and len(set(value)) == len(value),
        "Некорректный список приоритетов",
    )
    return value


def ref(db, raw, map_id, kind, *, pinned=False):
    if not raw:
        return {}
    board = tactic_library.resolve(db, raw, pinned=pinned)
    require(
        kind in ("team", "attack", "defense", "retake", "pcw"),
        "Направление не использует тактическую доску",
    )
    require(
        board["map"] == map_id
        and (kind != "attack" or board["side"] == "T")
        and (kind != "defense" or board["side"] == "CT"),
        "Проверьте сторону и карту тактики",
    )
    result = dict(tactic=tactics.reference(board))
    if kind == "pcw":
        result["board"] = board
    return result


def current(c, pack, day):
    official, reserved = tr.schedule_book(c, day)
    people, owners = tr.roster_staff(c, pack, c["team"])
    return tr.plan(c, pack, c["team"], day, official, reserved, people, owners)


def check_load(c, pack, day, rows, extra=0):
    require(len(rows) <= 3, "В расписании три окна на день")
    official, _ = tr.schedule_book(c, day)
    pcw = sum(e.get("pcw", False) and e["date"] == day for e in c["queue"])
    pcw += sum(
        e["date"] == day and not e.get("cancelled") for e in c["training"]["practice"]
    )
    require(len(rows) + pcw + extra <= 3, "Заняты все три окна дня")
    require(
        c["team"] not in official or all(tr.DRILLS[s["kind"]][2] <= 0 for s in rows),
        "В день официальной встречи доступны отдых и восстановление",
    )
    for pid in tr.members(c, pack, c["team"]):
        intensity = c["training"]["programs"].get(pid, {}).get("intensity", 1)
        load = sum(
            max(0, tr.DRILLS[s["kind"]][2]) * (intensity if s.get("player") else 1)
            for s in rows
            if s.get("player", pid) == pid
        )
        require(
            load + (pcw + extra) * 16 <= tr.MAX_LOAD,
            "Превышена допустимая дневная нагрузка",
        )


def change(c, pack, db, value, *, from_template=False):
    t, team, action = c["training"], c["team"], value.get("action")
    ids = tr.members(c, pack, team)
    if action == "program":
        pid = value.get("player")
        require(isinstance(pid, str) and pid in ids, "Выберите игрока клуба")
        role, intensity, coach = (value.get(k) for k in ("role", "intensity", "coach"))
        require(
            isinstance(role, str)
            and role in skills.ROLE_WEIGHTS
            and type(intensity) in (float, int)
            and intensity in (0.65, 1, 1.25),
            "Выберите роль и интенсивность",
        )
        require(
            coach is None
            or isinstance(coach, str)
            and coach in staff.team_people(c, pack, team),
            "Специалист отсутствует в штабе",
        )
        t["programs"][pid] = dict(
            role=role,
            intensity=intensity,
            coach=coach,
            skills=selection(value.get("skills"), tr.PUBLIC, 3),
            maps=selection(value.get("maps"), tr.maps(c), 3),
        )
        for day, rows in t["plans"].items():
            check_load(c, pack, day, rows)
        return
    day = day_value(value.get("date"))
    if action in ("template", "apply"):
        require(tr.monday(day) == day, "Выберите неделю")
        name = value.get("name")
        require(
            isinstance(name, str) and 0 < len(name.strip()) <= 48,
            "Введите название шаблона",
        )
        name = name.strip()
        if action == "template":
            week = []
            for i in range(7):
                d = tr.offset(day, i)
                sessions = (
                    t["days"].get(d, {}).get("sessions", [])
                    if d < c["date"]
                    else current(c, pack, d)
                )
                rows = [
                    {
                        k: v
                        for k, v in r.items()
                        if k not in ("quality", "specialist", "changes")
                    }
                    for r in sessions
                ]
                fixtures = [
                    e
                    for e in [*c["queue"], *t["practice"]]
                    if e.get("pcw")
                    and not e.get("cancelled")
                    and team in e["teams"]
                    and e["date"] == d
                ]
                sparring = None
                if fixtures:
                    first = fixtures[0]
                    sparring = dict(
                        opponent=next(t for t in first["teams"] if t != team),
                        map=first["mapId"],
                        goal=first["goal"],
                        watch=first["watch"],
                        games=len(fixtures),
                        tactic=first.get("tactic"),
                    )
                week.append(dict(sessions=deepcopy(rows), practice=sparring))
            t["templates"][name] = week
        else:
            require(name in t["templates"], "Шаблон не найден")
            for i, entry in enumerate(t["templates"][name]):
                d = tr.offset(day, i)
                if d < c["date"]:
                    continue
                rows = deepcopy(entry["sessions"])
                busy = set.union(*tr.schedule_book(c, d))
                if team in busy:
                    rows = [dict(kind="recovery")]
                check_load(c, pack, d, rows)
                t["plans"][d] = rows
                practice = entry["practice"]
                if practice and team not in busy and practice["opponent"] not in busy:
                    change(
                        c,
                        pack,
                        db,
                        dict(practice, action="pcw", date=d),
                        from_template=True,
                    )
        return
    require(day >= c["date"], "Прошедшие занятия завершены")
    if action in ("cancel-pcw", "watch-pcw"):
        event = next(
            (
                e
                for e in c["queue"]
                if e.get("pcw")
                and e["id"] == value.get("id")
                and team in e["teams"]
                and e["date"] == day
            ),
            None,
        )
        require(event, "Пракк уже завершён")
        if action == "watch-pcw":
            event["watch"] = not event["watch"]
            event["delegated"] = False
        else:
            if event.get("delegated"):
                t.setdefault("skipped", []).append(day)
            c["queue"].remove(event)
        return
    rows = list(current(c, pack, day))
    if action == "auto":
        t["plans"].pop(day, None)
        return
    if action == "pcw":
        other, map_id, goal = (value.get(k) for k in ("opponent", "map", "goal"))
        require(
            isinstance(other, str)
            and other != team
            and other in c["teams"]
            and set(ids).isdisjoint(tr.members(c, pack, other)),
            "Выберите доступный состав соперника",
        )
        require(
            isinstance(map_id, str)
            and map_id in tr.maps(c)
            and goal in ("synergy", "attack", "defense", "retake", "utility"),
            "Выберите карту и цель пракка",
        )
        count, watch = value.get("games"), value.get("watch")
        require(
            type(count) is int and count in (1, 2) and type(watch) is bool,
            "Выберите формат и режим пракка",
        )
        busy = set.union(*tr.schedule_book(c, day))
        active = {
            pid for tid in busy if tid in c["teams"] for pid in tr.members(c, pack, tid)
        }
        require(
            active.isdisjoint([*ids, *tr.members(c, pack, other)]),
            "Игрок уже участвует в матче в этот день",
        )
        require(not ({team, other} & busy), "Соперник или команда заняты в этот день")
        check_load(c, pack, day, rows if day in t["plans"] else [], extra=count)
        board = ref(db, value.get("tactic"), map_id, "pcw", pinned=from_template)
        for i in range(count):
            pair = [team, other] if i == 0 else [other, team]
            c["queue"].append(tr.fixture(c, day, *pair, map_id, goal, watch, i) | board)
        competitions.order(c)
        return
    index = value.get("index")
    require(type(index) is int and 0 <= index <= len(rows), "Выберите окно занятия")
    if action == "remove":
        require(index < len(rows), "Занятие отсутствует")
        rows.pop(index)
    elif action == "session":
        kind, pid, map_id = (value.get(k) for k in ("kind", "player", "map"))
        require(
            isinstance(kind, str) and kind in tr.DRILLS and kind != "pcw",
            "Выберите направление",
        )
        require(
            pid is None or isinstance(pid, str) and pid in ids,
            "Игрок отсутствует в составе",
        )
        require(
            kind != "program" or pid, "Выберите игрока для индивидуальной программы"
        )
        row = dict(kind=kind)
        if pid:
            row["player"] = pid
        if map_id:
            require(map_id in tr.maps(c), "Карта недоступна")
            row["map"] = map_id
        if kind in ("map", "attack", "defense", "retake"):
            require(map_id, "Выберите карту занятия")
        if kind == "opponent":
            other = value.get("opponent")
            require(
                isinstance(other, str) and other != team and other in c["teams"],
                "Выберите соперника для анализа",
            )
            row["opponent"] = other
            latest = next(
                (e for e in reversed(c["history"]) if other in e["teams"]), None
            )
            if latest:
                row["insight"] = "Последний результат · " + " : ".join(
                    map(str, latest["score"])
                )
                if latest["winnerTeamId"] == other:
                    row["targets"] = ["game_reading", "positioning"]
            else:
                roles = [pack["players"][p]["role"] for p in tr.members(c, pack, other)]
                row["targets"] = (
                    ["timing", "smokes"]
                    if "awper" in roles
                    else ["game_reading", "trades"]
                )
                row["insight"] = "Подготовка по ролям стартовой пятёрки"
        if kind == "review":
            event = next(
                (
                    e
                    for e in reversed(c["history"])
                    if e["id"] == value.get("match") and team in e["teams"]
                ),
                None,
            )
            require(event, "Выберите сыгранный матч клуба")
            row["match"] = event["id"]
            result = db.execute(
                "SELECT body FROM career_report WHERE digest=?", (event["result"],)
            ).fetchone()
            require(result, "Протокол матча отсутствует")
            rounds = json.loads(result[0])["rounds"]
            wins = {
                side: sum(
                    r["side"] == side and r["winnerTeamId"] == team for r in rounds
                )
                for side in ("T", "CT")
            }
            side = min(wins, key=wins.get)
            row.update(
                targets=(
                    ["entry", "execution"]
                    if side == "T"
                    else ["positioning", "retakes"]
                ),
                insight=f"Победы за T · {wins['T']}, за CT · {wins['CT']}",
            )
        row.update(ref(db, value.get("tactic"), map_id, kind))
        rows[index : index + 1] = [row]
    else:
        raise ValueError("Неизвестная команда тренировочного центра")
    check_load(c, pack, day, rows)
    t["plans"][day] = rows


def week(c, pack, db, start):
    first = tr.monday(day_value(start))
    t, team = c["training"], c["team"]
    dates = [tr.offset(first, i) for i in range(7)]
    days = []
    for day in dates:
        official, reserved = tr.schedule_book(c, day)
        saved = t["days"].get(day, {})
        days.append(
            dict(
                date=day,
                sessions=(
                    saved.get("sessions", [])
                    if day < c["date"]
                    else current(c, pack, day)
                ),
                official=team in official,
                fatigue=saved.get("fatigue", {}),
                manual=day in t["plans"],
                practices=[
                    e
                    for e in [*c["queue"], *t["practice"]]
                    if e.get("pcw") and e["date"] == day and team in e["teams"]
                ],
            )
        )
    ids = tr.members(c, pack, team)
    people = {}
    today = current(c, pack, c["date"])
    pcw = sum(e.get("pcw", False) and e["date"] == c["date"] for e in c["queue"])
    for pid in ids:
        row = tr.lookup(t, "players", pid)
        base = pack["players"][pid]
        recent = [
            (d, h["fatigue"][pid]) for d, h in t["days"].items() if pid in h["fatigue"]
        ][-14:]
        people[pid] = dict(
            fatigue=round(row.get("fatigue", 0), 1),
            practice=round(row.get("practice", 0), 1),
            plannedLoad=round(
                16 * pcw
                + sum(
                    max(0, tr.DRILLS[r["kind"]][2])
                    * (
                        t["programs"].get(pid, {}).get("intensity", 1)
                        if r.get("player")
                        else 1
                    )
                    for r in today
                    if r.get("player", pid) == pid
                ),
                1,
            ),
            trend=recent,
            metrics=(
                t["days"].get(recent[-1][0], {}).get("metrics", {}).get(pid, {})
                if recent
                else {}
            ),
            skills={
                k: round(
                    row.get("skills", {}).get(k, base["skills"][k]) - base["skills"][k],
                    2,
                )
                for k in tr.PUBLIC
            },
            maps=base["mapKnowledge"] | row.get("mapKnowledge", {}),
            roles=base["roleMastery"] | row.get("roleMastery", {}),
            tactics=row.get("tactics", {}),
        )
    boards = [
        dict(tactics.reference(p), map=p["map"]) for p in tactic_library.plans(db)
    ]
    return dict(
        days=days,
        players=people,
        initial={
            pid: {k: pack["players"][pid]["skills"][k] for k in tr.PUBLIC}
            for pid in ids
        },
        maps=tr.maps(c),
        catalog=tr.DRILLS,
        programs=t["programs"],
        templates=sorted(t["templates"]),
        boards=boards,
        history={d: t["weekStats"][d] for d in list(t["weekStats"])[-12:]},
        teams=[
            other
            for other in c["teams"]
            if other != team and set(ids).isdisjoint(tr.members(c, pack, other))
        ],
    )


def calendar(c, pack, since, count):
    day_value(since)
    require(1 <= count <= 42, "Выберите неделю или месяц")
    state = c["training"]
    rows = {}
    for i in range(count):
        day = tr.offset(since, i)
        sessions = (
            state["days"].get(day, {}).get("sessions", [])
            if day < c["date"]
            else current(c, pack, day)
        )
        rows[day] = [tr.DRILLS[s["kind"]][0] for s in sessions]
        rows[day].extend(
            "Пракк · "
            + pack["teams"][next(t for t in e["teams"] if t != c["team"])]["name"]
            for e in state["practice"]
            if e["date"] == day and not e.get("cancelled")
        )
    return rows
