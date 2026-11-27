"""Versioned balance for the fictional Depo BO1 exhibition, in 100 ms ticks."""

from dataclasses import dataclass

from . import engine

LEGACY_VERSION = "depo-bo1.1"
PREVIOUS_VERSION = "depo-bo1.2"
SCOREBOT_VERSION = "depo-bo1.3"
VERSION = "depo-bo1.4"
RULES = dict(
    half=12,
    overtimeHalf=3,
    freeze=45,
    live=1150,
    fuse=400,
    plant=32,
    defuse=100,
    kitDefuse=50,
    result=35,
    timeouts=3,
    startMoney=800,
    overtimeMoney=10000,
    cap=16000,
    win=3250,
    objectiveWin=3500,
    lossBase=1400,
    lossStep=500,
    lossMax=3400,
    plantBonus=800,
    planter=300,
    defuser=300,
)
CLUBS = ("Север", "Контур")
ROLES = ("Капитан", "Энтри", "Опора", "Снайпер", "Поддержка")
MAP = dict(
    engine.MAP,
    version=2,
    zones=[
        dict(name="A", **engine._rect(22, 1, 4, 3)),
        dict(name="B", **engine._rect(20, 15, 3, 4)),
    ],
)
# Ordered execution slots. Attack positions also serve as post-plant cover.
POSITIONS = {
    "A": [(235, 35), (225, 45), (255, 25), (195, 45), (245, 45)],
    "B": [(215, 165), (205, 155), (225, 175), (195, 185), (235, 165)],
}
STAGING = {
    "A": [(155, 55), (165, 65), (155, 65), (145, 55), (165, 55)],
    "B": [(155, 145), (165, 135), (155, 155), (135, 145), (165, 145)],
}


# The built-in plans bind five role slots to walkable approach and hold points.
# Mirrored pairs take different corridors before converging on the announced site.
APPROACH = {
    "A": [(145, 55), (105, 15), (125, 65), (105, 25), (145, 65)],
    "B": [(145, 145), (125, 185), (145, 155), (135, 185), (135, 145)],
}


def role_orders(side, site):
    slots = []
    for slot in range(5):
        anchor = site if side == "T" or slot == 4 else ("A" if slot in (0, 2) else "B")
        slots.append(
            dict(
                role=ROLES[slot],
                approach=list(APPROACH[anchor][slot]),
                stage=list(STAGING[anchor][slot]),
                hold=list(POSITIONS[anchor][slot]),
            )
        )
    return dict(version=1, map=MAP["id"], geometry=MAP["version"], slots=slots)


@dataclass(frozen=True)
class Weapon:
    price: int
    mag: int
    damage: int
    interval: int
    reload: int
    accuracy: int
    reward: int
    penetration: float
    falloff: float
    head_multiplier: float = 4.0
    pellets: int = 1


SIDEARMS = frozenset(("Glock", "USP", "Desert Eagle"))

WEAPONS = {
    "Desert Eagle": Weapon(700, 7, 53, 4, 23, 70, 300, 0.93, 0.81),
    "Glock": Weapon(0, 20, 30, 3, 23, 66, 300, 0.47, 0.85),
    "USP": Weapon(0, 12, 35, 3, 22, 70, 300, 0.505, 0.91),
    "MP9": Weapon(1250, 30, 26, 1, 21, 65, 600, 0.60, 0.87),
    "MAC-10": Weapon(1050, 30, 29, 1, 23, 63, 600, 0.575, 0.80),
    "AK-47": Weapon(2700, 30, 36, 1, 25, 75, 300, 0.775, 0.98),
    "M4A1-S": Weapon(2900, 20, 38, 1, 31, 79, 300, 0.70, 0.94, 3.475),
    "Nova": Weapon(1050, 8, 26, 8, 30, 82, 900, 0.50, 0.70, pellets=9),
    "Negev": Weapon(1700, 150, 35, 1, 55, 62, 300, 0.71, 0.97),
    "AWP": Weapon(4750, 5, 115, 15, 36, 87, 100, 0.975, 0.99),
}
PRICES = {
    "Ложная": 50,
    "Броня": 650,
    "Шлем": 350,
    "Набор": 400,
    "Дым": 300,
    "Свет": 200,
    "Огонь": 500,
    "HE": 300,
}
THROW_RECOVERY = 5
UTILITY = {
    "Ложная": (55, 41),
    "Дым": (20, 130),
    "Свет": (48, 1),
    "Огонь": (16, 63),
    "HE": (35, 1),
}
CALLS = ("Капитану", "Выход A", "Выход B", "Ускориться", "Экономить")


def equipment_value(a):
    return (
        WEAPONS[a["weapon"]].price
        + (WEAPONS[a["holster"]["weapon"]].price if a.get("holster") else 0)
        + (PRICES["Броня"] if a["armor"] else 0)
        + (PRICES["Шлем"] if a["helmet"] else 0)
        + (PRICES["Набор"] if a["kit"] else 0)
        + sum(PRICES[item] for item in a["utility"])
    )


BLAST_RADIUS = 80


def blast_damage(distance):
    return max(0, round(370 * (1 - distance / BLAST_RADIUS)))


WEAPON_CLASS = {
    "Glock": "pistols",
    "USP": "pistols",
    "Desert Eagle": "pistols",
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


PISTOL, ECO, HALF, FORCE, FULL = "Пистолетная", "Эко", "Частичная", "Форс", "Полная"
ANTI, BONUS = "Антиэко", "Бонусная"
SCENARIOS = (PISTOL, ECO, HALF, FORCE, FULL, ANTI, BONUS)
SMG = {"T": "MAC-10", "CT": "MP9"}
