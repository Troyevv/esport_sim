"""Sector ownership for the shared real-map BO1. Inputs are own assignments and observations."""

from math import dist, hypot

from .cs2_maps import xyz
from .match_rules import THROW_RECOVERY, UTILITY


def facing(origin, watch, point):
    dx, dy = watch[0] - origin[0], watch[1] - origin[1]
    x, y = point[0] - origin[0], point[1] - origin[1]
    return dx * x + dy * y >= 0.5 * hypot(dx, dy) * hypot(x, y)


def station(space, actor, site, lane, options, occupied=()):
    for point, watch in options:
        if any(dist(point, taken) < 5 for taken in occupied):
            continue
        if space._reachable(xyz(actor), [point], actor["navArea"]) is not None:
            return dict(
                id=actor["id"],
                site=site,
                lane=lane,
                hold=list(point),
                watch=list(watch),
            )
    return None


def relief(plan, actor):
    for key in ("backup", "secondBackup"):
        duty = plan.get(key)
        if duty and duty["id"] == actor["id"]:
            return duty
    return plan.get("commitments", {}).get(actor["id"])


def assignment(plan, actor, squad):
    """A reserve and an inherited anchor duty replace the whole home assignment."""
    slots = plan["orders"]["slots"]
    slot = actor["slot"]
    duty = relief(plan, actor)
    if duty:
        return duty
    if (slot in (2, 3) and slots[slot]["site"] == slots[slot-2]["site"]
            and not any(p["slot"] == slot - 2 for p in squad)):
        return slots[slot - 2]
    order = slots[slot]
    if order.get("screen") and not actor.get("leftScreen"):
        return order["screen"]
    return order


def opening_screen(space, site, lane, origin, hold, watch, anchor, anchor_watch):
    """Find an earlier playable contact along the wing's real route to its hold."""
    route = space.path(
        space.locate(origin), origin, space.locate(hold), hold, frozenset()
    )
    entries = space.ingress(site, lane)
    if not route or not entries:
        return None
    # Only buy space where the other defender can cover our retreat, and
    # where stopping gains a sightline unavailable from the final assignment.
    points = {}
    walked = 0.0
    prev = origin
    for node in route:
        pos = node[:3]
        walked += dist(prev, pos)
        prev = pos
        if 6 < dist(pos, hold) < 42 and 8 < dist(pos, anchor) < 65:
            points[pos] = walked
    if not points:
        return None

    def eye(p):
        x, y, z = space.world(p)
        return x, y, z + 64

    eyes = {p: eye(p) for p in [*points, hold, anchor, *entries]}
    rays = [(eyes[p], eyes[e]) for p in [*points, hold] for e in entries]
    rays.extend((eyes[anchor], eyes[p]) for p in points)
    seen = space.collision.sight_many(rays)
    options = []
    for step, entry in enumerate(entries):
        if seen.get((eyes[hold], eyes[entry])) and facing(hold, watch, entry):
            break
        for pos, length in points.items():
            if (
                seen.get((eyes[pos], eyes[entry]))
                and dist(pos, entry) > 6
                and seen.get((eyes[anchor], eyes[pos]))
                and facing(anchor, anchor_watch, pos)
            ):
                options.append((step, length, pos, entry))
    if options:
        _, _, pos, entry = min(options)
        return dict(site=site, lane=lane, hold=list(pos), watch=list(entry))
    return None


def corridor(space, site, lane, hold, watch):
    """Static, physically visible crossings in the assigned field, in route order."""
    points = [
        p
        for p in space.ingress(site, lane)
        if facing(hold, watch, p) and space.hit(hold, p, 1, 64) is None
    ]
    return tuple(dict.fromkeys([*points, watch]))


