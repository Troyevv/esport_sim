"""Manual physical-map probe, from two real sightlines through radio to executed orders."""
import argparse
import gzip
import json
from math import atan2, dist
from random import Random

from backend import cs2_maps, database, match, native_match_state


def xyz(a):
    return tuple(a[k] for k in "xyz")


def place(a, point, area):
    a.update(zip("xyz", point))
    a.update(navArea=area, visible=[], knowledge={}, path=[], utility=[], waypoint=0)


def scenario(name, seed, policy, domain=None, rosters=None, wounded=False):
    space = cs2_maps.get(name)
    w = match.initial(seed, domain, rosters, map_id=name, agent_policy=policy) if domain else match.initial(seed, map_id=name, agent_policy=policy)
    match.advance(w, 45)
    w["tick"] += 40
    w["plans"]["CT"]["review"] = w["tick"]+15
    # Select authentic NAV centers on each site and an unobstructed witness position.
    centers = space.centers
    site = min((a for a, q in centers.items() if space.site_at(q)=="A"), key=lambda a:dist(centers[a],space.site_points["A"]))
    q = centers[site]
    witness = min((a for a, p in centers.items() if 6<dist(q,p)<35 and abs(p[2]-q[2])<5
                   and not space.hit(q,p,1,64,64)), key=lambda a:abs(dist(q,centers[a])-14))
    b = min(centers, key=lambda a:dist(centers[a], space.site_points["B"]))
    ct = [a for a in w["agents"] if a["team"]=="CT"]
    attackers = [a for a in w["agents"] if a["team"]=="T"]
    slots = w["plans"]["CT"]["orders"]["slots"]
    witnesses = sorted((a for a in ct if not a["appointed"]), key=lambda a:slots[a["slot"]]["site"]!="A")[:2]
    for a in ct:
        area = witness if a in witnesses else b
        place(a,centers[area],area)
        a["heading"] = atan2(q[1]-a["y"],q[0]-a["x"]) if a in witnesses else 0
    if wounded:
        for a in witnesses:
            a["hp"] = 19
    for a in attackers:
        place(a,q,site)
    owner = native_match_state.open_game(w)
    owner.observe()
    seen = json.loads(owner.snapshot())
    packets = [m for m in seen["messages"] if m["team"]=="CT" and "sight" in m]
    ids = {m["sight"]["id"] for m in packets}
    assert len(ids)==5 and len({m["sender"] for m in packets})>=2
    assert any(m["sight"].get("carryingC4") for m in packets)
    arrival = max(m["due"] for m in packets)
    captain = next(a for a in ct if a["appointed"])
    assert not captain["knowledge"]
    owner = native_match_state.open_game(dict(seen,tick=arrival))
    owner.deliver_radio()
    received=json.loads(owner.snapshot())
    reports=next(a["knowledge"] for a in received["agents"] if a["id"]==captain["id"])
    assert ids <= reports.keys()
    review=max(arrival,received["plans"]["CT"]["review"])
    owner=native_match_state.open_game(dict(received,tick=review))
    owner.review_captain("CT")
    called=json.loads(owner.snapshot())
    plan=called["plans"]["CT"]
    distant=[a for a in ct if a not in witnesses]
    start={a["id"]:xyz(a) for a in distant}
    # Follow actual physical execution and its radio acknowledgement.
    first_move, ack, assigned, conflicts = {}, {}, {}, 0
    for _ in range(12):
        owner.advance(1)
        after=json.loads(owner.snapshot())
        for a in after["agents"]:
            who=a["id"]
            if who not in start: continue
            if dist(xyz(a),start[who])>.25: first_move.setdefault(who,after["tick"]-arrival)
            p=after["plans"]["CT"]
            duties=[*p.get("commitments",{}).values(),p.get("backup"),p.get("secondBackup")]
            chosen=[d for d in duties if d and d["id"]==who]
            conflicts+=int(len(chosen)>1)
            if chosen:
                assigned[who]=chosen[0]["site"]
                if chosen[0].get("acknowledged"): ack[who]=chosen[0]["acknowledged"]
    return dict(map=name,policy=policy,wounded=wounded,witnesses=[a["id"] for a in witnesses],packets=len(packets),
                unique=len(ids),arrival=arrival-seen["tick"],review=review-arrival,
                call=plan["defenseCall"]["kind"],site=plan["defenseCall"]["site"],
                assigned=assigned,firstMove=first_move,ack=ack,conflictingDuties=conflicts,
                observations={key:[r["source"],r["tick"],r.get("carryingC4",False),r.get("groupSize")] for key,r in reports.items()})


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy",type=int,default=12)
    parser.add_argument("--wounded",action="store_true")
    args=parser.parse_args()
    pack=json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    for i,name in enumerate(cs2_maps.installed()):
        seed=56560+i
        rosters=Random(seed).sample(sorted(pack["rosters"]),2)
        print(json.dumps(scenario(name,seed,args.policy,database.match_input(pack,rosters),rosters,wounded=args.wounded),ensure_ascii=False),flush=True)
