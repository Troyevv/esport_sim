from hashlib import sha256
from io import BytesIO
from zipfile import ZipFile

import pytest

from backend import lineup_photos
from backend.portrait_library import PortraitLibrary


def archive(entries):
    out = BytesIO()
    with ZipFile(out, "w") as z:
        for name, content in entries.items():
            z.writestr(name, content)
    return out.getvalue()


def test_private_pack_is_atomic_idempotent_and_portable(tmp_path, monkeypatch):
    library = PortraitLibrary(tmp_path / "personal.sqlite")
    files = {"alpha.png": b"a", "beta.png": b"b"}
    rows = {k:dict(team="test-team",file=k,size=len(v),sha256=sha256(v).hexdigest()) for k,v in files.items()}
    monkeypatch.setattr(lineup_photos,"catalog",lambda: rows)
    with pytest.raises(ValueError):
        lineup_photos.install(library, archive(dict(files, **{"beta.png":b"c"})))
    assert not lineup_photos.index(library)
    with pytest.raises(ValueError):
        lineup_photos.export(library)
    for prefix in ("r571-prototype/public/assets/players/",""):
        assert lineup_photos.install(library, archive({prefix+k:v for k,v in files.items()})) == {"installed":2}
    with ZipFile(BytesIO(lineup_photos.export(library))) as z:
        assert {k:z.read(k) for k in z.namelist()} == files
    assert all(library.image(rows[pid]["sha256"]) == files[pid] for pid in lineup_photos.index(library))