def interpret(space, order, reports, now, reading, familiarity):
    """Map a dated observation to an accessible crossing; no extrapolation through walls."""
    origin, watch = tuple(order["hold"]), tuple(order["watch"])
    points = space.sector(order["site"], order.get("lane", 0), origin, watch)
    best, focus = 0.0, watch
    for report in reports:
        age = now - report["tick"]
        if age < 0 or age >= 75:
            continue
        pos = xyz(report)
        direction = report.get("direction")
        projected = expected_travel(report,age,reading)
        confidence = (1 - age / 75) * (
            0.5 if report["source"] in ("Слух", "Граната") else 1
        )
        # Anticipation is bounded by travel since observation. Map knowledge
        # resolves the corridor within our duty, never an enemy's current NAV area.
        for point in points:
            gap = dist(pos, point)
            if gap > 12 + projected + familiarity / 4:
                continue
            if abs(point[2] - pos[2]) > 6 and space.hit(pos, point, 1, 48) is not None:
                continue
            forward = (
                sum((b - a) * d for a, b, d in zip(pos, point, direction)) / max(1, gap)
                if direction
                else 0
            )
            error = abs(gap - projected) if forward > 0 else gap
            strength = confidence * (1 + max(0, forward) * reading / 100) / (1 + error)
            if strength > best:
                best, focus = strength, point
    return focus


def plant_intercept(space, actor, allies, points, now, deadline):
    """Select a reachable angle onto the audible sector before the interaction ends."""
    origin = xyz(actor)
    if not points:
        return None, None
    others = [
        p["plantCue"]["watch"]
        for p in allies
        if p is not actor
        and p.get("plantCue")
        and p["plantCue"].get("peek") is not None
        and now - p["plantCue"]["tick"] < 30
    ]
    reach = max(0, (deadline - now) * 1.65)
    spots = [
        origin,
        *(space.centers[i] for i in sorted(space.nearby_areas(origin, min(24, reach)))),
    ]

    def eye(p, height):
        x, y, z = space.world(p)
        return x, y, z + height

    eyes = {p: eye(p, 64) for p in spots}
    targets = {p: eye(p, 40) for p in points}
    visible = space.collision.sight_many(
        [(e, t) for e in eyes.values() for t in targets.values()]
    )
    choices = []
    for spot in spots:
        seen = [q for q in points if visible.get((eyes[spot], targets[q]))]
        if not seen:
            continue

        def coverage(aim):
            field = [q for q in seen if facing(spot, aim, q)]
            independent = sum(all(dist(q, r) > 6 for r in others) for q in field)
            return independent, len(field), -dist(spot, aim)

        watch = max(seen, key=coverage)
        independent, count, _ = coverage(watch)
        choices.append((-independent, -count, dist(origin, spot), spot, watch))
    for _, _, _, spot, watch in sorted(choices):
        if spot == origin:
            return spot, watch
        path = space.path(
            actor["navArea"], origin, space.locate(spot), spot, frozenset()
        )
        if path is not None:
            vertices = [origin, *(node[:3] for node in path)]
            if sum(dist(a, b) for a, b in zip(vertices, vertices[1:])) <= reach:
                return spot, watch
    return None, None


def check_carrier(space, actor, allies, cue, now, reading):
    """A fresh carrier report can narrow a keypad sound to one playable angle."""
    from .cs2_play import outside_bearing
    from .match_ai import near_line
    from .match_rules import WEAPONS

    if (
        actor["blind"] > now
        or actor["reloadAt"]
        or now < actor["ready"]
        or actor["ammo"] <= 1
        or cue.get("checkingShots", 0) >= 3
    ):
        return None
    reports = [
        r
        for r in actor["knowledge"].values()
        if r.get("carryingC4")
        and r["source"] in ("Зрение", "Радио")
        and 0 <= now - r["tick"] <= 24
    ]
    if not reports:
        return None
    report = max(reports, key=lambda r: r["tick"])
    possible = anticipated(space, report, now, reading)
    if (
        outside_bearing(possible, cue["bearing"])
        or space.site_at(possible) != cue["site"]
    ):
        return None
    aim = dict(zip(("x", "y", "z"), possible))
    if any(p is not actor and near_line(actor, aim, p, 3) for p in allies):
        return None
    if not space.shot_transmission(
        xyz(actor), possible, WEAPONS[actor["weapon"]].penetration
    ):
        return None
    cue["checkingShots"] = cue.get("checkingShots", 0) + 1
    return aim


