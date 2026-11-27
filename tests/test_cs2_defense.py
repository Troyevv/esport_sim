from types import SimpleNamespace

from tests.reference_kernel import cs2_defense as defense


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
        sector=lambda *args: ((4, 0, 0), (7, 0, 0), (17, 0, 0), (60, 0, 0)),
        hit=lambda *args: None,
    )
    duty = order("A", (0, -10, 0), (60, 0, 0))
    sight = dict(
        x=0,
        y=0,
        z=0,
        id="T1",
        source="Радио",
        tick=100,
        speed=1,
        direction=[1, 0, 0],
        motionRun=1,
    )
    assert defense.interpret(space, duty, [sight], 117, 65, 70) == (7, 0, 0)
    assert defense.interpret(space, duty, [sight], 117, 85, 70) == (4, 0, 0)
    assert defense.interpret(space, duty, [dict(sight, motionRun=17)], 117, 85, 70) == (
        17,
        0,
        0,
    )
    assert defense.interpret(space, duty, [sight], 180, 85, 70) == (60, 0, 0)
    assert defense.anticipated(space, sight, 100, 85) == (0, 0, 0)


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
    from tests.reference_kernel.cs2_intel import duel_priority

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
    from tests.reference_kernel import match, match_ai

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


def test_guard_reports_only_the_visible_entrance_and_reports_smoke_without_enemy_ids():
    from math import pi

    point = (24, 0, 0)
    actor = dict(
        id="CT1",
        slot=0,
        x=0,
        y=0,
        z=0,
        heading=pi,
        blind=0,
        reloadAt=0,
        ammo=20,
        visible=[],
        knowledge={},
    )
    plan = dict(orders=dict(slots=[order("A", (0, 0, 0), point)]))
    space = SimpleNamespace(ingress=lambda *_: [point], hit=lambda *_: None)
    assert defense.report_crossing(space, actor, [actor], plan, [], 10) is None
    actor["heading"] = 0
    smoke = [dict(x=12, y=0, z=0, radius=3)]
    result = defense.report_crossing(space, actor, [actor], plan, smoke, 10)
    assert result == dict(
        site="A", lane=0, point=list(point), tick=10, state="obscured"
    )
    assert (
        defense.report_crossing(space, actor, [actor], plan, [], 10)["state"]
        == "watching"
    )


def test_support_uses_recent_radio_and_checks_geometry_between_landing_and_friend():
    from tests.reference_kernel.cs2_play import assist_contact

    actor = dict(team="CT", x=0, y=0, z=0, utility=["HE"])
    mate = dict(x=60, y=2, z=0, reloadAt=0, hp=100)
    sight = dict(x=60, y=0, z=0, tick=10, source="Радио")
    squad = [actor, mate]
    space = SimpleNamespace(
        grenade=lambda start, end, ticks: (*end, 0), hit=lambda *_: None
    )

    def decide(now, report):
        return assist_contact(
            space,
            actor,
            [mate],
            report,
            squad,
            {},
            now,
            dict(game_reading=75),
            "planted",
        )

    assert decide(11, sight) is None
    space.hit = lambda start, end, *_: True if end[1] == 2 else None
    assert decide(11, sight)[1]["utility"] == "HE"
    assert decide(28, sight) is None
    assert decide(11, dict(sight, source="Слух")) is None


def test_pressure_request_expires_without_creating_an_opponent():
    space = SimpleNamespace(
        reported_site=lambda origin: "A" if origin == (2, 3, 0) else "B"
    )
    leader = dict(squadPressure={"CT2": dict(origin=[2, 3, 0], tick=40)})
    assert defense.help_site(space, leader, 41) == "A"
    assert defense.help_site(space, leader, 70) is None


def test_order_feedback_requires_physical_arrival_and_resets_on_reassignment():
    from tests.reference_kernel import cs2_defense

    p = dict(id="one", slot=0, x=20, y=0, z=0, visible=[], hp=100)
    order = dict(id="one", hold=[45, 0, 0], site="B", lane=1)
    plan = dict(orders=dict(slots=[order]), backup=order)
    assert cs2_defense.duty_feedback(plan, p, [p], 10)["state"] == "moving"
    assert cs2_defense.duty_feedback(plan, p, [p], 15) is None
    p["blockedTicks"] = 5
    assert cs2_defense.duty_feedback(plan, p, [p], 20)["state"] == "blocked"
    p.update(blockedTicks=0, x=42)
    assert cs2_defense.duty_feedback(plan, p, [p], 25)["state"] == "arrived"
    order.update(site="A", hold=[4, 0, 0])
    assert cs2_defense.duty_feedback(plan, p, [p], 30)["state"] == "moving"
