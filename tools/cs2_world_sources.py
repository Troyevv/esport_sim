"""Extract map-owned Source 2 resources from a local CS2 install of the dated build."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
import shutil
from pathlib import Path

from cs2_map_sources import ACTIVE, ADDITIONAL, BUILD, VERSION


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def extract_map(csgo, map_id, viewer, exporter, reference, output):
    archive = csgo / "maps" / f"{map_id}.vpk"
    if output.exists():
        raise FileExistsError(f"Каталог назначения уже существует: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / map_id
        stage.mkdir()
        raw = stage / "compiled"
        physics = stage / "physics"
        for folder in (raw, physics):
            folder.mkdir()
        command = [str(viewer), "-i", str(archive)]
        # Preserve embedded physics, auxiliary physics files, node transforms and
        # entity lumps. Keeping only world_physics would discard brush triggers.
        subprocess.run(command + [
            "-e", "vmap_c,vwrld_c,vwnod_c,vmdl_c,vphys_c,vents_c,nav",
            "-o", str(raw),
        ], check=True)
        nav = raw / "maps" / f"{map_id}.nav"
        nav_hash = sha256(nav)
        if nav_hash != sha256(reference / map_id / f"{map_id}.nav"):
            raise ValueError(f"{map_id}: NAV установленной карты отличается от среза")
        world = f"maps/{map_id}/world_physics.vmdl_c"
        subprocess.run(command + [
            "-f", world, "-o", str(physics), "--gltf_export_format", "glb",
            "--gltf_export_materials",
        ], check=True)
        glb = physics / "maps" / map_id / "world_physics_physics.glb"
        if not glb.is_file():
            raise ValueError(f"{map_id}: Source 2 Viewer не экспортировал физическую модель")
        exported = stage / "world_physics.glb"
        glb.rename(exported)
        gameplay = stage / "gameplay.json"
        subprocess.run([*exporter, str(archive), str(gameplay)], check=True)
        spatial = json.loads(gameplay.read_bytes())
        counts = spatial["classes"]
        for name in ("info_player_terrorist", "info_player_counterterrorist", "func_bomb_target"):
            if not counts.get(name):
                raise ValueError(f"{map_id}: в дампе карты отсутствует {name}")
        geometry = json.loads((stage / "collision.json").read_bytes())
        atlas = json.loads((reference / "inventory.json").read_bytes())["maps"][map_id]
        for png in atlas["radars"]:
            shutil.copyfile(reference / map_id / png, stage / png)
        report = {
            "map": map_id, "clientVersion": VERSION, "steamBuild": BUILD,
            "vpkSha256": sha256(archive), "navSha256": nav_hash,
            "worldPhysicsSha256": sha256(exported),
            "overview": atlas["overview"], "radars": atlas["radars"],
            "surfaceCount": len(geometry["surfaces"]),
            "physicalTriangles": sum(b["triangles"] for b in geometry["blocks"]),
            "collisionTags": sorted({tag for b in geometry["blocks"] for tag in b["tags"]}),
            "analyticPrimitives": len(geometry["primitives"]),
            "unresolvedModels": geometry["missingModels"],
            "compiledFiles": dict(sorted(Counter(p.suffix for p in raw.rglob("*") if p.is_file()).items())),
            "entityClasses": dict(sorted(counts.items())),
            "spawns": dict(Counter(p["side"] for p in spatial["spawns"] if p["enabled"])),
            "targets": dict(Counter(t["site"] for t in spatial["targets"])),
            "places": sorted({p["name"] for p in spatial["places"] if p["name"]}),
            "ladders": len(spatial["ladders"]),
            "hidingSpots": sum(len(a["cover"]) for a in spatial["areas"]),
        }
        (stage / "provenance.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8",
        )
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", type=Path, required=True, help="Каталог game/csgo")
    parser.add_argument("--viewer", type=Path, required=True, help="Source2Viewer-CLI")
    parser.add_argument("--exporter", type=Path, help="Исполняемый файл Cs2Export")
    parser.add_argument("--reference", type=Path, required=True, help="Каталог cs2_map_sources")
    parser.add_argument("--map", choices=(*ACTIVE, *ADDITIONAL), action="append")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pairs = (args.game / "steam.inf").read_text(encoding="utf-8-sig").splitlines()
    version = dict(line.strip().split("=", 1) for line in pairs if "=" in line)
    if version.get("ClientVersion") != VERSION:
        raise SystemExit(f"Для стартовой базы требуется ClientVersion {VERSION}")
    if args.exporter:
        exporter = [str(args.exporter.resolve())]
    else:
        project = Path(__file__).resolve().parent / "cs2_export" / "Cs2Export.csproj"
        subprocess.run(["dotnet", "build", str(project), "-c", "Release"], check=True)
        exporter = ["dotnet", str(project.parent / "bin/Release/net11.0/Cs2Export.dll")]
    for map_id in args.map or (*ACTIVE, *ADDITIONAL):
        result = extract_map(args.game, map_id, args.viewer.resolve(), exporter, args.reference,
                             args.output / map_id)
        print(map_id, json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
