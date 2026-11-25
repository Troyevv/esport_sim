"""Build the redistributable scene from pinned, offline sporting observations."""

import csv
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from backend import club_art, database as db
from backend.valve_import import blank, ident, origin, row, person
from tools.scene_model import assign
from tools.import_scene import starter

DIR = Path(__file__).with_name("scene_sources")
DAY = "2026-11-24"
ART_DATE = "2026-11-25"
DEMO = "https://huggingface.co/datasets/sneakyzero/cs2-pro-round-economy"
SKIN = "https://skinory.io/en/pro-teams-cs2"
PGL = "https://news.pglesports.com/news/1794219566606-pgl-major-singapore-2026-team-rosters"
WIKI = "https://en.wikipedia.org/wiki/PGL_Major_Singapore_2026"
STYLE = "https://github.com/Jamie-Packer/cs2-playstyle-dataset-2024/tree/3b398f2c29cf2359dec1c09d85b632799d1977b4"
FREE = "https://www.fpshub.com/1126595/ecstatic-release-entire-cs2-roster-five-players-become-free-agents/"
ALIASES = {
    "Nemesis": "Team Nemesis",
    "5star": "5star eSports",
    "SINNERS": "SINNERS Esports",
    "THE ONE": "1w Team",
    "BB Team": "BetBoom Team",
    "PVISION": "PARIVISION",
    "GOSH": "BC.Game Esports",
    "DENDELE": "DENDELE CS",
    "Lynn Vision": "Lynn Vision Gaming",
    "Spirit": "Team Spirit",
    "Spirit Academy": "Team Spirit Academy",
    "Vitality": "Team Vitality",
    "Falcons": "Team Falcons",
    "Aurora": "Aurora Gaming",
    "FURIA": "FURIA Esports",
    "G2": "G2 Esports",
    "Liquid": "Team Liquid",
    "FaZe": "FaZe Clan",
    "9z": "9z Team",
    "Imperial": "Imperial Esports",
    "NAVI Junior": "Natus Vincere Junior",
    "Sangal": "Sangal Esports",
    "BC.Game": "BC.Game Esports",
    "Inner Circle": "IC Esports",
    "Sinners": "SINNERS Esports",
    "Nemiga": "Nemiga Gaming",
    "Metizport": "Metizport",
    "Nexus": "Nexus Gaming",
    "CYBERSHOKE": "CYBERSHOKE Esports",
    "UNiTY": "UNiTY esports",
    "Betclic": "Betclic Apogee Esports",
    "paiN": "paiN Gaming",
    "FUT": "FUT Esports",
    "NIP": "Ninjas in Pyjamas",
    "Luminosity": "Luminosity Gaming",
    "9 Pandas": "9Pandas",
}
ORG_NAMES = {
    "Team Vitality",
    "Natus Vincere",
    "MOUZ",
    "Team Spirit",
    "Team Falcons",
    "FaZe Clan",
    "100 Thieves",
    "G2 Esports",
    "FURIA Esports",
    "Team Liquid",
    "Astralis",
    "Ninjas in Pyjamas",
    "HEROIC",
    "FlyQuest",
    "The MongolZ",
    "MIBR",
    "Imperial Esports",
    "Eternal Fire",
    "Aurora Gaming",
    "9z Team",
    "FUT Esports",
    "Alliance",
    "BIG",
    "Fnatic",
    "Virtus.pro",
    "NRG",
    "TYLOO",
    "GamerLegion",
    "Complexity Gaming",
    "OG",
    "ENCE",
}
ORG_PAGES = {
    "BIG": "Berlin_International_Gaming",
    "HEROIC": "Heroic_(esports)",
    "Alliance": "Alliance_(esports)",
    "MIBR": "Made_in_Brazil_(esports)",
    "NRG": "NRG_Esports",
    "Team Falcons": "Team_Falcons",
    "Virtus.pro": "Virtus.pro",
    "OG": "OG_(esports)",
    "9z Team": "9z_Team",
    "ENCE": "ENCE_(esports)",
}


def read(file):
    return json.loads((DIR / file).read_bytes())


def team_key(name):
    return ALIASES.get(name, name).casefold()


