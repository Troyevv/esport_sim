"""Manual physical-map probe, from two real sightlines through radio to executed orders."""

import argparse
from collections import Counter
import gzip
import json
from math import atan2, cos, dist, pi, sin
from random import Random

from backend import cs2_maps, database, match, native_match_state


def xyz(a):
    return tuple(a[k] for k in "xyz")


def place(a, point, area):
    a.update(zip("xyz", point))
    a.update(navArea=area, visible=[], knowledge={}, path=[], utility=[], waypoint=0)


def ingress_pair(space, site):
    """Two walkable observations straddling a real plant boundary, seen by the same witness."""
    center = space.site_points[site]
    for _, origin in sorted(
        space.centers.items(), key=lambda item: dist(item[1], center)
    ):
        if space.site_at(origin) != site:
            continue
        for heading in range(16):
            dx, dy = cos(heading * pi / 8), sin(heading * pi / 8)
            for step in range(1, 35):
                start = (origin[0] + step * dx, origin[1] + step * dy, origin[2])
                if space.site_at(start) == site:
                    continue
                end = (start[0] - 1.7 * dx, start[1] - 1.7 * dy, start[2])
                if (
                    space.site_at(end) == site
                    and space._locate(start)
                    and space._locate(end)
                    and not space.hit(start, end, 1, 64, 64)
                ):
                    witnesses = (
                        area
                        for area, p in space.centers.items()
                        if 8 < dist(p, end) < 24
                        and abs(p[2] - end[2]) < 4
                        and not space.hit(p, start, 1, 64, 64)
                        and not space.hit(p, end, 1, 64, 64)
                    )
                    witness = min(
                        witnesses,
                        key=lambda area: dist(space.centers[area], origin),
                        default=None,
                    )
                    if witness is not None:
                        return start, end, witness
                break
    raise AssertionError("No traversable site boundary in the witness sightline")


