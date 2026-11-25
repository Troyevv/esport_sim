"""Check real spawn-to-site routes and area links against each extracted map."""

import argparse
import json
from pathlib import Path

from backend.cs2_navigation import Navigation, surface_height
from backend.cs2_sites import BombSites


def measure(data):
    nav = Navigation(data)
    sites = BombSites(data["targets"])
    plant_areas = {"A": set(), "B": set()}
    for ident, position in nav.centers.items():
        x, y, _ = position
        z = surface_height(nav.areas[ident]["corners"], x, y)
        if z is None:
            continue
        site = sites.at((x, y, z + 1))
        if site:
            plant_areas[site].add(ident)
    result = {}
    for side in ("T", "CT"):
        spawns = [s for s in data["spawns"] if s["side"] == side and s["enabled"]]
        found = [nav.locate(s["position"], 96) for s in spawns]
        details = {"enabledSpawns": len(spawns), "onNav": sum(i is not None for i in found)}
        reached_both = set(range(len(found)))
        for name, candidates in plant_areas.items():
            reachable = set()
            for index, start in enumerate(found):
                if start is None:
                    continue
                # Each count requires a route to a surface physically inside the target.
                if any(nav.route(start, goal) is not None for goal in sorted(candidates)):
                    reachable.add(index)
            details["reachable" + name] = len(reachable)
            reached_both &= reachable
        details["reachableBoth"] = len(reached_both)
        result[side] = details
    return {
        "spawnRoutes": result, "sampledPlantAreas": {k: len(v) for k, v in plant_areas.items()},
        "ladders": len(data["ladders"]),
        "namedPlaces": len({p["name"] for p in data["places"] if p["name"]}),
        "hidingSpots": sum(len(a["cover"]) for a in nav.areas.values()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worlds", type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    maps = json.loads(args.inventory.read_bytes())["maps"]
    failures = []
    for name in maps:
        data = json.loads((args.worlds / name / "gameplay.json").read_bytes())
        result = measure(data)
        print(name, json.dumps(result, sort_keys=True), flush=True)
        for side, counts in result["spawnRoutes"].items():
            if counts["reachableBoth"] < 5:
                failures.append(f"{name} {side}: меньше пяти спавнов достигают обоих плентов")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
