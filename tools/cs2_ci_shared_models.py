"""Resolve the placed-model dependencies of map-only Steam fixtures for source CI."""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("game", type=Path)
    parser.add_argument("downloader", type=Path)
    parser.add_argument("exporter", type=Path)
    args = parser.parse_args()
    export = ["dotnet", str(args.exporter.resolve())]
    game = args.game.resolve()
    with TemporaryDirectory(dir=game.parent) as scratch:
        work = Path(scratch)
        names = work / "names.json"
        chunks = work / "chunks.json"
        subprocess.run([*export, "model-list", game / "maps", names], check=True)

        def fetch(group):
            filelist = work / "files.txt"
            filelist.write_text("".join(f"game/csgo/{name}\n" for name in group))
            subprocess.run([args.downloader.resolve(), "-app", "730", "-depot", "2347770",
                            "-manifest", "5924479096069937098", "-filelist", filelist,
                            "-dir", work / "shared", "-validate"], check=True)

        index = work / "shared/game/csgo/pak01_dir.vpk"
        fetch([index.name])
        subprocess.run([*export, "chunk-list", index, names, chunks], check=True)
        groups = json.loads(chunks.read_bytes())
        filenames = sorted(groups)
        print(f"{len(json.loads(names.read_bytes()))} resources in {len(groups)} VPKs", flush=True)
        for start in range(0, len(filenames), 6):
            batch = filenames[start:start + 6]
            fetch(batch)
            names.write_text(json.dumps([name for chunk in batch for name in groups[chunk]]))
            subprocess.run([*export, "unpack", index, names, game], check=True)
            for chunk in batch:
                if chunk != index.name:
                    (index.parent / chunk).unlink()


if __name__ == "__main__":
    main()