def photo_asset(entry):
    name, author, license = entry
    file = name.replace(" ", "_")
    digest = hashlib.md5(file.encode()).hexdigest()
    path = quote(file, safe="")
    base = f"https://upload.wikimedia.org/wikipedia/commons/{digest[0]}/{digest[:2]}/{path}"
    return dict(
        image=base,
        author=author,
        source="https://commons.wikimedia.org/wiki/File:" + path,
        license=license,
        changes="Отображение в рамке профиля",
    )


def corroborated_accounts(sample):
    # Two accounts used by the same nick in the same named lineup with at
    # least three identical teammates. Never merge purely by a nickname.
    appearances = defaultdict(list)
    for m in sample["maps"]:
        for i, members in enumerate(m["sides"]):
            for sid in members or {}:
                appearances[sid].append((team_key(m["teams"][i]), set(members) - {sid}))
    names = defaultdict(list)
    accounts = {}
    for sid, aliases in sample["players"].items():
        candidates = names[aliases[0].casefold()]
        matches = {
            accounts[other]
            for other in candidates
            if any(
                a == b and len(x & y) >= 3
                for a, x in appearances[sid]
                for b, y in appearances[other]
            )
        }
        accounts[sid] = next(iter(matches)) if len(matches) == 1 else sid
        candidates.append(sid)
    return accounts


