"""Integration checks using the same verified map pack as the packaged game."""

import gzip
import json
from copy import deepcopy
from time import perf_counter
from uuid import uuid4

import psutil
import pytest

from tests.reference_kernel import cs2_maps, match
from backend import career, checkpoints, database, tactic_preview, tactics
from backend import match as production
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
    production.assign(game, dict(board, id="installed-test", revision=1))
    production.advance(game, 180)
    checkpoints.validate_current(game)
    with store.transaction():
        store.write(state)
    command(store, "save")
    store.db.close()
    store = Store(path)
    command(store, "load")
    restored = store.read()["world"]
    assert restored["mapId"] == name
    production.advance(game, 60)
    production.advance(restored, 60)
    assert production.project(restored) == production.project(game)
    audience = production.project(restored, "CT")
    assert all(
        a["team"] == "CT"
        or a["id"]
        in {i for b in restored["agents"] if b["team"] == "CT" for i in b["visible"]}
        for a in audience["agents"]
    )
    spar = tactic_preview.simulate(board)
    assert len(spar["frames"]) > 2 and len(spar["frames"][0][0]) == 5
    store.db.close()


@pytest.mark.parametrize("name", cs2_maps.NAMES)
def test_background_and_observed_share_report_across_the_map_pool(tmp_path, name):
    store = Store(tmp_path / "career.sqlite")
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    teams = career.roster_index(pack)
    state = career.create(
        pack, dict(team=next(iter(teams)), name="Тренер", mode="owner", scope="full")
    )
    assert set(state["mapPool"]) == set(cs2_maps.NAMES)
    event = next(e for e in state["queue"] if e["kind"] == "match")
    fixture = dict(event, mapId=name)
    fixture.pop("bestOf", None)  # Explicit single-map exhibition across all installed maps.
    fixture.pop("edition", None)  # An exhibition has no tournament series to record.
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
    production.advance(observed, 80)
    saved = json.loads(json.dumps(observed))
    checkpoints.validate_current(saved)
    assert career.simulate(saved) == expected
    store.careers.record(frozen, expected)
    assert store.careers.report(frozen["history"][-1]["result"]) == expected
    store.db.close()

@pytest.mark.parametrize("previous", ["cs2-bo1.14", "cs2-bo1.15", "cs2-bo1.16", "cs2-bo1.17", "cs2-bo1.18", "cs2-bo1.19"])
def test_recent_checkpoints_resume_from_the_recorded_tick(previous):
    state = production.initial(41000,map_id="de_nuke")
    production.advance(state)
    state["rules"] = previous
    tick, serial = state["tick"], state["serial"]
    production.advance(state)
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
    from tests.reference_kernel import cs2_play
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
    from tests.reference_kernel import cs2_play

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
    from tests.reference_kernel import cs2_play, match_performance
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

    from types import SimpleNamespace
    monkeypatch.setattr(collision, "scene", SimpleNamespace(first_many=miss_terminal_center))
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


def test_reported_carrier_redirects_living_defenders_before_plant():
    from tests.reference_kernel import cs2_defense, cs2_play

    game = match.initial(41000, map_id="de_dust2")
    match.begin_live(game)
    space = cs2_maps.get(game["mapId"])
    plan = game["plans"]["CT"]
    squad = [p for p in game["agents"] if p["team"] == "CT"]
    leader = squad[0]
    carrier = next(p for p in game["agents"] if p["team"] == "T")
    # The actual attacker stays at spawn through both reviews.
    for site in ("A", "B"):
        game["tick"] += 12
        point = next(
            space.centers[i]
            for i in space.plants[site]
            if space.site_at(space.centers[i]) == site
        )
        leader["knowledge"][carrier["id"]] = dict(
            zip(("x", "y", "z"), point),
            id=carrier["id"],
            carryingC4=True,
            tick=game["tick"],
            source="Радио",
        )
        cs2_play.direct_defense(space, game, plan, squad, leader)
        assert {cs2_defense.assignment(plan, p, squad)["site"] for p in squad} == {site}
        assert plan["confirmedAttack"]["site"] == site
        assert game["events"][-1]["carrierSite"] == site


def test_retake_wait_ends_when_the_partner_or_time_is_lost():
    from tests.reference_kernel import cs2_retake

    a = dict(id="a", x=10, y=10, z=0)
    b = dict(id="b")
    for alone in (False, True):
        duty = dict(stage=[10, 10, 0], partner="b", release=125, latest=130)
        state = dict(tick=120, plan=dict(retake=dict(duties={"a": duty, "b": {}})))
        assert cs2_retake.staging(state, a, [a, b]) == (10, 10, 0)
        assert a["status"] == "Ждёт напарника на ретейке"
        if not alone:
            state["tick"] = 130
        assert cs2_retake.staging(state, a, [a] if alone else [a, b]) is None
        assert duty["done"]


