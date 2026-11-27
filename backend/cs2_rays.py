"""Locate the pinned Embree shared library for the C++ ray scene."""
from functools import lru_cache
from pathlib import Path

from embreex import rtcore


@lru_cache(maxsize=1)
def _library_path():
    package = Path(rtcore.__file__).resolve().parent
    folders = (package.parent / "embreex.libs", package / ".dylibs", package)
    for folder in folders:
        for path in sorted(folder.glob("*embree4*")):
            if path.name.endswith((".dll", ".dylib")) or ".so" in path.name:
                return path
    raise RuntimeError("Не найдена библиотека Embree 4 из пакета embreex")
