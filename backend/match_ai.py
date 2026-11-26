"""Perception, captain decisions and execution in the common BO1 simulation."""

from collections import deque
from functools import lru_cache
from math import cos, dist, atan2, ceil, hypot, pi, sin

from . import engine, match_inventory, tactic_execution, world
from . import match_performance as perf
from .match_events import impact, emit
from .match_rules import (
    BLAST_RADIUS,
    equipment_value,
    MAP,
    POSITIONS,
    RULES,
    UTILITY,
    THROW_RECOVERY,
    WEAPONS,
    role_orders,
)


from . import cs2_intel, cs2_play
from .cs2_maps import xyz


def point(a):
    return xyz(a) if "z" in a else (a["x"], a["y"])


def clear(space, a, b):
    return space.clear(a,b) if space else engine.clear_line(a["x"],a["y"],b["x"],b["y"])


def in_view(a,b):
    dx,dy=b["x"]-a["x"],b["y"]-a["y"]
    d2=dx*dx+dy*dy
    dot=dx*cos(a["heading"])+dy*sin(a["heading"])
    return dot>=0 and 4*dot*dot >= d2


def sees(space,a,b):
    return in_view(a,b) and space.clear(a,b) if space else engine.sees(a,b)


def distance(a, b):
    if "z" in a and "z" in b:
        return dist(xyz(a),xyz(b))
    return hypot(a["x"] - b["x"], a["y"] - b["y"])


def at(xy):
    return dict(zip(("x","y","z"),xy))


def near_line(a, b, p, radius):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    dz = b.get("z",0)-a.get("z",0)
    length = dx * dx + dy * dy + dz*dz
    ratio = (
        max(0, min(1, ((p["x"] - a["x"]) * dx + (p["y"] - a["y"]) * dy + (p.get("z",0)-a.get("z",0))*dz) / length))
        if length
        else 0
    )
    return hypot(a["x"] + ratio * dx - p["x"], a["y"] + ratio * dy - p["y"], a.get("z",0)+ratio*dz-p.get("z",0)) <= radius


