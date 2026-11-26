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

@pytest.mark.parametrize("previous", ["cs2-bo1.14", "cs2-bo1.15", "cs2-bo1.16"])
def test_recent_checkpoints_resume_from_the_recorded_tick(previous):
    state = match.initial(41000,map_id="de_nuke")
    match.advance(state)
    state["rules"] = previous
    tick, serial = state["tick"], state["serial"]
    match.advance(state)
    assert state["rules"] == cs2_maps.RULES
    assert state["rulesTransition"] == dict(previous=previous,tick=tick,lastEvent=serial)


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
    rafters = space.places[space.profile["guards"]["A"][0]]
    assert min(abs(orders[0]["hold"][2] - space.centers[i][2]) for i in rafters) * cs2_maps.UNIT <= 72


@pytest.mark.parametrize("scenario", ["Пистолетная","Эко","Частичная","Форс","Полная","Антиэко","Бонусная"])
def test_economy_plan_runs_in_private_preview(scenario):
    plan = tactics.propose("CT",scenario,42,map_id="de_nuke")
    preview = tactic_preview.simulate(plan)
    assert preview["economy"]["scenario"] == scenario
    assert (preview["economy"]["spent"] == 0) == (scenario == "Эко")


def test_existing_double_smoke_plan_remains_playable():
    plan = tactics.propose("T","Оружейная",42,map_id="de_nuke")
    smoke = dict(plan["slots"][0][0],kind="throw",utility="Дым")
    plan.update(format=1,slots=[[smoke,smoke.copy()],[],[],[],[]])
    tactics.validate(plan)
    game = match.initial(42,map_id="de_nuke")
    board = dict(plan,id="legacy-smokes",revision=1)
    game.update(round=2,nextBoard=board,previewBuy="Полная")
    for agent in game["agents"]:
        agent["cash"]=6500
    match.begin_live(game)
    assert game["agents"][0]["utility"].count("Дым")==2
    with pytest.raises(ValueError):
        tactics.validate(dict(plan,format=2))


def test_map_default_assigns_three_sectors_and_uses_delivered_readiness():
    from collections import Counter
    from backend import cs2_play
    state = match.initial(41000, map_id="de_dust2")
    space = cs2_maps.get("de_dust2")
    squad = [p for p in state["agents"] if p["team"] == "T"]
    plan = dict(site="A", lane=0, style="Контроль карты")
    probe = cs2_play.default_probe(space,squad,state["bomb"]["carrier"],plan,100)
    plan["probe"] = probe
    assert sorted(Counter(v["label"] for v in probe["stations"].values()).values()) == [1,2,2]
    for actor in squad:
        goal=probe["stations"][actor["id"]]["point"]
        assert space._reachable(cs2_maps.xyz(actor),[goal],actor["navArea"]) is not None
    probe["reports"] = {actor["id"]:160 for actor in squad}
    cs2_play.release_probe(space,plan,squad,[],155)
    assert not probe.get("released")
    cs2_play.release_probe(space,plan,squad,[],160)
    assert probe["released"] == 160


def test_dust_reserve_can_cover_a_legal_plant_after_anchor_loss():
    from backend import cs2_play

    game = match.initial(41000, map_id="de_dust2")
    match.begin_live(game)
    space = cs2_maps.get(game["mapId"])
    squad = [p for p in game["agents"] if p["team"] == "CT"]
    plan = game["plans"]["CT"]
    for site in ("A", "B"):
        orders = plan["orders"]["slots"]
        remaining = [p for p in squad if p["slot"] >= 2 or orders[p["slot"]]["site"] != site]
        cs2_play.assign_backup(space, plan, remaining, site, 2)
        reserve = plan["backup"]
        hold = tuple(reserve["hold"])
        actor = next(p for p in remaining if p["id"] == reserve["id"])
        assert space._reachable(cs2_maps.xyz(actor), [hold], actor["navArea"]) == hold
        assert any(
            space.hit(hold, space.centers[area], 1, 64) is None
            for area in space.plants[site]
        )


def test_nuke_postplant_escape_time_uses_the_route_that_is_walked():
    from math import dist
    from backend import cs2_play, match_performance
    from backend.match_rules import BLAST_RADIUS

    # Seed 41001, second-half pistol. The default NAV exit is across a blocked
    # portal. Walking to it on the correct floor takes almost the entire fuse.
    origin = (316.000005, 346.66668333333337, -63.666666666666664)
    planted = (328.4050742801617, 299.96775201988845, -63.78752247263657)
    space = cs2_maps.get("de_nuke")
    game = match.initial(41001, map_id="de_nuke")
    actor = game["agents"][0]
    actor.update(zip("xyz", origin))
    actor.update(navArea=1507, path=[], dest=None, status="Прикрывает C4")
    player = match.profile(game, actor)
    bomb = dict(zip("xyz", planted), site="B")
    state = dict(deadline=100, tick=0, plan={}, player=player)
    speed = 2 * match_performance.move_speed(player)
    assert space.nominal_exit(1507, origin, planted) / speed > 100
    goal = None
    for tick in range(100):
        state["tick"] = tick
        if goal is None:
            goal = cs2_play.exit_goal(space, state, actor, [actor], bomb)
        if goal is not None:
            space.walk(actor, goal, speed, [])
    assert dist(cs2_maps.xyz(actor), planted) >= BLAST_RADIUS


def test_anubis_grenade_contact_includes_float32_endpoint(monkeypatch):
    from backend.cs2_collision import THROW

    space = cs2_maps.get("de_anubis")
    start = (217.59938814256856, 275.5744102415004, 4.333335441666666)
    # Actual last step of CT5's flash. Test the boundary from both sides at
    # float32 precision, and a real gap that must remain traversable.
    for error in (-0.000001, 0, 0.000001):
        end = (216 + error, 282.0, 0.333335441666666)
        t, material, normal = space.hit(start, end, THROW, terminal=True)
        assert 0.99999 < t <= 1 and material == "concrete" and normal[0] > 0.99
    assert space.hit(start, (216.001, 282.0, 0.333335441666666), THROW, terminal=True) is None

    # Reproduce the runner on which the single center ray missed the triangle
    # seam. The small endpoint query must return the same contact plane.
    collision = space.collision
    intersect = collision.scene.first_many

    def miss_terminal_center(starts, directions, limits, channel):
        faces, distances, normals = intersect(starts, directions, limits, channel)
        if channel == THROW and len(starts) == 1 and distances[0] > 0.99999:
            faces[0] = -1
        return faces, distances, normals

    monkeypatch.setattr(collision.scene, "first_many", miss_terminal_center)
    collision.trace.cache_clear()
    try:
        t, material, normal = space.hit(
            start, (216.0, 282.0, 0.333335441666666), THROW, terminal=True
        )
        assert t == 1 and material == "concrete" and normal[0] > 0.99
    finally:
        collision.trace.cache_clear()


def test_defensive_smoke_distinguishes_legal_plant_and_other_floor():
    space = cs2_maps.get("de_nuke")
    upper, lower = (space.site_points[s] for s in ("A", "B"))
    assert space.smokes_plant("A", tuple(upper))
    assert not space.smokes_plant("B", tuple(upper))
    assert space.smokes_plant("B", tuple(lower))


def test_nuke_scans_legal_parts_of_nav_polygons_cut_by_the_site_trigger():
    space = cs2_maps.get("de_nuke")
    for site, points in space.plant_surfaces.items():
        assert all(space.site_at(p) == site for p in points)
    assert any(space.locate(p) not in space.plants[site]
               for site,points in space.plant_surfaces.items() for p in points)
