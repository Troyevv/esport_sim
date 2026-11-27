"""Career-owned training. The immutable scene supplies initial values and identities."""

import base64
import json
import zlib
from functools import lru_cache
from random import Random
from datetime import date, timedelta
from itertools import combinations
from zlib import crc32

from . import database, registrations, skills, staff, world

# Title, instructional goal, workload, specialist competency and targeted attributes.
DRILLS = {
    "mechanics": (
        "Стрельба и механика",
        "Стабилизировать первый выстрел и контроль отдачи",
        14,
        "mechanics",
        "aim first_shot recoil",
    ),
    "program": (
        "Индивидуальная программа",
        "Развить выбранные навыки, роль и карты игрока",
        12,
        "individualisation",
        "decisions timing",
    ),
    "individual": (
        "Индивидуальная тактика",
        "Выбирать позицию и момент выхода",
        10,
        "individual_tactics",
        "positioning timing decisions",
    ),
    "team": (
        "Командная тактика",
        "Согласовать колл и исполнение плана",
        12,
        "team_tactics",
        "calling execution",
    ),
    "utility": (
        "Гранаты",
        "Отработать флешки, дымы и тайминги",
        11,
        "utility",
        "flashes smokes timing",
    ),
    "calls": (
        "Коммуникация",
        "Быстро передавать и уточнять информацию",
        8,
        "communication",
        "communication calling",
    ),
    "synergy": (
        "Взаимодействие",
        "Синхронизировать выходы и размены",
        11,
        "team_tactics",
        "trades coordination synchronization",
    ),
    "map": (
        "Изучение карты",
        "Освоить позиции и контроль пространства",
        9,
        "maps",
        "map_control positioning",
    ),
    "attack": (
        "Атакующая тактика",
        "Согласовать выход на точку",
        13,
        "team_tactics",
        "entry execution",
    ),
    "defense": (
        "Защитная тактика",
        "Отработать удержание и ротации",
        12,
        "team_tactics",
        "positioning game_reading",
    ),
    "retake": (
        "Ретейки и постпланты",
        "Разыграть установленную бомбу с обеих сторон",
        13,
        "team_tactics",
        "retakes postplant",
    ),
    "review": (
        "Разбор своего матча",
        "Разобрать решения в сыгранной встрече",
        5,
        "matches",
        "game_reading decisions",
    ),
    "opponent": (
        "Подготовка к сопернику",
        "Прочитать игру выбранного соперника",
        7,
        "opponent",
        "game_reading timing",
    ),
    "fitness": (
        "Физическая подготовка",
        "Развить выносливость",
        16,
        "fitness",
        "endurance fatigue_resistance",
    ),
    "mental": (
        "Психологическая подготовка",
        "Удерживать внимание под давлением",
        6,
        "mental",
        "concentration confidence",
    ),
    "recovery": ("Восстановление", "Снизить накопленную усталость", -9, "fitness", ""),
    "rest": ("Отдых", "Освободить время для восстановления", -6, None, ""),
    "pcw": (
        "Пракк",
        "Проверить подготовку в игровых раундах",
        16,
        "organisation",
        "coordination execution",
    ),
}
ROTATION = (
    "mechanics",
    "utility",
    "attack",
    "map",
    "synergy",
    "retake",
    "individual",
    "defense",
    "calls",
    "team",
    "fitness",
    "mental",
)
PUBLIC = tuple(k for k in skills.KEYS if k not in skills.HIDDEN)
MAX_LOAD = 38


def new(today):
    return dict(
        version=1,
        nextDay=today,
        plans={},
        templates={},
        programs={},
        players={},
        days={},
        practice=[],
        cohesion={},
        weekStats={},
        fixturesPlayed=0,
    )


def offset(day, n):
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def monday(day):
    return offset(day, -date.fromisoformat(day).weekday())


def maps(c):
    return list(dict.fromkeys([*(c.get("mapPool") or []), "depo"]))


def members(c, pack, team):
    return pack["rosters"][c["teams"][team]]["players"]


@lru_cache(maxsize=3)
def baseline(encoded):
    # A checkpoint travels with manual slots and autosaves. Never mutate its decoded rows.
    if not encoded:
        return {"players": {}, "cohesion": {}}
    return json.loads(zlib.decompress(base64.b64decode(encoded)))


