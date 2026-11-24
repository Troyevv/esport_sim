"""Versioned balance for the fictional Depo BO1 exhibition, in 100 ms ticks."""

from dataclasses import dataclass
from . import engine

VERSION = "depo-bo1.1"
RULES = dict(half=12, overtimeHalf=3, freeze=45, live=1150, fuse=400,
             plant=32, defuse=100, kitDefuse=50, result=35, timeouts=3,
             startMoney=800, overtimeMoney=10000, cap=16000, win=3250,
             objectiveWin=3500, lossBase=1400, lossStep=500, lossMax=3400,
             plantBonus=800, planter=300, defuser=300)
CLUBS = ("Север", "Контур")
ROLES = ("Капитан", "Энтри", "Опора", "Снайпер", "Поддержка")
MAP = dict(engine.MAP, version=2, zones=[dict(name="A", **engine._rect(22, 1, 4, 3)),
                                       dict(name="B", **engine._rect(20, 15, 3, 4))])
# Ordered execution slots. Attack positions also serve as post-plant cover.
POSITIONS = {
    "A": [(235, 35), (225, 45), (255, 25), (195, 45), (245, 45)],
    "B": [(215, 165), (205, 155), (225, 175), (195, 185), (235, 165)],
}
STAGING = {"A": [(155, 55), (165, 65), (155, 65), (145, 55), (165, 55)],
           "B": [(155, 145), (165, 135), (155, 155), (135, 145), (165, 145)]}


@dataclass(frozen=True)
class Weapon:
    price: int
    mag: int
    damage: int
    interval: int
    reload: int
    accuracy: int
    reward: int


WEAPONS = {
    "Glock": Weapon(0, 20, 25, 3, 23, 66, 300),
    "USP": Weapon(0, 12, 31, 3, 22, 70, 300),
    "MP9": Weapon(1250, 30, 26, 1, 21, 65, 600),
    "MAC-10": Weapon(1050, 30, 26, 1, 23, 63, 600),
    "AK-47": Weapon(2700, 30, 36, 1, 25, 75, 300),
    "M4A1-S": Weapon(2900, 20, 35, 1, 31, 79, 300),
    "AWP": Weapon(4750, 5, 115, 15, 36, 87, 100),
}
PRICES = {"Броня": 650, "Набор": 400, "Дым": 300, "Свет": 200, "Огонь": 500, "HE": 300}
UTILITY = {"Дым": (20, 130), "Свет": (48, 1), "Огонь": (16, 63), "HE": (35, 1)}
CALLS = ("Капитану", "Выход A", "Выход B", "Ускориться", "Экономить")
