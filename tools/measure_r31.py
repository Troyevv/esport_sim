"""Run paired BO1 experiments through the production engine. python -m tools.measure_r31"""

import argparse
import json
import platform
import time
from collections import Counter

import psutil

from backend import engine, match, skills, world
from backend.match_rules import WEAPONS

# Equal point budgets: four attributes at 90 instead of 65 on every player.
PROFILES = {
    "shooter": ("aim", "first_shot", "reaction", "rifles"),
    "tactical": ("game_reading", "calling", "decisions", "positioning"),
    "support": ("flashes", "smokes", "coordination", "trades"),
}


def experiment(seed, club, keys, process):
    data = world.exhibition(engine.initial(seed)["agents"])
    for p in data["players"].values():
        p["skills"] = dict.fromkeys(skills.KEYS, 65)
    for m in world.lineup(data, world.FIXTURE_ROSTERS[club]):
        data["players"][m["player"]]["skills"].update(dict.fromkeys(keys, 90))
    w = match.initial(seed, data)
    rss = process.memory_info().rss
    while w["phase"] != "finished":
        match.advance(w)
        if w["tick"] % 128 == 0:
            rss = max(rss, process.memory_info().rss)
    ids = {a["id"] for a in w["agents"] if a["club"] == club}
    totals = Counter(
        matches=1,
        wins=int(w["score"][club] > w["score"][1 - club]),
        rounds=sum(w["score"]),
        roundsWon=w["score"][club],
        ticks=w["tick"],
    )
    for batch in [*w["archive"], w["events"]]:
        for e in batch:
            if e.get("player") not in ids:
                continue
            if e["kind"] == "shot":
                totals["shots"] += 1
            elif e["kind"] == "damage" and e["weapon"] in WEAPONS:
                totals["hits"] += 1
            elif e["kind"] == "rotate":
                totals["rotations"] += 1
            elif e["kind"] == "kill" and e["enemy"] and e["trade"]:
                totals["trades"] += 1
    return totals, max(rss, process.memory_info().rss)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=32)
    parser.add_argument("--first-seed", type=int, default=1)
    args = parser.parse_args()
    if args.seeds < 1:
        parser.error("--seeds must be positive")
    started = time.perf_counter()
    process = psutil.Process()
    peak = 0
    profiles = {}
    for name, keys in PROFILES.items():
        totals = Counter()
        for seed in range(args.first_seed, args.first_seed + args.seeds):
            for club in (0, 1):
                counts, rss = experiment(seed, club, keys, process)
                totals.update(counts)
                peak = max(peak, rss)
        profiles[name] = totals
    print(
        json.dumps(
            dict(
                rules=match.VERSION,
                catalog=skills.VERSION,
                seeds=[args.first_seed, args.first_seed + args.seeds - 1],
                python=platform.python_version(),
                machine=platform.machine(),
                wallSeconds=round(time.perf_counter() - started, 2),
                peakSampledRSSMiB=round(peak / 2**20, 1),
                profiles=profiles,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
