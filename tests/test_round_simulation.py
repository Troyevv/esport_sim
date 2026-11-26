from copy import deepcopy

import pytest

from backend import career, cs2_maps, engine, match, round_sim, series, veto, world


def fixture(best, seed):
    domain = world.exhibition(engine.initial(42)["agents"])
    w = series.initial(
        seed, best, domain, list(world.FIXTURE_ROSTERS), jobs=[], detailed=False
    )
    w["simulation"] = round_sim.MODE
    return w


@pytest.mark.parametrize("best", [1, 3, 5])
def test_round_series_is_reproducible_without_map_files_or_ticks(monkeypatch, best):
    def forbidden(*args):
        pytest.fail("Round simulation invoked geometry or the tick engine")

    for obj, key in (
        (cs2_maps, "get"),
        (cs2_maps, "installed"),
        (match, "advance"),
        (match, "initial"),
    ):
        monkeypatch.setattr(obj, key, forbidden)
    w = fixture(best, 31)
    report = career.simulate(deepcopy(w))
    assert report == career.simulate(deepcopy(w))
    assert max(report["score"]) == best // 2 + 1 and report["veto"]
    expected = {
        m["player"]: w["domain"]["rosters"][r]["team"]
        for r in w["rosterIds"]
        for m in world.lineup(w["domain"], r)
    }
    for i, m in enumerate(report["maps"]):
        assert {"ticks", "events", "positions", "kills", "archive"}.isdisjoint(m)
        assert (
            m["simulation"] == round_sim.MODE
            and m["firstAttackTeamId"] == report["order"][i]["attack"]
        )
        assert (
            series.verify_map(
                m,
                report["teams"],
                expected,
                series.map_seed(31, i),
                report["order"][i]["map"],
            )
            == m["scoreByTeam"]
        )
        assert m["rounds"][0]["buys"] == m["rounds"][12]["buys"] == ["pistol", "pistol"]
    assert report["stats"] == series.total_stats(m["stats"] for m in report["maps"])
    m = deepcopy(report["maps"][0])
    m["stats"][0]["openingDeaths"] += 1
    with pytest.raises(ValueError):
        round_sim.validate(m, m["teams"])


def test_strength_roles_condition_and_overtime():
    w = fixture(1, 1)
    rid = w["rosterIds"][0]
    domain = w["domain"]
    member = world.lineup(domain, rid)[0]
    p = domain["players"][member["player"]]

    def power():
        rows, teamwork = round_sim.lineup(domain, rid, "de_mirage", 0)
        return rows[0]["base"] + teamwork

    p["mapKnowledge"]["mirage"] = 20
    original = power()
    p["mapKnowledge"]["mirage"] = 90
    assert power() > original
    p.update(form=0, morale=0, fatigue=100)
    assert power() < original
    # MR12 / MR3 target, side switches and economic resets across two overtimes.
    assert [round_sim.round_rules(n) for n in (1, 13, 25, 28, 31, 34)] == [
        (0, True, 13),
        (1, True, 13),
        (1, True, 16),
        (2, True, 16),
        (2, True, 19),
        (3, True, 19),
    ]
