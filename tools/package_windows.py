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
    shutil.copyfile(ROOT / "docs" / "DATABASE_R32.md", output / "DATABASE_R32.md")
    screenshots = output / "screenshots"
    screenshots.mkdir(exist_ok=True)
    for source in (ROOT / "docs" / "screenshots").glob("r2-*.png"):
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
