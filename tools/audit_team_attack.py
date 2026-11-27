"""Track the physical T trajectories and completed events of one mirrored pair of BO1."""
import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from math import dist
from pathlib import Path
import random
from time import process_time
from statistics import median

import psutil

from backend import career, cs2_maps, database, match, native_match_state


def timing(world, output):
    old, new = world["agentPolicy"] - 1, world["agentPolicy"]
    owner = native_match_state.open_game(dict(world, agentPolicy=old))
    rows = []
    for n, delta in enumerate((90, 320, 420, 610)):
        owner.advance(delta)
        state = json.loads(owner.snapshot())
        measurements = defaultdict(list)
        hashes = {}
        for policy in ((old, new, new, old) if n % 2 == 0 else (new, old, old, new)):
            replay = native_match_state.open_game(dict(state, agentPolicy=policy))
            before = process_time()
            assert replay.advance(180) == 180
            measurements[policy].append((process_time()-before)*1e6/180)
            digest = hashlib.sha256(replay.snapshot()).hexdigest()
            assert hashes.setdefault(policy, digest) == digest
        for policy, values in measurements.items():
            rows.append(dict(map=world["mapId"], tick=state["tick"], phase=state["phase"],
                             policy=policy, cpuUsTick=round(median(values), 3), sha256=hashes[policy]))
    (output / f"timing-{world['mapId']}.json").write_text(json.dumps(rows), encoding="utf-8")


def rotation_window(event, samples, actions, space, counts):
    """Classify the four-second window using the same two-player threshold as the original audit."""
    site = event.get("site") or event["text"][-1]
    tick = event["tick"] - event["tick"] % 5
    begin, end = samples.get(tick, {}), samples.get(tick+40, {})
    living = begin.keys() & end.keys()
    if len(living) < 2:
        return "tooFewOrRoundEnded"
    costs = space.site_costs[site]
    center = space.site_points[site]
    straight = nav = 0
    for who in living:
        p, q = begin[who], end[who]
        straight += dist(p, center) - dist(q, center) > 5
        a, b = space.locate(tuple(p)), space.locate(tuple(q))
        nav += a in costs and b in costs and costs[a] - costs[b] > 5 * cs2_maps.UNIT
    if straight >= 2:
        return "direct"
    if nav >= 2:
        return "navOnly"
    window = [intent for t in range(tick, tick+41, 5) for who, intent in actions.get(t, {}).items() if who in living]
    if any(intent in ("engage", "cover", "reload", "watch") for intent in window):
        return "contactOrRecovery"
    if "assist" in window:
        return "peerTask"
    return "noMeasuredAdvance"


