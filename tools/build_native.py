"""Prepare the local C++ module for this interpreter and checkout."""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
from time import monotonic, sleep

from backend.instance import launcher_lock
from tools.source_fingerprint import fingerprint, read_stamp, stamp

ROOT = Path(__file__).resolve().parents[1]


def build(install_tools, extension):
    if install_tools:
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", ROOT / "requirements-native.txt"], check=True)
    try:
        import cmake
        import pybind11
    except ImportError as exc:
        raise RuntimeError("Установите зависимости сборки: python -m pip install -r requirements-native.txt") from exc
    directory = ROOT / "build" / ("native-" + sys.implementation.cache_tag + "-" + sysconfig.get_platform())
    exe = Path(cmake.CMAKE_BIN_DIR) / ("cmake.exe" if sys.platform == "win32" else "cmake")
    subprocess.run([exe, "-S", ROOT / "native", "-B", directory, "-DCMAKE_BUILD_TYPE=Release",
                    f"-DPython_EXECUTABLE={sys.executable}", f"-Dpybind11_DIR={pybind11.get_cmake_dir()}"],
                   check=True)
    subprocess.run([exe, "--build", directory, "--config", "Release", "--parallel"], check=True)
    staging = directory / "install"
    subprocess.run([exe, "--install", directory, "--config", "Release", "--prefix", staging], check=True)
    temp = extension.with_suffix(".tmp")
    try:
        shutil.copyfile(staging / "backend" / extension.name, temp)
        os.replace(temp, extension)
    finally:
        temp.unlink(missing_ok=True)
    subprocess.run([sys.executable, "-c", "from backend import _match_native"], cwd=ROOT, check=True)


def ensure_built(install_tools=False):
    cache = ROOT / "build/source-launcher"
    cache.mkdir(parents=True, exist_ok=True)
    extension = ROOT / "backend" / ("_match_native" + sysconfig.get_config_var("EXT_SUFFIX"))
    inputs = [ROOT / "requirements-native.txt", Path(__file__), *(ROOT / "native").rglob("*")]
    identity = f"{sys.executable}|{platform.python_version()}|{extension.name}"
    marker = cache / "native.sha256"
    deadline = monotonic() + 600
    while True:
        with launcher_lock(cache / "native-build.lock") as acquired:
            if acquired:
                key = fingerprint(inputs, ROOT, identity)
                if extension.is_file() and read_stamp(marker) == key + fingerprint([extension], ROOT):
                    return
                try:
                    build(install_tools, extension)
                except subprocess.CalledProcessError as exc:
                    raise RuntimeError("Ошибка сборки C++20. Проверьте компилятор и заголовки Python. "
                                       "На Windows нужны Visual Studio Build Tools C++ x64.") from exc
                stamp(marker, key + fingerprint([extension], ROOT))
                return
        if monotonic() >= deadline:
            raise RuntimeError("Другая сборка нативного модуля ещё не завершилась.")
        sleep(.25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-tools", action="store_true", help="Install locked build tools on cache miss")
    try:
        ensure_built(parser.parse_args().install_tools)
    except (RuntimeError, OSError) as error:
        parser.exit(1, f"{error}\n")
