"""Replay a real BO1 and compare native state transitions to the live Python reference."""
import argparse
from collections import Counter
from contextlib import ExitStack
import gzip
import json
from pathlib import Path
from unittest.mock import patch

from backend import cs2_maps, match, match_ai, native_match_state


def encode(world):
    return json.dumps(world, ensure_ascii=False, separators=(",", ":"))


def compare(checkpoint):
    world = json.loads(gzip.decompress(checkpoint.read_bytes()))
    space = cs2_maps.get(world["mapId"])
    counts = Counter()
    radio_types = set()
    ref_finish, ref_deliver = match.finish_round, match_ai.deliver_radio

    def same(owner, operation):
        other = json.loads(owner.snapshot())
        if encode(other) != encode(world):
            keys = [k for k in world.keys() | other.keys() if encode(world.get(k)) != encode(other.get(k))]
            raise ValueError(f"{operation} at tick {world['tick']}: {keys}")
        counts[operation] += 1

    def finish(w, side, reason):
        owner = native_match_state.restore(encode(w))
        owner.finish_round(side, reason)
        ref_finish(w, side, reason)
        same(owner, "round_end")

    def deliver(w, players, arena):
        # Compare the first delivery of each payload kind in each BO1. Later
        # deliveries also influence reference inputs for every round settlement.
        kinds = {k for m in w["messages"] if m["due"] <= w["tick"]
                 for k in m.keys() - {"team", "sender", "due"}}
        owner = native_match_state.restore(encode(w)) if kinds - radio_types else None
        ref_deliver(w, players, arena)
        if owner is not None:
            owner.deliver_radio()
            same(owner, "radio")
            radio_types.update(kinds)

    with ExitStack() as patches:
        patches.enter_context(patch.object(match, "finish_round", finish))
        patches.enter_context(patch.object(match_ai, "deliver_radio", deliver))
        while world["phase"] != "finished":
            if world["phase"] == "result":
                owner = native_match_state.restore(encode(world), space)
                ticks = world["deadline"] - world["tick"]
                assert owner.advance_intermission(ticks) == ticks
                for _ in range(ticks):
                    match.advance(world)
                same(owner, "new_round")
            else:
                match.advance(world)
    return {"map": world["mapId"], "seed": world["seed"], "score": world["score"],
            "ticks": world["tick"], "operations": counts, "radioPayloads": sorted(radio_types)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.checkpoint), ensure_ascii=False))