def test_pair_waits_for_real_flash_and_checks_before_releasing_escort():
    from tests.reference_kernel import cs2_openings
    from tools.cs2_opening_audit import record
    from math import dist
    from random import Random

    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    teams = Random(843).sample(sorted(career.roster_index(pack).values()), 2)
    # Exactly the normal economy and captain call used in the 40-second audit.
    row = record(pack, teams, "de_dust2", 15)
    flashes = [
        e
        for e in row["events"]
        if e.get("openingZone")
        and e["utility"] == "Свет"
        and e["supported"] != e["player"]
    ]
    assert flashes
    first_contact = min(e["tick"] for e in row["events"] if e["kind"] == "contact")
    slots = {pid: i for i, (pid, _, _) in enumerate(row["agents"])}

    def followed_signal(e):
        who = e["supported"]
        departure = row["jobs"][who].get("departed", 0)
        time = departure - row["start"]
        if not (0 <= departure - e["land"] <= 15 and 0 < time < first_contact):
            return False

        def position(tick):
            _, players = min(row["frames"], key=lambda frame: abs(frame[0] - tick))
            return players[slots[who]][:3]

        return dist(position(time), position(time + 10)) > 4

    assert any(followed_signal(e) for e in flashes)

    plan = dict(
        opening=dict(
            quiet=False,
            focus=["Long"],
            jobs={
                "scout": dict(
                    zone="Long", watch=[10, 0, 0], role="разведка", partner="escort"
                ),
                "escort": dict(
                    zone="Long",
                    partner="scout",
                    handoff=dict(zone="Short"),
                    role="страховка",
                ),
            },
            reports={"scout": dict(zone="Long", observed=11, due=14)},
        )
    )
    squad = [dict(id="scout"), dict(id="escort")]
    captain = dict(id="scout", knowledge={})
    cs2_openings.review(None, plan, squad, 13, captain)
    assert "handoff" in plan["opening"]["jobs"]["escort"]
    captain["knowledge"]["T1"] = dict(x=10, y=2, z=0, tick=13, source="Радио")
    cs2_openings.review(None, plan, squad, 14, captain)
    assert "handoff" in plan["opening"]["jobs"]["escort"]
    plan["opening"]["reports"]["scout"].update(observed=21, due=24)
    cs2_openings.review(None, plan, squad, 24, captain)
    assert plan["opening"]["jobs"]["escort"]["zone"] == "Short"
    assert plan["opening"]["jobs"]["scout"]["holdsFor"] == "escort"


def test_dust2_short_long_hearing_depends_on_the_actual_approach():
    from tests.reference_kernel import match_ai

    space = cs2_maps.get("de_dust2")
    game = match.initial(65400, map_id="de_dust2")
    listener, source = game["agents"][5], game["agents"][0]
    listener.update(hp=100, visible=[])
    # Dated NAV. These walkable approaches are within 35 units of the
    # ShortStairs and LongA map markers, respectively.
    for who, ident in ((listener, 1248), (source, 1521)):
        who.update(match_ai.at(space.centers[ident]))
    match_ai.heard_action(game, space, source, [listener], "Шаги", 88)
    cue, = listener["knowledge"].values()
    assert cue["witness"] == listener["id"] and cue["id"] != source["id"]
    assert cs2_maps.xyz(cue) != cs2_maps.xyz(source)
    listener["knowledge"].clear()
    listener.update(match_ai.at(space.centers[968]))
    source.update(match_ai.at(space.centers[1682]))
    match_ai.heard_action(game, space, source, [listener], "Шаги", 88)
    assert not listener["knowledge"]


def test_authoritative_native_owner_survives_batches_and_reopens_saved_game(tmp_path, monkeypatch):
    store = Store(tmp_path / "native.sqlite")
    command(store, "match", dict(seed=41000, map="de_nuke"))
    state = store.read()
    state.update(running=True, speed=8)
    with store.transaction():
        store.write(state)
    reference = deepcopy(state["world"])
    expected = []
    for _ in range(9):
        for _ in range(8):
            match.advance(reference)
        expected.append(json.dumps(reference, ensure_ascii=False))

    def unexpected(*args):
        pytest.fail("The production match called a Python tick")

    monkeypatch.setattr(match, "advance", unexpected)
    for index, snapshot in enumerate(expected):
        store.tick()
        assert json.dumps(store.read()["world"], ensure_ascii=False) == snapshot
        if index == 0:
            first_owner = store.match_owner[1]
        elif index == 1:
            assert store.match_owner[1] is first_owner
        if index == 6:
            command(store, "save")
            command(store, "load")
            state = store.read()
            state.update(running=True, speed=8)
            with store.transaction():
                store.write(state)
    store.db.close()
