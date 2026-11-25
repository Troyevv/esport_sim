"""Map-dependent choices for the shared BO1 agents, using squad observations."""

from math import atan2, dist, sin
from .cs2_maps import UNIT, xyz
from . import match_performance as perf
from .match_rules import RULES, equipment_value


def opening(space, w, squad, captain, player, buy, site, style, call):
    from . import engine

    knowledge = player["mapKnowledge"].get(space.name.removeprefix("de_"), 0)
    lane = (engine._draw(captain) >> 16) % 2
    record = w.get("siteHistory", {}).get(captain["teamId"], [])
    if not call and captain["team"] == "T" and record:
        value = {
            s: sum(
                (1 if won else -1) / (age + 1)
                for age, (planted, won) in enumerate(reversed(record))
                if planted == s
            )
            for s in ("A", "B")
        }
        if (
            value[site] < value["B" if site == "A" else "A"]
            and player["skills"]["calling"] + knowledge
            > (engine._draw(captain) >> 16) % 200
        ):
            site = "B" if site == "A" else "A"
    if captain["team"] == "T" and call not in ("Ускориться", "Выход A", "Выход B"):
        if buy in ("Эко", "Форс"):
            # A shorter approach keeps teammates with pistols close enough to trade.
            area = captain["navArea"]
            options = [
                space.approach(site, j).costs.get(area, float("inf")) for j in range(2)
            ]
            lane = min(range(2), key=options.__getitem__)
            style = "Групповой выход"
        elif knowledge + player["skills"]["map_control"] >= 115 and style == "Сбор":
            style = "Контроль карты"
    return site, style, lane


def utility_buy(actor, squad, plan, skills):
    """Reserve grenades for the current call and complement teammates' equipment."""
    role = actor["playingRole"]
    if actor["team"] == "CT":
        preferred = ["Огонь", "Дым"] if role != "support" else ["Свет", "Дым"]
    elif role == "entry" or plan["style"] == "Групповой выход":
        preferred = ["Свет", "Дым"]
    elif role in ("support", "awper"):
        preferred = ["Дым", "Свет"]
    elif role == "lurker" and plan["style"] == "Контроль карты":
        preferred = ["Дым", "Ложная"]
    else:
        preferred = ["HE", "Свет"]
    counts = {g: sum(g in p["utility"] for p in squad) for g in perf.GRENADE_SKILL}
    options = list(dict.fromkeys(preferred + ["Дым", "Свет", "HE", "Огонь"]))
    return sorted(
        options,
        key=lambda g: (
            counts[g],
            g not in preferred,
            -skills[perf.GRENADE_SKILL[g]],
            options.index(g),
        ),
    )


def contact_utility(actor, opponents, allies, contact):
    # Use what the squad bought for the local situation. A decoy belongs
    # on the fake approach, not in a duel against a visible enemy.
    injured = actor["hp"] < 45
    under_fire = any(p is not actor and p["target"] == contact["id"] for p in allies)
    if injured or (actor["reloadAt"] and not under_fire):
        preferred = ["Дым", "Свет"]
    elif len(opponents) > 1:
        preferred = ["HE", "Огонь", "Свет"]
    elif under_fire:
        preferred = ["Свет", "HE"]
    else:
        preferred = ["Огонь", "HE", "Свет"]
    return next((g for g in preferred if g in actor["utility"]), None)