def build():
    sample = json.loads(gzip.decompress((DIR / "round-sample.json.gz").read_bytes()))
    ranks = read("skinory-202611.json")
    p = blank(db.RELEASE_ID, "Профессиональная сцена · ноябрь 2026", ART_DATE)
    src = p["origins"]
    src.update(
        demo=origin("confirmed", "2026-04-20", DEMO),
        skin=origin("confirmed", "2026-11-02", SKIN),
        pgl=origin("confirmed", "2026-11-09", PGL),
        wiki=origin("confirmed", DAY, WIKI),
        style=origin("confirmed", "2024-12-31", STYLE),
        free=origin("confirmed", "2026-11-08", FREE),
    )
    for key, status, detail in [
        (
            "scenario",
            "modeled",
            "Модель профиля v2 · роль, выборка, уровень соперников и индивидуальные вариации. Психология и потенциал — игровые предположения.",
        ),
        (
            "performance-estimate",
            "estimated",
            "Игровая оценка AIM с поправкой на индивидуальный рейтинг за 12 месяцев, размер выборки, соперников и ролевой профиль. Опубликованный рейтинг не измеряет AIM напрямую.",
        ),
        (
            "age-model",
            "estimated",
            "Возраст на дату среза · возрастной априорный диапазон, поправка на объём выступлений, индивидуальная вариация; точный день рождения неизвестен.",
        ),
        (
            "role-estimate",
            "estimated",
            "Приближение по игровому амплуа, выборке участия, результатам серий против соперников, доле AWP и архиву Jamie Packer 2024.",
        ),
        (
            "competition",
            "estimated",
            "Игровой тир по месту либо категории наблюдавшегося турнира. Регион ниже уровня рейтинга — вывод из названия регионального соревнования.",
        ),
        (
            "credits",
            "modeled",
            "Составы Skinory и данные участников Wikipedia · CC BY-SA 4.0. Адаптация базы на тех же условиях. Спортивные наблюдения sneakyzero / blanchon, стиль Jamie Packer / awpy / Harry Richards · CC BY 4.0.",
        ),
    ]:
        src[key] = origin(status, DAY, detail)
    players = p["players"]
    lookup = defaultdict(set)
    steam = {}
    accounts = corroborated_accounts(sample)
    for sid, names in sample["players"].items():
        pid = "steam-" + accounts[sid]
        if pid not in players:
            tmp = person(p, names[0], "demo")
            players[pid] = players.pop(tmp)
        steam[sid] = pid
        for n in names:
            lookup[n.casefold()].add(pid)

    def player(name, source):
        same = lookup[name.casefold()]
        if len(same) == 1:
            return next(iter(same))
        pid = person(p, name, source)
        if not same:
            same.add(pid)
        return pid

    clubs = read("organizations.json")
    teams, latest, regions, counts, rosters, known_rank = (
        {},
        {},
        defaultdict(Counter),
        Counter(),
        {},
        {},
    )
    obs = defaultdict(lambda: dict(maps=Counter(), usage=[0, 0, 0], series={}, days=[]))
    history = []
    for m in sample["maps"]:
        for side, members in enumerate(m["sides"]):
            if not members:
                continue
            label = m["teams"][side]
            key = team_key(label)
            teams.setdefault(key, ALIASES.get(label, label))
            counts[key] += 1
            members_ids = [steam[k] for k in members]
            latest[key] = (m["day"], members_ids)
            event = m["event"].lower()
            for words, reg in [
                (("europe", "european"), "Europe"),
                (("north america", "south america"), "Americas"),
                (("oceania", "asia"), "Asia"),
            ]:
                if any(w in event for w in words):
                    regions[key][reg] += 1
            won = m["score"][side] > m["score"][1 - side]
            for sid, usage in members.items():
                v = obs[steam[sid]]
                v["maps"][m["map"]] += 1
                v["usage"] = [a + b for a, b in zip(v["usage"], usage)]
                v["series"][m["series"]] = (won, team_key(m["teams"][1 - side]))
                v["days"].append(m["day"])
            history.append((key, m, side, members_ids, won))
    for rank, label, region, names in ranks:
        if len(names) != 5:
            continue
        key = team_key(label)
        known_rank[key] = rank
        teams[key] = ALIASES.get(label, label)
        rosters[key] = ("2026-11-02", [player(n, "skin") for n in names], "skin")
        regions[key] = Counter({region: 1})
    # Tournament registration can supersede the ranking five. Record the named replacement.
    licensed_roles = {}
    for squad in read("singapore-202611.json"):
        key = team_key(squad["name"])
        assert key in rosters, squad["name"]
        five = []
        for nick, name, replaced in squad["players"]:
            pid = player(nick, "wiki")
            players[pid].update(realName=name)
            players[pid]["fields"]["realName"] = "wiki"
            five.append(pid)
        sub = squad.get("sub")
        if sub and sub[1]:
            pid = player(sub[0], "wiki")
            players[pid].update(realName=sub[1])
            players[pid]["fields"]["realName"] = "wiki"
            for i, (_, _, replaced) in enumerate(squad["players"]):
                if replaced:
                    five[i] = pid
        rosters[key] = ("2026-11-09", five, "pgl")
        n, full = squad["coach"]
        s = row(
            n,
            "wiki",
            team=ident("t", key),
            role="Тренер",
            realName=full,
            preparation=round(66 + 8 / (1 + known_rank[key] / 20)),
        )
        s["fields"]["preparation"] = "scenario"
        p["staff"][ident("s", n)] = s
    # Keep top league teams plus the historical teams with the largest licensed map samples.
    continuity = read("continuity.json")
    selected = list(known_rank)
    selected += sorted(
        (k for k in latest if k not in known_rank),
        key=lambda k: (k not in continuity, -counts[k], k),
    )[: 287 - len(selected)]
    selected = set(selected)
    for k in sorted(selected):
        source = "skin" if k in known_rank else "demo"
        reg = regions[k].most_common(1)
        rank = known_rank.get(k)
        tier = 1 if rank and rank <= 16 else 2 if rank and rank <= 64 else 3
        tid = ident("t", k)
        team = row(
            teams[k],
            source,
            organization=None,
            region=reg[0][0] if reg else None,
            tier=tier,
        )
        team["fields"]["tier"] = "competition"
        if k not in known_rank:
            team["fields"]["region"] = "competition"
        if k in continuity and k not in known_rank:
            check = ident("verified", k)
            src[check] = origin("confirmed", "2026-11-02", continuity[k]["reference"])
            team["region"] = continuity[k]["region"]
            team["fields"]["region"] = check
        p["teams"][tid] = team
        if teams[k] in ORG_NAMES:
            oid = ident("org", k)
            wiki = "https://en.wikipedia.org/wiki/" + quote(
                ORG_PAGES.get(teams[k], teams[k].replace(" ", "_"))
            )
            src[oid] = origin("confirmed", DAY, wiki)
            p["organizations"][oid] = row(teams[k], oid, founded=None, website=None)
            p["organizations"][oid].update(clubs.get(teams[k], {}))
            team["organization"] = oid
            team["fields"]["organization"] = oid
        if k in rosters:
            when, five, ref = rosters[k]
        else:
            when, five = latest[k]
            ref = "demo"
            if k in continuity:
                when, ref = "2026-11-02", ident("verified", k)
        p["rosters"][ident("r", k)] = row(
            teams[k], ref, team=tid, date=when, players=five, captain=None
        )
    for key, m, side, ids, won in history:
        if key not in selected:
            continue
        # One record per series and witnessed lineup. Win/loss is the series outcome.
        hist = m["series"] + "-" + ident("h", key + " " + " ".join(sorted(ids)))
        p["history"][hist] = dict(
            team=ident("t", key),
            date=m["day"],
            event=m["event"],
            opponent=m["teams"][1 - side],
            outcome="W" if won else "L",
            origin="demo",
            players=ids,
        )
    for n, full in [
        ("Inspire", "David Rasmussen"),
        ("Mol011", "Emil Sall Würtz"),
        ("Skejs", "Rasmus Gleerup"),
        ("Z1noz", "Luca Stibolt Jensen"),
        ("Thom", "Thomas Hedemann"),
    ]:
        pid = player(n, "free")
        players[pid].update(contract="free", realName=full)
        players[pid]["fields"].update(contract="free", realName="free")
    old = starter()
    for orig, rec in old["players"].items():
        ids = lookup.get(rec["name"].casefold(), set())
        if len(ids) != 1:
            continue
        r = players[next(iter(ids))]
        for field in ("realName", "born", "nationality", "statistics"):
            if rec[field] and not r.get(field):
                key = rec["fields"][field]
                src["austin-" + key] = old["origins"][key]
                r[field] = rec[field]
                r["fields"][field] = "austin-" + key
    styles = {}
    for r in sorted(
        read("playstyles-2024.json"), key=lambda row: int(row["map_count"])
    ):
        pid = steam.get(r["steamid"])
        if pid:
            styles[pid] = r
    ratings = {}
    for k, (when, roster, ref) in rosters.items():
        for pid in roster:
            ratings[pid] = min(known_rank[k], ratings.get(pid, 999))
    for pid, v in obs.items():
        v["residuals"] = [
            w
            - (
                0.38
                if known_rank.get(opp, 999) <= 16
                else 0.48
                if known_rank.get(opp, 999) <= 64
                else 0.56
            )
            for w, opp in v["series"].values()
        ]
        players[pid]["sample"] = {
            "maps": sum(v["maps"].values()),
            "series": len(v["series"]),
            "wins": sum(w for w, _ in v["series"].values()),
            "rounds": v["usage"][0],
            "awpRounds": v["usage"][1],
            "utilityRounds": v["usage"][2],
            "from": min(v["days"]),
            "until": max(v["days"]),
        }
        players[pid]["fields"]["sample"] = "demo"
    enrich_bios(p, lookup)
    src["gamerstats"] = origin(
        "confirmed",
        "2026-11-15",
        "https://gamerstats.net/datasets/cs2-player-ratings.csv",
    )
    domains = {
        "In-Game Leader": "igl",
        "Main AWPer": "awper",
        "Entry Fragger": "entry",
        "Rifler / Lurker": "lurker",
        "Site Anchor": "support",
    }
    with (DIR / "cs2-player-ratings.csv").open(encoding="utf-8-sig", newline="") as f:
        for rec in csv.DictReader(f):
            nick = rec["nickname"]
            if not nick:
                continue
            same = lookup.get(nick.casefold(), set())
            if len(same) > 1:
                roster = rosters.get(team_key(rec["team_name"]))
                named = (
                    [
                        i
                        for i in roster[1]
                        if players[i]["name"].casefold() == nick.casefold()
                    ]
                    if roster
                    else []
                )
                if len(named) != 1:
                    continue
                pid = named[0]
            else:
                pid = player(nick, "gamerstats")
            r = players[pid]
            for field, v in (
                ("realName", rec["full_name"]),
                ("nationality", rec["country_code"]),
            ):
                if v and not r.get(field):
                    r[field] = v
                    r["fields"][field] = "gamerstats"
            if rec["role_title"] in domains:
                licensed_roles[pid] = domains[rec["role_title"]]
            if rec["maps"] and int(rec["maps"]) > 0 and rec["rating"]:
                r["performance"] = dict(
                    rating=float(rec["rating"]),
                    maps=int(rec["maps"]),
                    version=rec["rating_version"],
                    window=rec["rating_window"],
                    role=rec["role_title"] or None,
                )
                r["fields"]["performance"] = "gamerstats"
    for pid, r in players.items():
        assign(
            p,
            pid,
            obs.get(pid, {}),
            styles.get(pid),
            ratings.get(pid),
            licensed_roles.get(pid),
            DAY,
        )
    for roster in p["rosters"].values():
        countries = [players[pid].get("nationality") for pid in roster["players"]]
        if len(countries) == 5 and countries[0] and len(set(countries)) == 1:
            team = p["teams"][roster["team"]]
            team["nationality"] = countries[0]
            team["fields"]["nationality"] = "competition"
    attach_images(p)
    return db.validate(p)


