"""R5.5.3 checks through the production observation, delivery and movement executors."""
from copy import deepcopy
import hashlib
import json
from math import dist

import pytest

from backend import cs2_maps, match, native_match_state
from tests.test_individual_decision import decide
from tests.test_peer_radio import delivered, scenario
from backend.store import Store
from tests.test_server import envelope


def member(w, ident):
    return next(i for i, actor in enumerate(w["agents"]) if actor["id"] == ident)


def point(actor):
    return [actor["x"], actor["y"], actor.get("z", 0)]


@pytest.mark.parametrize("side", ["T", "CT"])
def test_one_mobile_responder_and_stationary_cover_with_igl_dead(side):
    w, _, sender, _ = scenario(side, policy=4)
    packet = next(m for m in w["messages"] if m.get("feedback", {}).get("state") == "help")
    mobile, cover = packet["feedback"]["members"]
    origin = packet["feedback"]["origin"]
    for ident in (mobile, cover):
        actor = w["agents"][member(w, ident)]
        actor.update(x=25, y=105, ammo=12, heading=0)
    idx = member(w, mobile)
    early = delivered(w, packet["due"]-1)
    before = decide(early, idx)
    private = deepcopy(early)
    private["agents"][member(w, sender)].update(knowledge={}, visible=[], target=None, sentFeedback={})
    assert before == decide(private, idx)
    assert before[1]["decision"]["intent"] != "assist"

    after = delivered(w, packet["due"])
    command, moving = decide(after, idx)
    assert command[0] == "move" and moving["status"] == "Идёт на запрос помощи"
    assert dist(point(moving), origin) < dist(point(after["agents"][idx]), origin)
    stationary = member(w, cover)
    command, holding = decide(after, stationary)
    assert command[0] == "hold" and holding["status"] == "Страхует группу со своей позиции"
    assert point(holding) == point(after["agents"][stationary])
    for i, actor in enumerate(after["agents"]):
        if actor["team"] == side and actor["hp"] and actor["id"] not in (sender, mobile, cover):
            assert decide(after, i)[1]["decision"]["intent"] != "assist"

    after["agents"][idx]["hp"] = 0
    command, replacement = decide(after, stationary)
    assert command[0] == "move" and dist(point(replacement), origin) < dist(point(holding), origin)
    after["agents"][member(w, sender)]["hp"] = 0
    command, replacement = decide(after, stationary)
    assert command[0] == "hold" and replacement["status"] == "Принимает сектор напарника"
    assert decide(dict(after, tick=packet["feedback"]["tick"]+26), stationary)[1]["decision"]["intent"] != "assist"


def execute(w, ident):
    owner = native_match_state.open_game(w)
    observation = {"action": None, "device": w["bomb"], "fire": []}
    command = json.loads(owner.priority_intent(ident, json.dumps(observation)))
    return command, json.loads(owner.snapshot())


@pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна карта Dust II")
def test_waypoint_release_requires_delivered_matching_cover_at_the_reported_position():
    w = match.initial(17, map_id="de_dust2", agent_policy=4)
    match.advance(w, 45)
    plan = w["plans"]["T"]
    plan.update(style="Сбор", probe=None)
    lead, wing = w["agents"][1], w["agents"][0]
    start = point(lead)
    end = point(wing)
    # A short route on two actual spawn surfaces. Leave one eligible partner.
    for a in w["agents"][2:5]:
        a["hp"] = 0
    w["bomb"]["carrier"] = "T3"
    plan["orders"]["slots"][1]["via"] = [start, end, end]
    lead["waypoint"] = 0
    command, asked = execute(w, lead["id"])
    p = asked["agents"][1]
    assert command[0] == "hold" and point(p) == start
    request = p["sentFeedback"]["stage"]
    assert request["members"] == [wing["id"]]
    # Stop the helper on an unoccluded point separated from its aim.
    for field, value in zip(("x", "y", "z"), start):
        asked["agents"][0][field] = value
    packet = next(m for m in asked["messages"] if m.get("feedback") == request)
    after = delivered(asked, packet["due"])
    command, response = execute(after, wing["id"])
    assert command[0] == "hold"
    ready = next(m for m in response["messages"] if m.get("feedback", {}).get("state") == "set")
    assert ready["feedback"]["order"] == [lead["id"], request["tick"]]
    for tick in (ready["due"]-1, ready["due"]):
        state = delivered(response, tick)
        cmd, acted = execute(state, lead["id"])
        if tick < ready["due"]:
            assert cmd[0] == "hold" and point(acted["agents"][1]) == start
        else:
            assert cmd[0] == "move" and dist(point(acted["agents"][1]), end) < dist(start, end)
            state["agents"][0]["x"] += 8
            assert execute(state, lead["id"])[0][0] == "hold"
    after["agents"][0]["reloadAt"] = after["tick"]+15
    _, busy = execute(after, wing["id"])
    assert all(m.get("feedback", {}).get("state") != "set" for m in busy["messages"])


