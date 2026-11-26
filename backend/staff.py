"""R5.1 professional profiles and daily work. People and club membership belong to the scene."""

from functools import lru_cache
from hashlib import sha256
from statistics import mean

ROLES = dict(
    head="Главный тренер",
    assistant="Ассистент тренера",
    tactical="Тактический тренер",
    individual="Тренер по индивидуальным навыкам",
    analyst="Аналитик",
    psychologist="Спортивный психолог",
    chief_scout="Главный скаут",
    scout="Скаут",
)
GROUPS = {
    "Тренерские": dict(
        mechanics="Механика",
        individual_tactics="Индивидуальная тактика",
        team_tactics="Командная тактика",
        utility="Работа с гранатами",
        maps="Знание карт",
        fitness="Физическая подготовка",
    ),
    "Педагогические": dict(
        teaching="Обучение",
        youth="Развитие молодёжи",
        individualisation="Индивидуальный подход",
        motivation="Мотивация",
        discipline="Дисциплина",
    ),
    "Аналитические": dict(
        opponent="Анализ соперника",
        matches="Анализ матчей",
        reading="Чтение игры",
        meta="Адаптация к мете",
    ),
    "Скаутские": dict(
        ability="Оценка способностей",
        potential="Оценка потенциала",
        fit="Оценка совместимости",
        discovery="Поиск талантов",
    ),
    "Управленческие": dict(
        leadership="Лидерство",
        communication="Коммуникация",
        organisation="Организация",
        conflicts="Управление конфликтами",
        mental="Психологическая подготовка",
    ),
}
# Primary competencies count twice, supporting competencies once.
WEIGHTS = {
    "head": (
        "leadership team_tactics organisation",
        "communication conflicts discipline motivation reading",
    ),
    "assistant": (
        "teaching communication organisation",
        "individualisation motivation maps discipline",
    ),
    "tactical": ("team_tactics utility maps", "reading meta matches teaching"),
    "individual": (
        "mechanics individual_tactics individualisation",
        "teaching youth fitness utility",
    ),
    "analyst": ("opponent matches reading", "maps team_tactics meta"),
    "psychologist": (
        "mental conflicts individualisation",
        "communication motivation discipline fitness",
    ),
    "chief_scout": (
        "discovery potential organisation",
        "leadership fit ability communication",
    ),
    "scout": ("ability potential discovery fit", "reading youth meta"),
}
PREFERENCES = {
    "Стиль игры": ["Агрессивный", "Сбалансированный", "Осторожный"],
    "Тактический подход": ["Структурированный", "Гибкий", "Импровизационный"],
    "Подготовка": ["Универсальность", "Специализация на картах"],
    "Развитие": ["Молодые таланты", "Опытные игроки"],
    "Дисциплина": ["Строгая", "Свободная"],
    "Нагрузка": ["Щадящая", "Интенсивная"],
    "Адаптация": ["Консервативная", "Экспериментальная"],
}
# Stage, professional inputs and workload units for a single day of actual work.
DUTIES = {
    "veto": ("Подготовка к Map Veto", "R5.1", "maps reading opponent team_tactics", 2),
    "opponent": ("Анализ соперников", "R5.1", "opponent matches reading meta", 2),
    "schedule": (
        "Тренировочное расписание",
        "R5.2",
        "organisation teaching discipline fitness",
        2,
    ),
    "individual": (
        "Индивидуальная подготовка",
        "R5.2",
        "mechanics individual_tactics individualisation teaching youth",
        2,
    ),
    "tactics": ("Подготовка тактик", "R5.1", "team_tactics utility maps meta", 2),
    "practice": (
        "Организация пракков",
        "R5.2",
        "communication organisation team_tactics",
        2,
    ),
    "recovery": (
        "Восстановление игроков",
        "R5.2",
        "fitness mental conflicts motivation",
        1,
    ),
    "search": ("Поиск новых игроков", "R5.3", "ability potential fit discovery", 2),
    "dispatch": (
        "Распределение заданий скаутам",
        "R5.3",
        "leadership organisation discovery communication",
        1,
    ),
}
MODEL = "staff.1"


def position(value):
    return next((k for k, title in ROLES.items() if value in (k, title)), "head")


def draw(person, key):
    return int.from_bytes(
        sha256(f"{MODEL}/{person}/{key}".encode()).digest()[:4], "big"
    )


def profile(person, row):
    return _profile(person, position(row["role"]), row["preparation"])


