"""R5.5.2 scenarios use the production tick, delivery and individual executor."""
from copy import deepcopy
import hashlib
import json
import math

import pytest

from backend import match, native_match_state, world
from backend.store import Store
from tests.test_individual_decision import decide
from tests.test_server import envelope


def scenario(side, communication=100, bond=100):
    w = match.initial(17)
    match.advance(w, 45)
    w["tick"] = 48
    own = [a for a in w["agents"] if a["team"] == side]
    enemy = next(a for a in w["agents"] if a["team"] != side and a["slot"] == 1)
    speaker, receiver = own[1], own[4]
    for a in w["agents"]:
        if a["team"] != side and a is not enemy:
            a["hp"] = 0
        a.update(utility=[], visible=[], knowledge={})
    for ally in own:
        ally.update(x=25, y=125, heading=math.pi)
    own[0]["hp"] = 0  # The appointed IGL cannot send, receive or relay.
    speaker.update(x=45, y=105, heading=0, hp=40)
    receiver.update(x=25, y=105, heading=math.pi)
    enemy.update(x=75, y=105, heading=0, blind=200)
    w["bomb"]["carrier"] = next(a["id"] for a in w["agents"] if a["team"] == "T" and a["hp"] and a is not receiver)
    w["domain"]["players"][speaker["playerId"]]["skills"]["communication"] = communication
    w["domain"]["players"][receiver["playerId"]]["skills"]["coordination"] = 100
    w["domain"]["chemistry"][world.pair_key(speaker["playerId"], receiver["playerId"])] = bond
    owner = native_match_state.open_game(w)
    owner.advance(1)  # Slot 1 sees and calls for help on tick 49.
    return json.loads(owner.snapshot()), w["agents"].index(receiver), speaker["id"], enemy["id"]


def delivered(w, tick):
    owner = native_match_state.open_game(dict(w, tick=tick))
    owner.deliver_radio()
    return json.loads(owner.snapshot())


@pytest.mark.parametrize("side", ["T", "CT"])
def test_call_changes_executed_move_only_after_delivery_and_expires(side):
    w, idx, speaker, enemy = scenario(side)
    sent = [m for m in w["messages"] if m["sender"] == speaker and "feedback" in m
            and m["feedback"]["state"] == "help"]
    assert len(sent) == 1
    due = sent[0]["due"]
    before = delivered(w, due - 1)
    receiver = before["agents"][idx]
    assert enemy not in receiver["knowledge"]
    assert speaker + "/contact" not in receiver.get("peerCalls", {})
    baseline = decide(before, idx)
    hidden = deepcopy(before)
    source = next(a for a in hidden["agents"] if a["id"] == speaker)
    source.update(knowledge={}, visible=[], sentFeedback={}, target=None)
    assert decide(hidden, idx) == baseline
    after = delivered(w, due)
    assert baseline[1]["decision"]["intent"] != "assist"
    command, acted = decide(after, idx)
    assert command[0] == "move" and acted["decision"]["respondingTo"]["sender"] == speaker
    origin = sent[0]["feedback"]["origin"][:2]
    assert math.dist([acted["x"], acted["y"]], origin) < math.dist([receiver["x"], receiver["y"]], origin)
    for a in after["agents"]:
        received = speaker + "/contact" in a.get("peerCalls", {})
        assert received == (a["hp"] > 0 and a["team"] == side and a["id"] != speaker)
    assert decide(dict(after, tick=due + 26), idx)[1]["decision"]["intent"] != "assist"


@pytest.mark.parametrize("side", ["T", "CT"])
def test_skill_and_pair_familiarity_change_reception_and_response(side):
    results = {}
    for skill, bond in [(100, 100), (100, 0), (0, 100)]:
        w, idx, speaker, enemy = scenario(side, skill, bond)
        packet = next(m for m in w["messages"] if m["sender"] == speaker and "feedback" in m
                      and m["feedback"]["state"] == "help")
        after = delivered(w, packet["due"])
        # Use the same decision tick for the two chemistry profiles and compare
        # the last tick on which it is worth breaking the assigned route.
        until = [t for t in range(packet["due"], w["tick"]+25)
                 if decide(dict(after, tick=t), idx)[1]["decision"]["intent"] == "assist"]
        results[skill, bond] = (packet["due"]-w["tick"], after["agents"][idx]["knowledge"][enemy]["confidence"], until)
    fast, unfamiliar, slow = results[100, 100], results[100, 0], results[0, 100]
    assert fast[0] == unfamiliar[0] == 1 and slow[0] == 9
    assert fast[1] > unfamiliar[1] and fast[1] > slow[1]
    assert fast[2] and set(fast[2]) > set(unfamiliar[2])
    assert slow[2] and fast[2][0] < slow[2][0] and set(fast[2]) > set(slow[2])


