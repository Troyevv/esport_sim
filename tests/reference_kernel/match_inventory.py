"""The equipped weapon, the other gun slot and loose items on Depo."""

from math import hypot, isfinite

from backend import engine
from backend.match_rules import SIDEARMS, WEAPONS


def stocked(name):
    mag = WEAPONS[name].mag
    return dict(weapon=name, ammo=mag, reserve=mag * 3)


def in_hand(a):
    return {key: a[key] for key in ("weapon", "ammo", "reserve")}


def slots(a):
    primary = secondary = None
    for item in (a, a["holster"]):
        if item is not None:
            if item["weapon"] in SIDEARMS:
                secondary = item["weapon"]
            else:
                primary = item["weapon"]
    return primary, secondary


def equip(a, item):
    """Install in the matching slot. Prefer a primary with usable ammunition."""
    active = in_hand(a)
    if (item["weapon"] in SIDEARMS) == (active["weapon"] in SIDEARMS):
        a.update(item, reloadAt=0)
    elif item["weapon"] not in SIDEARMS or not (active["ammo"] or active["reserve"]):
        a.update(item, holster=active, reloadAt=0)
    else:
        a["holster"] = item


def switch_if_empty(a):
    spare = a["holster"]
    if (
        not (a["ammo"] or a["reserve"])
        and spare
        and (spare["ammo"] or spare["reserve"])
    ):
        a.update(spare, holster=in_hand(a), reloadAt=0)


def drop_on_death(w, a, kill_id):
    # One retrievable gun per death, preferring the primary even when holstered.
    item = (
        a["holster"]
        if a["holster"] and a["holster"]["weapon"] not in SIDEARMS
        else in_hand(a)
    )
    w["groundWeapons"].append(dict(id=kill_id, **{k:a[k] for k in ("x","y","z") if k in a}, **item))


def take_nearby(w, a, space=None):
    if not w["groundWeapons"] or a["blind"] > w["tick"]:
        return None
    primary, secondary = slots(a)
    for index, gun in enumerate(w["groundWeapons"]):
        name = gun["weapon"]
        if name in SIDEARMS:
            if secondary and WEAPONS[secondary].price >= WEAPONS[name].price:
                continue
        elif primary:
            continue
        if (
            not (gun["ammo"] or gun["reserve"])
            or hypot(a["x"] - gun["x"], a["y"] - gun["y"],a.get("z",0)-gun.get("z",0)) > 6
        ):
            continue
        if not (space.clear(a,gun) if space else engine.clear_line(a["x"], a["y"], gun["x"], gun["y"])):
            continue
        w["groundWeapons"].pop(index)
        if name in SIDEARMS and secondary:
            previous = a if a["weapon"] == secondary else a["holster"]
            # The exchanged sidearm takes the same place on the ground.
            w["groundWeapons"].append(
                dict(id=gun["id"], **{k:a[k] for k in ("x","y","z") if k in a}, **in_hand(previous))
            )
        equip(a, in_hand(gun))
        return gun
    return None


def upgrade(w):
    w["groundWeapons"] = []
    for a in w["agents"]:
        a["holster"] = (
            None
            if a["weapon"] in SIDEARMS
            else stocked("Glock" if a["team"] == "T" else "USP")
        )


def validate(w):
    def valid(gun):
        return (
            gun["weapon"] in WEAPONS
            and all(type(gun[k]) is int and gun[k] >= 0 for k in ("ammo", "reserve"))
            and gun["ammo"] <= WEAPONS[gun["weapon"]].mag
        )

    for a in w["agents"]:
        spare = a["holster"]
        if not valid(a) or (
            spare is not None
            and (
                not valid(spare)
                or (spare["weapon"] in SIDEARMS) == (a["weapon"] in SIDEARMS)
            )
        ):
            raise ValueError("Некорректные слоты оружия")
    ids = set()
    for gun in w["groundWeapons"]:
        if (
            not valid(gun)
            or gun["id"] in ids
            or not all(isfinite(gun[k]) for k in ("x", "y"))
        ):
            raise ValueError("Некорректное оружие на карте")
        ids.add(gun["id"])
