"""Exercise native grenade actions, perception, checkpoint continuation and viewer projection."""
from copy import deepcopy
import json
import math

import pytest

from backend import match, native_match_state
from backend.store import Store
from tests.test_individual_decision import decide
from tests.test_server import envelope


def arena():
    w = match.initial(41)
    match.advance(w, 45)
    for a in w["agents"]:
        a.update(hp=0, visible=[], knowledge={}, heading=0, x=45, y=105, utility=[],
                 ready=0, reloadAt=0, ammo=5, armor=0)
    w["agents"][0].update(hp=100, x=35)
    w["agents"][5].update(hp=100, x=75, heading=math.pi)
    return w


def effect(w, item, x=55, y=105, age=0, owner=0):
    a = w["agents"][owner]
    radius, duration = {"Свет": (48, 1), "Дым": (20, 200), "HE": (35, 1),
                        "Огонь": (16, 70), "Ложная": (55, 150)}[item]
    land = w["tick"] - age
    row = dict(player=a["id"], team=a["team"], kind=item, x=x, y=y, sx=x, sy=y,
               start=land-4, land=land, end=land+duration, radius=radius)
    w["effects"].append(row)
    w["recentEffects"].append(row.copy())


def step(w, op="apply_effects", *args):
    owner = native_match_state.open_game(w)
    getattr(owner, op)(*args)
    return json.loads(owner.snapshot())


def fire(w, index, x, y, item=None):
    actor = w["agents"][index]
    if item:
        actor["utility"] = [item]
    aim = dict(x=x, y=y, z=actor.get("z", 0))
    if item:
        aim["utility"] = item
    return step(w, "resolve_actions", json.dumps([dict(actor=actor["id"], kind="throw" if item else "shoot", target=aim)]))


def test_flash_angles_distance_wall_recovery_and_overlap():
    def exposure(x, heading, burst=65):
        w = arena()
        w["agents"][0].update(x=x, heading=heading)
        effect(w, "Свет", burst)
        return step(w)
    full = exposure(50, 0)
    side = exposure(50, math.pi/2)
    back = exposure(50, math.pi)
    far = exposure(20, 0)
    level = lambda w: w["agents"][0].get("flashLevel", 0)
    assert level(full) >= .78 > level(side) > level(back) > 0
    assert level(full) > level(far) > 0
    assert level(exposure(95, 0, 115)) == 0  # Stone partition between x=95 and x=115.
    full["tick"] += 24
    fading = step(full)
    assert 0 < level(fading) < level(full)
    fading["agents"][0]["heading"] = math.pi
    effect(fading, "Свет", 65)
    again = step(fading)
    assert level(again) > level(fading)
    again["tick"] += 60
    assert level(step(again)) == 0


def test_blind_fire_uses_only_memory_and_does_not_track_hidden_opponent():
    w = arena()
    a, b = w["agents"][0], w["agents"][5]
    a.update(knowledge={b["id"]: dict(id=b["id"], x=56, y=105, tick=w["tick"]-2, source="Зрение")},
             groupDuty={"ticket": ["CT1", "test", 1]})
    w["domain"]["players"][a["playerId"]]["skills"]["aggression"] = 100
    effect(w, "Свет")
    w = step(step(w), "observe")
    def action(state):
        command, actor = decide(state, 0)
        assert actor["visible"] == [] and command[0] == "shoot"
        assert "id" not in command[1]
        return command[1]
    target = action(w)
    assert target["x"] == 56
    w["agents"][5]["x"] += 14
    assert action(step(w, "observe")) == target
    shot = fire(w, 0, target["x"], target["y"])
    healthy = deepcopy(w)
    healthy["agents"][0]["flashLevel"] = 0
    assert shot["traces"][-1]["accuracy"] < fire(healthy, 0, 56, 105)["traces"][-1]["accuracy"]


