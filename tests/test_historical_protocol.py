"""The fixture was written by R3.3 (0d09f33), including real completed BO1s."""

import gzip
import json
import sqlite3
from copy import deepcopy
from pathlib import Path

import pytest

from backend import historical_protocol, scout_sources
from backend.career_store import checksum
from backend.store import Store
from tests.test_server import local_server, send


def legacy_database(path):
    fixture = Path(__file__).with_name("fixtures") / "career-0d09f33.sqlite.gz"
    path.write_bytes(gzip.decompress(fixture.read_bytes()))


def records(db, table):
    return db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()


def test_old_application_profile_restores_history_and_all_slots(tmp_path):
    path = tmp_path / "scenario.sqlite"
    legacy_database(path)
    with sqlite3.connect(path) as db:
        originals = dict(records(db, "career_report"))
        active_body = records(db, "active")[0][1]
        original = json.loads(active_body)["career"]
        original_slots = records(db, "career_slot")
        receipts = records(db, "receipt")

    for restart in range(2):
        with local_server(path) as client:
            detail = client.get("/api/career").json()["active"]
            assert detail["id"] == original["id"]
            for event in original["history"]:
                raw = json.loads(originals[event["result"]])
                assert checksum(originals[event["result"]]) == event["result"]
                report = client.get("/api/career/report/" + event["id"]).json()
                assert report["scoreByTeam"] == dict(zip(event["teams"], raw["score"]))
                assert report["winnerTeamId"] == event["teams"][raw["score"].index(max(raw["score"]))]
                for row, old in zip(report["stats"], raw["stats"], strict=True):
                    assert row == dict(old, teamId=event["teams"][old["club"]])
                for row, old in zip(report["rounds"], raw["rounds"], strict=True):
                    assert row == dict(old, winnerTeamId=event["teams"][old["winner"]])
            with sqlite3.connect(path) as db:
                backups = records(db, "checkpoint_backup")
                state = json.loads(records(db, "active")[0][1])
                tape = scout_sources.public_base(state["career"]["scouting"]["baseline"])
                assert len(tape) == 40
                assert all("entry" not in f["signals"] for rows in tape.values() for f in rows)
                assert ("active", active_body) in backups
                for cid, slot, _, body, _ in original_slots:
                    if json.loads(body)["career"]:
                        assert (cid + "/" + slot, body) in backups
                assert originals == dict(records(db, "career_report"))
                assert receipts == records(db, "receipt")
                now = (records(db, "active"), records(db, "career_slot"), backups)
            if restart:
                assert now == migrated
                for slot in ("1", "2", "auto.bak"):
                    send(client, "career-load", {"slot": slot})
                    assert client.get("/api/career").json()["active"]["id"] == original["id"]
                send(client, "career-quick", {"fixture": original["queue"][0]["id"]})
                history = client.get("/api/career").json()["active"]["history"]
                assert len(history) == len(original["history"]) + 1
            else:
                migrated = now


def test_failed_upgrade_rolls_back_every_career_and_is_retryable(tmp_path):
    path = tmp_path / "scenario.sqlite"
    legacy_database(path)
    tables = ("active", "slot", "career_slot", "career_report", "receipt")
    with sqlite3.connect(path) as db:
        previous = [records(db, table) for table in tables]
        db.execute("""CREATE TRIGGER interrupt_upgrade BEFORE UPDATE ON active
                      BEGIN SELECT RAISE(ABORT, 'interrupt upgrade'); END""")
    with pytest.raises(sqlite3.IntegrityError, match="interrupt upgrade"):
        Store(path)
    with sqlite3.connect(path) as db:
        assert previous == [records(db, table) for table in tables]
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='checkpoint_backup'").fetchone()
        db.execute("DROP TRIGGER interrupt_upgrade")
    store = Store(path)
    assert store.read()["career"]["scouting"]["baseline"]
    store.db.close()


def test_recovery_requires_evidence_for_this_match():
    teams = ["home", "away"]
    pack = {"rosters": {"old": {"team": "home", "players": ["p"]}}}
    c = {"teams": {"home": "old"}, "circuit": {"editions": {"cup": {"registrations": {
        "away": [{"version": 1, "players": ["p"]}, {"version": 2, "players": ["q"]}]
    }}}}}
    event = {"teams": teams}
    raw = {"rules": "depo-bo1.2", "stats": [{"player": "p"}, {"player": "q", "club": True}],
           "rounds": [{"winner": 1, "side": "T"}, {"side": "CT"}]}
    before = deepcopy(raw)
    def project(event, report):
        return historical_protocol.normalize(c, pack, event, report)
    old = project(event, raw)
    assert [s["teamId"] for s in old["stats"]] == ["home", None]
    assert [r["winnerTeamId"] for r in old["rounds"]] == ["away", None]
    assert project(event, old) == old and raw == before
    scoreboard = dict(raw, rounds=[{"score": [0, 1]}, {"score": [1, 1]}, {"score": [3, 2]}])
    assert [r["winnerTeamId"] for r in project(event, scoreboard)["rounds"]] == ["away", "home", None]
    assert project(dict(event, pcw=True), raw)["stats"][0]["teamId"] is None
    cup = dict(event, edition="cup", rosterVersions={"away": 1})
    assert [s["teamId"] for s in project(cup, raw)["stats"]] == ["away", None]
    rows = [{"player": "p", "club": 0}, {"player": "q", "teamId": "home", "club": 1}]
    conflict = project(cup, dict(raw, stats=rows))
    assert all(s["teamId"] is None for s in conflict["stats"])
    assert project(cup, conflict) == conflict
    state = {"scouting": {"trials": [], "private": {}, "public": {}}}
    scout_sources.played(state, {"teams": dict.fromkeys(teams)}, event, conflict)
    assert state["scouting"]["public"] == {}
    # Map order, including a reversed fixture order, is authoritative for that map.
    m = dict(raw, teams=list(reversed(teams)), stats=[{"player": "z", "club": 0}])
    series = dict(maps=[m], stats=[{"player": "z"}], rounds=[])
    assert project(event, series)["stats"][0]["teamId"] == "away"
