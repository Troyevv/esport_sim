import gzip
import hashlib
import json
import random
from copy import deepcopy

import pytest

from backend import (
    career,
    competition_stages as stages,
    competitions,
    database,
    registrations,
    vrs,
)


@pytest.fixture(scope="module")
def pack():
    return json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]


@pytest.fixture(scope="module")
def scene(pack):
    team = next(
        t for t, row in pack["teams"].items() if row["name"] == "SINNERS Esports"
    )
    return career.create(
        pack, dict(team=team, name="Тренер", mode="owner", scope="full")
    )


def test_published_valve_engine_on_same_6731_series():
    # SHA of all 465 rows from Valve's unmodified model/ranking.js on this corpus.
    raw = vrs.history()
    rows = vrs.calculate(
        raw["matches"],
        raw["events"],
        "2026-11-25",
        {p: row["country"] for p, row in raw["players"].items()},
        json.loads((vrs.DATA / "vrs-regions.json").read_bytes()),
    )
    oracle_shape = [
        [
            raw["clubs"][r["team"]]["name"],
            r["points"],
            ["Europe", "Americas", "Asia"].index(r["region"]),
            r["nicks"],
        ]
        for r in rows
    ]
    assert len(raw["matches"]) == 6731 and len(rows) == 465
    digest = hashlib.sha256(
        json.dumps(oracle_shape, ensure_ascii=False, separators=(",", ":")).encode()
    )
    assert (
        digest.hexdigest()
        == "4dde537b60777f0755ead9a84f7f17fe28b85e89ff27540a497d20664f628cc4"
    )
    assert not vrs.calculate(raw["matches"], raw["events"], "2027-06-01", {}, {})


@pytest.mark.parametrize(
    "fmt,n,advance,played",
    [
        ("single", 13, 1, 12),
        ("single", 29, 8, 21),
        ("double", 16, 1, 30),
        ("double", 11, 1, 20),
        ("roundRobin", 7, 4, 21),
        ("swiss", 16, 8, 33),
    ],
)
def test_draw_completes_after_restore(fmt, n, advance, played):
    teams = [f"club{i}" for i in range(n)]
    draw = stages.draw(fmt, teams, advance)
    rng = random.Random(912)
    seen = set()
    count = 0
    while True:
        draw = json.loads(json.dumps(draw))
        for i, pair in stages.ready(draw):
            key = frozenset(pair)
            if fmt in ("swiss", "roundRobin"):
                assert key not in seen
            seen.add(key)
            win = rng.randrange(2)
            stages.record(draw, i, pair[win], pair[1 - win])
            count += 1
        promoted = stages.finish_round(draw)
        if promoted is not None:
            break
    assert len(promoted) == len(set(promoted)) == advance
    assert count == played
    if fmt == "swiss":
        assert all(row["wins"] == 3 for row in stages.table(draw)[:8])


def test_major_advancement_uses_result_and_awards_only_once(scene):
    c = deepcopy(scene)
    edition = next(
        e for e in c["circuit"]["editions"].values() if e["series"] == "pgl-major"
    )
    assert len(edition["registrations"]) == 32
    assert (
        len([g for g in edition["draws"][0][0]["games"] if g.get("historical")]) == 16
    )
    rng = random.Random(42)
    while edition["status"] == "playing":
        fixture = next(e for e in c["queue"] if e.get("edition") == edition["id"])
        c["queue"].remove(fixture)
        c["date"] = fixture["date"]
        a, b = fixture["teams"]
        winner = rng.choice([a, b])
        report = dict(
            winnerTeamId=winner,
            score=[int(winner == a), int(winner == b)],
            stats=[],
            rounds=[],
        )
        competitions.completed(c, fixture, report)
        with pytest.raises(ValueError):
            competitions.completed(c, fixture, report)
    assert [len(draws[0]["teams"]) for draws in edition["draws"]] == [16, 16, 16, 8]
    assert len(set(edition["placements"])) == 32
    assert sum(c["circuit"]["awards"][edition["id"]].values()) == 1_250_000
    assert c["circuit"]["awards"] == {edition["id"]: edition["payouts"]}


