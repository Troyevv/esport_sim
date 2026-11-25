import json
import sqlite3
from itertools import combinations
from copy import deepcopy
from uuid import uuid4

import pytest

from backend import career, database, match, skills
from backend.store import Conflict, Store


def intent(store, kind, value=None):
    state = store.read()
    return dict(
        id=str(uuid4()),
        context=state["context"],
        revision=state["revision"],
        kind=kind,
        value=value,
    )


def act(store, kind, value=None):
    return store.apply(intent(store, kind, value))


def start(store, **changes):
    pack = store.careers.pack(["austin-registration", 1])
    team = next(t for t, data in pack["teams"].items() if data["name"] == "Vitality")
    value = dict(
        id=pack["id"], revision=1, team=team, name="Тренер", mode="owner", scope="full"
    )
    act(store, "career-create", value | changes)
    return store.read()["career"]["id"]


def run_queue(store):
    while item := store.careers.work(store.read()):
        token, game = item
        result = career.simulate(game) if game else None
        assert store.careers.commit_work(token, result)
        assert not store.careers.commit_work(token, result)


def test_calendar_slots_switch_restart_and_finish(tmp_path):
    path = tmp_path / "profile.sqlite"
    store = Store(path)
    act(store, "save")  # R0 slot and scenario survive entering and leaving a career.
    lab = store.read()["world"]
    cid = start(store)
    c = store.read()["career"]
    public = store.careers.detail(store.read())["active"]
    assert all(
        skills.HIDDEN.isdisjoint(p["skills"]) and "potential" not in p
        for p in public["roster"]
    )
    assert "career" not in store.snapshot("full")
    first = intent(store, "career-advance")
    assert store.apply(first) == store.apply(first)
    token, game = store.careers.work(store.read())
    report = career.simulate(game)
    before = store.read()
    with pytest.raises(ValueError, match="не соответствует"):
        store.careers.commit_work(token, report | {"seed": -1})
    assert store.read() == before
    act(store, "career-save", {"slot": "2"})
    act(store, "career-load", {"slot": "2"})
    assert not store.careers.commit_work(token, report)
    run_queue(store)
    waiting = store.read()["career"]
    assert waiting["date"] > c["date"] and waiting["queue"][0]["teams"][0] == c["team"]
    assert waiting["history"] and waiting["history"][0]["score"] == report["score"]
    assert store.careers.report(waiting["history"][0]["result"]) == report
    with pytest.raises(ValueError, match="матч-центре"):
        act(store, "career-advance")
    act(store, "career-play")
    assert store.read()["world"]["domain"]["authority"]["mode"] == "owner"
    act(store, "speed", 128)
    act(store, "start")
    assert store.tick()
    act(store, "pause")
    saved = store.read()["world"]
    act(store, "save")
    expected = career.simulate(deepcopy(saved))
    stale = intent(store, "load")
    second = start(store, mode="manager", name="Другой тренер")
    assert cid != second and not store.read()["career"]["history"]
    act(store, "career-open", {"career": cid})
    assert store.read()["world"] == saved
    with pytest.raises(Conflict):
        store.apply(stale)
    store.db.close()
    store = Store(path)
    assert store.read()["world"] == saved
    act(store, "load")
    assert store.read()["world"] == saved
    act(store, "start")
    while store.tick():
        pass
    c = store.read()["career"]
    assert c["history"][-1]["score"] == expected["score"]
    assert store.careers.report(c["history"][-1]["result"]) == expected
    act(store, "career-finish")
    act(store, "career-advance")
    run_queue(store)
    end = store.read()["career"]
    assert end["milestones"][-1]["matches"] == len(end["history"])
    assert end["date"] == "2025-05-16"
    act(store, "career-lab")
    assert store.read()["world"] == lab
    act(store, "load")
    assert store.read()["world"] == lab
    store.db.close()


