"""R5.6 through the same commands, native turns and durable receipts as a client."""

from copy import deepcopy
import json

import pytest

from backend import checkpoints, coaching, cs2_maps, match, native_match_state, round_sim
from backend.store import Store
from tests.test_individual_decision import decide
from tests.test_round_simulation import fixture
from tests.test_server import envelope


def request(w, action, target, **fields):
    match.command(w, "address", dict(subject=0, action=action, target=target, **fields))


def bench_player(w):
    return next(
        (i, a) for i, a in enumerate(w["agents"]) if a["teamId"] == w["coachTeamId"] and a["slot"] == 1
    )


def test_reply_is_private_idempotent_and_survives_a_device_change(tmp_path):
    path = tmp_path / "career.sqlite"
    with_store = Store(path)

    def send(kind, value=None):
        with_store.apply(envelope(with_store.read(), kind, value))

    send("match", 561)
    send("timeout")
    state = with_store.read()
    side = bench_player(state["world"])[1]["team"]
    assert match.project(state["world"], "T" if side == "CT" else "CT")["match"]["room"] is None
    question = envelope(state, "address", dict(subject=0, action="opinion", target="team"))
    with_store.apply(question)
    send("save")
    with_store.db.close()
    with_store = Store(path)
    try:
        with_store.apply(question)
        send("load")
        w = with_store.read()["world"]
        assert w["talkSeconds"] == 50 and len(w["talkHistory"]) == 1
        assert len(w["talkHistory"][0]["replies"]) == 5
        assert len(match.project(w)["match"]["room"]["players"]) == 5
        checkpoints.validate_current(w)
        damaged = deepcopy(w)
        damaged["agents"][0]["mind"]["stress"] = 110
        with pytest.raises(checkpoints.CheckpointError):
            checkpoints.validate_current(damaged)
    finally:
        with_store.db.close()


def test_tilt_after_unfair_criticism_and_recovery_without_changing_traits():
    w = match.initial(17)
    i, a = bench_player(w)
    traits = w["domain"]["players"][a["playerId"]]["skills"]
    traits.update(stress_resistance=10, composure=10, professionalism=30)
    w["domain"]["players"][a["playerId"]]["fatigue"] = 65
    traits.update(aggression=55, risk=55)
    own_traits = deepcopy(traits)
    steady = deepcopy(w)
    steady["domain"]["players"][a["playerId"]]["skills"].update(stress_resistance=95, composure=95)
    for game in [w, steady]:
        match.command(game, "timeout")
        for _ in range(6):
            request(game, "harsh", a["id"])
        assert game["talkSeconds"] == 0
        with pytest.raises(ValueError):
            request(game, "calm", a["id"])
        match.command(game, "resume")
        match.advance(game, 45)
    unstable = w["agents"][i]["mind"]
    assert coaching.impression(unstable, True) == "Подвержен тильту"
    assert steady["agents"][i]["mind"]["frustration"] < unstable["frustration"]
    actions = []
    for game in (w, steady):
        actor = game["agents"][i]
        actor.update(x=45, y=105, hp=15, ammo=12, reserve=20, utility=[], knowledge={}, visible=[])
        rivals = [p for p in game["agents"] if p["team"] != actor["team"]][:2]
        for j, rival in enumerate(rivals):
            actor["visible"].append(rival["id"])
            actor["knowledge"][rival["id"]] = dict(
                id=rival["id"], source="Зрение", tick=game["tick"], x=85, y=105 + j
            )
        intent, result = decide(game, i)
        actions.append((result["decision"]["intent"], (result["x"], result["y"]) != (45, 105)))
    assert actions == [("engage", False), ("cover", True)]
    owner = native_match_state.open_game(w)
    owner.finish_round(a["team"], "Устранение")
    recovered = json.loads(owner.snapshot())
    assert recovered["agents"][i]["mind"]["frustration"] < unstable["frustration"]
    assert coaching.impression(recovered["agents"][i]["mind"], True) == "Раздражён"
    assert recovered["domain"]["players"][a["playerId"]]["skills"] == own_traits


