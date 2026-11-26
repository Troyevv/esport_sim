"""Versioned exhibition regulations and decisions from each team's scouting view."""

from datetime import date
from random import Random
from statistics import mean

from . import cs2_maps, skills, world
from .database import require

ACTIVE = (
    "de_ancient",
    "de_anubis",
    "de_cache",
    "de_dust2",
    "de_inferno",
    "de_mirage",
    "de_nuke",
)
# Gameplay preferences for exhibition scouting, not measured professional win rates.
ROLE_FIT = {
    "de_ancient": "entry support",
    "de_anubis": "lurker support",
    "de_cache": "entry awper",
    "de_dust2": "awper rifler",
    "de_inferno": "support entry",
    "de_mirage": "awper lurker",
    "de_nuke": "lurker support",
    "de_train": "awper support",
    "de_vertigo": "entry rifler",
}
REGULATION = {
    "id": "exhibition.202611.1",
    "pool": list(ACTIVE),
    "first": "draw",
    "formats": {
        "1": ["ban"] * 6,
        "3": ["ban", "ban", "pick", "pick", "ban", "ban"],
        "5": ["ban", "ban", "pick", "pick", "pick", "pick"],
    },
    "pickSide": "opponent",
    "deciderSide": "second",
}


def sequence(profile, best_of, teams, seed):
    require(type(best_of) is int and best_of in (1, 3, 5), "Неизвестный формат серии")
    pool = profile["pool"]
    schedule = profile["formats"][str(best_of)]
    # A profile may name the acting slot explicitly, including consecutive bans by one club.
    moves = [item["kind"] if isinstance(item, dict) else item for item in schedule]
    actors = [
        item["actor"] if isinstance(item, dict) else i % 2
        for i, item in enumerate(schedule)
    ]
    require(
        all(type(actor) is int and actor in (0, 1) for actor in actors),
        "Неизвестный участник вето",
    )
    require(
        len(set(pool)) == len(pool)
        and set(pool) <= cs2_maps.NAMES.keys()
        and len(moves) == len(pool) - 1
        and moves.count("pick") == best_of - 1
        and set(moves) <= {"pick", "ban"},
        "Неверная последовательность регламента",
    )
    require(
        profile["first"] in ("home", "away", "draw")
        and profile["pickSide"] in ("picker", "opponent")
        and profile["deciderSide"] in ("first", "second"),
        "Неверное право выбора",
    )
    first = {"home": 0, "away": 1, "draw": Random(seed).randrange(2)}[profile["first"]]
    steps = []
    for i, move in enumerate(moves):
        actor = first ^ actors[i]
        steps.append({"kind": move, "team": teams[actor]})
        if move == "pick":
            steps.append(
                {
                    "kind": "side",
                    "team": teams[actor ^ (profile["pickSide"] == "opponent")],
                }
            )
    return steps + [
        {"kind": "decider", "team": None},
        {"kind": "side", "team": teams[first ^ (profile["deciderSide"] == "second")]},
    ]


def evidence(pool, teams, history, today):
    """Only completed public results and recorded veto actions available by match day."""
    result = {
        t: {
            m: {
                "games": 0,
                "wins": 0,
                "picks": 0,
                "bans": 0,
                "weight": 0.0,
                "weightedWins": 0.0,
                "attackWins": 0,
                "attackRounds": 0,
                "defenseWins": 0,
                "defenseRounds": 0,
            }
            for m in pool
        }
        for t in teams
    }
    for event in history:
        age = (date.fromisoformat(today) - date.fromisoformat(event["date"])).days
        if age < 0:
            continue
        weight = 0.5 ** (age / 90)
        for action in event.get("veto", []):
            if (
                action["kind"] in ("pick", "ban")
                and action["team"] in result
                and action["map"] in pool
            ):
                result[action["team"]][action["map"]][action["kind"] + "s"] += 1
        facts = event.get("maps", [])
        if not facts and event.get("mapId") and event.get("winnerTeamId"):
            facts = [{"map": event["mapId"], "winner": event["winnerTeamId"]}]
        for fact in facts:
            for team in set(event["teams"]).intersection(teams):
                if fact["map"] not in pool:
                    continue
                row = result[team][fact["map"]]
                won = team == fact["winner"]
                row["games"] += 1
                row["wins"] += int(won)
                row["weight"] += weight
                row["weightedWins"] += weight * won
                for key, value in fact.get("sides", {}).get(team, {}).items():
                    row[key] += weight * value
    return result


