"""Regressions for permanent team identity, post-plant decisions and the damage ledger."""

from collections import Counter
from copy import deepcopy
import json

import pytest

from backend import career, career_store, match, match_score
from backend import match_ai as ai
from backend.match_events import damage, impact
from backend.match_rules import BLAST_RADIUS, POSITIONS, RULES, WEAPONS, equipment_value
from backend.store import Store


@pytest.mark.parametrize("winner", ["team-001", "team-002"])
def test_round_side_score_and_winner_through_two_overtimes(winner):
    w = match.initial(314)
    ids = match_score.team_ids(w)
    w["agents"].reverse()
    credited = Counter()
    for n in range(1, 35):
        side = match_score.side_for(w, ids[0])
        assert side == ("T" if n <= 12 or 28 <= n <= 33 else "CT")
        if n in (25, 28, 31, 34):
            assert all(a["cash"] == RULES["overtimeMoney"] for a in w["agents"])
        tid = ids[n % 2] if n <= 30 else winner
        winning_side = match_score.side_for(w, tid)
        match.finish_round(w, winning_side, "Устранение")
        match.finish_round(w, winning_side, "Устранение")
        credited[tid] += 1
        view = match.project(w)["match"]
        history = view["history"][-1]
        assert (history["winnerTeamId"], history["side"]) == (tid, winning_side)
        end = next(e for e in w["events"] if e["kind"] == "round_end")
        assert (end["winnerTeamId"], end["side"]) == (tid, winning_side)
        assert all(c["score"] == credited[c["id"]] for c in view["clubs"])
        assert history["scoreByTeam"] == {i: credited[i] for i in ids}
        match.validate_bindings(w)
        if n != 34:
            assert view["phase"] == "result" and view["winnerTeamId"] is None
            match.next_round(w)
    assert view["phase"] == "finished" and view["winnerTeamId"] == winner
    assert credited[winner] == 19
    assert [e["winnerTeamId"] for e in w["events"] if e["kind"] == "match_end"] == [
        winner
    ]


@pytest.mark.parametrize("first_out", ["T", "CT"])
def test_ordered_eliminations_in_one_tick(first_out):
    w = match.initial(42)
    match.begin_live(w)
    for side in (first_out, "CT" if first_out == "T" else "T"):
        for a in w["agents"]:
            if a["team"] == side:
                damage(w, a, a, 100, "Огонь")
    match.advance(w)
    assert w["history"][-1]["side"] != first_out
    assert w["history"][-1]["winnerTeamId"] == match_score.side_team(w, side)


def planted(site, remaining):
    w = match.initial(218)
    match.begin_live(w)
    w["bomb"].update(
        carrier=None, site=site, x=POSITIONS[site][0][0], y=POSITIONS[site][0][1]
    )
    w.update(phase="planted", deadline=w["tick"] + remaining)
    for a in w["agents"]:
        a.update(path=[], dest=[], utility=[], hp=100, armor=80, helmet=True)
        if a["team"] == "T":
            a["x"], a["y"] = POSITIONS[site][a["slot"]]
            a.update(weapon="AK-47", cash=400, hp=64)
        else:
            a.update(
                x=25,
                y=105,
                heardSite=site,
                kit=False,
                hp=100 if a["slot"] == 0 else 0,
                weapon="AWP",
            )
    return w


