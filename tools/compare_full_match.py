"""Manual differential replay of complete C++ ticks, including checkpoint restoration."""
import argparse
import gzip
import json
from pathlib import Path
from time import perf_counter

from backend import cs2_maps, match, native_match_state
from backend.native_physics import NativePerceptionMap
from tools.compare_native_state import encode


def difference(left, right, path="$"):
    if type(left) is not type(right):
        return path, left, right
    if isinstance(left, dict):
        if list(left) != list(right):
            return path + ".keys", list(left), list(right)
        for key, value in left.items():
            if delta := difference(value, right[key], f"{path}.{key}"):
                return delta
    elif isinstance(left, list):
        if len(left) != len(right):
            return path + ".length", len(left), len(right)
        for i, value in enumerate(left):
            if delta := difference(value, right[i], f"{path}[{i}]"):
                return delta
    elif left != right:
        return path, left, right


def compare(checkpoint, interval, limit, diagnostic=None):
    world = json.loads(gzip.decompress(checkpoint.read_bytes()))
    space = cs2_maps.get(world["mapId"])
    physics = NativePerceptionMap(space.folder)

    def restore(saved):
        return native_match_state.restore(saved, space, physics=physics)

    def reference(game, n):
        for _ in range(n):
            match.advance(game)

    owner = restore(encode(world))
    stop = world["tick"] + limit if limit else None
    samples = 0
    elapsed = [0., 0.]
    while world["phase"] not in ("timeout", "finished") and (stop is None or world["tick"] < stop):
        before = encode(world)
        size = min(interval, stop-world["tick"]) if stop else interval
        start = perf_counter()
        reference(world, size)
        elapsed[0] += perf_counter() - start
        start = perf_counter()
        try:
            owner.advance(size)
            elapsed[1] += perf_counter() - start
            success = encode(world) == encode(json.loads(owner.snapshot()))
        except (ValueError, IndexError, RuntimeError):
            success = False
        if not success:
            replay, owner = json.loads(before), restore(before)
            for _ in range(size):
                if diagnostic:
                    diagnostic.write_text(encode(replay), encoding="utf-8")
                reference(replay, 1)
                try:
                    owner.advance(1)
                except Exception as error:
                    raise RuntimeError(f"{space.name}, tick {replay['tick']}: {error}") from error
                actual = json.loads(owner.snapshot())
                if delta := difference(json.loads(encode(replay)), actual):
                    raise AssertionError(f"{space.name}, tick {replay['tick']}, {delta}")
            raise AssertionError("batch and single tick replay differ")
        samples += 1
    return dict(map=space.name, seed=world["seed"], tick=world["tick"], phase=world["phase"],
                score=world["score"], events=world["serial"], checkpoints=samples,
                python_seconds=elapsed[0], native_seconds=elapsed[1])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    parser.add_argument("--interval", type=int, default=128)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--diagnostic", type=Path, help="Save reference state immediately before the first difference")
    args = parser.parse_args()
    if args.interval < 1 or args.limit < 0:
        parser.error("interval must be positive and limit nonnegative")
    print(json.dumps(compare(args.checkpoint, args.interval, args.limit, args.diagnostic), ensure_ascii=False))
