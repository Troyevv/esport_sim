"""Extract map-owned Source 2 resources from a local CS2 install of the dated build."""

import argparse
import hashlib
import json
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from cs2_map_sources import ACTIVE, ADDITIONAL, BUILD, VERSION


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def entity_classes(directory):
    counts = Counter()
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            fields = line.split(None, 1)
            if len(fields) == 2 and fields[0] == "classname":
                counts[fields[1].strip()] += 1
    return counts


def extract_map(csgo, map_id, viewer, reference, output):
    archive = csgo / "maps" / f"{map_id}.vpk"
    if output.exists():
        raise FileExistsError(f"Каталог назначения уже существует: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        stage = Path(tmp) / map_id
        stage.mkdir()
        raw = stage / "compiled"
        dumps = stage / "entities"
        physics = stage / "physics"
        for folder in (raw, dumps, physics):
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
        subprocess.run(command + ["-e", "vents_c", "-d", "-o", str(dumps)], check=True)
        world = f"maps/{map_id}/world_physics.vmdl_c"
        subprocess.run(command + [
            "-f", world, "-o", str(physics), "--gltf_export_format", "glb",
            "--gltf_export_materials",
        ], check=True)
        glbs = list(physics.rglob("*.glb"))
        if len(glbs) != 1:
            raise ValueError(f"{map_id}: ожидалась одна модель world_physics, получено {len(glbs)}")
        exported = stage / "world_physics.glb"
        glbs[0].rename(exported)
        counts = entity_classes(dumps)
        for name in ("info_player_terrorist", "info_player_counterterrorist", "func_bomb_target"):
            if not counts[name]:
                raise ValueError(f"{map_id}: в дампе карты отсутствует {name}")
        report = {
            "map": map_id, "clientVersion": VERSION, "steamBuild": BUILD,
            "vpkSha256": sha256(archive), "navSha256": nav_hash,
            "worldPhysicsSha256": sha256(exported),
            "compiledFiles": dict(sorted(Counter(p.suffix for p in raw.rglob("*") if p.is_file()).items())),
            "entityClasses": dict(sorted(counts.items())),
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
    parser.add_argument("--reference", type=Path, required=True, help="Каталог cs2_map_sources")
    parser.add_argument("--map", choices=(*ACTIVE, *ADDITIONAL), action="append")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    pairs = (args.game / "steam.inf").read_text(encoding="utf-8-sig").splitlines()
    version = dict(line.strip().split("=", 1) for line in pairs if "=" in line)
    if version.get("ClientVersion") != VERSION:
        raise SystemExit(f"Для стартовой базы требуется ClientVersion {VERSION}")
    for map_id in args.map or (*ACTIVE, *ADDITIONAL):
        result = extract_map(args.game, map_id, args.viewer.resolve(), args.reference,
                             args.output / map_id)
        print(map_id, json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
