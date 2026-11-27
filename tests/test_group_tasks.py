"""Production invitations, local arbitration and physically executed rendezvous."""
from copy import deepcopy
import hashlib
import json
from math import dist

import pytest

from backend import cs2_maps, match, native_match_state
from tests.test_peer_radio import delivered, scenario
from tests.test_small_groups import execute, member, point


def put(actor, pos, area):
    actor.update(zip(("x", "y", "z"), pos))
    actor.update(navArea=area, waypoint=0, path=[], visible=[], knowledge={}, ready=0, utility=[])


def at_waypoint(name="de_dust2", areas=None):
    if name not in cs2_maps.installed():
        pytest.skip("Требуется установленная карта")
    w = match.initial(17, map_id=name, agent_policy=5)
    match.advance(w, 45)
    plan = w["plans"]["T"]
    plan.update(style="Сбор", probe=None)
    lead, one, two = [w["agents"][i] for i in (1, 0, 2)]
    w["agents"][3]["hp"] = w["agents"][4]["hp"] = 0
    w["bomb"]["carrier"] = w["agents"][3]["id"]
    space = cs2_maps.get(name)
    goal = point(one)
    if areas:
        for actor, area in zip((lead, one, two), areas):
            put(actor, space.centers[area], area)
        goal = point(two)
    else:
        for actor in (one, two):
            put(actor, point(lead), lead["navArea"])
    start = point(lead)
    orders = plan["orders"]["slots"]
    orders[1]["via"] = [start, goal, goal]
    lead.update(waypoint=0, playingRole="entry")
    for actor in (one, two):
        orders[actor["slot"]]["lane"] = orders[1]["lane"]
    command, asked = execute(w, lead["id"])
    assert command[0] == "hold"
    return asked, lead["id"], goal


def notice(w, state, sender=None):
    return next(m for m in reversed(w["messages"])
                if m.get("feedback", {}).get("state") == state and (sender is None or m["sender"] == sender))


def test_second_ready_member_releases_and_stale_or_displaced_confirmation_does_not():
    w, lead, _ = at_waypoint()
    msg = notice(w, "stage")
    first, second = msg["feedback"]["members"]
    after = delivered(w, msg["due"])
    _, prepared = execute(after, second)
    ready = notice(prepared, "set", second)
    assert not ready["feedback"]["wing"]
    assert execute(delivered(prepared, ready["due"] - 1), lead)[1]["agents"][member(w, lead)]["groupLead"].get("at") is None
    heard = delivered(prepared, ready["due"])
    for alter in ("ticket", "pose"):
        changed = deepcopy(heard)
        if alter == "ticket":
            changed["agents"][member(w, lead)]["peerCalls"][second + "/reply/" + lead + "/stage"]["order"][2] -= 1
        else:
            changed["agents"][member(w, second)]["x"] += 8
        _, resumed = execute(changed, lead)
        assert "at" not in resumed["agents"][member(w, lead)]["groupLead"]
    _, released = execute(heard, lead)
    assert notice(released, "go")["feedback"]["mate"] == second


def test_wait_deadline_survives_repeated_arrivals_and_checkpoint():
    w, lead, _ = at_waypoint()
    i = member(w, lead)
    first = w["agents"][i]["groupLead"]
    for tick in range(w["tick"] + 1, first["until"] + 2):
        w.update(tick=tick)
        w["agents"][i]["waypoint"] = 0  # Same route stage is evaluated as a fresh arrival.
        _, w = execute(w, lead)
        g = w["agents"][i]["groupLead"]
        assert (g["until"], g["ticket"]) == (first["until"], first["ticket"])
        if tick >= first["until"]:
            assert g["closed"] and w["agents"][i]["status"] != "Ждёт прикрытия на рубеже"


def test_launch_moves_both_players_on_the_same_tick_with_separate_angles():
    w, lead, goal = at_waypoint()
    packet = notice(w, "stage")
    wing = packet["feedback"]["members"][0]
    start = delivered(w, packet["due"])
    _, state = execute(start, wing)
    response = notice(state, "set", wing)
    _, state = execute(delivered(state, response["due"]), lead)
    launch = notice(state, "go")
    tick = launch["feedback"]["at"]
    assert tick == launch["due"]
    state = delivered(state, tick)
    p, q = [member(w, ident) for ident in (lead, wing)]
    initial = [point(state["agents"][i]) for i in (p, q)]
    for ident in (lead, wing):
        cmd, state = execute(state, ident)
        assert cmd[0] == "move"
    a, b = state["agents"][p], state["agents"][q]
    assert dist(point(a), goal) < dist(initial[0], goal)
    assert dist(point(b), initial[1]) > .1 and a["heading"] != b["heading"]
    assert a["groupLead"]["ticket"] == b["groupDuty"]["ticket"]


