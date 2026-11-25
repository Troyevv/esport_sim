"""Check source spawns, named tactical routes and target volumes on directed NAV."""

import argparse
from collections import defaultdict
import json
from math import dist
from pathlib import Path

from backend.cs2_navigation import Navigation, surface_height
from backend.cs2_sites import BombSites


def approaches(previous, stages):
    """Areas from which at least one choice in each ordered stage can be visited."""
    reachable = set()
    for index, choices in enumerate(reversed(stages)):
        reachable = set(choices) if index == 0 else reachable.intersection(choices)
        todo = list(reachable)
        while todo:
            for other in previous[todo.pop()]:
                if other not in reachable:
                    reachable.add(other)
                    todo.append(other)
    return reachable


def named_stages(data, nav, profile):
    names = {name for site in ("A", "B") for route in profile[site] for name in route}
    names.update(name for guards in profile["guards"].values() for name in guards)
    names.add(profile["middle"])
    markers = defaultdict(list)
    for place in data["places"]:
        name = place["name"]
        if name not in names:
            continue
        # env_cs_place is a label origin, not a walkable waypoint. Record
        # the distance to its representative NAV surface for human review.
        position = place["position"]
        ident = nav.locate(position, 96)
        if ident is None:
            ident = min(nav.centers, key=lambda i: (dist(position, nav.centers[i]), i))
            offset = dist(position, nav.centers[ident])
        else:
            offset = abs(position[2] - surface_height(nav.areas[ident]["corners"], *position[:2]))
        markers[name].append(dict(area=ident, offset=round(offset, 2)))
    missing = names.difference(markers)
    if missing:
        raise ValueError(f"{data['map']}: неизвестные позиции {sorted(missing)}")
    return dict(sorted(markers.items()))


def measure(data, profile):
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
    previous = defaultdict(set)
    for area, links in nav.links.items():
        for link in links:
            previous[link.area].add(area)
    reached = {site: approaches(previous, [goals]) for site, goals in plant_areas.items()}
    markers = named_stages(data, nav, profile)
    places = {name: {row["area"] for row in rows} for name, rows in markers.items()}
    result = {}
    routes = []

    def check(side, kind, labels, final=()):
        stages = [places[label] for label in labels] + list(final)
        starts = approaches(previous, stages)
        routes.append(dict(side=side, kind=kind, via=labels,
                           reachable=sum(area in starts for area in found),
                           enabled=len(found)))

    for side in ("T", "CT"):
        spawns = [s for s in data["spawns"] if s["side"] == side and s["enabled"]]
        found = [nav.locate(s["position"], 96) for s in spawns]
        result[side] = dict(enabledSpawns=len(found), onNav=sum(i is not None for i in found),
                            reachableA=sum(i in reached["A"] for i in found),
                            reachableB=sum(i in reached["B"] for i in found),
                            reachableBoth=sum(i in reached["A"] and i in reached["B"] for i in found))
        for site, goals in plant_areas.items():
            if side == "T":
                for route in profile[site]:
                    check(side, "plant" + site, route, [goals])
            else:
                for name in profile["guards"][site]:
                    check(side, "guard" + site, [name])
        check(side, "middle", [profile["middle"]])
    return {
        "spawnRoutes": result, "sampledPlantAreas": {k: len(v) for k, v in plant_areas.items()},
        "ladders": len(data["ladders"]),
        "namedPlaces": len({p["name"] for p in data["places"] if p["name"]}),
        "hidingSpots": sum(len(a["cover"]) for a in nav.areas.values()),
        "profileMarkers": markers, "profileRoutes": routes,
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
        result = measure(data, profiles[name])
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
