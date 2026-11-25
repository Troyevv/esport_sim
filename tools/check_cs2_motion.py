"""Inspect rejected movement segments against NAV and the actual Source 2 surfaces."""

import argparse
from bisect import bisect_right
from collections import Counter
import json
from math import dist
import numpy as np
from backend import cs2_maps


def inspect(name):
    space = cs2_maps.get(name)
    meta = json.loads((space.folder / "collision.json").read_bytes())
    limits = np.cumsum([b["triangles"] for b in space.collision.blocks]).tolist()
    by_class = Counter((i["kind"], i["active"]) for i in meta.get("instances", []))
    print("IMPORT", name, dict(by_class), flush=True)
    if name == "de_vertigo":
        for i in meta.get("instances", []):
            if i["kind"] == "func_brush":
                print(
                    "BRUSH",
                    name,
                    i["name"],
                    i["disabled"],
                    i["solidity"],
                    i["model"],
                    flush=True,
                )
    reasons = Counter()
    examples = {}
    for side in ("T", "CT"):
        agents = []
        for slot in range(5):
            p, _, area = space.spawn(side, slot)
            agents.append(dict(zip(("x", "y", "z"), p), slot=slot, navArea=area))
        for site in ("A", "B"):
            orders = space.orders(side, site, agents, 0)
            for a, o in zip(agents, orders["slots"]):
                pos = cs2_maps.xyz(a)
                area = a["navArea"]
                for goal in [*o["via"], o["plant"] if side == "T" else o["hold"]]:
                    target = space.locate(tuple(goal))
                    for cross in space.route(area, target) or ():
                        leave, enter = (
                            space.to_sim(cross.leave),
                            space.to_sim(cross.enter),
                        )
                        for start, end in [(pos, leave), (leave, enter)]:
                            hit = space.hit(start, end, 2, 34)
                            if not hit:
                                continue
                            p, q = space.world(start), space.world(end)
                            start_world = np.array(
                                [[p[0], p[1], p[2] + 34]], dtype=np.float32
                            )
                            delta = np.array([q], dtype=np.float32) - np.array(
                                [p], dtype=np.float32
                            )
                            faces, _, _ = space.collision.scene.first_many(
                                start_world + delta * max(0, hit[0] - 0.0005),
                                delta,
                                0.002,
                            )
                            face = faces[0]
                            block = (
                                space.collision.blocks[bisect_right(limits, int(face))]
                                if face >= 0
                                else {}
                            )
                            key = (
                                block.get("entity", "primitive"),
                                tuple(block.get("tags", [])),
                                block.get("group", ""),
                                hit[1],
                            )
                            reasons[key] += 1
                            if key not in examples:
                                examples[key] = dict(
                                    areas=[area, cross.area],
                                    p=p,
                                    q=q,
                                    hit=hit[0],
                                    length=dist(p, q),
                                    heights=[
                                        h
                                        for h in (12, 20, 32, 46, 62, 76)
                                        if space.hit(start, end, 2, h)
                                    ],
                                    ladder=cross.ladder,
                                )
                        area, pos = cross.area, enter
                    area, pos = target, tuple(goal)
    for key, count in reasons.most_common(20):
        print("OBSTACLE", name, count, key, examples[key], flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    inspect(parser.parse_args().map)
