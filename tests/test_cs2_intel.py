from copy import deepcopy

from backend import cs2_intel, match, match_ai


class SightLines:
    site_points = {"A": (60, 0, 0), "B": (0, 80, 0)}

    def __init__(self, observer):
        self.observer = observer

    def visible_pairs(self, pairs):
        return {(a["id"], b["id"]) for a, b in pairs if a is self.observer}

    def reported_site(self, pos):
        return "A" if pos[0] > 0 else "B"


def test_report_survives_observer_and_carries_only_observed_information():
    game = match.initial(17)
    scout, captain = game["agents"][:2]
    targets = game["agents"][5:7]
    space = SightLines(scout)
    for i, a in enumerate([scout, captain, *targets]):
        a.update(x=10 * i, y=0, z=0, heading=0)
    game["tick"] = 100
    match_ai.observe(game, [scout, captain, *targets], space)
    sight = scout["knowledge"][targets[0]["id"]]
    assert sight["groupSize"] == 2 and "direction" not in sight
    assert not captain["knowledge"]
    game["tick"] += 1
    targets[0].update(x=21, weapon="AWP")
    match_ai.observe(game, [scout, captain, *targets], space)
    sight = deepcopy(scout["knowledge"][targets[0]["id"]])
    assert sight["weapon"] == "AWP" and sight["direction"] == [1, 0, 0]
    assert not {"cash", "holster", "utility", "hp", "armor"}.intersection(sight)
    scout["hp"] = 0
    targets[0].update(x=115, weapon="Glock")
    for tick in range(102, 115):
        game["tick"] = tick
        match_ai.observe(game, [captain, *targets], space)
    delivered = captain["knowledge"][targets[0]["id"]]
    assert delivered == dict(sight, source="Радио")
    pressure = cs2_intel.pressure(space, [delivered], 114)
    assert cs2_intel.pressure(space, [delivered, sight], 114) == pressure
    assert 0 < cs2_intel.pressure(space, [delivered], 155)["A"] < pressure["A"]
    game["tick"] = 177
    match_ai.observe(game, [captain, *targets], space)
    assert not captain["knowledge"]


def test_direction_and_equipment_affect_calls_without_tracking_target():
    space = SightLines(None)
    pos = dict(id="enemy", x=10, y=0, z=0, tick=10, source="Радио", weapon="AWP")
    toward = dict(pos, direction=[1, 0, 0])
    away = dict(pos, direction=[-1, 0, 0])
    assert (
        cs2_intel.pressure(space, [toward], 12)["A"]
        > cs2_intel.pressure(space, [away], 12)["A"]
    )
    space.hit = lambda *args: None
    order = {"via": [[60, 0, 0]]}
    assert cs2_intel.sniper_lane(space, [pos], order, 15)
    assert not cs2_intel.sniper_lane(space, [dict(pos, weapon="Glock")], order, 15)
    assert not cs2_intel.sniper_lane(space, [pos], order, 50)
    space.hit = lambda *args: object()
    assert not cs2_intel.sniper_lane(space, [pos], order, 15)


def test_bomb_report_is_dated_and_sound_is_not_a_second_player():
    space = SightLines(None)
    sight = dict(id="T1", x=10, y=0, z=0, tick=100, source="Радио", carryingC4=True)
    sound = dict(id="Шум", x=22, y=0, z=0, tick=148, source="Слух")
    assert cs2_intel.pressure(space, [sight, sound], 102)["A"] > 1.65
    assert cs2_intel.pressure(space, [sight, sound], 150)["A"] < 1
    assert cs2_intel.pressure(space, [sight, sound], 176)["A"] == 0
