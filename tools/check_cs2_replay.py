"""Replay four cross-CPU checkpoints and an observed Train retake with a hidden plant."""

import gzip
import json
import random
from math import dist

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
        ("de_dust2", 1450, 0, (64.08, 177.21, 2.84), 100),
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
    train = match.initial(seed, database.match_input(pack, pair), pair, map_id="de_train")
    while not train["history"] and train["tick"] < 1400:
        match.advance(train)
    if not train["history"] or train["history"][0]["reason"] != "Обезвреживание":
        failures.append("Train: защита не завершила ретейк из воспроизводимого эпизода")
    else:
        print("de_train: доступная позиция для разминирования, первый раунд выиграла защита")
    if failures:
        raise ValueError("\n".join(failures))


if __name__ == "__main__":
    main()
