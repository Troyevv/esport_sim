"""The equipped weapon, the other gun slot and loose items on Depo."""

from math import hypot, isfinite

from . import engine
from .match_rules import SIDEARMS, WEAPONS


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
