"""Fast format/state-machine contracts and integration on the pinned R4.1 map pack."""
import json
from copy import deepcopy
from itertools import product
from uuid import uuid4

import pytest

from backend import career, cs2_maps, match, series, veto
from backend.store import Store


def act(store, kind, value=None):
    state = store.read()
    request = dict(id=str(uuid4()), context=state["context"], revision=state["revision"], kind=kind, value=value)
    receipt = store.apply(request)
    assert store.apply(request) == receipt


@pytest.mark.parametrize("best", [1, 3, 5])
def test_veto_reload_manual_sides_and_delegation(monkeypatch, tmp_path, best):
    monkeypatch.setattr(cs2_maps, "installed", lambda: list(cs2_maps.NAMES))
    path = tmp_path / "home.sqlite"
    store = Store(path)
    act(store, "match", dict(seed=17, bestOf=best))
    state = store.snapshot("full")["world"]["series"]
    assert len(state["pool"]) == 7 and "de_train" not in state["pool"]
    assert "domain" not in state and "skills" not in str(state)
    used = {a["map"] for a in state["actions"]}
    choice = next(m for m in state["pool"] if m not in used)
    act(store, "series-veto", {"choice": choice})
    act(store, "save")
    saved = store.read()["world"]
    with pytest.raises(ValueError):
        act(store, "series-veto", {"choice": choice})
    assert store.read()["world"] == saved
    act(store, "series-veto", {"delegate": "staff"})
    expected = store.read()["world"]["series"]
    store.db.close()
    store = Store(path)
    act(store, "load")
    assert store.read()["world"] == saved
    while store.read()["world"]["series"]["stage"] == "veto":
        w = store.read()["world"]
        step = w["series"]["steps"][len(w["series"]["actions"])]
        choice = "CT" if step["kind"] == "side" else veto.available(w["series"])[0]
        act(store, "series-veto", {"choice": choice})
    s = store.read()["world"]["series"]
    assert {a["kind"] for a in s["actions"]} >= {"ban", "side", "decider"}
    assert s["order"][-1]["picker"] is None and all(m["attack"] in s["teams"] for m in s["order"])
    assert len({m["map"] for m in s["order"]}) == len(expected["order"]) == best
    assert len(expected["actions"]) == len(expected["steps"])
    with pytest.raises(ValueError):
        act(store, "start")
    store.db.close()


def test_scouting_privacy_recency_and_draw(monkeypatch):
    monkeypatch.setattr(cs2_maps, "installed", lambda: list(veto.ACTIVE))
    w = series.initial(2, 3)
    before = veto.recommend(w, "staff")
    away = w["rosterIds"][1]
    for member in w["domain"]["rosters"][away]["members"]:
        p = w["domain"]["players"][member["player"]]
        p.update(skills=dict.fromkeys(p["skills"], 0), mapKnowledge={"dust2": 100})
    assert veto.recommend(w, "staff") == before
    picks = set()
    for seed in range(16):
        w = series.initial(seed, 3)
        veto.advance(w, "captain")
        picks.add(w["series"]["order"][0]["map"])
    assert len(picks) > 1
    event = dict(date="2026-02-01", teams=["a","b"], mapId="de_nuke", winnerTeamId="a")
    rows = veto.evidence(["de_nuke"], ["a","b"], [event, dict(event,date="2026-12-01")], "2026-11-24")
    assert rows["a"]["de_nuke"]["games"] == rows["a"]["de_nuke"]["wins"] == 1
    assert 0 < rows["a"]["de_nuke"]["weight"] < .2
    assert not rows["b"]["de_nuke"]["wins"]


@pytest.mark.parametrize("best", [1,3,5])
def test_all_winning_paths_stop_on_clinch(monkeypatch, best):
    monkeypatch.setattr(cs2_maps, "installed", lambda: list(veto.ACTIVE))
    w = series.initial(11, best)
    veto.advance(w, "captain")
    # Unit boundary: feed completed real-engine report shape for every possible win sequence.
    for path in product(w["series"]["teams"], repeat=best):
        s = deepcopy(w["series"])
        for i, winner in enumerate(path):
            s["stage"] = "playing"
            report = dict(winnerTeamId=winner)
            monkeypatch.setattr(series, "map_result", lambda game: report)
            series.finish_map({"series":s})
            if s["stage"] == "finished":
                assert len(s["results"]) == i+1 and s["score"][winner] == best//2+1
                with pytest.raises(ValueError):
                    series.next_map({"series":s})
                break
        assert s["winner"]


@pytest.mark.skipif(not set(veto.ACTIVE) <= set(cs2_maps.installed()), reason="Требуется игровой пул R4.1")
def test_real_career_series_store_matches_background(tmp_path):
    store = Store(tmp_path / "career.sqlite")
    pack = store.careers.pack(["austin-registration",1])
    team = next(iter(career.roster_index(pack)))
    act(store, "career-create", dict(id=pack["id"], revision=1, scope="full", name="Тренер", mode="owner", team=team))
    state = store.read()
    c = state["career"]
    e = next(e for e in c["queue"] if team in e["teams"])
    c.update(queue=[e], date=e["date"])
    store.write(state)
    act(store, "career-play")
    background = career.simulate(deepcopy(store.read()["world"]))
    act(store, "series-veto", {"delegate":"captain"})
    while True:
        act(store, "series-next")
        act(store, "speed", 128)
        act(store, "start")
        assert store.tick()
        act(store, "save")
        saved = store.read()["world"]
        act(store, "load")
        assert store.read()["world"] == saved
        while store.tick():
            pass
        w = store.read()["world"]
        assert w["phase"] == "finished"
        if w["series"]["stage"] == "finished":
            break
        assert not store.read()["career"]["history"]
        with pytest.raises(ValueError):
            act(store, "career-finish")
    assert series.result(w) == background
    assert len(store.read()["career"]["history"]) == 1
    assert store.careers.report(store.read()["career"]["history"][0]["result"]) == background