def screen_safe(space, plan, actor, squad, point):
    """Keep a live friendly firing lane open when screening an entrance."""
    from .match_ai import at, near_line

    cloud = at(point)
    for mate in squad:
        order = assignment(plan, mate, squad)
        hold, watch = order["hold"], order["watch"]
        # An approach can be smoked beyond our stop line; screening our own
        # fighting position leaves the attackers the exit from the cloud.
        if dist(hold, point) < UTILITY["Дым"][0]:
            return False
        if (
            near_line(at(hold), at(watch), cloud, UTILITY["Дым"][0])
            and dist(point, watch) > UTILITY["Дым"][0]
        ):
            return False
        if mate is not actor and mate.get("visible"):
            contact = mate.get("knowledge", {}).get(mate.get("target"))
            if contact and near_line(mate, contact, cloud, UTILITY["Дым"][0]):
                return False
    return True


def check_incoming(actor, intent, now, skills):
    """Turn toward an incoming round using only the observer's coarse directional cue."""
    from math import atan2
    from .cs2_play import outside_bearing

    cue = actor.get("incoming")
    shared = actor.get("pressureCall")
    if shared and (not cue or now - cue["tick"] > 12):
        cue = shared
    if (
        not cue
        or intent not in ("move", "hold")
        or actor["visible"]
        or actor["blind"] > now
    ):
        return
    age = now - cue["tick"]
    if age > 12 or age <= 0:
        return
    direction = cue["bearing"]
    # A recent sight in the same octant can disambiguate two possible angles.
    relevant = [
        r
        for r in actor["knowledge"].values()
        if r["source"] in ("Зрение", "Радио")
        and 0 <= now - r["tick"] < 20
        and not outside_bearing(xyz(r), direction)
    ]
    angle = atan2(direction[3], direction[2])
    if relevant:
        from math import pi

        sight = max(relevant, key=lambda r: r["tick"])
        bearing = atan2(sight["y"] - actor["y"], sight["x"] - actor["x"])
        confidence = (1 - (now - sight["tick"]) / 20) * skills["game_reading"] / 100
        angle += ((bearing - angle + pi) % (2 * pi) - pi) * confidence
    actor["heading"] = angle


def expected_travel(report, age, reading):
    """Estimate progress along the measured heading from available evidence."""
    if age <= 0 or not report.get("direction"):
        return 0
    age = min(age, 24)
    speed = min(2, report.get("speed", 0))
    sample = report.get("motionRun", 1)
    supported = min(age, sample) / age
    total, count = report.get("motionHistory", {}).get(
        str(age.bit_length() - 1), (0, 0)
    )
    fraction = (supported + total) / (1 + count)
    return speed * age * (1 + (fraction - 1) * reading / 100)


def anticipated(space, report, now, reading):
    """Project the report along observed movement within the visible corridor."""
    position = xyz(report)
    direction = report.get("direction")
    if not direction or report["source"] not in ("Радио", "Зрение"):
        return position
    travel = expected_travel(report, now - report["tick"], reading)
    if not travel:
        return position
    predicted = tuple(v + d * travel for v, d in zip(position, direction))
    return predicted if space.hit(position, predicted, 1, 48) is None else position


def breach_watch(space, plan, actor, squad, order, now, reading):
    """One available guard checks a credible breach; the other guards retain their angles."""
    reports = [r for r in actor["knowledge"].values() if 0 < now - r["tick"] < 30]
    reports.sort(key=lambda r: (not r.get("carryingC4"), -r["tick"]))
    for r in reports:
        last = xyz(r)
        point = anticipated(space, r, now, reading)
        # Personal visual contact can be reacquired without abandoning a
        # position. A NAV site label is immaterial to a visible corridor.
        if (
            r["source"] == "Зрение"
            and now - r["tick"] <= 12
            and space.hit(xyz(actor), point, 1, 64) is None
        ):
            return point
        if r["source"] == "Граната" or dist(last, order["hold"]) > 65:
            continue
        report_site = space.reported_site(last)
        if report_site != order["site"]:
            if report_site is not None:
                continue
            if not facing(order["hold"], order["watch"], point) and (
                space.entry_sites.get(space.locate(last)) != order["site"]
            ):
                continue
        if r["source"] == "Слух" and now - r["tick"] > 12:
            continue
        responders = []
        for mate in squad:
            if (
                mate["reloadAt"]
                or mate["blind"] > now
                or (mate["visible"] and r["id"] not in mate["visible"])
            ):
                continue
            job = assignment(plan, mate, squad)
            if (
                job["site"] != order["site"]
                or space.hit(xyz(mate), point, 1, 64) is not None
            ):
                continue
            # The player already facing this sector incurs the least exposure.
            # If everyone faces away, turn the closest available trade partner.
            continuing = facing(job["hold"], job["watch"], point)
            responders.append((not continuing, dist(xyz(mate), point), mate["slot"]))
        if responders and min(responders)[-1] == actor["slot"]:
            return point
    return None


