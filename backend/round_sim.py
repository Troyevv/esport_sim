"""Versioned round-level career simulation. No map assets or spatial state."""

from itertools import combinations
from math import exp
from random import Random

from . import coaching, skills, tactics, world
from .match_rules import RULES

LEGACY_MODE = {"mode": "round", "version": 1}
MODE = {"mode": "round", "version": 2}
# Small side priors in skill points, modulated by the actual lineups and purchases.
CT_EDGE = {"de_nuke": 2, "de_train": 2, "de_mirage": 0.8, "de_anubis": -1.5}
FIELDS = "k d a hs damage opening openingDeaths kast spent clutches".split()


# Derived modifiers for the bounded fast-kernel pressure scale.
_STRAIN_EFFECTS = tuple((min(10, s // 5), 1 - s / 320, 1 - s / 400) for s in range(66))


def round_rules(n):
    half, ot = RULES["half"], RULES["overtimeHalf"]
    if n <= half * 2:
        return int(n > half), n in (1, half + 1), half + 1
    after = n - 2 * half - 1
    return (
        1 + (after // ot + 1) // 2,
        after % ot == 0,
        half + ot * (1 + after // (2 * ot)) + 1,
    )


def lineup(domain, rid, map_id, club):
    team = domain["rosters"][rid]["team"]
    rows = []
    members = world.lineup(domain, rid)
    chemistry = (
        sum(
            domain["chemistry"].get(world.pair_key(a["player"], b["player"]), 0)
            for a, b in combinations(members, 2)
        )
        / 10
    )
    for m in members:
        p = domain["players"][m["player"]]
        s, role = p["skills"], m["role"]
        # Neutral career conditions are 50 form/morale and zero fatigue.
        condition = (
            0.10 * (p["form"] - 50)
            + 0.07 * (p["morale"] - 50)
            - 0.13 * p["fatigue"] * (1 - s["fatigue_resistance"] / 180)
        )
        base = (
            0.26 * s["aim"]
            + 0.14 * s["reaction"]
            + 0.17 * skills.role_rating(s, role)
            + 0.10 * p["roleMastery"].get(role, 50)
            + 0.11 * p["mapKnowledge"].get(map_id.removeprefix("de_"), 50)
            + 0.10 * s["decisions"]
            + 0.12 * s["coordination"]
            + condition
        )
        rows.append(
            dict(
                player=m["player"],
                teamId=team,
                club=club,
                name=p["name"],
                base=base,
                attack=0.12 * (s["entry"] + s["execution"] - 100),
                defense=0.12 * (s["positioning"] + s["retakes"] - 100),
                pistol=0.28 * (s["pistols"] - 50),
                rifle=0.2 * (s["sniper_rifles" if role == "awper" else "rifles"] - 50),
                weight=max(0.3, base / 55),
                openingWeight=1.35 if role in ("entry", "awper") else 0.92,
                consistency=s["consistency"],
                wear=(1.0 - s["endurance"] / 160)
                * (1.0 - s["fatigue_resistance"] / 180),
                capacity=(100 - p["fatigue"]) * (1 - s["fatigue_resistance"] / 180),
                recovery=s["recovery"],
                assist=0.20 + s["support"] / 350,
                hs=0.22 + s["first_shot"] / 270,
                risk=s["risk"],
            )
        )
        if m["captain"]:
            calling = (s["calling"] + s["game_reading"] + s["communication"]) / 3
    return rows, 0.12 * (calling - 50) + 0.035 * chemistry


def choose(rng, alive, players, opening=False):
    weights = [
        players[i]["weight"] * (players[i]["openingWeight"] if opening else 1)
        for i in alive
    ]
    return rng.choices(alive, weights)[0]


def purchase(rng, cash, saved, pistol, risk):
    if pistol:
        return "pistol", min(cash, 650), 0.0
    if cash + saved >= 4200:
        return "full", min(cash, 4850 - saved), 6.0
    if cash + saved >= 1700 and (
        cash + saved >= 3200 or rng.random() < 0.24 + risk / 300
    ):
        return "force", min(cash, 3000), -2.0
    return "eco", min(cash, 350), -13.0


def buy_for_team(rng, row, cash, saved, stats, pistol, attacking, strain):
    strength, purchases = 0, []
    for i, p in enumerate(row):
        kind, spent, gear = purchase(rng, cash[i], saved[i], pistol, p["risk"])
        purchases.append(kind)
        cash[i] -= spent
        stats[i]["spent"] += spent
        saved[i] = {"pistol": 0, "full": 3000, "force": 1300, "eco": 0}[kind]
        strength += (
            p["base"]
            - 0.13 * strain.get(p["player"], 0)
            + p["attack" if attacking else "defense"]
            + p["pistol" if pistol or kind == "eco" else "rifle"]
            + gear
        )
    return strength, max(dict.fromkeys(purchases), key=purchases.count)


def resolve_round(rng, powers, players, cash, stats):
    # An objective can settle a late round while players on both sides survive.
    objective_at = rng.randint(4, 8) if rng.random() < 0.36 else 10
    alive = [list(range(5)), list(range(5))]
    contributed = [set(), set()]
    clutch = [None, None]
    last, frags = None, 0
    while alive[0] and alive[1]:
        for side in (0, 1):
            if len(alive[side]) == 1:
                clutch[side] = alive[side][0]
        advantage = powers[0] - powers[1] + 2.7 * (len(alive[0]) - len(alive[1]))
        edge = 1 / (1 + exp(-advantage / 56))
        side = int(rng.random() >= edge)
        if frags == objective_at:
            break
        other = side ^ 1
        shooter = choose(rng, alive[side], players[side], not frags)
        victim = rng.choice(alive[other])
        alive[other].remove(victim)
        killer, dead = stats[side][shooter], stats[other][victim]
        killer["k"] += 1
        killer["hs"] += int(rng.random() < players[side][shooter]["hs"])
        dead["d"] += 1
        if frags == 0:
            killer["opening"] += 1
            dead["openingDeaths"] += 1
        contributed[side].add(shooter)
        mates = [j for j in alive[side] if j != shooter]
        dmg = 100
        if mates and rng.random() < 0.47:
            helper = rng.choices(mates, [players[side][i]["assist"] for i in mates])[0]
            harm = rng.randint(40, 65)
            stats[side][helper]["a"] += 1
            stats[side][helper]["damage"] += harm
            contributed[side].add(helper)
            dmg -= harm
        killer["damage"] += dmg
        if last and last[:2] == (other, victim):
            contributed[side].add(last[2])
        last = side, shooter, victim
        cash[side][shooter] += 300
        frags += 1
    winner = side
    if clutch[winner] is not None:
        stats[winner][clutch[winner]]["clutches"] += 1
    return winner, alive, contributed


def board_lineup(board, rows, domain):
    # A rehearsed five changes who takes first contact according to the saved slot orders.
    # The round resolver keeps the same weapons, team power and damage rules.
    prepared = []
    key = f"{board['id']}@{board['revision']}"
    for p, steps in zip(rows, board["slots"]):
        delay = 0
        for step in steps:
            if step["kind"] in ("exit", "hold", "plant"):
                break
            delay += step.get("seconds", 1)
        learned = domain["players"][p["player"]].get("tactics", {}).get(key, 0) / 100
        planned = 2 / (1 + delay / 3) if steps else p["openingWeight"]
        weight = p["openingWeight"] + learned * (planned - p["openingWeight"])
        prepared.append(dict(p, openingWeight=weight))
    return prepared


def board_applies(board, attacking, buy, previous, club, teams, carried):
    if board["side"] != ("T" if attacking else "CT"):
        return False
    category = board["buy"]
    if category == "Антиэко":
        return (
            buy == "full"
            and previous
            and previous["winnerTeamId"] == teams[club]
            and previous["buys"][1 - club] == "full"
        )
    if category == "Бонусная":
        return (
            buy != "pistol"
            and previous
            and previous["winnerTeamId"] == teams[club]
            and carried >= 2
        )
    if category == "Частичная":
        return buy == "eco" and carried > 0
    return (
        category
        in {
            "pistol": ("Пистолетная",),
            "eco": ("Эко",),
            "full": ("Оружейная", "Полная"),
            "force": ("Оружейная", "Форс"),
        }[buy]
    )


def play_map(game, map_id, first_attack, seed, strain=None):
    # Transient extra fatigue for rounds actually played. Shared only within this series.
    if strain is None:
        strain = {}
    rng = Random(seed)
    domain, rids = game["domain"], game["rosterIds"]
    teams = [domain["rosters"][rid]["team"] for rid in rids]
    players, teamwork = zip(
        *(lineup(domain, rid, map_id or "depo", i) for i, rid in enumerate(rids))
    )
    active_coaching = game.get("simulation") != LEGACY_MODE
    if active_coaching:
        from ._match_native import timeout_need, timeout_repeat_cost

        bench = coaching.bench(domain)
        series = game.get("series", {})
        regulation = series.get("profile", {})
        limit = regulation.get("timeouts", RULES["timeouts"])
        budgets = dict.fromkeys(teams, limit)
        if regulation.get("timeoutScope", "series") == "series" and series.get(
            "results"
        ):
            budgets.update(series["results"][-1].get("remainingTimeouts", {}))
        duration = regulation.get("timeoutSeconds", RULES["timeoutSeconds"])
        series_stakes = [
            domain.get("matchImportance", 0) // 3
            + 3
            * (
                series.get("bestOf", 1) > 1
                and series.get("score", {}).get(team, 0) == series["bestOf"] // 2
            )
            for team in teams
        ]
        last_break = [None, None]
        last_load = [0, 0]
        pressure = [0, 0]
        setbacks = [0, 0]
        recent = [0, 0]
        for row in players:
            for player in row:
                profile = domain["players"][player["player"]]
                stability = profile["skills"]["stress_resistance"]
                # The four outcome loads depend only on the player's resilience and round result.
                player.update(
                    strainOfPlay=0,
                    loads=tuple(v * (145 - stability) // 75 for v in (-9, 3, 1, 13)),
                    usualRisk=player["risk"],
                    usualOpening=player["openingWeight"],
                    usualAssist=player["assist"],
                )
    board = game.get("practiceBoard")
    if board:
        club = teams.index(game["practiceTeam"])
        prepared = list(players)
        prepared[club] = board_lineup(board, players[club], domain)
        if active_coaching:
            rehearsed = [p["openingWeight"] / p["usualOpening"] for p in prepared[club]]
    # Correlated map-to-map execution varies with the consistency of the five.
    execution = [
        rng.gauss(0, 3 + (100 - sum(p["consistency"] for p in row) / 5) * 0.07)
        for row in players
    ]
    stats = [
        [
            dict.fromkeys(FIELDS, 0)
            | {k: p[k] for k in ("player", "teamId", "club", "name")}
            for p in row
        ]
        for row in players
    ]
    scores, losses, rounds = [0, 0], [0, 0], []
    cash, saved = [[0] * 5 for _ in teams], [[0] * 5 for _ in teams]
    while True:
        n = len(rounds) + 1
        swaps, reset, target = round_rules(n)
        attack = teams.index(first_attack) ^ (swaps % 2)
        pistol = reset and n <= 2 * RULES["half"]
        if reset:
            cash = [
                [RULES["startMoney"] if pistol else RULES["overtimeMoney"]] * 5
                for _ in teams
            ]
            saved, losses = [[0] * 5 for _ in teams], [0, 0]
        called_break = None
        if active_coaching and rounds:
            rounds_left = target - max(scores)
            round_stakes = 8 * (rounds_left <= 1) + 4 * (n > 2 * RULES["half"])
            best = 0
            for side, team in enumerate(teams):
                if not budgets[team]:
                    continue
                poor_buy = rounds[-1]["buys"][side] in ("eco", "force")
                stakes = series_stakes[side] + round_stakes
                load = pressure[side] // 5
                need = timeout_need(
                    load,
                    setbacks[side],
                    scores[1 - side] - scores[side],
                    recent[side],
                    4 if poor_buy else 0,
                    stakes,
                    rounds_left,
                    budgets[team],
                    bench[team]["analysis"],
                )
                if last_break[side] is not None:
                    need -= timeout_repeat_cost(
                        n - last_break[side],
                        last_load[side],
                        load,
                        rounds[-1]["winnerTeamId"] == team,
                        stakes,
                    )
                if need > best:
                    best, called_break = need, team
            if called_break:
                side = teams.index(called_break)
                budgets[called_break] -= 1
                last_break[side] = n
                last_load[side] = pressure[side] // 5
                for p in players[side]:
                    if duration < 10:
                        continue
                    p["strainOfPlay"] = max(
                        0, p["strainOfPlay"] - bench[called_break]["support"] // 10
                    )
                    if duration < 25 or (setbacks[side] == 0 and recent[side] < 2):
                        continue
                    # Reassign first contact to the readiest player and adjust the risk of a force buy.
                    p["openingWeight"] = p["usualOpening"] * (
                        1.12 if p["strainOfPlay"] < 20 else 0.83
                    )
                    p["risk"] = max(
                        0,
                        min(
                            100,
                            p["usualRisk"]
                            + (10 if bench[called_break]["bold"] else -15),
                        ),
                    )
        if board:
            carried = sum(0 < value < 3000 for value in saved[club])
        powers, buys = [], []
        for side, row in enumerate(players):
            strength, buy = buy_for_team(
                rng,
                row,
                cash[side],
                saved[side],
                stats[side],
                pistol,
                side == attack,
                strain,
            )
            powers.append(
                strength / 5
                + teamwork[side]
                + execution[side]
                + (0 if side == attack else CT_EDGE.get(map_id, 0))
            )
            buys.append(buy)
        called = board and board_applies(
            board,
            attack == club,
            buys[club],
            rounds[-1] if rounds and not reset else None,
            club,
            teams,
            carried,
        )
        if called and active_coaching:
            for planned, current, factor in zip(
                prepared[club], players[club], rehearsed
            ):
                planned["openingWeight"] = current["openingWeight"] * factor
                planned["assist"] = current["assist"]
        winner, alive, contributed = resolve_round(
            rng, powers, prepared if called else players, cash, stats
        )
        scores[winner] += 1
        for side in (0, 1):
            if active_coaching:
                pressure[side] = setbacks[side] = 0
                coached = called_break == teams[side]
                outcome = 2 * (side != winner)
                recent[side] += int(side != winner)
                if len(rounds) >= 3:
                    recent[side] -= int(rounds[-3]["winnerTeamId"] != teams[side])
            # Surviving opponents may also have taken non-lethal damage.
            for _ in alive[side ^ 1]:
                if rng.random() < 0.80:
                    stats[side][rng.randrange(5)]["damage"] += rng.randint(12, 65)
            reward = (
                RULES["win"]
                if side == winner
                else min(
                    RULES["lossMax"],
                    RULES["lossBase"] + losses[side] * RULES["lossStep"],
                )
            )
            for i in range(5):
                player = players[side][i]
                pid = player["player"]
                strain[pid] = min(
                    player["capacity"], strain.get(pid, 0) + player["wear"]
                )
                survived = i in alive[side]
                helped = i in contributed[side]
                if active_coaching:
                    previous = player["strainOfPlay"]
                    load = player["loads"][outcome + (not survived)]
                    stress = previous * 4 // 5 + load - 3 * helped
                    stress = 0 if stress < 0 else 65 if stress > 65 else stress
                    pressure[side] += stress
                    setbacks[side] += stress > 24
                    if stress != previous or coached:
                        player["strainOfPlay"] = stress
                        risk, opening, assist = _STRAIN_EFFECTS[stress]
                        player["risk"] = player["usualRisk"] + risk
                        player["openingWeight"] = player["usualOpening"] * opening
                        player["assist"] = player["usualAssist"] * assist
                stats[side][i]["kast"] += int(survived or helped)
                if not survived:
                    saved[side][i] = 0
                cash[side][i] = min(RULES["cap"], cash[side][i] + reward)
            losses[side] = (
                max(0, losses[side] - 1) if side == winner else min(4, losses[side] + 1)
            )
        rounds.append(
            dict(
                round=n,
                winnerTeamId=teams[winner],
                side="T" if winner == attack else "CT",
                score=scores.copy(),
                buys=buys,
                reason="objective" if all(alive) else "elimination",
            )
        )
        if called_break:
            rounds[-1]["timeoutTeam"] = called_break
        if called:
            rounds[-1]["tactic"] = tactics.reference(board)
        if scores[winner] == target:
            break
    for row in players:
        for p in row:
            strain[p["player"]] *= 1 - p["recovery"] / 160
    return dict(
        simulation=MODE if active_coaching else LEGACY_MODE,
        rules="round-mr12.2" if active_coaching else "round-mr12.1",
        **({"remainingTimeouts": budgets} if active_coaching else {}),
        mapId=map_id,
        seed=seed,
        teams=teams,
        score=scores,
        scoreByTeam=dict(zip(teams, scores)),
        winnerTeamId=teams[winner],
        firstAttackTeamId=first_attack,
        rounds=rounds,
        stats=stats[0] + stats[1],
    )


def validate(report, teams):
    from .database import require

    ok = report["rules"] == ("round-mr12.2" if report.get("simulation") == MODE else "round-mr12.1") and report["firstAttackTeamId"] in teams
    points = dict.fromkeys(teams, 0)
    rows = report["rounds"]
    for n, r in enumerate(rows, 1):
        swaps, reset, target = round_rules(n)
        attack = teams[teams.index(report["firstAttackTeamId"]) ^ (swaps % 2)]
        tid = r["winnerTeamId"]
        require(tid in points, "Неизвестный победитель раунда")
        points[tid] += 1
        ok = (
            ok
            and r["round"] == n
            and r["score"] == [points[t] for t in teams]
            and (
                r["side"] == ("T" if tid == attack else "CT")
                and (points[tid] == target) == (n == len(rows))
                and len(r["buys"]) == 2
                and set(r["buys"]) <= {"pistol", "eco", "force", "full"}
                and r["reason"] in ("objective", "elimination")
            )
        )
    stats = report["stats"]
    ok = ok and all(
        all(type(p[k]) is int and p[k] >= 0 for k in FIELDS)
        and p["d"] <= len(rows)
        and p["kast"] <= len(rows)
        and p["opening"] <= p["k"]
        and p["openingDeaths"] <= p["d"]
        and p["hs"] <= p["k"]
        for p in stats
    )
    for team in teams:
        own = [p for p in stats if p["teamId"] == team]
        other = [p for p in stats if p["teamId"] != team]
        kills = sum(p["k"] for p in own)
        damage = sum(p["damage"] for p in own)
        ok = (
            ok
            and kills == sum(p["d"] for p in other)
            and kills * 100 <= damage <= len(rows) * 500
        )
        ok = ok and sum(p["opening"] for p in own) == sum(
            p["openingDeaths"] for p in other
        )
    require(
        ok and sum(p["opening"] for p in stats) == len(rows),
        "Результат не соответствует раундовому протоколу",
    )
