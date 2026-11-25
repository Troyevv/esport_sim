"""Check four observed cross-CPU divergences on the same dated teams and map inputs."""

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
        ("de_cache", 250, 0, (154.87, 212.60, 136.96), 100),
        ("de_nuke", 190, 1, (313.44, 329.70, -32.36), 100),
        ("de_dust2", 1450, 0, (323.29, 146.12, -0.54), 81),
    )
    for name, tick, slot, point, hp in samples:
        state = match.initial(seed, database.match_input(pack, pair), pair, map_id=name)
        for _ in range(tick):
            match.advance(state)
        actor = state["agents"][slot]
        position = cs2_maps.xyz(actor)
        if dist(position, point) > 0.02 or actor["hp"] != hp:
            raise ValueError(f"{name}, tick={tick}, {actor['id']}: XYZ={position}, HP={actor['hp']}")
        print(f"{name}: tick {tick}, {actor['id']}, XYZ={point}, HP={hp}")


if __name__ == "__main__":
    main()
