import gzip
import hashlib
import json
from io import BytesIO
from zipfile import ZipFile

import pytest

from backend import club_art, database, personal_badges as badges


def packed(entries):
    result = BytesIO()
    with ZipFile(result, "w") as z:
        for name, blob in entries:
            z.writestr(name, blob)
    return result.getvalue()


@pytest.fixture
def sample(monkeypatch):
    # Exercise the private-library paths using a distributable badge in CI.
    row = club_art.catalog()["BIG"]
    raw = (club_art.ROOT / (row["sha256"] + ".png")).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    entry = {
        "url": "https://example.org/logo.png",
        "page": "https://example.org/club",
        "sha256": digest,
    }
    monkeypatch.setattr(
        badges,
        "sources",
        lambda: {
            "Fnatic": {
                "copy": entry,
                "personal": {**entry, "url": "https://example.org/publisher.png"},
            }
        },
    )
    return raw, digest


def test_install_offline_atomic_private_and_reversible(tmp_path, sample):
    raw, sha = sample
    lib = badges.PersonalBadges(tmp_path / "local.sqlite")
    filename = sha + ".png"
    with pytest.raises(ValueError):
        lib.install_offline(packed([(filename, raw), ("unknown.png", raw)]))
    assert lib.status()["mode"] == "off"
    assert lib.status()["ready"] == 0
    with pytest.raises(ValueError, match="сумма"):
        lib.install_offline(packed([(filename, b"invalid")]))
    assert lib.install_offline(packed([(filename, raw)]))["ready"] == 1
    lib = badges.PersonalBadges(lib.path)
    with gzip.open(database.RELEASE) as source:
        p = json.load(source)["package"]
    before = database.envelope(p)["sha256"]
    index = lib.index(p)
    assert len(index) == 2
    tid = next(tid for tid, t in p["teams"].items() if t["name"] == "Fnatic")
    asset = index["teams/" + tid]
    digest = asset["image"].rsplit("/", 1)[1]
    assert lib.image(digest)[1] == "image/png" and asset["license"] == "Личная копия"
    roster = next(key for key, r in p["rosters"].items() if r["team"] == tid)
    other = next(key for key, r in p["rosters"].items() if r["team"] != tid)
    assert (
        database.match_input(p, [roster, other], index)["teams"][tid]["visual"][
            "gameBadge"
        ]
        is False
    )
    assert database.envelope(p)["sha256"] == before
    p["teams"][tid]["logo"] = {**p["teams"][tid]["logo"], "author": "Владелец"}
    assert "teams/" + tid not in lib.index(p)
    assert lib.start("off")["ready"] == 0 and lib.image(digest) is None


def test_publisher_scope_and_download_cache(tmp_path, sample):
    raw, sha = sample
    calls = []

    def download(url):
        calls.append(url)
        return raw

    lib = badges.PersonalBadges(tmp_path / "private.sqlite", download)
    lib.install_offline(packed([(sha + ".png", raw)]))
    lib.start("personal")
    lib.thread.join(5)
    assert calls == ["https://example.org/publisher.png"]
    assert lib.status()["ready"] == 1
    lib.start("copy")
    lib.thread.join(5)
    assert len(calls) == 1
    assert lib.status()["errors"] == {}


def test_logos_rasterized_locally():
    raw = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 40 40"><circle cx="20" cy="20" r="13"/></svg>'
    png, mime = badges.graphic(raw, "test.svg")
    assert png.startswith(b"\x89PNG") and mime == "image/png"
    assert badges.graphic(packed([("logo.png", png)]), "publisher.zip")[1] == mime


def test_private_catalog_sources_and_coverage():
    for name, opts in badges.sources().items():
        assert club_art.catalog()[name]["kind"] == "game"
        assert {"page", "identity", "url", "sha256"} <= opts["copy"].keys()
        assert len(opts["copy"]["sha256"]) == 64
    assert {"personal", "copy"} == badges.sources()["Fnatic"].keys()
    assert {"personal", "copy"} == badges.sources()["FURIA Esports"].keys()