@pytest.mark.parametrize("side", ["T", "CT"])
@pytest.mark.parametrize("reverse", [False, True])
def test_two_delivered_offers_produce_one_duty_and_explicit_refusal(side, reverse):
    w, _, lead, _ = scenario(side, policy=5)
    packet = notice(w, "help", lead)
    helper = packet["feedback"]["members"][0]
    buddy = next(p for p in w["agents"] if p["team"] == side and p["hp"] and p["id"] not in (lead, helper))
    other = deepcopy(packet)
    other["sender"] = buddy["id"]
    other["feedback"].update(state="stage", channel="stage", origin=point(buddy))
    w["messages"] = [other, packet] if reverse else [packet, other]
    for actor in w["agents"]:
        if actor["team"] != side:
            actor.update(x=275, y=115)
    owner = native_match_state.open_game(w)
    owner.advance(1)
    result = json.loads(owner.snapshot())
    who = result["agents"][member(w, helper)]
    assert who["groupDuty"]["ticket"] == [lead, "contact", packet["feedback"]["tick"]]
    replies = [m["feedback"] for m in result["messages"] if m.get("sender") == helper and "feedback" in m]
    assert any(r["state"] == "decline" and r["order"][0] == buddy["id"] for r in replies)
    assert sum(r["state"] == "accept" for r in replies) == 1


@pytest.mark.parametrize("name,areas", [
    ("de_nuke", (1, 34, 112)), ("de_vertigo", (1, 2097, 69)), ("de_train", (21, 114, 33)),
])
def test_nearest_on_another_level_is_rejected_by_physical_route(name, areas):
    w, _, _ = at_waypoint(name, areas)
    m = cs2_maps.get(name)
    src, near, far = (m.centers[i] for i in areas)
    assert dist(src, near) < dist(src, far)
    path = m.planner.path(areas[1], near, areas[0], src, set())
    assert not path or sum(dist(a[:3], b[:3]) for a, b in zip([near, *path[:-1]], path)) > 110
    assert notice(w, "stage")["feedback"]["members"] == [w["agents"][2]["id"]]


def test_real_flash_flight_precedes_readiness_and_release():
    w, lead, _ = at_waypoint()
    packet = notice(w, "stage")
    wing = packet["feedback"]["members"][0]
    origin = packet["feedback"]["origin"]
    # An open throw down the spawn lane, beyond friendly flash radius.
    packet["feedback"]["point"] = [origin[0] + 14, *origin[1:]]
    w["agents"][member(w, lead)]["sentFeedback"]["stage"] = deepcopy(packet["feedback"])
    w["agents"][member(w, wing)]["utility"] = ["Свет"]
    cmd, w = execute(delivered(w, packet["due"]), wing)
    assert cmd[0] == "throw"
    owner = native_match_state.open_game(w)
    owner.resolve_actions(json.dumps([dict(actor=wing, kind="throw", target=cmd[1])]))
    w = json.loads(owner.snapshot())
    flash = w["effects"][-1]
    assert flash["groupTicket"] == cmd[1]["groupTicket"] and len(flash["trajectory"]) > 1
    assert not w["agents"][member(w, wing)]["utility"]
    before = delivered(w, flash["land"] - 1)
    assert execute(before, wing)[0][0] == "hold"
    assert execute(before, lead)[0][0] == "hold"
    assert not any(m.get("feedback", {}).get("state") in ("set", "go") for m in before["messages"])
    armed = max(flash["land"], w["agents"][member(w, wing)]["ready"])
    _, w = execute(delivered(w, armed), wing)
    ready = notice(w, "set")
    _, w = execute(delivered(w, ready["due"]), lead)
    assert notice(w, "go")["feedback"]["at"] >= flash["land"]


def test_sole_ct_anchor_covers_from_its_post():
    if "de_dust2" not in cs2_maps.installed():
        pytest.skip("Требуется установленная карта")
    w = match.initial(17, map_id="de_dust2", agent_policy=5)
    match.advance(w, 45)
    own = [p for p in w["agents"] if p["team"] == "CT"]
    sender, anchor = own[:2]
    for p in own[2:]:
        p["hp"] = 0
    pos = point(anchor)
    # Only this defender is assigned to the live site. Another teammate on
    # radar has sent a request from a different position.
    orders = w["plans"]["CT"]["orders"]["slots"]
    orders[0]["site"], orders[1]["site"], orders[1]["hold"] = "B", "A", pos
    target = [pos[0] + 8, *pos[1:]]
    w["messages"] = [dict(team="CT", sender=sender["id"], due=46, feedback=dict(
        channel="contact", state="help", origin=[pos[0] + 35, *pos[1:]], point=target,
        tick=45, until=70, phase="live", order="T1", members=[anchor["id"]]))]
    cmd, result = execute(delivered(w, 46), anchor["id"])
    a = result["agents"][member(w, anchor["id"])]
    assert cmd[0] == "hold" and point(a) == pos and not a["groupDuty"]["wing"]


