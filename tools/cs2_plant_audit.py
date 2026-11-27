"""Observer-only audit of CT sight lines at the instant a player starts planting."""

import argparse
from collections import Counter
import gzip
import json
from math import dist
from pathlib import Path
import random

from tests.reference_kernel import cs2_maps, match, match_ai
from backend import career, database


def record(name, seed, pack):
    teams = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    game = match.initial(seed, database.match_input(pack, teams), teams, map_id=name)
    space = cs2_maps.get(name)
    attempts = []
    defense = Counter()
    while game["phase"] != "finished":
        phase = game["phase"]
        match.advance(game)
        if phase == "live" and game["phase"] == "planted":
            assert attempts and attempts[-1]["round"] == game["round"]
            attempts[-1]["planted"] = True
        # Observer sees the finished tick. Independent individual sight lists
        # are sampled before installation without feeding any result to the AI.
        if game["phase"] == "live" and game["tick"] % 10 == 0:
            defense["liveSeconds"] += 1
            targets = Counter(target for a in game["agents"] if a["team"] == "CT" and a["hp"]
                              for target in a["visible"])
            if targets:
                defense["contactSeconds"] += 1
                defense["sharedSeconds"] += max(targets.values()) >= 2
            carrier = game["bomb"]["carrier"]
            if carrier:
                defense["carrierSeenSeconds"] += carrier in targets
        action = game["action"]
        if not action or action["kind"] != "plant" or action["start"] != game["tick"]:
            continue
        now = game["tick"]
        planter = next(a for a in game["agents"] if a["id"] == action["player"])
        fog = [
            f
            for f in game["effects"]
            if f["kind"] == "Дым" and f["land"] <= now < f["end"]
        ]
        guards = [a for a in game["agents"] if a["team"] == "CT" and a["hp"]]
        visible = [a for a in guards if space.clear(a, planter)]
        gaze = [a for a in visible if match_ai.in_view(a, planter)]
        open_gaze = [
            a
            for a in gaze
            if a["blind"] <= now
            and not any(match_ai.near_line(a, planter, f, f["radius"]) for f in fog)
        ]
        attempts.append(
            dict(
                round=game["round"],
                side=action["site"],
                guards=len(guards),
                line=len(visible),
                gaze=len(gaze),
                blind=sum(a["blind"] > now for a in gaze),
                ctSmoke=any(match_ai.near_line(a, planter, f, f["radius"])
                           for a in gaze for f in fog if f["team"] == "CT"),
                tSmoke=any(match_ai.near_line(a, planter, f, f["radius"])
                          for a in gaze for f in fog if f["team"] == "T"),
                screeningClouds=[
                    dict(team=f["team"], player=f["player"],
                         distanceHU=round(dist(cs2_maps.xyz(f),cs2_maps.xyz(planter))*cs2_maps.UNIT))
                    for f in fog if any(match_ai.near_line(a,planter,f,f["radius"]) for a in gaze)
                ],
                unobscured=len(open_gaze),
                nearby=sum(
                    dist(cs2_maps.xyz(a), cs2_maps.xyz(planter)) * cs2_maps.UNIT <= 600
                    for a in guards
                ),
                planted=False,
            )
        )
    return dict(
        map=name, seed=seed, teams=teams, rounds=len(game["history"]), defense=defense, attempts=attempts
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    p.add_argument("--seed", type=int, default=41000)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(record(args.map, args.seed, pack), ensure_ascii=False)
    )