def attention(space, plan, actor, squad, player, now):
    order = assignment(plan, actor, squad)
    home = plan["orders"]["slots"][actor["slot"]]
    if order is home.get("screen"):
        sight = actor["knowledge"].values()
        # A sighting behind the screen or a reported carrier inside the site
        # makes the inner position more useful. A sound alone cannot prove a breach.
        breached = any(
            now - r["tick"] < 35
            and r["source"] in ("Радио", "Зрение")
            and dist(xyz(r), home["hold"]) < dist(xyz(r), order["watch"])
            and space.reported_site(xyz(r)) == home["site"]
            for r in sight
        )
        if dist(xyz(actor), order["hold"]) < 5:
            order.setdefault("checkedAt", now)
        checked = order.get("checkedAt")
        if (breached or actor["plantCue"] or actor["reloadAt"] or actor["hp"] < 35
                or now - plan["start"] > 190
                or checked is not None and now - checked >= 12 + player["skills"]["map_control"] // 3
                or any(r["source"] == "Зрение" and now-r["tick"] < 15 for r in sight)):
            actor["leftScreen"] = True
            order = home
    token = [order["site"], order["hold"], order["watch"]]
    review = actor.get("sectorReview")
    if not review or review["token"] != token or now >= review["next"]:
        skills = player["skills"]
        familiarity = player["mapKnowledge"].get(space.name.removeprefix("de_"), 0)
        focus = breach_watch(
            space, plan, actor, squad, order, now, skills["game_reading"]
        )
        if focus is None:
            focus = interpret(
                space,
                order,
                actor["knowledge"].values(),
                now,
                skills["game_reading"],
                familiarity,
            )
        actor["sectorReview"] = review = dict(
            token=token, focus=list(focus), next=now + 5
        )
    return order, review["focus"]


def rank_crossfire(anchor, anchor_watch, positions, visible, entries, wing, plant):
    """A trade requires two observers looking at the same crossing."""
    ranked = []
    for p in positions:
        if not 7 < dist(p, anchor) < 52:
            continue
        seen = visible[p]
        for point in seen:
            if point not in visible[anchor] or not facing(anchor, anchor_watch, point):
                continue
            vectors = [
                [origin[j] - point[j] for j in range(3)] for origin in (p, anchor)
            ]
            cosine = sum(a * b for a, b in zip(*vectors)) / (
                dist(p, point) * dist(anchor, point)
            )
            if cosine >= 0.78:
                continue
            # Coverage outside the anchor's field only counts if the wing
            # also sees it while watching the common trade point.
            extra = sum(
                r in entries
                and facing(p, point, r)
                and (r not in visible[anchor] or not facing(anchor, anchor_watch, r))
                for r in seen
            )
            ranked.append(
                (
                    point not in entries,
                    -min(extra, 4),
                    abs(p[2] - wing[2]) * 12 > 72,
                    -min(dist(plant, point), 50),
                    dist(p, wing),
                    cosine,
                    p,
                    point,
                )
            )
    return ranked


