"""Validate the pinned R4.1 runtime and restore missing or damaged files offline."""

import hashlib
import logging
import os
import shutil
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from zipfile import BadZipFile, ZipFile

from . import cs2_maps

BUILD = str(cs2_maps.BUILD)
MANIFEST = cs2_maps.RUNTIME_FILES


def matches(path, digest):
    try:
        with path.open("rb") as source:
            return hashlib.file_digest(source, "sha256").hexdigest() == digest
    except OSError:
        return False


def verified(folder):
    return all(
        matches(folder / name / file, digest)
        for name, files in MANIFEST.items()
        for file, digest in files.items()
    )


def restore(folder, packs):
    for name, files in MANIFEST.items():
        target = folder / name
        missing = {
            f: digest for f, digest in files.items() if not matches(target / f, digest)
        }
        if not missing:
            continue
        try:
            target.mkdir(parents=True, exist_ok=True)
            with ZipFile(packs / (name + ".zip")) as archive:
                for file, digest in missing.items():
                    with (
                        archive.open(file) as source,
                        NamedTemporaryFile(dir=target, delete=False) as temp,
                    ):
                        path = Path(temp.name)
                        try:
                            shutil.copyfileobj(source, temp)
                            temp.close()
                            if not matches(path, digest):
                                raise ValueError("не совпадает контрольная сумма")
                            path.replace(target / file)
                        finally:
                            temp.close()
                            path.unlink(missing_ok=True)
        except (BadZipFile, OSError, KeyError, ValueError) as exc:
            raise ValueError(
                f"Не удалось восстановить карту {name}. Проверьте свободное место и распакуйте полную версию игры поверх установки. Сохранения находятся отдельно. {exc}"
            ) from exc


_profile_root = None


def activate(data_dir=None):
    global _profile_root
    if data_dir is not None:
        _profile_root = Path(data_dir).resolve()

    base = (
        Path(sys.executable).parent
        if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parents[1]
    )
    if _profile_root is not None:
        folder = _profile_root / "maps" / BUILD
    elif os.name == "nt":
        from .paths import windows_data_dir

        folder = windows_data_dir() / "maps" / BUILD
    else:
        folder = base / "runtime-data" / "maps" / BUILD
    override = os.getenv("ESPORT_SIM_MAPS")
    if override and Path(override).is_absolute() and verified(Path(override)):
        folder = Path(override)
    else:
        if override:
            logging.info(
                "Путь ESPORT_SIM_MAPS не прошёл проверку. Используется комплект сборки."
            )
        restore(folder, base / "resources" / "cs2" / BUILD)
    cs2_maps.use_runtime(folder)
    return folder


if __name__ == "__main__":
    print(activate())
