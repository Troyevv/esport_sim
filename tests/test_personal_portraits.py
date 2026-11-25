from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

from backend import personal_portraits
from backend.portrait_library import PortraitLibrary


def archive(*members):
    buffer = BytesIO()
    with ZipFile(buffer, "w") as z:
        for name, data in members:
            z.writestr(name, data)
    return buffer.getvalue()


def test_private_pack_is_atomic_offline_and_does_not_mutate_players(
    tmp_path, monkeypatch
):
    raw = (
        Path(__file__).parents[1] / "frontend/e2e/fixtures/portraits/model-a.png"
    ).read_bytes()
    digest = sha256(raw).hexdigest()
    entry = dict(
        name="Игрок",
        sha256=digest,
        publisher="Тестовая студия",
        source="https://example.org/player",
    )
    monkeypatch.setattr(personal_portraits, "catalog", lambda: {"p-1": entry})
    library = PortraitLibrary(tmp_path / "portraits.sqlite")
    pack = {"players": {"p-1": {"name": "Игрок"}}}
    file = digest + ".png"
    with pytest.raises(ValueError):
        personal_portraits.install(
            library, pack, archive((file, raw), ("unknown.png", raw))
        )
    assert library.index(pack["players"]) == {}
    with pytest.raises(ValueError):
        personal_portraits.install(library, pack, archive((file, raw[:-5])))
    assert personal_portraits.install(library, pack, archive((file, raw))) == {
        "installed": 1
    }
    fresh = PortraitLibrary(library.path)
    assert fresh.index(pack["players"])["p-1"]["image"].endswith(digest)
    assert fresh.image(digest) == raw
    assert pack["players"] == {"p-1": {"name": "Игрок"}}
    assert personal_portraits.install(fresh, pack, archive((file, raw))) == {
        "installed": 1
    }
    with pytest.raises(ValueError):
        personal_portraits.install(
            fresh, {"players": {"p-1": {"name": "Другой игрок"}}}, archive((file, raw))
        )


def test_release_portrait_catalog_is_metadata_only():
    from backend.portrait_sources import previously_rejected

    catalog = personal_portraits.catalog()
    assert len(catalog) >= 6
    assert all(
        len(v["sha256"]) == len(v["originalSha256"]) == 64
        and v["identitySource"].startswith("https://")
        and not previously_rejected(v["source"])
        for v in catalog.values()
    )
    assert all(
        not (personal_portraits.CATALOG.parent / (v["sha256"] + ".png")).exists()
        for v in catalog.values()
    )
