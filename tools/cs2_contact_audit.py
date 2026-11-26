"""Count decisions during real-map visual contact without altering BO1 inputs."""

import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path
import random
from unittest.mock import patch

from backend import career, cs2_maps, database, match_ai
from tools.cs2_tactical_audit import run


def record(pack, name, seed, teams):
    counters = defaultdict(Counter)
    act = match_ai.act

    def observe(world, actor, allies, *args):
        visible = bool(actor["visible"])
        intent = act(world, actor, allies, *args)
        counts = counters[actor["team"], world["phase"]]
        if visible:
            counts["contactTicks"] += 1
            counts[intent[0]] += 1
        elif intent[0] == "shoot":
            counts["unseenShots"] += 1
        return intent

    with patch.object(match_ai, "act", observe):
        game, _ = run(name, seed, teams, pack, False)
    return dict(
        map=name,
        seed=seed,
        teams=teams,
        rounds=len(game["rounds"]),
        decisions={
            side: {phase: counters[side, phase] for phase in ("live", "planted")}
            for side in ("T", "CT")
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--seeds", nargs="+", type=int, default=[41000, 59000])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(pack).values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as stream:
        for seed in args.seeds:
            teams = random.Random(seed).sample(rosters, 2)
            for order in (teams, teams[::-1]):
                print(
                    json.dumps(record(pack, args.map, seed, order), ensure_ascii=False),
                    file=stream,
                    flush=True,
                )


if __name__ == "__main__":
    main()