@pytest.mark.parametrize("site", ["A", "B"])
def test_known_plant_with_ct_save_guard_exit_and_next_buy(site):
    w = planted(site, 165)
    attackers = [a for a in w["agents"] if a["team"] == "T"]
    ct = next(a for a in w["agents"] if a["team"] == "CT" and a["hp"])
    twin = deepcopy(w)
    hidden = next(a for a in twin["agents"] if a["id"] == ct["id"])
    hidden.update(saving=[55, 105], kit=True, cash=0, hp=1)
    match.advance(w)
    match.advance(twin)
    assert attackers == [a for a in twin["agents"] if a["team"] == "T"]
    assert ct["saving"] and not any(a["saving"] for a in attackers)
    assert all(a["status"] == "Прикрывает C4" for a in attackers)
    while w["phase"] == "planted":
        match.advance(w)
    assert w["history"][-1]["reason"] == "Взрыв C4"
    assert all(
        a["saving"] and a["hp"] and ai.distance(a, w["bomb"]) >= BLAST_RADIUS
        for a in attackers
    )
    assert ct["hp"] and ct["cash"] >= RULES["lossBase"]
    survived = {
        a["id"]: (equipment_value(a), a["cash"], a["weapon"]) for a in [ct, *attackers]
    }
    match.next_round(w)
    for a in w["agents"]:
        assert a["hp"] == 100
        if a["id"] in survived:
            assert (equipment_value(a), a["cash"], a["weapon"]) == survived[a["id"]]
        else:
            assert equipment_value(a) == 0 and a["weapon"] == "USP"
    match.begin_live(w)
    assert ct["weapon"] == "AWP" and all(a["weapon"] == "AK-47" for a in attackers)
    assert not any(
        e["kind"] == "buy" and e["item"] in WEAPONS and e["player"] in survived
        for e in w["events"]
    )


@pytest.mark.parametrize(("kit", "expected"), [(True, "defuse"), (False, "move")])
def test_defuse_budget_at_bomb(kit, expected):
    w = planted("A", 72)
    ct = next(a for a in w["agents"] if a["team"] == "CT")
    ct.update(x=w["bomb"]["x"], y=w["bomb"]["y"], kit=kit)
    obs = dict(
        phase=w["phase"],
        tick=w["tick"],
        deadline=w["deadline"],
        action=None,
        plan=w["plans"]["CT"],
        player=match.profile(w, ct),
        chemistry=w["domain"]["chemistry"],
    )
    assert ai.act(obs, ct, [ct], w["bomb"], [])[0] == expected


@pytest.mark.parametrize(
    ("weapon", "group", "helmet", "armor", "hp", "left"),
    [
        ("AK-47", "head", True, 100, 0, 84),
        ("M4A1-S", "head", True, 100, 8, 80),
        ("M4A1-S", "head", False, 100, 0, 100),
        ("AK-47", "chest", False, 100, 73, 96),
        ("AK-47", "arm", False, 100, 73, 96),
        ("AK-47", "leg", True, 100, 73, 100),
        ("AK-47", "stomach", True, 0, 55, 0),
        ("AWP", "chest", True, 100, 0, 99),
        ("HE", "blast", True, 100, 51, 76),
        ("Огонь", "fire", True, 100, 68, 100),
        ("C4", "blast", False, 4, 8, 0),
    ],
)
def test_game_damage_groups_and_armor(weapon, group, helmet, armor, hp, left):
    w = match.initial(11)
    a, b = w["agents"][0], w["agents"][5]
    b.update(armor=armor, helmet=helmet)
    base = (
        WEAPONS[weapon].damage
        if weapon in WEAPONS
        else {"HE": 98, "Огонь": 32, "C4": 100}[weapon]
    )
    impact(w, a, b, base, weapon, group)
    assert (b["hp"], b["armor"]) == (hp, left)
    if not left:
        assert not b["helmet"]
    assert w["stats"][a["id"]]["damage"] == 100 - hp
    if hp:
        impact(w, a, b, 1000, weapon, group)
    impact(w, a, b, 1000, weapon, group)
    assert w["stats"][a["id"]]["damage"] == 100
    assert w["stats"][b["id"]]["d"] == w["stats"][a["id"]]["k"] == 1
    assert sum(e["amount"] for e in w["events"] if e["kind"] == "damage") == 100


