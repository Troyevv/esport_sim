"""Perception, captain decisions and execution on Depo's navigation grid."""

from functools import lru_cache
from math import atan2, hypot, pi, sin

from . import engine, tactic_execution
from .match_events import damage, emit
from .match_rules import MAP, POSITIONS, RULES, UTILITY, WEAPONS, role_orders


def distance(a, b):
    return hypot(a["x"] - b["x"], a["y"] - b["y"])


def at(xy):
    return dict(x=xy[0], y=xy[1])


def near_line(a, b, p, radius):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    length = dx * dx + dy * dy
    ratio = (
        max(0, min(1, ((p["x"] - a["x"]) * dx + (p["y"] - a["y"]) * dy) / length))
        if length
        else 0
    )
    return hypot(a["x"] + ratio * dx - p["x"], a["y"] + ratio * dy - p["y"]) <= radius


@lru_cache(maxsize=256)
def audible_sector(col, row):
    centre = (col * 3 + 1, row * 3 + 1)
    floor = min(
        engine._FLOOR, key=lambda p: (p[0] - centre[0]) ** 2 + (p[1] - centre[1]) ** 2
    )
    return at(engine._center(floor))


def observe(w, players):
    now = w["tick"]
    for message in w["messages"][:]:
        if message["due"] > now:
            continue
        w["messages"].remove(message)
        for a in players:
            if a["team"] == message["team"] and a["id"] != message["sender"]:
                if "site" in message:
                    a["heardSite"] = message["site"]
                    continue
                sight = message["sight"]
                if sight["tick"] > a["knowledge"].get(sight["id"], {}).get("tick", -1):
                    a["knowledge"][sight["id"]] = dict(sight, source="Радио")
    smoke = [
        f for f in w["effects"] if f["kind"] == "Дым" and f["land"] <= now < f["end"]
    ]
    for a in players:
        previous = a["visible"]
        a["visible"] = []
        a["knowledge"] = {
            k: v for k, v in a["knowledge"].items() if now - v["tick"] < 75
        }
        if a["blind"] > now:
            continue
        for b in players:
            if b["team"] == a["team"] or not engine.sees(a, b):
                continue
            if any(near_line(a, b, fog, fog["radius"]) for fog in smoke):
                continue
            sight = dict(id=b["id"], x=b["x"], y=b["y"], tick=now, source="Зрение")
            a["visible"].append(b["id"])
            a["knowledge"][b["id"]] = sight
            if b["id"] not in previous or now % 10 == 0:
                w["messages"].append(
                    dict(
                        team=a["team"],
                        sender=a["id"],
                        sight=sight,
                        due=now + 1 + (100 - a["comms"]) // 12,
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


def captain(w, squad):
    leader = min(squad, key=lambda a: a["slot"])
    plan = w["plans"][leader["team"]]
    now = w["tick"]
    if plan["captain"] != leader["id"]:
        plan.update(captain=leader["id"], review=now)
        emit(
            w,
            "captain",
            f"{leader['name']} принимает колл",
            leader["team"],
            player=leader["id"],
        )
    if now < plan["review"]:
        return
    plan["review"] = now + 18 + (100 - leader["tactics"]) // 2
    # Only the acting captain's timestamped reports are available here.
    contacts = [p for p in leader["knowledge"].values() if p["source"] != "Слух"]
    counts = {
        s: sum(distance(at(POSITIONS[s][0]), p) < 80 for p in contacts)
        for s in POSITIONS
    }
    site = plan["site"]
    if (
        leader["team"] == "T"
        and counts[site] >= 3
        and not plan["rotated"]
        and w["deadline"] - now > 250
        and w["phase"] == "live"
    ):
        plan.update(site="B" if site == "A" else "A", rotated=True)
        plan["orders"] = role_orders("T", plan["site"])
        emit(
            w,
            "rotate",
            f"{leader['name']} меняет направление после трёх контактов · {plan['site']}",
            "T",
            player=leader["id"],
            contacts=[p["id"] for p in contacts],
        )
    if leader["team"] == "CT":
        if counts["A"] != counts["B"] and max(counts.values()) >= 2:
            plan["reinforce"] = max(counts, key=counts.get)
        if w["phase"] == "planted":
            # The announcement is public. Site identification travels with the beep.
            heard = leader["heardSite"]
            if heard:
                plan["reinforce"] = heard


@lru_cache(maxsize=4096)
def path_between(start, goal):
    return tuple(tuple(p) for p in engine.route(start, goal))


def walk(a, goal, pace, hazards):
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
        a["status"] = "Пережидает огонь за укрытием"
        return False
    dx, dy = x - a["x"], y - a["y"]
    a["heading"] = atan2(dy, dx)
    a["x"] += max(-pace, min(pace, dx))
    a["y"] += max(-pace, min(pace, dy))
    if (a["x"], a["y"]) == (x, y):
        a["path"].pop(0)
    return True


def act(w, a, allies, bomb, visible_fire):
    """Choose an intention using allies, own sensory memory and known objective."""
    now = w["tick"]
    plan = w["plan"]
    side, slot = a["team"], a["slot"]
    site = plan["site"]
    alive = sorted(allies, key=lambda p: p["slot"])
    visible = [a["knowledge"][i] for i in a["visible"]]
    contact = min(visible, key=lambda p: distance(a, p), default=None)
    spec = WEAPONS[a["weapon"]]
    if a["reloadAt"] and now >= a["reloadAt"]:
        count = min(spec.mag - a["ammo"], a["reserve"])
        a.update(ammo=a["ammo"] + count, reserve=a["reserve"] - count, reloadAt=0)
    if not a["ammo"] and not a["reserve"] and a["weapon"] not in ("USP", "Glock"):
        a.update(weapon="USP" if side == "CT" else "Glock", ammo=12, reserve=24)
    if not a["ammo"] and a["reserve"] and not a["reloadAt"]:
        a["reloadAt"] = now + spec.reload
    if (
        contact
        and w["action"]
        and w["action"]["player"] == a["id"]
        and w["action"]["end"] - now <= 10
    ):
        contact = None
    if contact:
        a["heading"] = atan2(contact["y"] - a["y"], contact["x"] - a["x"])
        if a["target"] != contact["id"]:
            a.update(
                target=contact["id"],
                ready=max(a["ready"], now + 1 + (100 - a["reaction"]) // 12),
            )
        a["status"] = "Перезаряжается" if a["reloadAt"] else "Держит контакт"
        if a["utility"] and now >= a["throwAt"] and distance(a, contact) > 18:
            return ("throw", contact)
        if not a["reloadAt"] and a["ammo"] and now >= a["ready"]:
            return ("shoot", contact)
        return ("hold", None)
    a["target"] = None
    if w["action"] and w["action"]["player"] == a["id"]:
        return ("objective", None)
    board = plan.get("board")
    if board and not plan["rotated"]:
        recover = side == "T" and bomb and not bomb["carrier"] and not bomb["site"]
        rescuer = (
            recover and min(alive, key=lambda p: (distance(p, bomb), p["id"])) is a
        )
        reinforce = side == "CT" and (
            w["phase"] == "planted" or (plan["reinforce"] and slot in (1, 4))
        )
        # The surviving support slot rejoins the acting captain after a casualty.
        regroup = len(alive) < 5 and a is alive[-1] and distance(a, alive[0]) > 34
        if not rescuer and not reinforce and regroup:
            a["status"] = "К капитану после потери союзника"
            moved = walk(a, (alive[0]["x"], alive[0]["y"]), 2, visible_fire)
            return ("move" if moved else "hold", None)
        if not rescuer and not reinforce:
            intent = tactic_execution.execute(
                a, board["slots"][slot], now, bomb, visible_fire, walk
            )
            if intent:
                return intent
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
            too_late = (
                w["deadline"] - now
                < (RULES["kitDefuse"] if a["kit"] else RULES["defuse"])
                + distance(a, at(goal)) / 2
            )
            if too_late and not w["action"]:
                goal = engine._center(engine._SPAWN_CELLS["CT"][slot])
                a["status"] = "Сохраняет оружие"
            else:
                a["status"] = "Идёт на ретейк"
        else:
            site = bomb["site"]
            goal = POSITIONS[site][slot]
            a["status"] = "Прикрывает C4"
    elif side == "T":
        staging = plan["style"] == "Сбор" and now - plan["start"] < 85
        order = plan["orders"]["slots"][slot]
        approach = a["approached"] != site
        if approach and distance(a, at(order["approach"])) < 6:
            a["approached"] = site
            approach = False
        goal = (
            order["approach"]
            if approach
            else order["stage"]
            if staging
            else order["hold"]
        )
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
        and now - memory["tick"] < 32
        and a["status"] not in ("Сохраняет оружие", "Подбирает C4")
    ):
        if side == "CT" or (bomb and a["id"] != bomb["carrier"]):
            goal = memory["x"], memory["y"]
            a["status"] = "Проверяет сообщение о контакте"
    if walk(
        a,
        goal,
        2 if plan["style"] == "Быстро" or w["phase"] == "planted" else 1,
        visible_fire,
    ):
        return ("move", None)
    if a["status"].startswith(("Занимает", "Выход")):
        a["status"] = f"Контролирует {site}"
    a["heading"] = (pi if side == "CT" else 0) + 1.6 * sin((now + slot * 12) / 16)
    return ("hold", None)


def shoot(w, a, sight, b):
    """Commit the shot toward the observed point, then resolve the collision."""

    spec = WEAPONS[a["weapon"]]
    gap = w["tick"] - a["lastShot"]
    burst = 0 if gap > 4 else min(4, a["burst"] + 1)
    dist = distance(a, sight)
    accuracy = round(spec.accuracy + (a["aim"] - 70) * 0.5 - dist * 0.36 - burst * 5)
    a.update(
        ammo=a["ammo"] - 1,
        lastShot=w["tick"],
        burst=burst,
        ready=w["tick"] + spec.interval + (3 if burst >= 3 else 0),
    )
    event = emit(
        w,
        "shot",
        f"{a['name']} · {a['weapon']}",
        a["team"],
        player=a["id"],
        target=b["id"],
        x=a["x"],
        y=a["y"],
        tx=sight["x"],
        ty=sight["y"],
        accuracy=accuracy,
        burst=burst,
    )
    w["traces"].append(event)
    intersects = (
        b["hp"]
        and near_line(a, sight, b, 3)
        and engine.clear_line(a["x"], a["y"], b["x"], b["y"])
    )
    if engine._draw(a) % 100 < max(8, min(96, accuracy)) and intersects:
        head = engine._draw(a) % 100 < 14 + a["aim"] // 6
        amount = spec.damage * (3 if head else 1)
        if b["armor"] and not head:
            b["armor"] = max(0, b["armor"] - max(1, amount // 8))
            amount = int(amount * 0.76)
        damage(w, a, b, amount, a["weapon"], head)


def throw(w, a, target):
    name = target.get("utility") or a["utility"][0]
    a["utility"].remove(name)
    now = w["tick"]
    radius, duration = UTILITY[name]
    flight = max(3, round(distance(a, target) / 7))
    effect = dict(
        kind=name,
        player=a["id"],
        team=a["team"],
        x=target["x"],
        y=target["y"],
        sx=a["x"],
        sy=a["y"],
        start=now,
        land=now + flight,
        end=now + flight + duration,
        radius=radius,
    )
    w["effects"].append(effect)
    w["recentEffects"].append(effect)
    emit(
        w,
        "throw",
        f"{a['name']} · {name}",
        a["team"],
        **{k: v for k, v in effect.items() if k not in ("team", "kind")},
        utility=name,
    )
    a.update(throwAt=now + 45, ready=now + 5, status="Бросает гранату")


def apply_effects(w, ids):
    now = w["tick"]
    w["recentEffects"] = [f for f in w["recentEffects"] if f["end"] + 42 > now]
    w["effects"] = [f for f in w["effects"] if f["end"] > now]
    for f in w["effects"]:
        if now < f["land"] or f["kind"] == "Дым":
            continue
        if f["kind"] == "Огонь" and (now - f["land"]) % 5:
            continue
        for a in ids.values():
            dist = distance(f, a)
            if (
                not a["hp"]
                or dist > f["radius"]
                or not engine.clear_line(f["x"], f["y"], a["x"], a["y"])
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
                    9
                    if f["kind"] == "Огонь"
                    else max(1, round(73 * (1 - dist / f["radius"])))
                )
                damage(w, ids[f["player"]], a, amount, f["kind"])
