"""Five-player CT calls on the installed map. All distances use simulation units."""

from math import atan2, dist

from . import cs2_defense
from backend import engine, world
from .cs2_maps import xyz
from backend.match_rules import UTILITY


def line(space, p, q):
    return space.hit(p, q, 1, 64) is None


def path(space, origin, goal):
    return space.path(
        space.locate(origin), origin, space.locate(goal), goal, frozenset()
    )


def positions(space, zone, origin, cautious):
    """Find an actual sightline and a covered step from which to check it again."""
    _, seat, target = space.defense["zones"][zone]
    seats = [space.centers[i] for i in sorted(space.places[seat])]
    targets = [space.centers[i] for i in sorted(space.places[target])]
    for post in sorted(seats, key=lambda q: dist(origin, q)):
        route = path(space, origin, post)
        if route is None:
            continue
        toward = min(targets, key=lambda q: dist(post, q))
        nearby = [space.centers[i] for i in sorted(space.nearby_areas(post, 38))]
        # Prefer a sightline looking into the named approach. A blocked
        # doorway can be checked from a corner on the way to its marker.
        onward = path(space, post, toward) or []
        views = [toward, *(q[:3] for q in reversed(onward) if dist(post, q[:3]) > 9)]
        # A named vent may have its marker inside a prop. Check the nearest
        # navigable lip on the same floor instead of losing the entire task.
        views.extend(
            sorted(
                (
                    space.centers[i]
                    for i in space.nearby_areas(toward, 22)
                    if abs(space.centers[i][2] - toward[2]) < 10
                ),
                key=lambda q: (dist(q, toward), q),
            )[:10]
        )
        for watch in views:
            opts = [
                q
                for q in [post, *nearby]
                if 5 < dist(q, watch) < 115 and line(space, q, watch)
            ]
            for peek in sorted(
                opts,
                key=lambda q: (
                    dist(q, post) + (0 if cautious else 0.35 * dist(q, watch))
                ),
            ):
                approach = path(space, origin, peek)
                if approach is None:
                    continue
                points = [q[:3] for q in approach]
                cover = [
                    q
                    for q in [*points, *nearby]
                    if 9 < dist(q, peek) < 33 and line(space, q, peek)
                ]
                cover.sort(
                    key=lambda q: (
                        not line(space, q, watch),
                        abs(dist(q, peek) - 18),
                        dist(q, origin),
                    )
                )
                back = next(
                    (
                        q
                        for q in cover
                        if path(space, q, peek) is not None
                        and path(space, peek, q) is not None
                    ),
                    None,
                )
                if back:
                    return back, peek, watch
        # Try another mapped seat if no supported peek exists here.
    return None


