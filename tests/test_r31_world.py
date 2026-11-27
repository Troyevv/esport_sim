from copy import deepcopy
import json

import pytest

from backend import native_match_state, match, skills, world
from backend.store import Conflict, Store


def test_identity_and_authority_survive_lineup_change_and_sides():
    w = match.initial(6)
    data = w["domain"]
    members = world.lineup(data, w["rosterIds"][0])
    members[0]["captain"], members[2]["captain"] = False, True
    data["rosters"][w["rosterIds"][0]]["members"].reverse()
    ident = members[2]["player"]
    data["players"][ident]["name"] = "Новое имя"
    for mode in ("manager", "owner"):
        data["authority"]["mode"] = mode
        game = match.initial(6, data)
        match.command(game, "timeout")
        match.command(game, "resume")
        owner = native_match_state.open_game(game)
        owner.begin_live()
        game = json.loads(owner.snapshot())
        captain = next(
            a for a in game["agents"] if a["id"] == game["plans"]["T"]["captain"]
        )
        assert (captain["playerId"], captain["name"]) == (ident, "Новое имя")
        game["round"] = 12
        game = native_match_state.start_round(game, None)
        owner = native_match_state.open_game(game)
        owner.begin_live()
        game = json.loads(owner.snapshot())
        captain = next(a for a in game["agents"] if a["playerId"] == ident)
        assert (
            captain["team"] == "CT" and game["plans"]["CT"]["captain"] == captain["id"]
        )
        with pytest.raises(ValueError, match="тайм-аут"):
            match.command(game, "call", "Выход A")
        game["domain"]["authority"]["organization"] = "org-002"
        with pytest.raises(ValueError, match="полномочий"):
            match.command(game, "timeout")
    for action in ("allocate_budget", "manage_organization"):
        world.authorize(data["authority"], "org-001", action)
        with pytest.raises(ValueError):
            world.authorize(
                dict(mode="manager", organization="org-001"), "org-001", action
            )


def test_ratings_and_estimates_do_not_disclose_private_truth():
    w = match.initial(7)
    d = w["domain"]
    a = w["agents"][0]
    p = world.match_player(w, a)
    projection = match.project(w)
    own = world.player_report(d, a["playerId"])
    rival = w["agents"][5]["playerId"]
    assert not {"skills", "estimates", "ratings"} & world.player_report(d, rival).keys()
    assert len(own["ratings"]) == 6
    assert set(own["skills"]) == set(skills.KEYS) - skills.HIDDEN
    for key in skills.HIDDEN:
        p["skills"][key] = 100 - p["skills"][key]
    p["potential"] = 0
    assert world.player_report(d, a["playerId"]) == own
    assert match.project(w) == projection
    assert set(projection["match"]["roleRatings"]) == {a["id"] for a in w["agents"][:5]}
    for view in ("T", "CT", "full"):
        dto = json.dumps(match.project(w, view))
        for k in ("potential", "domain", "assessments", *skills.HIDDEN):
            assert f'"{k}"' not in dto
    assert match.project(w, "CT")["match"]["teamRating"] is None
    d["assessments"]["org-002"] = {
        rival: {
            "potential": dict(
                low=60, high=80, asOf="2026-11-24", source="Контрольный отчёт"
            )
        }
    }
    assert "estimates" not in world.player_report(d, rival)
    d["authority"]["organization"] = "org-002"
    assert (
        world.player_report(d, rival)["estimates"] == d["assessments"]["org-002"][rival]
    )


def test_shooter_captain_and_staff_have_separate_weights():
    d = match.initial(8)["domain"]
    p = d["players"]["player-001"]
    p["skills"].update(dict.fromkeys(skills.KEYS, 40))
    before = world.player_report(d, "player-001")["ratings"]
    p["skills"].update(aim=100, rifles=100, tracking=100)
    after = world.player_report(d, "player-001")["ratings"]
    assert after["igl"] == before["igl"] and after["rifler"] > before["rifler"]
    p["skills"].update(calling=100, leadership=100)
    now = world.player_report(d, "player-001")["ratings"]
    assert now["igl"] > before["igl"] and after["rifler"] == now["rifler"]
    d["staff"]["staff-001"]["preparation"] = 0
    low = world.team_rating(d, "roster-001", "depo")
    d["staff"]["staff-001"]["preparation"] = 100
    assert world.team_rating(d, "roster-001", "depo") == low + 5


@pytest.mark.parametrize("bad", [-1, 101, True, 1.5, None])
def test_invalid_skill_cannot_replace_active_save(tmp_path, bad):
    store = Store(tmp_path / "r31.sqlite")
    state = store.read()
    state["world"] = match.initial(7)
    store.write(state)
    damaged = deepcopy(state)
    world.match_player(damaged["world"], damaged["world"]["agents"][0])["skills"]["aim"] = (
        bad
    )
    store.db.execute("INSERT INTO slot VALUES(1,?)", (json.dumps(damaged),))
    with pytest.raises(Conflict):
        store.apply(
            dict(kind="load", context=state["context"], revision=0, id="failed")
        )
    assert store.read() == state and store.result("failed") is None
    store.db.close()


@pytest.mark.parametrize(
    "broken", ["future", "roster", "staff", "overlap", "pair", "estimate", "captain"]
)
def test_invalid_world_cannot_start_a_match(broken):
    w = match.initial(3)
    d = w["domain"]
    org = d["authority"]["organization"]
    roster = d["rosters"][w["rosterIds"][0]]
    member = roster["members"][0]
    if broken == "future":
        d["skillVersion"] += 1
    elif broken == "roster":
        roster["team"] = "missing"
    elif broken == "staff":
        next(iter(d["staff"].values()))["team"] = "missing"
    elif broken == "overlap":
        roster["members"].append(dict(member, id="historical", until="2027-01-01"))
    elif broken == "pair":
        d["chemistry"]["player-001|unknown"] = 50
    elif broken == "estimate":
        d["assessments"][org] = {member["player"]: {"potential": dict(low=80, high=60)}}
    else:
        member["captain"] = False
    with pytest.raises(ValueError):
        match.initial(77, d)


def test_missing_shot_state_rolls_back_manual_load(tmp_path):
    store = Store(tmp_path / "partial.sqlite")
    state = store.read()
    state["world"] = match.initial(42)
    store.write(state)
    slot = deepcopy(state)
    del slot["world"]["agents"][0]["lastHurt"]
    store.db.execute("INSERT INTO slot VALUES(1,?)", (json.dumps(slot),))
    with pytest.raises(Conflict, match="ручное сохранение"):
        store.apply(
            dict(
                kind="load",
                id="partial",
                context=state["context"],
                revision=state["revision"],
            )
        )
    assert store.read() == state and store.result("partial") is None
    store.db.close()
