"""Build the offline starter or adapt a pinned local Valve Git object tree."""

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from collections import Counter, defaultdict
from pathlib import Path

from backend import database as db, skills

COMMIT = "f8c55f250fdef796d708aa32814587932154fa04"
ROOT = "invitation/2025/"
VRS = f"https://github.com/ValveSoftware/counter-strike_regional_standings/blob/{COMMIT}/{ROOT}"
BLAST = "https://blast.tv/cs/news/blasttv-austin-major-all-rosters-revealed"
FINAL = "https://blast.tv/cs/tournaments/blast-premier-rivals-season-1-2025/match/bfaaa42e/falcons-vitality"
CLUB = "https://vitality.gg/en-asia/blogs/presse/team-vitality-entre-dans-la-legende-en-gagnant-l-esl-grand-slam-lors-des-iem-melbourne-2025"
DAY = "2025-05-05"


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


def estimate(adr, role, opponent_rank, maps):
    """Conservative damage proxy, shrunk toward the neutral BO1 prior."""
    role_center = {"awper": 76, "support": 70, "igl": 68, "entry": 76}.get(role, 74)
    opposition = max(0, (31 - opponent_rank) / 30) if opponent_rank else 0
    signal = (adr - role_center) * 0.7 + 4 * opposition
    return max(0, min(100, round(65 + signal * maps / (maps + 12))))


