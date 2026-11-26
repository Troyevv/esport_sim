using System.Numerics;
using System.Runtime.InteropServices;
using System.Text.Json;
using ValveResourceFormat.IO;
using ValveResourceFormat.ResourceTypes;
using ValveResourceFormat.Serialization.KeyValues;
using ValveResourceFormat.Utils;
using Hull = ValveResourceFormat.ResourceTypes.RubikonPhysics.Shapes.Hull;

// Offsets are bytes in a little-endian file. Vertices stay in Hammer XYZ.
sealed class Physics : IDisposable
{
    private readonly FileStream output;
    private readonly List<object> blocks = [];
    private readonly Dictionary<uint, string> surfaces = [];
    private readonly List<object> primitives = [];
    public List<object> Instances { get; } = [];
    private readonly SortedSet<string> missing = [];
    public Physics(string path) => output = File.Open(path, FileMode.CreateNew);

    public void Model(GameFileLoader loader, string modelName, Matrix4x4 transform,
                      string entity, bool required = false, int instance = -1)
    {
        using var resource = loader.LoadFileCompiled(modelName);
        if (resource?.DataBlock is not Model model)
        {
            if (required) throw new InvalidDataException(modelName);
            missing.Add(modelName);
            return;
        }
        if (model.GetEmbeddedPhys() is {} embedded)
            AddPhysics(embedded, transform, entity, instance);
        foreach (var name in model.GetReferencedPhysNames())
        {
            using var external = loader.LoadFileCompiled(name);
            if (external?.DataBlock is PhysAggregateData phys)
                AddPhysics(phys, transform, entity, instance);
            else if (required)
                throw new InvalidDataException(name);
            else
                missing.Add(name);
        }
    }

    private void AddPhysics(PhysAggregateData phys, Matrix4x4 transform, string entity, int instance)
    {
        var hashes = phys.SurfacePropertyHashes;
        foreach (var hash in hashes)
            surfaces.TryAdd(hash, StringToken.GetKnownString(hash));
        var bind = phys.BindPose;
        for (var i = 0; i < phys.Parts.Length; i++)
        {
            var pose = bind.Length == 0 ? transform : bind[i] * transform;
            var shape = phys.Parts[i].Shape;
            foreach (var item in shape.GetAllMeshes())
            {
                var mesh = item.Shape;
                var triangles = mesh.GetTriangles().ToArray();
                var indices = new int[triangles.Length * 3];
                for (var j = 0; j < triangles.Length; j++)
                {
                    indices[3*j] = triangles[j].X;
                    indices[3*j+1] = triangles[j].Y;
                    indices[3*j+2] = triangles[j].Z;
                }
                var materials = mesh.Materials;
                if (materials.Length != 0 && materials.Length != triangles.Length)
                    throw new InvalidDataException("Triangle/material count mismatch");
                WriteMesh(mesh.GetVertices(), indices, materials, item.SurfacePropertyIndex,
                    item.CollisionAttributeIndex, phys, pose, entity, instance);
            }
            foreach (var item in shape.GetAllHulls())
            {
                var hull = item.Shape;
                var edges = hull.GetEdges();
                var indices = new List<int>();
                foreach (var face in hull.GetFaces())
                    foreach (var triangle in Hull.GetFaceTriangles(edges, face))
                    {
                        indices.Add(triangle.A);
                        indices.Add(triangle.B);
                        indices.Add(triangle.C);
                    }
                WriteMesh(hull.GetVertexPositions(), CollectionsMarshal.AsSpan(indices), [],
                    item.SurfacePropertyIndex, item.CollisionAttributeIndex, phys, pose, entity, instance);
            }

            void Primitive(string kind, Vector3[] centers, float radius, int attribute, int surface)
            {
                // Keep the full transform: non-uniform scale turns a sphere into an ellipsoid.
                primitives.Add(new { kind, centers = centers.Select(p => new[] {p.X, p.Y, p.Z}),
                    radius, transform = new[]{pose.M11,pose.M12,pose.M13,pose.M21,pose.M22,pose.M23,
                                              pose.M31,pose.M32,pose.M33,pose.M41,pose.M42,pose.M43},
                    tags = phys.GetInteractAsTags(attribute), material = hashes[surface], entity, instance });
            }
            foreach (var item in shape.GetAllSpheres())
                Primitive("sphere", [item.Shape.Center], item.Shape.Radius, item.CollisionAttributeIndex, item.SurfacePropertyIndex);
            foreach (var item in shape.GetAllCapsules())
                Primitive("capsule", item.Shape.Center, item.Shape.Radius, item.CollisionAttributeIndex, item.SurfacePropertyIndex);
        }
    }

    private void WriteMesh(ReadOnlySpan<Vector3> source, ReadOnlySpan<int> indices,
                           int[] faceMaterials, int surface, int attribute, PhysAggregateData phys,
                           Matrix4x4 pose, string entity, int instance)
    {
        if (indices.Length == 0) return;
        var vertices = new Vector3[source.Length];
        for (var i = 0; i < vertices.Length; i++)
            vertices[i] = Vector3.Transform(source[i], pose);
        var offset = output.Position;
        output.Write(MemoryMarshal.AsBytes(vertices.AsSpan()));
        output.Write(MemoryMarshal.AsBytes(indices));
        var hashes = phys.SurfacePropertyHashes;
        var overrides = faceMaterials.Select(index => hashes[index]).ToArray();
        output.Write(MemoryMarshal.AsBytes(overrides.AsSpan()));
        var attr = phys.CollisionAttributes[attribute];
        blocks.Add(new { offset, vertices = vertices.Length, triangles = indices.Length / 3,
            perFace = overrides.Length != 0, material = hashes[surface],
            group = attr.GetStringProperty("m_CollisionGroupString"),
            tags = phys.GetInteractAsTags(attribute), entity, instance });
    }

    public void Finish(string json)
    {
        if (blocks.Count == 0) throw new InvalidDataException("Empty world physics");
        File.WriteAllText(json, JsonSerializer.Serialize(new {
            format = 1, blocks, surfaces, primitives, instances = Instances, missingModels = missing
        }));
    }
    public void Dispose() => output.Dispose();
}
