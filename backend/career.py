"""Calendar of independent exhibitions on a pinned edition of the scene."""

import hashlib
from datetime import timedelta
from uuid import uuid4

from . import training, round_sim, staff, competitions, registrations, cs2_maps, database, match, series, veto, world
from .database import require

VERSION = 1
SCOPES = ("fast", "standard", "full")


def roster_index(pack):
    # A historical roster in an imported edition must not replace a later five.
    latest = {}
    for rid, roster in sorted(
        pack["rosters"].items(), key=lambda item: (item[1]["date"], item[0])
    ):
        if roster["date"] <= pack["asOf"]:
            latest[roster["team"]] = rid
    return {
        team: rid
        for team, rid in latest.items()
        if len(pack["rosters"][rid]["players"]) == 5
    }


def choices(pack):
    return dict(
        date=pack["asOf"],
        circuit=pack["id"] in database.NOVEMBER_EDITIONS and pack["asOf"] == "2026-11-25",
        teams=[
            dict(id=tid, name=t["name"], region=t["region"], tier=t["tier"])
            for tid in roster_index(pack)
            for t in [pack["teams"][tid]]
        ],
    )


def create(pack, options):
    name = options.get("name")
    require(
        isinstance(name, str) and 0 < len(name.strip()) <= 64,
        "Введите имя персонажа (до 64 знаков)",
    )
    mode, scope, team = (options.get(k) for k in ("mode", "scope", "team"))
    require(
        isinstance(mode, str) and mode in world.GRANTS and scope in SCOPES,
        "Неизвестная должность или охват",
    )
    regions = options.get("regions", [])
    require(
        isinstance(regions, list) and all(r in database.REGIONS for r in regions),
        "Неизвестный регион",
    )
    require(scope != "fast" or regions, "Выберите хотя бы один регион")
    available = roster_index(pack)
    require(
        isinstance(team, str) and team in available,
        "У клуба нет полной пятёрки на дату базы",
    )
    circuit = pack["id"] in database.NOVEMBER_EDITIONS and pack["asOf"] == "2026-11-25"
    ranked = any(t["tier"] for t in pack["teams"].values())
    participants = {}
    registered = set()
    for tid in [
        team,
        *sorted(
            available,
            key=lambda t: (pack["rosters"][available[t]]["date"], t),
            reverse=True,
        ),
    ]:
        t = pack["teams"][tid]
        if not circuit and tid != team and (
            (scope == "fast" and t["region"] not in regions)
            or (scope == "standard" and ranked and t["tier"] not in (1, 2))
        ):
            continue
        members = pack["rosters"][available[tid]]["players"]
        if circuit or registered.isdisjoint(members):
            participants[tid] = available[tid]
            registered.update(members)
    require(
        len(participants) >= 2, "В выбранном охвате нет соперника с отдельной пятёркой"
    )
    c = dict(
        version=VERSION,
        office=staff.office(),
        training=training.new(pack["asOf"]),
        id=str(uuid4()),
        source=[pack["id"], pack["revision"]] + ([pack["tournamentSupplement"]] if "tournamentSupplement" in pack else []),
        character=name.strip(),
        mode=mode,
        team=team,
        club=pack["teams"][team]["name"],
        scope="full" if circuit else scope,
        regions=[] if circuit else sorted(set(regions)),
        start=pack["asOf"],
        date=pack["asOf"],
        teams=participants,
        week=0,
        queue=[],
        history=[],
        progress=None,
        error=None,
        milestones=[dict(date=pack["asOf"], title="Назначение в клуб", matches=None)],
    )
    c["mapPool"] = cs2_maps.installed()
    if circuit:
        competitions.init(c,pack)
    else:
        schedule(c)
    return c


def schedule(c):
    if not c.get("mapPool"):
        c["mapPool"] = cs2_maps.installed()
    if "seriesProfile" not in c and set(veto.ACTIVE) <= set(c["mapPool"]):
        c["seriesProfile"] = veto.REGULATION
    week = c["week"]
    start = database.day(c["start"]) + timedelta(days=7 * week)
    # Rotate opponents without allocating a season or creating a competition.
    others = sorted(c["teams"].keys() - {c["team"]})
    offset = week % len(others)
    rotated = others[offset:] + others[:offset]
    pairs = [(c["team"], rotated.pop(0))]
    # Pair opposite positions around the circle. Adjacent pairing would
    # repeatedly schedule the same neighbours for all background teams.
    half = len(rotated) // 2
    pairs.extend(
        zip(rotated[:half], reversed(rotated[len(rotated) - half :]), strict=True)
    )
    for i, (home, away) in enumerate(pairs):
        day = start + timedelta(days=4 if i == 0 else 1 + (i - 1) % 6)
        ident = f"{week:08d}-{i:04d}"
        material = database.encode([c["source"], c["start"], ident, home, away])
        seed = (
            int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], "big") >> 1
        )
        c["queue"].append(
            dict(
                kind="match",
                id=ident,
                date=day.isoformat(),
                teams=[home, away],
                seed=seed,
                **({"bestOf": (3, 1, 5)[(week+i) % 3]} if c.get("seriesProfile") else
                   {"mapId": c["mapPool"][seed % len(c["mapPool"])]} if c.get("mapPool") else {}),
            )
        )
    c["queue"].append(
        dict(
            kind="review",
            id=f"{week:08d}-review",
            date=(start + timedelta(days=7)).isoformat(),
            teams=[],
        )
    )
    # At equal dates background results become visible before the coach is needed.
    c["queue"].sort(key=lambda e: (e["date"], c["team"] in e["teams"], e["id"]))
    c["week"] += 1


