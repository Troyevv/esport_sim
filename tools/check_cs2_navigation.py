"""Measure the real NAV graph and static LOS from an imported CS2 source release."""

import argparse
import json
from math import dist
from pathlib import Path

from awpy import NavMesh, VisibilityChecker

from backend.cs2_navigation import surface_height


def measure(folder, world=None, comparison=None):
    nav = NavMesh(folder / f"{folder.name}.nav")
    mesh = folder / f"{folder.name}.mesh"
    visibility = VisibilityChecker(mesh) if mesh.is_file() else None
    source_mesh = VisibilityChecker(comparison) if comparison is not None else None
    if source_mesh is not None and visibility is None:
        raise ValueError(f"{folder.name}: отсутствует эталонная сетка для сравнения")
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
    open_probes = []
    upper_lower = set()
    blocked = 0 if visibility is not None else None
    source_blocked = 0
    differences = []
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
                bottom, end = (x, y, z + 64), (x, y, top + 64)
                hidden = visibility.is_occluded(bottom, end)
                blocked += hidden
                probe = dict(lowerArea=ident, upperArea=other, x=x, y=y, bottom=bottom[2], top=end[2])
                if source_mesh is not None:
                    source_hidden = source_mesh.is_occluded(bottom, end)
                    source_blocked += source_hidden
                    probe["sourceOccluded"] = source_hidden
                    if hidden != source_hidden:
                        differences.append(dict(lowerArea=ident, upperArea=other,
                                                referenceOccluded=hidden, sourceOccluded=source_hidden))
                if not hidden:
                    open_probes.append(probe)
    if world is not None and open_probes:
        from tools.cs2_floor_probe import trace_probes
        trace_probes(world, open_probes)
    return {
        **({"sourceMeshOccluded": source_blocked, "sourceMeshDifferences": differences,
            "sourceMeshTriangles": source_mesh.triangle_count} if source_mesh is not None else {}),
        "playerHullAreas": len(areas),
        "reachableFromFirstArea": len(seen),
        "startArea": start, "goalArea": goal, "routeAreas": len(route),
        "areasWithLadderReferences": sum(
            bool(a["ladders_above"] or a["ladders_below"]) for a in areas.values()
        ),
        "sameXYAreaPairsSampled": len(upper_lower),
        "sameXYOccluded": blocked,
        "openFloorProbes": open_probes if visibility is not None else None,
        "staticOccluderTriangles": visibility.triangle_count if visibility else None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--require-all-meshes", action="store_true")
    parser.add_argument("--worlds", type=Path, help="Каталог исходных коллизий cs2_world_sources")
    parser.add_argument("--compare-source", action="append", default=[], metavar="MAP",
                        help="Сравнить лучи с world_visibility.mesh из исходной физики карты")
    args = parser.parse_args()
    if args.compare_source and args.worlds is None:
        parser.error("для --compare-source нужен --worlds")
    inventory = json.loads((args.root / "inventory.json").read_bytes())
    if set(args.compare_source) - inventory["maps"].keys():
        parser.error("неизвестная карта в --compare-source")
    failures = []
    for map_id, source in inventory["maps"].items():
        if not (source["overview"] and source["navVersion"]
                and f"{map_id}.png" in source["radars"]):
            failures.append(f"{map_id}: не хватает исходных данных")
            continue
        world = args.worlds / map_id if args.worlds else None
        comparison = world / "world_visibility.mesh" if map_id in args.compare_source else None
        counts = measure(args.root / map_id, world, comparison)
        print(map_id, json.dumps(counts, ensure_ascii=False), flush=True)
        if args.require_all_meshes and counts["staticOccluderTriangles"] is None:
            failures.append(f"{map_id}: отсутствует сетка видимости")
        if map_id in ("de_nuke", "de_vertigo") and not counts["sameXYOccluded"]:
            failures.append(f"{map_id}: ни одного подтверждённого перекрытия этажей")
    if failures:
        raise SystemExit("\n".join(failures))


if __name__ == "__main__":
    main()
