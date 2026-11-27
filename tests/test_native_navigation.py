from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.cs2_navigation import Navigation

native = pytest.importorskip("backend._match_native")


def test_shared_edges_slopes_floors_and_owned_input():
    slope = [(0, 0, 0), (256, 0, 16), (256, 256, 16), (0, 256, 0)]
    areas = [(9, slope), (8, slope), (3, [(x, y, z + 64) for x, y, z in slope])]
    surfaces = native.NavSurfaces(areas)
    slope.clear()
    del areas
    gc.collect()
    points = [(128, 128, 8), (256, 0, 48), (0, 256, 64), (-1, -1, 0)]
    expected = [8, 3, 3, None]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(lambda _: surfaces.locate_many(points * 100, 32), range(24)):
            assert result == expected * 100
    assert native.NAV_API_VERSION == 1
    assert surfaces.locate_many([], 32) == []
    assert surfaces.locate_many([(128, 128, 41)], 30) == [None]


def test_invalid_geometry():
    tri = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
    for areas in ([(1, [])], [(1, tri), (1, tri)], [(2, [*tri, (0, 0, float("nan"))])]):
        with pytest.raises(ValueError):
            native.NavSurfaces(areas)
    with pytest.raises(ValueError):
        native.NavSurfaces([]).locate_many([(0, 0, float("inf"))], 10)


def test_real_stacked_surfaces_match_reference():
    pack = Path(__file__).resolve().parents[1] / "resources/cs2/26879581/de_nuke.zip"
    with ZipFile(pack) as archive:
        data = json.loads(archive.read("gameplay.json"))
    nav = Navigation(data)
    surfaces = native.NavSurfaces([(i, a["corners"]) for i, a in nav.areas.items()])
    points = [p for area in nav.areas.values() for p in area["corners"]]
    points += list(nav.centers.values())
    assert surfaces.locate_many(points, 96) == [nav.locate(p, 96) for p in points]
