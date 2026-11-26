"""Team staging on the installed NAV, after the captain learns the planted site."""

from math import dist

from . import match_performance as perf, world
from .cs2_maps import xyz
from .match_rules import RULES, UTILITY


def walk_length(start, path):
    length = 0
    for node in path:
        point = node[:3]
        length += dist(start, point)
        start = point
    return length


def approach(space, actor, center, via=None):
    start = xyz(actor)
    path = space.path(
        actor["navArea"], start, space.locate(via or center), via or center, frozenset()
    )
    if path is None:
        return None
    if via:
        tail = space.path(
            space.locate(via), via, space.locate(center), center, frozenset()
        )
        if tail is None:
            return None
        path = (*path, *tail)
    # The last approach outside the site, even if two named routes merge.
    entry = next((q[:3] for q in reversed(path) if dist(q[:3], center) >= 23), start)
    stage = via or entry
    length = walk_length(start, path)
    tail = space.path(
        space.locate(stage), stage, space.locate(center), center, frozenset()
    )
    if tail is None:
        return None
    return dict(
        stage=list(stage),
        entry=list(entry),
        length=length,
        tail=walk_length(stage, tail),
    )


def assemble(space, w, squad, leader, site):
    plan = w["plans"]["CT"]
    device = leader.get("seenDevice")
    center = (
        xyz(device) if device and device["site"] == site else space.site_points[site]
    )
    now = w["tick"]
    direct = {}
    for p in squad:
        if not p.get("saving"):
            route = approach(space, p, center)
            if route:
                direct[p["id"]] = route
    duties = {}
    captain = world.match_player(w, leader)["skills"]
    for p in sorted(
        (p for p in squad if p["id"] in direct), key=lambda p: direct[p["id"]]["length"]
    ):
        route = direct[p["id"]]
        player = world.match_player(w, p)
        skills = player["skills"]
        pace = 2 * perf.move_speed(player)
        use = RULES["kitDefuse"] if p["kit"] else RULES["defuse"]
        slack = w["deadline"] - now - use - route["length"] / pace
        used = [d["entry"] for d in duties.values()]
        # Split only when the measured final approach differs and the diversion
        # still leaves time to search, regroup and interact with the device.
        if (
            used
            and slack > 40
            and min(dist(route["entry"], q) for q in used) < 20
            and route["length"] > 35
        ):
            options = []
            labels = set(space.profile["guards"][site]) | {
                r[-1] for r in space.profile[site]
            }
            points = {space.centers[i] for label in labels for i in space.places[label]}
            for q in sorted(points, key=lambda q: dist(xyz(p), q) + dist(q, center)):
                if not 16 < dist(q, center) < 75:
                    continue
                alternative = approach(space, p, center, q)
                if (
                    not alternative
                    or min(dist(alternative["entry"], e) for e in used) < 20
                ):
                    continue
                extra = (alternative["length"] - route["length"]) / pace
                familiarity = player["mapKnowledge"].get(space.name[3:], 0)
                if extra <= min(
                    slack - 35,
                    (familiarity + skills["timing"] + captain["calling"]) / 5,
                ):
                    options.append(alternative)
            if options:
                route = min(options, key=lambda d: d["length"])
        eta = max(0, route["length"] - route["tail"]) / pace
        due = w["deadline"] - use - round(route["tail"] / pace) - 20
        if slack > 20 and dist(xyz(p), center) > 18 and now + eta < due:
            route.update(eta=round(now + eta), latest=due)
            duties[p["id"]] = route
    plan["retake"] = dict(site=site, duties=duties)
    for p in squad:
        duty = duties.get(p["id"])
        if not duty:
            continue
        # Plan around the nearest arriving partner. A distant fifth player
        # cannot hold the entire team outside until the timer runs down.
        others = [m for m in squad if m is not p and m["id"] in duties]
        if others:

            def pair_cost(m):
                coordination = w["domain"]["chemistry"].get(
                    world.pair_key(m["playerId"], p["playerId"]), 0
                )
                return abs(duties[m["id"]]["eta"] - duty["eta"]) - coordination / 12

            mate = min(others, key=pair_cost)
            duty["partner"] = mate["id"]
            sync = world.match_player(w, p)["skills"]["synchronization"]
            duty["release"] = min(
                duty["latest"],
                duties[mate["id"]]["eta"],
                duty["eta"] + 6 + (captain["calling"] + sync) // 9,
            )
    return plan["retake"]


