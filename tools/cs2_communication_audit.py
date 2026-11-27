"""Paired full BO1 audit. Run explicitly with a baseline or candidate on PYTHONPATH."""

import argparse
from collections import Counter
from functools import lru_cache
import gzip
import json
from math import dist
from pathlib import Path
from random import Random
from time import perf_counter, process_time

from tests.reference_kernel import cs2_defense, cs2_maps, match
from backend import career, database


def play(pack, name, index, directory):
    # 15 seed/roster blocks. Each block reverses the starting sides.
    seed = 65400 + index // 2
    pool = sorted(career.roster_index(pack).values())
    rosters = Random(seed).sample(pool, 2)
    domain = database.match_input(pack, rosters)
    first = domain["rosters"][rosters[index % 2]]["team"]
    started, cpu = perf_counter(), process_time()
    w = match.initial(seed, domain, rosters, map_id=name, first_attack=first)
    space = cs2_maps.get(name)

    @lru_cache(maxsize=4096)
    def area_site(area):
        return space.reported_site(space.centers[area]) or space.entry_sites.get(area)

    counts = Counter()
    times = []
    recent = {}
    active = {}
    rotated = False
    round_start = 0
    ids = {a["id"]: a for a in w["agents"]}
    record = index < 2
    frames, cues = [], []
    while w["phase"] != "finished":
        phase = w["phase"]
        t = w["tick"] + 1
        serial = w["serial"]
        if phase == "live":
            captain = w["plans"]["CT"]["captain"]
            for msg in w["messages"]:
                sight = msg.get("sight")
                if (
                    msg["team"] != "CT"
                    or msg["sender"] == captain
                    or not sight
                    or msg["due"] != t
                    or not ids[captain]["hp"]
                    or sight["tick"]
                    <= ids[captain]["knowledge"].get(sight["id"], {}).get("tick", -1)
                ):
                    continue
                area = space.locate(cs2_maps.xyz(sight))
                site = area_site(area) if area is not None else None
                if site and (site not in recent or t - recent[site][1] > 30):
                    recent[site] = [t, t]
                    counts["episodes"] += 1
                if site:
                    recent[site][1] = t
                if record and (sight["source"] != "Зрение" or t % 10 == 0):
                    cues.append(
                        [w["round"], t, "radio", msg["sender"], sight["source"], site]
                    )
        match.advance(w)
        if w["tick"] > 180000:
            raise RuntimeError((name, seed, "unfinished"))
        if phase == "freeze" and w["phase"] == "live":
            active.clear()
            recent.clear()
            rotated = False
            round_start = t
        if phase not in ("planted", "live"):
            continue
        for event in reversed(w["events"]):
            if event["id"] <= serial:
                break
            kind = event["kind"]
            if kind == "round_end":
                counts["rounds"] += 1
                counts[event["side"]] += 1
            elif kind == "plant":
                counts["plants"] += 1
            elif kind == "defuse":
                counts["defuses"] += 1
            elif kind == "throw":
                counts["utility_" + event["team"]] += 1
            elif kind == "kill":
                counts["kills"] += 1
                counts["trades"] += bool(event.get("trade"))
            if record and kind in (
                "rotate",
                "kill",
                "plant",
                "defuse",
                "round_end",
                "throw",
            ):
                cues.append(
                    [
                        w["round"],
                        t,
                        kind,
                        event["text"],
                        event.get("team"),
                        event.get("assignments"),
                    ]
                )
        if phase == "live":
            plan = w["plans"]["CT"]
            for pid, a in ids.items():
                if a["team"] != "CT":
                    continue
                duty = cs2_defense.relief(plan, a) if a["hp"] else None
                key = duty["site"] if duty else None
                prior = active.get(pid)
                if prior and prior["site"] != key:
                    if a["hp"]:
                        counts["revoked"] += 1
                    del active[pid]
                if not duty:
                    continue
                pos = cs2_maps.xyz(a)
                if pid not in active:
                    if not rotated:
                        counts["rotation_rounds"] += 1
                        rotated = True
                    counts["orders"] += 1
                    report = recent.get(key)
                    active[pid] = dict(
                        site=key,
                        start=t,
                        distance=dist(pos, duty["hold"]),
                        report=report[0] if report and t - report[1] <= 30 else None,
                    )
                job = active[pid]
                remaining = dist(pos, duty["hold"])
                if not job.get("acted") and (
                    remaining < 8 or job["distance"] - remaining >= 6
                ):
                    job["acted"] = True
                    if job["report"] is not None:
                        times.append(t - job["report"])
                if remaining < 8 and not job.get("arrived"):
                    counts["arrived"] += 1
                    job["arrived"] = True
        if record and t % 5 == 0:
            frames.append(
                [
                    w["round"],
                    t,
                    t - round_start,
                    [
                        [
                            a["id"],
                            a["team"],
                            *[round(v, 1) for v in cs2_maps.xyz(a)],
                            round(a["heading"], 2),
                            a["hp"],
                            a["status"],
                        ]
                        for a in w["agents"]
                    ],
                ]
            )
    result = dict(
        rules=w["rules"],
        map=name,
        index=index,
        seed=seed,
        rosters=rosters,
        first=first,
        counts=dict(counts),
        latency=times,
        ticks=w["tick"],
        seconds=perf_counter() - started,
        cpu=process_time() - cpu,
        score=w["score"],
    )
    path = directory / f"{name}-{index:02d}.json"
    if record:
        with gzip.open(path.with_suffix(".radar.gz"), "wt", encoding="utf-8") as f:
            json.dump(
                dict(frames=frames, cues=cues),
                f,
                ensure_ascii=False,
                separators=(",", ":"),
            )
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(result), encoding="utf-8")
    tmp.replace(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", choices=cs2_maps.NAMES)
    parser.add_argument("directory", type=Path)
    parser.add_argument("indices", type=int, nargs="+")
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    for i in args.indices:
        if not (args.directory / f"{args.map}-{i:02d}.json").exists():
            play(pack, args.map, i, args.directory)
