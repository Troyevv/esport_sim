"""Import the dated CS2 radar, navigation and static visibility reference assets."""

import argparse
import hashlib
import json
import shutil
import struct
import tempfile
import zipfile
from contextlib import ExitStack
from pathlib import Path
from urllib.request import urlopen

VERSION = "2000950"
BUILD = "26879581"
RELEASE = f"https://github.com/pnxenopoulos/awpy-data/releases/download/{VERSION}"
DIGESTS = {
    "manifest.json": "b9b976dbff7b35d7cd3695d33fb2e91636f5f5452da1d08954ad3ebbbb65534c",
    "map_data.json": "a5b5a86e49ccbac870c37892d8c94e985154a397c5c8c0bbe1e24d15b498f3c7",
    "images.zip": "880f3c1181ad30e6f937fdb2bf86ee1748514fefb4a7debd838340209fe38ec2",
    "navs.zip": "2e853e6a54f9f865d636725ee957f10f904b9fa91c8cebd86d05fba3d381a097",
    "geometry.zip": "6201488d25cfb026916e760dc08e0ccceaa4fce2292668cf3110b8856d3bbc54",
}
ACTIVE = ("de_ancient", "de_anubis", "de_cache", "de_dust2", "de_inferno", "de_mirage", "de_nuke")
ADDITIONAL = ("de_train", "de_vertigo")


def verify_file(path):
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != DIGESTS[path.name]:
        raise ValueError(f"{path.name}: SHA-256 {digest}, ожидался {DIGESTS[path.name]}")


def radar_size(path):
    with path.open("rb") as source:
        header = source.read(24)
    if header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError(f"{path.name}: повреждён заголовок PNG")
    return struct.unpack(">II", header[16:])


def mesh_counts(path):
    with path.open("rb") as source:
        magic, version, vertices, triangles = struct.unpack("<4sIII", source.read(16))
    if (magic, version) != (b"AWMH", 1) or not vertices or not triangles:
        raise ValueError(f"{path.name}: неизвестный формат геометрии")
    if path.stat().st_size != 16 + 12 * (vertices + triangles):
        raise ValueError(f"{path.name}: неверная длина данных сетки")
    return {"vertices": vertices, "triangles": triangles}


def import_sources(source, output):
    """Publish a new directory only after every pinned input has been verified."""
    for name in DIGESTS:
        verify_file(source / name)
    manifest = json.loads((source / "manifest.json").read_bytes())
    if (str(manifest["client_version"]), str(manifest["buildid"])) != (VERSION, BUILD):
        raise ValueError("Версия CS2 расходится с датой исходной базы")
    transforms = json.loads((source / "map_data.json").read_bytes())
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Каталог назначения уже существует: {output}")
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp, ExitStack() as stack:
        stage = Path(tmp) / "maps"
        stage.mkdir()
        archives = {
            name: stack.enter_context(zipfile.ZipFile(source / name))
            for name in ("images.zip", "navs.zip", "geometry.zip")
        }
        rows = {}
        for map_id in (*ACTIVE, *ADDITIONAL):
            folder = stage / map_id
            folder.mkdir()
            record = {
                "active": map_id in ACTIVE,
                "overview": transforms.get(map_id),
                "radars": {},
                "navVersion": None,
                "visibilityMesh": None,
            }
            rows[map_id] = record
            members = [
                ("images.zip", f"radars/{map_id}.png"),
                ("images.zip", f"radars/{map_id}_lower.png"),
                ("navs.zip", f"{map_id}.nav"),
                ("geometry.zip", f"{map_id}.mesh"),
            ]
            for archive_name, member in members:
                archive = archives[archive_name]
                if member not in archive.namelist():
                    continue
                target = folder / Path(member).name
                with archive.open(member) as inp, target.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                if target.suffix == ".png":
                    record["radars"][target.name] = radar_size(target)
                elif target.suffix == ".mesh":
                    record["visibilityMesh"] = mesh_counts(target)
                else:
                    with target.open("rb") as nav:
                        magic, version = struct.unpack("<II", nav.read(8))
                    if magic != 0xFEEDFACE:
                        raise ValueError(f"{target.name}: неизвестный формат NAV")
                    record["navVersion"] = version
        report = {"date": "2026-11-24", "source": RELEASE, "build": BUILD,
                  "clientVersion": VERSION, "maps": rows}
        (stage / "inventory.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        shutil.copyfile(source / "manifest.json", stage / "manifest.json")
        stage.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--source", type=Path, help="Каталог пяти файлов релиза 2000950")
    mode.add_argument("--download", action="store_true", help="Скачать закреплённый релиз")
    parser.add_argument("output", type=Path, help="Новый каталог исходных карт")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        source = args.source
        if args.download:
            source = Path(tmp)
            for name in DIGESTS:
                with urlopen(f"{RELEASE}/{name}", timeout=120) as inp:
                    with (source / name).open("wb") as out:
                        shutil.copyfileobj(inp, out)
        report = import_sources(source, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
