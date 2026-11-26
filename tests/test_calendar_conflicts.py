import gzip
import json
from copy import deepcopy

import pytest

from backend import career, competition_scene, competitions, database, registrations


def test_major_stage_commitment_and_withdrawal_preserve_history():
    pack=competition_scene.extend(json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"])
    team=next(k for k,v in pack["teams"].items() if v["name"]=="Team Vitality")
    c=career.create(pack,dict(name="Тренер",team=team,scope="full",mode="owner"))
    events=c["circuit"]["editions"]
    major=events["pgl-major-2026"]
    early=events["ecl-eu-2026-13"]
    late=events["ecl-eu-2026-14"]
    assert major["entries"][team]=="locked"
    assert registrations.clashes(c,early,team)==[dict(id=major["id"],title=major["title"],state="locked",dates=["2026-12-03"])]
    with pytest.raises(ValueError,match="2026-12-03"):
        registrations.signup(c,early,team,pack)
    registrations.signup(c,late,team,pack)
    archives=deepcopy(major["registrations"])
    games=deepcopy(major["draws"])
    competitions.leave(c,major,team,pack,"Приоритет ECL")
    assert major["entries"][team]=="withdrawn" and major["registrations"]==archives and major["draws"]==games
    registrations.signup(c,early,team,pack)
    assert early["entries"][team]=="accepted"
    major["entries"][team]="offered"
    assert not registrations.clashes(c,early,team)
    major["entries"][team]="invited"
    assert not registrations.clashes(c,early,team)
    # A participant in the active Swiss draw already has historical matches.
    fixture=next(f for f in c["queue"] if f.get("edition")==major["id"])
    loser=fixture["teams"][0]
    history=deepcopy([g for g in major["draws"][0][0]["games"] if g.get("historical")])
    competitions.leave(c,major,loser,pack,"Снятие после фиксации")
    assert not any(f.get("edition")==major["id"] and loser in f["teams"] for f in c["queue"])
    assert [g for g in major["draws"][0][0]["games"] if g.get("historical")]==history
    assert major["draws"][0][0]["games"][fixture["game"]]["administrative"]
    assert major["registrations"][loser]


def test_only_flexible_slot_moves_and_bracket_follows():
    first=dict(id="a",entries={},modelDates=True,lan=False,stages=[dict(start="2026-10-01",end="2026-10-05")],
               draws=[[dict(games=[{"round":0}])]])
    fixed=dict(id="b",entries={},modelDates=False,stages=first["stages"],draws=deepcopy(first["draws"]))
    queue=[dict(id=key,edition=key,kind="match",teams=["us",key],date="2026-10-01",stage=0,group=0,game=0) for key in ("a","b")]
    c=dict(team="spectator",date="2026-10-01",queue=queue,circuit=dict(editions={"a":first,"b":fixed}))
    competitions.resolve_slots(c)
    assert [f["edition"] for f in c["queue"]]==["b","a"]
    assert c["queue"][1]["date"]==first["draws"][0][0]["games"][0]["date"]=="2026-10-02"
    assert c["queue"][0]["date"]=="2026-10-01"