@lru_cache(maxsize=4096)
def _profile(person, role, base):
    primary, secondary = (s.split() for s in WEIGHTS[role])
    attributes = {}
    for group in GROUPS.values():
        for key in group:
            offset = 7 if key in primary else -2 if key in secondary else -16
            attributes[key] = min(
                100, max(0, base + offset + draw(person, key) % 25 - 12)
            )
    philosophy = {
        k: options[draw(person, k) % len(options)] for k, options in PREFERENCES.items()
    }
    ratings = {}
    for key, (major, minor) in WEIGHTS.items():
        weights = major.split() * 2 + minor.split()
        ratings[key] = round(mean(attributes[s] for s in weights))
    return dict(
        attributes=attributes, philosophy=philosophy, ratings=ratings, model=MODEL
    )


def office():
    return dict(version=1, positions={}, duties={}, ledger={})


def team_people(c, pack, team):
    overrides = c.get("office", {}).get("positions", {})
    return {
        sid: dict(
            id=sid,
            name=row["name"],
            realName=row.get("realName"),
            born=row.get("born"),
            role=overrides.get(sid, position(row["role"])),
            publishedRole=row.get("publishedRole"),
            **profile(sid, row),
        )
        for sid, row in pack["staff"].items()
        if row["team"] == team
    }


def capacity(person):
    return 3 + person["attributes"]["organisation"] // 35


def quality(person, duty):
    return round(
        0.8 * mean(person["attributes"][key] for key in DUTIES[duty][2].split())
        + 0.2 * person["ratings"][person["role"]]
    )


def assignments(c, team, people):
    if team == c["team"]:
        return dict(c.get("office", {}).get("duties", {}))
    result = {}
    for duty in DUTIES:
        candidates = [
            p
            for p in people.values()
            if list(result.values()).count(p["id"]) < capacity(p)
        ]
        if candidates:
            best = max(
                candidates,
                key=lambda p: (
                    quality(p, duty) - 12 * list(result.values()).count(p["id"]),
                    p["id"],
                ),
            )
            result[duty] = best["id"]
    return result


def change(c, pack, value):
    from .database import require

    office_state = c.setdefault("office", office())
    sid = value.get("person")
    people = team_people(c, pack, c["team"])
    require(
        sid is None or isinstance(sid, str) and sid in people,
        "Сотрудник не входит в штаб клуба",
    )
    if set(value) == {"person", "role"}:
        role = value["role"]
        require(
            sid and isinstance(role, str) and role in ROLES, "Неизвестная должность"
        )
        require(
            role != "head"
            or not any(p["role"] == role and p["id"] != sid for p in people.values()),
            "Должность главного тренера уже занята",
        )
        office_state["positions"][sid] = role
    else:
        duty = value.get("duty")
        require(
            set(value) == {"person", "duty"}
            and isinstance(duty, str)
            and duty in DUTIES,
            "Неизвестная обязанность",
        )
        duties = office_state["duties"]
        if sid:
            require(
                sum(p == sid for k, p in duties.items() if k != duty)
                < capacity(people[sid]),
                "Достигнут предел обязанностей сотрудника",
            )
            duties[duty] = sid
        else:
            duties.pop(duty, None)


def day_plan(c, pack, team, day):
    """Allocate today's actual series in calendar order. Completed fixtures retain their costs."""
    people = team_people(c, pack, team)
    owners = assignments(c, team, people)
    ledger = c.get("office", {}).get("ledger", {})
    jobs = [j for j in ledger.get("jobs", []) if j["team"] == team and j["date"] == day]
    used = {sid: sum(j["cost"] for j in jobs if j["person"] == sid) for sid in people}
    frozen = {j["event"] for j in jobs}
    for event in c["queue"]:
        if (
            event["id"] in frozen
            or not event.get("bestOf")
            or team not in event["teams"]
            or event["date"] != day
        ):
            continue
        for duty in ("veto", "opponent"):
            sid = owners.get(duty)
            if sid is None:
                continue
            p = people[sid]
            cost = DUTIES[duty][3]
            if used[sid] + cost > capacity(p):
                continue
            jobs.append(
                dict(
                    person=sid,
                    name=p["name"],
                    team=team,
                    event=event["id"],
                    date=day,
                    due=day,
                    duty=duty,
                    cost=cost,
                    quality=max(0, quality(p, duty) - 3 * used[sid]),
                    philosophy=p["philosophy"],
                )
            )
            used[sid] += cost
    return jobs