def starter():
    p = blank("austin-registration", "Заявки в Остин", "2025-05-09")
    p["origins"].update(
        blast=origin("confirmed", p["asOf"], BLAST),
        club=origin("confirmed", "2025-04-27", CLUB),
        navi=origin(
            "confirmed",
            "2025-04-23",
            "https://navi.gg/en/publications/blast-austin-major-navi-stage3",
        ),
        final=origin("confirmed", "2025-05-04", FINAL),
        adr=origin(
            "estimated",
            "2025-05-09",
            "ADR финала BLAST Rivals · 5 карт · модель 1; исходные данные в tools/import_scene.py",
        ),
        free=origin(
            "confirmed",
            "2025-04-14",
            "https://www.hltv.org/news/41450/perfecto-enters-free-agency",
        ),
    )
    for region in db.REGIONS:
        p["origins"][region] = origin(
            "confirmed", DAY, VRS + f"standings_{region.lower()}_2025_05_05.md"
        )
    # Selected factual registrations, not match-day substitutions.
    entries = [
        ("Vitality", "Europe", "XTQZZZ", "apEX ZywOo flameZ mezii ropz"),
        ("Falcons", "Europe", "zonic", "kyxsan m0NESY NiKo Magisk TeSeS"),
        ("MOUZ", "Europe", "sycrone", "Brollan torzsi Jimpphat Spinx xertioN"),
        ("Spirit", "Europe", "hally", "chopper sh1ro magixx donk zont1x"),
        ("Natus Vincere", "Europe", "B1ad3", "Aleksib w0nderful jL b1t iM"),
        ("M80", "Americas", "dephh", "s1n reck Lake Swisher slaxz-"),
        ("FURIA", "Americas", "sidde", "FalleN yuurih KSCERATO skullz molodoy"),
        ("Imperial", "Americas", "zakk", "VINI try chayJESUS decenty noway"),
        ("The MongolZ", "Asia", "maaRaa", "bLitz Techno4K Senzu 910 Mzinho"),
        ("Lynn Vision", "Asia", "GUM", "westmelon z4KR Starry EmiliaQAQ C4LLM3SU3"),
        ("TYLOO", "Asia", "zhokiNg", "JamYoung Moseyuh Attacker Jee Mercury"),
        ("FlyQuest", "Asia", "Erkast", "INS Liazz Vexite regali nettik"),
    ]
    p["origins"]["vitality-history"] = origin(
        "confirmed", p["asOf"], "https://vitality.gg/en-eu/pages/who-are-we"
    )
    p["origins"]["navi-history"] = origin(
        "confirmed", "2009-12-17", "https://navi.gg/en/company/history"
    )
    p["origins"]["coach-vitality"] = origin(
        "confirmed",
        "2023-11-10",
        "https://vitality.gg/en/blogs/presse/xtqzzz-revient-chez-team-vitality-en-tant-que-head-coach-counter-strike-et-apex-prolonge-son-contrat-jusquen-2026",
    )
    for name, region, coach, names in entries:
        tid = ident("t", name)
        org = {"Vitality": "org-vitality", "Natus Vincere": "org-navi"}.get(name)
        org_source = "club" if name == "Vitality" else "navi"
        if org:
            p["organizations"][org] = row(
                "Team Vitality" if name == "Vitality" else name,
                org_source,
                founded=2013 if name == "Vitality" else 2009,
                website="https://vitality.gg"
                if name == "Vitality"
                else "https://navi.gg",
            )
            p["organizations"][org]["fields"]["founded"] = (
                "vitality-history" if name == "Vitality" else "navi-history"
            )
        team = row(name, "blast", region=region, tier=None, organization=org)
        team["fields"]["region"] = region
        if org:
            team["fields"]["organization"] = org_source
        p["teams"][tid] = team
        employee = row(
            coach, "blast", team=tid, role="Тренер", realName=None, preparation=65
        )
        employee["fields"]["preparation"] = "model"
        if coach == "XTQZZZ":
            employee.update(realName="Rémy Quoniam")
            employee["fields"]["realName"] = "coach-vitality"
        p["staff"][ident("s", coach)] = employee
        members = [person(p, n, "blast") for n in names.split()]
        r = row(
            name,
            "blast",
            team=tid,
            players=members,
            captain=members[0] if name == "Vitality" else None,
            date=p["asOf"],
        )
        if r["captain"]:
            r["fields"]["captain"] = "club"
        p["rosters"][ident("r", name)] = r
    p["origins"]["birth"] = origin(
        "confirmed", "2000-11-09", "https://www.wikidata.org/wiki/Q65246991"
    )
    p["origins"]["portrait"] = origin(
        "confirmed",
        "2019-07-20",
        "https://commons.wikimedia.org/wiki/File:IEM_Chicago_Final_Edits-9731_ZywOo_(48353577846)_(cropped).jpg",
    )
    for nick, full_name in [
        ("apEX", "Dan Madesclaire"),
        ("ZywOo", "Mathieu Herbaut"),
        ("flameZ", "Shahar Shushan"),
        ("mezii", "William Merriman"),
        ("ropz", "Robin Kool"),
    ]:
        player = p["players"][ident("p", nick)]
        player["realName"] = full_name
        player["fields"]["realName"] = "club"
    zywoo = p["players"][ident("p", "ZywOo")]
    zywoo.update(born="2000-11-09", nationality="Франция", photo="zywoo-chicago-2019")
    zywoo["fields"].update(born="birth", nationality="club", photo="portrait")
    for nick, name, country, page in [
        ("m0NESY", "Ilya Osipov", "Россия", "6a5b29fe/m0nesy"),
        ("TeSeS", "René Madsen", "Дания", "f04689e0/teses"),
        ("NiKo", "Nikola Kovač", "Босния и Герцеговина", "b20ec3d5/niko"),
        ("Magisk", "Emil Reif", "Дания", "4a6c5fed/magisk"),
        ("kyxsan", "Damjan Stoilkovski", "Северная Македония", "2b8bb6ae/kyxsan"),
        ("ropz", "Robin Kool", "Эстония", "fc196dbf/ropz"),
        ("flameZ", "Shahar Shushan", "Израиль", "0c718cc9/flamez"),
        ("mezii", "William Merriman", "Великобритания", "48128543/mezii"),
        ("apEX", "Dan Madesclaire", "Франция", "7236ed86/apex"),
    ]:
        source = "bio-" + nick
        p["origins"][source] = origin(
            "confirmed", p["asOf"], "https://blast.tv/cs/player/" + page
        )
        player = p["players"][ident("p", nick)]
        player.update(realName=name, nationality=country)
        player["fields"].update(realName=source, nationality=source)
    player = p["players"][person(p, "Perfecto", "free")]
    player["contract"] = "free"
    # Published all-map ADR for the May 4 final. Role assignments are tactical modeling choices.
    for name, role, adr, rank, kills, deaths, assists in [
        ("apEX", "igl", 73, 3, 64, 77, 28),
        ("ZywOo", "awper", 90, 3, 90, 65, 20),
        ("flameZ", "entry", 76, 3, 73, 77, 21),
        ("mezii", "support", 75, 3, 71, 73, 26),
        ("ropz", "lurker", 99, 3, 91, 68, 15),
        ("kyxsan", "igl", 75, 1, 59, 78, 27),
        ("m0NESY", "awper", 82, 1, 93, 78, 15),
        ("NiKo", "rifler", 72, 1, 67, 84, 25),
        ("Magisk", "lurker", 78, 1, 65, 70, 19),
        ("TeSeS", "entry", 73, 1, 76, 84, 11),
    ]:
        player = p["players"][ident("p", name)]
        player.update(
            role=role,
            statistics=dict(
                event="BLAST Rivals S1 · финал",
                date="2025-05-04",
                maps=5,
                kills=kills,
                deaths=deaths,
                assists=assists,
                adr=adr,
                opponent="Falcons" if rank == 3 else "Vitality",
            ),
        )
        player["fields"]["statistics"] = "final"
        player["fields"]["role"] = "model"
        player["skills"]["aim"] = estimate(adr, role, rank, 5)
        player["fields"]["skills.aim"] = "adr"
    for key, cutoff, event, source in [
        ("melbourne", "2025-04-27", "IEM Melbourne 2025 · финал 3–2", "club"),
        ("rivals", "2025-05-04", "BLAST Rivals S1 · финал 3–2", "final"),
    ]:
        for name, other, outcome in [
            ("Vitality", "Falcons", "W"),
            ("Falcons", "Vitality", "L"),
        ]:
            p["history"][key + "-" + name] = dict(
                date=cutoff,
                event=event,
                team=ident("t", name),
                opponent=other,
                outcome=outcome,
                players=p["rosters"][ident("r", name)]["players"]
                if source == "final" or name == "Vitality"
                else [],
                origin=source,
            )
    return db.validate(p)