def test_registration_transfer_lock_and_missed_deadline(pack, scene):
    c = deepcopy(scene)
    team = c["team"]
    event = next(
        e for e in c["circuit"]["editions"].values() if e["admission"] == "open"
    )
    event["entries"].clear()
    event["registrations"].clear()
    members = list(pack["rosters"][c["teams"][team]]["players"])
    extras = [
        p
        for p in pack["players"]
        if p not in members
        and not any(
            p in r[-1]["players"] + r[-1]["reserves"]
            for e in c["circuit"]["editions"].values()
            for r in e["registrations"].values()
        )
    ][:2]
    c["circuit"]["bench"][team] = extras.copy()
    registrations.signup(c, event, team, pack)
    first = registrations.submit(c, event, team, pack, members, [extras[0]], None)
    regs = event["registrations"][team]
    before = deepcopy(first)
    newfive = [extras[1], *members[1:]]
    registrations.submit(c, event, team, pack, newfive, [extras[0]], None)
    c["date"] = event["lock"]
    event["status"] = "playing"
    event["entries"][team] = "locked"
    with pytest.raises(ValueError):
        registrations.submit(c, event, team, pack, members, [extras[0]], None)
    with pytest.raises(ValueError):
        registrations.submit(
            c, event, team, pack, members, [extras[0]], None, reason="Замена"
        )
    emergency = registrations.submit(
        c,
        event,
        team,
        pack,
        [extras[0], *members[1:]],
        [extras[1]],
        None,
        reason="Болезнь",
    )
    assert len(regs) == 3 and regs[0] == before and emergency["version"] == 3
    fixture = {
        "edition": event["id"],
        "teams": [team, next(t for t in c["teams"] if t != team)],
    }
    other = fixture["teams"][1]
    event["registrations"][other] = [
        dict(
            version=1,
            players=pack["rosters"][c["teams"][other]]["players"],
            coach=None,
            date=c["date"],
        )
    ]
    domain, ids = career.match_domain(pack, c, fixture)
    assert {m["player"] for m in domain["rosters"][ids[0]]["members"]} == set(
        emergency["players"]
    )
    pending = deepcopy(event)
    pending.update(registrations={}, entries={team: "accepted"})
    competitions.lock(c, pending, pack)
    assert pending["entries"][team] == "missed" and pending["status"] == "cancelled"


def test_new_season_distinguishes_announced_and_generated_editions(pack, scene):
    c = deepcopy(scene)
    old = deepcopy(c["circuit"]["editions"]["pgl-major-2026"])
    c["date"] = "2027-01-01"
    competitions.tick(c, pack)
    events = c["circuit"]["editions"]
    assert events["pgl-major-2026"] == old
    assert not events["pw-major-2027"]["simulated"]
    assert events["fire-major-2027"]["start"] == "2027-05-31"
    assert not events["fire-major-2027"]["draws"]
    assert not events["iem-usa-2027"]["simulated"]
    assert (
        events["cct-contenders-2027-spring"]["start"]
        < events["cct-contenders-2027-summer"]["start"]
    )
    assert len(c["queue"]) == len({e["id"] for e in c["queue"]})


def test_registration_deadline_confirmation_and_waitlist(pack, scene):
    c = deepcopy(scene)
    event = c["circuit"]["editions"]["ecl-eu-2026-13"]
    team = next(t for t in event["entries"] if event["entries"][t] == "accepted")
    c["team"] = team
    event["capacity"] = 1
    stamp, rank = competitions.rank(c, event["seedDate"], pack)
    c["team"] = min(event["registrations"], key=lambda t: rank[t]["rank"])
    c["date"] = event["applyBy"]
    competitions.select_applicants(c, event, pack)
    assert event["entries"][c["team"]] == "offered" and event["seedSnapshot"] == stamp
    c["date"] = event["replyBy"][c["team"]]
    competitions.select_applicants(c, event, pack)
    assert event["entries"][c["team"]] == "missed"
    assert len([t for t, v in event["entries"].items() if v == "confirmed"]) == 1


def test_qualifier_carries_versions_and_excludes_other_branch(scene):
    c = deepcopy(scene)
    events = c["circuit"]["editions"]
    q = events["cct-contenders-2026-oq1"]
    target = events[q["feeds"]]
    team = next(
        t
        for t, versions in q["registrations"].items()
        if not registrations.conflict_for(c, target, t)
        and not registrations.player_conflict(
            c, target, t, versions[-1]["players"], versions[-1]["reserves"]
        )
    )
    c["date"] = q["end"]
    competitions.finish(c, q, [team])
    assert target["entries"][team] == "qualified"
    assert target["registrations"][team][0]["version"] == 1
    assert (
        target["registrations"][team][0]["players"]
        == q["registrations"][team][-1]["players"]
    )
    assert target["qualification"][team] == dict(
        edition=q["id"], version=q["registrations"][team][-1]["version"]
    )
    competitions.finish(c, q, [team])
    assert len(target["registrations"][team]) == 1
    assert target["registrations"][team] is not q["registrations"][team]
    assert events["cct-contenders-2026-oq2"]["entries"].get(team) in (
        None,
        "qualifiedElsewhere",
    )