def test_flash_assist_requires_recent_impairment_and_distinct_teammate():
    w = arena()
    w["agents"][1].update(hp=100, x=36)
    effect(w, "Свет", x=68)
    w = step(w)
    # Let the defender actually decide how to react to losing sight.
    _, victim = decide(w, 5)
    w["agents"][5] = victim
    victim.update(hp=1)
    def kill(state, index):
        effect(state, "HE", x=75, owner=index)
        state["tick"] += 1
        state["effects"][-1]["land"] += 1
        state["effects"][-1]["end"] += 1
        return step(state)["kills"][-1]
    assert kill(deepcopy(w), 1)["flashAssist"] == w["agents"][0]["id"]
    assert "flashAssist" not in kill(deepcopy(w), 0)
    w["tick"] += 55
    assert "flashAssist" not in kill(w, 1)


def test_smoke_edge_he_and_bullet_channels_reclose_and_extinguish_fire():
    w = arena()
    effect(w, "Дым", age=20)
    w = step(w)
    assert not step(w, "observe")["agents"][0]["visible"]
    # Move both agents parallel to the blocked line, just outside the cloud.
    outside = deepcopy(w)
    for i in (0, 5):
        outside["agents"][i]["y"] = 135
    assert step(outside, "observe")["agents"][0]["visible"]
    inside = deepcopy(w)
    inside["agents"][0]["x"] = 55
    assert not step(inside, "observe")["agents"][0]["visible"]
    for kind in ("HE", "shot"):
        fork = deepcopy(w)
        if kind == "HE":
            effect(fork, "HE")
            fork = step(fork)
        else:
            fork = fire(fork, 0, 75, 105)
        assert step(fork, "observe")["agents"][0]["visible"]
        fork["tick"] += 18
        assert not step(step(fork), "observe")["agents"][0]["visible"]
    effect(w, "Огонь", age=8)
    w = step(w)
    assert w["stats"][w["agents"][0]["id"]]["firesQuenched"] == 1
    assert all(c.get("out") for c in w["effects"][-1]["lobes"])


def test_he_armor_allies_self_and_cover():
    w = arena()
    for a in [w["agents"][0], w["agents"][1], w["agents"][5]]:
        a.update(hp=100, x=70)
    w["agents"][1]["armor"] = 100
    w["agents"][6].update(hp=100, x=115)
    effect(w, "HE", x=87)
    w = step(w)
    hp = [p["hp"] for p in w["agents"]]
    assert hp[0] == hp[5] < hp[1] < 100 == hp[6]
    assert w["agents"][1]["armor"] < 100
    assert w["stats"][w["agents"][0]["id"]]["heDamage"] == 100-hp[5]


def test_fire_variants_growth_smoke_expiry_and_decoy_audio():
    w = arena()
    for idx, duration, variant in ((0, 70, "Molotov"), (5, 55, "Incendiary")):
        thrown = fire(deepcopy(w), idx, 55, 105, "Огонь")["effects"][-1]
        assert thrown["end"] - thrown["land"] == duration and thrown["variant"] == variant
    effect(w, "Дым")
    early = step(w)
    size = lambda state: sum(c["reach"] for c in state["effects"][0]["lobes"])
    mid = step(dict(early, tick=w["tick"]+20))
    late = step(dict(mid, tick=w["tick"]+197))
    assert size(mid) > size(early) > 0 and size(mid) > size(late) > 0
    assert not step(dict(late, tick=w["tick"]+200))["effects"]
    w = arena()
    decoy = fire(w, 0, 55, 105, "Ложная")
    decoy["tick"] = decoy["effects"][0]["land"]
    sounded = step(decoy)
    heard = sounded["agents"][5]["knowledge"]["Шум · Выстрел"]
    assert heard["sound"] == "Выстрел" and heard["source"] == "Слух"
    assert "player" not in heard and "Ложная" not in str(heard)
    assert any(m.get("sight") == heard for m in sounded["messages"])


