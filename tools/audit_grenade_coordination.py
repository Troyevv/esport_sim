"""Mirror both starting sides on one map and observe actions around actual flash detonations."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from math import dist
from pathlib import Path
import random
from time import process_time

from backend import career, cs2_maps, database, match, native_match_state
from tools.audit_grenades import measure
from tools.audit_small_groups import GroupTasks


def review(world, history, groups):
    counts = measure(world)
    clubs = {a["id"]: a["club"] for a in world["agents"]}
    for rnd, events in enumerate([*world["archive"], world["events"]], 1):
        casts = [e for e in events if e["kind"] == "throw" and e["utility"] == "Свет"]
        by_source = defaultdict(list)
        hits = {}
        recent = {}
        for e in events:
            tick = e["tick"]
            if e["kind"] == "flash":
                by_source[tick, e.get("owner")].append(e)
                owner = e.get("owner")
                if owner:
                    relation = "enemy" if clubs[e["player"]] != clubs[owner] else "self" if owner == e["player"] else "ally"
                    counts[relation + "PeakSum"] += e["peak"]
                    counts[relation + "DurationSum"] += e["duration"]
            if e["kind"] != "damage" or clubs[e["player"]] == clubs[e["target"]]:
                continue
            prior = hits.get((e["team"], e["target"]))
            if prior and prior["player"] != e["player"] and tick-prior["tick"] <= 10:
                weapons = {prior["weapon"], e["weapon"]}
                counts["jointFire" if "Огонь" in weapons else "jointHE" if "HE" in weapons else "jointGuns"] += 1
            hits[e["team"], e["target"]] = e
        for e in casts:
            land, who = e["land"], e["player"]
            purpose = e.get("purpose") or ("Стартовый план" if e.get("openingZone") else "Без метки")
            counts["reason/" + purpose] += 1
            if not any(x["team"] != e["team"] for x in by_source[land,who]):
                counts["empty/" + purpose] += 1
            pos = (e["x"],e["y"],e.get("z",0))
            if any(0 <= land-t < 20 and dist(pos, p) < 18 for t,p in recent.get(e["team"], [])):
                counts["nearRepeat"] += 1
            recent.setdefault(e["team"], []).append((land,pos))
            mate = e.get("supported") or (e.get("groupTicket") or [None])[0]
            if not mate or mate == who:
                continue
            # The old event schema identified only opening and ticketed partners.
            original = e.get("openingZone") or e.get("groupTicket")
            if original:
                counts["openingOrTicket"] += 1
                counts["openingOrTicketHit"] += any(
                    h["kind"] == "damage" and h["player"] == mate and clubs[h["target"]] != clubs[mate]
                    and land <= h["tick"] < land+20 for h in events)
            samples = history[rnd,mate]
            window = [samples[t] for t in range(land,land+20) if t in samples]
            if not window:
                counts["noLiveWindow"] += 1
                continue
            counts["mateTurned"] += any(samples.get(t, (None,))[0] == "Отворачивается от флешки"
                                        for t in range(e["tick"],land))
            counts["mateMoved"] += any(v[1] for v in window)
            counts["mateSaw"] += any(v[2] for v in window)
            counts["mateShot"] += any(v[3] for v in window)
            counts["mateExposed"] += any(x["player"] == mate for x in by_source[land,who])
    groups.events(world)
    for c in groups.sides.values():
        for key, value in c.items():
            counts["group/" + key] += value
    return counts


def timings(world):
    """Repeat both policies from the same poses, equipment, radio inbox and random streams."""
    source = native_match_state.open_game(dict(world, agentPolicy=6))
    result = []
    for i, delta in enumerate((60, 320, 460, 790)):
        source.advance(delta)
        checkpoint = json.loads(source.snapshot())
        hashes = {}
        for policy in ((6, 7, 7, 6) if i % 2 == 0 else (7, 6, 6, 7)):
            owner = native_match_state.open_game(dict(checkpoint, agentPolicy=policy))
            before = process_time()
            assert owner.advance(180) == 180
            micros = (process_time() - before) * 1e6 / 180
            digest = hashlib.sha256(owner.snapshot()).hexdigest()
            assert hashes.setdefault(policy, digest) == digest
            result.append(dict(tick=checkpoint["tick"], policy=policy, cpuUsPerTick=micros, sha256=digest))
    return result


def run(map_id, policy, out, timing=False):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = 55300 + list(cs2_maps.NAMES).index(map_id)
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    data = database.match_input(pack, pair)
    out.mkdir(parents=True, exist_ok=True)
    for start in (0, 1):
        world = match.initial(seed, data, pair, map_id=map_id, agent_policy=policy,
                              first_attack=data["rosters"][pair[start]]["team"])
        if timing:
            (out / f"timing-{map_id}.json").write_text(json.dumps(timings(world)), encoding="utf-8")
            return
        owner = native_match_state.open_game(world)
        history = defaultdict(dict)
        groups = GroupTasks(policy)
        cpu = process_time()
        while True:
            frames = json.loads(owner.audit_group_ticks(256))
            for frame in frames:
                tick, rnd, phase, actors = frame
                if phase in ("live","planted"):
                    for row in actors:
                        old = groups.previous.get(row[0]) if groups.round == rnd else None
                        moved = old is not None and dist((old.x,old.y,old.z),row[3:6]) > .1
                        history[rnd,row[0]][tick] = (row[17],moved,row[12],row[14]==tick)
                groups.frame(*frame)
            if len(frames) < 256:
                break
        seconds = process_time()-cpu
        snapshot = owner.snapshot()
        final = json.loads(snapshot)
        assert final["phase"] == "finished"
        row = dict(map=map_id,seed=seed,start=start,policy=policy,rounds=len(final["history"]),
                   ticks=final["tick"],score=final["score"],cpuWithObserver=seconds,
                   sha256=hashlib.sha256(snapshot).hexdigest(),counts=review(final,history,groups))
        (out / f"{policy}-{map_id}-{start}.json").write_text(json.dumps(row,ensure_ascii=False),encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--policy", type=int, choices=(6,7), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timing", action="store_true", help="Four paired 180-tick windows on the first start")
    args = parser.parse_args()
    run(args.map, args.policy, args.out, args.timing)