def select(space, plan, squad, players, captain, predicted, explicit):
    profile = space.defense
    skills = players[captain["playerId"]]["skills"]
    familiar = players[captain["playerId"]]["mapKnowledge"].get(space.name[3:], 0)
    calls = list(profile["plays"].items())
    # Mix the full CT-local draw before taking the small weighted interval.
    # Adjacent match seeds otherwise repeatedly hit the same few calls.
    light = plan["buy"] in ("Эко", "Частичная")
    weights = []
    for _, zones in calls:
        site = explicit or predicted
        priority = sum(profile["zones"][z][0] == site for z in zones) if site else 0
        paired = max(zones.count(z) for z in zones)
        spawns = sum(
            min(
                dist(xyz(p), space.centers[i])
                for i in space.places[profile["zones"][zones[p["slot"]]][1]]
            )
            for p in squad
        )
        weights.append(
            max(
                3,
                18
                + priority * (12 if explicit else 5)
                + paired * (skills["coordination"] // 25)
                - int(spawns / 70),
            )
        )
    quiet = 7 + (20 if light else 0) + (200 - skills["calling"] - familiar) // 12
    draw = engine._draw(captain)
    roll = ((draw ^ (draw >> 16)) * 0x9E3779B1 & 0xFFFFFFFF) % (sum(weights) + quiet)
    if roll < quiet:
        return (
            "Закрытая защита",
            max(
                calls,
                key=lambda c: sum(
                    profile["zones"][z][0] == (explicit or predicted or plan["site"])
                    for z in c[1]
                ),
            )[1],
            True,
        )
    roll -= quiet
    for (name, zones), weight in zip(calls, weights):
        if roll < weight:
            return name, zones, False
        roll -= weight


def draft(space, plan, squad, players, captain, predicted, explicit, chemistry):
    name, zones, quiet = select(
        space, plan, squad, players, captain, predicted, explicit
    )
    stack = explicit or (
        predicted if quiet and plan["buy"] in ("Эко", "Форс", "Частичная") else None
    )
    if stack:
        zones = list(zones)
        wanted = [
            z for z in space.defense["zones"] if space.defense["zones"][z][0] == stack
        ]
        for slot in (4, 2, 3) if stack == "A" else (4, 3, 2):
            if sum(space.defense["zones"][z][0] == stack for z in zones) >= 4:
                break
            if space.defense["zones"][zones[slot]][0] != stack:
                zones[slot] = min(wanted, key=lambda z: (zones.count(z), z))
        name = "Усиление " + stack + " · " + name
    fallback = plan["orders"]["slots"]
    jobs = {}
    for p in sorted(squad, key=lambda p: p["slot"]):
        slot = p["slot"]
        zone = zones[slot]
        site, _, _ = space.defense["zones"][zone]
        original = fallback[slot]
        if original["site"] != site:
            lane = fallback[0 if site == "A" else 1]["lane"]
            relief = cs2_defense.station(
                space,
                p,
                site,
                lane,
                space.angles(site, lane, space.site_points[site], "site"),
                [order["hold"] for order in fallback if order["site"] == site],
            )
            original.update(
                relief
                or dict(
                    {
                        key: fallback[0 if site == "A" else 1][key]
                        for key in ("hold", "watch", "lane")
                    },
                    site=site,
                )
            )
        original.pop("screen", None)
        coords = space.zone_positions(zone, xyz(p), quiet)
        job = dict(zone=zone, site=site, role="наблюдение", home=original["hold"])
        if coords:
            job.update(zip(("gate", "peek", "watch"), map(list, coords)))
        else:
            job["reason"] = "Нет достижимой пары позиций"
        jobs[p["id"]] = job
    for zone in dict.fromkeys(zones):
        members = [
            p
            for p in squad
            if jobs[p["id"]]["zone"] == zone and "gate" in jobs[p["id"]]
        ]
        if len(members) < 2:
            continue

        def lead_score(p):
            skill = players[p["playerId"]]["skills"]
            return (
                skill["map_control"]
                + skill["decisions"]
                - dist(xyz(p), jobs[p["id"]]["gate"]) / 3
            )

        scout, support = sorted(members, key=lead_score, reverse=True)[:2]
        first, second = jobs[scout["id"]], jobs[support["id"]]
        if path(space, xyz(support), tuple(first["gate"])) is None:
            continue
        for key in ("gate", "peek", "watch"):
            second[key] = first[key]
        first.update(role="разведка", partner=support["id"])
        second.update(role="страховка", partner=scout["id"])
    # On a spread call the second player covers the first crossing, then takes
    # their own assignment once the scout has reported. Both routes must exist.
    singles = [
        p
        for p in squad
        if jobs[p["id"]]["role"] == "наблюдение" and "gate" in jobs[p["id"]]
    ]
    pairs = [
        (p, m)
        for p in singles
        for m in singles
        if p is not m and jobs[p["id"]]["site"] == jobs[m["id"]]["site"]
    ]

    def diversion(pair):
        lead, escort = (jobs[p["id"]] for p in pair)
        return (
            dist(lead["gate"], escort["gate"])
            - players[pair[1]["playerId"]]["skills"]["support"] / 5
            - chemistry.get(world.pair_key(pair[0]["playerId"], pair[1]["playerId"]), 0)
            / 4
        )

    for scout, escort in sorted(pairs, key=diversion):
        lead, j = jobs[scout["id"]], jobs[escort["id"]]
        if (
            dist(lead["gate"], j["gate"]) > 165
            or path(space, xyz(escort), tuple(lead["gate"])) is None
            or path(space, tuple(lead["gate"]), tuple(j["gate"])) is None
        ):
            continue
        j["handoff"] = {k: j[k] for k in ("gate", "peek", "watch", "zone")}
        j.update({k: lead[k] for k in ("gate", "peek", "watch", "zone")})
        j.update(role="страховка", partner=scout["id"])
        lead.update(role="разведка", partner=escort["id"])
        break
    leading = [j["zone"] for j in jobs.values() if j["role"] == "разведка"]
    priority_zones = list(dict.fromkeys([*leading, *zones]))
    if predicted or explicit:
        priority_zones.sort(
            key=lambda z: space.defense["zones"][z][0] != (explicit or predicted)
        )
    focus = priority_zones[:2]
    plan["opening"] = dict(jobs=jobs, quiet=quiet, reports={}, salvos={}, focus=focus)
    plan["formation"] = name
    return name


def priority(job):
    if "gate" not in job:
        return []
    if job["role"] == "страховка":
        return ["Свет", "Дым"]
    return ["Огонь", "Дым"]


def trajectory(space, origin, target):
    flight = max(3, round(dist(origin, target) / 7))
    landing = space.grenade(origin, target, flight)
    return len(landing[3]) - 1 if dist(landing[:3], target) < 6 else None


def lineup(space, origin, gate, peek, watch, item):
    """Search along the walk to the gate, then nearby reachable launch positions."""
    route = path(space, origin, gate)
    if route is None:
        return None
    radius = UTILITY[item][0]
    nearby = [space.centers[i] for i in sorted(space.nearby_areas(gate, 28))]
    launches = [
        origin,
        *(p[:3] for p in route),
        gate,
        *sorted(nearby, key=lambda q: dist(q, gate))[:12],
    ]
    # An alternative landing must still affect the observed choke on this floor.
    # Prefer an earlier validated release to walking all the way to the marker.
    options = [
        watch,
        *sorted(
            (space.centers[i] for i in space.nearby_areas(watch, radius - 2)),
            key=lambda q: (dist(q, watch), q),
        ),
    ]
    options = [
        q
        for q in options
        if abs(q[2] - watch[2]) < 12
        and line(space, q, watch)
        and (dist(q, gate) > radius + 2 or not line(space, gate, q))
        and (item == "Свет" or dist(q, peek) > radius + 3)
    ]
    for launch in dict.fromkeys(launches):
        for target in options:
            if not max(16, radius + 2) < dist(launch, target) < 105:
                continue
            if trajectory(space, launch, target) is None:
                continue
            if launch in nearby and (
                path(space, origin, launch) is None or path(space, launch, gate) is None
            ):
                continue
            return list(launch), list(target)
    return None


def equip(space, plan, squad):
    opening = plan["opening"]
    # Budget and actual purchases come first. One team may cover multiple
    # approaches to the same site. A flash can follow denial in a paired lane.
    for p in sorted(
        squad,
        key=lambda p: (opening["jobs"][p["id"]]["role"] != "страховка", p["slot"]),
    ):
        job = opening["jobs"][p["id"]]
        if "gate" not in job or opening["quiet"] or job["zone"] not in opening["focus"]:
            continue
        options = [g for g in priority(job) + ["Свет", "Дым"] if g in p["utility"]]
        if not options:
            job["utilityReason"] = "Нет подходящей гранаты"
        for item in dict.fromkeys(options):
            zone = job["zone"]
            key = zone + ("/flash" if item == "Свет" else "/screen")
            if key in opening["salvos"]:
                continue
            coords = space.zone_lineup(
                xyz(p), *(tuple(job[k]) for k in ("gate", "peek", "watch")), item
            )
            if not coords:
                job["utilityReason"] = "Нет проверенной траектории"
                continue
            job.pop("utilityReason", None)
            job["throw"] = dict(
                item=item,
                launch=coords[0],
                target=coords[1],
                forPlayer=job.get("partner", p["id"]),
            )
            opening["salvos"][key] = p["id"]
            break


def review(space, plan, squad, now, captain):
    """Act on delivered observations and replace a partner lost to a rotation."""
    opening = plan.get("opening")
    if not opening:
        return
    jobs, reports = opening["jobs"], opening["reports"]
    alive = {p["id"]: p for p in squad}
    clear = {
        pid: r
        for pid, r in reports.items()
        if pid in alive
        and 0 <= now - r["due"] < 65
        and not any(
            sight["tick"] >= r.get("observed", r["due"])
            and sight["source"] in ("Зрение", "Радио")
            and dist(xyz(sight), jobs[pid]["watch"]) < 28
            for sight in captain["knowledge"].values()
        )
    }
    for pid, p in alive.items():
        j = jobs[pid]
        partner = j.get("partner")
        mate = alive.get(partner)
        lost = partner and (
            not mate or cs2_defense.relief(plan, mate) or jobs[partner].get("withdrawn")
        )
        if j.get("handoff") and (partner in clear or lost):
            # Once the entry is accounted for the escort rotates to their
            # next lane. The entry holds the sector while that player moves.
            if "throw" in j and "land" not in j["throw"]:
                j["throw"]["skip"] = "Приказ о смене позиции"
            next_zone = j.pop("handoff")
            j.update(next_zone, role="наблюдение", handoffAt=now)
            for k in ("partner", "atGate", "lastCover", "departed"):
                j.pop(k, None)
            jobs[partner].pop("partner", None)
            jobs[partner]["holdsFor"] = pid
        if opening["quiet"] and pid not in clear and not cs2_defense.relief(plan, p):
            # Release the next pair together only after the first sector reports.
            if j["zone"] in opening["focus"][1:] and any(
                r["zone"] == opening["focus"][0] for r in clear.values()
            ):
                j.setdefault("release", now)
        assigned = alive.get(j.get("replacement"))
        if assigned:
            assignment = jobs[assigned["id"]].get("coverOrder", {})
            if assignment.get("forPlayer") == pid:
                if (
                    lost
                    and now < assignment["until"]
                    and not cs2_defense.relief(plan, assigned)
                ):
                    continue
                jobs[assigned["id"]].pop("coverOrder", None)
        if (
            not lost
            or "gate" not in j
            or cs2_defense.relief(plan, p)
            or j.get("withdrawn")
        ):
            continue
        candidates = [
            m
            for m in squad
            if m is not p
            and m["id"] in clear
            and not jobs[m["id"]].get("partner")
            and not cs2_defense.relief(plan, m)
            and not jobs[m["id"]].get("coverOrder")
            and jobs[m["id"]]["site"] == j["site"]
            and dist(xyz(m), j["gate"]) < 65
        ]
        if candidates:
            replacement = min(candidates, key=lambda m: dist(xyz(m), j["gate"]))
            if path(space, xyz(replacement), tuple(j["gate"])) is not None:
                job = jobs[replacement["id"]]
                job["coverOrder"] = dict(
                    goal=j["gate"],
                    watch=j["peek"],
                    until=now + 50,
                    forPlayer=pid,
                    issued=now,
                    captain=captain["id"],
                )
                j["replacement"] = replacement["id"]
    for j in jobs.values():
        if j.get("coverOrder", {}).get("until", now + 1) <= now:
            j.pop("coverOrder", None)


def planned_throw(space, w, a, squad, support, jobs, job, move, travel, fire):
    now = w["tick"]
    current = xyz(a)
    gate = job["gate"]
    plan = w["plan"]
    cast = job.get("throw")
    if cast and "land" not in cast and "skip" not in cast:
        item = cast["item"]
        target = cast["target"]
        if item not in a["utility"] or now - plan["start"] > 260:
            cast["skip"] = "Расход или истёк интервал"
        elif cast["forPlayer"] != a["id"] and not support:
            cast["skip"] = "Напарник недоступен"
        elif dist(current, cast["launch"]) > 3:
            return move(cast["launch"], "Занимает позицию броска")
        else:
            # If the second player carries denial and the flash, never make
            # both wait for each other. Only the flash waits for entry readiness.
            if (
                item == "Свет"
                and support
                and now < jobs[support["id"]].get("atGate", now + 1)
            ):
                if now - plan["start"] < 175:
                    return move(current, "Ждёт готовности выхода", gate)
                cast["skip"] = "Напарник не вышел на рубеж"
                return move(gate, "Занимает страховку")
            flight = trajectory(space, current, target)
            if flight is None:
                if dist(current, cast["launch"]) > 0.5:
                    travel(a, cast["launch"], 1, fire)
                    return "move", None
                cast["skip"] = "Линия броска перекрыта"
            elif any(
                dist(xyz(p), target) < UTILITY[item][0] + 2
                and line(space, xyz(p), target)
                for p in squad
            ):
                cast["skip"] = "Союзник в зоне гранаты"
            elif now >= a["throwAt"] and a["blind"] <= now:
                return "throw", dict(
                    zip(("x", "y", "z"), target),
                    utility=item,
                    purpose="Занятие " + job["zone"],
                    openingZone=job["zone"],
                )
    return None


def execute(space, w, a, squad, fire, travel):
    from . import match_ai as ai

    plan, now = w["plan"], w["tick"]
    opening = plan["opening"]
    jobs = opening["jobs"]
    job = jobs[a["id"]]
    if "gate" not in job or a.get("plantCue") and now - a["plantCue"]["tick"] < 30:
        return None
    current = xyz(a)
    gate, peek, watch = (job[k] for k in ("gate", "peek", "watch"))
    mates = {p["id"]: p for p in squad}
    mate = mates.get(job.get("partner"))
    # A reserve moving elsewhere can no longer supply the crossfire or flash.
    support = mate if mate and not cs2_defense.relief(plan, mate) else None
    if cs2_defense.relief(plan, a) or plan.get("reinforce") == job["site"]:
        job["reason"] = "Приказ на усиление"
        return None
    if a["hp"] < 35 or a.get("blockedTicks", 0) >= 6:
        job["reason"] = "Ранение или потеря маршрута"
        job["withdrawn"] = True
    if job.get("withdrawn"):
        return None
    fresh = [
        r
        for r in a["knowledge"].values()
        if now - r["tick"] < 30 and r["source"] in ("Зрение", "Радио")
    ]
    if any(
        dist(xyz(r), job["home"]) < dist(xyz(r), peek)
        and space.reported_site(xyz(r)) == job["site"]
        for r in fresh
    ):
        job["reason"] = "Обошли передовую позицию"
        return None
    if support and jobs[support["id"]].get("withdrawn"):
        support = None
    delay = ai.radio_delay(w["player"]["skills"])

    def move(goal, status, look=watch):
        a["status"] = status + " · " + job["zone"]
        moved = dist(current, goal) > 3 and travel(a, goal, 2, fire)
        if not moved or dist(current, goal) < 24:
            # Keep the designated route and the paired flash window. A guard on
            # a stationary angle can turn to a recent sound or an ally's sight.
            cast = job.get("throw", {})
            awaiting_flash = (
                cast.get("item") == "Свет"
                and "skip" not in cast
                and now < cast.get("land", now + 1)
            )
            if not moved and not awaiting_flash:
                report = cs2_defense.opening_watch(a, squad, now, w["player"]["skills"])
                if report:
                    look = xyz(report)
                    a["status"] = (
                        (
                            "Слушает направление"
                            if report["source"] == "Слух"
                            else "Проверяет по радио"
                        )
                        + " · "
                        + job["zone"]
                    )
            a["heading"] = atan2(look[1] - a["y"], look[0] - a["x"])
        return ("move" if moved else "hold"), None

    if (
        opening["quiet"]
        and job["zone"] != opening["focus"][0]
        and not job.get("coverOrder")
        and not job.get("release")
    ):
        return move(
            job["home"],
            "Держит внутренний рубеж",
            plan["orders"]["slots"][a["slot"]]["watch"],
        )
    if job.get("coverOrder") and now < job["coverOrder"]["until"]:
        task = job["coverOrder"]
        return move(task["goal"], "Сменяет напарника", task["watch"])
    job.pop("reason", None)
    if job.get("throw"):
        thrown = planned_throw(
            space, w, a, squad, support, jobs, job, move, travel, fire
        )
        if thrown:
            return thrown
    if dist(current, gate) < 5:
        job.setdefault("atGate", now + delay)
    if "atGate" not in job:
        return move(gate, "Выходит на рубеж")
    if dist(current, gate) < 5 and job.get("atGate", now + 1) <= now:
        job["lastCover"] = now
    other = jobs.get(support["id"]) if support else None
    if job["role"] == "страховка" and other:
        contact = a["knowledge"].get(support.get("target"))
        if contact and now - contact["tick"] < 25:
            a["tradeTarget"] = contact["id"]
            a["tradeUntil"] = now + 12
            return move(gate, "Готовит размен", xyz(contact))
        if other.get("departed") and dist(xyz(support), peek) < 8:
            return move(gate, "Страхует занятую зону", watch)
        return move(gate, "Прикрывает выход напарника", peek)
    if not other and job.get("replacement") in mates:
        replacement = mates[job["replacement"]]
        cover = jobs[replacement["id"]].get("coverOrder", {})
        if (
            not cs2_defense.relief(plan, replacement)
            and cover.get("forPlayer") == a["id"]
            and dist(xyz(replacement), gate) < 6
        ):
            return move(peek, "Проверяет под сменную страховку")
    if job.get("partner") and not other:
        job["reason"] = "Нет страховки"
        return move(gate, "Держит до смены напарника")
    if other:
        pending = other.get("throw", {})
        flash_window = (
            pending.get("land", -100) <= now <= pending.get("land", -100) + 12
            and pending.get("item") == "Свет"
        )
        if (not flash_window and now - other.get("lastCover", -100) > 25) or (
            "item" in pending
            and "skip" not in pending
            and now < pending.get("land", now + 1)
        ):
            return move(gate, "Ждёт страховку")
    job.setdefault("departed", now)
    if (
        dist(current, peek) < 6
        and not fresh
        and w.get("openingSight")
        and a["blind"] <= now
        and ai.in_view(a, ai.at(watch))
    ):
        previous = opening["reports"].get(a["id"])
        if not previous or now - previous["due"] > 65:
            opening["reports"][a["id"]] = dict(
                zone=job["zone"], observed=now, due=now + delay
            )
            job["rechecks"] = job.get("rechecks", 0) + 1
    report = opening["reports"].get(a["id"])
    relieving = jobs.get(job.get("holdsFor"))
    if (
        relieving
        and now - relieving.get("handoffAt", 0) < 65
        and not relieving.get("rechecks")
    ):
        return move(peek, "Прикрывает смену позиции")
    if report and 20 <= now - report["due"] < 43:
        return move(gate, "Меняет угол после проверки")
    return move(
        peek, "Проверяет направление" if dist(current, peek) > 5 else "Наблюдает подход"
    )