def valve(repo):
    # Read objects by SHA rather than trusting modified working-tree files.
    args = ["git", "-C", str(repo), "archive", COMMIT, ROOT + "details/2025_05_05"]
    data = subprocess.check_output(args)
    p = blank("valve-invitation-20250505", "Valve · май 2025", DAY)
    p["origins"]["tier"] = origin(
        "estimated", DAY, "Группы глобальных мест 1–16, 17–64, 65+ · модель 1"
    )
    rank_by_team = {}
    observations = defaultdict(dict)
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for entry in archive:
            if not entry.isfile():
                continue
            raw = archive.extractfile(entry).read().decode()
            name = re.search(r"^Team Name: (.*?)<br", raw, re.M)[1]
            rank = int(re.search(r"^Global Rank: \[(\d+)", raw, re.M)[1])
            region = re.search(r"^Region: \[(.*?)\]", raw, re.M)[1]
            rank_by_team[name] = min(rank, rank_by_team.get(name, rank))
            source = f"vrs-{rank}"
            p["origins"][source] = origin(
                "confirmed", DAY, VRS + entry.name.removeprefix(ROOT)
            )
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
            rid = ident("r", entry.name)
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


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--valve-repo", type=Path)
    cli.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    p = valve(args.valve_repo) if args.valve_repo else starter()
    content = db.envelope(p)
    args.output.write_bytes((db.encode(content) + "\n").encode())
    print(content["sha256"], {k: len(p[k]) for k in (*db.GROUPS, "history")})
    print(
        "Регионы:",
        Counter(r["region"] for r in p["teams"].values()),
        "Тиры:",
        Counter(r["tier"] for r in p["teams"].values()),
    )


if __name__ == "__main__":
    main()