def lookup(state, group, key):
    if key in state[group]:
        return state[group][key]
    return baseline(state.get("baseline", ""))[group].get(key, {})


def freeze_day(state):
    # Calendar fixtures change only the ten participants between overnight updates.
    # Keep those changes sparse so each score and match tick needn't serialize the scene.
    prior = baseline(state.get("baseline", ""))
    bulk = {group: prior[group] | state[group] for group in ("players", "cohesion")}
    packed = json.dumps(bulk, separators=(",", ":")).encode()
    state["baseline"] = base64.b64encode(zlib.compress(packed, 1)).decode("ascii")
    state.update(players={}, cohesion={})


def player(state, pid):
    rows = state["players"]
    if pid not in rows:
        old = lookup(state, "players", pid)
        rows[pid] = (
            {k: v.copy() if isinstance(v, dict) else v for k, v in old.items()}
            if old
            else dict(
                skills={},
                mapKnowledge={},
                roleMastery={},
                tactics={},
                fatigue=0.0,
                practice=0.0,
            )
        )
    return rows[pid]


def overlay(domain, state):
    for pid, p in domain["players"].items():
        data = lookup(state, "players", pid)
        if not data:
            continue
        for key in ("skills", "mapKnowledge", "roleMastery"):
            p[key].update({k: round(v) for k, v in data[key].items()})
        p["fatigue"] = round(data["fatigue"])
        p["tactics"] = {k: round(v) for k, v in data["tactics"].items()}
    for r in domain["rosters"].values():
        synergy = lookup(state, "cohesion", r["team"])
        for a, b in combinations(r["members"], 2):
            key = world.pair_key(a["player"], b["player"])
            if key in synergy:
                domain["chemistry"][key] = round(synergy[key])


def schedule_book(c, day):
    """Include finished fixtures and admission days before the draw is published."""
    official, reserved = set(), set()
    for e in c["queue"]:
        if e["date"] == day and e["kind"] == "match":
            (reserved if e.get("pcw") else official).update(e["teams"])
    for e in reversed(c["history"]):
        if e["date"] < day:
            break
        if e["date"] == day:
            official.update(e["teams"])
    for e in c.get("circuit", {}).get("editions", {}).values():
        if (
            e["status"] not in ("registration", "playing")
            or not e["start"] <= day <= e["end"]
        ):
            continue
        for team, status in e["entries"].items():
            if (
                status in registrations.COMMITTED
                and day in registrations.obligation_days(c, e, team)
            ):
                official.add(team)
    for e in reversed(c["training"]["practice"]):
        if e["date"] < day:
            break
        if e["date"] == day and not e.get("cancelled"):
            reserved.update(e["teams"])
    return official, reserved


def roster_staff(c, pack, team):
    people = staff.team_people(c, pack, team)
    return people, staff.assignments(c, team, people)