@pytest.mark.parametrize("policy", [3, 4, 5])
def test_pending_group_call_survives_manual_and_active_slot(tmp_path, policy):
    w, *_ = scenario("CT", communication=0, policy=policy)
    assert w["messages"]
    path = tmp_path / "slot.sqlite"
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
    expected.advance(83)
    for saved in (active, store.read()["world"]):
        assert saved["agentPolicy"] == policy and saved["messages"] == w["messages"]
        owner = native_match_state.open_game(saved)
        for _ in range(83):
            owner.advance(1)
        assert owner.snapshot() == expected.snapshot()
    store.db.close()


def test_policy_three_matches_pr43_binary():
    owner = native_match_state.open_game(match.initial(17, agent_policy=3))
    owner.advance(245)
    assert hashlib.sha256(owner.snapshot()).hexdigest() == "867cec5e9a1efe8095e4a03f9074874a851f7da5bc397d0a400b3b562e657862"


@pytest.mark.parametrize("name", ["de_dust2", "de_inferno"])
def test_ct_scout_moves_only_under_confirmed_cover(name):
    if name not in cs2_maps.installed():
        pytest.skip("Нужна установленная карта")
    w = match.initial(15, map_id=name, agent_policy=4)
    match.advance(w, 45)
    w["tick"] = 60
    jobs = w["plans"]["CT"]["opening"]["jobs"]
    scout = next(ident for ident, j in jobs.items() if j.get("role") == "разведка" and "partner" in j)
    job = jobs[scout]
    support = job["partner"]
    gate, peek = job["gate"], job["peek"]
    for ident in (scout, support):
        a = w["agents"][member(w, ident)]
        a.update(x=gate[0], y=gate[1], z=gate[2], navArea=cs2_maps.get(name).locate(tuple(gate)),
                 visible=[], knowledge={}, peerCalls={}, ready=0)
        jobs[ident]["atGate"] = w["tick"]-5
    jobs[support].update(lastCover=w["tick"], departed=w["tick"])
    # Even a simulated completion of the partner's private job cannot release the scout.
    assert execute(w, scout)[0][0] == "hold"
    report = dict(state="set", tick=60, point=peek, origin=gate, channel="gate", order=job["zone"])
    w["messages"] = [dict(team="CT", sender=support, due=63, feedback=report)]
    assert execute(delivered(w, 62), scout)[0][0] == "hold"
    heard = delivered(w, 63)
    cmd, advanced = execute(heard, scout)
    assert cmd[0] == "move" and dist(point(advanced["agents"][member(w, scout)]), gate) > .1
    for _ in range(12):
        advanced["tick"] += 1
        _, advanced = execute(advanced, scout)
    assert dist(point(advanced["agents"][member(w, scout)]), peek) < dist(gate, peek)
    heard["agents"][member(w, support)]["x"] += 10
    assert execute(heard, scout)[0][0] == "hold"


@pytest.mark.parametrize("side", ["T", "CT"])
def test_delivered_route_refusal_transfers_the_only_moving_role(side):
    w, _, _, _ = scenario(side, policy=4)
    packet = next(m for m in w["messages"] if m.get("feedback", {}).get("state") == "help")
    mobile, backup = packet["feedback"]["members"]
    w = delivered(w, packet["due"])
    origin = packet["feedback"]["origin"]
    p = w["agents"][member(w, backup)]
    p.update(x=25, y=105, ammo=12)
    # A local failure by the assigned player is private until the refusal arrives.
    w["agents"][member(w, mobile)]["blind"] = 150
    # The quoted opponent has left. A new personal firefight takes priority over aid.
    for actor in w["agents"]:
        if actor["team"] != side:
            actor.update(x=275, y=115)
    owner = native_match_state.open_game(w)
    owner.advance(1)
    w = json.loads(owner.snapshot())
    decline = next(m for m in w["messages"] if m.get("sender") == mobile and
                   m.get("feedback", {}).get("state") == "decline")
    for tick, moves in ((decline["due"]-1, False), (decline["due"], True)):
        state = delivered(w, tick)
        i = member(state, backup)
        cmd, result = decide(state, i)
        assert (cmd[0] == "move") == moves
        if moves:
            assert dist(point(result), origin) < dist(point(state["agents"][i]), origin)


