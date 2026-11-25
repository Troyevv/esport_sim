"""Record matched, side-reversed BO1s and an independent sample from the same engine."""
import argparse
from collections import Counter
import gzip
import json
from math import dist
from pathlib import Path
import random
from time import perf_counter

from backend import career, cs2_maps, database, match
from backend.match_rules import equipment_value


def run(name, seed, order, pack, replay):
    domain = database.match_input(pack, order)
    game = match.initial(seed, domain, order, map_id=name)
    space = cs2_maps.get(name)
    rows, frames = [], []
    started = perf_counter()
    while game["phase"] != "finished":
        phase = game["phase"]
        match.advance(game)
        tick = game["tick"]
        if phase == "freeze" and game["phase"] == "live":
            live = tick
            guards = [a for a in game["agents"] if a["team"] == "CT"]
            holds = game["plans"]["CT"]["orders"]["slots"]
            reached, saves, retakers = {}, set(), set()
            row = dict(round=game["round"], equip={s:sum(equipment_value(a) for a in game["agents"] if a["team"] == s) for s in ("T","CT")},
                       opening=game["plans"]["T"]["site"], buy={s:game["plans"][s].get("buy") for s in ("T","CT")})
            if replay:
                row["holds"] = [[slot["site"],slot["hold"],slot["watch"]] for slot in holds]
        if game["phase"] in ("live","planted"):
            if tick % 10 == 0:
                for a in guards:
                    if not a["hp"]:
                        continue
                    if dist(cs2_maps.xyz(a), holds[a["slot"]]["hold"]) <= 5:
                        reached.setdefault(a["id"], tick-live)
                    if a["status"] == "Сохраняет оружие":
                        saves.add(a["id"])
                    if a["status"] == "Идёт на ретейк":
                        retakers.add(a["id"])
                if replay:
                    frames.append([tick,game["round"],game["phase"],[[a["team"],a["slot"],*[round(x,1) for x in cs2_maps.xyz(a)],a["hp"],a["status"]] for a in game["agents"]]])
            if phase == "live" and game["phase"] == "planted":
                row.update(plant=tick-live, site=game["bomb"]["site"], guardsAtPlant=len(reached),
                           ctAliveAtPlant=sum(bool(a["hp"]) for a in guards))
        if game["phase"] in ("result","finished") and phase not in ("result","finished"):
            events = game["events"]
            history = game["history"][-1]
            contact = next((e for e in events if e["kind"]=="contact"), None)
            row.update(side=history["side"],reason=history["reason"],duration=tick-live,
                       contact=contact["tick"]-live if contact else None,
                       holdsReached=list(reached.values()),retake=bool(retakers),
                       saves=sum(bool(a["hp"]) and a["id"] in saves for a in guards),
                       survivingCT=sum(bool(a["hp"]) for a in guards),
                       utility={s:dict(Counter(e["utility"] for e in events if e["kind"]=="throw" and e["player"] in {a["id"] for a in game["agents"] if a["team"]==s})) for s in ("CT","T")},
                       rotations=sum(e["kind"]=="rotate" for e in events))
            rows.append(row)
        if tick > 180000:
            raise RuntimeError((name, seed, tick))
    return dict(seed=seed, teams=order, seconds=round(perf_counter()-started,3), rounds=rows), frames


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map",choices=cs2_maps.NAMES,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--pairs",type=int,default=12)
    p.add_argument("--seed",type=int,default=41000)
    args=p.parse_args()
    pack=json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters=sorted(career.roster_index(pack).values())
    args.out.mkdir(parents=True,exist_ok=True)
    path=args.out / (args.map+".jsonl")
    with path.open("w",encoding="utf-8") as report:
        for i in range(args.pairs):
            seed=args.seed+i
            pair=random.Random(seed).sample(rosters,2)
            for mirror,order in enumerate((pair,list(reversed(pair)))):
                row,frames=run(args.map,seed,order,pack,i==0 and not mirror)
                report.write(json.dumps(row,ensure_ascii=False)+"\n")
                report.flush()
                if frames:
                    with gzip.open(args.out / (args.map+"-radar.json.gz"),"wt",encoding="utf-8") as f:
                        json.dump(frames,f,ensure_ascii=False)
            print(args.map, seed, "обе стартовые стороны", flush=True)


if __name__=="__main__":
    main()