def ensure_schedule(c, pack):
    """Repopulate the calendar boundary of a parked career before advancing it."""
    if not any(not e.get("pcw") for e in c["queue"]):
        if "circuit" in c:
            competitions.add_season(c, pack, int(c["date"][:4]))
        else:
            schedule(c)
    training.refresh_practices(c, pack)


def stops(c, event):
    if event.get("pcw"):
        return event["watch"] and not training.unavailable(c, event)
    return event["kind"] == "review" or c["team"] in event["teams"] or event["id"]==c.get("watchFixture")


def start_advance(c, *, administrative=False):
    require(not c["progress"], "Календарь уже рассчитывается")
    until = next((i for i, e in enumerate(c["queue"]) if e["kind"] == "match" and stops(c, e)), len(c["queue"]))
    require(administrative or until or c["queue"][0]["kind"] == "review" or c["date"] != c["queue"][0]["date"], "Вас ждут в матч-центре")
    c.update(progress=dict(done=0, total=until, runId=str(uuid4())), error=None)


def match_domain(pack, c, event, badges=None, portraits=None):
    rosters = [c["teams"][team] for team in event["teams"]]
    if event.get("edition"):
        edition = c["circuit"]["editions"][event["edition"]]
        frozen = {}
        coaches = set()
        for tid in event["teams"]:
            version = edition["registrations"][tid][-1]
            require(set(version["players"]) <= set(registrations.available(c, tid, pack)),
                    "В заявке недоступен игрок. Требуется экстренная замена.")
            rid = f"{edition['id']}.{tid}.{version['version']}"
            club = pack["rosters"][c["teams"][tid]]
            frozen[rid] = dict(team=tid,players=list(version["players"]),date=version["date"],
                               captain=club["captain"] if club["captain"] in version["players"] else None)
            coaches.add(version["coach"])
        pack = dict(pack, rosters=frozen, staff={k:v for k,v in pack["staff"].items() if k in coaches})
        rosters = list(frozen)
    domain = database.match_input(pack, rosters, badges)
    if "training" in c:
        training.overlay(domain, c["training"])
    domain["authority"]["mode"] = c["mode"]
    if c["team"] in domain["teams"]:
        domain["authority"]["organization"] = domain["teams"][c["team"]]["organization"]
    if portraits:
        for pid, portrait in portraits.index(
            {pid: pack["players"][pid] for pid in domain["players"]}
        ).items():
            visual = domain["players"][pid]["visual"]
            if not pack["players"][pid].get("appearance"):
                visual["head"] = portrait["image"]
    return domain, rosters


def initial(pack, c, event, badges=None, portraits=None, *, detailed=True):
    domain, rosters = match_domain(pack, c, event, badges, portraits)
    if "bestOf" in event:
        jobs = staff.booked(c, pack, event)
        game = series.initial(event["seed"], event["bestOf"], domain, rosters,
                              c["team"] if c["team"] in event["teams"] else None,
                              profile=(c["circuit"]["editions"][event["edition"]]["rules"] if event.get("edition") else c["seriesProfile"]), history=c["history"], today=event["date"], jobs=jobs, detailed=detailed)
        if event.get("edition"):
            game["series"]["tournament"]=c["circuit"]["editions"][event["edition"]]["title"]
        if not detailed:
            game["simulation"] = round_sim.MODE
        return game
    if not detailed:
        game = dict(simulation=round_sim.MODE, seed=event["seed"], domain=domain, rosterIds=rosters, mapId=event.get("mapId"))
        if event.get("pcw") and event.get("board"):
            game.update(practiceBoard=event["board"], practiceTeam=c["team"])
        return game
    game = match.initial(
        event["seed"],
        domain,
        rosters,
        c["team"] if c["team"] in event["teams"] else None,
        map_id=event.get("mapId","depo"),
    )
    if event.get("pcw") and event.get("board"):
        match.assign(game, event["board"])
    return game


def simulate(game):
    if game.get("simulation") == round_sim.MODE:
        if "series" not in game:
            first = game["domain"]["rosters"][game["rosterIds"][0]]["team"]
            return round_sim.play_map(game, game["mapId"], first, game["seed"])
        s = game["series"]
        veto.advance(game, "captain")
        strain = {}
        for i, entry in enumerate(s["order"]):
            report = round_sim.play_map(game, entry["map"], entry["attack"], series.map_seed(s["seed"], i), strain)
            s["results"].append(report)
            winner = report["winnerTeamId"]
            s["score"][winner] += 1
            if s["score"][winner] == s["bestOf"] // 2 + 1:
                s.update(winner=winner, stage="finished")
                break
        return series.result(game)
    if "series" in game:
        veto.advance(game, "captain")
        while game["series"]["stage"] != "finished":
            if game["series"]["stage"] != "playing":
                game = series.next_map(game)
            while game["phase"] != "finished":
                match.advance(game)
            series.finish_map(game)
        return result(game)
    while game["phase"] != "finished":
        match.advance(game)
    return result(game)


def result(game):
    if "series" in game:
        return series.result(game)
    return dict(series.map_result(game), simulation=series.DETAILED)


def complete(c, digest, points, winner, facts=None):
    event = c["queue"].pop(0)
    if event["id"]==c.get("watchFixture"):
        c.pop("watchFixture")
    c["history"].append(
        dict(
            **event,
            **(facts or {}),
            score=[points[t] for t in event["teams"]],
            scoreByTeam=points,
            winnerTeamId=winner,
            result=digest,
        )
    )
    c["date"] = event["date"]
    if c["progress"]:
        c["progress"]["done"] += 1
    if "circuit" not in c and c["team"] in event["teams"]:
        schedule(c)
