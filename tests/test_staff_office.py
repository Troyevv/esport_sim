import gzip
import hashlib
import json

import pytest

from backend import (
    career,
    competition_scene,
    cs2_maps,
    database,
    scene_portraits,
    staff,
    veto,
)
from backend.store import Store
from tools.import_scene import starter


def test_model_and_daily_assignments():
    row = dict(role="analyst", preparation=75, name="A", team="club")
    pack = {"staff": {"a": row, "b": dict(row, team="away")}}
    c = dict(
        team="club",
        office=staff.office(),
        date="2026-11-25",
        queue=[
            dict(id=str(i), date="2026-11-25", bestOf=3, teams=["club", "away"])
            for i in range(4)
        ],
    )
    p = staff.profile("a", row)
    assert p == staff.profile("a", row)
    assert len(p["attributes"]) == 24 and all(
        0 <= n <= 100 for n in p["attributes"].values()
    )
    assert len(set(p["ratings"].values())) > 1 and len(p["ratings"]) == 8
    assert p["ratings"]["analyst"] > p["ratings"]["head"]
    assert set(p["philosophy"]) == set(staff.PREFERENCES)
    assert not staff.day_plan(c, pack, "club", c["date"])
    with pytest.raises(ValueError):
        staff.change(c, pack, dict(person="b", duty="veto"))
    for duty in ("veto", "opponent", "individual"):
        staff.change(c, pack, dict(person="a", duty=duty))
    for team, sid in (("club", "a"), ("away", "b")):
        jobs = staff.day_plan(c, pack, team, c["date"])
        assert jobs and {j["duty"] for j in jobs} <= {"veto", "opponent"}
        assert sum(j["cost"] for j in jobs) <= staff.capacity(
            staff.team_people(c, pack, team)[sid]
        )
        assert all(j["due"] == c["date"] and j["person"] == sid for j in jobs)
    jobs = staff.booked(c, pack, c["queue"][0])
    staff.record(c, jobs, c["date"])
    staff.record(c, jobs, c["date"])
    assert c["office"]["ledger"]["jobs"] == jobs
    c["queue"].pop(0)
    staff.change(c, pack, dict(person=None, duty="veto"))
    assert all(
        j["event"] == "0" or j["duty"] != "veto"
        for j in staff.day_plan(c, pack, "club", c["date"])
    )
    for key in staff.ROLES:
        staff.change(c, pack, dict(person="a", role=key))
        assert staff.team_people(c, pack, "club")["a"]["attributes"] == p["attributes"]


def test_assigned_specialist_drives_career_veto(monkeypatch):
    monkeypatch.setattr(cs2_maps, "installed", lambda: list(veto.ACTIVE))
    pack = starter()
    team = next(r["team"] for r in pack["staff"].values() if r["team"])
    c = career.create(pack, dict(name="Штаб", team=team, scope="full", mode="owner"))
    e = next(e for e in c["queue"] if team in e["teams"])
    p = next(sid for sid, r in pack["staff"].items() if r["team"] == team)
    manual = career.initial(pack, c, e)
    assert manual["series"]["stage"] == "veto"
    staff.change(c, pack, dict(person=p, duty="veto"))
    game = career.initial(pack, c, e)
    assert game["series"]["stage"] == "ready"
    work = game["series"]["work"][team]["veto"]
    assert work["person"] == p and work["quality"] == staff.quality(
        staff.team_people(c, pack, team)[p], "veto"
    )
    assert all(
        a["by"] == "staff" for a in game["series"]["actions"] if a["team"] == team
    )


def test_legacy_active_manual_and_new_assignments_survive_restart(tmp_path):
    store = Store(tmp_path / "profile.sqlite")
    pack = starter()
    sid, row = next(iter(pack["staff"].items()))
    st = store.read()
    c = career.create(
        pack, dict(name="До обновления", team=row["team"], scope="full", mode="manager")
    )
    del c["office"]
    st["career"] = c
    with store.transaction():
        store.write(st)
        store.careers.save(st, "1")
    store.db.close()
    store = Store(tmp_path / "profile.sqlite")
    for slot in ("active", "1"):
        state = store.read()
        if slot != "active":
            store.careers.load(state, c["id"], slot)
        assert state["career"] == dict(c, office=staff.office())
    assert store.db.execute("SELECT count(*) FROM checkpoint_backup").fetchone()[0] >= 2
    store.careers.change(state, "career-staff", dict(person=sid, duty="veto"))
    store.careers.change(state, "career-save", dict(slot="2"))
    store.careers.change(state, "career-staff", dict(person=None, duty="veto"))
    store.careers.load(state, c["id"], "2")
    assert state["career"]["office"]["duties"] == {"veto": sid}


def test_portrait_pack_complete_unique_and_addressed_by_content(tmp_path):
    raw = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    pack = competition_scene.extend(raw)
    assets = scene_portraits.catalog()
    store = Store(tmp_path / "portraits.sqlite")
    release = database.get(store.db, database.STAFF_RELEASE, 1)
    store.db.close()
    assert len(release["staff"]) == 44
    for edition in (starter(), pack, release):
        keys = list(edition["players"]) + list(edition["staff"])
        ids = [assets["people"][key] for key in keys]
        assert len(set(ids)) == len(ids)
    for roster in release["rosters"].values():
        if roster["name"] in ("BIG EQUIPA", "Shimmer", "girl kissers"):
            assert all(
                assets["assets"][assets["people"][pid]][2] == 35
                for pid in roster["players"]
            )
    for digest in assets["assets"]:
        assert hashlib.sha256(scene_portraits.read(digest)).hexdigest() == digest


def test_tactic_editor_drafts_are_real_idempotent_and_capacity_limited():
    from backend import tactics

    pack = starter()
    sid, row = next(iter(pack["staff"].items()))
    c = career.create(
        pack, dict(name="Тренер", team=row["team"], mode="owner", scope="full")
    )
    staff.change(c, pack, dict(duty="tactics", person=sid))
    request = dict(side="T", buy="Оружейная", map_id="depo")
    staff.prepare_draft(c, pack, request)
    job = staff.draft_job(c, "T", "Оружейная", "depo")
    assert job["plan"] == tactics.validate(job["plan"]) and job["person"] == sid
    staff.prepare_draft(c, pack, request)
    assert len(c["office"]["ledger"]["jobs"]) == 1
    staff.prepare_draft(c, pack, dict(request, side="CT"))
    with pytest.raises(ValueError, match="нет времени"):
        staff.prepare_draft(c, pack, dict(request, buy="Эко"))