def enrich_bios(p, lookup):
    bios = read("bios.json")
    # Distinct spelling and one person in the sporting record; preserve sourced PGL spellings.
    for v in read("wikidata-202611.json"):
        by_name = set()
        for n in v["aliases"]:
            by_name.update(lookup.get(n.casefold(), ()))
        staff = [
            r
            for r in p["staff"].values()
            if r["name"].casefold() in {n.casefold() for n in v["aliases"]}
        ]
        records = []
        if len(by_name) == 1:
            records.append((p["players"][next(iter(by_name))], True))
        if len(staff) == 1:
            records.append((staff[0], False))
        for r, is_player in records:
            key = "wd-" + v["id"].split("/")[0]
            ref = "https://www.wikidata.org/wiki/Special:Search?search=" + quote(
                'haswbstatement:P8878="' + v["id"] + '"'
            )
            p["origins"][key] = origin("confirmed", DAY, ref)
            for field, value in (
                ("realName", v["realName"]),
                ("nationality", v["country"]),
                ("born", v["born"] if is_player else None),
            ):
                if value and not r.get(field):
                    r[field] = value
                    r["fields"][field] = key
    for g in ("players", "staff"):
        for n, record in bios.get(g, {}).items():
            if g == "players":
                ids = lookup.get(n.casefold(), set())
                if len(ids) != 1:
                    continue
                r = p[g][next(iter(ids))]
            else:
                r = next(
                    (v for v in p[g].values() if v["name"].casefold() == n.casefold()),
                    None,
                )
                if not r:
                    continue
            key = ident("bio", record["source"])
            p["origins"][key] = origin("confirmed", DAY, record["source"])
            for field, val in record.items():
                if field != "source" and val:
                    r[field] = val
                    r["fields"][field] = key


def attach_images(p):
    media = read("media.json")
    for staff in p["staff"].values():
        entry = media["staff"].get(staff["name"])
        if entry:
            staff["photo"] = photo_asset(entry)
            key = ident("asset", entry[0])
            p["origins"][key] = origin("confirmed", DAY, staff["photo"]["source"])
            staff["fields"]["photo"] = key
    for group in ("teams", "organizations"):
        for record in p[group].values():
            name = record["name"]
            asset = club_art.embedded(name)
            record["logo"] = asset
            status = (
                "confirmed"
                if club_art.catalog()[name]["kind"] == "original"
                else "modeled"
            )
            key = ident("badge", name)
            p["origins"][key] = origin(status, ART_DATE, asset["source"])
            record["fields"]["logo"] = key


if __name__ == "__main__":
    result = build()
    with (
        db.RELEASE.open("wb") as f,
        gzip.GzipFile(filename="", fileobj=f, mode="wb", mtime=0) as out,
    ):
        out.write((db.encode(db.envelope(result)) + "\n").encode())
    print(
        db.envelope(result)["sha256"],
        {k: len(result[k]) for k in (*db.GROUPS, "history")},
    )
