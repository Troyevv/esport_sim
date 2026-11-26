"""Manager commands and public projections for the weekly training centre."""

from copy import deepcopy
from datetime import timedelta

from . import competitions, database, skills, staff, tactic_library, tactics, training as tr
from .database import require


def day_value(value):
    require(isinstance(value, str), "Выберите дату")
    database.day(value)
    return value


def selection(value, allowed, limit):
    require(isinstance(value, list) and len(value) <= limit
            and all(isinstance(k, str) and k in allowed for k in value)
            and len(set(value)) == len(value), "Некорректный список приоритетов")
    return value


def ref(db, raw, map_id, kind):
    if not raw:
        return {}
    board = tactic_library.resolve(db, raw)
    require(kind in ("team", "attack", "defense", "retake", "pcw"), "Направление не использует тактическую доску")
    require(board["map"] == map_id and (kind != "attack" or board["side"] == "T")
            and (kind != "defense" or board["side"] == "CT"), "Проверьте сторону и карту тактики")
    return dict(tactic=tactics.reference(board))


def current(c, pack, day):
    official, reserved = tr.schedule_book(c, day)
    people, owners = tr.roster_staff(c, pack, c["team"])
    return tr.plan(c, pack, c["team"], day, official, reserved, people, owners)


def check_load(c, pack, day, rows, extra=0):
    require(len(rows) <= 3, "В расписании три окна на день")
    official, reserved = tr.schedule_book(c, day)
    pcw = sum(e.get("pcw", False) and e["date"] == day for e in c["queue"])
    pcw += sum(e["date"] == day and not e.get("cancelled") for e in c["training"]["practice"])
    require(c["team"] not in official or all(tr.DRILLS[s["kind"]][2] <= 0 for s in rows),
            "В день официальной встречи доступны отдых и восстановление")
    for pid in tr.members(c, pack, c["team"]):
        intensity = c["training"]["programs"].get(pid, {}).get("intensity", 1)
        load = sum(max(0,tr.DRILLS[s["kind"]][2]) * (intensity if s.get("player") else 1)
                   for s in rows if s.get("player", pid) == pid)
        require(load + (pcw + extra) * 16 <= tr.MAX_LOAD, "Превышена допустимая дневная нагрузка")


