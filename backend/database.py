"""Versioned pre-match source packages. Match checkpoints contain only the selected ten."""

import base64
import hashlib
import json
import re
from copy import deepcopy
from datetime import date
from pathlib import Path

from . import lineup_photos, scene_portraits, club_art, match, skills, world
from .match_rules import SCOREBOT_VERSION

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
RELEASE_ID = "scene-20261125-clubs"
STAFF_RELEASE = "scene-20261125-staff"
NOVEMBER_EDITIONS = (RELEASE_ID, STAFF_RELEASE)
TEAM_TYPES = {"main", "academy", "reserve", "other", "unknown"}
RELEASE = STARTER.with_name("scene-202611.json.gz")
MAPS = (
    "depo",
    "ancient",
    "anubis",
    "cache",
    "dust2",
    "inferno",
    "mirage",
    "nuke",
    "overpass",
    "train",
    "vertigo",
)
OPTIONAL = {
    "players": {"ageEstimate", "sample", "performance", "appearance"},
    "staff": {"nationality", "photo", "publishedRole", "born"},
    "teams": {
        "nationality",
        "logo",
        "kit",
        "teamType",
        "formerOrganization",
        "affiliationEnded",
    },
    "organizations": {"nationality", "logo"},
    "rosters": set(),
}
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