def test_active_and_manual_checkpoint_preserve_grenade_state(tmp_path):
    w = arena()
    # Use a complete living roster when exercising the regular match continuation.
    for a in w["agents"]:
        a["hp"] = 100
    effect(w, "Дым", age=15)
    effect(w, "Свет")
    w = step(w)
    path = tmp_path / "effects.sqlite"
    store = Store(path)
    state = store.read()
    state["world"] = w
    with store.transaction():
        store.write(state)
    store.apply(envelope(store.read(), "save"))
    store.db.close()
    store = Store(path)
    active = store.read()["world"]
    store.apply(envelope(store.read(), "load"))
    expected = native_match_state.open_game(w)
    expected.advance(28)
    for saved in (active, store.read()["world"]):
        owner = native_match_state.open_game(saved)
        for n in (1, 5, 22):
            owner.advance(n)
        assert owner.snapshot() == expected.snapshot()
    store.db.close()


def test_warn_turn_and_group_release_follow_real_flight():
    from tests.test_group_tasks import at_waypoint, notice
    from tests.test_peer_radio import delivered
    from tests.test_small_groups import execute, member

    w, lead, _ = at_waypoint()
    w["agentPolicy"] = 6
    packet = notice(w, "stage")
    wing = packet["feedback"]["members"][0]
    origin = packet["feedback"]["origin"]
    packet["feedback"]["point"] = [origin[0]+14, *origin[1:]]
    w["agents"][member(w, lead)]["sentFeedback"]["stage"] = deepcopy(packet["feedback"])
    w["agents"][member(w, wing)]["utility"] = ["Свет"]
    intent, staged = execute(delivered(w, packet["due"]), wing)
    assert intent[0] == "hold" and not staged["effects"]
    warn = next(m for m in staged["messages"] if "flashWarning" in m)
    assert "flashWarning" not in delivered(staged, warn["due"]-1)["agents"][member(w, lead)]
    staged = delivered(staged, warn["due"])
    intent, staged = execute(staged, wing)
    assert intent[0] == "throw"
    cast = step(staged, "resolve_actions", json.dumps([dict(actor=wing, kind="throw", target=intent[1])]))
    f = cast["effects"][-1]
    assert f["trajectory"][-1] == [f["x"], f["y"], f["z"]]
    before = delivered(cast, f["land"]-1)
    command, waiting = execute(before, lead)
    assert command[0] == "hold"
    actor = waiting["agents"][member(w, lead)]
    assert actor["status"] == "Отворачивается от флешки"
    angle = actor["heading"]
    assert (f["x"]-actor["x"])*math.cos(angle)+(f["y"]-actor["y"])*math.sin(angle) < 0
    armed = max(f["land"], cast["agents"][member(w, wing)]["ready"])
    popped = step(dict(cast, tick=f["land"]))
    assert popped["recentEffects"][-1]["burstTick"] == f["land"]
    _, ready = execute(delivered(popped, armed), wing)
    msg = notice(ready, "set")
    _, launch = execute(delivered(ready, msg["due"]), lead)
    assert notice(launch, "go")["feedback"]["at"] >= f["land"]


def test_decoy_and_real_shots_share_anonymous_audio_and_reading_changes_confidence():
    w = arena()
    a, b = w["agents"][0], w["agents"][5]
    # Only the auditory channel is available to the defender.
    a["weapon"] = "Glock"
    w["domain"]["players"][b["playerId"]]["skills"]["game_reading"] = 95
    effect(w, "Ложная", x=a["x"])
    w["effects"][0]["weapon"] = "Glock"
    fake = step(w)
    normal = deepcopy(w)
    normal["effects"].clear()
    normal = fire(normal, 0, 40, 105)
    key = "Шум · Выстрел"
    hear = lambda state: state["agents"][5]["knowledge"][key]
    assert hear(fake) == hear(normal)
    novice = deepcopy(fake)
    novice["domain"]["players"][b["playerId"]]["skills"]["game_reading"] = 40
    for delay in (3, 6):
        fake = step(dict(fake, tick=w["tick"]+delay))
        novice = step(dict(novice, tick=w["tick"]+delay))
    assert hear(fake)["sameBearing"] == hear(novice)["sameBearing"] == 2
    assert hear(fake)["confidence"] < hear(novice)["confidence"]


