"""Build from a clean locked frontend dist and the installed packaging environment."""

import hashlib
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
    for file in ("EsportSim.exe", "_internal/frontend/dist/index.html"):
        if not (output / file).is_file():
            raise RuntimeError(f"В сборке отсутствует {file}")
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE")
    shutil.copyfile(ROOT / "docs" / "TACTICS.md", output / "TACTICS.md")
    shutil.copyfile(ROOT / "docs" / "WORLD_R31.md", output / "WORLD_R31.md")
    shutil.copyfile(ROOT / "SOURCES.md", output / "SOURCES.md")
    guide = (ROOT / "docs" / "DATABASE_R32.md").read_text(encoding="utf-8")
    (output / "DATABASE_R32.md").write_text(
        guide.replace("../SOURCES.md", "SOURCES.md"), encoding="utf-8"
    )
    for name in (
        "BO1.md",
        "CAREER_R33.md",
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
    screenshots = output / "screenshots"
    screenshots.mkdir(exist_ok=True)
    for source in sorted((ROOT / "docs" / "screenshots").glob("*.png")):
        if not source.name.startswith(("r2-", "r32-", "r33-")):
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