@pytest.mark.parametrize("side", ["T", "CT"])
def test_conflicting_witnesses_order_stale_and_direct_evidence(side):
    w, idx, speaker, enemy = scenario(side)
    r = w["agents"][idx]
    mate = next(a for a in w["agents"] if a["team"] == side and a["slot"] == 2)
    w["domain"]["players"][mate["playerId"]]["skills"]["communication"] = 0
    w["domain"]["chemistry"][world.pair_key(r["playerId"], mate["playerId"])] = 0
    def report(who, x, tick):
        return dict(sender=who, team=side, due=49, sight=dict(id=enemy, source="Зрение", x=x, y=105, tick=tick))
    calls = [report(speaker, 65, 48), report(mate["id"], 105, 48)]
    for packets in [calls, calls[::-1]]:
        after = delivered(dict(w, messages=packets), 49)["agents"][idx]["knowledge"][enemy]
        assert (after["reporter"], after["x"], after["disputed"]) == (speaker, 65, True)
        assert after["confidence"] < after["signalStrength"]
    direct = dict(id=enemy, source="Зрение", x=145, y=105, tick=49)
    r["knowledge"][enemy] = direct
    assert delivered(dict(w, messages=calls), 49)["agents"][idx]["knowledge"][enemy] == direct
    r["knowledge"].clear()
    assert enemy not in delivered(dict(w, messages=calls), 130)["agents"][idx]["knowledge"]


def test_previous_policy_matches_main_checkpoint():
    owner = native_match_state.open_game(match.initial(17, agent_policy=2))
    owner.advance(245)
    assert hashlib.sha256(owner.snapshot()).hexdigest() == "7db3bb650e620faf4b37504c233fe7f47ba33fdbe19669cfb8eddc9d5ba9f835"


def test_pending_radio_survives_active_slot_restart_and_chunking(tmp_path):
    w, _, _, _ = scenario("T", communication=0)
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
    manual = store.read()["world"]
    assert active["messages"] == manual["messages"] == w["messages"]
    baseline = native_match_state.open_game(w)
    baseline.advance(80)
    for source in (active, manual):
        owner = native_match_state.open_game(source)
        for _ in range(80):
            owner.advance(1)
        assert owner.snapshot() == baseline.snapshot()
    store.db.close()


@pytest.mark.parametrize("side", ["T", "CT"])
def test_refresh_is_bounded_and_local_memory_is_never_rebroadcast(side):
    w, idx, speaker, enemy = scenario(side)
    source = next(a for a in w["agents"] if a["id"] == speaker)
    for a in w["agents"]:
        a["blind"] = 500 if a is not source else 0
    source.update(x=45, y=105, heading=0)
    packets = []
    for tick in range(50, 125):
        owner = native_match_state.open_game(dict(w, tick=tick))
        owner.observe()  # identical geometry and heading for 75 observation ticks
        w = json.loads(owner.snapshot())
        packets.extend(m for m in w["messages"] if m.get("sight", {}).get("tick") == tick)
    assert 1 <= len(packets) <= 3
    assert all(p["sender"] == speaker and p["sight"]["id"] == enemy for p in packets)
    assert w["agents"][idx]["knowledge"][enemy]["reporter"] == speaker
    # With the witness gone, delivered evidence expires without creating packets.
    next(a for a in w["agents"] if a["id"] == speaker)["hp"] = 0
    for tick in (135, 210):
        owner = native_match_state.open_game(dict(w, tick=tick))
        owner.observe()
        w = json.loads(owner.snapshot())
        assert not w["messages"]
    assert enemy not in w["agents"][idx]["knowledge"]


