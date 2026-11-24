import gzip
from collections import Counter

import pytest

from backend import database as db, match, skills
from tools.november_scene import build


@pytest.fixture(scope="module")
def release():
    return db.read_json(gzip.decompress(db.RELEASE.read_bytes()))


def test_release_is_reproducible_and_individual(release):
    assert db.envelope(build()) == release
    p = release["package"]
    players = p["players"]
    assert 1500 <= len(players) <= 2500 and 200 <= len(p["teams"]) <= 300
    assert all(len(r["players"]) == 5 for r in p["rosters"].values())
    assert all(
        r["born"] or p["origins"][r["fields"]["ageEstimate"]]["status"] == "estimated"
        for r in players.values()
    )
    assert all(
        set(r["skills"]) == set(skills.KEYS)
        and len(r["roleMastery"]) == 6
        and set(r["mapKnowledge"]) == set(db.MAPS)
        and r["potential"] is not None
        for r in players.values()
    )
    assert len({tuple(r["skills"].values()) for r in players.values()}) == len(players)
    assert (
        Counter(v for r in players.values() for v in r["skills"].values())[65]
        < len(players) * 5
    )
    assert {"Europe", "Americas", "Asia"} <= {r["region"] for r in p["teams"].values()}
    assert {r["tier"] for r in p["teams"].values()} == {1, 2, 3}
    assert sum(r["contract"] == "free" for r in players.values()) >= 5


@pytest.mark.parametrize(
    "home,away,seed",
    [
        ("Team Vitality", "Team Falcons", 42),
        ("M80", "TYLOO", 47),
        ("The MongolZ", "FURIA Esports", 91),
    ],
)
def test_november_bo1_finishes_without_ovr(release, home, away, seed, monkeypatch):
    p = release["package"]
    by_name = {r["name"]: k for k, r in p["rosters"].items()}
    ids = [by_name[home], by_name[away]]
    monkeypatch.setattr(
        skills, "role_rating", lambda *args: pytest.fail("OVR in simulation")
    )
    domain = db.match_input(p, ids)
    for rid in ids:
        r = p["rosters"][rid]
        assert all(
            domain["players"][pid]["visual"]["kit"]["id"] == r["team"]
            for pid in r["players"]
        )
    w = match.initial(seed, domain, ids)
    while w["phase"] != "finished" and w["tick"] < 100000:
        match.advance(w)
    rounds = [
        e
        for batch in w["archive"] + [w["events"]]
        for e in batch
        if e["kind"] == "round_end"
    ]
    assert w["phase"] == "finished" and len(rounds) == sum(w["score"])
    print(home, away, seed, w["score"], w["serial"], w["tick"])
