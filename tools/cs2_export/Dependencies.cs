using System.Numerics;
using System.Text.Json;
using ValvePak;
using ValveResourceFormat.IO;
using ValveResourceFormat.ResourceTypes;
using ValveResourceFormat.Serialization.KeyValues;

static class Dependencies
{
    public static bool IsPlacedCollision(string kind) => kind is "func_brush" or "func_breakable"
        or "prop_door_rotating" or "prop_dynamic" or "prop_dynamic_override"
        or "prop_physics" or "prop_physics_multiplayer";

    public static int Find(string directory, string output)
    {
        var missing = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var path in Directory.EnumerateFiles(directory, "de_*.vpk"))
        {
            using var package = new Package();
            package.Read(path);
            using var loader = new GameFileLoader(package, path);
            var map = Path.GetFileNameWithoutExtension(path);
            using var wf = loader.LoadFileCompiled($"maps/{map}/world.vwrld");
            var world = wf?.DataBlock as World ?? throw new InvalidDataException(map);
            foreach (var name in world.GetEntityLumpNames())
            {
                using var file = loader.LoadFileCompiled(name);
                var lump = file?.DataBlock as EntityLump ?? throw new InvalidDataException(name);
                foreach (var (entity, _, _) in EntityLumpTraversal.EnumerateEntities(
                    lump, loader, Matrix4x4.Identity, m => throw new InvalidDataException(m)))
                {
                    var model = entity.GetStringProperty("model");
                    if (string.IsNullOrEmpty(model) || !IsPlacedCollision(entity.GetStringProperty("classname"))) continue;
                    var compiled = model + "_c";
                    if (package.FindEntry(compiled) == null) missing.Add(compiled);
                }
            }
        }
        File.WriteAllText(output, JsonSerializer.Serialize(missing));
        return 0;
    }

    public static int ReadPackage(string index, string names, string output, bool extract)
    {
        using var package = new Package();
        package.Read(index);
        var entries = new SortedDictionary<string, List<string>>();
        foreach (var name in JsonSerializer.Deserialize<string[]>(File.ReadAllText(names))!)
        {
            if (name.Contains('\\') || name.Contains(':') || Path.IsPathRooted(name)
                || name.Split('/').Any(part => part is "" or "." or ".."))
                throw new InvalidDataException($"Invalid resource path {name}");
            var entry = package.FindEntry(name) ?? throw new FileNotFoundException(name);
            var chunk = entry.ArchiveIndex == Package.DirectoryArchiveIndex
                ? Path.GetFileName(index) : $"pak01_{entry.ArchiveIndex:D3}.vpk";
            if (!entries.TryGetValue(chunk, out var list)) entries[chunk] = list = [];
            list.Add(name);
            if (!extract) continue;
            package.ReadEntry(entry, out var bytes, validateCrc: true);
            var target = Path.Combine(output, name);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.WriteAllBytes(target, bytes);
        }
        if (!extract) File.WriteAllText(output, JsonSerializer.Serialize(entries));
        return 0;
    }
}