def test_backup_takes_mobile_role_only_after_the_refusal_is_delivered():
    w, lead, _ = at_waypoint()
    packet = notice(w, "stage")
    first, second = packet["feedback"]["members"]
    due = packet["due"]
    after = delivered(w, due)
    _, active = execute(after, second)
    assert not active["agents"][member(w, second)]["groupDuty"]["wing"]
    # The backup cannot see its partner's private blindness.
    active["agents"][member(w, first)]["blind"] = 100
    ticket = [lead, "stage", packet["feedback"]["tick"]]
    active["messages"].append(dict(sender=first, team="T", due=due+2, feedback=dict(
        channel="reply/" + lead + "/stage", state="decline", point=packet["feedback"]["point"],
        origin=point(w["agents"][member(w, first)]), tick=due, order=ticket, wing=False, duty=True,
        until=packet["feedback"]["until"])))
    for tick, transferred in [(due+1, False), (due+2, True)]:
        _, state = execute(delivered(active, tick), second)
        assert state["agents"][member(w, second)]["groupDuty"]["wing"] is transferred



def test_policy_four_replays_pr44_checkpoint_byte_for_byte():
    owner = native_match_state.open_game(match.initial(17, agent_policy=4))
    owner.advance(245)
    assert hashlib.sha256(owner.snapshot()).hexdigest() == "c6cb962c4d1612e0f704491adeca4e65068e9ea4330eadc346bd599b3f2b4ad6"


def test_active_duty_and_inflight_launch_survive_manual_and_active_save(tmp_path):
    from backend.store import Store
    from tests.test_server import envelope

    w, lead, _ = at_waypoint()
    msg = notice(w, "stage")
    wing = msg["feedback"]["members"][0]
    _, w = execute(delivered(w, msg["due"]), wing)
    _, w = execute(delivered(w, notice(w, "set")["due"]), lead)
    assert notice(w, "go")["due"] > w["tick"]
    store = Store(tmp_path / "coord.sqlite")
    state = store.read()
    state["world"] = w
    with store.transaction():
        store.write(state)
    store.apply(envelope(store.read(), "save"))
    store.db.close()
    store = Store(tmp_path / "coord.sqlite")
    active = store.read()["world"]
    store.apply(envelope(store.read(), "load"))
    source = native_match_state.open_game(w)
    source.advance(48)
    for saved in [active, store.read()["world"]]:
        assert saved["agents"][member(w, wing)]["groupDuty"] == w["agents"][member(w, wing)]["groupDuty"]
        restored = native_match_state.open_game(saved)
        for size in (1, 16, 31):
            restored.advance(size)
        assert restored.snapshot() == source.snapshot()
    store.db.close()


@pytest.mark.parametrize("side", ["T", "CT"])
def test_urgent_offer_releases_an_accepted_task_before_switching(side):
    w, _, lead, _ = scenario(side, policy=5)
    help_call = notice(w, "help", lead)
    helper = help_call["feedback"]["members"][0]
    idx = member(w, helper)
    other = next(p for p in w["agents"] if p["team"] == side and p["hp"] and p["id"] not in (helper, lead))
    stage = deepcopy(help_call)
    stage["sender"] = other["id"]
    stage["feedback"].update(channel="stage", state="stage", origin=point(w["agents"][idx]), members=[helper])
    w["messages"] = [stage]
    _, w = execute(delivered(w, stage["due"]), helper)
    original = w["agents"][idx]["groupDuty"]["ticket"]
    assert original[0] == other["id"]
    # A new firsthand contact reaches the helper while the old obligation is still valid.
    tick = stage["due"] + 12
    assert tick < stage["feedback"]["until"]
    help_call.update(due=tick)
    help_call["feedback"].update(tick=tick - 1, until=tick + 22, origin=point(w["agents"][idx]))
    w["messages"] = [help_call]
    _, early = execute(delivered(w, tick - 1), helper)
    assert early["agents"][idx]["groupDuty"]["ticket"] == original
    _, switched = execute(delivered(w, tick), helper)
    replacement = switched["agents"][idx]["groupDuty"]["ticket"]
    assert replacement == [lead, "contact", tick - 1]
    changes = [(m["feedback"]["state"], m["feedback"]["order"]) for m in switched["messages"]
               if m["sender"] == helper and "feedback" in m]
    assert changes[:2] == [("cancel", original), ("accept", replacement)]
