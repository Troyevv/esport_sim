"""Series orchestration. Map simulation, round history and player state belong to R4.1."""

from copy import deepcopy

from . import staff, cs2_maps, engine, match, match_score, veto, world
from .database import require

VERSION = 1
DETAILED = {"mode": "detailed", "version": 1}


def initial(
    seed,
    best_of,
    domain=None,
    rosters=world.FIXTURE_ROSTERS,
    coach=None,
    *,
    profile=None,
    history=(),
    jobs=None,
    today="2026-11-24",
    detailed=True,
):
    profile = deepcopy(profile or veto.REGULATION)
    budget=profile.get("timeouts",match.RULES["timeouts"])
    require(type(budget) is int and 0 <= budget <= 6 and profile.get("timeoutScope","series") in ("map","series"), "Неверный лимит тайм-аутов")
    if detailed:
        missing = set(profile["pool"]) - set(cs2_maps.installed())
        require(
            not missing, "Недоступны ресурсы карт: " + ", ".join(sorted(missing)) + ". Перезапустите игру для автоматического восстановления."
        )
    domain = domain or world.exhibition(engine.initial(seed)["agents"])
    world.validate(domain)
    teams = [domain["rosters"][r]["team"] for r in rosters]
    require(len(set(teams)) == len(teams) == 2, "Нужны две разные команды")
    w = {
        "version": 3,
        "seed": seed,
        "tick": 0,
        "domain": domain,
        "rosterIds": list(rosters),
        "coachTeamId": coach or teams[0],
    }
    if detailed:
        w["agentPolicy"] = match.AGENT_POLICY
    match.check_coach(w)
    w["series"] = {
        "version": VERSION,
        "seed": seed,
        "bestOf": best_of,
        "profile": profile,
        "teams": teams,
        "steps": veto.sequence(profile, best_of, teams, seed),
        "actions": [],
        "order": [],
        "results": [],
        "stage": "veto",
        "date": today,
        "score": dict.fromkeys(teams, 0),
        "winner": None,
        "evidence": veto.evidence(profile["pool"], teams, history, today),
    }
    if jobs is None:
        # An exhibition has no career agenda. Select its best available specialist.
        jobs = []
        for team in teams:
            candidates = []
            for sid, row in domain["staff"].items():
                if row["team"] == team:
                    person = dict(role=staff.position(row["role"]), **staff.profile(sid, row))
                    candidates.append((staff.quality(person, "veto"), sid, person["philosophy"]))
            if candidates:
                quality, sid, philosophy = max(candidates)
                jobs.append(dict(team=team, person=sid, name=domain["staff"][sid]["name"], quality=quality, duty="veto", philosophy=philosophy))
        auto = False
    else:
        auto = True
    w["series"]["work"] = {t: {j["duty"]: j for j in jobs if j["team"] == t} for t in teams}
    veto.advance(w, "staff" if auto and "veto" in w["series"]["work"][w["coachTeamId"]] else None)
    return w


def command(w, value):
    s = w["series"]
    require(s["stage"] == "veto" and isinstance(value, dict), "Вето завершено")
    step = s["steps"][len(s["actions"])]
    require(step["team"] == w["coachTeamId"], "Ход соперника")
    if set(value) == {"delegate"} and value["delegate"] in ("captain", "staff"):
        require(value["delegate"] != "staff" or "work" not in s or "veto" in s["work"][step["team"]],
                "Нет доступного специалиста по Map Veto")
        veto.advance(w, value["delegate"])
    else:
        require(
            set(value) == {"choice"} and isinstance(value["choice"], str),
            "Укажите выбор",
        )
        veto.apply(s, value["choice"], "manager")
        veto.advance(w)


def map_seed(seed, index):
    return (seed + index * 2654435761) & 0x7FFFFFFF


def next_map(w):
    s = w["series"]
    require(s["stage"] in ("ready", "interval"), "Следующая карта недоступна")
    index = len(s["results"])
    item = s["order"][index]
    game = match.initial(
        map_seed(s["seed"], index),
        w["domain"],
        w["rosterIds"],
        w["coachTeamId"],
        map_id=item["map"],
        first_attack=item["attack"],
        agent_policy=w.get("agentPolicy"),
    )
    budget = s["profile"].get("timeouts",game["remaining"])
    game["remaining"] = budget if s["profile"].get("timeoutScope")=="map" else w.get("remaining",budget)
    game["openingTimeouts"] = game["remaining"]
    s["stage"] = "playing"
    game["series"] = s
    return game


def map_stats(w):
    return [
        dict(
            player=a["playerId"],
            name=a["name"],
            club=a["club"],
            teamId=a["teamId"],
            **w["stats"][a["id"]],
        )
        for a in w["agents"]
    ]