def assign_backup(space, plan, squad, site, pressure):
    """Send an available off-site player to an angle that complements the anchors."""
    if not site:
        plan.pop("backup", None)
        return
    slots = plan["orders"]["slots"]
    other = [a for a in squad if slots[a["slot"]]["site"] != site]
    if not other or (len(other) == 1 and pressure < 3):
        plan.pop("backup", None)
        return
    current = plan.get("backup")
    if (
        current
        and current["site"] == site
        and any(p["id"] == current["id"] for p in other)
    ):
        return
    guards = [slots[p["slot"]] for p in squad if slots[p["slot"]]["site"] == site]
    candidates = list(space.holds[site])
    if not candidates:
        candidates = [(i, space.centers[i]) for i in space.plants[site]]
    routes = []
    for actor in other:
        pos = xyz(actor)
        for area, target in candidates:
            if any(dist(target, guard["hold"]) < 6 for guard in guards):
                continue
            route = space.route(actor["navArea"], area)
            if route is not None:
                routes.append((len(route), dist(pos, target), actor["slot"], target))
    by_slot = {p["slot"]: p for p in other}
    for _, _, index, target in sorted(routes):
        actor = by_slot[index]
        if space._reachable(xyz(actor), [target]) is not None:
            visible = [
                q
                for q in space.ingress(site, plan["lane"])
                if dist(q, target) > 6 and space.hit(target, q, 1, 64) is None
            ]
            watch = visible[0] if visible else space.site_points[site]
            plan["backup"] = dict(
                id=actor["id"], site=site, hold=list(target), watch=list(watch)
            )
            return
    plan.pop("backup", None)


def rendezvous(space, actor, mate, now):
    # Rendezvous on a walkable surface within trading distance. The
    # teammate's exact feet can be between NAV surfaces on a ladder.
    pos, target = xyz(actor), xyz(mate)
    current = actor.get("rendezvous")
    if (
        current
        and current["mate"] == mate["id"]
        and now < current["review"]
        and dist(current["location"], target) < 14
        and not actor.get("blockedTicks")
    ):
        return current["point"]
    sectors = space.nearby_areas(target, 23)
    spots = [
        space.centers[i]
        for i in sectors
        if space.hit(space.centers[i], target, 1, 64) is None
    ]
    spots.sort(
        key=lambda q: (not 6 <= dist(q, target) <= 20, dist(pos, q) + dist(q, target))
    )
    goal = space._reachable(pos, [*spots, target])
    actor["rendezvous"] = dict(
        mate=mate["id"],
        review=now + 18,
        location=list(target),
        point=list(goal) if goal is not None else None,
    )
    return goal


def seek_cover(space, actor, contact, allies, skills, now, fire, travel):
    """Break sight or finish reloading using only this player's last contact."""
    if contact and (
        actor["reloadAt"] or actor["hp"] < 35 and len(actor["visible"]) > 1
    ):
        if now >= actor.get("coverReview", 0):
            threat = xyz(contact)
            pos = xyz(actor)
            spots = set(space.centers[i] for i in space.nearby_areas(pos, 15))
            spots.update(p for _, p in space.cover if dist(p, pos) <= 15)
            occupied = [xyz(p) for p in allies if p is not actor]
            choices = sorted(
                (
                    q
                    for q in spots
                    if 1 < dist(q, pos) and space.hit(q, threat, 1, 64) is not None
                ),
                key=lambda q: (any(dist(q, a) < 3 for a in occupied), dist(q, pos), q),
            )
            actor["coverReview"] = now + 5 + (100 - skills["positioning"]) // 12
            for q in choices:
                path = space.path(
                    actor["navArea"], pos, space.locate(q), q, frozenset()
                )
                if path is None:
                    continue
                prev = pos
                length = 0
                for node in path:
                    length += dist(prev, node[:3])
                    prev = node[:3]
                if length > 20:
                    continue
                actor["shelter"] = list(q)
                actor["coverUntil"] = max(actor["reloadAt"], now + 10)
                break
    if actor.get("shelter") and now < actor.get("coverUntil", 0):
        actor["status"] = "Уходит за укрытие"
        moved = travel(actor, actor["shelter"], 2, fire, allow_detour=True)
        if not moved and actor.get("blockedTicks"):
            actor.pop("shelter")
            return None
        return ("move" if moved else "hold"), None
    return None


