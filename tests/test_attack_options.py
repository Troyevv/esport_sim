"""Re-evaluate the same game checkpoint through the production captain and movement executors."""
from copy import deepcopy
import gzip
import json
import random
from math import dist

import pytest

from backend import career, cs2_maps, database, match, native_match_state
from tests.test_group_tasks import notice, put
from tests.test_peer_radio import delivered, scenario
from tests.test_small_groups import execute, point
from tests.test_team_attack import review, squad


pytestmark = pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна карта Dust II")


@pytest.fixture
def w():
    world = match.initial(17, map_id="de_dust2", agent_policy=9)
    match.advance(world, 45)
    world["tick"] += 40
    return world


def obstruction(world, observed, due):
    sender = next(a for a in squad(world) if not a["appointed"])
    packet = dict(team="T", sender=sender["id"], blockedSite=world["plans"]["T"]["site"],
                  observed=observed, due=due)
    world["messages"].append(packet)
    return delivered(world, due)


def test_each_new_switch_needs_new_evidence_and_time(w):
    original = w["plans"]["T"]["site"]
    assert review(w)["plans"]["T"]["commandKind"] == "scout"
    tick = w["tick"]
    informed = obstruction(w, tick, tick+3)
    rotated = review(informed)
    plan = rotated["plans"]["T"]
    assert plan["site"] != original and plan["commandKind"] == "rotate"
    assert all(a["routeIssued"] == tick+3 and not a["path"] for a in squad(rotated))
    for a in informed["agents"]:
        if a["team"] == "CT":
            a.update(hp=0, x=0, y=0, utility=[], knowledge={})
    assert review(informed)["plans"]["T"] == plan

    # A delayed observation from before the last switch cannot send the team back.
    duplicate = obstruction(deepcopy(rotated), tick, tick+100)
    assert "rotate" not in review(duplicate)["plans"]["T"]["assessment"]["scores"]
    second = obstruction(rotated, tick+99, tick+100)
    late = dict(second, deadline=second["tick"]+48)
    assert "rotate" not in review(late)["plans"]["T"]["assessment"]["scores"]
    back = review(second)["plans"]["T"]
    assert back["site"] == original and back["lastDirection"] == tick+100
    assert all(order["site"] == original for order in back["orders"]["slots"])


@pytest.mark.parametrize("count", [2, 3, 4, 5])
def test_regroup_preserves_separate_positions_and_moves_survivors(w, count):
    team = sorted(squad(w), key=lambda a: (a["id"] != w["bomb"]["carrier"], not a["appointed"]))
    arena = cs2_maps.get(w["mapId"])
    for i, a in enumerate(team):
        if i >= count:
            a["hp"] = 0
        elif i:
            area = arena.plants["B" if i % 2 else "A"][0]
            put(a, arena.centers[area], area)
    after = review(w)
    plan = after["plans"]["T"]
    jobs = plan["commandJobs"]
    assert plan["commandKind"] == "regroup" and len(jobs) == count
    assert len({tuple(j["point"]) for j in jobs.values()}) == count
    if count >= 4:
        assert max(dist(i["point"], j["point"]) for i in jobs.values() for j in jobs.values()) > 50
    moving = [a for a in team[:count] if dist(point(a), jobs[a["id"]]["point"]) > 6]
    assert moving
    intent, moved = execute(after, moving[0]["id"])
    actual = next(a for a in squad(moved) if a["id"] == moving[0]["id"])
    assert intent[0] == "move" and point(actual) != point(moving[0])


def test_feint_pair_and_main_move_without_decoy_then_cancel(w):
    plan = w["plans"]["T"]
    other = "B" if plan["site"] == "A" else "A"
    team = squad(w)
    captain = next(a for a in team if a["appointed"])
    sector = dict(order=other, tick=w["tick"], state="held")
    captain["peerCalls"] = {a["id"]+"/sector": sector for a in team if a != captain}
    for a in team:
        a["utility"] = ["Дым", "Свет"]
    after = review(w)
    plan = after["plans"]["T"]
    jobs = plan["commandJobs"]
    assert plan["commandKind"] == "feint" and len(jobs) == 2 and w["bomb"]["carrier"] not in jobs
    assert {j["site"] for j in jobs.values()} == {other}
    assert len({j["lane"] for j in jobs.values()}) == 1
    assert plan["probe"]["released"] == w["tick"]
    moves = {}
    for a in team:
        intent, moved = execute(after, a["id"])
        updated = next(x for x in squad(moved) if x["id"] == a["id"])
        moves[a["id"]] = point(a) != point(updated)
        if a["id"] in jobs:
            assert intent[0] == "move" and updated["status"] == "Давит на ложный вход"
    assert all(moves[k] for k in jobs) and any(v for k, v in moves.items() if k not in jobs)
    # End the demonstration on the next review after losses. Old orders must expire.
    for a in [a for a in squad(after) if not a["appointed"] and a["id"] != after["bomb"]["carrier"]][:2]:
        a["hp"] = 0
    after["tick"] = plan["review"]
    changed = review(after)["plans"]["T"]
    assert changed["commandKind"] != "feint" and changed["feintEnd"] == after["tick"]
    assert changed["revision"] > plan["revision"]


