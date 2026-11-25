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


def test_fifth_defender_can_reinforce_without_moving_the_anchor():
    from types import SimpleNamespace
    from backend.cs2_play import assign_backup

    pos = (7, 0, 0)
    plan = dict(lane=0, orders=dict(slots=[
        dict(site="A", hold=[0, 0, 0]),
        dict(site="B", hold=[50, 0, 0]),
        dict(site="B", hold=[60, 0, 0]),
    ]))
    squad = [dict(id=f"p{i}", slot=i, navArea=i, x=x, y=0, z=0)
             for i, x in enumerate((0, 50, 60))]
    space = SimpleNamespace(
        holds={"A": [(0, (0, 0, 0)), (3, pos)]},
        route=lambda *args: [3],
        _reachable=lambda origin, goals: goals[0],
        ingress=lambda *args: [(15, 0, 0)],
        hit=lambda *args: None,
        site_points={"A": pos},
    )
    assign_backup(space, plan, squad, "A", 2)
    assert plan["backup"]["id"] == "p1" and plan["backup"]["hold"] == list(pos)
    assign_backup(space, plan, squad, None, 0)
    assert "backup" not in plan


def test_visible_contact_can_trigger_a_reachable_reload_shelter():
    from types import SimpleNamespace
    from backend.cs2_play import seek_cover

    actor = dict(x=0, y=0, z=0, hp=65, reloadAt=20, visible=["x"], navArea=1)
    enemy = dict(x=20, y=0, z=0)
    hidden = (4, 5, 0)
    exposed = (3, 0, 0)
    space = SimpleNamespace(
        centers={1: exposed, 2: hidden}, nearby_areas=lambda *_: [1, 2], cover=[],
        hit=lambda a,*_: (0.5, "stone", None) if a == hidden else None,
        locate=lambda *_: 2, path=lambda *_: [(*hidden, 2)],
    )
    def travel(a, goal, *args, **kwargs):
        assert goal == list(hidden)
        return True
    assert seek_cover(space, actor, enemy, [actor], {"positioning":70}, 5, [], travel) == ("move", None)


def test_retaker_checks_obscured_plant_surfaces_after_hearing_the_beep():
    from types import SimpleNamespace
    from backend.cs2_play import search_site

    center = (0, 0, 0)
    behind_cover = (8, 5, 0)
    actor = dict(x=0, y=0, z=0, slot=2)
    space = SimpleNamespace(
        site_points={"B": center}, plants={"B": [1, 2]},
        centers={1: center, 2: behind_cover},
        hit=lambda a,b,*_: None if b == center else (0.5, "crate", None),
        _reachable=lambda _, points: next(iter(points), None),
    )
    assert search_site(space, actor, "B", 100) == behind_cover
    assert actor["bombSearch"]["seen"] == [1]


def test_utility_is_selected_for_a_call_and_a_contact():
    from backend import cs2_play, match_performance

    actor = dict(playingRole="support", team="T", utility=["Ложная","HE"], hp=100, reloadAt=0)
    allies = [actor, dict(utility=["Свет"], target="enemy")]
    skills = dict.fromkeys(match_performance.GRENADE_SKILL.values(), 65)
    buy = cs2_play.utility_buy(actor, allies, {"style":"Сбор"}, skills)
    assert buy[0] == "Дым" and "Ложная" not in buy
    enemy = dict(id="enemy")
    assert cs2_play.contact_utility(actor,[enemy],allies,enemy) == "HE"
    actor["utility"] = ["Ложная"]
    assert cs2_play.contact_utility(actor,[enemy],allies,enemy) is None


def test_only_corridor_reopens_after_fire_without_a_navigation_failure():
    from types import SimpleNamespace
    from backend.cs2_maps import Map

    def path(here, pos, zone, goal, avoided):
        return None if avoided else ((12, 0, 0, 3),)

    space = SimpleNamespace(locate=lambda _: 3, nearby_areas=lambda *_: [2], path=path)
    actor = dict(x=0, y=0, z=0, navArea=1, path=[], dest=None)
    fire = dict(x=6, y=0, z=0, radius=2)
    # Both ends of the requested stride are outside this fire.
    assert not Map.walk(space, actor, (12, 0, 0), 12, [fire])
    assert actor["blockedTicks"] == 0 and actor["status"].startswith("Пережидает")
    assert Map.walk(space, actor, (12, 0, 0), 12, [])
    assert actor["x"] == 12 and actor["navArea"] == 3


def test_support_rejoins_near_a_teammate_between_levels():
    from types import SimpleNamespace
    from backend.cs2_play import rendezvous

    teammate = dict(id="captain", x=24, y=0, z=4)
    support = dict(x=0, y=0, z=0)
    floor = (16, 0, 0)
    space = SimpleNamespace(
        centers={5:floor},nearby_areas=lambda *_:[5],hit=lambda *_:None,
        _reachable=lambda origin,points: next((p for p in points if p == floor),None),
    )
    assert rendezvous(space,support,teammate,100) == floor
    assert rendezvous(space,support,teammate,101) == list(floor)


def test_use_sound_does_not_reveal_a_defuser_through_distant_geometry():
    from types import SimpleNamespace
    from backend.cs2_play import hear_c4_use

    actors = [dict(x=x, y=0, z=z, hp=100, team="T") for x,z in [(4,0),(42,0),(4,65)]]
    bomb = dict(x=0,y=0,z=0)
    hear_c4_use(SimpleNamespace(hit=lambda *_:(0.4,"concrete",None)),actors,bomb,220)
    assert actors[0]["heardUse"] == 220
    assert all("heardUse" not in a for a in actors[1:])
    assert "target" not in actors[0]


def test_replan_from_a_portal_between_nav_polygons():
    from types import SimpleNamespace
    from backend.cs2_maps import Map

    start, goal = (142.32, 107.50, 988.48), (140.75, 108.04, 989.83)
    def path(area, origin, target, point, avoided):
        assert (area, origin, target, point) == (1618, start, 1834, goal)
        return (goal,)

    space = SimpleNamespace(locate=lambda p: 1834 if p == goal else None, path=path)
    assert Map._reachable(space, start, [goal], 1618) == goal


def test_coplanar_playerclip_cannot_hide_a_solid_wall(tmp_path):
    import json
    import struct
    from backend.cs2_collision import Collision, SIGHT, MOVEMENT

    vertices = b"".join(struct.pack("<3f", *p) for p in ((0, 0, 0), (10, 0, 0), (0, 10, 0)))
    triangle = vertices + struct.pack("<3i", 0, 1, 2)
    (tmp_path / "collision.bin").write_bytes(triangle * 2)
    mesh = dict(vertices=3, triangles=1, perFace=False, group="default", material=1)
    for tags in (["playerclip", "solid"], ["solid", "playerclip"]):
        blocks = [dict(mesh, offset=i * len(triangle), tags=[tag]) for i, tag in enumerate(tags)]
        data = dict(format=1, missingModels=[], primitives=[], surfaces={1:"concrete"}, blocks=blocks)
        (tmp_path / "collision.json").write_text(json.dumps(data))
        scene = Collision(tmp_path)
        above, below = (2, 2, 4), (2, 2, -4)
        for mask in (SIGHT, MOVEMENT):
            assert scene.trace(above, below, mask)[0] == 0.5
        assert not any(scene.sight_many([(above, below), (below, above)]).values())
