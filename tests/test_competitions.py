import gzip
import hashlib
import json
import random
from copy import deepcopy

import pytest

from backend import career, competition_stages as stages, competitions, database, registrations, vrs


@pytest.fixture(scope="module")
def pack():
    return json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]


@pytest.fixture(scope="module")
def scene(pack):
    team = next(t for t, row in pack["teams"].items() if row["name"] == "SINNERS Esports")
    return career.create(pack, dict(team=team, name="Тренер", mode="owner", scope="full"))


def test_published_valve_engine_on_same_6731_series():
    # SHA of all 465 rows from Valve's unmodified model/ranking.js on this corpus.
    raw = vrs.history()
    rows = vrs.calculate(raw["matches"], raw["events"], "2026-11-25",
        {p: row["country"] for p,row in raw["players"].items()},
        json.loads((vrs.DATA/"vrs-regions.json").read_bytes()))
    oracle_shape = [[raw["clubs"][r["team"]]["name"], r["points"],
                     ["Europe","Americas","Asia"].index(r["region"]), r["nicks"]] for r in rows]
    assert len(raw["matches"])==6731 and len(rows)==465
    digest = hashlib.sha256(json.dumps(oracle_shape,ensure_ascii=False,separators=(",",":")).encode())
    assert digest.hexdigest()=="4dde537b60777f0755ead9a84f7f17fe28b85e89ff27540a497d20664f628cc4"
    assert not vrs.calculate(raw["matches"],raw["events"],"2027-06-01",{},{})


@pytest.mark.parametrize("fmt,n,advance,played", [
    ("single", 13, 1, 12), ("single", 29, 8, 21), ("double", 16, 1, 30),
    ("double", 11, 1, 20), ("roundRobin", 7, 4, 21), ("swiss", 16, 8, 33)])
def test_draw_completes_after_restore(fmt,n,advance,played):
    teams=[f"club{i}" for i in range(n)]
    draw=stages.draw(fmt,teams,advance)
    rng=random.Random(912)
    seen=set()
    count=0
    while True:
        draw=json.loads(json.dumps(draw))
        for i, pair in stages.ready(draw):
            key=frozenset(pair)
            if fmt in ("swiss","roundRobin"):
                assert key not in seen
            seen.add(key)
            win=rng.randrange(2)
            stages.record(draw,i,pair[win],pair[1-win])
            count+=1
        promoted=stages.finish_round(draw)
        if promoted is not None:
            break
    assert len(promoted)==len(set(promoted))==advance
    assert count==played
    if fmt=="swiss":
        assert all(row["wins"]==3 for row in stages.table(draw)[:8])


def test_major_advancement_uses_result_and_awards_only_once(scene):
    c=deepcopy(scene)
    edition=next(e for e in c["circuit"]["editions"].values() if e["series"]=="pgl-major")
    assert len(edition["registrations"])==32
    assert len([g for g in edition["draws"][0][0]["games"] if g.get("historical")])==16
    rng=random.Random(42)
    while edition["status"]=="playing":
        fixture=next(e for e in c["queue"] if e.get("edition")==edition["id"])
        c["queue"].remove(fixture)
        c["date"]=fixture["date"]
        a,b=fixture["teams"]
        winner=rng.choice([a,b])
        report=dict(winnerTeamId=winner,score=[int(winner==a),int(winner==b)],stats=[],rounds=[])
        competitions.completed(c,fixture,report)
        with pytest.raises(ValueError):
            competitions.completed(c,fixture,report)
    assert [len(draws[0]["teams"]) for draws in edition["draws"]]==[16,16,16,8]
    assert len(set(edition["placements"]))==32
    assert sum(c["circuit"]["awards"][edition["id"]].values())==1_250_000
    assert c["circuit"]["awards"]=={edition["id"]:edition["payouts"]}


def test_registration_transfer_lock_and_missed_deadline(pack,scene):
    c=deepcopy(scene)
    team=c["team"]
    event=next(e for e in c["circuit"]["editions"].values() if e["admission"]=="open")
    event["entries"].clear();event["registrations"].clear()
    members=list(pack["rosters"][c["teams"][team]]["players"])
    extras=[p for p in pack["players"] if p not in members and not any(
        p in r[-1]["players"]+r[-1]["reserves"] for e in c["circuit"]["editions"].values() for r in e["registrations"].values())][:2]
    c["circuit"]["bench"][team]=extras.copy()
    registrations.signup(c,event,team,pack)
    first=registrations.submit(c,event,team,pack,members,[extras[0]],None)
    regs=event["registrations"][team]
    before=deepcopy(first)
    newfive=[extras[1],*members[1:]]
    registrations.submit(c,event,team,pack,newfive,[extras[0]],None)
    c["date"]=event["lock"]
    event["status"]="playing";event["entries"][team]="locked"
    with pytest.raises(ValueError):
        registrations.submit(c,event,team,pack,members,[extras[0]],None)
    with pytest.raises(ValueError):
        registrations.submit(c,event,team,pack,members,[extras[0]],None,reason="Замена")
    emergency=registrations.submit(c,event,team,pack,[extras[0],*members[1:]],[extras[1]],None,reason="Болезнь")
    assert len(regs)==3 and regs[0]==before and emergency["version"]==3
    fixture={"edition":event["id"],"teams":[team,next(t for t in c["teams"] if t!=team)]}
    other=fixture["teams"][1]
    event["registrations"][other]=[dict(version=1,players=pack["rosters"][c["teams"][other]]["players"],coach=None,date=c["date"])]
    domain,ids=career.match_domain(pack,c,fixture)
    assert {m["player"] for m in domain["rosters"][ids[0]]["members"]}==set(emergency["players"])
    pending=deepcopy(event)
    pending.update(registrations={},entries={team:"accepted"})
    competitions.lock(c,pending,pack)
    assert pending["entries"][team]=="missed" and pending["status"]=="cancelled"