def change(c, pack, db, value):
    t, team, action = c["training"], c["team"], value.get("action")
    ids = tr.members(c, pack, team)
    if action == "program":
        pid = value.get("player")
        require(isinstance(pid, str) and pid in ids, "Выберите игрока клуба")
        role, intensity, coach = (value.get(k) for k in ("role","intensity","coach"))
        require(isinstance(role, str) and role in skills.ROLE_WEIGHTS and type(intensity) in (float,int)
                and intensity in (.65, 1, 1.25), "Выберите роль и интенсивность")
        require(coach is None or isinstance(coach,str) and coach in staff.team_people(c,pack,team), "Специалист отсутствует в штабе")
        t["programs"][pid] = dict(role=role, intensity=intensity, coach=coach,
                                   skills=selection(value.get("skills"), tr.PUBLIC, 3),
                                   maps=selection(value.get("maps"), tr.maps(c), 3))
        for day, rows in t["plans"].items():
            check_load(c, pack, day, rows)
        return
    day = day_value(value.get("date"))
    if action in ("template", "apply"):
        require(tr.monday(day) == day, "Выберите неделю")
        name = value.get("name")
        require(isinstance(name,str) and 0 < len(name.strip()) <= 48, "Введите название шаблона")
        name = name.strip()
        if action == "template":
            t["templates"][name] = [deepcopy(t["days"].get(d, {}).get("sessions", current(c,pack,d))) for d in
                                     (tr.offset(day,i) for i in range(7))]
        else:
            require(name in t["templates"], "Шаблон не найден")
            for i, rows in enumerate(t["templates"][name]):
                d = tr.offset(day, i)
                if d < c["date"]:
                    continue
                copy = [{k:v for k,v in r.items() if k not in ("quality","specialist")} for r in rows]
                if c["team"] in set.union(*tr.schedule_book(c,d)):
                    copy = [dict(kind="recovery")]
                check_load(c,pack,d,copy)
                t["plans"][d] = copy
        return
    require(day >= c["date"], "Прошедшие занятия завершены")
    if action == "cancel-pcw":
        event = next((e for e in c["queue"] if e.get("pcw") and e["id"] == value.get("id") and team in e["teams"] and e["date"] == day), None)
        require(event, "Пракк уже завершён")
        c["queue"].remove(event)
        return
    rows = list(current(c,pack,day))
    if action == "auto":
        t["plans"].pop(day,None)
        return
    if action == "pcw":
        other, map_id, goal = (value.get(k) for k in ("opponent","map","goal"))
        require(isinstance(other,str) and other != team and other in c["teams"]
                and set(ids).isdisjoint(tr.members(c,pack,other)), "Выберите доступный состав соперника")
        require(isinstance(map_id,str) and map_id in tr.maps(c) and goal in ("synergy","attack","defense","retake","utility"), "Выберите карту и цель пракка")
        count, watch = value.get("games"), value.get("watch")
        require(type(count) is int and count in (1,2) and type(watch) is bool, "Выберите формат и режим пракка")
        busy = set.union(*tr.schedule_book(c,day))
        require(not ({team,other} & busy), "Соперник или команда заняты в этот день")
        check_load(c, pack, day, rows if day in t["plans"] else [], extra=count)
        board = ref(db, value.get("tactic"), map_id, "pcw")
        for i in range(count):
            pair = [team,other] if i == 0 else [other,team]
            c["queue"].append(tr.fixture(c,day,*pair,map_id,goal,watch,i) | board)
        competitions.order(c)
        return
    index = value.get("index")
    require(type(index) is int and 0 <= index <= len(rows), "Выберите окно занятия")
    if action == "remove":
        require(index < len(rows), "Занятие отсутствует")
        rows.pop(index)
    elif action == "session":
        kind, pid, map_id = (value.get(k) for k in ("kind","player","map"))
        require(isinstance(kind,str) and kind in tr.DRILLS and kind != "pcw", "Выберите направление")
        require(pid is None or isinstance(pid,str) and pid in ids, "Игрок отсутствует в составе")
        row = dict(kind=kind)
        if pid:
            row["player"] = pid
        if map_id:
            require(map_id in tr.maps(c), "Карта недоступна")
            row["map"] = map_id
        if kind in ("map","attack","defense","retake"):
            require(map_id, "Выберите карту занятия")
        if kind == "opponent":
            other = value.get("opponent")
            require(isinstance(other,str) and other != team and other in c["teams"], "Выберите соперника для анализа")
            row["opponent"] = other
        if kind == "review":
            event = next((e for e in reversed(c["history"]) if e["id"] == value.get("match") and team in e["teams"]),None)
            require(event, "Выберите сыгранный матч клуба")
            row["match"] = event["id"]
        row.update(ref(db, value.get("tactic"), map_id, kind))
        rows[index:index+1] = [row]
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
        official, reserved = tr.schedule_book(c,day)
        saved = t["days"].get(day, {})
        days.append(dict(date=day, sessions=saved.get("sessions", []) if day < c["date"] else current(c,pack,day),
                         official=team in official, fatigue=saved.get("fatigue",{}),
                         manual=day in t["plans"], practices=[e for e in [*c["queue"],*t["practice"]]
                             if e.get("pcw") and e["date"]==day and team in e["teams"]]))
    ids = tr.members(c,pack,team)
    people = {}
    for pid in ids:
        row = t["players"].get(pid, {})
        base = pack["players"][pid]
        recent = [(d, h["fatigue"][pid]) for d,h in t["days"].items() if pid in h["fatigue"]][-14:]
        people[pid] = dict(fatigue=round(row.get("fatigue",0),1), practice=round(row.get("practice",0),1),
                 trend=recent, skills={k:round(row.get("skills",{}).get(k,base["skills"][k]) - base["skills"][k],2) for k in tr.PUBLIC},
                 maps=base["mapKnowledge"] | row.get("mapKnowledge",{}), roles=base["roleMastery"] | row.get("roleMastery",{}),
                 tactics=row.get("tactics",{}))
    boards = [dict(tactics.reference(p),map=p["map"]) for p in tactic_library.catalog(db)["plans"]]
    return dict(days=days, players=people, maps=tr.maps(c), catalog=tr.DRILLS, programs=t["programs"],
                templates=sorted(t["templates"]), boards=boards, history=t["weekStats"],
                teams=[other for other in c["teams"] if other != team and set(ids).isdisjoint(tr.members(c, pack, other))])