def test_damaged_slot_and_pinned_edition(tmp_path):
    store = Store(tmp_path / "profile.sqlite")
    cid = start(store)
    act(store, "career-save")
    act(store, "career-advance")
    act(store, "career-save")
    pack = database.get(store.db, "austin-registration", 1)
    tid = store.read()["career"]["team"]
    with store.transaction():
        database.edit(
            store.db,
            pack["id"],
            1,
            "teams",
            tid,
            dict(pack["teams"][tid], name="Новое имя"),
            False,
        )
    assert store.careers.detail(store.read())["active"]["teams"][tid] == "Vitality"
    store.db.execute(
        "UPDATE career_slot SET body='broken' WHERE career=? AND slot='1'", (cid,)
    )
    before = store.read()
    with pytest.raises(ValueError, match="повреждено"):
        act(store, "career-load")
    assert store.read() == before
    act(store, "career-load", {"slot": "1.bak"})
    assert store.read()["career"]["progress"] is None
    act(store, "career-save")
    act(store, "career-load")
    for params in [
        dict(scope="fast", regions=[]),
        dict(name=" "),
        dict(mode=[]),
        dict(team="missing"),
    ]:
        with pytest.raises(ValueError):
            start(store, **params)
    assert store.read()["career"]["id"] == cid
    before = store.read()
    with pytest.raises(ValueError):
        act(store, "career-exhibition", {})
    assert store.read() == before
    act(
        store,
        "career-exhibition",
        dict(id=pack["id"], revision=1, seed=91, rosters=list(pack["rosters"])[:2]),
    )
    assert not store.read().get("career") and store.read()["world"]["seed"] == 91
    act(store, "career-open", {"career": cid})
    assert store.read()["career"] == before["career"]
    store.db.close()


def test_first_profile_migration_is_atomic(tmp_path):
    path = tmp_path / "profile.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE active(id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    db.execute("INSERT INTO active VALUES(1,?)", (json.dumps({"version": 777}),))
    db.commit()
    with pytest.raises(Conflict):
        Store(path)
    assert db.execute("PRAGMA user_version").fetchone() == (0,)
    assert not db.execute(
        "SELECT name FROM sqlite_master WHERE name='career_slot'"
    ).fetchone()
    with sqlite3.connect(str(path) + ".pre-r33.sqlite") as backup:
        assert (
            backup.execute("SELECT * FROM active").fetchall()
            == db.execute("SELECT * FROM active").fetchall()
        )
    db.close()


def test_background_opponents_rotate_over_the_cycle():
    pack = json.loads(database.STARTER.read_text(encoding="utf-8"))["package"]
    team = next(iter(career.roster_index(pack)))
    c = career.create(
        pack, dict(team=team, name="Тренер", mode="manager", scope="full")
    )
    encountered = set()
    for week in range(len(c["teams"]) - 1):
        if week:
            c["queue"].clear()
            career.schedule(c)
        games = [e for e in c["queue"] if e["kind"] == "match"]
        assert len({t for e in games for t in e["teams"]}) == len(c["teams"])
        encountered.update(tuple(sorted(e["teams"])) for e in games)
    assert encountered == set(combinations(sorted(c["teams"]), 2))


def test_career_scene_contains_public_links_without_private_ratings(tmp_path):
    from backend.career_scene import directory

    store = Store(tmp_path / "scene.sqlite")
    try:
        start(store)
        state = store.read()
        pack = store.careers.pack(state["career"]["source"])
        result = directory(pack, store.badges.index(pack), store.portraits)
        own = state["career"]["team"]
        for player_id in result["teams"][own]["members"]:
            player = result["players"][player_id]
            assert own in player["teams"]
            assert set(player).isdisjoint({"potential", "skills", "mapKnowledge", "roleMastery", "ratings"})
        for staff in result["staff"].values():
            assert "preparation" not in staff
        active = store.careers.detail(state)["active"]
        assert all(skills.HIDDEN.isdisjoint(p["skills"]) for p in active["roster"])
        assert 0 <= active["teamRating"] <= 100
    finally:
        store.db.close()