def exit_goal(space, w, a, allies, bomb):
    site = (bomb and bomb["site"]) or a["heardSite"] or w["plan"]["reinforce"]
    if not site:
        return
    pos = xyz(bomb) if bomb else space.site_points[site]
    area = a["navArea"]
    routes = space.escape(pos)
    if area not in routes.costs:
        return
    remaining = w["deadline"] - w["tick"]
    speed = 2 * perf.move_speed(w["player"])
    threats = sum(
        p["source"] != "Слух" and w["tick"] - p["tick"] < 32 and dist(xyz(p), pos) < 60
        for p in a["knowledge"].values()
    )
    if a["team"] == "T":
        if (
            remaining
            > routes.costs[area] / UNIT / speed
            + 12
            + equipment_value(a) / 450
            - threats * 3
        ):
            return
    else:
        if w["action"]:
            return
        to = space.locate(pos)
        path = space.route(area, to)
        length = 0.0
        prev = xyz(a)
        if path is not None:
            for cross in path:
                exit, entry = space.to_sim(cross.leave), space.to_sim(cross.enter)
                length += dist(prev, exit) + dist(exit, entry)
                prev = entry
            length += dist(prev, pos)
        if (
            path is not None
            and remaining
            > max(0, length - 6) / speed
            + (RULES["kitDefuse"] if a["kit"] else RULES["defuse"])
            + max(0, threats - len(allies) + 1) * 8
        ):
            return
    _, goals = routes.route(area)
    chosen = space.centers[goals[-1]]
    position = xyz(a)
    if space.path(area, position, goals[-1], chosen, frozenset()) is not None:
        return chosen
    # The closest safe NAV centre can lie beyond a closed prop. Check
    # other safe surfaces before committing the player's remaining time.
    from .match_rules import BLAST_RADIUS

    safe = (
        space.centers[i]
        for i in space.nearby_areas(pos, BLAST_RADIUS * 1.8)
        if dist(space.centers[i], pos) > BLAST_RADIUS + 2
    )
    return space._reachable(position, sorted(safe, key=lambda q: dist(position, q)))


def rescue(space, squad, bomb):
    if bomb["carrier"] or bomb["site"]:
        bomb.pop("recovery", None)
        return None
    goal = list(xyz(bomb))
    assigned = bomb.get("recovery")
    if (
        assigned
        and assigned["drop"] == goal
        and any(
            a["id"] == assigned["player"] and a.get("blockedTicks", 0) < 20
            for a in squad
        )
    ):
        return assigned
    # The team knows its dropped C4. Compare accessible routes, including
    # floors and one-way links, before deciding who leaves cover to fetch it.
    choices = []
    for actor in squad:
        point = space.use_position(actor, bomb, 7)
        if point is None:
            continue
        pos = xyz(actor)
        path = space.path(
            actor["navArea"], pos, space.locate(point), point, frozenset()
        )
        if path is None:
            continue
        length = 0
        for node in path:
            length += dist(pos, node[:3])
            pos = node[:3]
        choices.append((length, actor["slot"], actor["id"], point))
    if not choices:
        return None
    _, _, who, point = min(choices)
    bomb["recovery"] = dict(player=who, drop=goal, point=list(point))
    return bomb["recovery"]


def hear_c4_use(space, players, device, tick):
    # The use sound is emitted once. It discloses neither the defuser's
    # identity, kit, duration, nor whether the CT later lets go of the device.
    objective = xyz(device)
    for actor in players:
        if not actor["hp"] or actor["team"] != "T":
            continue
        pos = xyz(actor)
        distance = dist(pos, objective)
        if distance < 26 or (
            distance < 55 and space.hit(pos, objective, 1, 64, 12) is None
        ):
            actor["heardUse"] = tick


def plant_guard(space, actor, allies, bomb, order, direct, check):
    pos, device, site = xyz(actor), xyz(bomb), bomb["site"]
    # The nearest living attacker watches the plant itself; other players
    # cover entries. A local use sound gives its hearer a reason to peek.
    cover = actor.get("plantCover")
    if (
        cover is not None
        and actor.get("watchDevice") == direct
        and actor.get("blockedTicks", 0) < 5
    ):
        return cover
    reserved = [
        p["plantCover"] for p in allies if p is not actor and p.get("plantCover")
    ]
    named = [p for _, p in space.holds[site]]
    choices = list(
        dict.fromkeys(
            [*named, *(space.centers[i] for i in space.nearby_areas(device, 36))]
        )
    )
    if order["site"] == site:
        choices.append(tuple(order["hold"]))
    if direct and space.hit(pos, device, 1, 64, 40) is None and dist(pos, device) > 5:
        choices.append(pos)
    choices.sort(
        key=lambda q: (
            direct and space.hit(q, device, 1, 64, 40) is not None,
            any(dist(q, r) < 5 for r in reserved),
            not check and q not in named and q != tuple(order["hold"]),
            dist(q, pos),
            q,
        )
    )
    chosen = space._reachable(pos, choices)
    actor["plantCover"] = list(chosen or pos)
    actor["watchDevice"] = direct
    return actor["plantCover"]


