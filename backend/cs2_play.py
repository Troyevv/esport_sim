"""Map-dependent choices for the shared BO1 agents, using squad observations."""

from math import atan2, cos, dist, hypot, sin, tau
from .cs2_maps import UNIT, xyz
from . import match_performance as perf, world
from .match_rules import BLAST_RADIUS, RULES, UTILITY, equipment_value


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
        if buy == "Антиэко":
            # Hold wider lines so the group need not challenge stacked pistols at arm's length.
            label = space.profile["probe"][site]
            lane = min(range(2), key=lambda j: label in space.profile[site][j])
            style = "Контроль карты"
        elif style == "Быстро" and not call:
            # Light equipment favours a close trade only when at least two
            # friendly spawns can reach the crossing before a defender.
            if buy in ("Эко", "Частичная", "Форс", "Бонусная"):
                def contest_margin(j):
                    costs, defender = space.contest(site, j)
                    arrivals = sorted(costs.get(p["navArea"], float("inf")) for p in squad)
                    return arrivals[1] - defender

                lane = min(range(2), key=contest_margin)
                style = "Групповой выход"
            costs, defender = space.contest(site,lane)
            approach = sorted(costs.get(p["navArea"],float("inf")) for p in squad)
            # A fast split requires two players able to contest together. A lone
            # favourable spawn does not justify ordering four late players through it.
            if approach[1] > defender:
                style = "Контроль карты"
        elif knowledge + player["skills"]["map_control"] >= 115 and style == "Сбор":
            style = "Контроль карты"
    return site, style, lane


def default_probe(space, squad, carrier, plan, now, domain=None):
    """Split an information default between the primary approach, mid and the flank."""
    site = plan["site"]
    other = "B" if site == "A" else "A"
    available = [a for a in squad if a["id"] != carrier]
    def scout_fit(a):
        if domain is None:
            return 0
        player = domain["players"][a["playerId"]]
        return (player["skills"]["lurking"] + player["roleMastery"].get("lurker", 0)
                + player["mapKnowledge"].get(space.name.removeprefix("de_"), 0))

    scout = min(available, key=lambda a: (a["playingRole"] != "lurker", -scout_fit(a), a["slot"]))
    available.remove(scout)
    mid = min(available, key=lambda a: (a["playingRole"] != "awper", a["slot"]))
    available.remove(mid)
    partner = min(available, key=lambda a: (a["playingRole"] == "entry", a["slot"]))
    stations = {}
    for a in squad:
        flank = a in (scout, partner)
        sector = other if flank else site
        label = space.profile["middle"] if a is mid else space.profile["probe"][sector]
        pos = xyz(a)
        occupied = [v["point"] for v in stations.values() if v["label"] == label]
        surfaces = [space.centers[i] for i in sorted(space.places[label])]
        # Two players can work one lane while maintaining trading distance and
        # different sight lines. Only choose points reachable from this spawn.
        candidates = sorted(surfaces, key=lambda q: (
            bool(occupied) and min(dist(q,p) for p in occupied) < 8,
            dist(pos,q) + (abs(dist(q,occupied[0])-16) if occupied else 0)))
        point = space._reachable(pos, candidates, a["navArea"])
        if point is None:
            return None
        angles = [space.site_points[sector], *space.ingress(sector,plan["lane"])]
        angles = [q for q in angles if dist(point,q)>6 and space.hit(point,q,1,64) is None]
        watch = min(angles,key=lambda q: dist(point,q), default=space.site_points[sector])
        stations[a["id"]] = dict(label=label, sector=sector, point=list(point), watch=list(watch))
    return dict(scout=scout["id"], stations=stations, reports={}, until=now+RULES["live"]-RULES["plant"])


