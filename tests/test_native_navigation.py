from concurrent.futures import ThreadPoolExecutor
import gc
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from tests.reference_kernel.cs2_navigation import Navigation

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


def test_directed_portals_ties_and_stage_ownership():
    centers = {i: (0, 0, 0) for i in [8, 3, 5, 11, 20]}
    portals = [(8, 5, 1), (8, 3, 1), (8, 3, 1), (3, 11, 1), (5, 11, 1), (11, 20, 0)]
    graph = native.PortalGraph(centers, portals)
    assert graph.route(8, 11, set(), set()) == [1, 3]
    assert graph.route(8, 11, {3}, set()) == [0, 4]
    assert graph.route(8, 11, set(), {(8, 5), (3, 11)}) is None
    assert graph.route(8, 8, set(), set()) == []
    assert graph.route(8, 8, {8}, set()) is None
    assert graph.route(11, 8, set(), set()) is None
    assert graph.routes_through([]).route(8) == ([], [])
    assert graph.routes_through([[]]).route(8) is None
    plan = graph.routes_through([[3, 5, 999], [20]])
    del graph
    gc.collect()
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert list(pool.map(plan.route, [8] * 16)) == [([1, 3, 5], [3, 20])] * 16
    assert plan.costs() == {8: 2, 3: 1, 5: 1}


def test_portal_graph_rejects_invalid_weights_and_endpoints():
    centers = {1: (0, 0, 0), 2: (1, 2, 3)}
    for edges in ([(1, 2, -1)], [(9, 2, 2)], [(2, 1, float("nan"))]):
        with pytest.raises(ValueError):
            native.PortalGraph(centers, edges)


def test_real_routes_through_ordered_portals():
    from backend.native_navigation import NativeNavigation
    pack = Path(__file__).resolve().parents[1] / "resources/cs2/26879581/de_nuke.zip"
    with ZipFile(pack) as archive:
        data = json.loads(archive.read("gameplay.json"))
    reference, candidate = Navigation(data), NativeNavigation(data)
    ids = list(reference.areas)[::61]
    for a, b in zip(ids, reversed(ids)):
        assert candidate.route(a, b) == reference.route(a, b)
    stages = [ids[1:4], ids[7:10], ids[-3:]]
    expected, actual = reference.routes_through(stages), candidate.routes_through(stages)
    assert actual.costs == expected.costs
    for area in ids:
        assert actual.route(area) == expected.route(area)
