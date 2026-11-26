"""Replay cross-CPU checkpoints, mirrored Anubis openers and a recorded Train retake."""

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
        ("de_vertigo", 100, 4, (78.84, 203.85, 957.67), 100),
        ("de_cache", 250, 0, (235.07, 212.22, 139.75), 100),
        ("de_nuke", 190, 1, (232.04, 333.46, -34.33), 100),
        ("de_dust2", 1450, 0, (298.13, 76.85, 10.83), 100),
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
    # An independent runner disagreed before the first plant in both fixtures.
    # Record the approach as well as the finish so a divergence can be localized.
    seed = 41002
    pair = random.Random(seed).sample(sorted(career.roster_index(pack).values()), 2)
    for teams, expected in ((pair, 514), (pair[::-1], 651)):
        state = match.initial(seed, database.match_input(pack, teams), teams, map_id="de_anubis")
        approach = []
        live = None
        while not state["history"] and state["phase"] != "planted":
            phase = state["phase"]
            match.advance(state)
            if phase == "freeze" and state["phase"] == "live":
                live = state["tick"]
            if live is not None and (state["tick"] - live) % 10 == 0:
                approach.append([state["tick"] - live, [
                    [a["navArea"], *[round(x, 3) for x in cs2_maps.xyz(a)], a["hp"], a["status"]]
                    for a in state["agents"]
                ]])
        actual = state["tick"] - live if state["phase"] == "planted" else None
        if actual != expected:
            failures.append(f"Anubis {teams}, первый плент {actual}, ожидалось {expected}")
            print("ANUBIS_APPROACH", json.dumps(approach, ensure_ascii=False))
        else:
            print(f"de_anubis: seed {seed}, {teams[0]}, установка через {actual} тиков")
    if failures:
        raise ValueError("\n".join(failures))


if __name__ == "__main__":
    main()