def available(s):
    used = {a["map"] for a in s["actions"]}
    return [m for m in s["profile"]["pool"] if m not in used]


def own_five(w, team):
    rid = next(r for r in w["rosterIds"] if w["domain"]["rosters"][r]["team"] == team)
    return [
        (m, w["domain"]["players"][m["player"]]) for m in world.lineup(w["domain"], rid)
    ]


def map_fit(people, map_id):
    known = [
        p["mapKnowledge"][map_id[3:]]
        for _, p in people
        if map_id[3:] in p["mapKnowledge"]
    ]
    suited = [
        skills.role_rating(p["skills"], m["role"])
        for m, p in people
        if m["role"] in ROLE_FIT.get(map_id, "").split()
    ]
    knowledge = (sum(known) + 50 * (len(people) - len(known))) / len(people)
    return knowledge, len(known), mean(suited) if suited else 50


def recommend(w, delegate):
    s = w["series"]
    index = len(s["actions"])
    step = s["steps"][index]
    team = step["team"]
    people = own_five(w, team)
    captain = next(p["skills"] for m, p in people if m["captain"])
    opponent = next(t for t in s["teams"] if t != team)
    scouting = s["evidence"]
    rng = Random(f"{s['seed']}/{index}/{delegate}")
    work = s.get("work", {}).get(team, {})
    specialist = work.get("veto") if delegate == "staff" else None
    analysis = 0.35 + captain["game_reading"] / 180
    noise = 0.025 + captain["risk"] / 1200
    philosophy = {}
    if specialist:
        analysis = 0.3 + specialist["quality"] / 125
        noise = 0.09 - specialist["quality"] / 1250
        philosophy = specialist["philosophy"]
    if "opponent" in work:
        analysis = (analysis + .3 + work["opponent"]["quality"] / 120) / 2
    if step["kind"] == "side":
        row = scouting[team][s["order"][-1]["map"]]

        def side_value(prefix):
            return (row[prefix + "Wins"] + 4) / (row[prefix + "Rounds"] + 8)

        attack = (
            side_value("attack")
            - side_value("defense")
            + (captain["aggression"] - 50) / 500
        )
        attack += {"Агрессивный": .035, "Осторожный": -.035}.get(philosophy.get("Стиль игры"), 0)
        return "T" if attack + rng.uniform(-0.06, 0.06) > 0 else "CT"

    def value(map_id):
        own, other = scouting[team][map_id], scouting[opponent][map_id]
        knowledge, _, fit = map_fit(people, map_id)
        prior = 0.5 + (knowledge - 50) / 160 + (fit - 50) / 350

        def estimate(row, prior):
            return (row["weightedWins"] + 5 * prior) / (row["weight"] + 5)

        preference = lambda row: (
            (row["picks"] - row["bans"]) / (5 + row["picks"] + row["bans"])
        )
        if philosophy.get("Подготовка") == "Специализация на картах":
            prior += (knowledge - 50) / 350
        advantage = estimate(own, prior) - analysis * estimate(other, 0.5)
        advantage += 0.09 * (preference(own) - analysis * preference(other))
        if philosophy.get("Адаптация") == "Экспериментальная":
            advantage += 0.035 / (1 + own["games"])
        return advantage + rng.uniform(-noise, noise)

    choose = min if step["kind"] == "ban" else max
    return choose(available(s), key=value)


def apply(s, value, by):
    step = s["steps"][len(s["actions"])]
    team, kind = step["team"], step["kind"]
    if kind == "side":
        require(value in ("T", "CT"), "Выберите стартовую сторону")
        item = s["order"][-1]
        item["attack"] = (
            team if value == "T" else next(t for t in s["teams"] if t != team)
        )
        event = dict(**step, map=item["map"], side=value, by=by)
    else:
        require(value in available(s), "Карта уже выбрана или отсутствует в пуле")
        event = dict(**step, map=value, by=by)
        if kind != "ban":
            s["order"].append({"map": value, "picker": team, "attack": None})
    s["actions"].append(event)
    if len(s["actions"]) == len(s["steps"]):
        s["stage"] = "ready"


def advance(w, delegate=None):
    s = w["series"]
    while s["stage"] == "veto":
        step = s["steps"][len(s["actions"])]
        if step["kind"] == "decider":
            apply(s, available(s)[0], "rules")
        elif step["team"] == w["coachTeamId"] and delegate is None:
            break
        else:
            by = delegate if step["team"] == w["coachTeamId"] else (
                "staff" if "veto" in s.get("work", {}).get(step["team"], {}) else "captain")
            apply(s, recommend(w, by), by)
