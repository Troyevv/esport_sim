"""Manual local checkpoint/weapon-pace measurements on installed CS2 geometry."""

import argparse
import json
import sqlite3
from math import dist
from pathlib import Path
from statistics import median
from time import thread_time_ns

from pydantic_core import from_json, to_json

from backend import cs2_maps, match, native_match_state
from tools.review_coaching_matches import fixture


def cpu_ms(fn):
    samples = []
    for _ in range(31):
        start = thread_time_ns()
        fn()
        samples.append((thread_time_ns() - start) / 1e6)
    return round(median(samples), 3)


def checkpoint(directory):
    with sqlite3.connect(f"file:{directory/'match.sqlite'}?mode=ro", uri=True) as db:
        raw = db.execute("SELECT body FROM active").fetchone()[0]
        s = from_json(raw)
        w = s["world"]
        owner = native_match_state.open_game(w)
        native = owner.snapshot()
        frame = match.project(w, "full")
        return dict(
            tick=w["tick"],
            round=w["round"],
            checkpointBytes=len(raw.encode()),
            nativeBytes=len(native),
            roundLogs=len(w.get("logs", [])),
            sqliteRead=cpu_ms(lambda: db.execute("SELECT body FROM active").fetchone()),
            activeDecode=cpu_ms(lambda: from_json(raw, cache_strings="keys")),
            nativeDump=cpu_ms(owner.snapshot),
            previousNativeDecode=cpu_ms(lambda: json.loads(native)),
            nativeDecode=cpu_ms(lambda: from_json(native, cache_strings="keys")),
            activeEncode=cpu_ms(lambda: to_json(s)),
            project=cpu_ms(lambda: match.project(w, "full")),
            previousWsEncode=cpu_ms(
                lambda: json.dumps(frame, ensure_ascii=False, separators=(",", ":"))
            ),
            wsEncode=cpu_ms(lambda: to_json(frame).decode()),
        )


def weapons():
    w = fixture("de_mirage", 56705, 0)
    results = {}
    for policy in (11, 12):
        game = match.initial(
            w["seed"],
            w["domain"],
            w["rosterIds"],
            map_id=w["mapId"],
            first_attack=w["firstAttackTeamId"],
            agent_policy=policy,
        )
        owner = native_match_state.open_game(game)
        owner.advance(50)
        start = json.loads(owner.snapshot())
        for name in ("Glock", "AK-47", "AWP", "Negev"):
            actor = next(a for a in start["agents"] if a["id"] == "T1")
            actor["weapon"] = name
            probe = native_match_state.open_game(start)
            poses = [m["T1"][0] for m in json.loads(probe.advance_motion(10))]
            end = next(
                a for a in json.loads(probe.snapshot())["agents"] if a["id"] == "T1"
            )
            points = [(x, y, z) for x, y, h, z in poses] + [
                (end["x"], end["y"], end["z"])
            ]
            results[f"{policy}/{name}"] = round(
                sum(dist(a, b) * cs2_maps.UNIT for a, b in zip(points, points[1:])), 2
            )
    return results


if __name__ == "__main__":
    p = argparse.ArgumentParser(__doc__)
    p.add_argument("root", type=Path)
    args = p.parse_args()
    print(
        json.dumps(
            dict(
                early=checkpoint(args.root / "before-early"),
                late=checkpoint(args.root / "before-late"),
                movementHUPerSecond=weapons(),
            ),
            indent=2,
        )
    )
