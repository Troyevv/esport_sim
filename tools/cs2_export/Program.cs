using System.Numerics;
using System.Text.Json;
using ValvePak;
using ValveResourceFormat.IO;
using ValveResourceFormat.NavMesh;
using ValveResourceFormat.ResourceTypes;
using ValveResourceFormat.Serialization.KeyValues;
using Hull = ValveResourceFormat.ResourceTypes.RubikonPhysics.Shapes.Hull;

if (args is ["model-list", var maps, var list]) return Dependencies.Find(maps, list);
if (args is ["chunk-list" or "unpack", var index, var names, var result])
    return Dependencies.ReadPackage(index, names, result, args[0] == "unpack");
if (args.Length != 2)
{
    Console.Error.WriteLine("Cs2Export <map.vpk> <output.json>");
    return 2;
}

var path = Path.GetFullPath(args[0]);
var map = Path.GetFileNameWithoutExtension(path);
using var package = new Package();
package.Read(path);
using var loader = new GameFileLoader(package, path);
loader.AddDiskPathToSearch(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(path)!, "..")));
var navigation = new NavMeshFile();
using (var input = loader.GetFileStream($"maps/{map}.nav")
    ?? throw new InvalidDataException($"Missing NAV for {map}"))
{
    navigation.Read(input);
}

var areas = new List<object>();
foreach (var area in navigation.Areas.Values.OrderBy(a => a.AreaId))
{
    if (area.HullIndex != 0) continue;
    var transform = area.MovableMeshId == NavMeshFile.NoMovableMesh
        ? Matrix4x4.Identity : navigation.MovableMeshTransforms[area.MovableMeshId];
    areas.Add(new {
        id = area.AreaId,
        corners = area.Corners.Select(point => Point(Vector3.Transform(point, transform))),
        edges = area.Connections.Select(edge => edge
            .Where(c => navigation.GetArea(c.AreaId)?.HullIndex == 0)
            .Select(c => new { to = c.AreaId, edge = c.EdgeId })),
        up = area.LaddersAbove, down = area.LaddersBelow,
        cover = area.HidingSpots.Select(s => new {
            position = Point(Vector3.Transform(s.Position, transform)), flags = (int)s.Flags
        })
    });
}

