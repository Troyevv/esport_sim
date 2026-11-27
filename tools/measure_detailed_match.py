"""Measure one cold BO1 in a fresh process. Run manually for each map."""
import argparse
from collections import Counter
import gzip
import hashlib
from importlib.metadata import version
import json
import math
from pathlib import Path
import platform
import random
import sys
from time import perf_counter_ns, process_time_ns

import psutil

from backend import career, cs2_maps, database, match


def encode(value, *, sort_keys=True):
    return json.dumps(value, sort_keys=sort_keys, ensure_ascii=False, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def peak_mib():
    if sys.platform == "win32":
        return psutil.Process().memory_info().peak_wset / 2**20
    import resource
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (2**20 if sys.platform == "darwin" else 1024)


def run(args):
    if args.native_nav:
        # The differential harness is the only caller that substitutes geometry.
        # Production continues to use the reference until the entire tick is accepted.
        from backend.native_navigation import NativeNavigation

        cs2_maps.Navigation = NativeNavigation
    if args.native_rays:
        from backend import cs2_collision
        from backend._match_native import TriangleScene
        cs2_collision.TriangleScene = TriangleScene
    if args.native_collision:
        from backend import cs2_collision
        from backend.native_physics import NativeCollision
        cs2_collision.Collision = NativeCollision
    if args.native_perception:
        from backend import match_ai, native_physics
        cs2_maps.Map = native_physics.NativePerceptionMap
        match_ai.observed_players = native_physics.observed_players
        match_ai.hearing_estimates = native_physics.hearing_estimates
    elif args.native_movement:
        from backend.native_physics import NativeMovementMap
        cs2_maps.Map = NativeMovementMap
    elif args.native_physics:
        from backend.native_physics import NativePhysicalMap
        cs2_maps.Map = NativePhysicalMap
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pair = random.Random(args.seed).sample(sorted(career.roster_index(pack).values()), 2)
    domain = database.match_input(pack, pair)
    del pack
    rss_start = psutil.Process().memory_info().rss / 2**20
    durations = []
    poses = hashlib.sha256()
    started = perf_counter_ns()
    cpu = process_time_ns()
    game = match.initial(args.seed, domain, pair, map_id=args.map)
    initialized = perf_counter_ns() - started
    # Exercise the same legal manager input in every run.
    commands = [(0, "timeout", None), (0, "resume", None)]
    for _, kind, value in commands:
        match.command(game, kind, value)
    checkpoint = None
    while game["phase"] != "finished":
        before = perf_counter_ns()
        match.advance(game)
        durations.append(perf_counter_ns() - before)
        if game["tick"] == 150:
            # Store.write preserves insertion order. Dated contacts in an event
            # can reflect that order even when the match outcome is identical.
            checkpoint = encode(game, sort_keys=False)
            if args.checkpoint:
                saved = gzip.decompress(args.checkpoint.read_bytes())
                if hashlib.sha256(saved).digest() != hashlib.sha256(checkpoint).digest():
                    raise ValueError("The stored checkpoint differs at tick 150")
                game = json.loads(saved)
            elif args.restore:
                game = json.loads(checkpoint)
        if game["tick"] % 10 == 0:
            poses.update(encode([[a["id"], a["x"], a["y"], a["z"], a["hp"], a["navArea"]]
                                 for a in game["agents"]]))
        if game["tick"] >= 180000 or game["phase"] == "timeout":
            raise RuntimeError(f"BO1 stopped at tick {game['tick']}")
    wall = perf_counter_ns() - started
    cpu = process_time_ns() - cpu
    peak = peak_mib()
    rounds = [*game["archive"], game["events"]]
    counts = Counter(e["kind"] for events in rounds for e in events)
    durations.sort()
    controls = dict(seed=args.seed, map=args.map, rosterIds=pair, inputHash=digest(domain),
                    commands=commands, rules=game["rules"], geometry=game["map_version"],
                    checkpointVersion=game["checkpointVersion"], ticks=game["tick"],
                    score=game["score"], sides=Counter(r["side"] for r in game["history"]),
                    eventCounts=counts, ledgerHash=digest(rounds), stats=game["stats"],
                    posesHash=poses.hexdigest(), stateHash=digest(game),
                    checkpointHash=hashlib.sha256(checkpoint).hexdigest())
    args.out.mkdir(parents=True, exist_ok=True)
    stem = args.out / args.map
    stem.with_suffix(".checkpoint.json.gz").write_bytes(gzip.compress(checkpoint, mtime=0))
    movement = args.native_movement or args.native_perception
    physics = args.native_physics or movement
    collision = physics or args.native_collision
    report = dict(controls=controls, nativePerception=args.native_perception, nativeMovement=movement, nativePhysics=physics,
                  nativeCollision=collision, nativeRays=collision or args.native_rays,
                  nativeNav=physics or args.native_nav, restored=bool(args.restore or args.checkpoint),
                  python=platform.python_version(),
                  platform=platform.platform(), numpy=version("numpy"), embreex=version("embreex"),
                  initMs=initialized / 1e6, bo1WallS=wall / 1e9, cpuS=cpu / 1e9,
                  rssBeforeMiB=rss_start, peakMiB=peak,
                  meanTickMs=sum(durations) / len(durations) / 1e6,
                  p95TickMs=durations[math.ceil(.95 * len(durations)) - 1] / 1e6,
                  p99TickMs=durations[math.ceil(.99 * len(durations)) - 1] / 1e6)
    stem.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    if args.expect:
        expected = json.loads(args.expect.read_bytes())[args.map]
        actual = json.loads(encode(controls))
        differences = sorted(key for key in expected.keys() | actual.keys()
                             if expected.get(key) != actual.get(key))
        if differences:
            raise ValueError(f"{args.map}: reference mismatch in {', '.join(differences)}")
    print(args.map, game["score"], game["tick"], round(wall / 1e9, 2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--seed", type=int, default=41000)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, help="Continue from a pinned tick-150 checkpoint")
    parser.add_argument("--expect", type=Path, help="Compare all controls to a reference JSON by map")
    parser.add_argument("--native-collision", action="store_true", help="Use complete native segment queries")
    parser.add_argument("--native-perception", action="store_true", help="Use native vision, hearing and shot transmission with native movement")
    parser.add_argument("--native-movement", action="store_true", help="Use native walking and grenade flight with physical navigation")
    parser.add_argument("--native-physics", action="store_true", help="Use native physical route planning and collision")
    parser.add_argument("--native-rays", action="store_true", help="Use the native Embree triangle scene")
    parser.add_argument("--native-nav", action="store_true", help="Substitute native NAV lookup for comparison")
    parser.add_argument("--restore", action="store_true", help="Continue from JSON at tick 150")
    run(parser.parse_args())
