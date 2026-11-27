"""Bounded R5.5.2 BO1 audit. One map, two mirrored starts per seed."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import random
from time import process_time

import psutil

from backend import career, cs2_maps, database, match, native_match_state
from tools.audit_individual_match import Pose


def inspect_replay(world, reference):
    owner = native_match_state.open_game(world)
    by_side = {side: Counter() for side in ("T", "CT")}
    positions = {}
    while True:
        frames = json.loads(owner.audit_individual_ticks(256))
        for _, rnd, _, actors in frames:
            for values in actors:
                p = Pose(*values)
                before = positions.get((rnd, p.id))
                if p.intent == "assist":
                    counts = by_side[p.side]
                    counts["ticks"] += 1
                    counts["episodes"] += before is None or before.intent != "assist"
                    counts["movingTicks"] += bool(before and (p.x, p.y, p.z) != (before.x, before.y, before.z))
                positions[rnd, p.id] = p
        if len(frames) < 256:
            break
    if owner.snapshot() != reference:
        raise AssertionError("Replay diverged")
    return by_side


def run(name, baseline, output):
    process = psutil.Process()
    rows = []
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    for sample in range(1 if baseline else 2):
        seed = 55200 + sample * 10 + list(cs2_maps.NAMES).index(name)
        pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
        data = database.match_input(pack, pair)
        for start in (0, 1):
            policy = 2 if baseline else 3
            world = match.initial(seed, data, pair, map_id=name, agent_policy=policy,
                                  first_attack=data["rosters"][pair[start]]["team"])
            owner = native_match_state.open_game(world)
            start_cpu = process_time()
            while owner.advance(1024) == 1024:
                pass
            cpu = process_time() - start_cpu
            rss = process.memory_info().rss
            checkpoint = owner.snapshot()
            final = json.loads(checkpoint)
            assert final["phase"] == "finished"
            row = dict(map=name, seed=seed, start=start, rosters=pair, policy=policy, cpu=cpu,
                       rss=rss, rounds=len(final["history"]), ticks=final["tick"], score=final["score"],
                       sha256=hashlib.sha256(checkpoint).hexdigest())
            if not baseline and sample == 0 and start == 0:
                row["assist"] = inspect_replay(world, checkpoint)
            rows.append(row)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{policy}-{name}.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.map, args.baseline, args.out)
