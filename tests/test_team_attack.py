"""Physical team decisions use the captain's inbox, teammate radar and the objective clock."""
from copy import deepcopy
import json
from math import dist

import pytest

from backend import cs2_maps, match, native_match_state
from backend.store import Store
from tests.test_group_tasks import put
from tests.test_peer_radio import delivered
from tests.test_small_groups import execute, point
from tests.test_server import envelope


pytestmark = pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна карта Dust II")


@pytest.fixture
def live():
    w = match.initial(17, map_id="de_dust2", agent_policy=8)
    match.advance(w, 45)
    w["tick"] += 20
    w["plans"]["T"]["review"] = 0
    return w


def review(w):
    owner = native_match_state.open_game(w)
    owner.review_captain("T")
    return json.loads(owner.snapshot())


def squad(w):
    return [a for a in w["agents"] if a["team"] == "T"]


def test_delivered_obstruction_rotates_with_time_and_hidden_ct_poses_are_irrelevant(live):
    w = live
    plan = w["plans"]["T"]
    captain = plan["captain"]
    sender = next(a["id"] for a in squad(w) if a["id"] != captain)
    packet = dict(team="T", sender=sender, blockedSite=plan["site"], due=w["tick"]+3)
    w["messages"].append(packet)
    assert not review(delivered(w, packet["due"]-1))["plans"]["T"]["rotated"]
    after = delivered(w, packet["due"])
    rotated = review(after)
    target = rotated["plans"]["T"]["site"]
    assert rotated["plans"]["T"]["rotated"] and target != plan["site"]
    assert all(o["site"] == target for o in rotated["plans"]["T"]["orders"]["slots"])
    assert rotated["events"][-1]["reason"] == "перекрыт подход"
    hidden = deepcopy(after)
    for a in hidden["agents"]:
        if a["team"] == "CT":
            a.update(x=0, y=0, knowledge={}, hp=0, utility=[])
    assert review(hidden)["plans"]["T"] == rotated["plans"]["T"]
    for late in (dict(after, deadline=after["tick"]+50), dict(after, tick=after["tick"]+60)):
        assert not review(late)["plans"]["T"]["rotated"]


def test_successor_uses_own_inbox_and_keeps_active_plan(live):
    w = live
    leader = next(a for a in squad(w) if a["appointed"])
    leader["hp"] = 0
    leader["routeReports"]["old"] = [w["plans"]["T"]["site"], w["tick"]]
    result = review(w)
    plan = result["plans"]["T"]
    assert plan["captain"] != leader["id"] and not plan["rotated"]
    successor = next(a for a in squad(result) if a["id"] == plan["captain"])
    result["tick"] = plan["review"]
    successor["routeReports"]["new"] = [plan["site"], result["tick"]]
    assert review(result)["plans"]["T"]["rotated"]


def test_stage_waits_for_other_lane_delivery_then_moves(live):
    w = live
    plan = w["plans"]["T"]
    plan.update(probe=None, style="Сбор")
    players = squad(w)
    actor = next(a for a in players if a["id"] != w["bomb"]["carrier"] and a["playingRole"] != "support")
    order = plan["orders"]["slots"][actor["slot"]]
    other = next(a for a in players if plan["orders"]["slots"][a["slot"]]["lane"] != order["lane"])
    # Use two distinct reachable spawn surfaces for an exact movement comparison.
    start, end = point(actor), point(other)
    order.update(stage=start, via=[], hold=end)
    command, held = execute(w, actor["id"])
    assert command[0] == "hold"
    own = next(a for a in squad(held) if a["id"] == actor["id"])
    assert point(own) == start and own["status"] == "Ждёт второй вход"
    ready = dict(sender=other["id"], team="T", due=w["tick"]+3,
                 feedback=dict(tick=w["tick"], channel="entry", state="ready", origin=end,
                               point=end, order=plan["site"]))
    held["messages"].append(ready)
    assert execute(delivered(held, ready["due"]-1), actor["id"])[0][0] == "hold"
    after = delivered(held, ready["due"])
    command, moved = execute(after, actor["id"])
    assert command[0] == "move" and moved["events"][-1]["kind"] == "split"
    who = next(a for a in squad(moved) if a["id"] == actor["id"])
    assert dist(point(who), end) < dist(start, end)
    assert execute(dict(held, tick=w["tick"]+45), actor["id"])[0][0] == "move"


@pytest.mark.parametrize("policy", (None, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10))
def test_active_and_manual_checkpoints_keep_policy_and_exact_continuation(tmp_path, policy):
    w = match.initial(41, map_id="de_dust2", agent_policy=policy)
    match.advance(w, 95)
    database = tmp_path / "slots.sqlite"
    store = Store(database)
    state = store.read()
    state["world"] = w
    with store.transaction():
        store.write(state)
    store.apply(envelope(store.read(), "save"))
    store.db.close()
    store = Store(database)
    active = store.read()["world"]
    store.apply(envelope(store.read(), "load"))
    expected = native_match_state.open_game(w)
    expected.advance(100)
    for saved in (active, store.read()["world"]):
        assert saved.get("agentPolicy") == policy
        restored = native_match_state.open_game(saved)
        restored.advance(33)
        restored.advance(67)
        assert restored.snapshot() == expected.snapshot()
    store.db.close()


