"""Measure the real NAV graph and static LOS from an imported CS2 source release."""

import argparse
import json
from math import dist
from pathlib import Path

from awpy import NavMesh, VisibilityChecker


def measure(folder):
    nav = NavMesh(folder / f"{folder.name}.nav")
    mesh = folder / f"{folder.name}.mesh"
    visibility = VisibilityChecker(mesh) if mesh.is_file() else None
    areas = {
        a["area_id"]: nav.area(a["area_id"])
        for a in nav.areas.iter_rows(named=True)
        if a["hull_index"] == 0
    }
    if not areas:
        raise ValueError(f"{folder.name}: отсутствуют области основного hull")
    start = min(areas)
    seen = {start}
    pending = [start]
    while pending:
        for other in areas[pending.pop()]["connections"]:
            if other in areas and other not in seen:
                seen.add(other)
                pending.append(other)
    origin = areas[start]["centroid"]
    goal = max(sorted(seen), key=lambda i: dist(origin, areas[i]["centroid"]))
    route = nav.find_path(start, goal)
    if not route or route[0] != start or route[-1] != goal:
        raise ValueError(f"{folder.name}: маршрут до связанной области потерян")
    for here, there in zip(route, route[1:]):
        if there not in nav.neighbors(here):
            raise ValueError(f"{folder.name}: переход вне NAV {here} → {there}")

    # Probe two physical surfaces at the same XY. Projecting to a higher
    # query point alone does not establish the presence of an upper floor.
    upper_lower = set()
    blocked = 0 if visibility is not None else None
    for ident, area in areas.items():
        x, y, z = area["centroid"]
        if nav.find_area((x, y, z)) != ident:
            continue
        for dz in (128, 256, 512, 1024):
            other = nav.find_area((x, y, z + dz))
            if other not in areas or other == ident:
                continue
            top = surface_height(areas[other]["corners"], x, y)
            if top is None or top - z < 96:
                continue
            pair = (ident, other)
            if pair in upper_lower:
                continue
            upper_lower.add(pair)
            if visibility is not None:
                blocked += visibility.is_occluded((x, y, z + 64), (x, y, top + 64))
    return {
        "playerHullAreas": len(areas),
        "reachableFromFirstArea": len(seen),
        "startArea": start, "goalArea": goal, "routeAreas": len(route),
        "areasWithLadderReferences": sum(
            bool(a["ladders_above"] or a["ladders_below"]) for a in areas.values()
        ),
        "sameXYAreaPairsSampled": len(upper_lower),
        "sameXYOccluded": blocked,
        "staticOccluderTriangles": visibility.triangle_count if visibility else None,
    }


def surface_height(corners, x, y):
    """Height on a convex NAV polygon, including slopes and edge points."""
    ax, ay, az = corners[0]
    for b, c in zip(corners[1:], corners[2:]):
        bx, by, bz = b
        cx, cy, cz = c
        det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(det) < 1e-8:
            continue
        u = ((x - ax) * (cy - ay) - (y - ay) * (cx - ax)) / det
        v = ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / det
        if min(u, v, 1 - u - v) >= -1e-7:
            return az + u * (bz - az) + v * (cz - az)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--require-all-meshes", action="store_true")
    args = parser.parse_args()
    inventory = json.loads((args.root / "inventory.json").read_bytes())
    failures = []
    for map_id, source in inventory["maps"].items():
        if not (source["overview"] and source["navVersion"]
                and f"{map_id}.png" in source["radars"]):
            failures.append(f"{map_id}: не хватает исходных данных")
            continue
        counts = measure(args.root / map_id)
        print(map_id, json.dumps(counts, ensure_ascii=False), flush=True)
        if args.require_all_meshes and counts["staticOccluderTriangles"] is None:
            failures.append(f"{map_id}: отсутствует сетка видимости")
        if map_id in ("de_nuke", "de_vertigo") and not counts["sameXYOccluded"]:
            failures.append(f"{map_id}: ни одного подтверждённого перекрытия этажей")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