def map_result(w):
    require(w.get("phase") == "finished", "Матч ещё идёт")
    return dict(
        teams=match_score.team_ids(w),
        score=w["score"],
        scoreByTeam=w["scoreByTeam"],
        winnerTeamId=w["winnerTeamId"],
        rules=w["rules"],
        **({"agentPolicy": w["agentPolicy"]} if "agentPolicy" in w else {}),
        map=w["map_version"],
        **({"mapId": w["mapId"]} if w.get("mapId") else {}),
        seed=w["seed"],
        rounds=w["history"],
        ticks=w["tick"],
        events=w["serial"],
        stats=map_stats(w),
    )


def verify_map(report, teams, expected, seed, map_id):
    from . import round_sim

    mode = report.get("simulation", DETAILED)
    require(mode in (round_sim.MODE, DETAILED), "Неизвестная версия симуляции")
    if mode == round_sim.MODE:
        round_sim.validate(report, teams)
    else:
        require(
            report["rules"] in (cs2_maps.SUPPORTED_RULES if map_id else (match.VERSION,))
            and report["map"] == (cs2_maps.BUILD if map_id else match.MAP["version"]),
            "Результат не соответствует версии подробной симуляции",
        )
    points = {
        tid: sum(r["winnerTeamId"] == tid for r in report["rounds"]) for tid in teams
    }
    require(
        report["seed"] == seed
        and report.get("mapId") == map_id
        and len(report["stats"]) == len(expected)
        and {row["player"]: row["teamId"] for row in report["stats"]} == expected
        and set(report["teams"]) == set(points)
        and report["score"] == [points[t] for t in report["teams"]]
        and points == report["scoreByTeam"]
        and len(set(points.values())) == 2
        and report["winnerTeamId"] == max(points, key=points.get)
        and sum(points.values()) == len(report["rounds"]),
        "Результат не соответствует встрече календаря",
    )
    return points


def finish_map(w):
    s = w["series"]
    require(s["stage"] == "playing", "Карта уже учтена")
    report = map_result(w)
    s["results"].append(report)
    winner = report["winnerTeamId"]
    s["score"][winner] += 1
    if s["score"][winner] == s["bestOf"] // 2 + 1:
        s.update(stage="finished", winner=winner)
    else:
        s["stage"] = "interval"


def total_stats(rows):
    totals = {}
    for group in rows:
        for row in group:
            target = totals.setdefault(
                row["player"], {k: row[k] for k in ("player", "name", "teamId", "club")}
            )
            for k in row.keys() - {"player", "name", "teamId", "club"}:
                target[k] = target.get(k, 0) + row[k]
    return list(totals.values())


def result(w):
    s = w["series"]
    require(s["stage"] == "finished", "Серия ещё идёт")
    return {
        "seriesVersion": VERSION,
        "simulation": w.get("simulation", DETAILED),
        "bestOf": s["bestOf"],
        "profile": s["profile"],
        "seed": s["seed"],
        "teams": s["teams"],
        "scoreByTeam": s["score"],
        "score": [s["score"][t] for t in s["teams"]],
        "winnerTeamId": s["winner"],
        "maps": s["results"],
        "veto": s["actions"],
        **({"preparation": {t:{d:{k:j[k] for k in ("person","quality")} for d,j in jobs.items()}
                             for t,jobs in s["work"].items()}} if "work" in s else {}),
        "order": s["order"],
        "stats": total_stats(r["stats"] for r in s["results"]),
        "rounds": [row for r in s["results"] for row in r["rounds"]],
    }


def scouting_record(report):
    maps = []
    for item in report["maps"]:
        sides = {
            t: {
                "attackWins": 0,
                "defenseWins": 0,
                "attackRounds": 0,
                "defenseRounds": 0,
            }
            for t in item["teams"]
        }
        for row in item["rounds"]:
            for team, counts in sides.items():
                won = row["winnerTeamId"] == team
                prefix = "attack" if (row["side"] == "T") == won else "defense"
                counts[prefix + "Rounds"] += 1
                counts[prefix + "Wins"] += int(won)
        maps.append(
            {"map": item["mapId"], "winner": item["winnerTeamId"], "sides": sides}
        )
    return {"maps": maps, "veto": report["veto"]}


