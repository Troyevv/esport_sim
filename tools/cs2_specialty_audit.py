"""Controlled execution of equipment specialties absent in the automatic buy cohorts."""

import argparse
import gzip
import json
from math import dist
from pathlib import Path
from statistics import mean

from tests.reference_kernel import cs2_maps, match, match_ai, match_performance as performance
from backend import career, database
from backend.match_rules import WEAPONS


def measure(name, pack):
    teams = sorted(career.roster_index(pack).values())[:2]
    game = match.initial(41000, database.match_input(pack, teams), teams, map_id=name)
    actor = game["agents"][0]
    player = match.profile(game, actor)
    player["skills"] = dict.fromkeys(player["skills"], 65)
    player["form"] = 50
    actor.update(dayRoll=0, pressure=0, observedSpeed=0, lastMove=-100, lastHurt=-100, liveStart=0)
    space = cs2_maps.get(name)
    origin = cs2_maps.xyz(actor)
    candidates = sorted((abs(40 - dist(origin, p)), i, p) for i,p in space.centers.items()
                        if 25 <= dist(origin, p) <= 55 and abs(origin[2] - p[2]) < 4)
    target = next(p for _, _, p in candidates if space.hit(origin, p, 1, 64) is None)
    sight = dict(zip(("x", "y", "z"), target))
    rows = []
    for value in (45, 65, 85):
        rates = {}
        for weapon in ("Nova", "Negev"):
            actor["weapon"] = weapon
            player["skills"][performance.WEAPON_CLASS[weapon]] = value
            rates[weapon] = performance.accuracy(
                player, actor, WEAPONS[weapon], match_ai.distance(actor, sight), 0, 0
            )
        player["skills"]["decoys"] = value
        errors = []
        for seed in range(128):
            actor.update(rng=seed, utility=["Ложная"])
            match_ai.throw(game, actor, dict(sight, utility="Ложная"), space)
            landed = cs2_maps.xyz(game["effects"][-1])
            errors.append(dist(landed, target) * cs2_maps.UNIT)
        rows.append(dict(mastery=value, accuracy=rates, meanLandingErrorHU=round(mean(errors), 2)))
    return dict(map=name, rangeHU=round(dist(origin, target)*cs2_maps.UNIT), measurements=rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    package = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    measurements = [measure(name, package) for name in cs2_maps.NAMES]
    args.out.parent.mkdir(exist_ok=True, parents=True)
    args.out.write_text(json.dumps(measurements, indent=2), encoding="utf-8")
