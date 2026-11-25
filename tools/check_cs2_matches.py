"""Run event-driven BO1s against the installed map pack and record replay samples."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import random
from collections import defaultdict
import cProfile
import pstats
from time import perf_counter

import psutil
from backend import career, cs2_maps, database, match


def play(name, seed, pair, pack, replay, adjustment=0):
    started = perf_counter()
    domain = database.match_input(pack, pair)
    if adjustment:
        for member in domain["rosters"][pair[0]]["members"]:
            pid = member["player"]
            for skill in (
                "aim",
                "reaction",
                "calling",
                "communication",
                "trades",
                "positioning",
                "retakes",
                "execution",
            ):
                skills = domain["players"][pid]["skills"]
                skills[skill] = max(0, min(100, skills[skill] + adjustment))
    game = match.initial(seed, domain, pair, map_id=name)
    peak = 0
    process = psutil.Process()
    frames = []
    saves = set()
    retakes = set()
    stalls = set()
    blocked_areas = Counter()
    blocked_tasks = Counter()
    examples = []
    team_sides = {}
    outcomes = []
    while game["phase"] != "finished":
        match.advance(game)
        tick = game["tick"]
        if tick > 180000:
            raise RuntimeError(f"{name}/{seed}: BO1 превысил 180000 тиков")
        if replay:
            for e in reversed(game["events"]):
                if e["tick"] != tick:
                    break
                if e["kind"] in {
                    "plant",
                    "defuse",
                    "kill",
                    "rotate",
                    "round_end",
                    "explode",
                    "throw",
                }:
                    outcomes.append(e)
        if tick % 10 == 0:
            for a in game["agents"]:
                team_sides[game["round"], a["id"]] = a["team"]
                if not a["hp"]:
                    continue
                if a["status"] == "Сохраняет оружие":
                    saves.add((game["round"], a["id"]))
                if a["status"] == "Идёт на ретейк":
                    retakes.add(game["round"])
                if a.get("blockedTicks", 0) >= 20:
                    episode = (game["round"], a["id"])
                    if episode not in stalls:
                        blocked_tasks[a["status"]] += 1
                        if len(examples) < 4:
                            examples.append(
                                dict(
                                    tick=tick,
                                    player=a["id"],
                                    area=a["navArea"],
                                    goal=a.get("blockedGoal"),
                                    task=a["status"],
                                    phase=game["phase"],
                                )
                            )
                    stalls.add(episode)
                    blocked_areas[a["navArea"]] += 1
            if replay:
                frames.append(
                    [
                        tick,
                        game["round"],
                        game["phase"],
                        [
                            [
                                round(a["x"], 1),
                                round(a["y"], 1),
                                round(a["z"], 1),
                                a["hp"],
                                a["status"],
                            ]
                            for a in game["agents"]
                        ],
                    ]
                )
        if tick % 200 == 0:
            peak = max(peak, process.memory_info().rss)
    rounds = game["archive"] + [game["events"]]
    trades = own = rotations = 0
    utility = Counter()
    plans = Counter()
    plants = 0
    survived = set(saves)
    for n, events in enumerate(rounds, 1):
        for event in events:
            kind = event["kind"]
            plants += kind == "plant"
            rotations += kind == "rotate"
            if kind == "kill":
                survived.discard((n, event["target"]))
                trades += bool(event["trade"])
                own += (
                    event["weapon"] == "C4"
                    and team_sides.get((n, event["target"])) == "T"
                )
            if kind == "throw":
                utility[event["utility"]] += 1
            if kind == "plan" and event["team"] == "T":
                plans[event["site"] + " " + event["style"]] += 1
    first_id = domain["rosters"][pair[0]]["team"]
    if hasattr(process.memory_info(), "peak_wset"):
        peak = max(peak, process.memory_info().peak_wset)
    else:
        import resource

        peak = max(peak, resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)
    results = dict(
        homeRounds=game["scoreByTeam"][first_id],
        homeKills=sum(
            game["stats"][a["id"]]["k"]
            for a in game["agents"]
            if a["teamId"] == first_id
        ),
        seed=seed,
        map=name,
        teams=[game["domain"]["teams"][t]["name"] for t in game["scoreByTeam"]],
        score=game["score"],
        rounds=len(rounds),
        ticks=game["tick"],
        seconds=round(perf_counter() - started, 3),
        peakMiB=round(max(peak, process.memory_info().rss) / 2**20, 1),
        reasons=Counter(h["reason"] for h in game["history"]),
        sides=Counter(h["side"] for h in game["history"]),
        plants=plants,
        retakes=len(retakes),
        saveDecisions=len(saves),
        saved=len(survived),
        ownC4=own,
        utility=utility,
        plans=plans,
        rotations=rotations,
        trades=trades,
        stalls=len(stalls),
        blockedAreas=blocked_areas.most_common(8),
        blockedTasks=blocked_tasks,
        blockedExamples=examples,
    )
    return results, frames, outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--games", type=int, default=12)
    parser.add_argument("--seed", type=int, default=41000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(pack).values())
    args.out.mkdir(exist_ok=True, parents=True)
    rows = []
    profiler = cProfile.Profile()
    for i in range(args.games):
        seed = args.seed + i
        pair = random.Random(seed).sample(rosters, 2)
        if i == 1:
            profiler.enable()
        row, frames, events = play(args.map, seed, pair, pack, i == 0)
        if i == 1:
            profiler.disable()
            profiler.dump_stats(str(args.out / (args.map + ".prof")))
            pstats.Stats(profiler).strip_dirs().sort_stats("tottime").print_stats(15)
            row["profiled"] = True
        rows.append(row)
        print("BO1", json.dumps(row, ensure_ascii=False), flush=True)
        if frames:
            (args.out / (args.map + "-frames.json")).write_text(
                json.dumps(frames, ensure_ascii=False)
            )
            # Short, evenly spaced samples can also be viewed from the CI journal.
            (args.out / (args.map + "-events.json")).write_text(
                json.dumps(events, ensure_ascii=False)
            )
            by_round = defaultdict(list)
            for tick, number, phase, agents in frames[::3]:
                by_round[number].append([tick, phase, [a[:4] for a in agents]])
            for number, samples in by_round.items():
                print(
                    "RADAR",
                    number,
                    json.dumps(samples, separators=(",", ":")),
                    flush=True,
                )
    for i in range(min(6, args.games)):
        seed = args.seed + i
        pair = random.Random(seed).sample(rosters, 2)
        altered, _, _ = play(args.map, seed, pair, pack, False, adjustment=-20)
        print(
            "PAIRED",
            json.dumps(
                dict(
                    seed=seed,
                    ordinary=rows[i]["homeRounds"],
                    reduced=altered["homeRounds"],
                    kills=rows[i]["homeKills"],
                    reducedKills=altered["homeKills"],
                ),
                ensure_ascii=False,
            ),
            flush=True,
        )
    (args.out / (args.map + ".json")).write_text(
        json.dumps(rows, ensure_ascii=False, indent=2)
    )


if __name__ == "__main__":
    main()
