"""Build from a clean locked frontend dist and the installed packaging environment."""

import hashlib
from importlib.metadata import distribution
import os
import platform
import shutil
import struct
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    if (
        sys.platform != "win32"
        or platform.machine().upper() not in ("AMD64", "X86_64")
        or struct.calcsize("P") != 8
    ):
        raise SystemExit("Сборка требует 64-разрядный Windows x64 и Python x64.")
    subprocess.run([sys.executable, "-m", "tools.build_native"], cwd=ROOT, check=True)
    frontend = ROOT / "frontend" / "dist"
    if not (frontend / "index.html").is_file() or not any(
        (frontend / "assets").glob("*.js")
    ):
        raise SystemExit("Сначала соберите frontend через npm ci и npm run build.")
    build = ROOT / "build"
    build.mkdir(exist_ok=True)
    # PyInstaller uses these for hash ordering and the Windows PE timestamp.
    epoch = (
        os.environ.get("SOURCE_DATE_EPOCH")
        or subprocess.check_output(
            ["git", "show", "-s", "--format=%ct", "HEAD"], cwd=ROOT, text=True
        ).strip()
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--noupx",
            "--name",
            "EsportSim",
            "--specpath",
            str(build),
            "--workpath",
            str(build / "freeze"),
            "--distpath",
            str(ROOT / "dist"),
            "--paths",
            str(ROOT),
            "--add-data",
            f"{frontend}:frontend/dist",
            "--add-data",
            f"{ROOT / 'backend' / 'data'}:backend/data",
            "--hidden-import",
            "backend._match_native",
            "--exclude-module",
            "tests",
            "--collect-all",
            "embreex",
            "--add-binary",
            f"{distribution('embreex').locate_file('embreex.libs')}/*.dll:embreex.libs",
            "--collect-data",
            "mediapipe",
            "--collect-binaries",
            "mediapipe",
            "--collect-submodules",
            "uvicorn",
            str(ROOT / "backend" / "desktop.py"),
        ],
        cwd=ROOT,
        env={**os.environ, "SOURCE_DATE_EPOCH": epoch, "PYTHONHASHSEED": "0"},
        check=True,
    )
    dist = ROOT / "dist"
    output = dist / "EsportSim"
    from json import loads
    manifest = loads((ROOT / "backend/data/maps-runtime-26879581.json").read_bytes())
    source = ROOT / "resources/cs2/26879581"
    target = output / "resources/cs2/26879581"
    target.mkdir(parents=True, exist_ok=True)
    for name, expected in manifest.items():
        archive = source / (name + ".zip")
        with zipfile.ZipFile(archive) as files:
            for path, digest in expected.items():
                if hashlib.sha256(files.read(path)).hexdigest() != digest:
                    raise RuntimeError(f"Повреждён ресурс {name}/{path}")
        shutil.copyfile(archive, target / archive.name)
    for file in ("EsportSim.exe", "_internal/frontend/dist/index.html"):
        if not (output / file).is_file():
            raise RuntimeError(f"В сборке отсутствует {file}")
    if not list((output / "_internal/backend").glob("_match_native*.pyd")):
        raise RuntimeError("В сборке отсутствует нативный матчевый модуль")
    from PyInstaller.archive.readers import CArchiveReader

    binary = CArchiveReader(str(output / "EsportSim.exe"))
    modules = binary.open_embedded_archive("PYZ.pyz").toc
    if any(name.startswith("tests.reference_kernel") for name in modules) or any(
        name in modules for name in ("backend.match_ai", "backend.cs2_play", "backend.tactic_execution")
    ):
        raise RuntimeError("В ZIP обнаружена тестовая реализация матчевого ядра")
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE")
    shutil.copyfile(ROOT / "native/vendor/embree4/LICENSE.txt", output / "LICENSE-Embree.txt")
    shutil.copyfile(ROOT / "docs" / "TACTICS.md", output / "TACTICS.md")
    shutil.copyfile(ROOT / "docs" / "WORLD_R31.md", output / "WORLD_R31.md")
    shutil.copyfile(ROOT / "SOURCES.md", output / "SOURCES.md")
    guide = (ROOT / "docs" / "DATABASE_R32.md").read_text(encoding="utf-8")
    (output / "DATABASE_R32.md").write_text(
        guide.replace("../SOURCES.md", "SOURCES.md"), encoding="utf-8"
    )
    for name in (
        "BO1.md",
        "COMPETITIONS_R43.md",
        "STAFF_R51.md",
        "MAPS_R4.md",
        "MAPS_R4_QA.md",
        "MAPS_R4_AI.md",
        "CAREER_R33.md",
        "INTERFACE_R34.md",
        "INTERFACE_R34_QA.md",
        "SCENE_202611.md",
        "PORTRAITS_R32.md",
        "SCENE_ART_R32.md",
        "CLUBS_AND_KITS_R32.md",
        "PORTRAIT_FIT_R32.md",
        "TEAM_KIT_COVERAGE.csv",
        "PERSONAL_BADGES_R32.md",
        "PRIVATE_STUDIO_R32.md",
        "PRIVATE_STUDIO_COVERAGE.csv",
        "PRIVATE_STUDIO_SEARCH.csv",
        "CLUB_BADGE_SOURCES.md",
    ):
        doc = (ROOT / "docs" / name).read_text(encoding="utf-8")
        (output / name).write_text(
            doc.replace("../backend/data/", "_internal/backend/data/").replace(
                "../frontend/public/scorebot/", "_internal/frontend/dist/scorebot/"
            ),
            encoding="utf-8",
        )
    source_tools = output / "tools"
    source_tools.mkdir(exist_ok=True)
    for script in ("cs2_map_sources.py", "cs2_world_sources.py"):
        shutil.copyfile(ROOT / "tools" / script, source_tools / script)
    exporter_source = source_tools / "cs2_export"
    exporter_source.mkdir(exist_ok=True)
    for name in ("Program.cs", "Physics.cs", "Dependencies.cs", "Cs2Export.csproj"):
        shutil.copyfile(ROOT / "tools" / "cs2_export" / name, exporter_source / name)
    screenshots = output / "screenshots"
    screenshots.mkdir(exist_ok=True)
    shutil.copytree(ROOT / "docs" / "screenshots" / "r34", screenshots / "r34", dirs_exist_ok=True)
    shutil.copyfile(ROOT / "docs" / "screenshots" / "r41-bo1.webp", screenshots / "r41-bo1.webp")
    for source in sorted((ROOT / "docs" / "screenshots").glob("*.png")):
        if not source.name.startswith(("r2-", "r32-", "r33-", "r41-")):
            continue
        shutil.copyfile(source, screenshots / source.name)
    archive = dist / "EsportSim-windows-x64.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                entry = zipfile.ZipInfo(
                    path.relative_to(dist).as_posix(), time.gmtime(int(epoch))[:6]
                )
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.create_system = 0
                with path.open("rb") as source, bundle.open(entry, "w") as target:
                    shutil.copyfileobj(source, target)
    with archive.open("rb") as result:
        checksum = hashlib.file_digest(result, "sha256").hexdigest()
    print(f"{archive}  SHA-256 {checksum}")


if __name__ == "__main__":
    main()
