import gzip
import json
from copy import deepcopy

import pytest

from backend import career, competition_scene, competitions, database, registrations


def test_major_stage_commitment_and_withdrawal_preserve_history():
    pack = competition_scene.extend(
        json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    )
    team = next(k for k, v in pack["teams"].items() if v["name"] == "Team Vitality")
    c = career.create(pack, dict(name="Тренер", team=team, scope="full", mode="owner"))
    events = c["circuit"]["editions"]
    major = events["pgl-major-2026"]
    early = events["ecl-eu-2026-13"]
    late = events["ecl-eu-2026-14"]
    assert major["entries"][team] == "locked"
    assert registrations.clashes(c, early, team) == [
        dict(id=major["id"], title=major["title"], state="locked", dates=["2026-12-03"])
    ]
    with pytest.raises(ValueError, match="2026-12-03"):
        registrations.signup(c, early, team, pack)
    registrations.signup(c, late, team, pack)
    archives = deepcopy(major["registrations"])
    games = deepcopy(major["draws"])
    competitions.leave(c, major, team, pack, "Приоритет ECL")
    assert (
        major["entries"][team] == "withdrawn"
        and major["registrations"] == archives
        and major["draws"] == games
    )
    registrations.signup(c, early, team, pack)
    assert early["entries"][team] == "accepted"
    major["entries"][team] = "offered"
    assert not registrations.clashes(c, early, team)
    major["entries"][team] = "invited"
    assert not registrations.clashes(c, early, team)
    # A participant in the active Swiss draw already has historical matches.
    fixture = next(f for f in c["queue"] if f.get("edition") == major["id"])
    loser = fixture["teams"][0]
    history = deepcopy(
        [g for g in major["draws"][0][0]["games"] if g.get("historical")]
    )
    competitions.leave(c, major, loser, pack, "Снятие после фиксации")
    assert not any(
        f.get("edition") == major["id"] and loser in f["teams"] for f in c["queue"]
    )
    assert [g for g in major["draws"][0][0]["games"] if g.get("historical")] == history
    assert major["draws"][0][0]["games"][fixture["game"]]["administrative"]
    assert major["registrations"][loser]


def test_only_flexible_slot_moves_and_bracket_follows():
    first = dict(
        id="a",
        entries={},
        reschedule="withinRound",
        modelDates=True,
        lan=False,
        stages=[dict(start="2026-10-01", end="2026-10-05")],
        draws=[[dict(games=[{"round": 0}])]],
    )
    fixed = dict(
        id="b",
        entries={},
        modelDates=False,
        stages=first["stages"],
        draws=deepcopy(first["draws"]),
    )
    queue = [
        dict(
            id=key,
            edition=key,
            kind="match",
            teams=["us", key],
            date="2026-10-01",
            stage=0,
            group=0,
            game=0,
        )
        for key in ("a", "b")
    ]
    c = dict(
        team="spectator",
        date="2026-10-01",
        queue=queue,
        circuit=dict(editions={"a": first, "b": fixed}),
    )
    competitions.resolve_slots(c)
    assert [f["edition"] for f in c["queue"]] == ["b", "a"]
    assert (
        c["queue"][1]["date"]
        == first["draws"][0][0]["games"][0]["date"]
        == "2026-10-02"
    )
    assert c["queue"][0]["date"] == "2026-10-01"


def test_ai_withdraws_from_lower_priority_fixed_semifinal():
    day = "2026-12-01"
    stage = dict(
        name="Плей-офф",
        format="single",
        start=day,
        end="2026-12-04",
        advance=1,
        bestOf=3,
    )
    events = {}
    c = dict(team="observer", date=day, circuit=dict(editions=events), queue=[])
    for name, prestige in (("cup", 3), ("masters", 1)):
        field = ["shared", *(f"{name}-{i}" for i in range(3))]
        event = dict(
            id=name,
            title=name,
            lock=day,
            status="playing",
            prestige=prestige,
            prizes=[10000],
            stages=[stage],
            draws=[],
            entries=dict.fromkeys(field, "locked"),
        )
        events[name] = event
        competitions.begin(c, event, field)
    semifinal = next(
        f for f in c["queue"] if f["edition"] == "masters" and "shared" in f["teams"]
    )
    competitions.settle_fixture_conflicts(c, semifinal, {})
    assert events["cup"]["entries"]["shared"] == "withdrawn"
    assert events["masters"]["entries"]["shared"] == "locked"
    assert competitions.fixture_conflicts(c, semifinal) == []
    assert (
        sum(
            bool(g.get("administrative")) for g in events["cup"]["draws"][0][0]["games"]
        )
        == 1
    )


def test_free_online_round_slot_works_in_either_registration_order():
    start, end = "2026-12-01", "2026-12-04"
    stage = dict(start=start, end=end, format="single", advance=1)
    fixed = dict(
        id="masters",
        title="Masters",
        entries={"club": "accepted"},
        start=start,
        end=end,
        stages=[stage],
        draws=[],
        lan=True,
    )
    online = dict(
        fixed, id="open", title="Open", capacity=2, lan=False, reschedule="withinRound"
    )
    c = dict(
        date=start, queue=[], circuit=dict(editions={"masters": fixed, "open": online})
    )
    assert registrations.clashes(c, fixed, "club") == []
    assert registrations.clashes(c, online, "club") == []
    online["stages"] = [dict(stage, roundDays=[0])]
    assert registrations.clashes(c, fixed, "club")[0]["dates"] == [start]
