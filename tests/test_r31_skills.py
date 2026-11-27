"""One-input interventions at the production decision / execution boundaries."""

from copy import deepcopy
from math import pi

import pytest

from tests.reference_kernel import match, match_ai as ai, match_performance as perf
from backend import skills
from backend.match_rules import POSITIONS
from backend.tactics import standards


def observed(key, value):
    w = match.initial(42)
    match.begin_live(w)
    a, b = w["agents"][0], w["agents"][5]
    p = match.profile(w, a)
    s = p["skills"]
    s.update(dict.fromkeys(skills.KEYS, 65))
    s[key] = value
    w["tick"] = 100
    a.update(x=25, y=105, heading=0, lastShot=-100, weapon="AK-47", ammo=20, armor=0)
    b.update(x=75, y=105, armor=0)
    sight = dict(x=b["x"], y=b["y"], id=b["id"], tick=100, source="Зрение")
    plan = w["plans"]["T"]
    plan.update(
        style="Быстро", start=0, review=0, site="A", orders=match.role_orders("T", "A")
    )
    obs = dict(
        tick=100,
        phase="live",
        plan=plan,
        player=p,
        action=None,
        chemistry=w["domain"]["chemistry"],
        deadline=1150,
    )
    allies = w["agents"][:5]
    for mate in allies:
        mate["utility"] = []
    if key in {
        "aim",
        "tracking",
        "recoil",
        "first_shot",
        "counter_strafe",
        "consistency",
        "concentration",
        "stress_resistance",
        "composure",
        *perf.WEAPON_CLASS.values(),
    }:
        if key in perf.WEAPON_CLASS.values():
            a["weapon"] = next(
                name for name, category in perf.WEAPON_CLASS.items() if category == key
            )
        if key == "recoil":
            a.update(lastShot=99, burst=2)
        if key == "counter_strafe":
            a["lastMove"] = 99
        if key == "tracking":
            a["observedSpeed"] = 2
        if key == "consistency":
            a["dayRoll"] = -8
        if key == "stress_resistance":
            a["pressure"] = 1
        if key == "concentration":
            a["liveStart"] = -650
        if key == "composure":
            a["lastHurt"] = 99
        ai.shoot(w, a, sight, b)
        return w["traces"][-1]["accuracy"]
    if key == "burst_control":
        a.update(lastShot=99, burst=2)
        ai.shoot(w, a, sight, b)
        return a["ready"] - w["tick"]
    if key in {
        "reaction",
        "flick",
        "target_switch",
        "peeking",
        "entry",
        "trades",
        "clutch",
    }:
        a.update(
            heading=pi / 2, visible=[b["id"]], knowledge={b["id"]: sight}, lastMove=-20
        )
        if key == "target_switch":
            a["previousTarget"] = "CT2"
        if key == "peeking":
            a["lastMove"] = 99
        if key == "entry":
            a["playingRole"] = "entry"
        if key == "trades":
            a.update(tradeTarget=b["id"], tradeUntil=101)
        ai.act(obs, a, [a] if key == "clutch" else allies, None, [])
        return a["ready"] - 100
    if key in perf.GRENADE_SKILL.values():
        item = next(g for g, k in perf.GRENADE_SKILL.items() if k == key)
        a["utility"] = [item]
        a["rng"] = 300
        ai.throw(w, a, sight)
        return ai.distance(w["effects"][0], sight)
    if key == "communication":
        ai.observe(w, [a, b])
        return next(
            m["due"] - w["tick"] for m in w["messages"] if m["sender"] == a["id"]
        )
    if key in ("calling", "leadership", "game_reading", "adaptability"):
        plan["site"] = "A"
        xy = POSITIONS["A"][0]
        a["knowledge"] = {
            str(i): dict(
                id=str(i),
                x=xy[0],
                y=xy[1],
                tick=50 if key == "game_reading" else 100,
                source="Радио",
            )
            for i in range(3)
        }
        if key == "leadership":
            plan["captain"] = "T2"
        if key == "adaptability":
            plan["start"] = 85
        ai.captain(w, allies)
        if key == "leadership":
            # First eligible review after succession, not the next scheduled review.
            return (
                0
                if plan["review"] == 100 + 18 + (100 - s["calling"]) // 2
                else plan["review"] - 100
            )
        return plan["review"] - 100 if key == "calling" else plan["rotated"]
    if key == "decisions":
        a.update(visible=[b["id"]], knowledge={b["id"]: sight}, utility=["HE"])
        allies[1].update(x=b["x"] - 12, y=b["y"])
        return ai.act(obs, a, allies, None, [])[0]
    if key == "coordination":
        near = dict(sight, id="CT2", x=sight["x"] - 10)
        a.update(visible=[b["id"], "CT2"], knowledge={b["id"]: sight, "CT2": near})
        allies[1].update(x=26, y=105, target=b["id"])
        ai.act(obs, a, allies, None, [])
        return a["target"]
    if key == "confidence":
        a.update(visible=[b["id"]], knowledge={b["id"]: sight})
        obs["action"] = dict(player=a["id"], end=109)
        return ai.act(obs, a, allies, None, [])[0]
    if key == "support":
        plan.update(board=standards()[0])
        a.update(playingRole="support", stepIndex=0, stepUntil=None)
        plan["captain"] = allies[1]["id"]
        allies[1].update(x=75, y=105)
        ai.act(obs, a, allies[:4], None, [])
        return a["status"]
    if key == "execution":
        plan["board"] = {
            "slots": [[dict(kind="move", x=a["x"], y=a["y"])], [], [], [], []]
        }
        a.update(stepIndex=0, stepUntil=None)
        ai.act(obs, a, allies, None, [])
        return a["stepReady"] - 100
    if key in ("retakes", "risk"):
        a.update(team="CT", heardSite="A", x=195, y=35, kit=False)
        # The traversable route is 80 units around a wall. Budget the walk and defuse.
        obs.update(phase="planted", deadline=247)
        ai.act(obs, a, allies, dict(site="A", x=235, y=35), [])
        return a["status"]
    if key in ("timing", "synchronization"):
        plan.update(style="Сбор", start=20, site="A")
        a["approached"] = "A"
        allies[-1].update(x=215, y=35)
        if key == "timing":
            s["synchronization"] = 0
        else:
            s["timing"] = 100
        ai.act(obs, a, allies, None, [])
        return a["status"]
    if key in ("discipline", "aggression", "patience"):
        s["discipline"] = value if key == "discipline" else 0
        a.update(
            team="CT",
            knowledge={
                "Шум": dict(
                    sight,
                    x=135,
                    y=35,
                    tick=78 if key == "patience" else 66,
                    source="Слух" if key == "patience" else "Радио",
                )
            },
        )
        ai.act(obs, a, allies, None, [])
        return a["status"]
    if key == "lurking":
        a["playingRole"] = "lurker"
        plan["site"] = "A"
        p["mapKnowledge"]["depo"] = 70
        ai.act(obs, a, allies, None, [])
        return a["dest"]
    if key in ("positioning", "map_control", "postplant"):
        a.update(team="CT", x=235, y=35)
        if key == "postplant":
            a.update(team="T", slot=1, x=225, y=45)
            obs["phase"] = "planted"
        ai.act(obs, a, allies, dict(site="A", carrier=None), [])
        return a["heading"]
    if key in ("movement", "fatigue_resistance"):
        p["fatigue"] = 60
        ai.act(obs, a, allies, None, [])
        return ai.distance(a, dict(x=25, y=105))
    if key in ("endurance", "recovery"):
        p["fatigue"] = 35
        a["movingTicks"] = 250
        match.finish_round(w, "CT", "Время")
        return p["fatigue"]
    raise AssertionError(key)


