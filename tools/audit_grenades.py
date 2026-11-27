"""Paired detailed BO1 audit. Each invocation plays both starts on one installed map."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
import random
from time import process_time

import psutil
from backend import career, cs2_maps, database, match, native_match_state


def measure(world):
    counts = Counter()
    club = {a["id"]: a["club"] for a in world["agents"]}
    for events in [*world["archive"], world["events"]]:
        detonations = defaultdict(list)
        hits = {}
        intervals = defaultdict(list)
        dead = {}
        group_casts = []
        successful = set()
        end_round = 0
        blinded = {}
        for e in events:
            kind, tick = e["kind"], e["tick"]
            end_round = max(end_round, tick)
            if kind == "throw":
                counts[e["utility"]] += 1
                if e["utility"] == "Свет":
                    detonations[e["land"]].append(e)
                    mate = e.get("supported") or (e.get("groupTicket") or [None])[0]
                    if mate and mate != e["player"]:
                        group_casts.append((e["id"], mate, e["land"]))
                        counts["pairedFlashes"] += 1
            elif kind == "flash":
                counts["exposures"] += 1
                candidates = detonations[tick]
                if "owner" in e:
                    candidates = [c for c in candidates if c["player"] == e["owner"]]
                if len(candidates) == 1:
                    cast = candidates[0]
                    relation = ("self" if e["player"] == cast["player"] else
                                "ally" if e["team"] == cast["team"] else "enemy")
                    counts[relation] += 1
                    counts[relation + ("Full" if e.get("peak", 1) >= .78 else "Partial")] += 1
                    if relation == "enemy":
                        intervals[e["player"]].append((tick, tick+e["duration"]))
                        blinded[e["player"]] = (tick + e["duration"], cast["player"])
                else:
                    counts["ambiguous"] += 1
            elif kind == "damage":
                if e["weapon"] in ("HE", "Огонь"):
                    counts[e["weapon"] + " HP"] += e["amount"]
                if club[e["player"]] == club[e["target"]]:
                    continue
                for ident, mate, land in group_casts:
                    if e["player"] == mate and 0 <= tick-land < 20:
                        successful.add(ident)
                previous = hits.get((e["team"], e["target"]))
                if previous and previous[0] != e["player"] and tick - previous[1] <= 10:
                    counts["jointHits"] += 1
                hits[e["team"], e["target"]] = (e["player"], tick)
            elif kind == "kill":
                dead[e["target"]] = tick
                if not e["enemy"]:
                    continue
                end, owner = blinded.get(e["target"], (-1, None))
                counts["killsDuringExposureByTeammate"] += tick < end and e["player"] != owner
                counts["flashAssists"] += bool(e.get("flashAssist"))
        counts["pairedFollowups"] += len(successful)
        for target, ranges in intervals.items():
            end = -1
            for start, stop in sorted(ranges):
                stop = min(stop, dead.get(target, end_round+1), end_round+1)
                counts["attributedEnemyTicks"] += max(0, stop-max(start,end))
                end = max(end,stop)
    if world.get("agentPolicy", 0) >= 6:
        for metric in match.UTILITY_STATS:
            counts["stat_" + metric] = sum(row.get(metric, 0) for row in world["stats"].values())
    return counts


def run(name, policy, folder):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = 55300 + list(cs2_maps.NAMES).index(name)
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    data = database.match_input(pack, pair)
    folder.mkdir(parents=True, exist_ok=True)
    for start in (0, 1):
        path = folder / f"{policy}-{name}-{start}.json"
        if path.exists():
            continue
        w = match.initial(seed, data, pair, map_id=name, agent_policy=policy,
                          first_attack=data["rosters"][pair[start]]["team"])
        owner = native_match_state.open_game(w)
        clock = process_time()
        verified_ticks = 0
        if policy == 6:
            owner.advance(256)
            before = owner.snapshot()
            cpu_before_restore = process_time() - clock
            restored = native_match_state.open_game(json.loads(before))
            restored.advance(17)
            restored.advance(111)
            clock = process_time() - cpu_before_restore
            owner.advance(128)
            assert restored.snapshot() == owner.snapshot()
            verified_ticks = 128
        while owner.advance(1024) == 1024:
            pass
        cpu = process_time() - clock
        rss = psutil.Process().memory_info().rss
        snapshot = owner.snapshot()
        final = json.loads(snapshot)
        assert final["phase"] == "finished"
        row = dict(map=name, policy=policy, seed=seed, start=start, rosters=pair,
                   rounds=len(final["history"]), ticks=final["tick"], score=final["score"],
                   cpu=cpu, rss=rss, verifiedTicks=verified_ticks, sha256=hashlib.sha256(snapshot).hexdigest(),
                   counts=measure(final))
        path.write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--policy", type=int, choices=(5, 6), required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.map, args.policy, args.out)
