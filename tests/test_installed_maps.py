"""Integration checks using the same verified map pack as the packaged game."""

import gzip
import json
from copy import deepcopy
from time import perf_counter
from uuid import uuid4

import psutil
import pytest

from backend import (
    career,
    checkpoints,
    cs2_maps,
    database,
    match,
    tactic_preview,
    tactics,
)
from backend.store import Store

pytestmark = pytest.mark.skipif(
    len(cs2_maps.installed()) != 9, reason="Нужен импорт девяти карт"
)


def command(store, kind, value=None):
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


@pytest.mark.parametrize("name", cs2_maps.NAMES)
def test_real_map_exhibition_save_and_board(tmp_path, name):
    path = tmp_path / "home.sqlite"
    store = Store(path)
    command(store, "match", dict(seed=41, map=name))
    state = store.read()
    game = state["world"]
    board = tactics.propose("T", "Пистолетная", 41, map_id=name)
    match.assign(game, dict(board, id="installed-test", revision=1))
    for _ in range(180):
        match.advance(game)
    checkpoints.validate_current(game)
    with store.transaction():
        store.write(state)
    command(store, "save")
    store.db.close()
    store = Store(path)
    command(store, "load")
    restored = store.read()["world"]
    assert restored["mapId"] == name
    for _ in range(60):
        match.advance(game)
        match.advance(restored)
    assert match.project(restored) == match.project(game)
    audience = match.project(restored, "CT")
    assert all(
        a["team"] == "CT"
        or a["id"]
        in {i for b in restored["agents"] if b["team"] == "CT" for i in b["visible"]}
        for a in audience["agents"]
    )
    spar = tactic_preview.simulate(board)
    assert len(spar["frames"]) > 2 and len(spar["frames"][0][0]) == 5
    store.db.close()


def test_background_and_observed_share_report_across_the_map_pool(tmp_path):
    store = Store(tmp_path / "career.sqlite")
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    teams = career.roster_index(pack)
    state = career.create(
        pack, dict(team=next(iter(teams)), name="Тренер", mode="owner", scope="full")
    )
    assert set(state["mapPool"]) == set(cs2_maps.NAMES)
    event = next(e for e in state["queue"] if e["kind"] == "match")
    for name in cs2_maps.NAMES:
        fixture = dict(event, mapId=name)
        frozen = dict(state, queue=[fixture], history=[])
        started = perf_counter()
        game = career.initial(pack, frozen, fixture)
        initialized = perf_counter() - started
        observed = deepcopy(game)
        started = perf_counter()
        expected = career.simulate(game)
        elapsed = perf_counter() - started
        rss = psutil.Process().memory_info().rss / 2**20
        print(f"CAREER {name} init={initialized:.2f}s BO1={elapsed:.2f}s RSS_after={rss:.1f}MiB")
        for _ in range(80):
            match.advance(observed)
        saved = json.loads(json.dumps(observed))
        checkpoints.validate_current(saved)
        assert career.simulate(saved) == expected
        store.careers.record(frozen, expected)
        assert store.careers.report(frozen["history"][-1]["result"]) == expected
    store.db.close()

def test_nuke_anchors_and_floor_reports_before_contact():
    game = match.initial(41000, map_id="de_nuke")
    # A checkpoint from the earlier PR keeps its ledger and marks the first new tick.
    game["rules"] = cs2_maps.PREVIOUS_RULES
    serial = game["serial"]
    while game["phase"] == "freeze":
        match.advance(game)
    assert game["rulesTransition"] == dict(previous=cs2_maps.PREVIOUS_RULES, tick=0, lastEvent=serial)
    assert game["rules"] == cs2_maps.RULES
    space = cs2_maps.get("de_nuke")
    orders = game["plans"]["CT"]["orders"]["slots"]
    for i, site in enumerate(("A", "B")):
        assert space.reported_site(space.site_points[site]) == site
        hold = orders[i]["hold"]
        assert orders[i]["site"] == site
        assert any(space.hit(hold, space.centers[area], 1, 64) is None for area in space.plants[site])
    assert orders[4]["hold"] != orders[0]["hold"]
