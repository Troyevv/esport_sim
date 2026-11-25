"""Run event-driven BO1s against the installed map pack and record replay samples."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import random
from statistics import mean
from time import perf_counter

import psutil
from backend import career, cs2_maps, database, match


def play(name, seed, pair, pack, replay):
    started = perf_counter()
    domain = database.match_input(pack,pair)
    game = match.initial(seed,domain,pair,map_id=name)
    peak=0
    process=psutil.Process()
    frames=[]
    saves=set()
    retakes=set()
    stalls=set()
    team_sides={}
    while game["phase"]!="finished":
        match.advance(game)
        tick=game["tick"]
        if tick>180000:
            raise RuntimeError(f"{name}/{seed}: BO1 превысил 180000 тиков")
        if tick%10==0:
            for a in game["agents"]:
                team_sides[game["round"],a["id"]]=a["team"]
                if not a["hp"]:
                    continue
                if a["status"]=="Сохраняет оружие":
                    saves.add((game["round"],a["id"]))
                if a["status"]=="Идёт на ретейк":
                    retakes.add(game["round"])
                if a.get("blockedTicks",0)>=20:
                    stalls.add((game["round"],a["id"]))
            if replay and game["round"]<=3:
                frames.append([tick,game["round"],game["phase"],
                               [[round(a["x"],1),round(a["y"],1),round(a["z"],1),a["hp"],a["status"]]
                                for a in game["agents"]]])
        if tick%200==0:
            peak=max(peak,process.memory_info().rss)
    rounds=game["archive"]+[game["events"]]
    trades=own=rotations=0
    utility=Counter()
    plans=Counter()
    plants=0
    survived=set(saves)
    for n,events in enumerate(rounds,1):
        for event in events:
            kind=event["kind"]
            plants+=kind=="plant"
            rotations+=kind=="rotate"
            if kind=="kill":
                survived.discard((n,event["target"]))
                trades+=bool(event["trade"])
                own+=event["weapon"]=="C4" and team_sides.get((n,event["target"]))=="T"
            if kind=="throw":
                utility[event["utility"]]+=1
            if kind=="plan" and event["team"]=="T":
                plans[event["site"]+" "+event["style"]]+=1
    results=dict(seed=seed,map=name,teams=[game["domain"]["teams"][t]["name"] for t in game["scoreByTeam"]],
                 score=game["score"],rounds=len(rounds),ticks=game["tick"],seconds=round(perf_counter()-started,3),
                 peakMiB=round(max(peak,process.memory_info().rss)/2**20,1),
                 reasons=Counter(h["reason"] for h in game["history"]),sides=Counter(h["side"] for h in game["history"]),
                 plants=plants,retakes=len(retakes),saveDecisions=len(saves),saved=len(survived),
                 ownC4=own,utility=utility,plans=plans,rotations=rotations,trades=trades,stalls=len(stalls))
    return results,frames


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map",choices=cs2_maps.NAMES,required=True)
    parser.add_argument("--games",type=int,default=12)
    parser.add_argument("--seed",type=int,default=41000)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    pack=json.loads(gzip.decompress(database.RELEASE.read_bytes()))
    rosters=sorted(career.roster_index(pack).values())
    args.out.mkdir(exist_ok=True,parents=True)
    rows=[]
    for i in range(args.games):
        seed=args.seed+i
        pair=random.Random(seed).sample(rosters,2)
        row,frames=play(args.map,seed,pair,pack,i==0)
        rows.append(row)
        print("BO1",json.dumps(row,ensure_ascii=False),flush=True)
        if frames:
            (args.out/(args.map+"-frames.json")).write_text(json.dumps(frames,ensure_ascii=False))
            # Short, evenly spaced samples can also be viewed from the CI journal.
            print("RADAR",json.dumps([[f[0],f[1],f[2],[a[:4] for a in f[3]]] for f in frames[::5]],separators=(",",":")),flush=True)
    (args.out/(args.map+".json")).write_text(json.dumps(rows,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
