from concurrent.futures import ThreadPoolExecutor
from itertools import product
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cs2_collision import Collision, Primitive
from backend.cs2_maps import Map
from backend.cs2_rays import TriangleScene

native = pytest.importorskip("backend._match_native")
from backend.native_physics import NativeCollision, NativePhysicalMap, NativeMovementMap


def collision(cls, vertices, faces, masks, shapes=()):
    obj = object.__new__(cls)
    scene = TriangleScene if cls is Collision else native.TriangleScene
    obj.scene = scene(np.asarray(vertices, np.float32).reshape(-1, 3),
                      np.asarray(faces, np.int32).reshape(-1, 3), np.array(masks, np.uint8))
    obj.materials = ["wood", "metal", "plastic"]
    obj.material = np.zeros(len(faces), np.uint16)
    obj.shapes = shapes
    obj._finish_geometry()
    return obj


def shape(center, length, mask):
    # Non-uniform transform, shear and a translation exercise inverse-transpose normals.
    desc = dict(transform=[2, .5, 0, 0, 1, 0, 0, 0, .5, *center],
                centers=[[0., 0., 0.], [0., 0., length]], radius=2., tags=["solid"])
    instance = Primitive(desc, "metal" if length else "plastic")
    instance.mask = mask
    return instance


def test_analytic_contacts_and_mesh_ties_match_reference():
    shapes = [shape((i*12., 0., 0.), 6. if i%2 else 0., 31 if i%3 else 8) for i in range(10)]
    points = [(-10., -8., 0.), (130., -8., 0.), (-10., 8., 0.)]
    ref, candidate = [collision(cls, points, [[0, 1, 2]], [15], shapes)
                      for cls in (Collision, NativeCollision)]
    segments = [(tuple(x+d for x,d in zip((i*12.,0.,z), off)), (i*12.+.25, .5, z))
                for i,z,off in product(range(10), (-1., 0., 1., 2., 3.),
                                       [(7., 0., 0.), (0., -4., 0.), (0., .5, 8.)])]
    segments += [(b,a) for a,b in segments] + [(points[0], points[0])]
    for a,b in segments:
        for ch in (1, 2, 4, 8, 16):
            expected, actual = ref.trace(a,b,ch,True), candidate.trace(a,b,ch,True)
            if expected is None:
                assert actual is None
            else:
                assert actual[0] == pytest.approx(expected[0], abs=2e-14)
                assert actual[1] == expected[1]
                if expected[2] is None:
                    assert actual[2] is None
                else:
                    np.testing.assert_allclose(actual[2], expected[2], rtol=2e-14, atol=2e-14)
    assert candidate.sight_many(segments) == ref.sight_many(segments)


def corridor(cls):
    # Central wall blocks the main portal lane. The +Y lane is traversable.
    obj = object.__new__(cls)
    obj.overview = dict(pos_x=0, pos_y=0)
    wall = [(24,-7,0),(24,7,0),(24,7,70),(24,-7,70)]
    obj.collision = collision(NativeCollision if issubclass(cls, NativePhysicalMap) else Collision,
                              wall, [[0,1,2],[0,2,3]], [2,2])
    areas = {1: dict(corners=[[-36,-36,0],[24,-36,0],[24,36,0],[-36,36,0]]),
             2: dict(corners=[[24,-36,0],[84,-36,0],[84,36,0],[24,36,0]])}
    cross = SimpleNamespace(area=2, leave=(22,0,0), enter=(26,0,0), ladder=None,
                            alternatives=[((22,18,0),(26,18,0))])
    obj.nav = SimpleNamespace(areas=areas, links={1:[cross], 2:[]})
    obj.centers = {1:(-.5,0.,0.), 2:(4.5,0.,0.)}
    obj.ladder_mounts = set()
    obj.nav.graph = native.PortalGraph(obj.centers, [(1,2,5)])
    obj.nav.surfaces = native.NavSurfaces([(a,d["corners"]) for a,d in areas.items()])
    obj.nav.route = lambda a,b,avoided: None if b in avoided else obj.route(a,b)
    obj.route = lambda a,b: [cross] if (a,b)==(1,2) else ([] if a==b else None)
    obj.locate = lambda p: obj.nav.surfaces.locate_many([obj.world(p)],96)[0]
    obj.exits, obj.gate = obj._exits, obj._gate
    obj.passage, obj.inside = obj._passage, obj._inside
    return obj


def test_ordered_lanes_escape_and_ownership():
    old, new = corridor(Map), corridor(NativePhysicalMap)
    start, goal = old.centers[1], old.centers[2]
    expected = old._path(1,start,2,goal,set())
    assert expected[1] == (*old.to_sim((26,18,0)), 2)
    assert new._path(1,start,2,goal,set()) == expected
    assert new._path(2,goal,1,start,set()) is None
    assert new._path(1,start,2,goal,{2}) is None
    assert new._physical_exit(1,start,(-81.,0.,0.)) == old._physical_exit(1,start,(-81.,0.,0.))
    planner = new.planner
    del new
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(val == list(expected) for val in pool.map(
            lambda _: planner.path(1,start,2,goal,set()), range(24)))


def test_invalid_physical_input():
    planner = corridor(NativePhysicalMap).planner
    with pytest.raises(ValueError):
        planner.path(1, (np.nan,0.,0.), 2, (5.,0.,0.), set())
    with pytest.raises(ValueError):
        native.CollisionWorld(corridor(NativePhysicalMap).collision.scene, np.zeros(0,np.uint16), [])


def test_persistent_motion_matches_mid_portal_restore_and_fire_wait():
    from copy import deepcopy

    reference, candidate = corridor(Map), corridor(NativeMovementMap)
    reference.path = reference._path
    # The two NAV centers are outside the intervening flame.
    reference.nearby_areas = lambda p, r: []
    actor = dict(x=-.5,y=0.,z=0.,navArea=1,heading=1.,path=[],dest=[],blockedTicks=7,status="Ход")
    old, new = deepcopy(actor), deepcopy(actor)
    goal = reference.centers[2]
    fire = dict(x=1., y=-.75, z=0.,radius=.6)
    for dest, pace, hazards in [(goal,.7,[]), (goal,3.,[fire]), (goal,2.2,[]),
                                (reference.centers[1],.1,[]), (goal,2.,[]), (goal,8.,[]),
                                ((100.,100.,0.),1.,[]), (goal,1.,[])]:
        assert candidate.walk(new,dest,pace,hazards) == reference.walk(old,dest,pace,hazards)
        assert old == new
    assert new["navArea"] == 2
    assert not new["path"]


def test_grenade_trajectory_including_terminal_mesh_contact():

    old, new = corridor(Map), corridor(NativeMovementMap)
    wall = [(24.,-70.,-5.), (24.,70.,-5.), (24.,70.,120.), (24.,-70.,120.)]
    old.collision = collision(Collision, wall, [[0,1,2],[0,2,3]], [8,8])
    new.collision = collision(NativeCollision, wall, [[0,1,2],[0,2,3]], [8,8])
    origin = (-1.,0.,0.)
    for goal in ((2.,0.,3.), (4.,.5,0.), (1.,-1.,2.)):
        expected = old.grenade(origin,goal,6)
        assert new.grenade(origin,goal,6) == expected
        assert len(expected[-1]) == 7
