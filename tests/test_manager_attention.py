from copy import deepcopy
from uuid import uuid4

import pytest

from backend import attention, career, cs2_maps, database, map_install, registrations


def send(store, kind, value=None):
    state = store.read()
    return store.apply(
        dict(
            id=str(uuid4()),
            context=state["context"],
            revision=state["revision"],
            kind=kind,
            value=value,
        )
    )


def test_existing_aurora_conflict_is_actionable_after_reload(tmp_path, monkeypatch):
    from backend.store import Store

    monkeypatch.setattr(cs2_maps, "installed", lambda: list(cs2_maps.NAMES))
    path = tmp_path / "profile.sqlite"
    store = Store(path)
    pack = database.get(store.db, database.STAFF_RELEASE, 1)
    team = next(k for k, t in pack["teams"].items() if t["name"] == "Aurora Gaming")
    send(
        store,
        "career-create",
        dict(
            id=pack["id"],
            revision=1,
            team=team,
            name="Аврора",
            scope="full",
            mode="owner",
        ),
    )
    state = store.read()
    c = state["career"]
    events = c["circuit"]["editions"]
    major, league = events["pgl-major-2026"], events["ecl-eu-2026-13"]
    registrations.signup(c, league, team, pack, prioritise={major["id"]})
    c["error"] = "Пересечение дат: Major"
    # An existing, paused save at the last pending calendar review of the day.
    c["queue"] = [r for r in c["queue"] if r["date"] > c["date"]]
    with store.transaction():
        store.write(state)
        store.careers.save(state, "2")
    store.db.close()
    store = Store(path)
    send(store, "career-load", {"slot": "2"})
    rows = store.careers.detail(store.read())["active"]["attention"]
    assert {r["kind"] for r in rows if r["level"] == "required"} == {
        "conflict",
        "roster",
    }
    with pytest.raises(ValueError):
        send(store, "career-advance")
    roster_history = deepcopy(major["registrations"][team])
    send(
        store,
        "career-entry",
        dict(edition=league["id"], action="prioritise", release=[major["id"]]),
    )
    send(
        store,
        "career-entry",
        dict(
            edition=league["id"],
            action="submit",
            players=pack["rosters"][c["teams"][team]]["players"],
            reserves=[],
            coach=None,
        ),
    )
    updated = store.read()["career"]
    assert (
        updated["circuit"]["editions"][major["id"]]["registrations"][team]
        == roster_history
    )
    assert updated["circuit"]["editions"][major["id"]]["entries"][team] == "withdrawn"
    assert not attention.blockers(updated, pack, {"version": 1})
    send(store, "career-advance")
    assert store.read()["career"]["progress"]
    # A review opening a required invitation stops the worker before another fixture.
    state = store.read()
    c = state["career"]
    next_event = c["queue"][0]
    league = c["circuit"]["editions"][league["id"]]
    league["entries"][team] = "offered"
    league["replyBy"] = {team: league["lock"]}
    previous_date = c["date"]
    with store.transaction():
        store.write(state)
    token, game = store.careers.work(state)
    assert game is None and store.careers.commit_work(token, None)
    stopped = store.read()["career"]
    assert (
        stopped["progress"] is None
        and stopped["date"] == previous_date
        and stopped["queue"][0] == next_event
    )
    assert any(
        r["kind"] == "invitation"
        for r in attention.blockers(stopped, pack, {"version": 1})
    )
    send(store, "career-entry", dict(edition=league["id"], action="leave"))
    send(store, "career-advance")
    store.db.close()


def test_map_restore_repairs_real_assets_without_rewriting_healthy_files(
    tmp_path, monkeypatch
):
    from pathlib import Path

    packs = Path(__file__).resolve().parents[1] / "resources/cs2" / map_install.BUILD
    name = "de_mirage"
    monkeypatch.setattr(map_install, "MANIFEST", {name: map_install.MANIFEST[name]})
    map_install.restore(tmp_path, packs)
    radar = tmp_path / name / (name + ".png")
    modified = radar.stat().st_mtime_ns
    collision = tmp_path / name / "collision.bin"
    collision.write_bytes(b"old version")
    (tmp_path / name / "gameplay.json").unlink()
    map_install.restore(tmp_path, packs)
    assert map_install.verified(tmp_path) and radar.stat().st_mtime_ns == modified
    collision.write_bytes(b"damaged after start")
    with pytest.raises(ValueError, match="восстановить карту"):
        map_install.restore(tmp_path, tmp_path / "missing distribution")


def test_rival_calendar_clash_is_resolved_by_the_rival(monkeypatch):
    monkeypatch.setattr(cs2_maps, "installed", lambda: list(cs2_maps.NAMES))
    pack = {
        "rosters": {
            t: {"players": [t + str(i) for i in range(5)]}
            for t in ("aurora", "rival", "third")
        }
    }
    fixtures = [
        dict(
            kind="match",
            id=k,
            date="2026-12-03",
            edition=k,
            teams=teams,
            bestOf=3,
            stage=0,
        )
        for k, teams in (("cup", ["aurora", "rival"]), ("open", ["rival", "third"]))
    ]
    events = {
        f["edition"]: dict(
            id=f["edition"], title=f["edition"],
            rules={"pool": ["de_nuke"]},
            stages=[{}],
            registrations={t: [pack["rosters"][t]] for t in f["teams"]},
        )
        for f in fixtures
    }
    c = dict(
        date="2026-12-03",
        club="Aurora Gaming", progress=None,
        team="aurora",
        teams={t: t for t in pack["rosters"]},
        circuit=dict(editions=events, bench={}),
        queue=fixtures,
    )
    assert attention.autonomous_fixture(c, fixtures[0], pack)
    assert not list(attention.fixture_items(c, pack, {}))
    career.start_advance(c, administrative=True)
    assert c["progress"] is not None
    c["queue"] = fixtures[:1]
    assert [r["action"] for r in attention.fixture_items(c, pack, {})] == ["play"]
    events["cup"]["registrations"]["aurora"] = [{"players": ["absent"]}]
    assert [r["kind"] for r in attention.fixture_items(c, pack, {})] == ["replace"]
