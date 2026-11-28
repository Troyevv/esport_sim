"""R5.5.5 uses the production captain, movement, observation and objective executors."""
from copy import deepcopy
import json
from math import dist

import pytest

from backend import cs2_maps, match, native_match_state
from tests.test_group_tasks import put
from tests.test_peer_radio import delivered
from tests.test_small_groups import point


pytestmark = pytest.mark.skipif("de_dust2" not in cs2_maps.installed(), reason="Нужна физическая карта")


def players(w, side="CT"):
    return [a for a in w["agents"] if a["team"] == side and a["hp"]]


def actor(w, who):
    return next(a for a in w["agents"] if a["id"] == who)


def captain(w):
    return actor(w, w["plans"]["CT"]["captain"])


def review(w, side="CT"):
    w["plans"][side]["review"] = 0
    owner = native_match_state.open_game(w)
    owner.review_captain(side)
    return json.loads(owner.snapshot())


def act(w, who):
    owner = native_match_state.open_game(w)
    info = dict(action=w["action"], fire=[], device=w["bomb"] if actor(w, who)["team"] == "T" else actor(w, who).get("seenDevice"))
    cmd = json.loads(owner.priority_intent(who, json.dumps(info)))
    return cmd, actor(json.loads(owner.snapshot()), who)


@pytest.fixture
def live():
    w = match.initial(17, map_id="de_dust2", agent_policy=11)
    match.advance(w, 45)
    w["tick"] += 70
    return w


def report(w, site, i=1, **detail):
    return dict(id=f"T{i}", tick=w["tick"], source="Радио",
                **dict(zip("xyz", cs2_maps.get(w["mapId"]).site_points[site]))) | detail


def inform(w, *reports):
    captain(w)["knowledge"] = {r["id"]: r for r in reports}


@pytest.mark.parametrize("evidence", ["Слух", "Граната", "устарело", "спорно"])
def test_unconfirmed_attack_preserves_opposite_assignments_and_motion(live, evidence):
    w = live
    sound = report(w, "B")
    if evidence == "устарело":
        sound.update(tick=w["tick"]-76, carryingC4=True)
    elif evidence == "спорно":
        sound.update(disputed=True, carryingC4=True)
    else:
        sound.update(source=evidence, sound="Шаги", confidence=.58)
    inform(w, sound)
    original = review(w)
    hidden = deepcopy(w)
    for t in players(hidden, "T"):
        t.update(x=150, y=100, hp=3, utility=["Дым"], weapon="AWP", target=None)
    hidden["plans"]["T"].update(commandKind="feint", site="A", commandJobs={})
    hidden["bomb"].update(carrier="T1", x=9, y=8)
    other = review(hidden)
    p = original["plans"]["CT"]
    assert p == other["plans"]["CT"] and p["defenseCall"]["kind"] in ("hold", "space")
    assert not p.get("backup") and not p.get("commitments")
    anchor = next(a for a in players(w) if p["orders"]["slots"][a["slot"]]["site"] == "A")
    assert act(original, anchor["id"]) == act(other, anchor["id"])


def test_delivered_carrier_can_reverse_twice_old_report_cannot(live):
    w = live
    for a in players(w):
        a["utility"] = []
    first = report(w, "A", carryingC4=True)
    inform(w, first)
    w = review(w)
    assert w["plans"]["CT"]["defenseCall"]["kind"] == "full"
    for site in ("B", "A"):
        prior = w["plans"]["CT"]["defenseCall"].copy()
        w["tick"] += 12
        msg = report(w, site, source="Зрение", carryingC4=True)
        w["messages"].append(dict(sender="CT2", team="CT", sight=msg, due=w["tick"]+3))
        early = review(delivered(w, w["tick"]+2))
        assert early["plans"]["CT"]["defenseCall"]["site"] == prior["site"]
        w = review(delivered(w, w["tick"]+3))
        p = w["plans"]["CT"]
        assert (p["defenseCall"]["kind"], p["defenseCall"]["site"]) == ("full", site)
        lead = p["backup"]["id"]
        cmd, moved = act(w, lead)
        assert cmd[0] == "move" and point(moved) != point(actor(w, lead))
        # Delayed pre-switch evidence must not reverse the same players again.
        stale = deepcopy(w)
        inform(stale, report(stale, prior["site"], tick=prior["issued"], carryingC4=True))
        assert review(stale)["plans"]["CT"]["defenseCall"]["site"] != prior["site"]


