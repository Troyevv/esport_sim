"""Observe both sides of a detailed BO1 using the production tick owner."""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
from math import dist
from pathlib import Path
import random
from time import process_time

import psutil

from backend import career, cs2_maps, database, match, native_match_state
from tools.audit_team_attack import timing


def rounds(events, frames, site_points, clubs, counts, examples):
    hits = {}
    turns = 0
    screens = []
    killed = {e["target"] for e in events if e["kind"] == "kill"}
    savers = {i for frame in frames.values() for i, (side, _, status) in frame.items()
              if side == "CT" and status == "Сохраняет оружие"}
    counts["savers"] += len(savers)
    counts["saversAliveAtEnd"] += len(savers - killed)
    for e in events:
        kind, tick, side = e["kind"], e["tick"], e["team"]
        if kind == "plant" or kind == "defuse":
            counts[kind] += 1
        if kind == "throw":
            counts["throws" + side] += 1
            if side == "CT" and e["utility"] in ("Дым", "Огонь"):
                point = [e[k] for k in "xyz"]
                counts["ctScreens"] += 1
                counts["nearSimultaneousScreens"] += any(
                    old["utility"] == e["utility"] and old["player"] != e["player"] and
                    0 <= e["land"] - old["land"] <= 8 and dist(point, [old[k] for k in "xyz"]) < .6 * e["radius"]
                    for old in screens)
                screens.append(e)
            if side == "T" and e.get("purpose") == "Ложный выход":
                counts["fakeThrows"] += 1
        if kind == "damage" and clubs[e["player"]] != clubs[e["target"]]:
            key = (side, e["target"])
            last = hits.get(key)
            if last and e["player"] != last["player"] and tick - last["tick"] <= 10:
                counts["jointHits" + side] += 1
                if side == "CT" and all(hit["weapon"] not in ("HE", "Огонь") for hit in (e, last)):
                    counts["jointGunHitsCT"] += 1
                    sample = frames.get(tick - tick % 5, {})
                    ids = [last["player"], e["player"], e["target"]]
                    if all(i in sample for i in ids):
                        a, b, target = [sample[i][1] for i in ids]
                        product = sum((x-z)*(y-z) for x, y, z in zip(a, b, target))
                        if product < .78 * dist(a, target) * dist(b, target):
                            counts["crossfireHitsCT"] += 1
            hits[key] = e
        if kind == "kill" and e.get("trade") and e.get("enemy"):
            pose = frames.get(tick - tick % 5, {}).get(e["player"])
            if pose and pose[0] == "CT":
                counts["tradesCT"] += 1
        if kind == "defense_call":
            counts["call_" + e["decision"]] += 1
            if e["decision"] != "hold" and "scores" in e and not e["goals"]:
                counts["callsWithoutGoal"] += 1
            if "scores" in e:
                key = e["decision"] + ("/" + e["site"] if e["site"] else "")
                assert e["scores"][key] == max(e["scores"].values())
            if "slack" in e and e["decision"] == "save":
                counts["postplantSaveCalls"] += 1
        if kind == "throw" and side == "CT" and e.get("purpose"):
            counts["throw_" + e["purpose"]] += 1
        fake = side == "T" and e.get("choice") == "feint"
        turn = side == "T" and kind == "rotate"
        jobs = e.get("goals", {})
        if not (turn or fake or jobs):
            continue
        t = tick + (-tick % 5)
        begin, end = frames.get(t, {}), frames.get(t+30, {})
        alive = sorted(begin.keys() & end.keys())
        if jobs:
            counts["ordersWithGoals"] += 1
            moving = [i for i in alive if i in jobs and dist(begin[i][1], jobs[i])-dist(end[i][1], jobs[i]) > 4]
            counts["withGoals_" + e["decision"]] += 1
            counts["advance_" + e["decision"]] += bool(moving)
            counts["twoAdvancing_" + e["decision"]] += len(moving) >= 2
            if moving:
                counts["ordersWithAdvance"] += 1
                i = moving[0]
                examples.setdefault(e["decision"], [tick, i, begin[i][1], end[i][1], jobs[i]])
        if not (turn or fake):
            continue
        center = site_points[e["site"]]
        if turn:
            turns += 1
            counts["tTurns"] += 1
            counts["repeatTurns"] += turns > 1
            advancing = [i for i in alive if begin[i][0] == "T" and dist(begin[i][1], center)-dist(end[i][1], center) > 4]
            counts["tTurnsWithTwoMoving"] += len(advancing) >= 2
            if turns > 1:
                approaching = [i for i in alive if begin[i][0] == "CT" and
                               dist(begin[i][1], center)-dist(end[i][1], center) > 4]
                counts["repeatWithCTAdvance"] += bool(approaching)
                if approaching:
                    i = approaching[0]
                    examples.setdefault("repeatT", [tick, e["site"], i, begin[i][1], end[i][1]])
        else:
            # The event carries the current *real* T objective even after a prior switch.
            # Require a moving decoy participant during this window and a surviving CT initially in range.
            moving_fake = any(row[0] == "T" and row[2] == "Давит на ложный вход" and i in frames.get(k-5, {})
                              and dist(row[1], frames[k-5][i][1]) > 1
                              for k in range(t+5, t+31, 5) for i, row in frames.get(k, {}).items())
            home = [i for i in alive if begin[i][0] == "CT" and dist(begin[i][1], center) <= 55]
            if home and moving_fake:
                counts["executedFakeWithAnchor"] += 1
                held = [i for i in home if dist(end[i][1], center) <= 55]
                counts["anchorStillNearRealSite"] += bool(held)
                i = (held or home)[0]
                examples.setdefault("feintHeld" if held else "feintLeft",
                                    [tick, e["site"], i, begin[i][1], end[i][1]])