def test_background_and_observer_career_reports_allow_either_fixture_order(tmp_path, monkeypatch):
    monkeypatch.setenv("ESPORT_SIM_MAPS", str(tmp_path / "without-maps"))
    store = Store(tmp_path / "career.sqlite")
    pack = store.careers.pack(["austin-registration", 1])
    user = next(iter(career.roster_index(pack)))
    c = career.create(
        pack, dict(team=user, name="Тренер", mode="manager", scope="full")
    )
    fixture = next(e for e in c["queue"] if user in e["teams"])
    c["queue"] = [fixture]
    winners = set()
    for seed in range(1, 17):
        fixture["seed"] = seed
        fixture["teams"].reverse()
        game = career.initial(pack, c, fixture)
        background_game = deepcopy(game)
        background_game["agents"].reverse()
        background = career.simulate(background_game)
        while game["phase"] != "finished":
            match.advance(game)
            if game["tick"] % 128 == 0:
                match.project(game)
        view = match.project(game)["match"]
        assert view["coachTeamId"] == user
        assert career.result(game) == background
        entry = deepcopy(c)
        entry["queue"][0]["teams"].reverse()
        with store.transaction():
            store.careers.record(entry, background)
        h = entry["history"][-1]
        assert h["winnerTeamId"] == view["winnerTeamId"]
        assert h["score"] == [background["scoreByTeam"][t] for t in h["teams"]]
        assert (
            Counter(r["winnerTeamId"] for r in background["rounds"])
            == background["scoreByTeam"]
        )
        winners.add(h["winnerTeamId"])
        if len(winners) == 2:
            break
    assert winners == set(fixture["teams"])


def test_migrate_pre_scorebot_lab_and_parked_slots_without_replaying_rounds(tmp_path):
    from backend import checkpoints
    from test_career import act

    path = tmp_path / "world.sqlite"
    store = Store(path)
    pack = store.careers.pack(["austin-registration", 1])
    ids = list(career.roster_index(pack).values())[:2]
    act(store, "database-match", dict(id=pack["id"], revision=1, seed=517, rosters=ids))
    state = store.read()
    w = state["world"]
    while w["phase"] != "result":
        match.advance(w)
    expected = deepcopy(w)
    w.update(rules=match.PREVIOUS_VERSION, checkpointVersion=4)
    for k in ("firstAttackTeamId", "winnerTeamId", "scoreByTeam", "coachTeamId"):
        del w[k]
    for a in w["agents"]:
        for k in ("saving", "helmet", "teamId"):
            a.pop(k)
    for row in w["history"]:
        del row["winnerTeamId"], row["scoreByTeam"]
    for e in w["events"]:
        e.pop("winnerTeamId", None)
    raw = json.dumps(state, ensure_ascii=False)
    for table in ("slot", "active"):
        store.db.execute(f"INSERT OR REPLACE INTO {table} VALUES(1,?)", (raw,))
    for slot in ("auto", "1", "1.bak"):
        store.db.execute(
            "INSERT INTO career_slot VALUES(?,?,?,?,?)",
            ("parked", slot, "{}", raw, career_store.checksum(raw)),
        )
    store.db.close()
    store = Store(path)
    assert store.read()["world"]["domain"] == expected["domain"]
    assert dict(store.db.execute("SELECT source,body FROM checkpoint_backup")) == {
        k: raw for k in ("active", "slot", "parked/auto", "parked/1", "parked/1.bak")
    }
    for body, digest in store.db.execute("SELECT body,digest FROM career_slot"):
        assert career_store.checksum(body) == digest
        game = json.loads(body)["world"]
        assert game["checkpointVersion"] == checkpoints.VERSION
        assert game["scoreByTeam"] == expected["scoreByTeam"]
        assert game["history"] == expected["history"] and game["events"] == w["events"]
        assert all(not a["helmet"] for a in game["agents"])
    act(store, "load")
    assert store.read()["world"]["scoreByTeam"] == expected["scoreByTeam"]
