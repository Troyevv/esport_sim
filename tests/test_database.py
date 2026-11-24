import json
from copy import deepcopy
from uuid import uuid4

import pytest

from backend import database as data, match, skills
from backend.store import Store
from tools.import_scene import estimate, ident, starter


def test_seed_package_is_reproducible_and_estimates_shrink():
    pack = starter()
    assert (
        data.STARTER.read_bytes() == (data.encode(data.envelope(pack)) + "\n").encode()
    )
    assert estimate(95, "rifler", 1, 1) < estimate(95, "rifler", 1, 25)
    assert estimate(85, "support", 1, 25) > estimate(85, "entry", 30, 25)
    assert set(pack["players"][ident("p", "ZywOo")]["skills"]) == set(skills.KEYS)


@pytest.mark.parametrize(
    "field,value",
    [("potential", 101), ("role", "bad"), ("skills", {}), ("contract", "unknown")],
)
def test_atomic_import_refuses_invalid_packages(tmp_path, field, value):
    store = Store(tmp_path / "scene.sqlite")
    pack = starter()
    pack["revision"] = 2
    pack["players"][ident("p", "apEX")][field] = value
    with pytest.raises(ValueError), store.transaction():
        data.install(store.db, data.encode(data.envelope(pack)))
    assert len(data.installed(store.db)) == 1
    with pytest.raises(ValueError, match="Повтор"):
        data.install(store.db, '{"package":1,"package":2}')


@pytest.mark.parametrize("group", data.GROUPS)
def test_copy_edit_delete_preserve_source_and_provenance(tmp_path, group):
    store = Store(tmp_path / "scene.sqlite")
    p = starter()
    key = p["id"]
    original = next(iter(p[group].values()))
    copied = dict(original, name=original["name"] + " (копия)")
    with store.transaction():
        data.edit(store.db, key, 1, group, "copy", copied, True)
    created = data.get(store.db, key, 2)[group]["copy"]
    assert created["origin"] == "edit-2"
    changed = deepcopy(created)
    changed["name"] = "Правка"
    if group == "players":
        changed["skills"]["loyalty"] = 0
    with store.transaction():
        data.edit(store.db, key, 2, group, "copy", changed, False)
    edits = data.get(store.db, key, 3)[group]["copy"]["fields"]
    assert edits["name"] == "edit-3"
    if group == "players":
        assert edits["skills.loyalty"] == "edit-3"
    with pytest.raises(ValueError, match="последнюю"), store.transaction():
        data.edit(store.db, key, 2, group, "copy", None, False)
    with store.transaction():
        data.edit(store.db, key, 3, group, "copy", None, False)
    assert "copy" not in data.get(store.db, key, 4)[group]
    assert data.get(store.db, key, 1) == p


def test_integrity_and_save_isolation(tmp_path):
    path = tmp_path / "scene.sqlite"
    store = Store(path)
    p = starter()
    pid = ident("p", "apEX")
    with pytest.raises(ValueError, match="отсутствует"), store.transaction():
        data.edit(store.db, p["id"], 1, "players", pid, None, False)
    with pytest.raises(ValueError, match="SHA-256"):
        data.install(store.db, json.dumps(dict(package=p, sha256="0" * 64)))
    pairs = [ident("r", "Vitality"), ident("r", "Falcons")]

    def command(kind, value=None):
        state = store.read()
        message = dict(
            id=str(uuid4()),
            revision=state["revision"],
            context=state["context"],
            kind=kind,
            value=value,
        )
        assert store.apply(message) == store.apply(message)

    command("database-match", dict(id=p["id"], revision=1, seed=50, rosters=pairs))
    command("save")
    before = store.read()["world"]
    assert len(before["domain"]["players"]) == 10
    with store.transaction():
        data.edit(
            store.db,
            p["id"],
            1,
            "players",
            pid,
            dict(p["players"][pid], name="Переименован"),
            False,
        )
    store.db.close()
    store = Store(path)
    command("load")
    assert store.read()["world"] == before
    assert "potential" not in json.dumps(store.snapshot("full"))


@pytest.mark.parametrize(
    "home,away,seed",
    [("Vitality", "Falcons", 42), ("M80", "TYLOO", 47), ("The MongolZ", "FURIA", 91)],
)
def test_real_rosters_finish_by_events(home, away, seed, monkeypatch):
    p = starter()
    rosters = [ident("r", home), ident("r", away)]
    monkeypatch.setattr(
        skills, "role_rating", lambda *args: pytest.fail("OVR in engine")
    )
    w = match.initial(seed, data.match_input(p, rosters), rosters)
    while w["phase"] != "finished" and w["tick"] < 100000:
        match.advance(w)
    assert w["phase"] == "finished"
    ends = [
        e
        for batch in w["archive"] + [w["events"]]
        for e in batch
        if e["kind"] == "round_end"
    ]
    assert len(ends) == sum(w["score"])
    print(home, away, seed, w["score"], w["serial"], w["tick"])


def test_zip_import_requires_pinned_reports():
    from io import BytesIO
    from zipfile import ZipFile
    from backend import valve_import

    with pytest.raises(ValueError, match="ZIP"):
        valve_import.import_zip(b"bad")
    manifest = json.loads(valve_import.MANIFEST.read_bytes())
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for i in range(len(manifest)):
            archive.writestr(f"{i:04}.md", "wrong version")
    with pytest.raises(ValueError, match="не совпадает"):
        valve_import.import_zip(buffer.getvalue())


def test_familiarity_and_staff_follow_selected_revision():
    p = starter()
    pid = ident("p", "ZywOo")
    p["players"][pid]["mapKnowledge"]["depo"] = 17
    p["players"][pid]["roleMastery"]["awper"] = 91
    coach = ident("s", "XTQZZZ")
    p["staff"][coach]["preparation"] = 82
    domain = data.match_input(
        data.validate(p), [ident("r", "Vitality"), ident("r", "M80")]
    )
    assert domain["players"][pid]["mapKnowledge"] == {"depo": 17}
    assert domain["players"][pid]["roleMastery"]["awper"] == 91
    assert domain["staff"][coach]["preparation"] == 82


def test_embedded_credited_portrait_survives_export(tmp_path):
    import base64

    p = starter()
    png = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/lccAAAAASUVORK5CYII="
    image = dict(
        image="data:image/png;base64," + png,
        author="Test fixture",
        source="https://example.org/photo",
        license="CC0",
        changes="",
    )
    player = next(iter(p["players"].values()))
    player["photo"] = image
    player["fields"]["photo"] = "model"
    p["id"] = "test-portrait"
    store = Store(tmp_path / "photo.sqlite")
    with store.transaction():
        data.install(store.db, data.encode(data.envelope(p)))
    assert data.get(store.db, p["id"], 1) == p
    image["image"] = "data:image/png;base64," + base64.b64encode(b"not a png").decode()
    with pytest.raises(ValueError, match="формат фотографии"):
        data.validate(p)
