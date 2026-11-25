from copy import deepcopy

from backend import database
from backend.store import Store


def test_academy_ownership_migrates_an_edited_branch_without_overwriting_its_history(
    tmp_path,
):
    path = tmp_path / "season.sqlite"
    store = Store(path)
    release = database.get(store.db, database.RELEASE_ID, 1)
    teams = {r["name"]: k for k, r in release["teams"].items()}
    main, junior = teams["Team Spirit"], teams["Team Spirit Academy"]
    assert database.shares_organization(release, main, junior)
    assert not database.shares_organization(release, main, teams["G2 Ares"])
    archived = release["teams"][teams["Falcons Force"]]
    assert archived["organization"] is None
    assert (
        archived["formerOrganization"]
        == release["teams"][teams["Team Falcons"]]["organization"]
    )
    branch = deepcopy(release)
    branch["id"] = "custom-november"
    branch["teams"][junior]["organization"] = None
    for field in ("teamType", "organization"):
        branch["teams"][junior]["fields"].pop(field, None)
    branch["teams"][junior].pop("teamType")
    branch["teams"][main]["tier"] = 3
    with store.transaction():
        database.put(store.db, branch)
        database.migrate_club_links(store.db)
        database.migrate_club_links(store.db)
    new = database.get(store.db, branch["id"], 2)
    assert database.get(store.db, branch["id"], 1) == branch
    assert database.shares_organization(new, main, junior)
    assert new["teams"][main]["tier"] == 3
    assert new["players"] == branch["players"] and new["history"] == branch["history"]
    assert (
        max(
            r["revision"]
            for r in database.installed(store.db)
            if r["id"] == branch["id"]
        )
        == 2
    )
    ids = [
        next(i for i, r in new["rosters"].items() if r["team"] == tid)
        for tid in (main, junior)
    ]
    domain = database.match_input(new, ids)
    assert domain["teams"][junior]["teamType"] == "academy"
    assert (
        domain["teams"][junior]["organization"] == domain["teams"][main]["organization"]
    )
    store.db.close()


def test_every_stock_team_has_a_registered_local_garment():
    import csv
    import gzip
    import json
    from pathlib import Path
    from PIL import Image

    root = Path(__file__).resolve().parents[1]
    kits = json.loads((root / "frontend/src/kitArt.json").read_text())
    teams = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"][
        "teams"
    ]
    rows = csv.DictReader(
        (root / "docs/TEAM_KIT_COVERAGE.csv").read_text().splitlines()
    )
    assert {row["team_id"] for row in rows} == kits.keys() == teams.keys()
    for tid, item in kits.items():
        rig = item["rig"]
        with Image.open(
            root / "frontend/public/portraits/kits" / (tid + ".webp")
        ) as im:
            assert im.mode == "RGBA" and im.size == (rig["width"], rig["height"])
            assert im.getextrema()[3] == (0, 255)
        assert 0 < rig["span"] <= rig["width"]
        assert all(
            0 < x < limit
            for x, limit in zip(rig["collar"], (rig["width"], rig["height"]))
        )
