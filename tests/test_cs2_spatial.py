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


def test_tactical_route_requires_a_single_ordered_path():
    from collections import defaultdict
    from tools.check_cs2_playable_areas import approaches

    # Spawn 1 can visit either copy of the first landmark. Only copy 3
    # leads through landmark 4 to the target. Spawn 2 is a dead end.
    previous = defaultdict(set, {2: {1}, 3: {1}, 4: {3}, 5: {4}})
    assert approaches(previous, [{2, 3}, {4}, {5}]) == {1, 3}
    assert approaches(previous, [{4}, {3}, {5}]) == set()
