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
            goal = xyz(bomb) if bomb else space.site_points[site]
            other = w["action"] and w["action"]["player"] != a["id"]
            if bomb and dist(pos, goal) <= 6 and not other and space.clear(a, bomb):
                return "defuse", None
            if other:
                goal = (
                    space.holds[site][slot][1]
                    if len(space.holds[site]) > slot
                    else (order["hold"] if order["site"] == site else pos)
                )
            a["status"] = "Прикрывает разминирование" if other else "Идёт на ретейк"
        else:
            site = bomb["site"]
            if order["site"] != site:
                goal = space.site_points[site]
            a["status"] = "Прикрывает C4"
    elif side == "T":
        if (
            bomb
            and not bomb["carrier"]
            and min(allies, key=lambda p: (dist(xyz(p), xyz(bomb)), p["slot"])) is a
        ):
            goal = xyz(bomb)
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
        if plan["reinforce"] and slot in (1, 4):
            site = plan["reinforce"]
            goal = space.site_points[site]
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
                if a.get("checkContact") != key:
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
    watch = xyz(latest) if latest else order["watch"]
    a["heading"] = atan2(watch[1] - a["y"], watch[0] - a["x"]) + 0.65 * sin(
        (now + 13 * slot) / 26
    )
    return "hold", None
