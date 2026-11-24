"""Versioned pre-match source packages. Match checkpoints contain only the selected ten."""

import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path

from . import match, skills, world

GROUPS = ("players", "teams", "organizations", "staff", "rosters")
VERSIONS = dict(
    format=1,
    world=world.VERSION,
    skills=skills.VERSION,
    rating=skills.RATING_VERSION,
    rules=match.VERSION,
    map=match.MAP["version"],
)
STARTER = Path(__file__).with_name("data") / "austin.json"
REGIONS = ("Europe", "Americas", "Asia")
STATUSES = ("confirmed", "estimated", "modeled", "unknown")
FIELDS = dict(
    players={
        "role",
        "skills",
        "potential",
        "contract",
        "realName",
        "born",
        "nationality",
        "photo",
        "mapKnowledge",
        "roleMastery",
        "statistics",
    },
    teams={"region", "tier", "organization"},
    staff={"team", "role", "realName", "preparation"},
    organizations={"founded", "website"},
    rosters={"team", "players", "captain", "date"},
)
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}\Z")


def encode(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def envelope(pack):
    return dict(package=pack, sha256=hashlib.sha256(encode(pack).encode()).hexdigest())


def read_json(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError(f"Повтор ключа JSON: {k}")
            result[k] = v
        return result

    return json.loads(raw, object_pairs_hook=unique)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def day(value):
    parsed = date.fromisoformat(value)
    require(value == parsed.isoformat(), "Нужна дата ГГГГ-ММ-ДД")
    return parsed


def valid_id(key):
    require(
        isinstance(key, str)
        and IDENT.fullmatch(key)
        and key
        not in {"constructor", "prototype", "toString", "valueOf", "hasOwnProperty"},
        f"Недопустимый ID: {key}",
    )


def label(value):
    require(
        isinstance(value, str) and 0 < len(value.strip()) <= 240,
        "Пустое или слишком длинное название",
    )


def reference(value, rows, field):
    require(
        isinstance(value, str) and value in rows, f"{field}: отсутствует запись {value}"
    )


def validate(pack):
    try:
        _validate(pack)
    except (KeyError, TypeError, AttributeError, IndexError) as exc:
        raise ValueError(f"Некорректная структура пакета: {exc}") from exc
    return pack


def _validate(p):
    require(
        set(p)
        == {
            "versions",
            "id",
            "title",
            "revision",
            "asOf",
            "origins",
            "history",
            *GROUPS,
        },
        "Неверный набор разделов пакета",
    )
    require(
        encode(p["versions"]) == encode(VERSIONS),
        "Несовместимые версии пакета, мира, карты или правил",
    )
    valid_id(p["id"])
    label(p["title"])
    require(type(p["revision"]) is int and p["revision"] > 0, "Некорректная редакция")
    cutoff = day(p["asOf"])
    origins = p["origins"]
    for k, o in origins.items():
        valid_id(k)
        require(
            set(o) == {"status", "date", "reference"} and o["status"] in STATUSES,
            "Некорректное происхождение",
        )
        day(o["date"])
        require(
            isinstance(o["reference"], str) and 0 < len(o["reference"]) <= 1500,
            "Укажите источник",
        )
        if o["status"] == "confirmed":
            require(
                o["reference"].startswith("https://") and day(o["date"]) <= cutoff,
                "Факту нужна ссылка и дата на момент среза",
            )
    for group in GROUPS:
        for ident, r in p[group].items():
            valid_id(ident)
            try:
                require(
                    set(r) == {"name", "origin", "fields", *FIELDS[group]},
                    "Некорректный набор полей",
                )
                label(r["name"])
                reference(r["origin"], origins, "Источник")
                allowed = {"name", *FIELDS[group]}
                if group == "players":
                    allowed.update("skills." + s for s in skills.KEYS)
                require(
                    isinstance(r["fields"], dict) and r["fields"].keys() <= allowed,
                    "Неизвестное поле происхождения",
                )
                for key in r["fields"].values():
                    reference(key, origins, "Источник поля")
                if group == "players":
                    for field in ("realName", "nationality"):
                        if r[field] is not None:
                            label(r[field])
                    if r["born"] is not None:
                        require(day(r["born"]) <= cutoff, "Дата рождения позже среза")
                    require(
                        r["photo"] in (None, "zywoo-chicago-2019"),
                        "Неизвестная лицензия портрета",
                    )
                    for field, allowed_keys in (
                        ("mapKnowledge", {"depo"}),
                        ("roleMastery", set(world.ROLE_NAMES)),
                    ):
                        require(
                            isinstance(r[field], dict)
                            and r[field].keys() <= allowed_keys,
                            "Неизвестная карта или роль",
                        )
                        for v in r[field].values():
                            skills.points(v)
                    stat = r["statistics"]
                    if stat is not None:
                        require(
                            set(stat)
                            == {
                                "event",
                                "date",
                                "maps",
                                "kills",
                                "deaths",
                                "assists",
                                "adr",
                                "opponent",
                            },
                            "Неверные поля статистики",
                        )
                        label(stat["event"])
                        label(stat["opponent"])
                        require(
                            day(stat["date"]) <= cutoff
                            and type(stat["maps"]) is int
                            and stat["maps"] > 0,
                            "Некорректная выборка",
                        )
                        for k in ("kills", "deaths", "assists", "adr"):
                            require(
                                type(stat[k]) is int and stat[k] >= 0,
                                "Некорректная статистика",
                            )
                    require(
                        r["role"] is None or r["role"] in world.ROLE_NAMES,
                        "Неизвестная роль",
                    )
                    require(
                        r["contract"] in (None, "free"), "Неизвестный тип контракта"
                    )
                    require(
                        isinstance(r["skills"], dict)
                        and set(r["skills"]) == set(skills.KEYS),
                        "Нужны все 58 характеристик",
                    )
                    for s, v in r["skills"].items():
                        skills.points(v)
                        k = r["fields"].get(
                            "skills." + s, r["fields"].get("skills", r["origin"])
                        )
                        require(
                            origins[k]["status"] in ("modeled", "estimated"),
                            "Навык должен быть моделью или оценкой",
                        )
                    if r["potential"] is not None:
                        skills.points(r["potential"])
                        require(
                            origins[r["fields"].get("potential", r["origin"])]["status"]
                            in ("estimated", "modeled"),
                            "Потенциал — оценка",
                        )
                if group == "teams":
                    require(r["region"] in (None, *REGIONS), "Неизвестный регион")
                    require(
                        r["tier"] is None
                        or type(r["tier"]) is int
                        and 1 <= r["tier"] <= 3,
                        "Тир должен быть 1–3",
                    )
                    if r["organization"] is not None:
                        reference(r["organization"], p["organizations"], "Организация")
                if group == "organizations":
                    y = r["founded"]
                    require(
                        y is None or type(y) is int and 1800 <= y <= cutoff.year,
                        "Некорректный год основания",
                    )
                    site = r["website"]
                    require(
                        site is None
                        or isinstance(site, str)
                        and re.fullmatch(r"https://[A-Za-z0-9.-]+(?:/[^\s]*)?", site),
                        "Сайт должен иметь HTTPS-адрес",
                    )
                if group == "staff":
                    if r["realName"] is not None:
                        label(r["realName"])
                    skills.points(r["preparation"])
                    require(
                        origins[r["fields"].get("preparation", r["origin"])]["status"]
                        in ("modeled", "estimated"),
                        "Подготовка штаба должна быть оценкой",
                    )
                    label(r["role"])
                    if r["team"] is not None:
                        reference(r["team"], p["teams"], "Команда сотрудника")
                if group == "rosters":
                    reference(r["team"], p["teams"], "Команда состава")
                    require(day(r["date"]) <= cutoff, "Состав позже даты среза")
                    lineup = r["players"]
                    require(
                        isinstance(lineup, list)
                        and len(lineup) <= 5
                        and len(set(lineup)) == len(lineup),
                        "В пятёрке до пяти разных игроков",
                    )
                    for player in lineup:
                        reference(player, p["players"], "Игрок состава")
                    require(
                        r["captain"] is None or r["captain"] in lineup,
                        "Капитан должен входить в состав",
                    )
            except ValueError as exc:
                raise ValueError(f"{group}/{ident}: {exc}") from exc
    for key, h in p["history"].items():
        valid_id(key)
        require(
            set(h)
            == {"date", "team", "opponent", "outcome", "players", "origin", "event"},
            "Неверная запись истории",
        )
        reference(h["team"], p["teams"], "Команда в истории")
        reference(h["origin"], origins, "Источник результата")
        label(h["opponent"])
        if h["event"] is not None:
            label(h["event"])
        require(
            h["outcome"] in ("W", "L") and day(h["date"]) <= cutoff,
            "Некорректные дата или результат",
        )
        require(
            isinstance(h["players"], list)
            and len(h["players"]) in (0, 5)
            and len(set(h["players"])) == len(h["players"]),
            "Некорректная историческая пятёрка",
        )
        for player in h["players"]:
            reference(player, p["players"], "Игрок в истории")


def installed(db):
    rows = db.execute(
        "SELECT id,title,revision FROM data_pack ORDER BY title,id,revision DESC"
    )
    return [dict(id=k, title=t, revision=r) for k, t, r in rows]


def put(db, p):
    validate(p)
    db.execute(
        "INSERT INTO data_pack VALUES(?,?,?,?)",
        (p["id"], p["revision"], p["title"], encode(p)),
    )


def get(db, key, rev):
    row = db.execute(
        "SELECT body FROM data_pack WHERE id=? AND revision=?", (key, rev)
    ).fetchone()
    require(row, "Редакция пакета не найдена")
    return json.loads(row[0])


def install(db, raw):
    obj = read_json(raw)
    p = validate(obj["package"])
    require(
        envelope(p)["sha256"] == obj.get("sha256"),
        "Контрольная сумма SHA-256 не совпала",
    )
    row = db.execute(
        "SELECT body FROM data_pack WHERE id=? AND revision=?", (p["id"], p["revision"])
    ).fetchone()
    if row:
        require(row[0] == encode(p), "ID и редакция уже заняты другим содержимым")
    else:
        put(db, p)
    return dict(id=p["id"], revision=p["revision"])


def edit(db, key, rev, group, ident, record, create):
    require(group in GROUPS, "Неизвестный раздел")
    valid_id(ident)
    p = get(db, key, rev)
    latest = db.execute(
        "SELECT max(revision) FROM data_pack WHERE id=?", (key,)
    ).fetchone()[0]
    require(rev == latest, "Пакет изменён. Откройте последнюю редакцию")
    rows = p[group]
    require((ident not in rows) == create, "ID уже занят или запись отсутствует")
    if record is None:
        require(not create, "Отсутствует запись")
        del rows[ident]
    else:
        old = rows.get(ident, {})
        source = "edit-" + str(rev + 1)
        p["origins"][source] = dict(
            date=date.today().isoformat(),
            status="modeled",
            reference="Правка пользователя",
        )
        row = {
            **record,
            "origin": old.get("origin", source),
            "fields": dict(old.get("fields", {})),
        }
        for field in {"name", *FIELDS[group]}:
            if field == "skills" and old:
                for s in skills.KEYS:
                    if old[field][s] != row[field][s]:
                        row["fields"]["skills." + s] = source
            elif old and row[field] != old[field]:
                row["fields"][field] = source
        rows[ident] = row
    p["revision"] += 1
    put(db, p)
    return dict(id=key, revision=p["revision"])


def match_input(p, roster_ids):
    require(
        isinstance(roster_ids, list) and len(roster_ids) == 2, "Выберите два состава"
    )
    domain = dict(
        version=world.VERSION,
        skillVersion=skills.VERSION,
        ratingVersion=skills.RATING_VERSION,
        source=dict(id=p["id"], revision=p["revision"]),
        players={},
        organizations={},
        teams={},
        rosters={},
        staff={},
        chemistry={},
        assessments={},
    )
    for rid in roster_ids:
        reference(rid, p["rosters"], "Состав")
        r = p["rosters"][rid]
        tid = r["team"]
        t = p["teams"][tid]
        require(tid not in domain["teams"], "Выберите разные команды")
        require(len(r["players"]) == 5, "Для BO1 нужны пять игроков в каждом составе")
        org = t["organization"] or "@team-" + tid
        domain["organizations"][org] = dict(name=p["organizations"].get(org, t)["name"])
        domain["teams"][tid] = dict(name=t["name"], organization=org)
        members = []
        for slot, pid in enumerate(r["players"]):
            require(pid not in domain["players"], "Один игрок заявлен за обе команды")
            player = p["players"][pid]
            role = player["role"] or world.SLOT_ROLES[slot]
            domain["players"][pid] = dict(
                name=player["name"],
                skills=deepcopy(player["skills"]),
                potential=player["potential"],
                mapKnowledge=deepcopy(player["mapKnowledge"]),
                roleMastery=deepcopy(player["roleMastery"]),
                form=50,
                morale=50,
                fatigue=0,
                languages=[],
            )
            members.append(
                dict(
                    id=f"{rid}:{slot}",
                    player=pid,
                    role=role,
                    captain=pid == (r["captain"] or r["players"][0]),
                    since=r["date"],
                    until=None,
                )
            )
        domain["rosters"][rid] = dict(team=tid, members=members)
        for sid, s in p["staff"].items():
            if s["team"] == tid:
                domain["staff"][sid] = dict(
                    name=s["name"],
                    team=tid,
                    role=s["role"],
                    preparation=s["preparation"],
                )
    domain["authority"] = dict(
        mode="manager",
        organization=next(iter(domain["teams"].values()))["organization"],
    )
    return domain