def search_site(space, actor, site, now):
    # A beep identifies the site, but a crate or raised platform can hide
    # the device from the site's centre. Clear the actual plant surfaces.
    pos = xyz(actor)
    center = space.site_points[site]
    state = actor.get("bombSearch")
    if not state or state["site"] != site:
        if dist(pos, center) > 25 and actor.get("blockedTicks", 0) < 5:
            return center
        state = actor["bombSearch"] = dict(site=site, seen=[], goal=None, next=0)
    if (
        state["goal"]
        and dist(pos, state["goal"]) > 2
        and actor.get("blockedTicks", 0) < 5
    ):
        return state["goal"]
    if now < state["next"]:
        return state["goal"] or pos
    state["next"] = now + 8
    candidates = space.plants[site]
    seen = set(state["seen"])
    for i in candidates:
        p = space.centers[i]
        if i not in seen and dist(pos, p) < 26 and space.hit(pos, p, 1, 64, 5) is None:
            seen.add(i)
    unsearched = [i for i in candidates if i not in seen]
    if not unsearched:
        # The centre of each polygon is only one sample of a legal plant.
        # Inspect it from a different position as the retake develops.
        seen.clear()
        unsearched = sorted(candidates)
        offset = (actor["slot"] + now // 8) % len(unsearched)
        unsearched = unsearched[offset:] + unsearched[:offset]
    else:
        unsearched.sort(key=lambda i: (dist(pos, space.centers[i]), i))
    state["seen"] = sorted(seen)
    goal = space._reachable(pos, (space.centers[i] for i in unsearched))
    state["goal"] = list(goal) if goal else None
    return goal or center


def spatial_intent(space, w, a, allies, bomb, fire, travel):
    now, plan = w["tick"], w["plan"]
    side, slot = a["team"], a["slot"]
    order = plan["orders"]["slots"][slot]
    site = plan["site"]
    pos = xyz(a)
    recent = [p for p in a["knowledge"].values() if now - p["tick"] < 35]
    latest = max(
        recent,
        key=lambda p: (
            p["id"] == a["tradeTarget"] and now <= a["tradeUntil"],
            p["tick"],
        ),
        default=None,
    )
    skill = w["player"]["skills"]
    familiarity = w["player"]["mapKnowledge"].get(space.name.removeprefix("de_"), 0)
    goal = order["hold"]
    watch = order["watch"]
    if w["phase"] == "planted":
        if side == "CT":
            site = a["heardSite"] or plan["reinforce"] or order["site"]
            if not a["heardSite"] and not bomb and not plan["reinforce"]:
                inspected = a.setdefault("inspectedSites", {})
                if dist(pos, space.site_points[site]) < 15:
                    inspected.setdefault(site, now)
                other_site = "B" if site == "A" else "A"
                if site in inspected and (
                    other_site not in inspected
                    or inspected[site] > inspected[other_site]
                ):
                    site = other_site
                if dist(pos, space.site_points[site]) < 15:
                    inspected[site] = now
            if bomb:
                goal = xyz(bomb)
            elif a["heardSite"]:
                goal = search_site(space, a, site, now)
            else:
                goal = space.site_points[site]
            other = w["action"] and w["action"]["player"] != a["id"]
            if bomb and dist(pos, goal) <= 6 and not other and space.clear(a, bomb):
                return "defuse", None
            if bomb and not other and a.get("blockedTicks", 0) >= 5:
                if a.get("useTarget") != list(goal):
                    a["useTarget"] = list(goal)
                    a["useFloor"] = space.use_position(a, bomb, 6)
            if bomb and a.get("useTarget") == list(goal) and a.get("useFloor"):
                goal = a["useFloor"]
            if other:
                # The defuser's teammates choose separate reachable angles,
                # including when the cover list contains another storey.
                who = w["action"]["player"]
                if a.get("coveredDefuser") != who:
                    center = next((xyz(p) for p in allies if p["id"] == who), pos)
                    reserved = [
                        p["coverPoint"]
                        for p in allies
                        if p is not a
                        and p.get("coveredDefuser") == who
                        and p.get("coverPoint")
                    ]
                    candidates = [p for _, p in space.holds[site]]
                    candidates.sort(
                        key=lambda p: (
                            any(dist(p, q) < 5 for q in [center, *reserved]),
                            abs(p[2] - center[2]),
                            dist(p, pos),
                        )
                    )
                    cover = space._reachable(pos, candidates)
                    a.update(coveredDefuser=who, coverPoint=list(cover or pos))
                goal = a["coverPoint"]
            else:
                a.pop("coveredDefuser", None)
            a["status"] = "Прикрывает разминирование" if other else "Идёт на ретейк"
        else:
            site = bomb["site"]
            check = now - a.get("heardUse", -1000) <= 34
            if not any(p["id"] == plan.get("deviceWatch") for p in allies):
                plan["deviceWatch"] = min(
                    allies, key=lambda p: (dist(xyz(p), xyz(bomb)), p["slot"])
                )["id"]
            goal = plant_guard(
                space,
                a,
                allies,
                bomb,
                order,
                check or a["id"] == plan["deviceWatch"],
                check,
            )
            if a["watchDevice"]:
                watch = xyz(bomb)
            a["status"] = "Проверяет C4 после звука" if check else "Прикрывает C4"
    elif side == "T":
        if (
            bomb
            and not bomb["carrier"]
            and w.get("recovery")
            and w["recovery"]["player"] == a["id"]
        ):
            goal = w["recovery"]["point"]
            a["status"] = "Подбирает C4"
        else:
            carrier = bomb and bomb["carrier"] == a["id"]
            if carrier:
                at = space.site_at(pos)
                if at and (at == site or w["deadline"] - now < 90):
                    return "plant", at
            route = order["via"]
            index = a["waypoint"]
            if index < len(route) and dist(pos, route[index]) < 2.6:
                index += 1
                a["waypoint"] = index
            if index < len(route) and w["deadline"] - now > 145:
                goal = route[index]
            elif carrier:
                goal = order["plant"]
            a["status"] = f"Выход на {site}"
            if (
                index
                and index < len(route)
                and plan["style"] in ("Сбор", "Групповой выход", "Контроль карты")
            ):
                partners = [
                    p
                    for p in allies
                    if p is not a and plan["orders"]["slots"][p["slot"]]["via"] == route
                ]
                if (
                    partners
                    and now - plan["start"] < 230
                    and min(dist(pos, xyz(p)) for p in partners) > 35
                ):
                    goal = pos
                    a["status"] = "Ждёт партнёра для выхода"
    else:
        site = order["site"]
        backup = plan.get("backup")
        if backup and backup["id"] == a["id"]:
            site, goal, watch = backup["site"], backup["hold"], backup["watch"]
        a["status"] = f"Занимает {site}"
    if (
        side == "T"
        and plan["style"] == "Контроль карты"
        and a["playingRole"] == "lurker"
        and w["phase"] == "live"
        and a["waypoint"] == 0
        and not latest
        and now - plan["start"] < 2 * familiarity
        and not (bomb and bomb["carrier"] == a["id"])
    ):
        middle = space.places[space.profile["middle"]]
        goal = min((space.centers[i] for i in middle), key=lambda p: dist(pos, p))
        a["status"] = "Проверяет центр"
        if "Ложная" in a["utility"] and now >= a["throwAt"] and dist(pos, goal) <= 22:
            other = "B" if site == "A" else "A"
            false_lane = [
                p for p in space.ingress(other, plan["lane"]) if 12 < dist(pos, p) < 48
            ]
            if false_lane:
                aim = min(false_lane, key=lambda p: dist(p, goal))
                a["status"] = "Отвлекает на другом подходе"
                return "throw", dict(zip(("x", "y", "z"), aim), utility="Ложная")
    if (
        latest
        and w["phase"] == "live"
        and (side == "CT" or not bomb or bomb["carrier"] != a["id"])
        and not w["action"]
    ):
        if dist(goal, xyz(latest)) < 40 and dist(pos, xyz(latest)) > 6:
            contact = xyz(latest)
            if space.hit(pos, contact, 1, 64) is None:
                goal = pos
            else:
                # Check an angle from a nearby walkable surface. Radio and
                # sound do not give the observer a path to a live enemy.
                key = [latest["id"], latest["tick"]]
                if a.get("checkContact") != key or a.get("blockedTicks", 0) >= 5:
                    near = space.nearby_areas(contact, 24)
                    positions = sorted(
                        (space.centers[i] for i in near),
                        key=lambda q: dist(pos, q) + abs(15 - dist(q, contact)),
                    )
                    peek = space._reachable(
                        pos,
                        (q for q in positions if space.hit(q, contact, 1, 64) is None),
                    )
                    a.update(checkContact=key, checkPosition=peek)
                goal = a["checkPosition"] or goal
            a["status"] = "Проверяет сообщение о контакте"
    if (
        w["phase"] == "live"
        and latest
        and not w["action"]
        and a["utility"]
        and now >= a["throwAt"]
        and (
            a["playingRole"] == "support" or skill["coordination"] + familiarity >= 145
        )
        and latest["source"] != "Слух"
        and now - latest["tick"] < 15
    ):
        engaged = next(
            (p for p in allies if p is not a and p["target"] == latest["id"]), None
        )
        smoke = "Дым" in a["utility"]
        if engaged and dist(pos, xyz(latest)) > 25 and smoke:
            a["status"] = "Закрывает дымом контакт партнёра"
            return "throw", dict(latest, utility="Дым")
    if side == "T" and w["phase"] == "live" and a["status"].startswith("Выход на "):
        repair = a.get("revisedApproach")
        original_goal = list(goal)
        if repair and repair["from"] == original_goal and repair["site"] == site:
            goal = repair["to"]
        if a.get("blockedTicks", 0) >= 8 and a.get("blockedGoal") == list(goal):
            # A contact, recovery or one-way drop can disconnect the original
            # intermediate point. Continue from the player's actual position.
            carrier = bomb and bomb.get("carrier") == a["id"]
            areas = space.plants[site] if carrier else space.nearby_areas(goal, 22)
            points = sorted(
                (space.centers[i] for i in areas), key=lambda q: dist(q, goal)
            )
            if not carrier:
                points.extend(space.centers[i] for i in space.plants[site])
            replacement = space._reachable(pos, points, a["navArea"])
            if replacement is not None and replacement != tuple(goal):
                a["revisedApproach"] = {
                    "site": site,
                    "from": original_goal,
                    "to": list(replacement),
                }
                if (
                    a["waypoint"] < len(order["via"])
                    and list(goal) == order["via"][a["waypoint"]]
                ):
                    a["waypoint"] += 1
                goal = replacement
    moved = travel(
        a,
        goal,
        2 if plan["style"] == "Быстро" or w["phase"] == "planted" else 1.65,
        fire,
        allow_detour=True,
    )
    if moved:
        if latest and now - latest["tick"] < 12 + skill["positioning"] // 5:
            a["heading"] = atan2(latest["y"] - a["y"], latest["x"] - a["x"])
        return "move", None
    # Watch an approach known to this team or turn toward the last reported contact.
    if latest and latest["tick"] >= a.get("heardUse", -1000):
        watch = xyz(latest)
    a["heading"] = atan2(watch[1] - a["y"], watch[0] - a["x"]) + 0.65 * sin(
        (now + 13 * slot) / 26
    )
    return "hold", None
