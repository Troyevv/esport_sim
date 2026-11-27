"""Observe executed actions in mirrored detailed BO1. Writes one JSONL file per map and policy."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
from math import dist, hypot
from pathlib import Path
import random
from time import process_time

import psutil

from backend import career, cs2_maps, database, match, native_match_state
from tools.audit_individual_match import Pose, position


class Groups:
    def __init__(self, policy):
        self.policy = policy
        self.sides = {s: Counter() for s in ("T", "CT")}
        self.previous = {}
        self.examples = {}
        self.roster = {}
        self.round = 0
        self.shots = {}
        self.impacts = {}
        self.last_move = {}
        self.contacts = {}

    def frame(self, tick, rnd, phase, actors):
        if phase not in ("live", "planted"):
            return
        if self.round != rnd:
            self.previous.clear()
            self.round = rnd
            self.last_move.clear()
            self.contacts.clear()
        for values in actors:
            actor = Pose(*values)
            self.roster[rnd, actor.id] = actor.side
            before = self.previous.get(actor.id)
            self.previous[actor.id] = actor
            if not before:
                continue
            status = actor.status
            key = None
            moving = dist(position(before), position(actor)) > .1
            if self.policy == 4 and actor.shot == tick:
                self.shots[rnd, tick, actor.id] = position(actor)
            if self.policy == 4 and actor.hurt == tick:
                self.impacts[rnd, tick, actor.id] = position(actor)
            if moving:
                self.last_move[actor.id] = tick
            if self.policy == 4 and actor.visible and not before.visible and tick - self.last_move.get(actor.id, -100) <= 4:
                if any(s == actor.side and who != actor.id and tick-time <= 5
                       for who, (s, time) in self.contacts.items()):
                    self.sides[actor.side]["pairedSight"] += 1
                self.contacts[actor.id] = (actor.side, tick)
            if moving:
                if status == "Выходит под прикрытие напарника":
                    key = "released"
                elif status == "Идёт на запрос помощи":
                    key = "helpMove"
                elif status.startswith(("Проверяет направление ·", "Проверяет под сменную страховку")):
                    key = "scoutMove"
                elif status.startswith("Обходит к "):
                    key = "flankMove"
                elif self.policy == 4 and status == "Проверяет звук установки":
                    key = "interceptMove"
            else:
                if status.startswith(("Ждёт страховку", "Ждёт напарника", "Ждёт прикрытия", "Ждёт партнёра")):
                    key = "waiting"
                elif status.startswith(("Прикрывает выход напарника", "Страхует занятую зону",
                                        "Страхует группу", "Прикрывает направление по радио")):
                    key = "cover"
                elif status == "Принимает сектор напарника":
                    key = "handover"
            if key:
                counts = self.sides[actor.side]
                counts[key] += 1
                self.examples.setdefault(actor.side + "/" + key, [rnd, tick, actor.id, position(before), position(actor), status])

    def events(self, world):
        for rnd, events in enumerate([*world["archive"], world["events"]], 1):
            deaths = {}
            hits = {}
            for event in events:
                kind = event["kind"]
                if kind not in ("kill", "throw", "damage"):
                    continue
                who = event.get("player", event.get("owner"))
                side = self.roster.get((rnd, who), event.get("team"))
                if side not in self.sides:
                    continue
                c = self.sides[side]
                tick, target = event["tick"], event.get("target")
                if kind == "damage" and self.roster.get((rnd, target)) != side:
                    prior = hits.get((side, target))
                    if prior and prior[0] != who and tick-prior[1] <= 10:
                        c["jointHits"] += 1
                        origin = self.shots.get((rnd, tick, who))
                        other = self.shots.get((rnd, prior[1], prior[0]))
                        impact = self.impacts.get((rnd, tick, target))
                        if origin and other and impact:
                            x, y = origin[0]-impact[0], origin[1]-impact[1]
                            u, v = other[0]-impact[0], other[1]-impact[1]
                            if hypot(x, y)*hypot(u, v) and x*u+y*v <= .8660254*hypot(x, y)*hypot(u, v):
                                c["crossfireHits"] += 1
                    hits[side, target] = (who, tick)
                if kind == "kill" and event["enemy"]:
                    c["kills"] += 1
                    deaths[target] = tick
                    if event["trade"] is not None:
                        delay = tick - deaths[event["trade"]]
                        c["trades"] += 1
                        c["tradeTicks"] += delay
                        c["fastTrades"] += delay <= 10
                if kind == "throw" and (event.get("supported") or event.get("purpose") == "Поддержка по запросу напарника"):
                    c["supportThrows"] += 1
                    if self.policy == 4 and event.get("supported") != who:
                        c["partnerThrows"] += 1


def opening(world):
    """Inspect every local ticket and executed displacement through the first round."""
    owner = native_match_state.open_game(world)
    counts = {side: Counter() for side in ("T", "CT")}
    previous = {}
    examples = {}
    while owner.advance(1):
        w = json.loads(owner.snapshot())
        if w["phase"] == "result":
            break
        tick = w["tick"]
        moving = Counter()
        for a in w["agents"]:
            side = a["team"]
            c = counts[side]
            point = (a["x"], a["y"], a.get("z", 0))
            old = previous.get(a["id"], point)
            previous[a["id"]] = point
            if not a["hp"]:
                continue
            sent = a.get("sentFeedback") or {}
            for channel in ("contact", "stage"):
                request = sent.get(channel, {})
                if request.get("tick") == tick:
                    size = len(request.get("members", []))
                    c[("unfilled", "pair", "trio")[size]] += 1
            if dist(old, point) <= .1:
                continue
            if a["status"] == "Идёт на запрос помощи":
                cause = a["decision"]["respondingTo"]
                moving[side, cause["sender"]] += 1
            if a["status"] == "Выходит под прикрытие напарника":
                request = sent["stage"]
                for mate in request["members"]:
                    reply = a["peerCalls"].get(mate+"/support", {})
                    if reply.get("state") == "set" and reply["order"] == [a["id"], request["tick"]]:
                        c["confirmedMoves"] += 1
                        examples.setdefault("release", dict(tick=tick, player=a["id"], mate=mate,
                                            request=request["tick"], confirmation=reply["tick"],
                                            before=old, after=point))
                        break
                else:
                    raise AssertionError("Waypoint move without a delivered matching confirmation")
        for (side, sender), responders in moving.items():
            counts[side]["mobileRequestTicks"] += 1
            if responders > 1:
                raise AssertionError(f"{w['mapId']} tick {tick}: {responders} moving responders for {sender}")
    return dict(map=world["mapId"], seed=world["seed"], throughTick=tick, sides=counts, examples=examples)


def timings(world):
    """Price both executors from identical poses, loadouts, RNG and delivered evidence."""
    world["agentPolicy"] = 3
    source = native_match_state.open_game(world)
    source.advance(45)
    result = []
    for sample in range(8):
        snapshot = json.loads(source.snapshot())
        row = dict(tick=snapshot["tick"], rounds=snapshot["round"])
        order = (3, 4) if sample % 2 == 0 else (4, 3)
        for policy in (*order, *reversed(order)):
            owner = native_match_state.open_game(dict(snapshot, agentPolicy=policy))
            clock = process_time()
            advanced = owner.advance(96)
            if advanced != 96:
                raise AssertionError("Incomplete timing window")
            row.setdefault(str(policy), []).append((process_time()-clock)*1e6/96)
        result.append(row)
        source.advance(160)
    return result


def run(name, policy, out, first_round=False, timing=False):
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    out.mkdir(parents=True, exist_ok=True)
    prefix = "timing" if timing else "opening" if first_round else policy
    with (out / f"{prefix}-{name}.jsonl").open("w", encoding="utf-8") as stream:
        for sample in range(1 if policy == 3 else 2):
            seed = 55300 + sample * 10 + list(cs2_maps.NAMES).index(name)
            pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
            data = database.match_input(pack, pair)
            for start in (0, 1):
                w = match.initial(seed, data, pair, map_id=name, agent_policy=policy,
                                  first_attack=data["rosters"][pair[start]]["team"])
                if timing:
                    row = dict(map=name, seed=seed, start=start, windows=timings(w))
                    print(json.dumps(row), file=stream, flush=True)
                    if start:
                        return
                    continue
                if first_round:
                    print(json.dumps(opening(w), ensure_ascii=False), file=stream)
                    return
                owner = native_match_state.open_game(w)
                metrics = Groups(policy)
                while True:
                    frames = json.loads(owner.audit_individual_ticks(256))
                    for frame in frames:
                        metrics.frame(*frame)
                    if len(frames) < 256:
                        break
                checkpoint = owner.snapshot()
                final = json.loads(checkpoint)
                assert final["phase"] == "finished"
                metrics.events(final)
                row = dict(map=name, policy=policy, seed=seed, start=start, rosters=pair,
                           rounds=len(final["history"]), ticks=final["tick"], score=final["score"],
                           sha256=hashlib.sha256(checkpoint).hexdigest(), sides=metrics.sides,
                           examples=metrics.examples)
                if name in ("de_dust2", "de_inferno") and sample == start == 0:
                    replay = native_match_state.open_game(w)
                    clock = process_time()
                    while replay.advance(1024) == 1024:
                        pass
                    row["cpu"] = process_time() - clock
                    row["rssMiB"] = psutil.Process().memory_info().rss / 2**20
                    assert replay.snapshot() == checkpoint
                print(json.dumps(row, ensure_ascii=False), file=stream, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--policy", type=int, choices=(3, 4), required=True)
    parser.add_argument("--out", type=Path, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--timing", action="store_true", help="Compare 96-tick windows from common checkpoints")
    modes.add_argument("--opening", action="store_true", help="Audit one full first round under policy 4")
    args = parser.parse_args()
    if args.opening and args.policy != 4:
        parser.error("--opening requires --policy 4")
    run(args.map, args.policy, args.out, args.opening, args.timing)