def hold_sector(space, w, a, allies, fire, travel):
    """Take a sector, observe its crossing, then radio readiness to the captain."""
    plan, now = w["plan"], w["tick"]
    probe = plan.get("probe")
    if not probe or "stations" not in probe or probe.get("released") or plan["rotated"]:
        return None
    station = probe["stations"][a["id"]]
    pos, goal = xyz(a), station["point"]
    a["status"] = "Берёт контроль · " + station["label"]
    if dist(pos, goal) > 4:
        if travel(a,goal,1.65,fire,allow_detour=True):
            return "move", None
        if a.get("blockedTicks",0) >= 20:
            # This member cannot establish their assigned sector. This is
            # a report about our path, not an enemy sighting.
            probe.setdefault("unreachable", {}).setdefault(a["id"], now+1+(100-w["player"]["skills"]["communication"])//12)
        return "hold", None
    watch = station["watch"]
    a["heading"] = atan2(watch[1]-pos[1], watch[0]-pos[0])
    a["status"] = "Наблюдает · " + station["label"]
    if a["id"] not in probe["reports"]:
        player = w["player"]
        # The scout checks visible approaches from the reached NAV surface.
        # Report immediately when a teammate already sees the other crossing.
        if "check" not in station:
            angles = [q for q in space.ingress(station.get("sector",plan["site"]),plan["lane"])
                      if 6 < dist(pos,q) < 75 and space.hit(pos,q,1,64) is None]
            flank = max(angles,key=lambda q:dist(q,watch), default=watch)
            covered = any(m is not a and dist(xyz(m),pos) < 28 and
                          space.hit(xyz(m),flank,1,64) is None and
                          cos(m["heading"]-atan2(flank[1]-m["y"],flank[0]-m["x"])) >= 0.5
                          for m in allies)
            station["check"] = list(watch if covered else flank)
        q = station["check"]
        a["heading"] = atan2(q[1]-pos[1],q[0]-pos[0])
        latency = 1 + (100-player["skills"]["execution"])//25
        probe["reports"][a["id"]] = now+latency+(100-player["skills"]["communication"])//12
    utility = crossing_utility(space,w,a,allies,plan["orders"]["slots"][a["slot"]],station.get("sector", plan["site"]))
    return utility or ("hold", None)


def probe_intent(space, w, a, allies, goal, watch):
    plan, now = w["plan"], w["tick"]
    probe = plan.get("probe")
    if not probe or probe.get("released") or plan["rotated"] or len(allies) < 4 or now >= probe["until"]:
        return goal, watch
    pos = xyz(a)
    if a["id"] == probe["scout"]:
        if dist(pos, probe["goal"]) > 5:
            a["status"] = "Проверяет второй подход"
            return probe["goal"], space.site_points["B" if plan["site"] == "A" else "A"]
        if "reportDue" not in probe:
            # Report reaching the landmark. It does not certify that the lane is empty.
            probe["reportDue"] = now + 1 + (100 - w["player"]["skills"]["communication"]) // 12
        a["status"] = "Наблюдает второй подход"
        return pos, space.site_points["B" if plan["site"] == "A" else "A"]
    # The core can take its own lane. Stop before the final crossing if the
    # scout is still working; keep watching the site during the short wait.
    site = plan["site"]
    costs = space.site_costs[site]
    remaining = costs.get(a["navArea"], float("inf")) / UNIT
    if 20 < remaining < 50 and a["status"].startswith("Выход на "):
        a["status"] = "Ждёт сведений со второго подхода"
        return pos, space.site_points[site]
    return goal, watch


def release_probe(space, plan, squad, contacts, now):
    probe = plan.get("probe")
    if not probe or probe.get("released"):
        return
    if "stations" in probe:
        # The slowest live member must still be able to reach a legal plant. NAV
        # costs are Hammer units; the approach uses simulation units per tick.
        travel = max(space.site_costs[plan["site"]].get(a["navArea"], 0) / (UNIT*1.65) for a in squad)
        due = probe["reports"]
        ready = all(due.get(a["id"],float("inf")) <= now for a in squad)
        failed = any(t <= now for t in probe.get("unreachable", {}).values())
        if ready or failed or len(squad) <= 3 or now+travel+RULES["plant"] >= probe["until"]:
            probe["released"] = now
        return
    other = "B" if plan["site"] == "A" else "A"
    scout = next((a for a in squad if a["id"] == probe["scout"]), None)
    # A mid duel by the main group says nothing about the scout's flank.
    flank = any(space.reported_site(xyz(report)) == other for report in contacts)
    if scout is None or flank or now >= probe.get("reportDue", probe["until"]) or len(squad) < 4:
        probe["released"] = now


def prepare_plant(space, w, a, allies, site):
    now = w["tick"]
    if w["action"] or w["deadline"] - now <= RULES["plant"] + 10:
        return "plant", site
    pos = xyz(a)
    # The planter can count a friendly covering an angle only if the teammate
    # can see it, is facing it and can fire. Enemy locations come from memory.
    check = a.get("plantCheck")
    if not check or check["site"] != site or dist(pos, check["origin"]) > 6:
        reports = [r for r in a["knowledge"].values() if r["source"] not in ("Слух","Граната")
                   and now-r["tick"] < 50 and space.hit(pos, xyz(r), 1, 64) is None]
        angles = [xyz(r) for r in sorted(reports, key=lambda r: -r["tick"])]
        choices = sorted((p for _, p in space.holds[site]), key=lambda p: dist(pos,p))
        for p in choices:
            if len(angles) >= 3:
                break
            if 8 < dist(pos,p) < 65 and all(dist(p,q)>12 for q in angles) and space.hit(pos,p,1,64) is None:
                angles.append(p)
        check = a["plantCheck"] = dict(site=site, origin=list(pos), angles=[list(p) for p in angles], index=0)
    while check["index"] < len(check["angles"]):
        q = check["angles"][check["index"]]
        covered = False
        for mate in allies:
            if mate is a or not mate["ammo"] or mate["blind"] > now or mate["reloadAt"]:
                continue
            dx, dy = q[0]-mate["x"], q[1]-mate["y"]
            if (dx*cos(mate["heading"])+dy*sin(mate["heading"]) >= 0.75*hypot(dx,dy)
                    and dist(xyz(mate),pos)<55 and space.hit(xyz(mate),q,1,64) is None):
                covered = True
                break
        if not covered:
            a["status"] = "Проверяет угол перед установкой"
            a["heading"] = atan2(q[1]-pos[1], q[0]-pos[0])
            if now < check.setdefault("until", now + 2 + (100-w["player"]["skills"]["positioning"])//15):
                return "hold", None
        check.pop("until", None)
        check["index"] += 1
    return "plant", site


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
    # The junction player can have this site's label and still be watching mid.
    # Count a mobile guard by their actual position, never by the nominal label.
    other = [a for a in squad if slots[a["slot"]]["site"] != site or a["slot"] == 4]
    # Release the mobile defender before the only player watching the other plant.
    reserves = [a for a in other if a["slot"] >= 2]
    if reserves:
        other = reserves
    elif len(other) == 1 and any(slots[p["slot"]]["site"] == site for p in squad):
        plan.pop("backup", None)
        return
    if not other:
        plan.pop("backup", None)
        return
    current = plan.get("backup")
    if (
        current
        and current["site"] == site
        and any(p["id"] == current["id"] for p in other)
    ):
        return
    guards = [slots[p["slot"]] for p in squad if p["slot"] != 4 and slots[p["slot"]]["site"] == site]
    # Rank covering angles by their view of the legal plant surfaces and entry.
    # Some maps have no authored cover markers on the site itself. Choosing the
    # nearest marker to the incoming player can then strand the reserve off-site.
    center = space.site_points[site]
    angles = space.angles(site, plan["lane"], center, "site")
    ordered = sorted(
        other,
        key=lambda p: (
            space.site_costs[site].get(p["navArea"], float("inf")),
            dist(xyz(p), center),
            p["slot"],
        ),
    )
    for actor in ordered:
        for target, watch in angles:
            if any(dist(target, guard["hold"]) < 6 for guard in guards):
                continue
            if space._reachable(xyz(actor), [target], actor["navArea"]) is None:
                continue
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
    exposed = False
    if contact and actor["team"] == "CT" and len(actor["visible"]) > 1:
        engaged = sum(p is not actor and p["target"] in actor["visible"] and
                      dist(xyz(p),xyz(actor)) < 45 for p in allies)
        # A lone defender who cannot trade the opening can break contact and
        # re-engage with a partner. A confident entry can still take the duel.
        exposed = (len(actor["visible"]) > 1 + engaged and
                   skills["positioning"] + skills["discipline"] > skills["aggression"] + skills["risk"])
    if contact and (actor["reloadAt"] or exposed or actor["hp"] < 35 and len(actor["visible"]) > 1):
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
                key=lambda q: (any(dist(q, a) < 3 for a in occupied),
                                   exposed and not any(dist(q,p) < 35 for p in occupied), dist(q, pos), q),
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
        p["source"] not in ("Слух","Граната") and w["tick"] - p["tick"] < 32 and dist(xyz(p), pos) < 60
        for p in a["knowledge"].values()
    )
    if a["team"] == "T":
        reserve = 12 + equipment_value(a) / 450 - threats * 3
        departure = routes.costs[area] / UNIT / speed + reserve
        origin = xyz(a)
        stationary = a["status"] == "Прикрывает C4" and not a["path"]
        if dist(origin, pos) < BLAST_RADIUS and (stationary or remaining <= departure):
            # A short abstract route may lead through a portal blocked on this floor.
            # Compare actual walking time with the time the captain intended to leave.
            if space.nominal_exit(area, origin, pos) / speed > departure:
                alternative = space.physical_exit(area, origin, pos)
                if alternative is not None:
                    length, path = alternative
                    if remaining > max(departure, length / speed + reserve):
                        return
                    if path:
                        safe = path[-1][:3]
                        # Execute the measured path. Replanning solely to this
                        # point can again choose the original, much longer detour.
                        a["path"] = [list(node) for node in path]
                        a["dest"] = [space.locate(safe), *safe, []]
                        return safe
        if remaining > departure:
            return
    else:
        if w["action"]:
            return
        # A device on the far lip of a one-way NAV edge can be used from
        # an adjacent surface. Estimate the walk to that usable floor.
        origin = xyz(a)
        use_ticks = RULES["kitDefuse"] if a["kit"] else RULES["defuse"]
        if bomb and dist(origin, pos) <= 6 and space.clear(a, bomb) and remaining > use_ticks:
            return
        if bomb:
            if a.get("useTarget") != list(pos) or a.get("blockedTicks", 0) >= 5:
                a["useFloor"] = space.use_position(a, bomb, 6)
                a["useTarget"] = list(pos)
            floor = a.get("useFloor")
        else:
            search = a.get("bombSearch") or {}
            floor = search.get("goal") or pos
        path = None
        length = 0.0
        if floor:
            goal = tuple(floor)
            if a["path"] and tuple(a["path"][-1][:3]) == goal:
                path = a["path"]
            else:
                path = space.path(area, origin, space.locate(goal), goal, frozenset())
            prev = origin
            for node in path or ():
                point = node[:3]
                length += dist(prev, point)
                prev = point
        if (
            path is not None
            and remaining
            > max(0, length - 6) / speed
            + use_ticks
            + max(0, threats - len(allies) + 1) * 8
            + (perf.retake_margin(w["player"]["skills"], length, equipment_value(a)) if threats else 0)
        ):
            return
    _, goals = routes.route(area)
    chosen = space.centers[goals[-1]]
    position = xyz(a)
    if space.path(area, position, goals[-1], chosen, frozenset()) is not None:
        return chosen
    # The closest safe NAV centre can lie beyond a closed prop. Check
    # other safe surfaces before committing the player's remaining time.
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


def sound_bearing(actor, device):
    dx, dy = device["x"] - actor["x"], device["y"] - actor["y"]
    sector = round(atan2(dy, dx) * 8 / tau) % 8
    directions = ((1, 0), (1, 1), (0, 1), (-1, 1),
                  (-1, 0), (-1, -1), (0, -1), (1, -1))
    return [actor["x"], actor["y"], *directions[sector]]


def hear_plant(space, players, planter, tick):
    # One audible interaction, including a fake. The keypad does not identify its user.
    source = xyz(planter)
    for actor in players:
        if actor["team"] != "CT" or not actor["hp"]:
            continue
        pos = xyz(actor)
        distance = dist(pos, source)
        if distance > 55 or (distance > 26 and space.hit(pos, source, 1, 64, 34)):
            continue
        cue = sound_bearing(actor, planter)
        # Choose from known plant areas in the audible direction; stacked sites can be ambiguous.
        guesses = [(costs.get(actor["navArea"], float("inf")), site)
                   for site, costs in space.site_costs.items()
                   if any(not outside_bearing(space.centers[i], cue) for i in space.plants[site])]
        if guesses:
            _, site = min(guesses)
            actor["plantCue"] = dict(tick=tick, site=site, bearing=cue)


def hear_device(actor, device, tick):
    # A beep gives a coarse direction but no range or floor.
    if tick % 10 == 0:
        actor["beepBearing"] = sound_bearing(actor, device)


def outside_bearing(point, cue):
    if not cue:
        return False
    x, y, dx, dy = cue
    vx, vy = point[0] - x, point[1] - y
    return vx * dx + vy * dy < abs(vx * dy - vy * dx)


def search_site(space, actor, site, now, allies=()):
    # A beep identifies the site, but a crate or raised platform can hide
    # the device from the site's centre. Clear the actual plant surfaces.
    pos = xyz(actor)
    center = space.site_points[site]
    cue = actor.get("beepBearing")
    state = actor.get("bombSearch")
    if not state or state["site"] != site:
        if not cue and dist(pos, center) > 25 and actor.get("blockedTicks", 0) < 5:
            return center
        state = actor["bombSearch"] = dict(site=site, seen=[], goal=None, next=0)
    if (
        state["goal"]
        and dist(pos, state["goal"]) > 2
        and (now < state["next"] or not outside_bearing(state["goal"], cue))
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
    visited = set(state.get("visited", []))
    if state["goal"] and dist(pos, state["goal"]) <= 2 and state.get("area") is not None:
        # Standing at an obstructed polygon centre is a completed visit even
        # when a crate prevents the eye-to-floor ray from clearing that centre.
        visited.add(state["area"])
    reserved = []
    for mate in allies:
        report = mate.get("bombSearch")
        if mate is actor or not report or report["site"] != site or dist(pos, xyz(mate)) > 20:
            continue
        if report.get("sweep", 0) == state.get("sweep", 0):
            seen.update(report["seen"])
            visited.update(report.get("visited", []))
        if report["goal"]:
            reserved.append(report["goal"])
    unsearched = [i for i in candidates if i not in seen and i not in visited]
    if not unsearched:
        # After a full sweep inspect the site from a different part of each
        # polygon. A hidden plant need not coincide with the polygon centre.
        sweep = state.get("sweep", 0) + 1
        state["sweep"] = sweep
        seen.clear()
        visited.clear()
        unsearched = list(candidates)
    points = {}
    for i in unsearched:
        point = space.centers[i]
        if state.get("sweep"):
            corners = space.nav.areas[i]["corners"]
            corner = space.to_sim(corners[(actor["slot"] + state["sweep"]) % len(corners)])
            point = tuple((v + c) / 2 for v, c in zip(point, corner))
        points[point] = i
    choices = sorted(points, key=lambda p: (outside_bearing(p, cue),
                                             any(dist(p, g) < 7 for g in reserved), dist(pos, p), p))
    state["seen"], state["visited"] = sorted(seen), sorted(visited)
    goal = space._reachable(pos, choices, actor.get("navArea"))
    state["area"] = points.get(goal)
    state["goal"] = list(goal) if goal else None
    return goal or center


def crossing_utility(space, w, a, allies, order, site):
    """Use available cover and utility to open or deny the next crossing."""
    now, plan = w["tick"], w["plan"]
    if not a["utility"] or now < a["throwAt"] or now < a.get("crossingReview",0):
        return None
    a["crossingReview"] = now + 14
    pos = xyz(a)
    reserve = plan.get("probe") or {}
    scouting = a["team"] == "T" and not reserve.get("released") and not plan["rotated"]
    feint = scouting and a["id"] == reserve.get("scout")
    if feint and "stations" not in reserve:
        site = "B" if site == "A" else "A"
    calls = plan.setdefault("crossingCalls", [])
    calls[:] = [c for c in calls if now < c["end"]]
    defending = a["team"] == "CT" and w["phase"] == "live"
    if defending:
        targets = space.ingress(site,plan["lane"])
        # Deny an opening race or respond to a report of pressure. Do not
        # continually refresh an empty lane throughout a quiet round.
        pressure = any(now-r["tick"] < 35 and space.reported_site(xyz(r)) == site
                       for r in a["knowledge"].values())
        if not pressure and (now-plan["start"] > 200 or a.get("screenedOpening")):
            return None
        gadgets = ("Огонь","Дым")
    else:
        labels = space.profile["guards"][site]
        targets = [space.centers[i] for label in labels for i in sorted(space.places[label])]
        gadgets = ("Ложная","Дым","Свет") if feint else ("Дым","Свет")
        # The potential beneficiary must be near enough to take the crossing.
        if not feint and not any(m is not a and dist(xyz(m),pos) < 35 for m in allies):
            return None
    candidates = sorted((p for p in targets if 24 < dist(pos,p)<68),key=lambda p:dist(pos,p))
    for p in candidates[:8]:
        item = next((g for g in gadgets if g in a["utility"]
                     and not any(c["item"] == g and dist(c["point"],p) < UTILITY[g][0] for c in calls)
                     and not any(dist(xyz(m),p) < (UTILITY[g][0] if g == "Свет" else 18)
                                 for m in allies)), None)
        if not item:
            continue
        flight = max(3,round(dist(pos,p)/7))
        x,y,z,_ = space.grenade(pos,p,flight)
        if dist((x,y,z),p)>8:
            continue
        calls.append(dict(item=item, point=list(p), end=now+flight+UTILITY[item][1]))
        if defending:
            a["screenedOpening"] = True
        a["status"]="Имитирует выход" if feint else "Готовит гранату на подход"
        return "throw", dict(zip(("x","y","z"),p),utility=item)
    return None


def spatial_intent(space, w, a, allies, bomb, fire, travel):
    now, plan = w["tick"], w["plan"]
    side, slot = a["team"], a["slot"]
    orders = plan["orders"]["slots"]
    order = orders[slot]
    if side == "CT" and w["phase"] == "live" and slot in (2, 3):
        anchor = slot - 2
        if not any(p["slot"] == anchor for p in allies):
            order = orders[anchor]
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
                goal = search_site(space, a, site, now, allies)
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
            elif a.get("plantCover") and dist(pos,goal) < 5:
                # Orient towards the way a retaker can enter this position.
                # A less experienced guard tends to watch the familiar plant.
                if "postWatch" not in a:
                    routes = space.ingress(site, plan["lane"])
                    visible = [q for q in routes if 8 < dist(pos,q) < 90
                               and space.hit(pos,q,1,64) is None]
                    a["postWatch"] = list(min(visible,key=lambda q:dist(pos,q))) if visible else list(watch)
                attention = skill["postplant"] / 100
                watch = [p*attention + b*(1-attention) for p,b in zip(a["postWatch"],xyz(bomb))]
            a["status"] = "Проверяет C4 после звука" if check else "Прикрывает C4"
    elif side == "T":
        if bomb and bomb["carrier"] and not w["action"]:
            occupation = hold_sector(space,w,a,allies,fire,travel)
            if occupation:
                return occupation
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
                    return prepare_plant(space, w, a, allies, at)
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
                # Read the progress of the pair on the same entry. Familiar
                # partners and experienced executors can stage a tighter trade.
                cohesion = max((w["chemistry"].get(world.pair_key(a["playerId"],p["playerId"]),0)
                                for p in partners), default=0)
                mastery = w["player"]["roleMastery"].get(a["playingRole"],0)
                spacing = 52 - (skill["synchronization"] + skill["timing"] + mastery + cohesion) / 16
                if (
                    partners
                    and now + space.site_costs[site].get(a["navArea"], 0) / (UNIT * 1.65) + RULES["plant"] + 45 < w["deadline"]
                    and min(dist(pos, xyz(p)) for p in partners) > spacing
                    and any(p["waypoint"] < index for p in partners)
                    and not any(p.get("blockedTicks",0) >= 5 for p in partners)
                ):
                    goal = pos
                    a["status"] = "Ждёт партнёра для выхода"
    else:
        site = order["site"]
        backup = plan.get("backup")
        if backup and backup["id"] == a["id"]:
            site, goal, watch = backup["site"], backup["hold"], backup["watch"]
        a["status"] = f"Занимает {site}"
    if not w["action"] and (w["phase"] == "live" or (side == "CT" and a["heardSite"] and len(allies) >= 2 and w["deadline"]-now > RULES["defuse"] + 40)):
        intent = crossing_utility(space,w,a,allies,order,site)
        if intent:
            return intent
    cue = a.get("plantCue")
    if side == "CT" and w["phase"] == "live" and cue and 0 <= now-cue["tick"] < 30:
        if "peek" not in cue:
            points = [space.centers[i] for i in space.plants[cue["site"]]
                      if not outside_bearing(space.centers[i], cue["bearing"])]
            if points:
                target = min(points, key=lambda p: dist(p, pos))
                angles = sorted((space.centers[i] for i in space.nearby_areas(pos, 18)),
                                key=lambda p: dist(pos, p))
                spots = [pos, *angles]
                cue["peek"] = space._reachable(pos, (p for p in spots if space.hit(p, target, 1, 64) is None))
                cue["watch"] = target
            else:
                cue["peek"] = None
        if cue["peek"] is not None:
            goal, watch = cue["peek"], cue["watch"]
            a["status"] = "Проверяет звук установки"
    if side == "T" and w["phase"] == "live" and plan.get("probe") and "stations" not in plan["probe"] and not latest and not w["action"] and bomb and bomb["carrier"]:
        goal, watch = probe_intent(space, w, a, allies, goal, watch)
        if a["status"] == "Наблюдает второй подход" and "Ложная" in a["utility"] and now >= a["throwAt"]:
            other = "B" if site == "A" else "A"
            points = [p for p in space.ingress(other, plan["lane"]) if 12 < dist(pos, p) < 48]
            if points:
                return "throw", dict(zip(("x", "y", "z"), points[0]), utility="Ложная")
    if (
        side == "T"
        and not plan.get("probe")
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
        and now-latest["tick"] <= perf.pursuit_window(skill, latest["source"] == "Слух")
    ):
        anchor = side == "CT" and order in orders[:2]
        if anchor and latest["source"] != "Слух" and a["utility"] and now >= a["throwAt"]:
            # Use a reported push to delay a crossing while the anchor still holds the site.
            if now - latest["tick"] < 18 and 20 < dist(pos, xyz(latest)) < 80:
                for crossing in space.ingress(site, plan["lane"]):
                    if dist(crossing, xyz(latest)) > 12 or space.hit(pos, crossing, 1, 64):
                        continue
                    if any(dist(xyz(p), crossing) < 21 for p in allies):
                        continue
                    grenade = next((g for g in ("Огонь", "Дым") if g in a["utility"]), None)
                    if grenade:
                        a["status"] = "Сдерживает выход на плент"
                        return "throw", dict(zip(("x","y","z"),crossing), utility=grenade)
        if not anchor and dist(goal, xyz(latest)) < (55 - skill["discipline"] / 4) and dist(pos, xyz(latest)) > 6:
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
        if side == "CT" and not latest and dist(xyz(a), goal) < 22 + familiarity / 6:
            # Strafe into the last stretch of the hold facing the known crossing.
            a["heading"] = atan2(watch[1]-a["y"], watch[0]-a["x"])
        if latest and now - latest["tick"] < 12 + skill["positioning"] // 5:
            a["heading"] = atan2(latest["y"] - a["y"], latest["x"] - a["x"])
        return "move", None
    # Watch an approach known to this team or turn toward the last reported contact.
    if latest and now - latest["tick"] <= perf.pursuit_window(skill, latest["source"] == "Слух") and latest["tick"] >= a.get("heardUse", -1000):
        watch = xyz(latest)
    a["heading"] = atan2(watch[1] - a["y"], watch[0] - a["x"]) + (0.6 - skill["discipline"] / 260) * sin(
        (now + 13 * slot) / 26
    )
    return "hold", None
