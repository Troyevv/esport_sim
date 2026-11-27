"""Compare motion estimates against an observer's ground truth after sight is lost."""

import argparse
import gzip
import json
from math import dist
from pathlib import Path
import random

from tests.reference_kernel import cs2_defense, cs2_maps, match
from backend import career, database


def prior_estimate(space, report, age, reading):
    """The cs2-bo1.16 projection, retained here as a fixed observer control."""
    pos = cs2_maps.xyz(report)
    travel = min(age + 2, 14) * min(2, report["speed"]) * reading / 100
    target = tuple(p + d * travel for p, d in zip(pos, report["direction"]))
    return target if space.hit(pos, target, 1, 48) is None else pos


def observe(name, seed, teams, package):
    game = match.initial(seed, database.match_input(package, teams), teams, map_id=name)
    space = cs2_maps.get(name)
    players = {a["id"]: a for a in game["agents"]}
    error = {
        key: 0.0 for key in ("last", "prior65", "prior85", "current65", "current85")
    }
    samples = 0
    while game["phase"] != "finished":
        match.advance(game)
        now = game["tick"]
        if now % 5 or game["phase"] not in ("live", "planted"):
            continue
        for observer in players.values():
            if not observer["hp"]:
                continue
            for report in observer["knowledge"].values():
                age = now - report["tick"]
                if (
                    not 1 <= age <= 24
                    or report["source"] not in ("Радио", "Зрение")
                    or not report.get("direction")
                    or report["id"] in observer["visible"]
                ):
                    continue
                target = players.get(report["id"])
                if not target or not target["hp"]:
                    continue
                actual = cs2_maps.xyz(target)
                samples += 1
                error["last"] += dist(cs2_maps.xyz(report), actual) * cs2_maps.UNIT
                for level in (65, 85):
                    old = prior_estimate(space, report, age, level)
                    current = cs2_defense.anticipated(space, report, now, level)
                    error[f"prior{level}"] += dist(old, actual) * cs2_maps.UNIT
                    error[f"current{level}"] += dist(current, actual) * cs2_maps.UNIT
    return dict(map=name, seed=seed, teams=teams, samples=samples, errorSumHU=error)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[59000, 81002])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    package = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(package).values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as output:
        for seed in args.seeds:
            teams = random.Random(seed).sample(rosters, 2)
            for order in (teams, teams[::-1]):
                row = observe(args.map, seed, order, package)
                print(json.dumps(row), file=output, flush=True)


if __name__ == "__main__":
    main()
