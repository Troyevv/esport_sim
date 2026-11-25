"""Calendar of independent exhibition BO1s on a pinned edition of the scene."""

import hashlib
from datetime import timedelta
from uuid import uuid4

from . import cs2_maps, database, match, match_score, world
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
        if tid != team and (
            (scope == "fast" and t["region"] not in regions)
            or (scope == "standard" and ranked and t["tier"] not in (1, 2))
        ):
            continue
        members = pack["rosters"][available[tid]]["players"]
        if registered.isdisjoint(members):
            participants[tid] = available[tid]
            registered.update(members)
    require(
        len(participants) >= 2, "В выбранном охвате нет соперника с отдельной пятёркой"
    )
    c = dict(
        version=VERSION,
        id=str(uuid4()),
        source=[pack["id"], pack["revision"]],
        character=name.strip(),
        mode=mode,
        team=team,
        club=pack["teams"][team]["name"],
        scope=scope,
        regions=sorted(set(regions)),
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
    schedule(c)
    return c


def schedule(c):
    if not c.get("mapPool"):
        c["mapPool"] = cs2_maps.installed()
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
                **({"mapId":c["mapPool"][seed%len(c["mapPool"])]} if c.get("mapPool") else {}),
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


def stops(c, event):
    return event["kind"] == "review" or c["team"] in event["teams"]


def start_advance(c):
    require(not c["progress"], "Календарь уже рассчитывается")
    until = next(i for i, e in enumerate(c["queue"]) if stops(c, e))
    require(until or c["date"] != c["queue"][0]["date"], "Вас ждут в матч-центре")
    c.update(progress=dict(done=0, total=until), error=None)


def match_domain(pack, c, event, badges=None, portraits=None):
    rosters = [c["teams"][team] for team in event["teams"]]
    domain = database.match_input(pack, rosters, badges)
    domain["authority"]["mode"] = c["mode"]
    if c["team"] in domain["teams"]:
        domain["authority"]["organization"] = domain["teams"][c["team"]]["organization"]
    if portraits:
        for pid, portrait in portraits.index(
            {pid: pack["players"][pid] for pid in domain["players"]}
        ).items():
            visual = domain["players"][pid]["visual"]
            if not visual["head"]:
                visual["head"] = portrait["image"]
    return domain, rosters


def initial(pack, c, event, badges=None, portraits=None):
    domain, rosters = match_domain(pack, c, event, badges, portraits)
    return match.initial(
        event["seed"],
        domain,
        rosters,
        c["team"] if c["team"] in event["teams"] else None,
        map_id=event.get("mapId","depo"),
    )


def simulate(game):
    while game["phase"] != "finished":
        match.advance(game)
    return result(game)


def result(game):
    require(game.get("phase") == "finished", "Матч ещё идёт")
    return dict(
        teams=match_score.team_ids(game),
        score=game["score"],
        scoreByTeam=game["scoreByTeam"],
        winnerTeamId=game["winnerTeamId"],
        rules=game["rules"],
        map=game["map_version"],
        **({"mapId":game["mapId"]} if game.get("mapId") else {}),
        seed=game["seed"],
        rounds=game["history"],
        ticks=game["tick"],
        events=game["serial"],
        stats=[
            dict(
                player=a["playerId"],
                name=a["name"],
                club=a["club"],
                teamId=a["teamId"],
                **game["stats"][a["id"]],
            )
            for a in game["agents"]
        ],
    )


def complete(c, digest, points, winner):
    event = c["queue"].pop(0)
    c["history"].append(
        dict(
            **event,
            score=[points[t] for t in event["teams"]],
            scoreByTeam=points,
            winnerTeamId=winner,
            result=digest,
        )
    )
    c["date"] = event["date"]
    if c["progress"]:
        c["progress"]["done"] += 1
    if c["team"] in event["teams"]:
        schedule(c)
