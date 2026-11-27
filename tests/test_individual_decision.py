"""R5.5.1 on the production C++ owner. Times and radio reports use simulation ticks."""
import json

import pytest

from backend import checkpoints, match, native_match_state, tactics


def live():
    w = match.initial(17)
    match.advance(w, 45)
    return w


def decide(w, index):
    actor = w["agents"][index]
    owner = native_match_state.open_game(w)
    device = w["bomb"] if actor["team"] == "T" else actor.get("seenDevice")
    intent = json.loads(owner.priority_intent(
        actor["id"], json.dumps(dict(action=None, device=device, fire=[]))
    ))
    return intent, json.loads(owner.snapshot())["agents"][index]


@pytest.mark.parametrize("index", [4, 9])
def test_personal_resources_and_aging_change_the_executed_choice(index):
    w = live()
    a = w["agents"][index]
    a.update(ammo=1, reserve=20, utility=[])
    intent, result = decide(w, index)
    assert result["decision"]["intent"] == "reload" and result["reloadAt"] > w["tick"]
    assert intent[0] == "hold"

    target = w["agents"][5 if index < 5 else 0]["id"]
    a["knowledge"][target] = dict(id=target, source="Радио", tick=w["tick"], x=a["x"]+3, y=a["y"]+1)
    a["ammo"] = 12
    w["domain"]["players"][a["playerId"]]["roleMastery"]["support"] = 100
    intent, result = decide(w, index)
    assert result["decision"]["intent"] == "watch" and intent[0] == "hold"
    assert result["heading"] == pytest.approx(0.3217505544)
    w["tick"] += 74
    assert decide(w, index)[1]["decision"]["intent"] == "assignment"


@pytest.mark.parametrize("index", [1, 6])
def test_private_enemy_and_undelivered_ally_contacts_cannot_change_turn(index):
    w = live()
    actor = w["agents"][index]
    enemy = w["agents"][5 if index < 5 else 0]
    ally = w["agents"][index+1]
    # Includes both a live opponent and the private memory of a nearby ally facing the actor.
    ally.update(x=actor["x"]+2, y=actor["y"], heading=3.14)
    before = decide(w, index)
    enemy.update(x=115, y=125, hp=3, weapon="AWP", heading=2.7)
    ally.update(target=enemy["id"], visible=[enemy["id"]])
    ally["knowledge"][enemy["id"]] = dict(id=enemy["id"], source="Зрение", tick=w["tick"], x=115, y=125)
    assert decide(w, index) == before


def test_individual_reload_experience_is_local_and_persists():
    w = live()
    a = w["agents"][4]
    a.update(ammo=3, reserve=20, reloadAt=w["tick"] + 8, lastHurt=w["tick"]-1)
    _, experienced = decide(w, 4)
    memory = experienced["exposedReload"]
    assert memory["position"] == [a["x"], a["y"], 0]
    w["tick"] += 20
    a.update(reloadAt=0, exposedReload=memory)
    cautious = decide(w, 4)[1]["decision"]
    del a["exposedReload"]
    baseline = decide(w, 4)[1]["decision"]
    assert cautious["alternatives"]["reload"]["risk"] > baseline["alternatives"]["reload"]["risk"]
    assert (cautious["intent"], baseline["intent"]) == ("assignment", "reload")


@pytest.mark.parametrize("index", [1, 6])
def test_refusal_is_a_single_event_and_next_board_step_executes(index):
    w = live()
    a = w["agents"][index]
    x, y = a["x"], a["y"]
    board = tactics.propose(a["team"], "Пистолетная", 17)
    board.update(id="missing-smoke", revision=1, slots=[[] for _ in range(5)])
    board["slots"][a["slot"]] = [
        dict(kind="throw", utility="Дым", x=x, y=y),
        dict(kind="face", x=x+5, y=y, seconds=1),
    ]
    w["plans"][a["team"]]["board"] = board
    for actor in w["agents"]:
        actor.update(stepIndex=0, stepReady=0, stepUntil=None)
    a["utility"] = []
    owner = native_match_state.open_game(w)
    owner.advance(1)
    state = json.loads(owner.snapshot())
    refused = [e for e in state["events"] if e["kind"] == "order_refused"]
    assert [(e["player"], e["step"], e["team"]) for e in refused] == [(a["id"], 0, a["team"])]
    assert state["agents"][index]["lastRefusal"]["reason"] == "нет назначенной гранаты"
    assert not any(e["kind"] == "board_step" and e["player"] == a["id"] for e in state["events"])
    restored = native_match_state.open_game(state)
    owner.advance(22)
    for _ in range(22):
        restored.advance(1)
    assert restored.snapshot() == owner.snapshot()
    final = json.loads(owner.snapshot())
    assert final["agents"][index]["stepIndex"] == 2
    assert sum(e["kind"] == "order_refused" for e in final["events"]) == 1


def test_ten_private_decisions_and_checkpoint_policy_guard():
    w = live()
    match.advance(w, 1)
    assert len([a for a in w["agents"] if a["decision"]["tick"] == w["tick"]]) == 10
    assert all(a["decision"]["goal"] == ("attack" if a["team"] == "T" else "defend") for a in w["agents"])
    for bad in (2, True, "1"):
        with pytest.raises(ValueError):
            native_match_state.open_game(dict(w, agentPolicy=bad))
        with pytest.raises(ValueError):
            checkpoints.validate_current(dict(w, agentPolicy=bad))
    legacy = match.initial(17, agent_policy=None)
    match.advance(legacy, 46)
    assert all("decision" not in a for a in legacy["agents"])


@pytest.mark.parametrize("index", [1, 6])
def test_style_changes_risk_choice_at_the_same_observed_contact(index):
    w = live()
    a = w["agents"][index]
    a.update(hp=45, ammo=12, reserve=20, utility=[], x=45, y=105)
    opponents = [p for p in w["agents"] if p["team"] != a["team"]][:2]
    for j, target in enumerate(opponents):
        ident = target["id"]
        a["visible"].append(ident)
        a["knowledge"][ident] = dict(id=ident, source="Зрение", tick=w["tick"], x=85, y=105+j)
    profile = w["domain"]["players"][a["playerId"]]
    profile["skills"].update(aggression=100, risk=100)
    bold = decide(w, index)[1]
    profile["skills"].update(aggression=0, risk=0)
    cautious = decide(w, index)[1]
    assert bold["decision"]["intent"] == "engage"
    assert cautious["decision"]["intent"] == "cover"
    assert (cautious["x"], cautious["y"]) != (a["x"], a["y"])
    assert bold["rng"] == cautious["rng"] == a["rng"]