@pytest.mark.parametrize("side", ["T", "CT"])
def test_nomination_uses_role_experience_chemistry_and_delivered_resource_reports(side):
    from backend.world import pair_key

    w, _, sender, enemy = scenario(side, policy=4)
    allies = [p for p in w["agents"] if p["team"] == side]
    lead, left, right = allies[1], allies[3], allies[4]
    w.update(tick=48, messages=[])
    allies[2]["hp"] = 0
    lead.update(hp=40, x=45, y=105, heading=0, sentFeedback={}, peerCalls={})
    w["agents"][member(w, enemy)].update(x=75, y=105)
    for p in (left, right):
        p.update(x=25, y=105, playingRole="support")
        w["domain"]["players"][p["playerId"]]["roleMastery"]["support"] = 0
        w["domain"]["chemistry"][pair_key(lead["playerId"], p["playerId"])] = 0

    def nominate(source):
        owner = native_match_state.open_game(source)
        owner.advance(1)
        state = json.loads(owner.snapshot())
        call = next(m for m in state["messages"] if m["sender"] == sender and
                    m.get("feedback", {}).get("state") == "help")
        return call["feedback"]["members"]

    for better in (left, right):
        for field in ("mastery", "chemistry"):
            same = deepcopy(w)
            if field == "mastery":
                same["domain"]["players"][better["playerId"]]["roleMastery"]["support"] = 100
            else:
                same["domain"]["chemistry"][pair_key(lead["playerId"], better["playerId"])] = 100
            assert nominate(same)[0] == better["id"]
    # A teammate's private empty weapon does not alter nomination. Its actual radio delivery does.
    preferred = nominate(w)[0]
    same = deepcopy(w)
    same["agents"][member(w, preferred)]["ammo"] = 0
    assert nominate(same)[0] == preferred
    notice = dict(channel="order", state="ack", tick=48, armed=False, hasUtility=False,
                  origin=point(left), point=point(left), order="hold")
    same["messages"] = [dict(team=side, sender=preferred, due=50, feedback=notice)]
    assert nominate(same)[0] == preferred
    same["messages"][0]["due"] = 49
    assert preferred not in nominate(same)


@pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна карта Dust II")
@pytest.mark.parametrize("side", ["T", "CT"])
def test_named_support_cast_uses_inventory_and_a_real_grenade_trajectory(side):
    w = match.initial(17, map_id="de_dust2", agent_policy=4)
    match.advance(w, 45)
    start, goal = point(w["agents"][0]), point(w["agents"][3])
    allies = [p for p in w["agents"] if p["team"] == side]
    lead, helper = allies[0], allies[4]
    for ally in allies[1:4]:
        ally["hp"] = 0
    target = next(p["id"] for p in w["agents"] if p["team"] != side)
    helper.update(x=start[0], y=start[1], z=start[2], ammo=12, utility=["Дым"],
                  navArea=cs2_maps.get("de_dust2").locate(tuple(start)), visible=[], knowledge={})
    w["messages"] = [
        dict(sender=lead["id"], team=side, due=50,
             sight=dict(source="Зрение", id=target, tick=49, x=goal[0], y=goal[1], z=goal[2])),
        dict(sender=lead["id"], team=side, due=50, feedback=dict(channel="contact", state="help",
             tick=49, order=target, origin=start, point=goal, members=[helper["id"]]))]
    after = delivered(w, 50)
    cmd, state = execute(after, helper["id"])
    assert cmd[0] == "throw" and cmd[1]["purpose"] == "Поддержка по запросу напарника"
    owner = native_match_state.open_game(state)
    owner.resolve_actions(json.dumps([dict(actor=helper["id"], kind="throw", target=cmd[1])]))
    state = json.loads(owner.snapshot())
    effect = state["effects"][-1]
    assert effect["player"] == helper["id"] and effect["kind"] == "Дым"
    assert not state["agents"][member(w, helper["id"])]["utility"]
    assert effect["land"] > state["tick"] and len(effect["trajectory"]) > 1
    assert dist(point(effect), goal) < effect["radius"]
    notice = next(m for m in state["messages"] if "friendlyUtility" in m)
    reception = delivered(state, notice["due"])
    cast = notice["friendlyUtility"]["cast"]
    assert cast in reception["agents"][member(w, lead["id"])]["crossingCalls"]