def scenario(
    name, seed, policy, domain=None, rosters=None, wounded=False, moving=False
):
    space = cs2_maps.get(name)
    w = (
        match.initial(seed, domain, rosters, map_id=name, agent_policy=policy)
        if domain
        else match.initial(seed, map_id=name, agent_policy=policy)
    )
    match.advance(w, 45)
    w["tick"] += 40
    w["plans"]["CT"]["review"] = w["tick"] + 15
    # Select authentic NAV centers on each site and an unobstructed witness position.
    centers = space.centers
    site = min(
        (a for a, q in centers.items() if space.site_at(q) == "A"),
        key=lambda a: dist(centers[a], space.site_points["A"]),
    )
    q = centers[site]
    witness = min(
        (
            a
            for a, p in centers.items()
            if 6 < dist(q, p) < 35 and abs(p[2] - q[2]) < 5 and not space.hit(q, p, 1, 64, 64)
        ),
        key=lambda a: abs(dist(q, centers[a]) - 14),
    )
    if moving:
        approach, q, witness = ingress_pair(space, "A")
        site = space._locate(q)
    b = min(centers, key=lambda a: dist(centers[a], space.site_points["B"]))
    ct = [a for a in w["agents"] if a["team"] == "CT"]
    attackers = [a for a in w["agents"] if a["team"] == "T"]
    slots = w["plans"]["CT"]["orders"]["slots"]
    witnesses = sorted(
        (a for a in ct if not a["appointed"]), key=lambda a: slots[a["slot"]]["site"] != "A"
    )[:2]
    for a in ct:
        area = witness if a in witnesses else b
        place(a, centers[area], area)
        a["heading"] = atan2(q[1] - a["y"], q[0] - a["x"]) if a in witnesses else 0
    if wounded:
        for a in witnesses:
            a["hp"] = 19
    for a in attackers:
        place(a, approach if moving else q, space._locate(approach) if moving else site)
    owner = native_match_state.open_game(w)
    owner.observe()
    seen = json.loads(owner.snapshot())
    if moving:
        # Between consecutive sensory frames the group crosses the actual objective boundary.
        seen["tick"] += 1
        for a in seen["agents"]:
            if a["team"] == "T":
                a.update(zip("xyz", q))
                a["navArea"] = site
        owner = native_match_state.open_game(seen)
        owner.observe()
        seen = json.loads(owner.snapshot())
        assert any(
            m.get("sight", {}).get("carryingC4")
            and m["sight"].get("direction")
            and m["sight"]["tick"] == seen["tick"]
            for m in seen["messages"]
        ), "carrier movement was not relayed"
    packets = [m for m in seen["messages"] if m["team"] == "CT" and "sight" in m]
    ids = {m["sight"]["id"] for m in packets}
    assert len(ids) == 5 and len({m["sender"] for m in packets}) >= 2
    assert any(m["sight"].get("carryingC4") for m in packets)
    arrival = max(m["due"] for m in packets)
    captain = next(a for a in ct if a["appointed"])
    assert not captain["knowledge"]
    owner = native_match_state.open_game(dict(seen, tick=arrival))
    owner.deliver_radio()
    received = json.loads(owner.snapshot())
    reports = next(a["knowledge"] for a in received["agents"] if a["id"] == captain["id"])
    assert ids <= reports.keys()
    if moving:
        assert any(
            r.get("carryingC4") and r.get("direction") and r.get("entrySite") == "A"
            for r in reports.values()
        )
    review = max(arrival, received["plans"]["CT"]["review"])
    owner = native_match_state.open_game(dict(received, tick=review))
    owner.review_captain("CT")
    called = json.loads(owner.snapshot())
    plan = called["plans"]["CT"]
    distant = [a for a in ct if a not in witnesses]
    start = {a["id"]: xyz(a) for a in distant}
    # Follow actual physical execution and its radio acknowledgement.
    first_move, ack, assigned, conflicts = {}, {}, {}, 0
    acted, unassigned_idle, samples = {}, 0, {}
    for _ in range(26):
        owner.advance(1)
        after = json.loads(owner.snapshot())
        for a in after["agents"]:
            who = a["id"]
            if who not in start:
                continue
            if dist(xyz(a), start[who]) > 0.25:
                first_move.setdefault(who, after["tick"] - arrival)
            p = after["plans"]["CT"]
            duties = [*p.get("commitments", {}).values(), p.get("backup"), p.get("secondBackup")]
            chosen = [d for d in duties if d and d["id"] == who]
            conflicts += int(len(chosen) > 1)
            if chosen:
                assigned[who] = chosen[0]["site"]
                d = chosen[0]
                if a["hp"] and dist(xyz(a), start[who]) > 0.25 and d["site"] == "A":
                    acted.setdefault(
                        who,
                        dict(
                            delay=after["tick"] - arrival,
                            status=a["status"],
                            intent=a.get("decision", {}).get("intent"),
                            destination=a.get("dest"),
                        ),
                    )
                if chosen[0].get("acknowledged"):
                    ack[who] = chosen[0]["acknowledged"]
            if a["hp"] and xyz(a) == start[who] and not a.get("status") and not chosen:
                unassigned_idle += 1
            samples[who] = dict(
                status=a["status"], ownIntel=list(a["knowledge"]), task=a.get("decision", {}).get("task")
            )
    return dict(
        map=name,
        policy=policy,
        wounded=wounded,
        moving=moving,
        acted=acted,
        final=samples,
        idleWithoutTask=unassigned_idle,
        scores=plan.get("defenseScores"),
        witnesses=[a["id"] for a in witnesses],
        packets=len(packets),
        unique=len(ids),
        arrival=arrival - seen["tick"],
        review=review - arrival,
        call=plan["defenseCall"]["kind"],
        site=plan["defenseCall"]["site"],
        assigned=assigned,
        firstMove=first_move,
        ack=ack,
        conflictingDuties=conflicts,
        observations={
            key: [
                r["source"],
                r["tick"],
                r.get("carryingC4", False),
                r.get("groupSize"),
            ]
            for key, r in reports.items()
        },
    )


