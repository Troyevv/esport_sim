from types import SimpleNamespace

from backend import cs2_defense as defense


def order(site, hold, watch, lane=0):
    return dict(site=site, lane=lane, hold=list(hold), watch=list(watch))


def test_reserve_uses_destination_sector_for_vision_and_for_friendly_smoke():
    actors = [dict(id="anchor", slot=0), dict(id="rotator", slot=2)]
    home = order("B", (120, 0, 0), (200, 0, 0))
    destination = order("A", (0, 0, 0), (64, 0, 0), 1)
    plan = dict(
        orders=dict(slots=[home, home, home]), backup=dict(id="rotator", **destination)
    )
    assert defense.assignment(plan, actors[1], actors)["lane"] == 1
    assert not defense.screen_safe(None, plan, actors[0], actors, (30, 0, 0))
    assert defense.screen_safe(None, plan, actors[0], actors, (30, 0, 48))


def test_trade_crossing_must_be_inside_the_anchors_current_field():
    anchor, wing = (0, 0, 0), (0, 10, 0)
    front, back = (12, 12, 0), (-12, 12, 0)
    seen = {anchor: [front, back], wing: [front, back]}
    results = defense.rank_crossfire(
        anchor, (0, -10, 0), [wing], seen, [front], wing, front
    )
    assert results == []


def test_predictions_use_only_report_time_and_reported_motion():
    space = SimpleNamespace(
        sector=lambda *args: ((12, 0, 0), (17, 0, 0), (60, 0, 0)),
        hit=lambda *args: None,
    )
    duty = order("A", (0, -10, 0), (60, 0, 0))
    sight = dict(
        x=0, y=0, z=0, id="T1", source="Радио", tick=100, speed=1, direction=[1, 0, 0]
    )
    assert defense.interpret(space, duty, [sight], 117, 65, 70) == (12, 0, 0)
    assert defense.interpret(space, duty, [sight], 117, 85, 70) == (17, 0, 0)
    assert defense.interpret(space, duty, [sight], 180, 85, 70) == (60, 0, 0)


def test_only_one_available_defender_checks_a_report_behind_the_assigned_angles():
    space = SimpleNamespace(hit=lambda *args: None, reported_site=lambda point: "A")
    jobs = [order("A", (0, 0, 0), (20, 0, 0)), order("A", (1, 0, 0), (20, 0, 0))]
    plan = dict(orders=dict(slots=jobs))
    sight = dict(id="T1", x=-8, y=0, z=0, tick=10, source="Радио", carryingC4=True)
    squad = [
        dict(
            id=f"CT{i}",
            slot=i,
            x=i,
            y=0,
            z=0,
            reloadAt=0,
            blind=0,
            visible=[],
            knowledge={"T1": sight},
        )
        for i in range(2)
    ]
    assert defense.breach_watch(space, plan, squad[0], squad, jobs[0], 20, 85) == (
        -8,
        0,
        0,
    )
    assert defense.breach_watch(space, plan, squad[1], squad, jobs[1], 20, 85) is None
    assert defense.breach_watch(space, plan, squad[0], squad, jobs[0], 50, 85) is None


def test_visible_body_orientation_changes_threat_assessment_without_private_state():
    from backend.cs2_intel import duel_priority

    actor = dict(x=0, y=0, z=0)
    skill = dict(game_reading=85, coordination=65)
    front = dict(id="T1", x=12, y=0, z=0, weapon="AK-47", bodySector=4)
    assert duel_priority(actor, front, set(), skill) < duel_priority(
        actor, dict(front, bodySector=0), set(), skill
    )


def test_sound_alone_cannot_identify_a_planter_and_friendly_crossing_stops_check():
    space = SimpleNamespace(site_at=lambda p: "A", shot_transmission=lambda *args: 1)
    actor = dict(
        x=0, y=0, z=0, blind=0, reloadAt=0, ready=0, ammo=8, weapon="USP", knowledge={}
    )
    cue = dict(site="A", bearing=[0, 0, 1, 0])
    assert defense.check_carrier(space, actor, [actor], cue, 11, 80) is None
    actor["knowledge"]["T2"] = dict(
        id="T2", x=16, y=0, z=0, source="Радио", tick=10, carryingC4=True
    )
    assert (
        defense.check_carrier(space, actor, [actor, dict(x=8, y=0, z=0)], cue, 11, 80)
        is None
    )
    assert defense.check_carrier(space, actor, [actor], cue, 11, 80) == dict(
        x=16, y=0, z=0
    )
    assert defense.check_carrier(space, actor, [actor], cue, 40, 80) is None


def test_shot_on_empty_map_point_records_ammo_and_no_victim():
    from backend import match, match_ai

    game = match.initial(41000)
    actor = game["agents"][0]
    original = actor["ammo"]
    match_ai.shoot(game, actor, dict(x=actor["x"] + 15, y=actor["y"], z=0), None)
    assert actor["ammo"] == original - 1
    assert game["traces"][-1]["target"] is None
    assert not any(e["kind"] == "damage" for e in game["events"])


def test_incoming_direction_can_override_an_empty_watch_but_expires_and_preserves_contact():
    from math import pi

    actor = dict(
        heading=0,
        x=0,
        y=0,
        z=0,
        visible=[],
        blind=0,
        knowledge={},
        incoming=dict(tick=100, bearing=[0, 0, -1, 0]),
    )
    defense.check_incoming(actor, "hold", 101, dict(game_reading=65))
    assert actor["heading"] == pi
    actor.update(heading=0, visible=["T2"])
    defense.check_incoming(actor, "hold", 102, dict(game_reading=65))
    assert actor["heading"] == 0
    actor["visible"].clear()
    defense.check_incoming(actor, "move", 114, dict(game_reading=85))
    assert actor["heading"] == 0


def test_stationary_personal_sight_does_not_need_an_invented_motion_vector():
    player = dict(skills=dict(game_reading=85))
    actor = dict(x=0, y=0, z=0)
    sight = dict(x=20, y=0, z=0, id="T2", tick=19, source="Зрение")
    assert defense.last_burst(None, actor, sight, [actor], player, 20) == sight
    assert defense.last_burst(None, actor, sight, [actor], player, 24) is None
    assert (
        defense.last_burst(
            None, actor, dict(sight, source="Радио"), [actor], player, 20
        )
        is None
    )
