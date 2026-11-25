"""Check source spawns, named tactical routes and target volumes on directed NAV."""

import argparse
import json
from pathlib import Path

from backend.cs2_navigation import Navigation, surface_height
from backend.cs2_sites import BombSites


from backend.cs2_profiles import named_stages, resolve_anchors


def measure(data, profile, nav_sha256):
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
    reached = {site: nav.routes_through([goals]).costs for site, goals in plant_areas.items()}
    markers = named_stages(data, nav, profile)
    places = resolve_anchors(profile, markers, nav, nav_sha256)
    result = {}
    routes = []

    for side in ("T", "CT"):
        spawns = [s for s in data["spawns"] if s["side"] == side and s["enabled"]]
        found = [nav.locate(s["position"], 96) for s in spawns]
        result[side] = dict(enabledSpawns=len(found), onNav=sum(i is not None for i in found),
                            reachableA=sum(i in reached["A"] for i in found),
                            reachableB=sum(i in reached["B"] for i in found),
                            reachableBoth=sum(i in reached["A"] and i in reached["B"] for i in found))
        orders = []
        for site, goals in plant_areas.items():
            if side == "T":
                orders.extend(("plant" + site, route, [goals]) for route in profile[site])
            else:
                orders.extend(("guard" + site, [name], []) for name in profile["guards"][site])
        orders.append(("middle", [profile["middle"]], []))
        for kind, labels, final in orders:
            paths = nav.routes_through([places[label] for label in labels] + final)
            starts = [i for i in found if i in paths.costs]
            row = dict(side=side, kind=kind, via=labels, reachable=len(starts), enabled=len(found))
            if starts:
                witness, waypoints = paths.route(starts[0])
                row.update(exampleStart=starts[0], selectedAreas=waypoints, crossings=len(witness),
                           maxPathUnits=round(max(paths.costs[i] for i in starts)))
            routes.append(row)
    return {
        "spawnRoutes": result, "sampledPlantAreas": {k: len(v) for k, v in plant_areas.items()},
        "ladders": len(data["ladders"]),
        "namedPlaces": len({p["name"] for p in data["places"] if p["name"]}),
        "hidingSpots": sum(len(a["cover"]) for a in nav.areas.values()),
        "profileMarkers": markers, "profileAreas": {k: sorted(v) for k, v in places.items()},
        "profileRoutes": routes,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("worlds", type=Path)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    maps = json.loads(args.inventory.read_bytes())["maps"]
    profiles = json.loads((Path(__file__).resolve().parents[1] /
                           "backend/data/maps_202611_tactics.json").read_bytes())
    failures = []
    for name in maps:
        folder = args.worlds / name
        source = json.loads((folder / "provenance.json").read_bytes())
        if source["unresolvedModels"]:
            failures.append(f"{name}: остались ссылки на отсутствующие модели")
        data = json.loads((folder / "gameplay.json").read_bytes())
        result = measure(data, profiles[name], source["navSha256"])
        print(name, json.dumps(result, sort_keys=True), flush=True)
        for side, counts in result["spawnRoutes"].items():
            if counts["enabledSpawns"] < 5 or counts["reachableBoth"] != counts["enabledSpawns"]:
                failures.append(f"{name} {side}: неполная достижимость плентов {counts}")
        for route in result["profileRoutes"]:
            if route["reachable"] != route["enabled"]:
                failures.append(f"{name}: недостижимый маршрут {route}")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