def test_regroup_after_losses_moves_wing_and_keeps_carrier_in_place(live):
    w = live
    team = squad(w)
    carrier = next(a for a in team if a["id"] == w["bomb"]["carrier"])
    captain = next(a for a in team if a["appointed"])
    wing = next(a for a in team if a not in (carrier, captain) and a["playingRole"] != "support")
    survivors = {carrier["id"], captain["id"], wing["id"]}
    for a in team:
        if a["id"] not in survivors:
            a["hp"] = 0
    space = cs2_maps.get(w["mapId"])
    other = "A" if w["plans"]["T"]["site"] == "B" else "B"
    area = space.plants[other][0]
    put(wing, space.centers[area], area)
    after = review(w)
    plan = after["plans"]["T"]
    assert after["events"][-1]["kind"] == "regroup"
    assert plan["regroup"]["point"] == list(point(carrier))
    assert len({o["lane"] for o in plan["orders"]["slots"]}) == 1
    intent, covering = execute(after, carrier["id"])
    assert intent[0] == "hold" and point(next(a for a in squad(covering) if a["id"] == carrier["id"])) == point(carrier)
    intent, moving = execute(after, wing["id"])
    assert intent[0] == "move"
    actual = next(a for a in squad(moving) if a["id"] == wing["id"])
    assert actual["status"] == "Перегруппировка у носителя C4" and point(actual) != point(wing)


def test_heard_defuse_keeps_other_entrances_covered(live):
    w = live
    space = cs2_maps.get(w["mapId"])
    site = w["plans"]["T"]["site"]
    pos = space.site_points[site]
    w["bomb"].update(zip(("x", "y", "z"), pos))
    w["bomb"].update(carrier=None, site=site)
    w.update(phase="planted", deadline=w["tick"]+350)
    team = squad(w)
    areas = sorted(space.centers, key=lambda i: dist(space.centers[i], pos))[:len(team)]
    for a, area in zip(team, areas):
        put(a, space.centers[area], area)
        a["heardUse"] = w["tick"]
    w["plans"]["T"]["deviceWatch"] = team[0]["id"]
    positions = set()
    for i, a in enumerate(team):
        # Compare decisions from the same radar snapshot. The nearest backup can
        # change when an earlier actor physically moves.
        _, acted = execute(w, a["id"])
        updated = next(m for m in squad(acted) if m["id"] == a["id"])
        assert updated["watchDevice"] == (i <= 1)
        positions.add(tuple(updated["plantCover"]))
    assert len(positions) >= 2


@pytest.mark.parametrize("map_id", cs2_maps.NAMES)
def test_same_position_preserves_ct_review_and_executable_orders(map_id):
    w = match.initial(17, map_id=map_id)
    match.advance(w, 45)
    plan = w["plans"]["T"]
    orders = plan["orders"]["slots"]
    space = cs2_maps.get(map_id)
    for a in squad(w):
        pos = point(a)
        order = orders[a["slot"]]
        for end in [*order["via"], order["plant"]]:
            source, dest = space.locate(tuple(pos)), space.locate(tuple(end))
            assert source is not None and dest is not None
            assert space.path(source, tuple(pos), dest, tuple(end), frozenset()) is not None
            pos = end
        assert space.site_at(pos) == plan["site"]
    ct = []
    for policy in (7, 8, 9):
        ref = native_match_state.open_game(dict(w, agentPolicy=policy))
        ref.review_captain("CT")
        state = json.loads(ref.snapshot())
        ct.append((state["plans"]["CT"], [e for e in state["events"] if e["team"] == "CT"]))
    assert ct[0] == ct[1] == ct[2]


def test_carrier_walks_to_sheltered_plant_surface_only_with_clock_to_spare(live):
    w = live
    plan = w["plans"]["T"]
    plan.update(site="A", probe=None)
    carrier = next(a for a in squad(w) if a["id"] == w["bomb"]["carrier"])
    origin = (300.75, 60.26043333333333, 8.238473154431706)
    angle = (313.74999166666663, 41.41670833333334, 9.666665833333333)
    put(carrier, origin, 1849)
    carrier["knowledge"]["CT1"] = dict(id="CT1", source="Радио", tick=w["tick"]-35,
                                       **dict(zip(("x", "y", "z"), angle)))
    cmd, acted = execute(w, carrier["id"])
    moved = next(a for a in squad(acted) if a["id"] == carrier["id"])
    spot = moved["plantSpot"]["point"]
    space = cs2_maps.get(w["mapId"])
    assert cmd[0] == "move" and dist(point(moved), spot) < dist(origin, spot)
    assert space.site_at(spot) == "A" and not space.hit(origin, angle, 1, 46, 64)
    assert space.hit(tuple(spot), angle, 1, 46, 64)
    cmd, _ = execute(dict(w, deadline=w["tick"]+35), carrier["id"])
    assert cmd == ["plant", "A"]


def test_real_decoy_changes_defender_trajectory_from_identical_checkpoint():
    import gzip
    import random
    from backend import career, database

    # Round 2 of the mirrored acceptance BO1 on Vertigo.
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pair = random.Random(55408).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, pair)
    w = match.initial(55408, domain, pair, map_id="de_vertigo", agent_policy=8,
                      first_attack=domain["rosters"][pair[1]]["team"])
    owner = native_match_state.open_game(w)
    owner.advance(1359)
    state = json.loads(owner.snapshot())
    cast = next(e for e in state["events"] if e["tick"] == 1359 and e["kind"] == "throw")
    assert cast["utility"] == "Ложная" and cast["purpose"] == "Ложный выход"
    state["effects"].remove(next(e for e in state["effects"]
                                 if e["start"] == 1359 and e["player"] == cast["player"]))
    control = native_match_state.open_game(state)
    center = cs2_maps.get("de_vertigo").site_points["B"]
    positions = []
    for run in (owner, control):
        run.advance(80)
        after = json.loads(run.snapshot())
        positions.append({a["id"]: dist(point(a), center) for a in after["agents"] if a["team"] == "CT" and a["hp"]})
    assert any(positions[1][i] - positions[0][i] > 20 for i in positions[0].keys() & positions[1].keys())