@pytest.mark.parametrize(
    "key", [k for k in skills.KEYS if k not in skills.DEPENDENCIES]
)
def test_one_attribute_changes_its_action(key):
    low, high = observed(key, 0), observed(key, 100)
    print(key, low, "→", high)
    decreasing = {
        "reaction",
        "flick",
        "target_switch",
        "peeking",
        "entry",
        "clutch",
        "trades",
        "burst_control",
        "leadership",
        "calling",
        "communication",
        "execution",
        "recovery",
        "endurance",
        *perf.GRENADE_SKILL.values(),
    }
    increasing = {
        "aim",
        "tracking",
        "recoil",
        "counter_strafe",
        "first_shot",
        "consistency",
        "concentration",
        "composure",
        "stress_resistance",
        "movement",
        "fatigue_resistance",
        *perf.WEAPON_CLASS.values(),
    }
    if key in decreasing:
        assert high < low
    elif key in increasing:
        assert high > low
    else:
        assert low != high


def test_catalog_future_inputs_and_role_ratings_do_not_choose_winner(monkeypatch):
    from backend import world

    assert len(skills.KEYS) == len(set(skills.KEYS)) == 58
    a = match.initial(42)
    b = deepcopy(a)
    p = match.profile(b, b["agents"][0])
    p["potential"] = 0
    for key in skills.DEPENDENCIES:
        p["skills"][key] = 0

    def forbidden(*args):
        pytest.fail("Боевой расчёт запросил OVR")

    monkeypatch.setattr(world, "team_rating", forbidden)
    monkeypatch.setattr(skills, "role_rating", forbidden)
    for w in (a, b):
        while w["phase"] != "finished":
            match.advance(w)
    assert (a["archive"], a["events"], a["stats"]) == (
        b["archive"],
        b["events"],
        b["stats"],
    )