def test_concrete_position_is_executed_and_impossible_exit_reported():
    w = match.initial(17)
    i, actor = bench_player(w)
    match.command(w, "timeout")
    match.command(w, "call", "Выход A")
    request(w, "order", actor["id"], order="position", site="A")
    match.command(w, "resume")
    if w["phase"] != "live":
        match.advance(w, 45)
    before = w["agents"][i]
    assert before["id"] != w["bomb"]["carrier"]
    command, moved = decide(w, i)
    assert command[0] == "move" and moved["status"] == "Занимает назначенную позицию"
    assert (moved["x"], moved["y"]) != (before["x"], before["y"])
    before["coachOrder"]["site"] = "B"
    _, redirected = decide(w, i)
    assert "coachOrder" not in redirected and "другой плент" in redirected["evidence"]["text"]


def test_unearned_praise_and_false_or_foreign_subjects():
    w = match.initial(17)
    match.command(w, "timeout")
    i, a = bench_player(w)
    start = deepcopy(a["mind"])
    request(w, "praise", a["id"])
    assert w["agents"][i]["mind"] == start
    with pytest.raises(ValueError):
        match.command(
            w, "address", dict(action="discuss", target=a["id"], speaker=a["id"], subject=99999)
        )
    assert w["talkSeconds"] == 50


def test_fast_coach_spends_separate_budgets_and_legacy_report_replays():
    g = fixture(1, 564)
    teams = [g["domain"]["rosters"][r]["team"] for r in g["rosterIds"]]

    def play():
        return round_sim.play_map(g, "de_mirage", teams[0], 564)

    r = play()
    assert r == play()
    calls = [x["timeoutTeam"] for x in r["rounds"] if "timeoutTeam" in x]
    assert calls
    for team in teams:
        assert r["remainingTimeouts"][team] + calls.count(team) == g["series"]["profile"].get(
            "timeouts", match.RULES["timeouts"]
        )
    g["simulation"] = round_sim.LEGACY_MODE
    old = play()
    assert old == play() and old["rules"] == "round-mr12.1"
    assert all("timeoutTeam" not in row for row in old["rounds"])


@pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна физическая Dust II")
def test_two_witnesses_five_identified_attackers_and_actual_reserve_movement():
    from tools.trace_match_orders import scenario

    result = scenario("de_dust2", 56563, 12, wounded=True)
    assert result["unique"] == 5 and result["packets"] >= 10
    assert result["site"] == "A" and len(result["acted"]) >= 2
    assert not result["conflictingDuties"] and not result["idleWithoutTask"]


def test_same_score_and_spending_limit_allow_a_coach_to_wait_or_intervene():
    w = match.initial(567)
    match.advance(w, 45)
    owner = native_match_state.open_game(w)
    owner.finish_round("T", "Устранение")
    w = json.loads(owner.snapshot())
    # Same scoreboard, same money and same sequence of public results in both branches.
    w["round"] = 7
    rival = next(t for t in w["domain"]["teams"] if t != w["coachTeamId"])
    def intermission(load, budget=2):
        before = deepcopy(w)
        before["rivalRemaining"] = budget
        for a in before["agents"]:
            if a["teamId"] == rival:
                a["mind"].update(stress=load, frustration=load, confidence=60)
        owner = native_match_state.open_game(before)
        owner.advance(before["deadline"] - before["tick"])
        return json.loads(owner.snapshot())
    quiet = intermission(8)
    assert quiet["rivalRemaining"] == 2 and "breakOwner" not in quiet
    tense = intermission(68)
    assert tense["breakOwner"] == rival and tense["rivalRemaining"] == 1
    assert tense["remaining"] == w["remaining"]
    assert tense["aiCall"]["team"] == rival and any(a.get("coachOrder") for a in tense["agents"])
    public = match.project(tense)["match"]
    assert public["room"] is None and not public["feedback"]
    with pytest.raises(ValueError):
        request(tense, "praise", "team")
    match.advance(tense, 600)
    assert "breakOwner" not in tense and tense["phase"] == "freeze"
    assert "breakOwner" not in intermission(68, budget=0)
    assert not any(row["team"] != rival for row in tense["talkHistory"])