def booked(c, pack, event):
    return [
        j
        for team in event["teams"]
        for j in day_plan(c, pack, team, event["date"])
        if j["event"] == event["id"]
    ]


def record(c, jobs, day):
    office_state = c.setdefault("office", office())
    old = [j for j in office_state["ledger"].get("jobs", []) if j["date"] == day]
    keys = {(j["event"], j["team"], j["duty"]) for j in old}
    office_state["ledger"] = {
        "jobs": old
        + [j for j in jobs if (j["event"], j["team"], j["duty"]) not in keys]
    }


def overview(c, pack):
    people = team_people(c, pack, c["team"])
    owners = assignments(c, c["team"], people)
    next_day = next(
        (
            e["date"]
            for e in c["queue"]
            if e.get("bestOf") and c["team"] in e["teams"] and e["date"] > c["date"]
        ),
        None,
    )
    jobs = day_plan(c, pack, c["team"], c["date"])
    if next_day:
        jobs += day_plan(c, pack, c["team"], next_day)
    for p in people.values():
        p["capacity"] = capacity(p)
        p["suitability"] = {d: quality(p, d) for d in DUTIES}
    return dict(
        people=people,
        roles=ROLES,
        groups=GROUPS,
        owners=owners,
        duties={k: dict(title=v[0], stage=v[1]) for k, v in DUTIES.items()},
        jobs=[
            {k: v for k, v in j.items() if k not in ("plan", "philosophy")}
            for j in jobs
        ],
    )


def registered_coach(c, pack, team):
    people = team_people(c, pack, team)
    eligible = [
        p
        for p in people.values()
        if p["role"] in ("head", "assistant", "tactical", "individual")
    ]
    return (
        max(
            eligible, key=lambda p: (p["role"] == "head", p["ratings"]["head"], p["id"])
        )["id"]
        if eligible
        else None
    )


def draft_job(c, side, buy, map_id):
    return next(
        (
            j
            for j in c.get("office", {}).get("ledger", {}).get("jobs", [])
            if j["date"] == c["date"]
            and j["team"] == c["team"]
            and j["duty"] == "tactics"
            and j["person"] == c["office"]["duties"].get("tactics")
            and j.get("request") == [side, buy, map_id]
        ),
        None,
    )


def prepare_draft(c, pack, value):
    from math import hypot
    from . import tactics
    from .database import require

    side, buy, map_id = (value.get(k) for k in ("side", "buy", "map_id"))
    require(
        set(value) == {"side", "buy", "map_id"}
        and all(isinstance(v, str) for v in (side, buy, map_id)),
        "Укажите карту, сторону и закупку",
    )
    team = c["team"]
    sid = c.get("office", {}).get("duties", {}).get("tactics")
    require(sid, "Подготовка тактик находится под личным управлением")
    if draft_job(c, side, buy, map_id):
        return
    person = team_people(c, pack, team)[sid]
    used = sum(
        j["cost"] for j in day_plan(c, pack, team, c["date"]) if j["person"] == sid
    )
    cost = DUTIES["tactics"][3]
    require(
        used + cost <= capacity(person),
        "У специалиста нет времени на новый тактический план сегодня",
    )
    grade = max(0, quality(person, "tactics") - used * 3)
    key = f"draft/{sid}/{side}/{buy}/{map_id}"
    seed = draw(sid, c["date"] + key)
    philosophy = person["philosophy"]

    def preference(plan):
        lengths = [
            sum(
                hypot(b["x"] - a["x"], b["y"] - a["y"])
                for a, b in zip(steps, steps[1:])
            )
            for steps in plan["slots"]
        ]
        spread = max(lengths) - min(lengths)
        structure = {"Структурированный": -1, "Гибкий": 0, "Импровизационный": 1}[
            philosophy["Тактический подход"]
        ]
        tempo = {"Агрессивный": -1, "Сбалансированный": 0, "Осторожный": 1}[
            philosophy["Стиль игры"]
        ]
        return structure * spread + tempo * mean(lengths)

    plans = (
        tactics.propose(side, buy, seed + i, map_id=map_id)
        for i in range(1 + grade // 25)
    )
    plan = max(plans, key=preference)
    job = dict(
        person=sid,
        name=person["name"],
        team=team,
        event=key,
        date=c["date"],
        due=c["date"],
        duty="tactics",
        cost=cost,
        quality=grade,
        request=[side, buy, map_id],
        plan=plan,
    )
    record(c, [job], c["date"])
