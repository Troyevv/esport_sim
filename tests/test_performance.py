from copy import deepcopy

import pytest

from backend.performance import annotate, summarize


def played(rounds, winner="a"):
    return dict(winnerTeamId=winner, rounds=[{} for _ in range(rounds)], stats=[
        dict(player=f"{t}{i}", teamId=t, k=14, damage=1500, kast=14, opening=2, openingDeaths=2)
        for t in ("a", "b") for i in range(5)
    ])


def test_map_impact_and_reproducible_tie():
    game = played(20)
    game["stats"].reverse()
    result = summarize([game], "a")
    assert result["mvp"] == "a0"
    assert result["players"][0]["impact"] == pytest.approx(1)
    for row in game["stats"]:
        row.update(opening=0, openingDeaths=0)
    assert summarize([game], "b")["players"][0]["impact"] == pytest.approx(.9)
    del game["stats"][0]["openingDeaths"]
    assert summarize([game], "b")["mvp"] is None


def test_series_counts_actual_participation_and_preserves_unknowns():
    short, long = played(16, "b"), played(24)
    short["stats"][0].update(player="sub", k=50)
    long["stats"][0]["k"] = 48
    raw = dict(maps=[short, long], winnerTeamId="a", preparation={"a": {"veto": {}}, "b": {"veto": {"quality": 91}}})
    view = annotate(deepcopy(raw), "a")
    assert set(view["preparation"]) == {"a"}
    assert view["performance"]["mvp"] == "a0"
    assert [m["performance"]["mvp"] for m in view["maps"]] == ["b0", "a0"]
    players = {p["player"]: p for p in view["performance"]["players"]}
    assert players["sub"]["rounds"] == 16
    assert players["a0"]["rounds"] == 24
    assert players["a1"]["rounds"] == 40
    assert players["a1"]["adr"] == 3000 / 40
    short["stats"][1]["teamId"] = None
    assert summarize([short, long], "a")["mvp"] is None


def test_profile_filters_use_historical_team_and_played_maps():
    from backend.performance import profile_rows

    old, recent = played(20), played(24)
    old.update(mapId="de_nuke", teams=["a", "b"])
    recent.update(mapId="de_mirage", teams=["b", "c"], winnerTeamId="c")
    for p in recent["stats"]:
        if p["teamId"] == "a":
            p["teamId"] = "c"
    history = [dict(id=i, date=d, edition=e, teams=m["teams"], result=i)
               for i, d, e, m in [("old", "2026-10-01", "cup", old), ("new", "2026-11-01", "final", recent)]]
    career = dict(date="2026-11-10")
    def rows(group, subject, since="", edition="", map_id=""):
        return profile_rows(career, {}, group, subject, history, {"old": old, "new": recent}.__getitem__,
                            since, edition, map_id)["rows"]
    assert [r["team"] for r in rows("players", "a0")] == ["c", "a"]
    assert [r["fixture"] for r in rows("players", "a0", "2026-11-01", "final", "de_mirage")] == ["new"]
    assert rows("teams", "a")[0]["counts"]["k"] == 70
    assert not rows("players", "missing")


def test_mixed_archive_metrics_require_all_played_maps():
    first, second = played(20), played(20)
    del first["stats"][0]["openingDeaths"]
    report = dict(maps=[first, second], stats=[dict(second["stats"][0])], winnerTeamId="a")
    view = annotate(report, "a")
    assert view["stats"][0]["openingDeaths"] is None
    assert view["performance"]["mvp"] is None


def test_native_map_records_paired_opening_contacts():
    from backend import match, series
    game = match.initial(37)
    match.play_map(game)
    stats = series.map_stats(game)
    assert sum(p["opening"] for p in stats) == sum(p["openingDeaths"] for p in stats) > 0
    assert all(p["openingDeaths"] <= p["d"] for p in stats)
    projected = match.project(game)["match"]["award"]
    assert projected["player"] == summarize([series.map_result(game)], game["winnerTeamId"])["mvp"]
