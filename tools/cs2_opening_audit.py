"""Record the first 40 seconds through the match loop, including the first sighting."""

from copy import deepcopy
import argparse
import gzip
import json
import random
from pathlib import Path
from backend import career, cs2_maps, database, match


def record(pack, teams, name, index):
    seed = 73000 + index
    w = match.initial(seed, database.match_input(pack, teams), teams, map_id=name)
    # Change only pre-round finances. The real captain, purchase and enemy AI run.
    number, cash = ((1, 800), (4, 7600), (5, 900), (4, 3500), (12, 3000), (7, 6800))[
        index % 6
    ]
    w["round"] = number
    for p in w["agents"]:
        p["cash"] = cash
    while w["phase"] == "freeze":
        match.advance(w)
    start = w["tick"]
    plan = w["plans"]["CT"]
    opening = plan["opening"]
    initial_jobs = deepcopy(opening["jobs"])
    agents = [(p["id"], p["name"], p["team"]) for p in w["agents"]]
    frames = []
    while w["phase"] == "live" and w["tick"] - start <= 400:
        if (w["tick"] - start) % 5 == 0:
            frames.append(
                [
                    w["tick"] - start,
                    [
                        [*(round(v, 1) for v in cs2_maps.xyz(p)), p["hp"], p["status"]]
                        for p in w["agents"]
                    ],
                ]
            )
        match.advance(w)
    events = [
        dict(e, tick=e["tick"] - start)
        for e in w["events"]
        if start <= e["tick"] <= start + 400
        and e["kind"] in ("contact", "throw", "rotate", "kill", "plant")
    ]
    return dict(
        seed=seed,
        teams=teams,
        buy=plan["buy"],
        start=start,
        formation=plan["formation"],
        jobs=opening["jobs"],
        initial=initial_jobs,
        reports=opening["reports"],
        agents=agents,
        frames=frames,
        events=events,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", choices=cs2_maps.NAMES)
    parser.add_argument("output", type=Path)
    parser.add_argument("--rounds", type=int, default=18)
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pool = sorted(career.roster_index(pack).values())
    pairs = [random.Random(841 + i).sample(pool, 2) for i in range(3)]
    rows = [
        record(pack, pairs[(i // 6 + i % 3) % 3], args.map, i)
        for i in range(args.rounds)
    ]
    with gzip.open(args.output, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