var ladders = navigation.Ladders.Select(l => new {
    id = l.Id, top = Point(l.Top), bottom = Point(l.Bottom), width = l.Width,
    above = Ids(l.TopForwardArea, l.TopLeftArea, l.TopRightArea, l.TopBehindArea),
    below = Ids(l.BottomArea, l.BottomLeftArea, l.BottomRightArea)
});
var destination = Path.GetDirectoryName(Path.GetFullPath(args[1]))!;
using var collision = new Physics(Path.Combine(destination, "collision.bin"));
collision.Model(loader, $"maps/{map}/world_physics.vmdl", Matrix4x4.Identity, "world", true);
var spawns = new List<object>();
var targets = new List<object>();
var places = new List<object>();
var classes = new SortedDictionary<string, int>();
using var worldFile = loader.LoadFileCompiled($"maps/{map}/world.vwrld");
var world = worldFile?.DataBlock as World ?? throw new InvalidDataException("Missing world");
foreach (var name in world.GetEntityLumpNames())
{
    using var file = loader.LoadFileCompiled(name);
    var lump = file?.DataBlock as EntityLump ?? throw new InvalidDataException(name);
    foreach (var (entity, parent, _) in EntityLumpTraversal.EnumerateEntities(
        lump, loader, Matrix4x4.Identity, missing => throw new InvalidDataException(missing)))
    {
        var kind = entity.GetStringProperty("classname");
        if (string.IsNullOrEmpty(kind)) continue;
        classes[kind] = classes.GetValueOrDefault(kind) + 1;
        var pose = EntityTransformHelper.ToTransformationMatrix(entity) * parent;
        var position = Point(pose.Translation);
        if (Dependencies.IsPlacedCollision(kind))
        {
            var nameOfModel = entity.GetStringProperty("model");
            if (!string.IsNullOrEmpty(nameOfModel))
                collision.Model(loader, nameOfModel, pose, kind);
        }
        if (kind is "info_player_terrorist" or "info_player_counterterrorist")
        {
            var facing = Vector3.Normalize(Vector3.TransformNormal(Vector3.UnitX, pose));
            spawns.Add(new { side = kind == "info_player_terrorist" ? "T" : "CT",
                position, heading = Math.Atan2(facing.Y, facing.X),
                priority = entity.GetInt32Property("priority"),
                enabled = entity.GetBooleanProperty("enabled", true) });
        }
        if (kind == "env_cs_place")
        {
            places.Add(new { name = entity.GetStringProperty("place_name"), position });
        }
        if (kind == "func_bomb_target")
        {
            var model = entity.GetStringProperty("model");
            using var modelFile = loader.LoadFileCompiled(model);
            var brush = modelFile?.DataBlock as Model ?? throw new InvalidDataException(model);
            var solids = new List<Solid>();
            var embedded = brush.GetEmbeddedPhys();
            if (embedded != null) solids.AddRange(Volumes(embedded, pose));
            foreach (var refName in brush.GetReferencedPhysNames())
            {
                using var physFile = loader.LoadFileCompiled(refName);
                var phys = physFile?.DataBlock as PhysAggregateData
                    ?? throw new InvalidDataException(refName);
                solids.AddRange(Volumes(phys, pose));
            }
            if (solids.Count == 0) throw new InvalidDataException($"Empty bomb target {model}");
            var site = entity.GetInt32Property("bomb_site_designation") switch
            {
                0 => "A", 1 => "B", var value => throw new InvalidDataException($"Bomb site {value}")
            };
            targets.Add(new { site, model, position, solids });
        }
    }
}
collision.Finish(Path.Combine(destination, "collision.json"));
var data = new { format = 1, map, space = "Hammer XYZ", areas, ladders, spawns, targets, places, classes };
using (var output = File.Open(args[1], FileMode.CreateNew))
{
    JsonSerializer.Serialize(output, data);
}
return 0;

static float[] Point(Vector3 p) => [p.X, p.Y, p.Z];

static uint[] Ids(params NavMeshArea?[] candidates) =>
    candidates.OfType<NavMeshArea>().Where(a => a.HullIndex == 0).Select(a => a.AreaId).Distinct().ToArray();

static List<Solid> Volumes(PhysAggregateData physics, Matrix4x4 placement)
{
    var solids = new List<Solid>();
    var binds = physics.BindPose;
    for (var i = 0; i < physics.Parts.Length; i++)
    {
        var shape = physics.Parts[i].Shape;
        var transform = binds.Length == 0 ? placement : binds[i] * placement;
        foreach (var hull in shape.GetAllHulls())
        {
            var verts = hull.Shape.GetVertexPositions().ToArray();
            var edges = hull.Shape.GetEdges();
            var indices = new List<int[]>();
            foreach (var face in hull.Shape.GetFaces())
            {
                foreach (var triangle in Hull.GetFaceTriangles(edges, face))
                    indices.Add([triangle.A, triangle.B, triangle.C]);
            }
            solids.Add(new Solid(verts.Select(p => Point(Vector3.Transform(p, transform))).ToArray(), indices));
        }
        foreach (var mesh in shape.GetAllMeshes())
        {
            var verts = mesh.Shape.GetVertices().ToArray();
            var indices = mesh.Shape.GetTriangles().ToArray().Select(t => new[] {t.X, t.Y, t.Z}).ToList();
            solids.Add(new Solid(verts.Select(p => Point(Vector3.Transform(p, transform))).ToArray(), indices));
        }
        if (shape.GetAllSpheres().Any() || shape.GetAllCapsules().Any())
            throw new InvalidDataException("Bomb target contains a non-polyhedral shape");
    }
    return solids;
}

record Solid(float[][] vertices, List<int[]> triangles);
