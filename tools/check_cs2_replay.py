"""Replay four cross-CPU checkpoints and an observed Train retake with a hidden plant."""

import gzip
import json
import random
from math import dist
from pathlib import Path

from backend import career, cs2_maps, database, match


def main():
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    seed = 41000
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    # Each tick is the first different recorded position in independent CI replays.
    samples = (
        ("de_vertigo", 100, 4, (135.81, 185.47, 957.67), 100),
        ("de_cache", 250, 0, (164.84, 244.99, 134.33), 100),
        ("de_nuke", 190, 1, (320.58, 315.48, -32.33), 100),
        ("de_dust2", 1450, 0, (121.75, 337.25, 10.00), 100),
    )
    failures = []
    for name, tick, slot, point, hp in samples:
        state = match.initial(seed, database.match_input(pack, pair), pair, map_id=name)
        trace = []
        for _ in range(tick):
            match.advance(state)
            actor = state["agents"][slot]
            if state["tick"] % 10 == 0:
                trace.append([state["tick"], actor["navArea"], actor["status"],
                              *[round(v, 4) for v in cs2_maps.xyz(actor)], actor["hp"],
                              actor["dest"], actor["visible"]])
        actor = state["agents"][slot]
        position = cs2_maps.xyz(actor)
        if dist(position, point) > 0.02 or actor["hp"] != hp:
            failures.append(f"{name}, tick={tick}, {actor['id']}: XYZ={position}, HP={actor['hp']}")
            for snap in trace:
                print("TRACE", name, json.dumps(snap, ensure_ascii=False))
            continue
        print(f"{name}: tick {tick}, {actor['id']}, XYZ={point}, HP={hp}")
    fixture = Path(__file__).resolve().parents[1] / "tests/fixtures/cs2-train-retake.json.gz"
    train = json.loads(gzip.decompress(fixture.read_bytes()))
    # Atrix vs Lazer Cats, seed 41000, tick 305 on f3948fe. No living CT
    # knows the device location at this historical point of the real match.
    assert train["phase"]=="planted" and all(not a["seenDevice"] for a in train["agents"] if a["team"]=="CT")
    while train["phase"]=="planted" and train["tick"]<710:
        match.advance(train)
    if not train["history"] or train["history"][0]["reason"] != "Обезвреживание":
        failures.append("Train: защита не завершила ретейк из воспроизводимого эпизода")
    else:
        print("de_train: защита нашла скрытую C4 и разминировала в записанном эпизоде")
    if failures:
        raise ValueError("\n".join(failures))


if __name__ == "__main__":
    main()
