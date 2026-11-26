"""Measure real recalls of living CT reserves before a plant, without changing the match."""

import argparse
import gzip
import json
from math import dist
from pathlib import Path
import random
from unittest.mock import patch

from backend import career, cs2_maps, database, match_ai
from tools.cs2_tactical_audit import run


def measure(pack, name, seed, teams):
    records = []
    captain = match_ai.captain

    def track(world, squad, space=None):
        if not squad or squad[0]["team"] != "CT" or world["phase"] != "live":
            return captain(world, squad, space)
        plan = world["plans"]["CT"]
        previous = {key: plan.get(key) for key in ("backup", "secondBackup")}
        result = captain(world, squad, space)
        members = {actor["id"]: actor for actor in squad}
        for key, old in previous.items():
            if not old or old["id"] not in members:
                continue
            new = plan.get(key)
            if new and new["id"] == old["id"] and new["site"] == old["site"]:
                continue
            distance = dist(cs2_maps.xyz(members[old["id"]]), old["hold"]) * cs2_maps.UNIT
            records.append(dict(
                round=world["round"], tick=world["tick"], site=old["site"],
                kind=key, far=round(distance), next=new and new["site"],
            ))
        return result

    with patch.object(match_ai, "captain", track):
        game, _ = run(name, seed, teams, pack, False)
    for change in records:
        round_result = game["rounds"][change["round"] - 1]
        change["plantedHere"] = round_result.get("site") == change["site"]
    return dict(seed=seed, teams=teams, rounds=len(game["rounds"]), events=records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(pack).values())
    results = []
    for seed in (41000, 59000):
        teams = random.Random(seed).sample(rosters, 2)
        results.extend(measure(pack, args.map, seed, pair) for pair in (teams, teams[::-1]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results), encoding="utf-8")