@pytest.mark.parametrize("index", [1, 6])
def test_board_ack_ready_completion_and_refusal_reach_allies(index):
    from backend import tactics

    w = match.initial(17)
    match.advance(w, 45)
    actor = w["agents"][index]
    side, slot, x, y = (actor[k] for k in ("team", "slot", "x", "y"))
    ident = actor["id"]
    board = dict(tactics.propose(side, "Пистолетная", 17), id="radio-board", revision=1, slots=[[] for _ in range(5)])
    board["slots"][slot] = [dict(kind="hold", x=x, y=y, seconds=3),
                             dict(kind="throw", utility="Дым", x=x, y=y)]
    w["plans"][side]["board"] = board
    for p in w["agents"]:
        p.update(stepIndex=0, stepReady=0, stepUntil=None)
        if p["team"] != side:
            p.update(blind=250, x=155, y=35)
    actor["utility"] = []
    receiver = next(p for p in w["agents"] if p["team"] == side and p["slot"] == 3)
    key = ident + "/order"
    owner = native_match_state.open_game(w)
    received = {}
    for _ in range(60):
        owner.advance(1)
        state = json.loads(owner.snapshot())
        p = next(p for p in state["agents"] if p["id"] == receiver["id"])
        call = p.get("peerCalls", {}).get(key, {})
        if call:
            received.setdefault(call["state"], call)
    assert {"ready", "completed", "refused", "ack"} <= received.keys()
    assert received["completed"]["order"] == ["radio-board", 1, 0]
    assert received["refused"]["order"] == ["radio-board", 1, 1]
    assert received["refused"]["reason"] == "нет назначенной гранаты"
    assert math.dist(received["ready"]["origin"], received["ready"]["point"]) == pytest.approx(14)


@pytest.mark.parametrize("side", ["T", "CT"])
def test_lost_contact_prompts_a_peer_to_check_the_reported_direction(side):
    w, idx, speaker, enemy = scenario(side)
    source = next(a for a in w["agents"] if a["id"] == speaker)
    target = next(a for a in w["agents"] if a["id"] == enemy)
    source.update(heading=math.pi, hp=100)
    target.update(x=275, y=115)
    w.update(tick=52, messages=[])
    # Keep the original firsthand sight and remove the previous help episode.
    source.pop("sentFeedback", None)
    owner = native_match_state.open_game(w)
    owner.advance(1)
    w = json.loads(owner.snapshot())
    call = next(m for m in w["messages"] if m["sender"] == speaker and m.get("feedback", {}).get("state") == "check")
    assert call["feedback"]["point"][:2] != [target["x"], target["y"]]
    w = delivered(w, call["due"])
    command, p = decide(w, idx)
    assert command[0] == "hold" and p["decision"]["intent"] == "assist"
    x, y, _ = call["feedback"]["point"]
    assert p["heading"] == pytest.approx(math.atan2(y-p["y"], x-p["x"]))


@pytest.mark.parametrize("side", ["T", "CT"])
def test_reported_coverage_can_release_recipient_to_assignment(side):
    w, idx, speaker, _ = scenario(side)
    helper = next(m for m in w["messages"] if m["sender"] == speaker and m.get("feedback", {}).get("state") == "help")
    w = delivered(w, helper["due"])
    # Same call, age, recipient, geometry and RNG. Change only the arrival
    # time of another ally's confirmation that this direction is covered.
    mate = next(p for p in w["agents"] if p["team"] == side and p["slot"] == 2)
    ready = dict(helper["feedback"], state="ready", channel="order", tick=60)
    w["messages"] = [dict(team=side, sender=mate["id"], due=65, feedback=ready)]
    assert decide(delivered(w, 64), idx)[1]["decision"]["intent"] == "assist"
    assert decide(delivered(w, 65), idx)[1]["decision"]["intent"] == "assignment"
    assert decide(dict(w, tick=65, messages=[]), idx)[1]["decision"]["intent"] == "assist"


@pytest.mark.parametrize("policy", [None, 1, 2])
def test_older_slot_keeps_its_policy_after_restart(tmp_path, policy):
    path = tmp_path / "old-slot.sqlite"
    store = Store(path)
    state = store.read()
    w = match.initial(17, agent_policy=policy)
    match.advance(w, 150)
    state["world"] = w
    with store.transaction():
        store.write(state)
    store.apply(envelope(store.read(), "save"))
    store.db.close()
    store = Store(path)
    active = store.read()["world"]
    store.apply(envelope(store.read(), "load"))
    expected = native_match_state.open_game(w)
    expected.advance(95)
    for saved in (active, store.read()["world"]):
        assert saved.get("agentPolicy") == policy
        owner = native_match_state.open_game(saved)
        owner.advance(95)
        assert owner.snapshot() == expected.snapshot()
        assert all("peerCalls" not in a for a in json.loads(owner.snapshot())["agents"])
    store.db.close()