def validate_photo(photo):
    if photo in (None, "zywoo-chicago-2019"):
        return
    require(
        isinstance(photo, dict)
        and set(photo) == {"image", "author", "source", "license", "changes"},
        "Некорректная карточка фотографии",
    )
    label(photo["author"])
    require(
        photo["license"]
        in (
            "CC0",
            "PD-textlogo",
            "Условия G2 Esports",
            "Условия 3DMAX",
            "Условия Team Spirit",
            "MIT",
            "CC BY 2.0",
            "CC BY 3.0",
            "CC BY 4.0",
            "CC BY-SA 2.0",
            "CC BY-SA 3.0",
            "CC BY-SA 4.0",
        ),
        "Неизвестная лицензия фотографии",
    )
    require(
        isinstance(photo["changes"], str) and len(photo["changes"]) <= 240,
        "Некорректное описание изменений фото",
    )
    require(
        isinstance(photo["source"], str)
        and re.fullmatch(r"https://[A-Za-z0-9.-]+(?:/[^\s]*)?", photo["source"]),
        "Нужна HTTPS-ссылка на источник фото",
    )
    image = photo["image"]
    if isinstance(image, str) and re.fullmatch(r"https://[A-Za-z0-9.-]+/[^\s]+", image):
        return
    require(
        isinstance(image, str) and len(image) <= 1400000,
        "Фотография больше 1 МиБ или не указана",
    )
    header, _, payload = image.partition(",")
    signatures = {
        "data:image/jpeg;base64": b"\xff\xd8\xff",
        "data:image/png;base64": b"\x89PNG\r\n\x1a\n",
    }
    require(header in signatures, "Загрузите фотографию JPEG или PNG")
    raw = base64.b64decode(payload, validate=True)
    require(
        len(raw) <= 1024 * 1024 and raw.startswith(signatures[header]),
        "Неверный размер или формат фотографии",
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
        encode(p["versions"])
        in (
            encode(VERSIONS),
            encode(dict(VERSIONS, rules=SCOREBOT_VERSION)),
            encode(dict(VERSIONS, rules=match.PREVIOUS_VERSION)),
        ),
        "Несовместимые версии пакета, мира, карты или правил",
    )
    valid_id(p["id"])
    label(p["title"])
    require(
        type(p["revision"]) is int and 0 < p["revision"] <= 2147483647,
        "Некорректная редакция",
    )
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
                    {"name", "origin", "fields", *FIELDS[group]} <= set(r)
                    and set(r)
                    <= {"name", "origin", "fields", *FIELDS[group], *OPTIONAL[group]},
                    "Некорректный набор полей",
                )
                label(r["name"])
                reference(r["origin"], origins, "Источник")
                allowed = {"name", *FIELDS[group], *OPTIONAL[group]}
                if group == "players":
                    allowed.update("skills." + s for s in skills.KEYS)
                require(
                    isinstance(r["fields"], dict) and r["fields"].keys() <= allowed,
                    "Неизвестное поле происхождения",
                )
                for key in r["fields"].values():
                    reference(key, origins, "Источник поля")
                if group != "players" and r.get("nationality") is not None:
                    label(r["nationality"])
                if group == "staff":
                    validate_photo(r.get("photo"))
                    if r.get("born") is not None:
                        require(day(r["born"]) <= cutoff, "Дата рождения позже среза")
                    if r.get("publishedRole") is not None:
                        label(r["publishedRole"])
                if group in ("teams", "organizations"):
                    validate_photo(r.get("logo"))
                if group == "teams" and r.get("kit") is not None:
                    kit = r["kit"]
                    require(
                        isinstance(kit, dict)
                        and set(kit) == {"primary", "accent", "pattern"},
                        "Некорректная форма команды",
                    )
                    require(
                        all(
                            isinstance(kit[k], str)
                            and re.fullmatch(r"#[0-9a-fA-F]{6}", kit[k])
                            for k in ("primary", "accent")
                        )
                        and kit["pattern"] in ("plain", "sash", "panels", "chevron"),
                        "Неизвестные цвета или рисунок формы",
                    )
                if group == "players":
                    head = r.get("appearance")
                    if head is not None:
                        validate_photo(head)
                        require(
                            isinstance(head, dict)
                            and head["image"].startswith("data:image/png;base64,"),
                            "Слой внешности требует встроенный PNG",
                        )
                        raw = base64.b64decode(
                            head["image"].split(",", 1)[1], validate=True
                        )
                        require(
                            len(raw) > 33
                            and raw[12:16] == b"IHDR"
                            and (
                                int.from_bytes(raw[16:20], "big"),
                                int.from_bytes(raw[20:24], "big"),
                            )
                            in ((240, 280), (480, 560))
                            and raw[25] == 6,
                            "Для головы нужен RGBA PNG 240×280 или 480×560",
                        )
                    age = r.get("ageEstimate")
                    if age is not None:
                        require(
                            type(age) is int and 14 <= age <= 60,
                            "Игровой возраст вне диапазона",
                        )
                        require(
                            origins[r["fields"].get("ageEstimate", r["origin"])][
                                "status"
                            ]
                            in ("estimated", "modeled"),
                            "Для игрового возраста нужна метка оценки",
                        )
                    perf = r.get("performance")
                    if perf is not None:
                        require(
                            isinstance(perf, dict)
                            and set(perf)
                            == {"rating", "maps", "version", "window", "role"},
                            "Неверные поля статистики рейтинга",
                        )
                        require(
                            type(perf["rating"]) in (int, float)
                            and 0 <= perf["rating"] <= 5
                            and type(perf["maps"]) is int
                            and perf["maps"] > 0,
                            "Неверные рейтинг или число карт",
                        )
                        for field in ("window", "version"):
                            label(perf[field])
                        if perf["role"] is not None:
                            label(perf["role"])
                    sample = r.get("sample")
                    if sample is not None:
                        require(
                            isinstance(sample, dict)
                            and set(sample)
                            == {
                                "maps",
                                "series",
                                "wins",
                                "rounds",
                                "awpRounds",
                                "utilityRounds",
                                "from",
                                "until",
                            },
                            "Неверная выборка выступлений",
                        )
                        require(
                            all(
                                type(sample[k]) is int and sample[k] >= 0
                                for k in (
                                    "maps",
                                    "series",
                                    "wins",
                                    "rounds",
                                    "awpRounds",
                                    "utilityRounds",
                                )
                            )
                            and 0
                            <= sample["wins"]
                            <= sample["series"]
                            <= sample["maps"]
                            and max(sample["awpRounds"], sample["utilityRounds"])
                            <= sample["rounds"],
                            "Неверное число карт или побед",
                        )
                        require(
                            day(sample["from"]) <= day(sample["until"]) <= cutoff,
                            "Неверные даты выборки",
                        )
                    for field in ("realName", "nationality"):
                        if r[field] is not None:
                            label(r[field])
                    if r["born"] is not None:
                        require(day(r["born"]) <= cutoff, "Дата рождения позже среза")
                    validate_photo(r["photo"])
                    for field, allowed_keys in (
                        ("mapKnowledge", set(MAPS)),
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
                    require(
                        r.get("teamType", "unknown") in TEAM_TYPES,
                        "Неизвестный тип команды",
                    )
                    former = r.get("formerOrganization")
                    ended = r.get("affiliationEnded")
                    require(
                        not ended or former,
                        "Укажите прежнюю организацию и дату окончания связи",
                    )
                    if former:
                        reference(former, p["organizations"], "Прежняя организация")
                    if ended:
                        require(
                            day(ended) <= cutoff, "Связь завершена после даты среза"
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


def migrate_club_links(db):
    """Append an enriched revision to existing November editing branches, preserving old revisions."""
    branches = db.execute(
        "SELECT id,max(revision) FROM data_pack WHERE id NOT IN (?,?) GROUP BY id",
        (RELEASE_ID, "austin-registration"),
    ).fetchall()
    if not branches:
        return
    release = get(db, RELEASE_ID, 1)
    for key, rev in branches:
        pack = get(db, key, rev)
        if (
            pack["asOf"] != release["asOf"]
            or not pack["teams"].keys() & release["teams"].keys()
        ):
            continue
        changed = False
        by_name = {
            r["name"].casefold(): oid for oid, r in pack["organizations"].items()
        }
        for tid, t in pack["teams"].items():
            src = release["teams"].get(tid)
            if not src or t.get("teamType") or t["name"] != src["name"]:
                continue
            changed = True
            for field in (
                "teamType",
                "organization",
                "formerOrganization",
                "affiliationEnded",
            ):
                if field not in src or t.get(field) is not None or field in t["fields"]:
                    continue
                value = src[field]
                if field in ("organization", "formerOrganization") and value:
                    org = release["organizations"][value]
                    target = by_name.get(org["name"].casefold(), value)
                    if (
                        target in pack["organizations"]
                        and pack["organizations"][target]["name"].casefold()
                        != org["name"].casefold()
                    ):
                        continue
                    if target not in pack["organizations"]:
                        pack["organizations"][target] = deepcopy(org)
                        by_name[org["name"].casefold()] = target
                        for ref in (org["origin"], *org["fields"].values()):
                            pack["origins"].setdefault(ref, release["origins"][ref])
                    value = target
                t[field] = value
                ref = src["fields"].get(field)
                if ref:
                    t["fields"][field] = ref
                    pack["origins"].setdefault(ref, release["origins"][ref])
        if changed:
            pack["revision"] = rev + 1
            put(db, pack)


def shares_organization(pack, first_team, second_team):
    owner = pack["teams"][first_team]["organization"]
    return bool(owner and owner == pack["teams"][second_team]["organization"])


def install_staff_edition(db):
    """Install a new immutable edition. Existing careers keep the revision they selected."""
    from . import staff
    if db.execute("SELECT 1 FROM data_pack WHERE id=? AND revision=1", (STAFF_RELEASE,)).fetchone():
        return
    pack = get(db, RELEASE_ID, 1)
    pack.update(id=STAFF_RELEASE, title="Профессиональная сцена · ноябрь 2026 · штаб R5.1")
    clubs = {row["name"]: key for key, row in pack["teams"].items()}
    for name, full, role, club, date, url in json.loads(STARTER.with_name("staff-20261125.json").read_bytes()):
        sid = "staff-" + name.lower().replace(" ", "-").rstrip("-")
        pack["origins"][sid] = dict(status="confirmed", date=date, reference=url)
        pack["staff"][sid] = dict(name=name, realName=full, role=staff.ROLES[role], team=clubs[club],
                                  preparation=66, origin=sid, fields={"preparation": "scenario"})
    for sid,bio in json.loads(STARTER.with_name("staff-biographies.json").read_bytes()).items():
        row = pack["staff"][sid]
        ref = sid+"-bio"
        pack["origins"][ref] = dict(status="confirmed",date=pack["asOf"],reference=bio["source"])
        for field in ("born","nationality"):
            if field in bio:
                row[field] = bio[field]
                row["fields"][field] = ref
    lead = pack["staff"]["staff-tobiz"]
    lead["publishedRole"] = "Head of Talent Development"
    lead["fields"]["role"] = "scenario"
    pack["staff"]["staff-oskarish"]["publishedRole"] = "Assistant Coach / Analyst"
    put(db, pack)


def installed(db):
    rows = db.execute(
        "SELECT id,title,revision FROM data_pack ORDER BY (id=?) DESC,title,id,revision DESC",
        (STAFF_RELEASE,),
    )
    return [dict(id=k, title=t, revision=r) for k, t, r in rows]


def put(db, p):
    validate(p)
    body = encode(p)
    require(len(body.encode()) + 100 <= 24 * 1024 * 1024, "Пакет больше 24 МиБ")
    db.execute(
        "INSERT INTO data_pack VALUES(?,?,?,?)",
        (p["id"], p["revision"], p["title"], body),
    )


def get(db, key, rev):
    row = db.execute(
        "SELECT body FROM data_pack WHERE id=? AND revision=?", (key, rev)
    ).fetchone()
    require(row, "Редакция пакета не найдена")
    return json.loads(row[0])


def get_record(db, key, rev, group, ident):
    require(group in GROUPS, "Неизвестный раздел пакета")
    valid_id(ident)
    path = f'$."{group}"."{ident}"'
    row = db.execute(
        "SELECT json_extract(body, ?) FROM data_pack WHERE id=? AND revision=?",
        (path, key, rev),
    ).fetchone()
    require(row and row[0], "Запись не найдена")
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
        for field in {"name", *FIELDS[group], *OPTIONAL[group]}:
            if field == "skills" and old:
                for s in skills.KEYS:
                    if old[field][s] != row[field][s]:
                        row["fields"]["skills." + s] = source
            elif old and row.get(field) != old.get(field):
                row["fields"][field] = source
        rows[ident] = row
    p["revision"] += 1
    put(db, p)
    return dict(id=key, revision=p["revision"])


def match_input(p, roster_ids, personal_badges=None, portraits=None):
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
        personal = (personal_badges or {}).get("teams/" + tid)
        badge = personal or club_art.archive_badge(p["id"], t) or t.get("logo")
        badge_meta = badge if isinstance(badge, dict) else {}
        media_root = f"/api/database/{p['id']}/{p['revision']}/media/"
        domain["teams"][tid] = dict(
            name=t["name"],
            organization=org,
            teamType=t.get("teamType", "unknown"),
            visual=dict(
                club=True,
                badgeLicense=badge_meta.get("license"),
                gameBadge=badge_meta.get("changes", "").startswith("Игровая эмблема"),
                flag=t.get("nationality") or t["region"],
                url=media_root + "teams/" + tid if badge else None,
            ),
        )
        members = []
        for slot, pid in enumerate(r["players"]):
            require(pid not in domain["players"], "Один игрок заявлен за обе команды")
            player = p["players"][pid]
            role = player["role"] or world.SLOT_ROLES[slot]
            domain["players"][pid] = dict(
                name=player["name"],
                visual=dict(
                    flag=player.get("nationality"),
                    player=True,
                    head=(
                        media_root + "appearance/" + pid
                        if player.get("appearance")
                        else (scene_portraits.synthetic(pid) or {}).get("image")
                    ),
                    kit=dict(
                        id=tid,
                        name=t["name"],
                        design=t.get("kit"),
                        badgeLicense=badge_meta.get("license"),
                        badge=media_root + "teams/" + tid if badge else None,
                    ),
                ),
                skills=player["skills"].copy(),
                potential=player["potential"],
                mapKnowledge=player["mapKnowledge"].copy(),
                roleMastery=player["roleMastery"].copy(),
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
    if portraits is not None:
        full_photos = lineup_photos.index(portraits)
        people = {pid: p["players"][pid] for pid in domain["players"]}
        heads = portraits.index(people)
        for pid, person in domain["players"].items():
            if pid in full_photos:
                person["visual"]["lineupPhoto"] = full_photos[pid]
            if pid in heads and not people[pid].get("appearance"):
                person["visual"]["head"] = heads[pid]["image"]
    return domain
