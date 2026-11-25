import csv
import gzip
import json
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


@pytest.mark.parametrize("native_width", [None, 181])
def test_private_pack_is_atomic_offline_and_does_not_mutate_players(
    tmp_path, monkeypatch, native_width
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
    if native_width:
        entry["nativeWidth"] = native_width
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
    url = fresh.index(pack["players"])["p-1"]["image"]
    assert url == "/api/portraits/image/" + digest + (
        "?nativeWidth=181" if native_width else ""
    )
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
    from backend.database import RELEASE

    with gzip.open(RELEASE, "rt", encoding="utf-8") as stream:
        players = json.load(stream)["package"]["players"]
    coverage = Path(__file__).parents[1] / "docs" / "PRIVATE_STUDIO_COVERAGE.csv"
    with coverage.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(players)
    assert {row["player_id"] for row in rows} == players.keys()
    assert {
        row["player_id"] for row in rows if row["stage"] == "included"
    } == catalog.keys()
    assert len({entry["sha256"] for entry in catalog.values()}) == len(catalog)
    assert all(players[pid]["name"] == entry["name"] for pid, entry in catalog.items())
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


def test_private_garment_rollback_and_offline_registration(tmp_path, monkeypatch):
    raw = (
        Path(__file__).parents[1] / "frontend/e2e/fixtures/portraits/model-a.png"
    ).read_bytes()
    digest = sha256(raw).hexdigest()
    rig = dict(width=480, height=560, collar=[240, 310], span=490, seat=[120, 157])
    item = dict(
        sha256=digest, rig=rig, observed="2026-07-26", source="https://example.org/kit"
    )
    monkeypatch.setattr(personal_portraits, "kits", lambda: {"team-1": item})
    library = PortraitLibrary(tmp_path / "portraits.sqlite")
    name = "kits/" + digest + ".png"
    pack = {"teams": {"team-1": {}}, "players": {}}
    with pytest.raises(ValueError):
        personal_portraits.install(
            library, pack, archive((name, raw), ("bad.png", b"bad"))
        )
    assert not personal_portraits.installed_kits(library)
    assert personal_portraits.install(library, pack, archive((name, raw))) == {
        "installed": 0,
        "kits": 1,
    }
    assert personal_portraits.installed_kits(library)["team-1"]["rig"] == rig
    assert library.image(digest) == raw
    library.close()
