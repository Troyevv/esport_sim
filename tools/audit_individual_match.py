"""Manual paired BO1 audit. The C++ owner runs every tick; the observer measures the resulting poses."""
import argparse
from collections import Counter, namedtuple
import gzip
import json
from math import dist, remainder, tau
from pathlib import Path
import random
from time import process_time

from backend import career, cs2_maps, database, match, native_match_state
from backend.match_rules import WEAPONS

Pose = namedtuple("Pose", "id side intent x y z hp armor ammo reserve reload weapon visible hurt shot shelter step status heading blocked")


def position(p):
    return p.x, p.y, p.z


class TrajectoryAudit:
    def __init__(self):
        self.sides = {s: Counter() for s in ("T", "CT")}
        self.last = {}
        self.reloads = {}
        self.cover = {}
        self.transient = {}
        self.recent_reload = {}
        self.examples = {}
        self.round = 0
        self.phase = None

    def end_reload(self, key, completed):
        episode = self.reloads.pop(key)
        c = self.sides[episode["side"]]
        c["completedReload" if completed else "unfinishedReload"] += 1
        reason = "Voluntary" if episode["ammo"] else "Empty"
        c[("completed" if completed else "unfinished") + reason] += 1
        if episode["damage"]:
            c["hitDuringReload"] += 1
            c["reloadHpLost"] += episode["damage"]
            c["hitVoluntary" if episode["ammo"] else "hitEmpty"] += 1
        elif completed:
            c["safeComplete"] += 1
            c["safe" + reason] += 1

    def close_round(self):
        for key in list(self.reloads):
            self.end_reload(key, False)
        self.last.clear()
        self.cover.clear()
        self.transient.clear()
        self.recent_reload.clear()

    def record(self, frame):
        tick, rnd, phase, actors = frame
        if rnd != self.round:
            self.close_round()
            self.round = rnd
        active = phase in ("live", "planted")
        was_active = self.phase in ("live", "planted")
        self.phase = phase
        if not active and not was_active:
            return
        for values in actors:
            p = Pose(*values)
            key = p.id
            c = self.sides[p.side]
            old = self.last.get(key, p)
            self.last[key] = p
            d = dist(position(old), position(p))
            c["actorTicks"] += 1
            c["distance"] += d
            if p.intent == "assignment" and d > .01:
                c["movingOnAssignment"] += 1
            if p.intent != old.intent:
                c["switch"] += 1
                c[f"{old.intent}>{p.intent}"] += 1
                prior = self.transient.get(key)
                if prior:
                    start, before = prior
                    if tick-start <= 3 and before.intent == p.intent:
                        c["shortReversal"] += 1
                        if (before.visible == old.visible == p.visible and before.hp == old.hp == p.hp
                            and before.ammo == p.ammo and p.shot < start and p.step == before.step
                            and dist(position(before), position(old)) < .1
                            and abs(remainder(before.heading-old.heading, tau)) < .05):
                            c["idleReversal"] += 1
                self.transient[key] = tick, old

            if p.reload > tick and key not in self.reloads:
                # World resolves shots after choosing intents. No shot can spend rounds during this reload.
                self.reloads[key] = dict(side=p.side, ammo=p.ammo, due=p.reload, damage=0, weapon=p.weapon)
                c["reloads"] += 1
                c["voluntary" if p.ammo else "empty"] += 1
                if p.ammo:
                    c[f"partialMag_{p.ammo}"] += 1
                    c[f"weapon_{p.weapon}"] += 1
                    c["partialVisibleAfterMove"] += bool(p.visible)
                    c["partialRecentHit"] += tick - p.hurt <= 12
                c["startAmmo"] += p.ammo
                if p.ammo:
                    c["voluntaryAmmo"] += p.ammo
                c["visibleAtStart"] += bool(p.visible)
                c["recentHitAtStart"] += tick-p.hurt <= 12
                last = self.recent_reload.get(key)
                c["repeatWithoutShot"] += bool(last and last[1] == p.weapon and p.shot < last[0])
                self.recent_reload[key] = tick, p.weapon
                c[f"ammoBin_{min(4, int(4*p.ammo/WEAPONS[p.weapon].mag))}"] += 1
            if key in self.reloads:
                episode = self.reloads[key]
                # On the scheduled completion tick, servicing precedes combat resolution.
                if tick < episode["due"] and p.reload == episode["due"]:
                    episode["damage"] += max(0, old.hp-p.hp)
                if p.reload != episode["due"] or p.hp == 0:
                    self.end_reload(key, tick >= episode["due"] and p.weapon == episode["weapon"]
                                    and p.reserve < old.reserve)
            if p.intent == "cover" and p.shelter:
                if old.intent != "cover" or key not in self.cover:
                    c["coverStarts"] += 1
                    self.cover[key] = False
                remaining = dist(position(p), p.shelter)
                if remaining <= 2.5 and not self.cover[key]:
                    c["coverArrivals"] += 1
                    self.cover[key] = True
                c["coverTravel"] += d
                if d > .1:
                    self.examples.setdefault(f"{p.side}-cover", [rnd,tick,key,position(old),position(p),p.shelter])
            elif key in self.cover:
                # A player can lose sight a tick before reaching cover.
                if old.shelter and not self.cover[key] and dist(position(p), old.shelter) <= 2.5:
                    c["coverArrivals"] += 1
                del self.cover[key]


def run(name, policy, output):
    seed = 55100 + list(cs2_maps.NAMES).index(name)
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    data = database.match_input(pack, pair)
    rows = []
    for start in (0, 1):
        w = match.initial(seed, data, pair, map_id=name, first_attack=data["rosters"][pair[start]]["team"],
                          agent_policy=policy)
        owner = native_match_state.open_game(w)
        audit = TrajectoryAudit()
        while True:
            frames = json.loads(owner.audit_individual_ticks(256))
            for frame in frames:
                audit.record(frame)
            if len(frames) < 256:
                break
        audit.close_round()
        result = json.loads(owner.snapshot())
        assert result["phase"] == "finished"
        events = Counter(e["kind"] for log in [*result["archive"], result["events"]] for e in log)
        # Compare the entire checkpoint, including events and RNG, to an ordinary timed replay.
        replay = native_match_state.open_game(w)
        t = process_time()
        while replay.advance(1024) == 1024:
            pass
        cpu = process_time() - t
        assert replay.snapshot() == owner.snapshot()
        rows.append(dict(map=name, seed=seed, start=start, pair=pair, policy=policy,
                         ticks=result["tick"], rounds=len(result["history"]), score=result["score"],
                         events=events, sides=audit.sides, examples=audit.examples, cpu=cpu))
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    p.add_argument("--policy", type=int, choices=(1, 2), required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    run(args.map, args.policy, args.out)
