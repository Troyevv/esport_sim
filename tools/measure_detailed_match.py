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


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


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
        from backend._match_native import NavSurfaces
        from backend.cs2_navigation import Navigation

        class NativeNavigation(Navigation):
            def __init__(self, data):
                super().__init__(data)
                self.surfaces = NavSurfaces([(area, desc["corners"]) for area, desc in self.areas.items()])

            def locate(self, point, max_vertical):
                return self.surfaces.locate_many([point], max_vertical)[0]

        cs2_maps.Navigation = NativeNavigation
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
            checkpoint = encode(game)
            if args.restore:
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
    report = dict(controls=controls, nativeNav=args.native_nav, restored=args.restore, python=platform.python_version(),
                  platform=platform.platform(), numpy=version("numpy"), embreex=version("embreex"),
                  initMs=initialized / 1e6, bo1WallS=wall / 1e9, cpuS=cpu / 1e9,
                  rssBeforeMiB=rss_start, peakMiB=peak,
                  meanTickMs=sum(durations) / len(durations) / 1e6,
                  p95TickMs=durations[math.ceil(.95 * len(durations)) - 1] / 1e6,
                  p99TickMs=durations[math.ceil(.99 * len(durations)) - 1] / 1e6)
    stem.with_suffix(".json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    print(args.map, game["score"], game["tick"], round(wall / 1e9, 2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", required=True, choices=cs2_maps.NAMES)
    parser.add_argument("--seed", type=int, default=41000)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--native-nav", action="store_true", help="Substitute native NAV lookup for comparison")
    parser.add_argument("--restore", action="store_true", help="Continue from JSON at tick 150")
    run(parser.parse_args())
