"""Versioned permanent player attributes. Integer points, inclusive range 0..100."""

VERSION = 1
RATING_VERSION = 1
GROUPS = {
    "mechanics": "aim reaction flick tracking recoil first_shot burst_control target_switch movement counter_strafe peeking",
    "equipment": "pistols rifles sniper_rifles smgs shotguns machine_guns flashes smokes he incendiaries decoys",
    "tactics": "positioning game_reading decisions timing map_control entry lurking clutch retakes postplant adaptability discipline",
    "team": "communication coordination leadership calling trades support synchronization execution",
    "mentality": "consistency concentration stress_resistance composure confidence patience aggression risk motivation professionalism ambition loyalty learning",
    "physical": "endurance fatigue_resistance recovery",
}
KEYS = tuple(key for group in GROUPS.values() for key in group.split())
HIDDEN = frozenset(
    "consistency stress_resistance composure discipline adaptability motivation professionalism ambition loyalty learning".split()
)
DEPENDENCIES = {
    "motivation": "R5 · вовлечённость в занятие",
    "professionalism": "R5 · соблюдение тренировочной нагрузки",
    "learning": "R5 · прирост освоения после занятия",
    "ambition": "R6 · спортивные цели при переговорах",
    "loyalty": "R6 · решение о продлении контракта",
}

# Scout-safe report weights. Style and private qualities are excluded by design.
ROLE_WEIGHTS = {
    "rifler": {"aim": 3, "rifles": 3, "tracking": 2, "recoil": 2, "positioning": 2},
    "entry": {"entry": 3, "peeking": 2, "reaction": 2, "first_shot": 2, "timing": 1},
    "lurker": {"lurking": 3, "map_control": 2, "timing": 2, "patience": 2, "aim": 1},
    "support": {
        "support": 3,
        "coordination": 2,
        "trades": 2,
        "flashes": 1,
        "smokes": 2,
    },
    "awper": {"sniper_rifles": 4, "flick": 2, "first_shot": 2, "positioning": 2},
    "igl": {
        "calling": 3,
        "leadership": 2,
        "game_reading": 2,
        "decisions": 2,
        "communication": 1,
    },
}


def points(value):
    if type(value) is not int or not 0 <= value <= 100:
        raise ValueError("Оценка должна быть целым числом от 0 до 100")
    return value


def role_rating(skills, role):
    weights = ROLE_WEIGHTS[role]
    return round(
        sum(skills[k] * weight for k, weight in weights.items()) / sum(weights.values())
    )
