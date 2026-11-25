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


def test_every_release_club_has_a_local_distinct_badge(release):
    import base64
    import hashlib
    from io import BytesIO
    from PIL import Image
    from backend import club_art

    pack = release["package"]
    marks = {}
    for group in ("teams", "organizations"):
        for row in pack[group].values():
            logo = row["logo"]
            header, payload = logo["image"].split(",", 1)
            assert header == "data:image/png;base64"
            raw = base64.b64decode(payload, validate=True)
            checksum = hashlib.sha256(raw).hexdigest()
            info = club_art.catalog()[row["name"]]
            assert checksum == info["sha256"]
            assert (club_art.ROOT / (checksum + ".png")).read_bytes() == raw
            image = Image.open(BytesIO(raw)).convert("RGBA")
            assert image.size == (192, 192) and image.getchannel("A").getextrema() == (
                0,
                255,
            )
            status = pack["origins"][row["fields"]["logo"]]["status"]
            assert status == ("modeled" if info["kind"] == "game" else "confirmed")
            assert marks.setdefault(row["name"], checksum) == checksum
    assert len(marks) == len(pack["teams"])
    modeled = [sha for name, sha in marks.items() if club_art.catalog()[name]["kind"] == "game"]
    assert len(set(modeled)) == len(modeled)
    assert set(modeled).isdisjoint(sha for name, sha in marks.items() if club_art.catalog()[name]["kind"] == "original")
    assert set(marks.values()) == {p.stem for p in club_art.ROOT.glob("*.png")}
    assert all(r["decision"] and r.get("checked") is not None for r in club_art.catalog().values())
