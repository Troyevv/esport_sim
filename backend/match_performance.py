"""Local execution costs in map units, 100 ms ticks and percentage points."""

from math import pi

WEAPON_CLASS = {
    "Glock": "pistols",
    "USP": "pistols",
    "MP9": "smgs",
    "MAC-10": "smgs",
    "AK-47": "rifles",
    "M4A1-S": "rifles",
    "AWP": "sniper_rifles",
    "Nova": "shotguns",
    "Negev": "machine_guns",
}
GRENADE_SKILL = {
    "Дым": "smokes",
    "Свет": "flashes",
    "HE": "he",
    "Огонь": "incendiaries",
    "Ложная": "decoys",
}


def acquisition(s, angle, switching, peeking, opening, trading, alone):
    ticks = 1 + (100 - s["reaction"]) / 23 + abs(angle) / pi * (100 - s["flick"]) / 11
    if switching:
        ticks += (100 - s["target_switch"]) / 20
    if peeking:
        ticks += (100 - s["peeking"]) / 25
    if opening:
        ticks += (100 - s["entry"]) / 30
    if trading:
        ticks -= s["trades"] / 35
    if alone:
        ticks += (100 - s["clutch"]) / 24
    return max(1, round(ticks))


def accuracy(player, a, spec, dist, burst, now):
    s = player["skills"]
    # Aim locates the target. Weapon handling converts that aim at range.
    base = spec.accuracy + (s["aim"] - 65) * 0.19
    falloff = 0.95 if a["weapon"] == "Nova" else 0.36
    base -= dist * falloff * (1.4 - s[WEAPON_CLASS[a["weapon"]]] / 140)
    if burst:
        base -= burst * (8 - s["recoil"] * 0.065)
    else:
        base += (s["first_shot"] - 65) * 0.10
    base -= min(3, a["observedSpeed"]) * (100 - s["tracking"]) / 16
    base -= max(0, 6 - (now - a["lastMove"])) * (100 - s["counter_strafe"]) / 30
    base += a["dayRoll"] * (100 - s["consistency"]) / 100
    base += (player["form"] - 50) / 12
    base -= a["pressure"] * (100 - s["stress_resistance"]) / 10
    base -= min(1, (now - a["liveStart"]) / 850) * (100 - s["concentration"]) / 12
    base -= max(0, 12 - (now - a["lastHurt"])) * (100 - s["composure"]) / 110
    return max(8, min(96, round(base)))


def move_speed(player):
    s = player["skills"]
    return (
        0.82
        + s["movement"] * 0.003
        - player["fatigue"] * (110 - s["fatigue_resistance"]) / 35000
    )


def next_fatigue(player, moving_ticks):
    s = player["skills"]
    load = round(moving_ticks * (150 - s["endurance"]) / 2100)
    rest = 1 + s["recovery"] // 15
    return min(100, max(0, player["fatigue"] + load - rest))


def commit_ticks(s, morale):
    # How long a player will stick to a nearly completed objective under fire.
    return 3 + s["confidence"] // 10 + morale // 30


def retake_margin(s, distance, weapon_price):
    # An inexperienced defender budgets more travel time. Risk is a preference.
    navigation = min(50, distance / 2) * (100 - s["retakes"]) / 100
    save_margin = (50 - s["risk"]) * min(1, weapon_price / 3000) / 2
    return navigation + save_margin


def pursuit_window(s, sound):
    if sound:
        return 8 + (100 - s["patience"]) // 3
    return 12 + s["aggression"] // 2


def staging_ticks(s, separated):
    return (
        65 + (100 - s["timing"]) // 3 + (s["synchronization"] // 3 if separated else 0)
    )


def grenade_landing(a, target, mastery, roll):
    # A miss falls short on the validated throw segment, never through a wall.
    error = min(1, ((100 - mastery) / 100) * ((roll % 17) / 100))
    return tuple(round(target[k] + (a[k] - target[k]) * error) for k in ("x", "y"))