def test_decoy_creates_only_anonymous_sound():
    w = match.initial(4)
    a, b = w["agents"][0], w["agents"][5]
    a.update(x=25, y=105, utility=["Ложная"])
    b.update(x=55, y=105)
    ai.throw(w, a, b)
    w["tick"] = w["effects"][0]["land"]
    ai.apply_effects(w, {a["id"]: a, b["id"]: b})
    assert b["hp"] == 100 and b["blind"] == 0
    assert list(b["knowledge"]) == ["Шум"] and b["knowledge"]["Шум"]["source"] == "Слух"


def test_stationary_first_shots_hit_the_observed_target_at_expected_rate():
    totals = []
    for aim in (0, 100):
        w = match.initial(8)
        a, b = w["agents"][0], w["agents"][5]
        p = match.profile(w, a)
        p["skills"].update(dict.fromkeys(skills.KEYS, 65), aim=aim)
        a.update(x=25, y=105, weapon="AK-47")
        b.update(x=75, y=105, armor=0)
        hits = 0
        for seed in range(2048):
            a.update(lastShot=-100, ammo=30, rng=seed)
            b["hp"] = 100
            ai.shoot(w, a, b, b)
            hits += b["hp"] < 100
        totals.append(hits)
    print("2048 выстрелов при AIM 0/100:", totals)
    assert 0.15 < (totals[1] - totals[0]) / 2048 < 0.23


def test_grenade_cost_depends_on_weapon_readiness_and_distance():
    w = match.initial(8)
    match.begin_live(w)
    a, b = w["agents"][0], w["agents"][5]
    p = match.profile(w, a)
    p["skills"]["decisions"] = 90
    sight = dict(id=b["id"], x=50, y=105, source="Зрение", tick=100)
    a.update(
        x=25,
        y=105,
        weapon="AWP",
        ammo=5,
        utility=["Дым"],
        ready=100,
        target=b["id"],
        visible=[b["id"]],
        knowledge={b["id"]: sight},
    )
    obs = dict(tick=100, phase="live", plan=w["plans"]["T"], player=p, action=None)
    assert ai.act(obs, a, [a], None, [])[0] == "shoot"
    a["reloadAt"] = 120
    assert ai.act(obs, a, [a], None, [])[0] == "throw"
    a["reloadAt"] = 0
    sight["x"] = 105
    assert ai.act(obs, a, [a], None, [])[0] == "throw"


def test_unrelated_specialties_and_untriggered_modifiers_leave_first_shot_unchanged():
    w = match.initial(9)
    a = w["agents"][0]
    a.update(weapon="Glock", observedSpeed=0, pressure=0, dayRoll=0, liveStart=100)
    p = match.profile(w, a)
    spec = match.WEAPONS[a["weapon"]]
    expected = perf.accuracy(p, a, spec, 50, 0, 100)
    unrelated = (
        "rifles",
        "smgs",
        "shotguns",
        "sniper_rifles",
        "machine_guns",
        "leadership",
        "calling",
        "recoil",
        "tracking",
        "consistency",
        "concentration",
        "stress_resistance",
        "composure",
        "counter_strafe",
        "entry",
        "trades",
    )
    for value in (0, 100):
        p["skills"].update(dict.fromkeys(unrelated, value))
        assert perf.accuracy(p, a, spec, 50, 0, 100) == expected