def test_transfer_removes_access_without_rewriting_frozen_roster(pack, scene):
    c = deepcopy(scene)
    edition = c["circuit"]["editions"]["pgl-major-2026"]
    e = next(e for e in c["queue"] if e.get("edition") == edition["id"])
    team = e["teams"][0]
    start = deepcopy(edition["registrations"][team][-1])
    outgoing = start["players"][0]
    c["circuit"]["bench"][team] = []
    replacement = next(p for p in pack["players"] if p not in start["players"])
    pack = dict(
        pack,
        rosters={
            **pack["rosters"],
            "after-transfer": dict(
                pack["rosters"][c["teams"][team]],
                players=[replacement, *start["players"][1:]],
            ),
        },
    )
    c["teams"][team] = "after-transfer"
    assert competitions.missing_players(c, e, pack)[team] == {outgoing}
    with pytest.raises(ValueError, match="недоступен"):
        career.match_domain(pack, c, e)
    assert edition["registrations"][team][-1] == start
    assert competitions.resolve_availability(c, e, pack)
    row = edition["draws"][e["stage"]][e["group"]]["games"][e["game"]]
    assert row["administrative"] and "score" not in row and not c["history"]


def test_double_swiss_withdrawal_keeps_other_groups_playing():
    stage = stages.draw("swiss", [f"club{i}" for i in range(16)], 8)
    first, *games = stages.ready(stage)
    index, withdrawn = first
    stage["withdrawn"] = withdrawn
    stage["games"][index].update(winner=None, loser=None, administrative=True)
    promoted = None
    while promoted is None:
        for n, pair in stages.ready(stage):
            assert set(pair).isdisjoint(withdrawn)
            stages.record(stage, n, *pair)
        promoted = stages.finish_round(stage)
    assert len(set(promoted)) == 8 and set(promoted).isdisjoint(withdrawn)
    assert "score" not in stage["games"][index]


def test_cct_europe_opening_day_and_pinned_guest_rosters(pack):
    from backend import competition_scene

    extra = competition_scene.extend(pack)
    team = competition_scene.lineups()[0]["id"]
    c = career.create(extra, dict(team=team, name="Тренер", scope="full", mode="owner"))
    assert c["source"][-1] == competition_scene.EDITION
    qualifier = c["circuit"]["editions"]["cct-europe-2026-playin"]
    main = c["circuit"]["editions"]["cct-europe-2026"]
    assert len(qualifier["registrations"]) == 16 and len(main["entries"]) == 20
    games = [g for g in c["queue"] if g.get("edition") == qualifier["id"]]
    assert len(games) == 8 and {g["date"] for g in games} == {
        "2026-11-25",
        "2026-11-27",
    }
    for fixture in games:
        domain, _ = career.match_domain(extra, c, fixture)
        assert len(domain["players"]) == 10
    assert sum(main["prizes"]) == 25000 and list(map(len, main["direct"].values())) == [
        12,
        8,
    ]


def test_academy_starter_can_be_an_unused_major_reserve():
    academy = dict(start="2026-12-01", end="2026-12-13", entries={}, registrations={})
    major = dict(
        start="2026-11-24",
        end="2026-12-13",
        entries={"senior": "locked"},
        registrations={"senior": [dict(players=list("abcde"), reserves=["f"])]},
    )
    c = {"circuit": {"editions": {"academy": academy, "major": major}}}
    assert registrations.player_conflict(c, academy, "youth", list("fghij")) is None
    assert registrations.player_conflict(c, academy, "youth", list("aghij")) is major
    assert registrations.player_conflict(c, major, "rival", list("fghij")) is major
    academy["entries"]["youth"] = "locked"
    academy["registrations"]["youth"] = [dict(players=list("fghij"), reserves=[])]
    assert registrations.player_conflict(c, major, "senior", list("abcdf")) is academy
