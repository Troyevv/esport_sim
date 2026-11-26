"""Offline matched ablation of the previous throw, buy and crossfire decisions."""

import argparse
import gzip
import json
from pathlib import Path
import random
import subprocess
from types import ModuleType
from unittest.mock import patch

from backend import career, cs2_economy, cs2_maps, cs2_play, database
from tools.cs2_tactical_audit import run


REFERENCE = "68d7f4f"


def historical(name):
    source = subprocess.check_output(["git", "show", f"{REFERENCE}:backend/{name}.py"], text=True)
    module = ModuleType("backend." + name)
    module.__package__ = "backend"
    module.__file__ = str(Path(cs2_maps.__file__).with_name(name + ".py"))
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    old_play = historical("cs2_play")
    old_buy = historical("cs2_economy").buy
    old_crossfire = historical("cs2_maps").Map._crossfire
    current = cs2_play.crossing_utility

    def old_attack(space, w, actor, allies, order, site):
        policy = old_play.crossing_utility if actor["team"] == "T" else current
        return policy(space, w, actor, allies, order, site)

    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(pack).values())
    args.out.parent.mkdir(exist_ok=True, parents=True)
    with args.out.open("w", encoding="utf-8") as report:
        for name, obj, attr, replacement in (
            ("attackUtility", cs2_play, "crossing_utility", old_attack),
            ("buy", cs2_economy, "buy", old_buy),
            ("crossfire", cs2_maps.Map, "_crossfire", old_crossfire),
        ):
            with patch.object(obj, attr, replacement):
                # Geometry and its caches bind the crossfire function at construction.
                cs2_maps._load.cache_clear()
                for seed in (41000,59000):
                    pair = random.Random(seed).sample(rosters, 2)
                    for teams in (pair,pair[::-1]):
                        result, _ = run(args.map, seed, teams, pack, False)
                        result["ablation"] = name
                        print(json.dumps(result, ensure_ascii=False), file=report, flush=True)


if __name__ == "__main__":
    main()
