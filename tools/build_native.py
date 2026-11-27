"""Configure, incrementally build and install the module for the running Python."""
from pathlib import Path
import subprocess
import sys
import sysconfig

import cmake
import pybind11


def main():
    root = Path(__file__).resolve().parents[1]
    build = root / "build" / ("native-" + sys.implementation.cache_tag + "-" + sysconfig.get_platform())
    exe = Path(cmake.CMAKE_BIN_DIR) / ("cmake.exe" if sys.platform == "win32" else "cmake")
    subprocess.run([exe, "-S", root / "native", "-B", build, "-DCMAKE_BUILD_TYPE=Release",
                    f"-DPython_EXECUTABLE={sys.executable}", f"-Dpybind11_DIR={pybind11.get_cmake_dir()}"],
                   check=True)
    subprocess.run([exe, "--build", build, "--config", "Release", "--parallel"], check=True)
    subprocess.run([exe, "--install", build, "--config", "Release", "--prefix", root], check=True)


if __name__ == "__main__":
    main()