def test_profiles_change_relative_scores_and_review_time(w):
    for a in squad(w):
        a["utility"] = ["Дым", "Свет"]
    w["tick"] += 22  # Both scouting and a two-player demonstration are feasible.
    plans = []
    for skill in (10, 95):
        trial = deepcopy(w)
        for a in squad(trial):
            profile = trial["domain"]["players"][a["playerId"]]
            profile["skills"].update(calling=skill, leadership=skill, synchronization=skill)
            profile["roleMastery"][a["playingRole"]] = skill
            profile["mapKnowledge"]["dust2"] = skill
        plans.append(review(trial)["plans"]["T"])
    weak, strong = plans
    assert strong["review"] < weak["review"]
    lo, hi = (p["assessment"]["scores"] for p in plans)
    assert hi["feint"] - hi["scout"] > lo["feint"] - lo["scout"]
    assert strong["commandKind"] != weak["commandKind"]


def test_save_equipment_and_resume_active_orders(w):
    team = squad(w)
    for a in team:
        a["weapon"] = "AK-47"
    w["deadline"] = w["tick"]+25
    after = review(w)
    assert after["plans"]["T"]["commandKind"] == "save"
    original = native_match_state.open_game(after)
    resumed = native_match_state.open_game(after)
    original.advance(60)
    resumed.advance(19)
    resumed.advance(41)
    assert original.snapshot() == resumed.snapshot()


def test_same_radar_picture_does_not_reopen_completed_rally(w):
    team = squad(w)
    space = cs2_maps.get(w["mapId"])
    for i, a in enumerate(team):
        if i % 2:
            area = space.plants["B"][0]
            put(a, space.centers[area], area)
    captain = next(a for a in team if a["appointed"])
    captain["routeReports"]["T2"] = [w["plans"]["T"]["site"], w["tick"]]
    # Resistance is reported on both lanes. Waiting cannot supply a better route.
    captain["routeReports"]["T4"] = ["B", w["tick"]]
    result = review(w)
    assert result["plans"]["T"]["commandKind"] == "regroup"
    result["tick"] += 70
    result = review(result)
    assert result["plans"]["T"]["commandKind"] != "regroup"
    result["tick"] += 90
    assert "regroup" not in review(result)["plans"]["T"]["assessment"]["scores"]

@pytest.mark.skipif("de_anubis" not in cs2_maps.installed(), reason="Нужна карта Anubis")
def test_feint_smoke_is_a_physical_cast_while_main_group_executes():
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = 55301
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, pair)
    state = match.initial(seed, domain, pair, map_id="de_anubis", agent_policy=9,
                          first_attack=domain["rosters"][pair[0]]["team"])
    owner = native_match_state.open_game(state)
    owner.advance(156)
    state = json.loads(owner.snapshot())
    plan = state["plans"]["T"]
    event = next(e for e in state["events"] if e["tick"] == 156 and e["kind"] == "throw")
    effect = next(e for e in state["effects"] if e["player"] == event["player"] and e["start"] == 156)
    assert plan["commandKind"] == "feint" and plan["commandJobs"][event["player"]]["site"] == "B"
    assert event["utility"] == effect["kind"] == "Дым" and event["purpose"] == "Ложный выход"
    assert len(event["trajectory"]) > 1 and effect["land"] > state["tick"]
    main = [a for a in squad(state) if a["id"] not in plan["commandJobs"]]
    assert len(main) == 3 and all(a["status"] == "Выход на A" for a in main)


def test_route_revision_rejects_stale_stage_but_keeps_contact_assistance():
    world, _, lead, _ = scenario("T", policy=9)
    help_call = notice(world, "help", lead)
    helper = help_call["feedback"]["members"][0]
    actor = next(a for a in squad(world) if a["id"] == helper)
    stage = deepcopy(help_call)
    stage["feedback"].update(channel="stage", state="stage", origin=point(actor), members=[helper])

    def respond(packet, revised):
        trial = deepcopy(world)
        if revised:
            trial["plans"]["T"]["routeChanges"] = {lead: packet["feedback"]["tick"]+1}
        trial["messages"] = [packet]
        _, acted = execute(delivered(trial, packet["due"]), helper)
        return next(a for a in squad(acted) if a["id"] == helper).get("groupDuty")

    assert respond(stage, False)["ticket"][1] == "stage"
    assert respond(stage, True) is None
    assert respond(help_call, True)["ticket"][1] == "contact"
