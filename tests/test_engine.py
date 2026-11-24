import copy
import json
from math import pi

import pytest

from backend import engine


def test_map_is_connected_and_has_valid_starts_and_zones():
    origin = engine._cell(engine.MAP["spawns"][0]["x"], engine.MAP["spawns"][0]["y"])
    for cell in engine._FLOOR:
        assert cell == origin or engine.route(origin, cell)
    starts = engine.MAP["spawns"]
    assert len({(p["x"], p["y"]) for p in starts}) == 10
    assert all(engine._cell(p["x"], p["y"]) in engine._FLOOR_SET for p in starts)
    for zone in engine.MAP["zones"]:
        for x in range(zone["x"], zone["x"] + zone["w"], engine.CELL):
            for y in range(zone["y"], zone["y"] + zone["h"], engine.CELL):
                assert engine._cell(x, y) in engine._FLOOR_SET


def test_navigation_bends_around_opaque_wall():
    start, goal = (3, 5), (5, 5)
    assert not engine.clear_line(35, 55, 55, 55)
    walk = engine.route(start, goal)
    assert len(walk) > 2
    x, y = engine._center(start)
    for nx, ny in walk:
        assert abs(nx - x) + abs(ny - y) == engine.CELL
        assert engine.clear_line(x, y, nx, ny)
        x, y = nx, ny
    assert (x, y) == engine._center(goal)
    with pytest.raises(ValueError):
        engine.route(start, (4, 5))


def test_vision_depends_on_cone_range_and_wall():
    observer = dict(x=35, y=55, heading=0)
    assert not engine.sees(observer, dict(x=55, y=55))
    assert not engine.sees(observer, dict(x=25, y=55))
    observer["heading"] = pi
    assert engine.sees(observer, dict(x=25, y=55))
    observer.update(x=15, y=15, heading=0)
    assert not engine.sees(observer, dict(x=115, y=15))


def test_hidden_enemy_cannot_change_decision_or_disclose_live_position():
    world = engine.initial(7)
    scout, enemy = world["agents"][0], world["agents"][5]
    world["agents"] = [scout, enemy]
    scout.update(x=35, y=55, heading=0)
    enemy.update(x=55, y=55)
    twin = copy.deepcopy(world)
    twin["agents"][1]["y"] = 65
    for state in [world, twin]:
        engine._observe(state)
        assert [a["id"] for a in engine.project(state, "T")["agents"]] == [scout["id"]]
        engine.advance(state)
    assert world["agents"][0] == twin["agents"][0]


def test_last_known_position_does_not_follow_unseen_enemy():
    state = engine.initial(13)
    scout, opponent = state["agents"][0], state["agents"][5]
    state["agents"] = [scout, opponent]
    scout.update(x=25, y=55, heading=0)
    opponent.update(x=35, y=55)
    engine._observe(state)
    contact = engine.project(state, "T")["agents"][1]
    assert contact["id"] == opponent["id"] and not contact["knowledge"]
    opponent.update(x=55, y=55)
    state["tick"] = 1
    engine._observe(state)
    markers = engine.project(state, "T")["agents"]
    assert len(markers) == 1
    assert markers[0]["knowledge"] == [dict(id=opponent["id"], x=35, y=55, tick=0)]
    state["tick"] = engine.MEMORY_TICKS + 1
    engine._observe(state)
    assert not scout["knowledge"]


def test_snapshot_preserves_paths_rng_observations_and_continuation():
    state = engine.initial(123)
    for _ in range(95):
        engine.advance(state)
    assert any(a["path"] for a in state["agents"])
    restored = json.loads(json.dumps(state))
    for _ in range(250):
        engine.advance(state)
        engine.advance(restored)
        assert state == restored
        for a in state["agents"]:
            assert engine._cell(a["x"], a["y"]) in engine._FLOOR_SET


def test_batch_size_and_view_have_no_effect_on_core():
    states = [engine.initial(123) for _ in range(3)]
    for world, batch, view in zip(states, [1, 2, 8], ["T", "CT", "full"]):
        for _ in range(160 // batch):
            for _ in range(batch):
                engine.advance(world)
            engine.project(world, view)
    assert states[0] == states[1] == states[2]
    altered = engine.initial(124)
    for _ in range(160):
        engine.advance(altered)
    assert altered["agents"] != states[0]["agents"]


def test_line_of_sight_treats_diagonal_touch_of_wall_as_opaque():
    assert not engine.clear_line(35, 35, 45, 25)
    assert not engine.clear_line(45, 25, 35, 35)