def staging(w, actor, squad):
    plan = w["plan"].get("retake", {})
    duties = plan.get("duties", {})
    duty = duties.get(actor["id"])
    now = w["tick"]
    if not duty or duty.get("done"):
        return None
    if (
        now >= duty["latest"]
        or actor.get("blockedTicks", 0) >= 5
        or not any(m is not actor and not m.get("saving") for m in squad)
    ):
        duty["done"] = True
        return None
    if dist(xyz(actor), duty["stage"]) > 4:
        actor["status"] = "Заходит на ретейк через свой проход"
        return duty["stage"]
    mates = [
        duties[m["id"]]
        for m in squad
        if m is not actor and m["id"] in duties and not m.get("saving")
    ]
    duty["ready"] = True
    partner = duties.get(duty.get("partner"))
    if (
        partner in mates
        and not (partner.get("ready") or partner.get("done"))
        and now < duty.get("release", now)
    ):
        actor["status"] = "Ждёт напарника на ретейке"
        return xyz(actor)
    duty["done"] = True
    return None


def check_angle(space, w, actor, site, fallback):
    """Clear visible map cover while moving through the final approach."""
    duty = w["plan"].get("retake", {}).get("duties", {}).get(actor["id"])
    if (
        not duty
        or actor["blind"] > w["tick"]
        or dist(xyz(actor), space.site_points[site]) > 46
    ):
        return fallback
    state = duty.setdefault("sweep", {})
    if w["tick"] < state.get("next", 0):
        return state.get("watch", fallback)
    checked = state.setdefault("checked", [])
    points = [
        q
        for _, q in space.holds[site]
        if list(q) not in checked
        and 5 < dist(xyz(actor), q) < 45
        and space.hit(xyz(actor), q, 1, 64) is None
    ]
    if not points:
        state.update(watch=fallback, next=w["tick"] + 6)
        return fallback
    point = min(points, key=lambda q: dist(xyz(actor), q))
    checked.append(list(point))
    state.update(
        watch=list(point),
        next=w["tick"] + 3 + (100 - w["player"]["skills"]["positioning"]) // 15,
    )
    return point


def utility(space, w, actor, squad, site):
    now, plan = w["tick"], w["plan"]
    if (
        now < max(actor["throwAt"], actor.get("crossingReview", 0))
        or not actor["utility"]
    ):
        return None
    actor["crossingReview"] = now + 7
    center = space.site_points[site]
    origin = xyz(actor)
    teammates = [
        p
        for p in squad
        if p is not actor and not p.get("saving") and dist(xyz(p), center) < 55
    ]
    if not teammates or dist(origin, center) > 83:
        return None
    reports = [
        xyz(r)
        for r in actor["knowledge"].values()
        if now - r["tick"] < 35
        and r["source"] in ("Зрение", "Радио")
        and dist(xyz(r), center) < 55
    ]
    cover = [q for _, q in space.holds[site] if 9 < dist(q, center) < 45]
    calls = plan.setdefault("crossingCalls", [])
    calls[:] = [c for c in calls if c["end"] > now]
    skills = w["player"]["skills"]
    for item in sorted(
        set(actor["utility"]), key=lambda g: (-skills[perf.GRENADE_SKILL[g]], g)
    ):
        if item not in ("Дым", "Свет", "Огонь", "HE"):
            continue
        if item == "HE" and not reports:
            continue
        points = sorted(cover, key=lambda q: min(dist(q, xyz(m)) for m in teammates))
        for q in [*reports, *points]:
            radius = UTILITY[item][0]
            if not 12 < dist(q, origin) < 75 or any(
                dist(q, c["point"]) < radius for c in calls
            ):
                continue
            if item in ("Огонь", "Дым") and dist(q, center) < radius + 6:
                continue
            if item == "Свет" and not any(
                dist(q, xyz(m)) < radius + 30 for m in teammates
            ):
                continue
            if any(
                dist(q, xyz(m)) < radius + 3 and space.hit(q, xyz(m), 1, 5, 64) is None
                for m in squad
            ):
                continue
            landing = space.grenade(origin, q, max(3, round(dist(origin, q) / 7)))
            if dist(landing[:3], q) > 6:
                continue
            if item in ("Дым", "Огонь") and any(
                dist(q, d["entry"]) < radius
                for d in plan.get("retake", {}).get("duties", {}).values()
            ):
                continue
            calls.append(
                dict(
                    item=item,
                    point=list(q),
                    end=now + len(landing[3]) + UTILITY[item][1],
                )
            )
            purpose = {
                "Свет": "Поддерживает вход",
                "Дым": "Изолирует позицию",
                "Огонь": "Проверяет укрытие",
                "HE": "Проверяет контакт",
            }[item]
            return "throw", dict(zip(("x", "y", "z"), q), utility=item, purpose=purpose)
    return None
