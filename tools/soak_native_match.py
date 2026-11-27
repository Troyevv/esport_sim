"""Manual repeatability, resident-memory and checkpoint-boundary measurements."""
import argparse
import gc
import gzip
import hashlib
import json
from pathlib import Path
from time import perf_counter_ns

import psutil

from backend import native_match_state
from backend.cs2_maps import root


def measure(fn, count):
    start = perf_counter_ns()
    for _ in range(count):
        fn()
    return (perf_counter_ns() - start) / count / 1000


def run(path, repeats):
    saved = gzip.decompress(path.read_bytes()).decode()
    initial = json.loads(saved)
    arena = native_match_state.physical_map(root() / initial["mapId"])
    process = psutil.Process()
    owner = native_match_state.restore(saved, arena, physics=arena)
    boundary = dict(emptyCallUs=measure(lambda: owner.advance(0), 20000),
                    snapshotUs=measure(owner.snapshot, 100),
                    decodeSnapshotUs=measure(lambda: json.loads(owner.snapshot()), 100),
                    checkpointBytes=len(saved.encode()))
    samples = []
    digest = None
    ticks = 0
    for _ in range(repeats):
        owner = native_match_state.restore(saved, arena, physics=arena)
        while count := owner.advance(2048):
            ticks += count
        body = owner.snapshot()
        final = hashlib.sha256(body).hexdigest()
        if json.loads(body)["phase"] != "finished" or digest not in (None, final):
            raise RuntimeError("Repeat replay differs or stopped before finishing")
        digest = final
        del owner, body
        gc.collect()
        samples.append(round(process.memory_info().rss / 2**20, 3))
    return dict(map=initial["mapId"], repeats=repeats, ticks=ticks, sha256=digest,
                residentMiBAfterRelease=samples, boundary=boundary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--repeats", type=int, default=12)
    args = parser.parse_args()
    if args.repeats <= 0:
        parser.error("repeats must be positive")
    print(json.dumps(run(args.checkpoint, args.repeats)))
