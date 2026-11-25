from backend.cs2_navigation import Navigation, surface_height
from backend.cs2_sites import BombSites, Solid


def area(ident, x, y, z, width=20):
    return dict(id=ident, corners=[[x, y, z], [x + width, y, z],
                [x + width, y + 20, z], [x, y + 20, z]],
                edges=[[], [], [], []], up=[], down=[], cover=[])


def test_stacked_floors_only_connect_at_a_real_ladder():
    lower, upper = area(7, 0, 0, 0), area(9, 0, 0, 128)
    data = dict(format=1, space="Hammer XYZ", areas=[lower, upper], ladders=[])
    nav = Navigation(data)
    assert nav.locate((8, 8, 5), 12) == 7
    assert nav.locate((8, 8, 129), 12) == 9
    assert nav.locate((8, 8, 64), 12) is None
    assert nav.route(7, 9) is None
    lower["up"] = [12]
    data["ladders"] = [dict(id=12, bottom=[3, 1, 0], top=[3, 1, 128], below=[7], above=[9])]
    nav = Navigation(data)
    step, = nav.route(7, 9)
    assert (step.enter, step.leave, step.ladder) == ((3, 1, 128), (3, 1, 0), 12)
    assert nav.route(9, 7) is None


def test_split_portal_and_ramp_use_the_connected_part_of_the_edge():
    a, b = area(1, 0, 0, 0, width=100), area(2, 75, 20, 0)
    a["edges"][2] = [dict(to=2, edge=0)]
    b["corners"][2][2] = b["corners"][3][2] = 10
    nav = Navigation(dict(format=1, space="Hammer XYZ", areas=[a, b], ladders=[]))
    crossing, = nav.route(1, 2)
    assert crossing.leave == crossing.enter == (85, 20, 0)
    assert surface_height(b["corners"], 85, 30) == 5
    assert nav.route(1, 2, avoided={2}) is None


def tetrahedron(z):
    return dict(vertices=[[0, 0, z], [10, 0, z], [0, 10, z], [0, 0, z + 10]],
                triangles=[[0, 2, 1], [0, 1, 3], [1, 2, 3], [0, 3, 2]])


def test_plant_uses_the_brush_volume_including_boundaries():
    sites = BombSites([dict(site="A", solids=[tetrahedron(0)]),
                       dict(site="B", solids=[tetrahedron(128)])])
    assert sites.at((1, 1, 1)) == "A"
    assert sites.at((1, 1, 129)) == "B"
    assert sites.at((1, 1, 64)) is None
    assert sites.at((8, 8, 1)) is None
    assert Solid(tetrahedron(0)).contains((5, 5, 0))


def test_floor_probe_reads_face_materials_and_transformed_primitives(tmp_path):
    import json
    import struct
    from tools.cs2_floor_probe import trace_probes

    # Two faces share a mesh. The second is vertical and overlaps the probe.
    points = [(0, 0, 0), (8, 0, 8), (0, 8, 0),
              (2, 0, 10), (2, 4, 10), (2, 2, 20)]
    (tmp_path / "collision.bin").write_bytes(b"".join(struct.pack("<3f", *p) for p in points)
                                            + struct.pack("<6i2I", *range(6), 9, 10))
    primitive = dict(kind="capsule", centers=[[0, 0, 0], [2, 0, 0]], radius=1,
                     transform=[0, 1, 0, -1, 0, 0, 0, 0, 2, 2, 1, 28],
                     material=9, tags=["solid"], entity="prop_dynamic")
    metadata = dict(format=1, missingModels=[], primitives=[primitive], surfaces={9: "wood", 10: "metal"},
                    blocks=[dict(offset=0, vertices=6, triangles=2, perFace=True, material=10,
                                 group="default", tags=["solid"], entity="world")])
    (tmp_path / "collision.json").write_text(json.dumps(metadata))
    rays = [dict(x=2, y=2, bottom=1, top=29), dict(x=8, y=8, bottom=0, top=29)]
    trace_probes(tmp_path, rays)
    assert [(hit["surface"], hit["z"]) for hit in rays[0]["physicalHits"]] == [
        ("wood", [2, 2]), ("metal", [10, 20]), ("wood", [26, 29])]
    assert rays[1]["physicalHits"] == []

    from backend.cs2_collision import Collision, SIGHT, THROW
    runtime = Collision(tmp_path)
    segments = [((2,2,25),(2,2,31)), ((8,8,-2),(8,8,24)), ((2,2,21),(2,2,22))]
    bulk = runtime.sight_many(segments)
    assert bulk == {segment: runtime.trace(*segment,SIGHT) is None for segment in segments}
    assert [bulk[s] for s in segments] == [False, True, True]
    hit = runtime.trace(*segments[0],THROW)
    assert hit[1] == "wood" and abs(hit[0]-1/6)<1e-6


