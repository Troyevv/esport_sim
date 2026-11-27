"""Measure Python/C++ call costs and compare batched lookup on a real NAV mesh."""
import argparse
import json
from statistics import median
from timeit import repeat

from tests.reference_kernel import cs2_maps
from backend._match_native import NavSurfaces


def per_call_us(function, count):
    return median(repeat(function, repeat=5, number=count)) * 1e6 / count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, default="de_nuke")
    args = parser.parse_args()
    nav = cs2_maps.get(args.map).nav
    surfaces = NavSurfaces([(area, data["corners"]) for area, data in nav.areas.items()])
    batch = list(nav.centers.values())[:256]
    expected = [nav.locate(p, 96) for p in batch]
    assert surfaces.locate_many(batch, 96) == expected
    print(json.dumps(dict(map=args.map, points=len(batch),
                          emptyCallUs=per_call_us(lambda: surfaces.locate_many([], 96), 50000),
                          scalarBatchUs=per_call_us(lambda: [surfaces.locate_many([p], 96)[0] for p in batch], 100),
                          nativeBatchUs=per_call_us(lambda: surfaces.locate_many(batch, 96), 100),
                          pythonBatchUs=per_call_us(lambda: [nav.locate(p, 96) for p in batch], 100)),
                     indent=2))


if __name__ == "__main__":
    main()