def report_crossing(space, actor, squad, plan, smoke, now):
    """Report one entrance the guard physically watches, including an obscured approach."""
    from .match_ai import in_view, near_line, at

    order = assignment(plan, actor, squad)
    if (
        actor["blind"] > now
        or actor["reloadAt"]
        or not actor["ammo"]
        or dist(xyz(actor), order["hold"]) > 12
    ):
        return None
    entries = space.ingress(order["site"], order.get("lane", 0))
    pos = xyz(actor)
    points = sorted(entries, key=lambda p: dist(p, order["watch"]))
    for point in points:
        mark = at(point)
        if not in_view(actor, mark) or space.hit(pos, point, 1, 64) is not None:
            continue
        blocked = any(near_line(actor, mark, f, f["radius"]) for f in smoke)
        contact = any(
            dist(xyz(actor["knowledge"][k]), point) < 18 for k in actor["visible"]
        )
        return dict(
            site=order["site"],
            lane=order.get("lane", 0),
            point=list(point),
            tick=now,
            state="contact" if contact else "obscured" if blocked else "watching",
        )
    return None


def help_site(space, leader, now):
    """Select a nearby guard's request for assistance with no inferred enemy count."""
    calls = [
        r for r in leader.get("squadPressure", {}).values() if 0 <= now - r["tick"] < 30
    ]
    if not calls:
        return None
    newest = max(calls, key=lambda r: r["tick"])
    return space.reported_site(tuple(newest["origin"]))


def brief(space, plan, squad, leader, player, now):
    """Assign the relief lane by observed pressure and the squad's actual coverage."""
    skills = player["skills"]
    familiarity = player["mapKnowledge"].get(space.name.removeprefix("de_"), 0)
    reports = list(leader["knowledge"].values())
    lanes = {}
    for site in ("A", "B"):
        scores = []
        for lane in (0, 1):
            route = space.ingress(site, lane)
            if not route:
                scores.append(0)
                continue
            guards = [a for a in squad if assignment(plan, a, squad)["site"] == site]
            # Benefit of reinforcing a crossing left uncovered. An assigned
            # player still travelling or engaged is not holding that line yet.
            covered = set()
            for mate in guards:
                order = assignment(plan, mate, squad)
                if order.get("lane", lane) != lane:
                    continue
                call = leader.get("sectorCalls", {}).get(mate["id"])
                if call and call["site"] == site and call["lane"] == lane and 0 <= now-call["tick"] < 35:
                    if call["state"] == "watching":
                        covered.add(tuple(call["point"]))
                    continue
                # Until a report arrives, the position and facing of an available
                # teammate support only a conservative estimate of his field.
                if dist(xyz(mate), order["hold"]) < 8 and not mate["reloadAt"]:
                    from .match_ai import at, in_view
                    covered.update(p for p in space.sector(site,lane,tuple(order["hold"]),tuple(order["watch"]))
                                   if in_view(mate,at(p)))
            evidence = 0
            for report in reports:
                age = now - report["tick"]
                if not 0 <= age < 75:
                    continue
                pos = xyz(report)
                point = min(route, key=lambda q: dist(q, pos))
                gap = dist(pos, point)
                direction = report.get("direction")
                movement = (
                    sum((b - a) * d for a, b, d in zip(pos, point, direction))
                    / max(1, gap)
                    if direction
                    else 0
                )
                confidence = (1 - age / 75) / (1 + gap)
                if report["source"] in ("Граната", "Слух"):
                    confidence /= 2
                evidence += confidence * (1 + movement * skills["game_reading"] / 100)
            unguarded = 1 - sum(p in covered for p in route)/len(route)
            # A captain with limited familiarity relies more on direct reports.
            scores.append(
                evidence
                + unguarded
                * (familiarity + skills["calling"] + skills["leadership"])
                / 300
            )
        lanes[site] = max((plan["lane"], 1 - plan["lane"]), key=scores.__getitem__)
    plan["reliefLanes"] = lanes


def protected_by(space, actor, contact, squad):
    """A ready teammate can trade a visible opponent even before acquiring a target."""
    from .match_ai import in_view

    return any(
        p is not actor
        and p["ammo"]
        and not p["reloadAt"]
        and dist(xyz(actor), xyz(p)) < 45
        and in_view(p, contact)
        and space.hit(xyz(p), xyz(contact), 1, 64) is None
        for p in squad
    )


