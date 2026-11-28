"""Read-time performance projections from completed match protocols only."""

VERSION = "impact.1"
COUNTERS = ("k", "damage", "kast", "opening", "openingDeaths")


def performance(totals, rounds):
    """Return unrounded values for ordering. Zero opening attempts earn zero credit."""
    k, damage, kast, fk, fd = (totals[field] for field in COUNTERS)
    adr = damage / rounds
    kast_rate = kast / rounds
    duels = fk / (fk + fd) if fk + fd else 0
    impact = .5 * (k / rounds / .70) + .2 * (adr / 75) + .2 * (kast_rate / .70) + .1 * (duels / .50)
    return dict(impact=impact, adr=adr, kastPercent=100 * kast_rate)


def summarize(maps, winner):
    """Each recorded five plays the entire map. Sum participation across maps."""
    players = {}
    rounds = 0
    complete = bool(maps)
    for game in maps:
        count = len(game["rounds"])
        rounds += count
        seen = set()
        team_sizes = {}
        for row in game["stats"]:
            pid, tid = row["player"], row["teamId"]
            if not tid or pid in seen:
                complete = False
                continue
            seen.add(pid)
            team_sizes[tid] = team_sizes.get(tid, 0) + 1
            player = players.setdefault(pid, dict(player=pid, name=row.get("name") or pid, teamId=tid,
                                                  rounds=0, maps=0, totals=dict.fromkeys(COUNTERS, 0)))
            player["rounds"] += count
            player["maps"] += 1
            if player["teamId"] != tid:
                player["teamId"] = None
            valid = count > 0 and all(type(row.get(k)) is int and row[k] >= 0 for k in COUNTERS)
            if not valid or row["kast"] > count or player["totals"] is None:
                player["totals"] = None
            else:
                for field in COUNTERS:
                    player["totals"][field] += row[field]
        if len(team_sizes) != 2 or any(n != 5 for n in team_sizes.values()):
            complete = False
    eligible = []
    for player in players.values():
        totals = player.pop("totals")
        metrics = performance(totals, player["rounds"]) if totals is not None and player["teamId"] else None
        player.update(metrics or dict(impact=None, adr=None, kastPercent=None))
        if player["teamId"] is None:
            complete = False
        if player["teamId"] == winner and 2 * player["rounds"] >= rounds:
            if metrics:
                eligible.append(player)
            else:
                complete = False
    eligible.sort(key=lambda p: (-p["impact"], -p["adr"], -p["kastPercent"], p["player"]))
    return dict(version=VERSION, maps=len(maps), rounds=rounds, players=list(players.values()),
                mvp=eligible[0]["player"] if eligible and complete else None)


def annotate(report, own_team):
    """Add derived fields to the observer's copy, preserving the content-addressed blob."""
    maps = report.get("maps")
    if maps is not None:
        for game in maps:
            game["performance"] = summarize([game], game.get("winnerTeamId"))
    report["performance"] = summarize(maps if maps is not None else [report], report.get("winnerTeamId"))
    if "preparation" in report:
        report["preparation"] = {tid: jobs for tid, jobs in report["preparation"].items() if tid == own_team}
    return report


def profile_rows(career, pack, group, subject, history, read_report, since, edition, map_id):
    """Project official completed maps, including a player's former clubs."""
    from . import historical_protocol

    rows = []
    for event in reversed(history):
        if (event["date"] < since or event["date"] > career["date"] or not event.get("result")
                or (edition and event.get("edition") != edition)
                or (group == "teams" and subject not in event["teams"])):
            continue
        raw = read_report(event["result"])
        maps = raw.get("maps", [raw])
        if group == "players" and not any(any(p["player"] == subject for p in m["stats"]) for m in maps):
            continue
        report = historical_protocol.normalize(career, pack, event, raw)
        games = report.get("maps", [report])
        series_award = summarize(games, report.get("winnerTeamId"))["mvp"]
        for index, game in enumerate(games):
            key = game.get("mapId") or event.get("mapId")
            if key is None and (game.get("rules") or "").startswith("depo-"):
                key = "depo"
            if map_id and key != map_id:
                continue
            selected = [p for p in game["stats"] if
                        (p["player"] == subject if group == "players" else p["teamId"] == subject)]
            if not selected:
                continue
            tid = selected[0]["teamId"]
            opponent = next((t for t in event["teams"] if t != tid), None) if tid else None
            counts = {}
            for field in ("k", "d", "a", *COUNTERS[1:], "clutches"):
                values = [row.get(field) for row in selected]
                counts[field] = sum(values) if all(type(v) is int and v >= 0 for v in values) else None
            length = len(game["rounds"])
            samples = length * len(selected)
            rating = None
            if group == "players" and samples and all(counts[k] is not None for k in COUNTERS):
                rating = performance(counts, samples)["impact"]
            winner = game.get("winnerTeamId")
            rows.append(dict(fixture=event["id"], date=event["date"], edition=event.get("edition"),
                             tournament=event.get("title"), mapId=key, index=index, team=tid, opponent=opponent,
                             score=game.get("scoreByTeam"), won=(winner == tid) if winner and tid else None,
                             rounds=length, playerRounds=samples, impact=rating, counts=counts,
                             mapMvp=summarize([game], winner)["mvp"], seriesMvp=series_award))
    return dict(version=VERSION, asOf=career["date"], rows=rows)
