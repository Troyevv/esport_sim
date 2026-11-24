"""Import Valve's published roster reports from a local ZIP. No remote calls."""

from collections import defaultdict
from io import BytesIO
import hashlib
import json
import re
import zlib
from zipfile import BadZipFile, ZipFile

from . import database as db, skills

COMMIT = "f8c55f250fdef796d708aa32814587932154fa04"
ROOT = "invitation/2025/"
VRS = f"https://github.com/ValveSoftware/counter-strike_regional_standings/blob/{COMMIT}/{ROOT}"
DAY = "2025-05-05"
DIRECTORY = ROOT + "details/2025_05_05/"
MANIFEST = db.STARTER.with_name("valve-may-sha256.json")


def origin(status, date, reference):
    return dict(status=status, date=date, reference=reference)


def blank(key, title, cutoff):
    return dict(
        id=key,
        revision=1,
        title=title,
        asOf=cutoff,
        versions=db.VERSIONS,
        origins={"model": origin("modeled", cutoff, "Параметры BO1 · модель 1")},
        history={},
        **{group: {} for group in db.GROUPS},
    )


def ident(kind, name):
    # Exact Unicode spelling, no fuzzy matching or mutable rank in a person's ID.
    return kind + "-" + hashlib.sha256(name.encode()).hexdigest()[:20]


def row(name, source, **fields):
    return dict(name=name, origin=source, fields={}, **fields)


def person(p, name, source):
    key = ident("p", name)
    if key not in p["players"]:
        player = row(
            name,
            source,
            skills=dict.fromkeys(skills.KEYS, 65),
            role=None,
            potential=None,
            contract=None,
            realName=None,
            born=None,
            nationality=None,
            photo=None,
            statistics=None,
            mapKnowledge={"depo": 65},
            roleMastery=dict.fromkeys(skills.ROLE_WEIGHTS, 65),
        )
        player["fields"].update(
            dict.fromkeys(("skills", "mapKnowledge", "roleMastery"), "model")
        )
        p["players"][key] = player
    return key


def verified_reports(raw):
    manifest = json.loads(MANIFEST.read_bytes())
    try:
        with ZipFile(BytesIO(raw)) as archive:
            items = sorted(
                (e for e in archive.infolist() if not e.is_dir()),
                key=lambda e: e.filename.split("/")[-1],
            )
            names = [e.filename.split("/")[-1] for e in items]
            db.require(
                len(items) == len(manifest) and set(names) == set(manifest),
                "Нужны все 297 файлов из details/2025_05_05 без посторонних записей",
            )
            for name, entry in zip(names, items):
                db.require(
                    entry.file_size <= 128 * 1024 and not entry.flag_bits & 1,
                    "Недопустимый файл в ZIP",
                )
                content = archive.read(entry).replace(b"\r\n", b"\n")
                db.require(
                    hashlib.sha256(content).hexdigest() == manifest[name],
                    f"Файл не совпадает со срезом Valve: {name}",
                )
                yield DIRECTORY + name, content.decode("utf-8")
    except (BadZipFile, NotImplementedError, RuntimeError, EOFError, zlib.error) as exc:
        raise ValueError("Не удалось прочитать ZIP Valve") from exc


def import_zip(raw):
    p = blank("valve-invitation-20250505", "Valve · май 2025", DAY)
    p["origins"]["tier"] = origin(
        "estimated", DAY, "Группы глобальных мест 1–16, 17–64, 65+ · модель 1"
    )
    rank_by_team = {}
    observations = defaultdict(dict)
    for path, raw in verified_reports(raw):
        name = re.search(r"^Team Name: (.*?)<br", raw, re.M)[1]
        rank = int(re.search(r"^Global Rank: \[(\d+)", raw, re.M)[1])
        region = re.search(r"^Region: \[(.*?)\]", raw, re.M)[1]
        rank_by_team[name] = min(rank, rank_by_team.get(name, rank))
        source = f"vrs-{rank}"
        p["origins"][source] = origin("confirmed", DAY, VRS + path.removeprefix(ROOT))
        tid = ident("t", name)
        # A team label can occur more than once. Region/tier belong to a ranked five.
        tier = 1 if rank <= 16 else 2 if rank <= 64 else 3
        if tid not in p["teams"]:
            team = row(name, source, organization=None, region=region, tier=tier)
            team["fields"]["tier"] = "tier"
            p["teams"][tid] = team
        else:
            team = p["teams"][tid]
            if team["region"] != region:
                team["region"] = None
            if team["tier"] != tier:
                team["tier"] = None
        members = re.search(r"^Roster: (.*?)<br", raw, re.M)[1]
        players = [
            person(p, n.strip(), source) for n in members.split(",") if n.strip()
        ]
        rid = ident("r", path)
        p["rosters"][rid] = row(
            f"{name} · #{rank}",
            source,
            team=tid,
            date=DAY,
            captain=None,
            players=players,
        )
        for line in raw.splitlines():
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) == 12 and cells[0].isdigit() and cells[4] in ("W", "L"):
                _, match_id, when, opponent, outcome = cells[:5]
                five = [person(p, n.strip(), source) for n in cells[-1].split(",")]
                for pid in five:
                    observations[pid].setdefault(match_id, set()).add(
                        (opponent, outcome)
                    )
                p["history"][source + "-" + match_id] = dict(
                    date=when,
                    team=tid,
                    opponent=opponent,
                    outcome=outcome,
                    origin=source,
                    event=None,
                    players=five,
                )
    # Weak team-level proxy only. A win is shared evidence and cannot measure aim or personality.
    p["origins"]["participation"] = origin(
        "estimated",
        DAY,
        "Модель 1 · результат пятёрки с участием игрока; строки и ссылки во вкладке История",
    )
    for pid, matches in observations.items():
        residuals = []
        for variants in matches.values():
            if len(variants) != 1:
                continue
            opponent, outcome = next(iter(variants))
            rank = rank_by_team.get(opponent)
            if rank is None:
                continue
            expected = 0.40 if rank <= 16 else 0.50 if rank <= 64 else 0.60
            residuals.append(int(outcome == "W") - expected)
        if residuals:
            player = p["players"][pid]
            player["skills"]["execution"] = round(
                65 + 12 * sum(residuals) / (len(residuals) + 20)
            )
            player["fields"]["skills.execution"] = "participation"
    return db.validate(p)