def test_radar_projection_tracks_tick_state_and_hides_opponent_telemetry():
    w = arena()
    effect(w, "Свет")
    effect(w, "Дым", age=15)
    w = step(w)
    full = match.project(w)
    victim = w["agents"][5]
    marker = next(p for p in full["agents"] if p["id"] == victim["id"])
    assert marker["flashLevel"] == victim["flashLevel"]
    cloud = next(f for f in full["match"]["effects"] if f["kind"] == "Дым")
    actual = next(f for f in w["effects"] if f["kind"] == "Дым")
    assert cloud["volume"] == [[*c["p"],c["reach"]] for c in actual["lobes"] if c["reach"] > 0]
    side = match.project(w, "T")
    assert all("enemiesFlashed" not in row for row in side["match"]["stats"])
    assert all("owner" not in e for e in side["events"] if e["kind"] == "flash")


def test_nuke_smoke_spreads_on_connected_floor_below_another_level():
    from backend import cs2_maps
    if "de_nuke" not in cs2_maps.installed():
        pytest.skip("Требуется установленная геометрия Nuke")
    w = match.initial(11, map_id="de_nuke")
    match.advance(w, 45)
    space = cs2_maps.get("de_nuke")
    # Two real NAV surfaces at nearly the same radar position.
    centers = list(space.centers.values())
    lower, upper = next((p,q) for p in centers for q in centers
                        if math.dist(p[:2],q[:2]) < 4 and 18 < q[2]-p[2] < 40)
    effect(w, "Дым", x=lower[0], y=lower[1], age=20)
    w["effects"][-1]["z"] = lower[2]
    w["recentEffects"][-1]["z"] = lower[2]
    lobes = step(w)["effects"][-1]["lobes"]
    assert any(math.dist(lower, c["p"]) <= c["reach"] for c in lobes)
    assert all(math.dist(upper, c["p"]) > c["reach"] for c in lobes)


def test_staged_pair_reserves_a_threatened_angle_and_prepares_cover_in_flight():
    from tests.test_group_tasks import at_waypoint, notice
    from tests.test_peer_radio import delivered
    from tests.test_small_groups import execute, member

    w, lead, _ = at_waypoint()
    w["agentPolicy"] = 7
    packet = notice(w, "stage")
    offer = packet["feedback"]
    wing = offer["members"][0]
    origin = offer["origin"]
    offer["point"] = [origin[0] + 14, *origin[1:]]
    w["agents"][member(w, lead)]["sentFeedback"]["stage"] = deepcopy(offer)
    actor = w["agents"][member(w, wing)]
    actor["utility"] = ["Свет"]
    command, covered = execute(delivered(w, packet["due"]), wing)
    assert command[0] == "hold" and notice(covered, "set")
    assert not any("flashWarning" in m for m in covered["messages"])

    actor["knowledge"]["Шум"] = dict(id="Шум", source="Слух", x=origin[0]+36, y=origin[1],
                                     z=origin[2], tick=w["tick"], confidence=.8)
    ready = delivered(w, packet["due"])
    duplicate = deepcopy(ready)
    duplicate["agents"][member(w, wing)]["crossingCalls"] = [
        dict(item="Свет", land=w["tick"]+10, end=w["tick"]+15, point=[origin[0]+36,*origin[1:]])]
    assert execute(duplicate, wing)[0][0] == "hold"

    command, informed = execute(ready, wing)
    assert command[0] == "throw"
    warning = next(m for m in informed["messages"] if "flashWarning" in m)
    cast = step(informed, "resolve_actions", json.dumps([dict(actor=wing,kind="throw",target=command[1])]))
    land = cast["effects"][-1]["land"]
    assert warning["due"] < land
    _, scheduled = execute(delivered(cast, cast["tick"]+1), wing)
    reply = notice(scheduled, "set")
    assert scheduled["tick"] < land <= reply["feedback"]["coverAt"]
    lead_state = delivered(scheduled, reply["due"])
    _, launched = execute(lead_state, lead)
    assert notice(launched,"go")["feedback"]["at"] >= reply["feedback"]["coverAt"]

    displaced = deepcopy(lead_state)
    displaced["agents"][member(w, wing)]["x"] += 20
    _, stopped = execute(displaced, lead)
    assert all(m.get("feedback",{}).get("state") != "go" for m in stopped["messages"])