def contact_grenade(space, actor, contact, visible, allies, player, plan, now, phase):
    """Compare a throw with the shots forgone before it lands."""
    from . import match_performance as perf
    from .match_rules import WEAPONS
    from .match_ai import distance

    if not actor["utility"] or now < actor["throwAt"]:
        return None
    gap = distance(actor, contact)
    if gap <= 18:
        return None
    spec = WEAPONS[actor["weapon"]]
    skills = player["skills"]
    flight = max(3, round(gap / 7))
    backup = any(p is not actor and p["target"] == contact["id"] for p in allies)
    vulnerable = bool(actor["reloadAt"] or actor["hp"] < 45)
    ready_in = max(0, max(actor["ready"], actor["reloadAt"]) - now)
    shots = min(actor["ammo"], max(0, 1 + (THROW_RECOVERY - 1 - ready_in) // spec.interval))
    chance = perf.accuracy(player, actor, spec, gap, actor["burst"], now) / 100
    opportunity = shots * spec.damage * chance
    choices = []
    for item in dict.fromkeys(actor["utility"]):
        radius = UTILITY[item][0]
        if item == "Ложная":
            continue
        affected = [p for p in visible if distance(p, contact) < radius]
        friends = [p for p in allies if distance(p, contact) < radius
                   and space.hit(xyz(contact),xyz(p),1,5,64) is None]
        if item == "Дым":
            if (
                not vulnerable
                or backup
                or (
                    phase == "live"
                    and actor["team"] == "CT"
                    and not screen_safe(space, plan, actor, allies, xyz(contact))
                )
            ):
                continue
            benefit = spec.damage
        elif item == "Свет":
            if friends or not (backup or vulnerable):
                continue
            benefit = len(affected) * spec.damage
        else:
            if friends:
                continue
            benefit = sum(
                (1 - distance(p, contact) / radius) * (82 if item == "HE" else 30)
                for p in affected
            )
        mastery = skills[perf.GRENADE_SKILL[item]] / 100
        # Forecast exposure during flight using only observed lateral motion.
        exposure = max(0, 1 - contact.get("speed", 0) * flight / radius)
        value = benefit * (1 - mastery * (1 - exposure))
        choices.append((value, item))
    if not choices:
        return None
    value, item = max(choices)
    # A player who has time to evaluate the duel includes the value of the
    # loaded weapon. The underlying shot and grenade mechanics are unchanged.
    if value <= opportunity * skills["decisions"] / 100:
        return None
    x, y, z, _ = space.grenade(xyz(actor), xyz(contact), flight)
    if dist((x, y, z), xyz(contact)) >= UTILITY[item][0]:
        return None
    return item


def last_burst(space, actor, sight, squad, player, now):
    """Continue an already acquired burst along observed motion while it remains plausible."""
    from .match_ai import near_line

    age = now - sight["tick"]
    if sight["source"] != "Зрение" or not 0 < age <= 3:
        return None
    direction = sight.get("direction", (0, 0, 0))
    origin = xyz(sight)
    reading = player["skills"]["game_reading"] / 100
    delta = min(2, sight.get("speed", 0)) * age * reading
    predicted = tuple(a + d * delta for a, d in zip(origin, direction))
    if predicted != origin and space.hit(origin, predicted, 1, 56) is not None:
        predicted = origin
    target = dict(sight, **dict(zip(("x", "y", "z"), predicted)))
    if any(p is not actor and near_line(actor, target, p, 2) for p in squad):
        return None
    return target


def support_partner(plan, actor, squad, chemistry, skills):
    """Support the actual entry or carrier on our approach, with a trade partner in mind."""
    from .world import pair_key

    slots = plan["orders"]["slots"]
    lane = slots[actor["slot"]]["lane"]
    mates = [p for p in squad if p is not actor and slots[p["slot"]]["lane"] == lane]
    if not mates:
        return None

    def priority(mate):
        pair = chemistry.get(pair_key(actor["playerId"], mate["playerId"]), 0)
        readiness = (skills["support"] + skills["coordination"] + pair) / 300
        need = int(bool(mate["reloadAt"]) or mate["hp"] < actor["hp"])
        need += int(mate["playingRole"] == "entry")
        return need * readiness - dist(xyz(actor), xyz(mate)) / 100, -mate["slot"]

    return max(mates, key=priority)