def default_day(c, pack, team, day, official, reserved, people, owners):
    number = date.fromisoformat(day).toordinal()
    ids = members(c, pack, team)
    data = {pid: lookup(c["training"], "players", pid) for pid in ids}
    fatigue = sum(data.get(pid, {}).get("fatigue", 0) for pid in ids) / len(ids)
    coach = people.get(owners.get("schedule"), {})
    philosophy = coach.get("philosophy", {})
    if team in official or team in reserved or fatigue > 65:
        return [dict(kind="recovery")]
    if number % 7 == 0:
        return [dict(kind="rest")]
    salt = crc32(team.encode())
    organisation = coach.get("attributes", {}).get("organisation", 0)
    kind = ROTATION[(number + salt) % len(ROTATION)]
    if team not in official and organisation >= 50 and number % 3 == 0:
        # Prioritize the squad's weakest area among this week's candidate drills.
        def current_level(direction):
            keys = DRILLS[direction][4].split()
            return sum(
                data.get(p, {})
                .get("skills", {})
                .get(k, pack["players"][p]["skills"][k])
                for p in ids
                for k in keys
            ) / len(keys)

        candidates = [
            ROTATION[(number + salt + i) % len(ROTATION)]
            for i in range(1 + organisation // 25)
        ]
        kind = min(candidates, key=current_level)
    map_id = maps(c)[
        (
            number
            // (7 if philosophy.get("Подготовка") == "Специализация на картах" else 2)
            + salt
        )
        % len(maps(c))
    ]
    row = dict(kind=kind)
    if kind in ("map", "attack", "defense", "retake"):
        row["map"] = map_id
    rows = [row]
    if number % 2 == 0 and fatigue < (
        42 if philosophy.get("Нагрузка") == "Щадящая" else 58
    ):
        ordered = sorted(ids, key=lambda p: pack["players"][p].get("born") or "")
        pid = (
            ordered[-1]
            if philosophy.get("Развитие") == "Молодые таланты" and number % 4 == 0
            else ordered[number % len(ids)]
        )
        rows.append(dict(kind="program", player=pid))
    return rows


def plan(c, pack, team, day, official, reserved, people, owners):
    if team == c["team"] and day in c["training"]["plans"]:
        rows = c["training"]["plans"][day]
        if team in official:
            return [r for r in rows if r["kind"] in ("rest", "recovery")] or [
                dict(kind="recovery")
            ]
        return rows
    return default_day(c, pack, team, day, official, reserved, people, owners)


def gain(row, base, group, key, effort, ceiling):
    values = row[group]
    old = values.get(key, base.get(key, 45))
    # Remaining headroom and current level both slow growth. Preserve imported stars.
    increment = effort * max(0, ceiling - old) / 40 * (1.15 - old / 125)
    values[key] = round(min(100, old + increment), 4)


def age_on(base, as_of, day):
    born = base.get("born") or as_of
    years = int(day[:4]) - int(born[:4]) - (day[5:] < born[5:])
    return years if base.get("born") else 25 + years


def develop(state, pack, pid, session, grade, day, load):
    base = pack["players"][pid]
    s = base["skills"]
    row = player(state, pid)
    program = state["programs"].get(pid, {})
    kind = session["kind"]
    before = row["fatigue"]
    if load < 0:
        row["fatigue"] = round(max(0, before + load * (0.65 + grade / 120)), 2)
        return
    age = age_on(base, pack["asOf"], day)
    individual = bool(session.get("player"))
    intensity = program.get("intensity", 1) if individual else 1
    wear = load * intensity * (1.15 - s["fatigue_resistance"] / 240)
    row["fatigue"] = round(min(100, before + wear), 2)
    aptitude = (s["learning"] + s["professionalism"] + s["motivation"]) / 300
    effort = (
        (0.23 + grade / 175)
        * (0.45 + aptitude)
        * max(0.18, 1.35 - max(0, age - 18) * 0.045)
    )
    effort *= (
        max(0.06, 1 - before / 85)
        * (0.52 + min(0.48, row["practice"] / 35))
        * intensity
    )
    ceiling = base["potential"] if base["potential"] is not None else 82
    targets = session.get("targets") or DRILLS[kind][4].split()
    role = program.get("role") or base.get("role") or "rifler"
    if kind == "program":
        targets = program.get("skills") or list(skills.ROLE_WEIGHTS[role])[:2]
    elif individual:
        targets = [
            key for key in targets if key in program.get("skills", [])
        ] or targets
    if kind == "pcw" and session.get("goal") in DRILLS:
        targets = DRILLS[session["goal"]][4].split()
    for key in targets:
        gain(row, s, "skills", key, effort / max(1, len(targets)), ceiling)
    map_ids = (
        [session["map"]]
        if session.get("map")
        else program.get("maps", []) if kind == "program" else []
    )
    for map_id in map_ids:
        gain(
            row,
            base["mapKnowledge"],
            "mapKnowledge",
            map_id.removeprefix("de_"),
            effort * 1.6 / len(map_ids),
            98,
        )
    if kind == "program":
        gain(row, base["roleMastery"], "roleMastery", role, effort * 2, 97)
    if session.get("tactic"):
        key = tactic_key(session["tactic"])
        gain(row, {key: 0}, "tactics", key, effort * 3 * session.get("exposure", 1), 98)


def tactic_key(board):
    return f"{board['id']}@{board['revision']}"


def train_together(state, team, ids, amount):
    if team not in state["cohesion"]:
        state["cohesion"][team] = lookup(state, "cohesion", team).copy()
    synergy = state["cohesion"][team]
    for a, b in combinations(ids, 2):
        key = world.pair_key(a, b)
        old = synergy.get(key, 0)
        synergy[key] = round(old + amount * (1 - old / 100), 3)


def match_practice(c, pack, event, report):
    state = c["training"]
    count = len(report["rounds"])
    for item in report["stats"]:
        row = player(state, item["player"])
        row["practice"] = min(40, row["practice"] + count / 3)
        if event["date"] != row.get("loadDate"):
            row.update(loadDate=event["date"], matchLoad=0.0)
        prior = row["fatigue"]
        if not event.get("pcw"):
            row["fatigue"] = round(min(100, row["fatigue"] + count * 0.55), 2)
            row["matchLoad"] += row["fatigue"] - prior
    if event.get("pcw"):
        board = event.get("tactic")
        studied = (
            sum(r.get("tactic") == board for r in report["rounds"]) if board else 0
        )
        for team in event["teams"]:
            people, owners = roster_staff(c, pack, team)
            jobs = staff.day_plan(c, pack, team, event["date"])
            used = {
                sid: sum(j["cost"] for j in jobs if j["person"] == sid)
                for sid in people
            }
            assigned = people.get(owners.get("practice"))
            work = []
            grade = coach_job(
                c,
                team,
                event["date"],
                event["id"],
                "practice",
                "team_tactics",
                assigned,
                used,
                work,
            )
            staff.record(c, work, event["date"])
            ids = [s["player"] for s in report["stats"] if s["teamId"] == team]
            train_together(state, team, ids, count / 16)
            for pid in ids:
                row = player(state, pid)
                old = row["fatigue"]
                develop(
                    state,
                    pack,
                    pid,
                    dict(
                        kind="pcw",
                        map=event["mapId"],
                        goal=event["goal"],
                        tactic=board if team == c["team"] and studied else None,
                        exposure=studied / count,
                    ),
                    grade,
                    event["date"],
                    min(24, count * 0.65),
                )
                row["matchLoad"] += row["fatigue"] - old
        state["fixturesPlayed"] += 1


def coach_job(c, team, day, event_id, duty, competency, person, used, jobs):
    if not person:
        return 32
    sid = person["id"]
    cost = staff.DUTIES[duty][3]
    if used.get(sid, 0) + cost > staff.capacity(person):
        return 32
    grade = round(
        (staff.quality(person, duty) + 2 * person["attributes"][competency]) / 3
        - used.get(sid, 0) * 3
    )
    used[sid] = used.get(sid, 0) + cost
    jobs.append(
        dict(
            person=sid,
            name=person["name"],
            team=team,
            date=day,
            due=day,
            duty=duty,
            event=event_id,
            cost=cost,
            quality=max(0, grade),
        )
    )
    return max(0, grade)


def daily_team(c, pack, team, day, official, reserved, ledger, claimed, visiting):
    state = c["training"]
    people, owners = roster_staff(c, pack, team)
    from . import scout_sources
    visitors = [pid for pid, host in visiting.items() if host == team]
    ids = [pid for pid in members(c, pack, team) if pid not in visiting and pid not in claimed]
    ids.extend(visitors)
    claimed.update(ids)
    jobs, used = [], {}
    for j in ledger.get(team, []):
        used[j["person"]] = used.get(j["person"], 0) + j["cost"]
    prefix = f"training/{team}/{day}"
    planner = people.get(owners.get("schedule"))
    if planner and used.get(planner["id"], 0) + staff.DUTIES["schedule"][
        3
    ] > staff.capacity(planner):
        owners = {k: v for k, v in owners.items() if k != "schedule"}
        planner = None
    rows = plan(c, pack, team, day, official, reserved, people, owners)
    if planner and (team != c["team"] or day not in state["plans"]):
        coach_job(c, team, day, prefix, "schedule", "organisation", planner, used, jobs)
    reports = []
    metrics = {}
    if team == c["team"]:
        for pid in ids:
            row = player(state, pid)
            load = row.get("matchLoad", 0) if row.get("loadDate") == day else 0
            metrics[pid] = dict(load=load, recovery=0.0)
    for i, session in enumerate(rows):
        kind = session["kind"]
        _, _, load, competency, _ = DRILLS[kind]
        if load < 0:
            duty = "recovery"
        elif kind in ("opponent", "review"):
            duty = "opponent"
        elif session.get("player") or kind == "mechanics":
            duty = "individual"
        else:
            duty = "tactics"
        owner = state["programs"].get(session.get("player"), {}).get(
            "coach"
        ) or owners.get(duty)
        # A manager can ask an available specialist to run a session personally planned.
        coach = (
            people.get(owner)
            if owner
            else max(
                people.values(),
                key=lambda p: p["attributes"].get(competency, 0),
                default=None,
            )
        )
        booked = len(jobs)
        grade = (
            coach_job(
                c, team, day, f"{prefix}/{i}", duty, competency, coach, used, jobs
            )
            if competency
            else 45
        )
        students = [
            p for p in ids if not session.get("player") or p == session["player"]
        ]
        changes = {}
        for pid in students:
            row = player(state, pid)
            old = row["fatigue"]
            before = row["skills"].copy() if metrics else {}
            develop(state, pack, pid, session, grade, day, load)
            if pid in visitors and load > 0:
                scout_sources.session(c, pack, team, pid, day, i, kind, grade)
            if metrics:
                delta = row["fatigue"] - old
                metrics[pid]["load" if delta >= 0 else "recovery"] += abs(delta)
                diff = {
                    k: round(v - before.get(k, pack["players"][pid]["skills"][k]), 3)
                    for k, v in row["skills"].items()
                    if k in PUBLIC
                    and v != before.get(k, pack["players"][pid]["skills"][k])
                }
                if diff and pid not in visitors:
                    changes[pid] = diff
        if kind in ("synergy", "team", "attack", "defense", "retake"):
            train_together(state, team, students, 0.25 + grade / 110)
        reports.append(
            dict(
                session,
                quality=grade,
                changes=changes,
                specialist=jobs[-1]["name"] if len(jobs) > booked else None,
            )
        )
    for pid in ids:
        row = player(state, pid)
        base = pack["players"][pid]
        row["practice"] = round(row["practice"] * 0.92, 3)
        # Overnight recovery also applies on an otherwise empty day.
        old = row["fatigue"]
        row["fatigue"] = round(max(0.0, old - 7 - base["skills"]["recovery"] / 12), 2)
        if metrics:
            metrics[pid]["recovery"] += old - row["fatigue"]
        row.pop("loadDate", None)
        row.pop("matchLoad", None)
        if day.endswith("-01"):
            age = age_on(base, pack["asOf"], day)
            for key in ("reaction", "flick", "endurance"):
                loss = (
                    max(0, age - 28) * 0.021
                    + max(0, 3 - row["practice"]) * 0.025
                    + max(0, row["fatigue"] - 60) * 0.004
                )
                if loss:
                    row["skills"][key] = round(
                        max(0, row["skills"].get(key, base["skills"][key]) - loss), 4
                    )
    if team == c["team"]:
        state["days"][day] = dict(
            sessions=reports,
            metrics={p: v for p, v in metrics.items() if p not in visitors},
            fatigue={p: round(state["players"][p]["fatigue"], 1) for p in ids if p not in visitors},
        )
        if date.fromisoformat(day).weekday() == 6:
            state["weekStats"][day] = {
                p: {
                    k: round(v, 1)
                    for k, v in state["players"][p]["skills"].items()
                    if k in PUBLIC
                }
                for p in ids if p not in visitors
            }
    return jobs


def practice_pairs(c, pack, day, official, reserved, *, manager_only=False):
    state = c["training"]
    number = date.fromisoformat(day).toordinal()
    rotation = sorted(c["teams"])
    Random(number // 7).shuffle(rotation)
    groups = min(7, max(1, len(rotation) // 2))
    weekday = number % 7
    if weekday >= groups:
        return
    group = rotation[weekday::groups]
    if manager_only and c["team"] not in group:
        return
    loaned = {trial["origin"] for trial in c.get("scouting", {}).get("trials", [])
              if trial["status"] == "active" and trial["start"] <= day <= trial["end"]}
    pool = [
        t
        for t in group
        if t not in official | reserved | loaned
        and (
            t != c["team"]
            or (
                manager_only
                and day not in state["plans"]
                and day not in state.get("skipped", [])
            )
        )
    ]
    booked_players = {
        pid
        for t in official | reserved
        if t in c["teams"]
        for pid in members(c, pack, t)
    }
    for a, b in zip(pool[::2], pool[1::2]):
        if manager_only and c["team"] not in (a, b):
            continue
        left, right = set(members(c, pack, a)), set(members(c, pack, b))
        both = left | right
        if (
            left & right
            or both & booked_players
            or any(lookup(state, "players", p).get("fatigue", 0) > 70 for p in both)
        ):
            continue
        team = c["team"] if manager_only else a
        people, owners = roster_staff(c, pack, team)
        philosophy = people.get(owners.get("practice"), {}).get("philosophy", {})
        goal = {"Агрессивный": "attack", "Осторожный": "defense"}.get(
            philosophy.get("Стиль игры"), "synergy"
        )
        period = (
            number // 7
            if philosophy.get("Подготовка") == "Специализация на картах"
            else number
        )
        map_id = maps(c)[period % len(maps(c))]
        yield dict(fixture(c, day, a, b, map_id, goal, False, 0), delegated=True)
        booked_players.update(both)


def refresh_practices(c, pack):
    from . import competitions

    t = c["training"]
    if not c["office"]["duties"].get("practice"):
        return
    start = max(
        c["date"],
        offset(t["plannedThrough"], 1) if t.get("plannedThrough") else c["date"],
    )
    end = offset(c["date"], 13)
    changed = False
    while start <= end:
        official, reserved = schedule_book(c, start)
        for event in practice_pairs(
            c, pack, start, official, reserved, manager_only=True
        ):
            c["queue"].append(event)
            changed = True
        start = offset(start, 1)
    t["plannedThrough"] = end
    if changed:
        competitions.order(c)


def run_day(c, pack, day):
    from . import career

    state = c["training"]
    official, reserved = schedule_book(c, day)
    jobs, claimed = [], set()
    teams = [c["team"], *sorted(c["teams"].keys() - {c["team"]})]
    for ev in practice_pairs(c, pack, day, official, reserved):
        report = career.simulate(career.initial(pack, c, ev, detailed=False))
        from . import scout_sources
        scout_sources.played(c, pack, ev, report)
        match_practice(c, pack, ev, report)
        reserved.update(ev["teams"])
    ledger = {}
    for j in c["office"]["ledger"].get("jobs", []):
        if j["date"] == day:
            ledger.setdefault(j["team"], []).append(j)
    from . import scouting
    visiting = scouting.attendance(c, pack, day, official | reserved)
    for team in teams:
        jobs.extend(daily_team(c, pack, team, day, official, reserved, ledger, claimed, visiting))
    staff.record(c, jobs, day)
    scouting.daily(c, pack, day)
    state["plans"].pop(day, None)
    if day in state.get("skipped", []):
        state["skipped"].remove(day)
    state["nextDay"] = offset(day, 1)


def fixture(c, day, home, away, map_id, goal, watch, leg):
    ident = f"pcw-{day}-{leg}-{home}-{away}"
    return dict(
        id=ident,
        date=day,
        teams=[home, away],
        kind="match",
        pcw=True,
        mapId=map_id,
        goal=goal,
        watch=watch,
        seed=crc32(ident.encode()) >> 1,
        title="Пракк",
    )


def practice_summary(event, report):
    return dict(
        {k: v for k, v in event.items() if k != "board"},
        score=report["score"],
        rounds=len(report["rounds"]),
        simulation=report["simulation"],
        sides={
            side: sum(r.get("side") == side for r in report["rounds"])
            for side in ("T", "CT")
        },
        stats=[
            {k: s[k] for k in ("player", "name", "k", "d", "damage")}
            for s in report["stats"]
        ],
    )


def unavailable(c, event):
    return bool(set(event["teams"]) & schedule_book(c, event["date"])[0])
