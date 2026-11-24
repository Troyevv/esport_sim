"""Build from a clean locked frontend dist and the installed packaging environment."""

import platform
import shutil
import struct
import subprocess
import sys
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
            "--collect-submodules",
            "uvicorn",
            str(ROOT / "backend" / "desktop.py"),
        ],
        cwd=ROOT,
        check=True,
    )
    dist = ROOT / "dist"
    output = dist / "EsportSim"
    for file in ("EsportSim.exe", "_internal/frontend/dist/index.html"):
        if not (output / file).is_file():
            raise RuntimeError(f"В сборке отсутствует {file}")
    shutil.copyfile(ROOT / "LICENSE", output / "LICENSE")
    print(
        shutil.make_archive(
            str(dist / "EsportSim-windows-x64"), "zip", dist, "EsportSim"
        )
    )


if __name__ == "__main__":
    main()