def attack_scenario(name, seed, domain, rosters):
    w = match.initial(seed, domain, rosters, map_id=name)
    match.advance(w, 45)
    w["tick"] += 55
    plan = w["plans"]["T"]
    site = plan["site"]
    space = cs2_maps.get(name)
    center = space.site_points[site]
    squad = [a for a in w["agents"] if a["team"] == "T"]
    captain = next(a for a in squad if a["appointed"])
    sender = next(a for a in squad if a != captain)
    # Two independent inputs: a delivered refusal on the called route and
    # identified defenders from a teammate's visual report.
    due = w["tick"] + 4
    w["messages"].append(dict(sender=sender["id"], team="T", blockedSite=site, due=due))
    for enemy in [a for a in w["agents"] if a["team"] == "CT"][:3]:
        sight = dict(
            id=enemy["id"],
            tick=w["tick"],
            source="Зрение",
            confidence=0.9,
            groupSize=3,
            x=center[0],
            y=center[1],
            z=center[2],
        )
        w["messages"].append(dict(team="T", sender=sender["id"], sight=sight, due=due))

    def evaluate(state):
        owner = native_match_state.open_game(state)
        owner.deliver_radio()
        result = json.loads(owner.snapshot())
        result["tick"] = max(result["tick"], result["plans"]["T"]["review"])
        owner = native_match_state.open_game(result)
        owner.review_captain("T")
        return owner, json.loads(owner.snapshot())

    _, control = evaluate(dict(w, tick=due - 1))
    owner, called = evaluate(dict(w, tick=due))
    order = called["plans"]["T"]
    owner.advance(8)
    after = json.loads(owner.snapshot())
    moved = {
        a["id"]: dict(status=a["status"], distance=round(dist(xyz(a), xyz(old)), 2))
        for a, old in zip(after["agents"], w["agents"])
        if a["team"] == "T"
    }
    return dict(
        map=name,
        site=site,
        control=control["plans"]["T"].get("assessment"),
        received=order.get("assessment"),
        destination=order["site"],
        delay=called["tick"] - due,
        moved=moved,
    )


def field_sample(name, seed, domain, rosters):
    """Measure stationary actor-ticks by actual decision and status on an unmodified opening."""
    w = match.initial(seed, domain, rosters, map_id=name)
    owner = native_match_state.open_game(w)
    last, stationary, blocked, unresolved, totals = {}, Counter(), Counter(), Counter(), Counter()
    for _, rnd, phase, actors in json.loads(owner.audit_individual_ticks(500)):
        if phase not in ("live", "planted"):
            last.clear()
            continue
        for actor in actors:
            who, side, intent, x, y, z, hp = actor[:7]
            visible, status, obstruction = actor[12], actor[17], actor[19]
            key, point = (rnd, who), (x, y, z)
            if hp and last.get(key) == point:
                stationary[side, intent, status] += 1
                if intent == "assignment" and obstruction and not visible:
                    blocked[side, status] += 1
                if not intent or status in ("", "Подготовка"):
                    unresolved[side] += 1
            last[key] = point
            totals[side] += 1
    return dict(map=name, samples=totals, unresolved=unresolved,
                stationary=[[*key,count] for key,count in stationary.items()],
                blocked=[[*key,count] for key,count in blocked.items()])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=int, default=12)
    parser.add_argument("--wounded", action="store_true")
    parser.add_argument("--attack", action="store_true")
    parser.add_argument("--moving", action="store_true")
    parser.add_argument("--field", action="store_true")
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    for i, name in enumerate(cs2_maps.installed()):
        seed = 56560 + i
        rosters = Random(seed).sample(sorted(pack["rosters"]), 2)
        domain = database.match_input(pack, rosters)
        result = (
            field_sample(name, seed, domain, rosters)
            if args.field
            else (
                attack_scenario(name, seed, domain, rosters)
                if args.attack
                else scenario(
                    name,
                    seed,
                    args.policy,
                    domain,
                    rosters,
                    wounded=args.wounded,
                    moving=args.moving,
                )
            )
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