def test_tactical_route_requires_a_single_ordered_path():
    areas = [area(i, (i - 1) * 20, 0, 0) for i in range(1, 6)]
    for start, end in ((1, 2), (1, 3), (3, 4), (4, 5)):
        areas[start - 1]["edges"][1].append(dict(to=end, edge=3))
    nav = Navigation(dict(format=1, space="Hammer XYZ", areas=areas, ladders=[]))
    routes = nav.routes_through([{2, 3}, {4}, {5}])
    path, selected = routes.route(1)
    assert selected == [3, 4, 5]
    assert path == nav.route(1, 5)
    assert routes.route(2) is None
    assert routes.route(3)[1] == selected
    assert nav.routes_through([{4}, {3}, {5}]).route(1) is None


def test_reviewed_positions_require_the_bound_nav_version():
    import pytest
    from tools.check_cs2_playable_areas import resolve_anchors

    markers = {"Middle": [dict(area=10)], "B": [dict(area=11)]}
    profile = {"navAnchors": {"sha256": "dated-nav", "places": {"Middle": [12]}}}
    nav = Navigation(dict(format=1, space="Hammer XYZ", ladders=[],
                          areas=[area(10, 0, 0, 128), area(11, 20, 0, 0), area(12, 0, 0, 0)]))
    assert resolve_anchors(profile, markers, nav, "dated-nav") == {"Middle": {12}, "B": {11}}
    with pytest.raises(ValueError, match="Версия NAV"):
        resolve_anchors(profile, markers, nav, "different-nav")


def test_portal_can_be_crossed_away_from_its_obstructed_midpoint():
    from backend.cs2_maps import Map

    first,second = area(1,0,0,0),area(2,20,0,0)
    first["edges"][1] = [dict(to=2,edge=3)]
    nav=Navigation(dict(format=1,space="Hammer XYZ",areas=[first,second],ladders=[]))
    space=Map.__new__(Map)
    space.to_sim=lambda p:tuple(p)
    space.world=lambda p:p
    space.centers=nav.centers
    space.nav=nav
    space.ladder_mounts=set()
    # A narrow prop occupies the central part of the portal.
    def crosses(a,b,climbing=False):
        if a==b:
            return True
        return not any(17<x<23 and 7<y<13 for x,y,_ in
                       (tuple(s+(e-s)*t/30 for s,e in zip(a,b)) for t in range(31)))
    space.passage=crosses
    space.inside=space._inside
    space.gate=space._gate
    space.route=nav.route
    points=space._path(1,(10,10,0),2,(30,10,0),frozenset())
    assert points is not None and points[-1] == (30,10,0,2)
    route=[(10,10,0),*(p[:3] for p in points)]
    assert all(crosses(a,b) for a,b in zip(route,route[1:]))
    assert any(abs(p[0]-20)<1e-8 and abs(p[1]-10)>3 for p in points)


def test_disabled_source_entity_does_not_block_runtime_rays(tmp_path):
    import json
    import struct
    from backend.cs2_collision import Collision, MOVEMENT

    raw=b"".join(struct.pack("<3f",*p) for p in ((0.,0.,0.),(10.,0.,0.),(0.,10.,0.)))
    raw+=struct.pack("<3i",0,1,2)
    (tmp_path/"collision.bin").write_bytes(raw*2)
    block=dict(offset=0,vertices=3,triangles=1,material=11,perFace=False,group="default",tags=["solid"])
    data=dict(format=1,missingModels=[],primitives=[],surfaces={11:"metal"},instances=[dict(id=0,active=False)],
              blocks=[dict(block,instance=0),dict(block,offset=len(raw),tags=["csgo_grenadeclip"])])
    (tmp_path/"collision.json").write_text(json.dumps(data))
    scene=Collision(tmp_path)
    assert scene.trace((1,1,-3),(1,1,3),MOVEMENT) is None


def test_guard_selects_a_position_with_sight_of_the_approach():
    from types import SimpleNamespace
    from backend.cs2_maps import Map

    anchor = (0, 0, 0)
    cover = (0, 5, 0)
    portal = (20, 10, 0)
    space = SimpleNamespace(
        ingress=lambda *args: [portal],
        cover=[(2, cover)],
        nearby_areas=lambda *args: [1, 2],
        centers={1: anchor, 2: cover},
        hit=lambda start, *_: None if start == cover else (0.1, "stone", None),
        _watch=lambda *_: portal,
    )
    assert Map._angles(space, "A", 0, anchor)[0] == (cover, portal)


def test_squad_reassigns_dropped_c4_by_accessible_route():
    from types import SimpleNamespace
    from backend.cs2_play import rescue

    goal = (7, 1, 0)
    bomb = dict(x=7, y=1, z=0, carrier=None, site=None)
    squad = [
        dict(id=i, slot=i, navArea=i, x=x, y=1, z=0)
        for i, x in enumerate((8, 2, 0))
    ]
    space = SimpleNamespace(
        use_position=lambda actor, *_: goal if actor["slot"] else None,
        locate=lambda _: 3,
        path=lambda *_: [(*goal, 3)],
    )
    assert rescue(space, squad, bomb)["player"] == 1
    assert rescue(space, squad[2:], bomb)["player"] == 2
    bomb["carrier"] = 2
    assert rescue(space, squad, bomb) is None and "recovery" not in bomb