def test_concurrent_warnings_keep_near_flash_and_restore_look_after_burst():
    from tests.test_small_groups import execute, member
    from tests.test_peer_radio import delivered

    w = arena()
    a = w["agents"][0]
    w["agents"][1]["hp"] = w["agents"][2]["hp"] = 100
    for sender,point in [(1,[55,105,0]), (2,[180,150,0])]:
        w["messages"].append(dict(team=a["team"], sender=w["agents"][sender]["id"], due=w["tick"],
                                  flashWarning=dict(point=point,land=w["tick"]+1,ticket=None)))
    state = delivered(w,w["tick"])
    assert len(state["agents"][0]["flashWarnings"]) == 2
    command,turned = execute(state,a["id"])
    actor = turned["agents"][member(w,a["id"])]
    assert command[0] == "hold" and math.cos(actor["heading"]) < 0
    assert actor["resumeFlashLook"]["heading"] == a["heading"]
    effect(turned,"Свет",x=55,owner=5)
    turned["effects"][-1]["land"] += 1
    turned["effects"][-1]["end"] += 1
    owner = native_match_state.open_game(turned)
    owner.advance(1)
    after = json.loads(owner.snapshot())["agents"][0]
    assert "resumeFlashLook" not in after and 0 < after["flashLevel"] < .78


def test_side_radar_can_see_the_exposed_surface_of_an_opposing_cloud():
    w = arena()
    effect(w,"Дым",x=60,age=10,owner=5)
    w = step(w)
    view = match.project(w,"T")["match"]["effects"]
    cloud = next(f for f in view if f["kind"] == "Дым")
    assert cloud["volume"] and cloud["player"] is None and "trajectory" not in cloud


def test_late_ticket_warning_after_go_defers_lead_and_wing_until_burst():
    from tests.test_group_tasks import at_waypoint, notice
    from tests.test_peer_radio import delivered
    from tests.test_small_groups import execute, member

    w, lead, _ = at_waypoint()
    w["agentPolicy"] = 7
    request = notice(w, "stage")
    wing, backup = request["feedback"]["members"]
    _, ready = execute(delivered(w,request["due"]), wing)
    reply = notice(ready,"set",wing)
    _, ordered = execute(delivered(ready,reply["due"]),lead)
    launch = notice(ordered,"go")
    start = launch["feedback"]["at"]
    assert start == launch["due"]
    # The third player's warning arrives after go, outside both players' personal flash radius.
    ordered["messages"].append(dict(sender=backup,team="T",due=start,
                                    flashWarning=dict(ticket=launch["feedback"]["order"],
                                                      point=[1000,1000,0],land=start+1)))
    at_launch = delivered(ordered,start)
    for actor in (lead,wing):
        before = [at_launch["agents"][member(w,actor)][axis] for axis in ("x","y")]
        command, at_launch = execute(at_launch,actor)
        assert command[0] == "hold"
        assert before == [at_launch["agents"][member(w,actor)][axis] for axis in ("x","y")]
    released = delivered(at_launch,start+1)
    for actor in (lead,wing):
        command,released = execute(released,actor)
        assert command[0] == "move"