def run(map_id, base, policy, out, clock=False, traces=None):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = base + list(cs2_maps.NAMES).index(map_id)
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, pair)
    out.mkdir(parents=True, exist_ok=True)
    for start in (0, 1):
        world = match.initial(seed, domain, pair, map_id=map_id, agent_policy=policy,
                              first_attack=domain["rosters"][pair[start]]["team"])
        if clock:
            timing(world, out)
            return
        owner = native_match_state.open_game(world)
        cpu = process_time()
        frames = defaultdict(dict)
        samples = defaultdict(dict)
        if traces:
            traces.mkdir(parents=True, exist_ok=True)
        counts, examples = Counter(), {}
        proc = psutil.Process()
        peak = 0
        # Fork during live play and compare the observed and unobserved owners.
        owner.advance(90)
        saved = json.loads(owner.snapshot())
        clone = native_match_state.open_game(saved)
        clone.advance(90)
        owner.audit_group_ticks(90)
        assert owner.snapshot() == clone.snapshot()
        del clone
        owner = native_match_state.open_game(world)
        prior = {}
        last_round = 0
        while batch := json.loads(owner.audit_group_ticks(256)):
            peak = max(peak, proc.memory_info().rss)
            for tick, rnd, phase, rows in batch:
                if tick % 5 or phase not in ("live", "planted"):
                    continue
                if rnd != last_round:
                    prior = {}
                    last_round = rnd
                if traces:
                    samples[rnd][tick] = rows
                sample = {r[0]: (r[1], r[3:6], r[17]) for r in rows if r[6] > 0}
                frames[rnd][tick] = sample
                for i, (side, p, status) in sample.items():
                    if side != "CT" or i not in prior:
                        continue
                    moving = dist(prior[i][1], p) > 1
                    if status == "Сохраняет оружие" and moving:
                        counts["saveMoveSamples"] += 1
                    if status in ("Заходит на ретейк через свой проход", "Идёт на ретейк") and moving:
                        counts["retakeMoveSamples"] += 1
                    if status == "Прикрывает разминирование" and not moving:
                        counts["defuseCoverSamples"] += 1
                prior = sample
        raw = owner.snapshot()
        final = json.loads(raw)
        assert final["phase"] == "finished"
        clubs = {a["id"]: a["club"] for a in final["agents"]}
        for rnd, events in enumerate([*final["archive"], final["events"]], 1):
            if traces:
                path = traces / f"{policy}-{seed}-{start}-{rnd}.json.gz"
                with gzip.open(path, "wt", encoding="utf-8", compresslevel=1) as trace:
                    json.dump(dict(map=map_id, events=events, samples=samples.pop(rnd, {})), trace, ensure_ascii=False)
            rounds(events, frames[rnd], cs2_maps.get(map_id).site_points, clubs, counts, examples)
        row = dict(map=map_id, seed=seed, start=start, policy=policy, rosters=pair,
                   score=final["score"], rounds=len(final["history"]), ticks=final["tick"],
                   cpuObserved=round(process_time()-cpu, 3), rssMiB=round(peak/2**20, 1),
                   sha256=hashlib.sha256(raw).hexdigest(), **counts, examples=examples)
        (out / f"{policy}-{seed}-{start}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


def export(folder, target, clocks):
    if clocks:
        rows = [r for p in sorted(folder.glob("timing-*.json")) for r in json.loads(p.read_bytes())]
        fields = ["map", "tick", "phase", "policy", "cpuUsTick", "sha256"]
    else:
        rows = [json.loads(p.read_bytes()) for p in sorted(folder.glob("[0-9]*.json"))]
        fields = ["map", "seed", "start", "policy", "rosters", "score", "rounds", "ticks",
                  "cpuObserved", "rssMiB", "sha256"]
        fields += sorted({k for row in rows for k in row} - set(fields) - {"examples"})
        fields.append("examples")
    if not rows:
        raise ValueError("В каталоге нет результатов выбранного измерения")
    with target.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fields, restval="", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                             for k, v in row.items()})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES)
    parser.add_argument("--base", type=int, default=55300)
    parser.add_argument("--policy", type=int, choices=(9, 10, 11), default=11)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--traces", type=Path)
    parser.add_argument("--timing", action="store_true")
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args()
    if args.csv:
        export(args.out, args.csv, args.timing)
    elif args.map:
        run(args.map, args.base, args.policy, args.out, args.timing, args.traces)
    else:
        parser.error("Укажите карту или выходной CSV")