def test_partial_rotation_keeps_an_anchor_and_covers_distinct_sectors(live):
    w = live
    inform(w, report(w, "A"), report(w, "A", 2))
    state = review(w)
    p = state["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "partial"
    reserves = [p["backup"], p["secondBackup"]]
    assert len({r["id"] for r in reserves}) == 2
    assert dist(*[r["hold"] for r in reserves]) >= 6
    assert any(p["orders"]["slots"][a["slot"]]["site"] == "B" and
               all(r["id"] != a["id"] for r in reserves) for a in players(w))
    for r in reserves:
        cmd, moved = act(state, r["id"])
        assert cmd[0] == "move" and point(moved) != point(actor(w, r["id"]))


def test_space_selection_and_execution_depend_on_captain_profile(live):
    plans = []
    for level in (5, 95):
        w = deepcopy(live)
        profile = w["domain"]["players"][captain(w)["playerId"]]
        profile["skills"].update(aggression=level, risk=level, calling=level, communication=level)
        w = review(w)
        plans.append(w["plans"]["CT"])
        if level == 95:
            front, wing = plans[-1]["defenseCall"]["pair"]
            for who in (front, wing):
                cmd, moved = act(w, who)
                assert cmd[0] == "move" and point(moved) != point(actor(w, who))
    assert [p["defenseCall"]["kind"] for p in plans] == ["hold", "space"]
    assert plans[0]["review"] > plans[1]["review"]


def test_outnumbered_wounded_anchors_yield_to_reachable_distinct_points(live):
    w = live
    arena = cs2_maps.get(w["mapId"])
    for a in players(w):
        if w["plans"]["CT"]["orders"]["slots"][a["slot"]]["site"] == "A":
            a["hp"] = 22
            pos = arena.site_points["A"]
            put(a, pos, arena.locate(pos))
    inform(w, report(w, "A", carryingC4=True), report(w, "A", 2), report(w, "A", 3))
    after = review(w)
    p = after["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "yield"
    assert len(p["commitments"]) == 2
    goals = [j["hold"] for j in p["commitments"].values()]
    assert dist(*goals) >= 7 and all(dist(g, arena.site_points["A"]) >= 30 for g in goals)
    for who in p["commitments"]:
        # Keep the contact on the captain's radio. A free actor executes the retreat.
        actor(after, who)["knowledge"] = {}
        cmd, moved = act(after, who)
        assert cmd[0] == "move" and moved["status"] == "Отходит на рубеж ретейка"


def planted(w, left):
    w.update(phase="planted", deadline=w["tick"]+left)
    arena = cs2_maps.get(w["mapId"])
    pos = arena.site_points["A"]
    w["bomb"].update(carrier=None, site="A", **dict(zip("xyz", pos)))
    for a in players(w):
        a.update(heardSite="A", seenDevice=deepcopy(w["bomb"]), kit=False, utility=[])
    return arena, pos


def test_kit_holder_uses_device_with_cover_and_no_wait_at_deadline(live):
    w = live
    arena, pos = planted(w, 70)
    kit, support = players(w)[:2]
    for a in (kit, support):
        put(a, pos, arena.locate(pos))
    kit["kit"] = True
    state = review(w)
    p = state["plans"]["CT"]
    assert p["retakeCall"]["kind"] == "retake" and p["retakeCall"]["defuser"] == kit["id"]
    assert p["retakeCall"]["eta"][kit["id"]] == 0
    assert act(state, kit["id"])[0][0] == "defuse"
    cmd, defender = act(state, support["id"])
    assert cmd[0] in ("move", "hold") and defender["status"] == "Прикрывает разминирование"
    # If the kit is lost, starting in time beats saving a nominal formation.
    actor(state, kit["id"])["hp"] = 0
    state["deadline"] += 45
    state["tick"] += 1
    successor = review(state)
    successor["tick"] += 30
    successor["deadline"] += 30
    state = review(successor)
    assert state["plans"]["CT"]["captain"] != kit["id"]
    assert state["plans"]["CT"]["retakeCall"]["defuser"] == support["id"]
    assert act(state, support["id"])[0][0] == "defuse"


def test_collective_save_moves_and_hidden_c4_does_not_change_estimated_arrivals(live):
    w = live
    arena, pos = planted(w, 40)
    survivor = captain(w)
    for a in players(w):
        a["seenDevice"] = None
        if a != survivor:
            a["hp"] = 0
    put(survivor, pos, arena.locate(pos))
    survivor.update(weapon="AWP", kit=True)
    state = review(w)
    call = state["plans"]["CT"]["retakeCall"]
    assert call["kind"] == "save" and call["slack"] < 0
    cmd, moved = act(state, survivor["id"])
    assert cmd[0] == "move" and point(moved) != point(survivor) and moved["saving"]
    w["bomb"].update(site="B", x=100, y=10)
    for t in players(w, "T"):
        t.update(hp=0, utility=[], weapon="USP")
    assert review(w)["plans"]["CT"]["retakeCall"] == call


@pytest.mark.parametrize("map_id", cs2_maps.NAMES)
def test_t_captain_and_all_five_executors_match_r554_on_same_snapshot(map_id):
    if map_id not in cs2_maps.installed():
        pytest.skip("Нужна физическая карта")
    w = match.initial(53, map_id=map_id, agent_policy=9)
    match.advance(w, 130)
    old, new = (review(dict(deepcopy(w), agentPolicy=policy), "T") for policy in (9, 11))
    assert old["plans"]["T"] == new["plans"]["T"]
    for a in players(old, "T"):
        assert act(old, a["id"]) == act(new, a["id"])

def test_reclaim_with_fallen_anchor_keeps_other_site_and_cancels_dead_assignment(live):
    w = live
    arena = cs2_maps.get(w["mapId"])
    # Remove the A wing on a known approach and keep the opposite anchor alive.
    fallen = players(w)[2]
    job = w["plans"]["CT"]["opening"]["jobs"][fallen["id"]]
    pos = job["gate"]
    put(fallen, pos, arena.locate(tuple(pos)))
    fallen.update(hp=0, lastHurt=w["tick"]-1)
    state = review(w)
    p = state["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "reclaim"
    lead = p["backup"]["id"]
    assert lead != fallen["id"] and p["backup"]["hold"] == pos
    assert act(state, lead)[0][0] == "move"
    # The surviving captain receives a public kill and still has the recently
    # observed point. Moving the hidden corpse cannot alter the reclaim call.
    w["tick"] += 90
    inform(w, report(w, "A", tick=w["tick"]-5))
    w["kills"].append(dict(target="T1", tick=w["tick"]-1))
    actor(w, "T1")["hp"] = 0
    after = review(w)
    assert after["plans"]["CT"]["defenseCall"]["kind"] == "reclaim"
    actor(w, "T1").update(x=15, y=20, z=-10)
    assert review(w)["plans"]["CT"] == after["plans"]["CT"]


def test_live_save_requires_confirmed_c4_and_an_expensive_wounded_survivor(live):
    w = live
    for a in players(w):
        if a["id"] != captain(w)["id"]:
            a["hp"] = 0
    leader = captain(w)
    arena = cs2_maps.get(w["mapId"])
    pos = arena.site_points["A"]
    put(leader, pos, arena.locate(pos))
    leader.update(hp=21, weapon="AWP")
    inform(w, report(w, "A"), report(w, "A", 2))
    assert "save/A" not in review(w)["plans"]["CT"]["defenseScores"]
    inform(w, report(w, "A", carryingC4=True), report(w, "A", 2))
    after = review(w)
    p = after["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "save"
    goal = p["commitments"][leader["id"]]["hold"]
    assert dist(goal, pos) > 50
    actor(after, leader["id"])["knowledge"] = {}
    cmd, moved = act(after, leader["id"])
    assert cmd[0] == "move" and point(moved) != pos


def test_staging_releases_an_already_ready_player_when_the_kit_clock_runs_short(live):
    w = live
    arena, pos = planted(w, 200)
    defenders = players(w)
    kit = defenders[0]
    choices = sorted(arena.centers, key=lambda area: abs(dist(arena.centers[area], pos)-20))
    area = next(i for i in choices if arena.path(i, arena.centers[i], arena.locate(pos), pos, frozenset()))
    put(kit, arena.centers[area], area)
    kit["kit"] = True
    state = review(w)
    call = state["plans"]["CT"]["retakeCall"]
    assert call["defuser"] == kit["id"]
    state["deadline"] = state["tick"] + int(call["eta"][kit["id"]]) + 50 + 7
    state = review(state)
    call = state["plans"]["CT"]["retakeCall"]
    assert call["kind"] == "retake" and 0 < call["slack"] < 25
    # A previously issued assembly window still wants the absent partner.
    duty = dict(stage=point(kit), latest=state["tick"]+45, eta=state["tick"], entry=point(kit),
                partner=defenders[-1]["id"], release=state["tick"]+40)
    state["plans"]["CT"]["retake"] = dict(site="A", duties={kit["id"]: duty})
    cmd, moved = act(state, kit["id"])
    assert cmd[0] == "move" and point(moved) != point(kit)


def test_kit_duty_and_support_throwers_are_reassigned_after_casualty(live):
    w = live
    arena, pos = planted(w, 300)
    near = sorted(arena.centers, key=lambda i: dist(arena.centers[i], pos))
    for a, area in zip(players(w), near):
        put(a, arena.centers[area], area)
        a.update(utility=["Свет", "Дым"], kit=True)
    state = review(w)
    call = state["plans"]["CT"]["retakeCall"]
    assert call["kind"] == "retake" and call["throwers"] and call["defuser"] not in call["throwers"]
    previous = call["throwers"][0]
    actor(state, previous)["hp"] = 0
    state = review(state)
    call = state["plans"]["CT"]["retakeCall"]
    assert call["throwers"] and previous not in call["throwers"]


@pytest.mark.skipif("de_anubis" not in cs2_maps.installed(), reason="Нужна карта Anubis")
def test_same_clubs_open_the_real_r554_feint_without_giving_ct_the_t_jobs():
    from backend import career, database
    import gzip
    import random

    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pair = random.Random(55301).sample(sorted(career.roster_index(pack).values()), 2)
    d = database.match_input(pack, pair)
    w = match.initial(55301, d, pair, map_id="de_anubis", agent_policy=9,
                      first_attack=d["rosters"][pair[0]]["team"])
    match.advance(w, 156)
    assert any(e["kind"] == "throw" and e.get("purpose") == "Ложный выход" for e in w["events"])
    w["agentPolicy"] = 11
    before = review(w)
    plan = w["plans"]["T"]
    plan.update(commandKind="rotate", commandJobs={}, site="B" if plan["site"] == "A" else "A")
    after = review(w)
    assert after["plans"]["CT"] == before["plans"]["CT"]
    for a in players(w):
        assert act(before, a["id"]) == act(after, a["id"])

def test_role_mastery_and_team_synchronization_change_size_of_rotation(live):
    calls = []
    for level in (5, 95):
        w = deepcopy(live)
        for a in players(w):
            p = w["domain"]["players"][a["playerId"]]
            p["skills"].update(synchronization=level, leadership=level)
            p["roleMastery"][a["playingRole"]] = level
        leader = w["domain"]["players"][captain(w)["playerId"]]
        leader["skills"].update(game_reading=92, adaptability=92)
        leader["mapKnowledge"]["dust2"] = 92
        for key in w["domain"]["chemistry"]:
            w["domain"]["chemistry"][key] = level
        inform(w, report(w, "A"), report(w, "A", 2))
        state = review(w)
        calls.append(state["plans"]["CT"])
    assert [p["defenseCall"]["kind"] for p in calls] == ["reinforce", "partial"]
    assert "secondBackup" not in calls[0] and calls[1]["secondBackup"]["id"] != calls[1]["backup"]["id"]


def test_known_friendly_smoke_cancels_a_duplicate_before_spending_the_item(live):
    w = live
    a = players(w)[2]
    pos = point(a)
    a["utility"] = ["Дым"]
    visible_fire = dict(zip("xyz", pos), radius=12)
    observation = dict(device=None, action=None, fire=[visible_fire])

    def choose(state):
        owner = native_match_state.open_game(state)
        return json.loads(owner.priority_intent(a["id"], json.dumps(observation)))

    assert choose(w)[0] == "throw"
    # Use the production queue: a signal in transit cannot suppress the cast.
    cast = dict(item="Дым", point=pos, end=w["tick"]+80)
    cue = dict(zip("xyz", pos), end=w["tick"]+15, cast=cast)
    w["messages"].append(dict(team="CT", sender=captain(w)["id"], due=w["tick"]+3, friendlyUtility=cue))
    assert choose(delivered(w, w["tick"]+2))[0] == "throw"
    assert choose(delivered(w, w["tick"]+3))[0] == "hold"
    assert choose(delivered(w, w["tick"]+81))[0] == "throw"


def test_last_grenade_survives_opening_assignment(live):
    w = live
    p = w["plans"]["CT"]
    who = p["utilityReserve"]
    job = p["opening"]["jobs"][who]
    assert "throw" in job
    actor(w, who)["utility"] = [job["throw"]["item"]]
    owner = native_match_state.open_game(w)
    owner.priority_intent(who, json.dumps(dict(device=None, action=None, fire=[])))
    state = json.loads(owner.snapshot())
    assert state["plans"]["CT"]["opening"]["jobs"][who]["throw"]["skip"] == "Последняя граната в резерве"
    assert actor(state, who)["utility"] == [job["throw"]["item"]]

def test_rally_brings_the_wandering_wing_back_to_the_retained_sector(live):
    w = live
    arena = cs2_maps.get(w["mapId"])
    anchor, opposite, wing, *others = players(w)
    for a in others:
        a["hp"] = 0
    a_job = w["plans"]["CT"]["orders"]["slots"][anchor["slot"]]
    pos = tuple(a_job["hold"])
    put(anchor, pos, arena.locate(pos))
    far = arena.site_points["B"]
    put(wing, far, arena.locate(far))
    state = review(w)
    p = state["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "regroup"
    jobs = p["commitments"]
    assert set(jobs) == {anchor["id"], wing["id"]}
    assert jobs[anchor["id"]]["hold"] == list(pos)
    assert 6 < dist(jobs[wing["id"]]["hold"], pos) <= 24
    assert act(state, anchor["id"])[0][0] == "hold"
    cmd, moved = act(state, wing["id"])
    assert cmd[0] == "move" and point(moved) != point(wing)
    for who, job in jobs.items():
        put(actor(state, who), job["hold"], arena.locate(tuple(job["hold"])))
    state["tick"] += 70
    finished = review(state)
    put(actor(finished, wing["id"]), far, arena.locate(far))
    finished["tick"] += 75
    assert "regroup/A" not in review(finished)["plans"]["CT"]["defenseScores"]


def test_checkpoint_in_coordinated_retake_replays_exact_state(live):
    w = live
    planted(w, 255)
    for a in players(w):
        a.update(utility=["Свет", "Дым"], kit=True)
    w = review(w)
    assert w["plans"]["CT"]["retakeCall"]["kind"] == "retake"
    assert w["plans"]["CT"]["retake"]["duties"]
    original = native_match_state.open_game(w)
    original.advance(17)
    restored = native_match_state.open_game(json.loads(original.snapshot()))
    restored.advance(21)
    restored.advance(39)
    original.advance(60)
    assert original.snapshot() == restored.snapshot()

def test_split_pressure_then_fast_group_with_a_lurker_on_the_other_site(live):
    w = live
    inform(w, report(w, "A"), report(w, "B", 2))
    split = review(w)
    p = split["plans"]["CT"]
    assert p["defenseCall"]["kind"] == "hold" and not p.get("backup")
    split["tick"] += 25
    inform(split, report(split, "A"), *(report(split, "B", i) for i in (2, 3, 4)))
    rushed = review(split)
    assert rushed["plans"]["CT"]["defenseCall"]["kind"] == "hold"
    # The isolated contact at A argues against stripping that site. The B
    # witnesses see the group again as the initial formation commitment ages.
    rushed["tick"] += 32
    inform(rushed, report(rushed, "A"), *(report(rushed, "B", i) for i in (2, 3, 4)))
    rushed = review(rushed)
    p = rushed["plans"]["CT"]
    assert (p["defenseCall"]["kind"], p["defenseCall"]["site"]) == ("partial", "B")
    mobile = {p[k]["id"] for k in ("backup", "secondBackup")}
    anchor = next(a for a in players(rushed) if p["orders"]["slots"][a["slot"]]["site"] == "A" and a["id"] not in mobile)
    for who in mobile:
        assert act(rushed, who)[0][0] == "move"
    # The isolated A contact cannot draw the rest of the team back after
    # evidence of the B group becomes stale.
    rushed["tick"] += 80
    later = review(rushed)
    assert later["plans"]["CT"]["defenseCall"]["kind"] in ("hold", "space")
    assert anchor["id"] not in rushed["events"][-1]["goals"]


def test_later_clear_only_invalidates_the_observed_crossing(live):
    w = live
    msg = report(w, "B", carryingC4=True, tick=w["tick"]-5)
    inform(w, msg)
    leader = captain(w)
    pos = [msg[k] for k in "xyz"]
    clear = dict(state="watching", site="B", point=pos, lane=0, tick=w["tick"]-2)
    leader["sectorCalls"]["CT2"] = clear
    assert review(w)["plans"]["CT"]["defenseCall"]["kind"] != "full"
    msg["tick"] = w["tick"]
    assert review(w)["plans"]["CT"]["defenseCall"]["kind"] == "full"
    msg["tick"] -= 5
    clear["point"] = list(cs2_maps.get(w["mapId"]).site_points["A"])
    assert review(w)["plans"]["CT"]["defenseCall"]["kind"] == "full"


def test_home_assignment_without_a_defender_on_site_cannot_trigger_withdrawal(live):
    arena = cs2_maps.get(live["mapId"])
    pos = arena.site_points["B"]
    for a in players(live):
        put(a, pos, arena.locate(pos))
        a["hp"] = 22
    inform(live, report(live, "A", carryingC4=True), report(live, "A", 2), report(live, "A", 3))
    call = review(live)["plans"]["CT"]["defenseCall"]
    assert call["kind"] == "full" and call["site"] == "A"


@pytest.mark.parametrize("item", ["Дым", "Огонь"])
def test_observed_obstruction_and_weapon_recovery_change_retake_eta(live, item):
    w = live
    arena, pos = planted(w, 310)
    player = players(w)[0]
    candidates = sorted(arena.centers, key=lambda i: abs(dist(arena.centers[i], pos)-24))
    area = next(i for i in candidates if arena.path(i, arena.centers[i], arena.locate(pos), pos, frozenset()))
    put(player, arena.centers[area], area)
    who = player["id"]

    def arrival():
        return review(w)["plans"]["CT"]["retakeCall"]["eta"][who]

    base = arrival()
    cast = dict(item=item, point=point(player), end=w["tick"]+60)
    captain(w)["crossingCalls"] = [cast]
    obstructed = arrival()
    assert obstructed > base
    cast["end"] = w["tick"]
    assert arrival() == base
    player["ready"] = w["tick"]+int(base)+20
    assert arrival() >= base+20


def test_cover_and_clear_face_distinct_assigned_points_and_kit_loss_releases_cover(live):
    w = live
    arena, pos = planted(w, 240)
    kit, *mates = players(w)
    near = sorted(arena.centers, key=lambda i: dist(arena.centers[i], pos))
    for a, area in zip(mates, near):
        put(a, arena.centers[area], area)
    put(kit, pos, arena.locate(pos))
    kit["kit"] = True
    w["action"] = dict(kind="defuse", player=kit["id"], end=w["tick"]+45)
    state = review(w)
    call = state["plans"]["CT"]["retakeCall"]
    jobs = call["sectors"]
    assert {job["role"] for job in jobs.values()} == {"cover", "clear"}
    assert len({tuple(job["watch"]) for job in jobs.values()}) == len(jobs)
    for who, job in jobs.items():
        cmd, defender = act(state, who)
        assert cmd[0] in ("hold", "move")
        assert defender["coverSector"] == job and defender["coveredDefuser"] == kit["id"]
    state["action"] = None
    actor(state, kit["id"])["hp"] = 0
    # The nearest survivor can take over even during captain succession.
    successor = mates[0]["id"]
    put(actor(state, successor), pos, arena.locate(pos))
    assert act(state, successor)[0][0] == "defuse"


def test_stale_ack_for_another_destination_does_not_mark_current_reserve(live):
    w = live
    inform(w, report(w, "A"), report(w, "A", 2))
    w = review(w)
    job = w["plans"]["CT"]["backup"]
    who = job["id"]
    leader = captain(w)
    reply = dict(duty=True, state="moving", tick=w["tick"], point=point(actor(w, who)),
                 site=job["site"], lane=job["lane"], goal=list(cs2_maps.get(w["mapId"]).site_points["B"]))
    leader["sectorCalls"][who+"/order"] = reply
    assert "acknowledged" not in review(w)["plans"]["CT"]["backup"]
    reply["goal"] = job["hold"]
    assert review(w)["plans"]["CT"]["backup"]["acknowledged"] == "moving"


def test_repeated_block_at_same_position_cannot_reopen_completed_rally(live):
    arena = cs2_maps.get(live["mapId"])
    anchor, opposite, wing, *others = players(live)
    for a in others:
        a["hp"] = 0
    home = live["plans"]["CT"]["orders"]["slots"][anchor["slot"]]["hold"]
    put(anchor, home, arena.locate(tuple(home)))
    far = arena.site_points["B"]
    put(wing, far, arena.locate(far))
    p = live["plans"]["CT"]
    tick = live["tick"]
    sender = wing["id"]
    p["lastRally"] = {"A": dict(alive=4, tick=tick-50,
                                block=dict(sender=sender, point=far, tick=tick-51))}
    p.pop("lastFront", None)
    captain(live)["sectorCalls"][sender] = dict(site="A", state="blocked", tick=tick, point=far, lane=0)
    assert "regroup/A" not in review(live)["plans"]["CT"]["defenseScores"]


def test_safe_exit_is_reachable_outside_blast_and_can_be_contested(live):
    from backend.match_rules import BLAST_RADIUS
    w = live
    arena, pos = planted(w, 32)
    who = captain(w)["id"]
    for a in players(w):
        if a["id"] != who:
            a["hp"] = 0
    defender = actor(w, who)
    put(defender, pos, arena.locate(pos))
    defender["weapon"] = "AWP"
    state = review(w)
    _, moving = act(state, who)
    safe = tuple(moving["saving"])
    assert dist(pos, safe) > BLAST_RADIUS
    assert arena.path(defender["navArea"], pos, arena.locate(safe), safe, frozenset())
    # The actor never acquires a pursuer's true position from the escape search.
    for enemy in players(state, "T"):
        put(enemy, safe, arena.locate(safe))
    assert act(state, who)[1]["saving"] == list(safe)