@lru_cache(maxsize=256)
def audible_sector(col, row):
    centre = (col * 3 + 1, row * 3 + 1)
    floor = min(
        engine._FLOOR, key=lambda p: (p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2
    )
    return at(engine._center(floor))


def sound_position(space, source):
    if space:
        # Report a NAV sector, keeping the floor and discarding exact enemy XY.
        i=space.locate(xyz(source))
        if i is not None:
            return at(space.centers[i])
        return at(tuple(round(v/8)*8 for v in xyz(source)))
    return audible_sector(source["x"]//30,source["y"]//30)


def radio_delay(skills):
    return 1 + (100 - skills["communication"]) // 12


def heard_action(w, space, source, guards, kind, radius):
    """Model a game audio event at the listener, before any radio transmission."""
    now = w["tick"]
    pos = xyz(source)
    for guard in guards:
        if (
            guard["team"] != "CT"
            or not guard["hp"]
            or source.get("id") in guard["visible"]
        ):
            continue
        d = distance(guard, source)
        if d > radius or d < 1:
            continue
        skills = world.match_player(w, guard)["skills"]
        obstruction = space.hit(xyz(guard), pos, 4, 48)
        transmission = 1.0
        if obstruction:
            transmission = (
                0.70 if obstruction[1] in ("wood", "glass", "metalgrate") else 0.47
            )
        reach = radius * transmission * (0.78 + skills["game_reading"] / 460)
        if d + 0.8 * abs(pos[2] - guard["z"]) > reach:
            continue
        # Report an octant and a distance band, on the listener's floor. Never copy the source NAV area, identity or exact position.
        _, _, dx, dy = cs2_play.sound_bearing(guard, source)
        band = 14 if d < 25 else 43 if d < 62 else 83
        step = band / hypot(dx, dy)
        estimate = (guard["x"] + dx * step, guard["y"] + dy * step, guard["z"])
        key = "Шум · " + kind
        prior = guard["knowledge"].get(key)
        # Several footsteps or fake shots are one cue, never a head count.
        sustained = bool(
            prior
            and prior.get("witness") == guard["id"]
            and 0 < now - prior["tick"] < 18
            and dist(xyz(prior), estimate) < 28
        )
        cue = dict(
            id=key,
            **at(estimate),
            source="Слух",
            tick=now,
            sound=kind,
            witness=guard["id"],
            repeated=sustained,
            confidence=round(0.35 + 0.45 * (1 - d / reach), 2),
        )
        guard["knowledge"][key] = cue
        clocks = guard.setdefault("audioCalls", {})
        if now >= clocks.get(kind, 0):
            clocks[kind] = now + 12 + radio_delay(skills)
            w["messages"].append(
                dict(
                    team="CT",
                    sender=guard["id"],
                    sight=cue,
                    due=now + radio_delay(skills),
                )
            )


def send_sector(w, actor, call):
    now = w["tick"]
    key = actor["id"] + ("/order" if call.get("feedback") else "")
    actor.setdefault("sectorCalls", {})[key] = call
    delay = radio_delay(world.match_player(w, actor)["skills"])
    w["messages"].append(
        dict(team="CT", sender=actor["id"], crossing=call, due=now + delay)
    )


def observe(w, players, space=None):
    now = w["tick"]
    for message in w["messages"][:]:
        if message["due"] > now:
            continue
        w["messages"].remove(message)
        for a in players:
            if a["team"] == message["team"] and a["id"] != message["sender"]:
                if "crossing" in message:
                    call = message["crossing"]
                    key = message["sender"] + ("/order" if call.get("feedback") else "")
                    prior = a.setdefault("sectorCalls", {}).get(key)
                    if not prior or prior["tick"] <= call["tick"]:
                        a["sectorCalls"][key] = call
                    continue
                if "pressure" in message:
                    call = message["pressure"]
                    a.setdefault("squadPressure",{})[message["sender"]] = call
                    # A nearby partner can cover the reported sector. The call
                    # contains the teammate’s position and an octant, not a target.
                    if dist(point(a),call["origin"]) < 35:
                        previous = a.get("pressureCall")
                        if not previous or call["tick"] > previous["tick"]:
                            a["pressureCall"] = call
                    continue
                if "friendlyUtility" in message:
                    a["friendlyUtility"] = [p for p in a.get("friendlyUtility",[]) if p["end"] >= now]
                    a["friendlyUtility"].append(message["friendlyUtility"])
                    continue
                if "blockedSite" in message:
                    a.setdefault("routeReports",{})[message["sender"]]=[message["blockedSite"],now]
                    continue
                if "device" in message:
                    a["seenDevice"] = message["device"]
                    a["heardSite"] = message["device"]["site"]
                    continue
                if "site" in message:
                    a["heardSite"] = message["site"]
                    continue
                sight = message["sight"]
                if sight["tick"] > a["knowledge"].get(sight["id"], {}).get("tick", -1):
                    source = (
                        sight["source"]
                        if sight["source"] in ("Граната", "Слух")
                        else "Радио"
                    )
                    delivered = dict(sight, source=source)
                    if space and a["team"] == "CT" and w.get("phase") == "live":
                        delivered["reporter"] = message["sender"]
                        plan = w["plans"]["CT"]
                        old = a["knowledge"].get(sight["id"], {})
                        if (
                            a["id"] == plan["captain"]
                            and source == "Радио"
                            and (
                                not old
                                or sight.get("carryingC4")
                                and not old.get("carryingC4")
                                or sight.get("groupSize", 1) > old.get("groupSize", 1)
                            )
                        ):
                            skill = world.match_player(w, a)["skills"]
                            sender = next(
                                (
                                    p
                                    for p in w["agents"]
                                    if p["id"] == message["sender"]
                                ),
                                None,
                            )
                            chemistry = (
                                w["domain"]["chemistry"].get(
                                    world.pair_key(sender["playerId"], a["playerId"]), 0
                                )
                                if sender
                                else 0
                            )
                            delay = (
                                1
                                + (
                                    400
                                    - skill["decisions"]
                                    - skill["coordination"]
                                    - skill["leadership"]
                                    - chemistry
                                )
                                // 55
                            )
                            plan["review"] = min(plan["review"], now + delay)
                    a["knowledge"][sight["id"]] = delivered
    smoke = [
        f for f in w["effects"] if f["kind"] == "Дым" and f["land"] <= now < f["end"]
    ]
    if space:
        opponents = {"CT": [], "T": []}
        for agent in players:
            opponents["CT" if agent["team"]=="T" else "T"].append(agent)
        pairs = []
        for a in players:
            if a["blind"]>now:
                continue
            x,y = a["x"],a["y"]
            dx,dy = cos(a["heading"]),sin(a["heading"])
            for b in opponents[a["team"]]:
                vx,vy = b["x"]-x,b["y"]-y
                dot = vx*dx+vy*dy
                if dot>=0 and 4*dot*dot>=vx*vx+vy*vy:
                    pairs.append((a,b))
        visible = space.visible_pairs(pairs)
        observed_by = {a["id"]:[] for a in players}
        for a,b in pairs:
            if (a["id"],b["id"]) in visible and not any(
                near_line(a,b,fog,fog["radius"]) for fog in smoke
            ):
                observed_by[a["id"]].append(b)
    for a in players:
        previous = a["visible"]
        a["visible"] = []
        a["knowledge"] = {
            k: v for k, v in a["knowledge"].items() if now - v["tick"] < 75
        }
        if a["blind"] > now:
            continue
        observed = observed_by[a["id"]] if space else [
            b for b in players if b["team"]!=a["team"] and engine.sees(a,b)
            and not any(near_line(a,b,fog,fog["radius"]) for fog in smoke)
        ]
        for b in observed:
            sight = dict(id=b["id"], **at(point(b)), tick=now, source="Зрение")
            prior = a["knowledge"].get(b["id"])
            if prior and b["id"] in previous and prior["tick"] == now - 1:
                sight["speed"] = distance(prior, sight)
            if space:
                nearby = [p for p in observed if distance(p, b) <= 28 and abs(p["z"] - b["z"]) < 8]
                cs2_intel.observe_contact(sight, b, prior, nearby, "speed" in sight)
                cs2_intel.learn_motion(a,sight,prior)
                action = w.get("action")
                if action and action["player"] == b["id"]:
                    sight["interaction"] = action["kind"]
                if b["team"] == "T" and w.get("bomb", {}).get("carrier") == b["id"]:
                    sight["carryingC4"] = True
            a["visible"].append(b["id"])
            a["knowledge"][b["id"]] = sight
            changed = space and prior and (prior.get("weapon") != sight["weapon"]
                                              or prior.get("carryingC4") != sight.get("carryingC4")
                                              or prior.get("interaction") != sight.get("interaction")
                                              or prior.get("groupSize") != sight["groupSize"]
                                              or ("direction" in sight and "direction" not in prior))
            if b["id"] not in previous or now % 10 == 0 or changed:
                w["messages"].append(
                    dict(
                        team=a["team"],
                        sender=a["id"],
                        sight=sight,
                        due=now + radio_delay(world.match_player(w, a)["skills"]),
                    )
                )
            if b["id"] not in previous:
                event = emit(
                    w,
                    "contact",
                    f"{a['name']} заметил {b['name']}",
                    a["team"],
                    player=a["id"],
                    target=b["id"],
                    x=b["x"],
                    y=b["y"],
                )
                a["evidence"] = dict(
                    id=event["id"],
                    round=w["round"],
                    text=f"В раунде {w['round']} я видел {b['name']} в секторе {b['x'] // 40 + 1}. Стоит перепроверить подход.",
                )


        if space and a["team"] == "CT" and w.get("phase") == "live":
            lost = [
                a["knowledge"][pid]
                for pid in previous
                if pid not in a["visible"] and pid in a["knowledge"]
            ]
            if lost:
                report = max(lost, key=lambda r: r["tick"])
                site = space.reported_site(xyz(report))
                if site:
                    send_sector(
                        w,
                        a,
                        dict(
                            state="lost",
                            point=list(xyz(report)),
                            site=site,
                            lane=w["plans"]["CT"]["lane"],
                            tick=now,
                        ),
                    )

    if space and w.get("phase")=="live" and now%5==0 and (plan:=w.get("plans",{}).get("CT")) and plan.get("orders",{}).get("slots"):
        squad = [p for p in players if p["team"]=="CT"]
        observer = next((p for p in squad if p["slot"]==(now//5)%5),None)
        if observer:
            call = cs2_play.cs2_defense.report_crossing(space,observer,squad,plan,smoke,now)
            if call:
                send_sector(w,observer,call)


def captain(w, squad, space=None):
    leader = min(squad, key=lambda a: (not a["appointed"], a["slot"]))
    plan = w["plans"][leader["team"]]
    now = w["tick"]
    s = world.match_player(w, leader)["skills"]
    if plan["captain"] != leader["id"]:
        plan.update(captain=leader["id"], review=now + (100 - s["leadership"]) // 4)
        emit(
            w,
            "captain",
            f"{leader['name']} принимает колл",
            leader["team"],
            player=leader["id"],
        )
    if space:
        reported = plan.setdefault("economicSightings", {})
        for report in leader["knowledge"].values():
            weapon = report.get("weapon")
            previous = reported.get(report["id"])
            if weapon and (not previous or previous["tick"] < report["tick"]):
                reported[report["id"]] = dict(weapon=weapon,tick=report["tick"])
    if now < plan["review"]:
        return
    plan["review"] = now + 18 + (100 - s["calling"]) // 2
    if space and leader["team"] == "CT":
        plan["review"] = now + 5 + (200 - s["calling"] - s["communication"]) // 8
        if w["phase"] == "live":
            cs2_play.direct_defense(space, w, plan, squad, leader)
            return
    # Only the acting captain's timestamped reports are available here.
    contacts = [
        p
        for p in leader["knowledge"].values()
        if p["source"] not in ("Слух","Граната") and now - p["tick"] <= (74 if space else 74 - s["game_reading"] // 2)
    ]
    if space:
        counts = cs2_intel.pressure(space, leader["knowledge"].values(), now)
    else:
        counts = {site: sum(distance(at(POSITIONS[site][0]), p) < 80 for p in contacts)
                  for site in POSITIONS}
    if space and leader["team"] == "T":
        cs2_play.release_probe(space, plan, squad, contacts, now)
    site = plan["site"]
    obstructed=space and any(s==site and now-t<60 for s,t in leader.get("routeReports",{}).values())
    if space and leader["team"] == "T" and not plan.get("board") and not plan["rotated"] and w["phase"] == "live":
        order = plan["orders"]["slots"][leader["slot"]]
        # With little utility a reported sniper covering our approach can warrant a new route.
        if not any("Дым" in mate["utility"] for mate in squad) and cs2_intel.sniper_lane(space, contacts, order, now):
            obstructed = True
    if (
        leader["team"] == "T"
        and (obstructed or (counts[site] >= (min(2.5, max(1.5, len(squad) - 0.5)) if space else 3)
             and (not space or counts[site] > counts["B" if site=="A" else "A"])))
        and now - plan["start"] >= (100 - s["adaptability"]) // 2
        and not plan["rotated"]
        and w["deadline"] - now > 250
        and w["phase"] == "live"
    ):
        plan.update(site="B" if site == "A" else "A", rotated=True)
        if space:
            members = [a for a in w["agents"] if a["team"]=="T"]
            plan["lane"] = 1 - plan["lane"]
            plan["orders"] = space.orders("T",plan["site"],members,plan["lane"],plan["style"])
            for a in squad:
                a["waypoint"]=0
        else:
            plan["orders"] = role_orders("T", plan["site"])
        emit(
            w,
            "rotate",
            (f"{leader['name']} меняет направление после донесения · {plan['site']}" if space else
             f"{leader['name']} меняет направление после трёх контактов · {plan['site']}"),
            "T",
            player=leader["id"],
            contacts=[p["id"] for p in contacts],
        )
    if leader["team"] == "CT":
        if not space and counts["A"] != counts["B"] and max(counts.values()) >= 2:
            plan["reinforce"] = max(counts, key=counts.get)
        if w["phase"] == "planted":
            # The announcement is public. Site identification travels with the beep.
            heard = leader["heardSite"]
            if heard:
                plan["reinforce"] = heard
                if space and "retake" not in plan:
                    from . import cs2_retake
                    cs2_retake.assemble(space, w, squad, leader, heard)


@lru_cache(maxsize=4096)
def path_between(start, goal):
    return tuple(tuple(p) for p in engine.route(start, goal))


@lru_cache(maxsize=128)
def fire_detour(start, goal, sources):
    blocked = {
        cell
        for cell in engine._FLOOR
        if any(
            hypot(engine._center(cell)[0] - x, engine._center(cell)[1] - y) < radius
            for x, y, radius in sources
        )
    }
    try:
        return engine.route(start, goal, blocked)
    except ValueError:
        return []


def walk(a, goal, pace, hazards, *, allow_detour=False):
    cell = engine._cell(a["x"], a["y"])
    dest = engine._cell(*goal)
    # Replan at cell centres; preserve the current edge when redirected mid-step.
    if a["dest"] != list(dest) or not a["path"]:
        centre = engine._center(cell)
        path = list(path_between(cell, dest))
        if (
            centre != (a["x"], a["y"])
            and path
            and not engine.clear_line(a["x"], a["y"], *path[0])
        ):
            path.insert(0, centre)
        if not path and centre != (a["x"], a["y"]):
            path = [centre]
        a["path"], a["dest"] = path, list(dest)
    if not a["path"]:
        return False
    x, y = a["path"][0]
    if any(
        distance(at((x, y)), f) < f["radius"] and distance(a, f) >= f["radius"]
        for f in hazards
    ):
        detour = (
            fire_detour(
                cell, dest, tuple((f["x"], f["y"], f["radius"]) for f in hazards)
            )
            if allow_detour
            else []
        )
        if not detour:
            a["status"] = "Пережидает огонь за укрытием"
            return False
        centre = engine._center(cell)
        # Return to this cell centre before taking a different edge mid-stride.
        a["path"] = ([centre] if centre != (a["x"], a["y"]) else []) + list(detour)
        x, y = a["path"][0]
        a["status"] = "Обходит огонь"
    dx, dy = x - a["x"], y - a["y"]
    a["heading"] = atan2(dy, dx)
    a["x"] = round(a["x"] + max(-pace, min(pace, dx)), 3)
    a["y"] = round(a["y"] + max(-pace, min(pace, dy)), 3)
    if (a["x"], a["y"]) == (x, y):
        a["path"].pop(0)
    return True


@lru_cache(maxsize=96)
def escape_routes(x, y):
    """Shortest walkable exits from every cell for this known plant location."""
    floor = engine._FLOOR
    exits = [
        cell
        for cell in floor
        if hypot(engine._center(cell)[0] - x, engine._center(cell)[1] - y)
        >= BLAST_RADIUS + engine.CELL
    ]
    queue = deque(sorted(exits))
    routes = {cell: (0, engine._center(cell)) for cell in exits}
    while queue:
        cell = queue.popleft()
        length, goal = routes[cell]
        for other in engine._NEIGHBORS[cell]:
            if other not in routes:
                routes[other] = (length + engine.CELL, goal)
                queue.append(other)
    return routes


def postplant_exit(w, a, allies, bomb):
    """Only public fuse, own inventory, allied radio and recent observations."""
    if w.get("space"):
        return cs2_play.exit_goal(w["space"],w,a,allies,bomb)
    site = (bomb and bomb["site"]) or a["heardSite"] or w["plan"]["reinforce"]
    if not site:
        return None
    position = (bomb["x"], bomb["y"]) if bomb and "x" in bomb else POSITIONS[site][0]
    cell = engine._cell(a["x"], a["y"])
    speed = 2 * perf.move_speed(w["player"])
    length, goal = escape_routes(*position)[cell]
    # walk() rounds each simulation step and may recenter before turning.
    escape_ticks = length / engine.CELL * ceil(engine.CELL / speed) + 5
    remaining = w["deadline"] - w["tick"]
    contacts = [
        p
        for p in a["knowledge"].values()
        if p["source"] != "Слух"
        and w["tick"] - p["tick"] <= 30
        and distance(p, at(position)) < 75
    ]
    value = equipment_value(a)
    reserve = min(
        24, value // 450 + (100 - a["hp"]) // 10 + (6 if a["cash"] < 1800 else 0)
    )
    if a["team"] == "CT":
        if w["action"]:
            return None
        route = path_between(cell, engine._cell(*position))
        approach = max(0, (len(route) * engine.CELL - 8) / speed)
        use = RULES["kitDefuse"] if a["kit"] else RULES["defuse"]
        # At the known device an immediately feasible defuse takes precedence.
        if bomb and distance(a, bomb) <= 8 and remaining > use:
            return None
        opposition = max(0, len(contacts) - len(allies) + 1)
        margin = perf.retake_margin(w["player"]["skills"], approach * speed, value)
        if remaining > approach + use + max(0, opposition * (12 + reserve) + margin):
            return None
    else:
        # An observed retake prolongs cover; silence is not evidence of a CT save.
        if remaining > escape_ticks + (0 if contacts else reserve):
            return None
    return goal


def act(w, a, allies, bomb, visible_fire):
    """Choose an intention using allies, own sensory memory and known objective."""
    now = w["tick"]
    plan = w["plan"]
    player = w["player"]
    s = player["skills"]
    side, slot = a["team"], a["slot"]

    if w.get("space") and a.get("lastBlockedTick") != now - 1:
        a["blockedTicks"] = 0

    def travel(agent, goal, pace, fire, **options):
        if w.get("space"):
            moved = w["space"].walk(agent,goal,pace*perf.move_speed(player),fire)
            if agent["blockedTicks"]:
                agent["lastBlockedTick"] = now
                agent["blockedGoal"] = list(goal)
            return moved
        return walk(agent, goal, pace * perf.move_speed(player), fire, **options)

    site = plan["site"]
    alive = sorted(allies, key=lambda p: p["slot"])
    visible = [a["knowledge"][i] for i in a["visible"]]
    if len(visible) > 1:
        # Focus fire uses teammates' current targets only when directly nearby.
        focus = {
            mate["target"]
            for mate in allies
            if mate is not a
            and distance(a, mate) < 25
            and clear(w.get("space"),a,mate)
        }
        contact = min(
            visible,
            key=lambda p: (not p.get("interaction"),cs2_intel.duel_priority(a,p,focus,s)) if w.get("space") else (
                distance(a, p) - (s["coordination"] / 4 if p["id"] in focus else 0)
            ),
        )
    else:
        contact = visible[0] if visible else None
    match_inventory.switch_if_empty(a)
    spec = WEAPONS[a["weapon"]]
    if a["reloadAt"] and now >= a["reloadAt"]:
        count = min(spec.mag - a["ammo"], a["reserve"])
        a.update(ammo=a["ammo"] + count, reserve=a["reserve"] - count, reloadAt=0)
    if not a["ammo"] and a["reserve"] and not a["reloadAt"]:
        a["reloadAt"] = now + spec.reload
    if (
        contact
        and w["action"]
        and w["action"]["player"] == a["id"]
        and w["action"]["end"] - now <= perf.commit_ticks(s, player["morale"])
    ):
        contact = None
    if w["phase"] == "planted" and not (
        w["action"] and w["action"]["player"] == a["id"]
    ):
        if side == "CT" and w.get("space") and w["action"] and bomb and distance(a,bomb) < 45:
            a.pop("saving", None)
        exit_goal = a.get("saving") or postplant_exit(w, a, allies, bomb)
        if exit_goal:
            a["saving"] = list(exit_goal)
            a["status"] = "Отходит от C4" if side == "T" else "Сохраняет оружие"
            if travel(a, exit_goal, 2, visible_fire, allow_detour=True):
                return ("move", None)
            if not contact:
                return ("hold", None)
    if w.get("space") and not w["action"] and w["deadline"]-now > 35:
        retreat = cs2_play.seek_cover(w["space"],a,contact,allies,s,now,visible_fire,travel,plan)
        if retreat:
            return retreat
    if contact:
        old_heading = a["heading"]
        a["heading"] = atan2(contact["y"] - a["y"], contact["x"] - a["x"])
        if a["target"] != contact["id"]:
            angle = (a["heading"] - old_heading + pi) % (2 * pi) - pi
            previous = a["previousTarget"]
            delay = perf.acquisition(
                s,
                angle,
                previous is not None and previous != contact["id"],
                now - a["lastMove"] <= 2,
                side == "T" and a["playingRole"] == "entry" and previous is None,
                contact["id"] == a["tradeTarget"] and now <= a["tradeUntil"],
                len(alive) == 1,
            )
            a.update(
                target=contact["id"],
                previousTarget=contact["id"],
                ready=max(a["ready"], now + delay),
            )
        a["observedSpeed"] = contact.get("speed", 0)
        a["status"] = "Перезаряжается" if a["reloadAt"] else "Держит контакт"
        grenade = None
        if w.get("space"):
            grenade = cs2_play.cs2_defense.contact_grenade(w["space"], a, contact, visible, allies,
                                                            player, plan, now, w["phase"])
            if grenade:
                return "throw", dict(contact,utility=grenade)
        elif a["utility"] and now >= a["throwAt"] and distance(a, contact) > 18:
            grenade = a["utility"][0]
        if grenade:
            clearance = UTILITY[grenade][0] * s["decisions"] / 100
            unsafe = grenade in ("HE", "Огонь", "Свет") and any(
                distance(mate, contact) < clearance for mate in allies
            )
            # Throwing occupies the hands for five ticks. Close targets can be
            # engaged sooner with a loaded weapon, especially a lethal first shot.
            shot_soon = a["ammo"] and not a["reloadAt"] and a["ready"] < now + 5
            shot_range = 18 + s["decisions"] * min(0.6, spec.damage / 75)
            if not unsafe and not (shot_soon and distance(a, contact) <= shot_range):
                return ("throw", dict(contact,utility=grenade) if w.get("space") else contact)
        if not a["reloadAt"] and a["ammo"] and now >= a["ready"]:
            return ("shoot", contact)
        return ("hold", None)
    if w.get("space") and a["target"] and a["ammo"] > spec.mag//2 and not a["reloadAt"]:
        seen=a["knowledge"].get(a["target"])
        if seen and now>=a["ready"] and a["blind"]<=now and not w["action"]:
            target = cs2_play.cs2_defense.last_burst(w["space"],a,seen,allies,player,now)
            if target:
                a["status"]="Продолжает очередь по последнему контакту"
                return "shoot", target
    a["target"] = None
    if w["action"] and w["action"]["player"] == a["id"]:
        return ("objective", None)
    board = plan.get("board")
    recover = side == "T" and bomb and not bomb["carrier"] and not bomb["site"]
    if w.get("space"):
        assignment = w.get("recovery")
        rescuer = recover and assignment and assignment["player"] == a["id"]
    else:
        rescuer = recover and min(alive, key=lambda p: (distance(p, bomb), p["id"])) is a
    responding = cs2_play.cs2_defense.relief(plan, a) if w.get("space") else (plan["reinforce"] and slot in (1, 4))
    reinforce = side == "CT" and (w["phase"] == "planted" or responding)
    if (
        not rescuer
        and (not board or not w.get("space"))
        and not reinforce
        and len(alive) < 5
        and a["playingRole"] == "support"
        and (side == "T" or not w.get("space"))
        and w["phase"] == "live"
        and not (bomb and bomb.get("carrier") == a["id"])
    ):
        partner = next(
            (mate for mate in alive if mate["id"] == plan["captain"]), alive[0]
        )
        if w.get("space"):
            partner = cs2_play.cs2_defense.support_partner(plan,a,alive,w["chemistry"],s) or a
        pair = w["chemistry"].get(world.pair_key(a["playerId"], partner["playerId"]), 0)
        if distance(a, partner) > 75 - s["support"] * 0.45 - pair * 0.15:
            target = cs2_play.rendezvous(w["space"],a,partner,now) if w.get("space") else point(partner)
            if target is not None:
                a["status"] = "Поддерживает партнёра на выходе" if w.get("space") else "К капитану после потери союзника"
                moved = travel(a, target, 2, visible_fire)
                if moved or not w.get("space") or not a.get("blockedTicks"):
                    return ("move" if moved else "hold", None)
    if (
        board
        and w["phase"] != "planted"
        and not plan["rotated"]
        and not rescuer
        and not reinforce
    ):
        if now < a["stepReady"]:
            a["status"] = "Готовит следующий шаг"
            return ("hold", None)
        before = a["stepIndex"]
        intent = tactic_execution.execute(
            a, board["slots"][slot], now, bomb, visible_fire, travel, w.get("space")
        )
        if a["stepIndex"] != before:
            mastery = player["roleMastery"].get(a["playingRole"], 0)
            a["stepReady"] = (
                now + 1 + (100 - s["execution"]) // 20 + (100 - mastery) // 35
            )
        if intent:
            return intent
    if w.get("space"):
        return cs2_play.spatial_intent(w["space"],w,a,allies,bomb,visible_fire,travel)
    if w["phase"] == "planted":
        if side == "CT":
            site = (
                a["heardSite"]
                or plan["reinforce"]
                or (site if slot % 2 else ("B" if site == "A" else "A"))
            )
            goal = POSITIONS[site][0]
            teammate_using = w["action"] and w["action"]["player"] != a["id"]
            if bomb and distance(a, bomb) <= 8 and not teammate_using:
                return ("defuse", None)
            if bomb:
                goal = (
                    POSITIONS[site][slot] if teammate_using else (bomb["x"], bomb["y"])
                )
            a["status"] = "Идёт на ретейк"
        else:
            site = bomb["site"]
            goal = POSITIONS[site][slot]
            a["status"] = "Прикрывает C4"
    elif side == "T":
        staging = plan["style"] == "Сбор" and now - plan["start"] < perf.staging_ticks(
            s, any(distance(a, mate) > 50 for mate in allies)
        )
        order = plan["orders"]["slots"][slot]
        approach = a["approached"] != site
        if approach and distance(a, at(order["approach"])) < 6:
            a["approached"] = site
            approach = False
        goal = (
            order["approach"]
            if approach
            else order["stage"] if staging else order["hold"]
        )
        if (
            approach
            and a["playingRole"] == "lurker"
            and s["lurking"] + player["mapKnowledge"].get("depo", 0) >= 145
        ):
            goal = plan["orders"]["slots"][3]["approach"]
            if distance(a, at(goal)) < 6:
                a["approached"] = site
        a["status"] = "Собирается с командой" if staging else f"Выход на {site}"
        if bomb and not bomb["carrier"]:
            collector = min(alive, key=lambda p: (distance(p, bomb), p["id"]))
            if collector is a:
                goal = (bomb["x"], bomb["y"])
                a["status"] = "Подбирает C4"
        elif bomb and bomb["carrier"] == a["id"]:
            if not staging and not approach:
                goal = POSITIONS[site][0]
            for zone in MAP["zones"]:
                if (
                    zone["x"] <= a["x"] < zone["x"] + zone["w"]
                    and zone["y"] <= a["y"] < zone["y"] + zone["h"]
                ):
                    return ("plant", zone["name"])
    else:
        site = "A" if slot in (0, 2) else "B"
        if slot == 4 or (slot == 1 and plan["reinforce"]):
            site = plan["reinforce"] or plan["site"]
        goal = POSITIONS[site][slot]
        a["status"] = f"Занимает {site}"
    memory = max(a["knowledge"].values(), key=lambda m: m["tick"], default=None)
    if (
        memory
        and now - memory["tick"] < perf.pursuit_window(s, memory["source"] == "Слух")
        and a["status"] not in ("Сохраняет оружие", "Подбирает C4")
        # A disciplined holder stays within reach of the assigned objective.
        and (side != "CT" or distance(at(goal), memory) <= 145 - s["discipline"])
    ):
        if side == "CT" or (bomb and a["id"] != bomb["carrier"]):
            goal = memory["x"], memory["y"]
            a["status"] = "Проверяет сообщение о контакте"
    if travel(
        a,
        goal,
        2 if plan["style"] == "Быстро" or w["phase"] == "planted" else 1,
        visible_fire,
    ):
        return ("move", None)
    if a["status"].startswith(("Занимает", "Выход")):
        a["status"] = f"Контролирует {site}"
    # Orient toward the approach corridor when holding a position on site.
    base = pi if side == "CT" else 0
    if side == "T" and w["phase"] == "planted":
        anchor = POSITIONS[site][0]
        outward = atan2(a["y"] - anchor[1], a["x"] - anchor[0])
        base += ((outward - base + pi) % (2 * pi) - pi) * s["postplant"] / 100
    elif side == "CT":
        approach_xy = plan["orders"]["slots"][slot]["approach"]
        lane = atan2(approach_xy[1] - a["y"], approach_xy[0] - a["x"])
        base += ((lane - base + pi) % (2 * pi) - pi) * s["positioning"] / 100
    a["heading"] = base + 1.6 * sin((now + slot * 12) / (24 - s["map_control"] / 8))
    return ("hold", None)


def shoot(w, a, sight, b, space=None):
    """Commit the shot toward the observed point, then resolve the collision."""

    spec = WEAPONS[a["weapon"]]
    gap = w["tick"] - a["lastShot"]
    burst = 0 if gap > 4 else min(4, a["burst"] + 1)
    dist = distance(a, sight)
    player = world.match_player(w, a)
    accuracy = perf.accuracy(player, a, spec, dist, burst, w["tick"])
    a.update(
        ammo=a["ammo"] - 1,
        lastShot=w["tick"],
        burst=burst,
        ready=w["tick"]
        + spec.interval
        + (1 + (100 - player["skills"]["burst_control"]) // 13 if burst >= 3 else 0),
    )
    event = emit(
        w,
        "shot",
        f"{a['name']} · {a['weapon']}",
        a["team"],
        player=a["id"],
        target=sight.get("id"),
        x=a["x"],
        y=a["y"],
        tx=sight["x"],
        ty=sight["y"],
        **({"z":a["z"],"tz":sight["z"]} if space else {}),
        accuracy=accuracy,
        burst=burst,
    )
    w["traces"].append(event)
    intersects = (
        b is not None and b["hp"]
        and near_line(a, sight, b, 3)
        and (space or engine.clear_line(a["x"], a["y"], b["x"], b["y"]))
    )
    transmission = space.shot_transmission(xyz(a),xyz(b),spec.penetration) if space and intersects else 1.
    if not transmission:
        return
    for _ in range(spec.pellets):
        if (engine._draw(a) >> 16) % 100 >= accuracy or not intersects or not b["hp"]:
            continue
        location = (engine._draw(a) >> 16) % 100
        group = (
            "head"
            if location < 24
            else (
                "chest"
                if location < 62
                else "stomach" if location < 78 else "arm" if location < 89 else "leg"
            )
        )
        impact(w, a, b, transmission * spec.damage * spec.falloff ** (dist / 100), a["weapon"], group)


def throw(w, a, target, space=None):
    name = target.get("utility") or a["utility"][0]
    a["utility"].remove(name)
    now = w["tick"]
    radius, duration = UTILITY[name]
    flight = max(3, round(distance(a, target) / 7))
    mastery = world.match_player(w, a)["skills"][perf.GRENADE_SKILL[name]]
    x, y = perf.grenade_landing(a, target, mastery, engine._draw(a) >> 16)
    if space:
        x,y,z,trajectory=space.grenade(xyz(a),(x,y,target["z"]),flight)
        flight=len(trajectory)-1
    elif not engine.clear_line(a["x"], a["y"], x, y):
        x, y = a["x"], a["y"]
    effect = dict(
        kind=name,
        player=a["id"],
        team=a["team"],
        x=x,
        y=y,
        sx=a["x"],
        sy=a["y"],
        start=now,
        land=now + flight,
        end=now + flight + duration,
        radius=radius,
    )
    if space:
        effect.update(z=z, sz=a["z"], trajectory=[list(point) for point in trajectory])
    if space and name in ("Дым","Огонь"):
        # Teammates call their intended target. A missed/bounced grenade can be misidentified.
        cue=dict(**at(point(target)),end=now+flight+10)
        w["messages"].append(dict(team=a["team"],sender=a["id"],friendlyUtility=cue,
                                  due=now+radio_delay(world.match_player(w,a)["skills"])))
    if target.get("openingZone"):
        job = w["plans"]["CT"]["opening"]["jobs"][a["id"]]
        job["throw"]["land"] = effect["land"]
        effect.update(openingZone=job["zone"], supported=job["throw"]["forPlayer"])
    w["effects"].append(effect)
    w["recentEffects"].append(effect)
    emit(
        w,
        "throw",
        f"{a['name']} · {name}",
        a["team"],
        **{k: v for k, v in effect.items() if k not in ("team", "kind")},
        utility=name,
        **({"purpose": target["purpose"]} if target.get("purpose") else {}),
    )
    a.update(throwAt=now + 45, ready=now + THROW_RECOVERY, status="Бросает гранату")


def apply_effects(w, ids, space=None):
    now = w["tick"]
    w["recentEffects"] = [f for f in w["recentEffects"] if f["end"] + 42 > now]
    w["effects"] = [f for f in w["effects"] if f["end"] > now]
    for f in w["effects"]:
        if space and w.get("phase") == "live" and f["team"] == "T":
            if (
                now == f["land"]
                or f["kind"] == "Ложная"
                and now > f["land"]
                and (now - f["land"]) % 10 == 0
            ):
                kind = "Выстрел" if f["kind"] == "Ложная" else "Граната"
                heard_action(w, space, f, ids.values(), kind, 108 if f["kind"] in ("HE","Свет","Ложная") else 54)
        if space and f["kind"] in ("Дым","Огонь") and now==f["land"]:
            for a in ids.values():
                if (a["hp"] and a["id"]!=f["player"] and a["blind"]<=now and distance(a,f)<58
                    and in_view(a,f) and space.clear(a,f)):
                    if any(call["end"] >= now and distance(call, f) < 10 for call in a.get("friendlyUtility", [])):
                        continue
                    # A visible screen identifies a threatened angle, not a thrower or a head count.
                    pos=sound_position(space,f)
                    a["knowledge"]["Граната"]=dict(id="Граната",**pos,tick=now,source="Граната")
                    w["messages"].append(dict(team=a["team"],sender=a["id"],sight=a["knowledge"]["Граната"],
                                              due=now+radio_delay(world.match_player(w,a)["skills"])))
        if now < f["land"] or f["kind"] == "Дым":
            continue
        if f["kind"] == "Ложная":
            if (now - f["land"]) % 10 == 0:
                sector = sound_position(space,f)
                for a in ids.values():
                    if (
                        a["hp"]
                        and a["team"] != f["team"]
                        and not (space and a["team"] == "CT" and w.get("phase") == "live")
                        and distance(f, a) < f["radius"]
                    ):
                        a["knowledge"]["Шум"] = dict(
                            id="Шум", **sector, tick=now, source="Слух"
                        )
            continue
        if f["kind"] == "Огонь" and (now - f["land"]) % 5:
            continue
        for a in ids.values():
            dist = distance(f, a)
            if (
                not a["hp"]
                or dist > f["radius"]
                or not clear(space,f,a)
            ):
                continue
            if f["kind"] == "Свет":
                duration = round(7 + 19 * (1 - dist / f["radius"]))
                a["blind"] = max(a["blind"], now + duration)
                emit(
                    w,
                    "flash",
                    f"{a['name']} ослеплён",
                    a["team"],
                    player=a["id"],
                    duration=duration,
                )
            else:
                amount = (
                    min(32, 8 + 4 * ((now - f["land"]) // 5))
                    if f["kind"] == "Огонь"
                    else max(0, round(98 * (1 - dist / f["radius"])))
                )
                impact(
                    w,
                    ids[f["player"]],
                    a,
                    amount,
                    f["kind"],
                    "fire" if f["kind"] == "Огонь" else "blast",
                )