def run(map_id, base, policy, output, timing_only=False):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = base + list(cs2_maps.NAMES).index(map_id)
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, pair)
    output.mkdir(parents=True, exist_ok=True)
    for start in (0, 1):
        world = match.initial(seed, domain, pair, map_id=map_id, agent_policy=policy,
                              first_attack=domain["rosters"][pair[start]]["team"])
        if timing_only:
            timing(world, output)
            return
        owner = native_match_state.open_game(world)
        # Compare restored and uninterrupted owners with and without the trajectory observer.
        owner.advance(90)
        checkpoint = owner.snapshot()
        clone = native_match_state.open_game(json.loads(checkpoint))
        before = process_time()
        clone.advance(90)
        tick_us = (process_time() - before) * 1e6 / 90
        owner.audit_group_ticks(90)
        assert clone.snapshot() == owner.snapshot()
        del clone
        owner = native_match_state.open_game(world)
        frames = []
        prior_positions = {}
        counts = Counter()
        samples = defaultdict(dict)
        defenders = defaultdict(dict)
        actions = defaultdict(dict)
        positions = {}
        examples = {}
        previous_round = None
        cpu = process_time()
        peak = 0
        process = psutil.Process()
        while True:
            for tick, rnd, phase, actors in frames:
                if rnd != previous_round:
                    positions.clear()
                    prior_positions.clear()
                    previous_round = rnd
                if phase not in ("live", "planted"):
                    continue
                attackers = [row for row in actors if row[1] == "T" and row[6] > 0]
                if tick % 5 == 0:
                    actions[rnd][tick] = {r[0]: r[2] for r in attackers}
                    defenders[rnd][tick] = {r[0]: r[3:6] for r in actors if r[1] == "CT" and r[6] > 0}
                    samples[rnd][tick] = {r[0]: r[3:6] for r in attackers}
                covers = []
                fake = [r for r in attackers if r[17] == "Давит на ложный вход"]
                if len(fake) >= 2 and any(dist(r[3:6], positions[r[0]]) > .1 for r in attackers
                                          if r not in fake and r[0] in positions):
                    counts["feintAndMainMoveTicks"] += 1
                    examples.setdefault("fakePair", [rnd, tick, [[r[0], r[3:6], positions.get(r[0])] for r in attackers]])
                    counts["movingFeintPairAndMain"] += all(r[0] in positions and dist(r[3:6], positions[r[0]]) > .1 for r in fake)
                for row in attackers:
                    who, pos, status = row[0], row[3:6], row[17]
                    old = positions.get(who, pos)
                    traveled = dist(old, pos)
                    positions[who] = pos
                    if traveled > .1 and status.startswith("Берёт контроль"):
                        counts["probeDistance"] += traveled
                    if traveled < .1 and status.startswith("Наблюдает ·"):
                        counts["sectorHoldTicks"] += 1
                    if status == "Ждёт второй вход" and traveled < .1:
                        counts["splitWaitTicks"] += 1
                    if status == "Прикрывает установку C4" and traveled < .1:
                        counts["plantCoverTicks"] += 1
                    if status in ("Перегруппировка у носителя C4", "Перестраивается по парам") and traveled > .1:
                        counts["regroupMoveTicks"] += 1
                    if phase == "planted" and status == "Прикрывает C4" and traveled < .1:
                        covers.append(pos)
                    lead = row[-1][0]
                    if lead and traveled > .1 and status == "Выходит под прикрытие напарника":
                        if any(r[0] == lead[1] and r[-1][1] and r[-1][1][0] == lead[0]
                               and r[17] == "Выходит вторым номером" and r[0] in prior_positions
                               and dist(prior_positions[r[0]], r[3:6]) > .1 for r in attackers):
                            counts["pairedMoveTicks"] += 1
                if len(covers) >= 2 and max(dist(p, q) for p in covers for q in covers) >= 8:
                    counts["spreadPostplantTicks"] += 1
                prior_positions = positions.copy()
            peak = max(peak, process.memory_info().rss)
            frames = json.loads(owner.audit_group_ticks(256))
            if not frames:
                break
        elapsed = process_time() - cpu
        snapshot = owner.snapshot()
        final = json.loads(snapshot)
        assert final["phase"] == "finished"
        space = cs2_maps.get(map_id)
        clubs = {a["id"]: a["club"] for a in final["agents"]}
        for rnd, events in enumerate([*final["archive"], final["events"]], 1):
            hits = {}
            throws = {}
            rotations = []
            for e in events:
                kind, tick = e["kind"], e["tick"]
                if kind == "plan" and e["team"] == "T":
                    initial_site = e["site"]
                if "choice" in e:
                    assert e["scores"][e["choice"]] == max(e["scores"].values())
                    counts["decisionsWithAck"] += e["acknowledged"] > 0
                if kind == "command" and e["team"] == "T":
                    counts["call/" + e["choice"]] += 1
                if kind == "throw":
                    throws[e["player"], e["land"]] = e["team"]
                    if e["team"] == "T":
                        counts[e["utility"]] += 1
                        counts["ticketFlashes"] += bool(e.get("groupTicket") and e["utility"] == "Свет")
                        if e.get("purpose") == "Ложный выход":
                            counts["feints"] += 1
                            false_site = "B" if initial_site == "A" else "A"
                            t = e["land"] - e["land"] % 5
                            begin = defenders[rnd].get(t, {})
                            end = defenders[rnd].get(t+40, {})
                            center = space.site_points[false_site]
                            shifts = [who for who in sorted(begin.keys() & end.keys())
                                      if dist(begin[who], center)-dist(end[who], center) > 8]
                            counts["feintWithCTMove"] += bool(shifts)
                            examples.setdefault("feint", [rnd, tick, e["player"], e["utility"], false_site,
                                                          e["trajectory"], [[i, begin[i], end[i]] for i in shifts]])
                elif kind == "flash" and throws.get((e.get("owner"), tick)) == "T":
                    counts["selfFull"] += e["owner"] == e["player"] and e["peak"] >= .78
                    counts["allyFull"] += (e["team"] == "T" and e["owner"] != e["player"] and e["peak"] >= .78)
                    counts["enemyFlashed"] += e["team"] == "CT"
                elif kind == "damage" and e["team"] == "T" and clubs[e["player"]] != clubs[e["target"]]:
                    last = hits.get(e["target"])
                    if last and e["player"] != last["player"] and tick-last["tick"] <= 10:
                        counts["jointHits"] += 1
                        counts["jointGuns"] += all(x["weapon"] not in ("HE", "Огонь") for x in (last, e))
                    hits[e["target"]] = e
                elif kind == "split":
                    counts["splitCalls"] += 1
                    poses = samples[rnd]
                    t = tick - tick % 5
                    begin, end = poses.get(t, {}), poses.get(t+10, {})
                    group = [e["player"], e["partner"]]
                    if all(who in begin and who in end and dist(begin[who], end[who]) > 2 for who in group):
                        counts["splitMoves"] += 1
                        examples.setdefault("split", [rnd, tick, e["site"], [
                            [who, begin[who], end[who]] for who in group]])
                elif kind in ("rotate", "execute", "regroup") and e["team"] == "T":
                    counts[kind] += 1
                    if kind == "rotate":
                        counts["rotation/" + rotation_window(e, samples[rnd], actions[rnd], space, counts)] += 1
                        if rotations:
                            counts["secondOrLaterRotate"] += 1
                            gap = tick - rotations[-1]
                            counts["minReturnTicks"] = min(counts.get("minReturnTicks", gap), gap)
                            examples.setdefault("return", [rnd, rotations[-1], tick, e["site"],
                                                           e["freshPressure"], e["freshBlock"], e["remaining"],
                                                           round(e["alternateTravel"], 1)])
                        if "freshPressure" in e:
                            assert e["freshPressure"] >= .8 or e["freshBlock"]
                        rotations.append(tick)
                        site = e.get("site") or e["text"][-1]
                        center = space.site_points[site]
                        poses = samples[rnd]
                        t = tick - tick % 5
                        begin, end = poses.get(t, {}), poses.get(t+40, {})
                        advances = [who for who in begin.keys() & end.keys()
                                    if dist(begin[who], center)-dist(end[who], center) > 5]
                        if len(advances) >= 2:
                            counts["followedRotate"] += 1
                            examples.setdefault("rotate", [rnd, tick, site, e.get("reason"), [
                                [who, begin[who], end[who]] for who in sorted(advances)]])
                elif kind in ("plant", "defuse"):
                    counts[kind] += 1
            counts["tWins"] += final["history"][rnd-1]["side"] == "T"
        row = dict(map=map_id, seed=seed, start=start, policy=policy, rosters=pair, score=final["score"],
                   rounds=len(final["history"]), ticks=final["tick"], cpuObserved=round(elapsed, 3),
                   cpuUsTick=round(tick_us, 2), rssMiB=round(peak/2**20, 1),
                   sha256=hashlib.sha256(snapshot).hexdigest(), counts=counts, examples=examples)
        (output / f"{policy}-{seed}-{start}.json").write_text(json.dumps(row, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--base", type=int, default=55300)
    parser.add_argument("--policy", type=int, choices=(7, 8, 9), default=9)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timing", action="store_true", help="Matched CPU windows instead of BO1")
    args = parser.parse_args()
    run(args.map, args.base, args.policy, args.out, args.timing)