def project(w, view="full"):
    s = w["series"]
    public = {
        k: s[k]
        for k in (
            "stage",
            "bestOf",
            "score",
            "winner",
            "teams",
            "steps",
            "actions",
            "order",
        )
    }
    public.update(
        tournament=s.get("tournament"),spectator=s.get("spectator",False),
        pool=s["profile"]["pool"],
        names=cs2_maps.NAMES,
        coach=w["coachTeamId"],
        clubs={
            t: {
                k: v
                for k, v in w["domain"]["teams"][t].items()
                if k in ("name", "visual")
            }
            for t in s["teams"]
        },
        results=[{"map": r["mapId"], "score": r["scoreByTeam"]} for r in s["results"]],
    )
    public["specialists"] = {team: jobs["veto"].get("name", jobs["veto"]["person"])
                             for team, jobs in s.get("work", {}).items() if "veto" in jobs}
    if s["stage"] in ("veto", "ready"):
        public["evidence"] = {
            t: {
                m: {k: row[k] for k in ("wins", "games", "picks", "bans", "weight")}
                for m, row in maps.items()
            }
            for t, maps in s["evidence"].items()
        }
        if s["stage"] == "veto" and not s.get("spectator"):
            advisor = s.get("work", {}).get(w["coachTeamId"], {}).get("veto")
            public["staffAvailable"] = bool(advisor) or "work" not in s
            if advisor:
                public["advisor"] = public["specialists"][w["coachTeamId"]]
            choice = veto.recommend(w, "staff" if public["staffAvailable"] else "captain")
            public["advice"] = choice
            if choice in s["profile"]["pool"]:
                knowledge, assessed, fit = veto.map_fit(
                    veto.own_five(w, w["coachTeamId"]), choice
                )
                public["fit"] = {
                    "knowledge": round(knowledge),
                    "assessed": assessed,
                    "roles": round(fit),
                }
    else:
        groups = [r["stats"] for r in s["results"]]
        rounds = sum(len(r["rounds"]) for r in s["results"])
        public["completedRounds"] = rounds
        if s["stage"] == "playing":
            groups.append(map_stats(w))
            rounds += w["round"]
            public["completedRounds"] += len(w["history"])
        public["rounds"] = rounds
        public["stats"] = total_stats(groups)
        if view != "full" and s["stage"] == "playing":
            own = match_score.side_team(w, view)
            for row in public["stats"]:
                for metric in match.UTILITY_STATS:
                    row.pop(metric, None)
                if row["teamId"] != own:
                    row["spent"] = None
    return public


def validate(w):
    s = w["series"]
    require(
        s["version"] == VERSION
        and s["teams"] == match_score.team_ids(w)
        and s["steps"]
        == veto.sequence(s["profile"], s["bestOf"], s["teams"], s["seed"]),
        "Повреждён регламент серии",
    )
    replay = dict(s, actions=[], order=[], stage="veto")
    for action in s["actions"]:
        require(len(replay["actions"]) < len(s["steps"]), "Лишний ход вето")
        veto.apply(replay, action.get("side", action["map"]), action["by"])
    require(
        replay["actions"] == s["actions"] and replay["order"] == s["order"],
        "Нарушен журнал вето",
    )
    points = dict.fromkeys(s["teams"], 0)
    target = s["bestOf"] // 2 + 1
    expected_players = {
        m["player"]: w["domain"]["rosters"][rid]["team"]
        for rid in w["rosterIds"]
        for m in world.lineup(w["domain"], rid)
    }
    for i, r in enumerate(s["results"]):
        require(
            max(points.values()) < target
            and i < len(s["order"])
            and r["mapId"] == s["order"][i]["map"]
            and r["seed"] == map_seed(s["seed"], i)
            and r["teams"] == s["teams"]
            and r["winnerTeamId"] in points,
            "Нарушен порядок карт серии",
        )
        verify_map(
            r,
            s["teams"],
            expected_players,
            map_seed(s["seed"], i),
            s["order"][i]["map"],
        )
        points[r["winnerTeamId"]] += 1
    winner = next((t for t, p in points.items() if p == target), None)
    if w["version"] == 3:
        expected = replay["stage"]
        require(not s["results"], "Лишние результаты до старта серии")
        world.validate(w["domain"])
        match.check_coach(w)
    else:
        require(replay["stage"] == "ready", "Карта начата до завершения вето")
        ended = w["phase"] == "finished"
        index = len(s["results"]) - int(ended)
        require(
            0 <= index < len(s["order"])
            and w["mapId"] == s["order"][index]["map"]
            and w["firstAttackTeamId"] == s["order"][index]["attack"]
            and w["seed"] == map_seed(s["seed"], index),
            "Активная карта расходится с вето",
        )
        require(
            not ended or s["results"][-1] == map_result(w),
            "Последняя карта расходится с итоговым протоколом",
        )
        require(
            0 <= w["remaining"] <= w["openingTimeouts"] <= s["profile"].get("timeouts",match.RULES["timeouts"]),
            "Повреждён бюджет тайм-аутов",
        )
        expected = "finished" if winner else "interval" if ended else "playing"
    require(
        s["score"] == points and s["winner"] == winner and s["stage"] == expected,
        "Счёт серии расходится с результатами",
    )
