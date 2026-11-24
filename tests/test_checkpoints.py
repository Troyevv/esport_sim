"""Real profiles from both on-disk formats shipped in PR #3."""

import gzip
import json
from pathlib import Path
import sqlite3

import pytest

from backend import checkpoints, match
from backend.store import Conflict, Store
from test_server import envelope


def restore(tmp_path, commit):
    path = tmp_path / "scenario.sqlite"
    fixture = Path(__file__).parent / "fixtures" / f"bo1-{commit}.sqlite.gz"
    path.write_bytes(gzip.decompress(fixture.read_bytes()))
    return path


def bodies(db):
    return {
        table: db.execute(f"SELECT body FROM {table}").fetchone()[0]
        for table in ("active", "slot")
    }


def rounds(db, world):
    return (
        [
            json.loads(
                db.execute(
                    "SELECT body FROM round_log WHERE digest=?", (key,)
                ).fetchone()[0]
            )
            for key in world["logs"]
        ]
        + world["archive"]
        + [world["events"]]
    )


@pytest.mark.parametrize("commit", ["67e384f", "761cc70", "1a51f40"])
def test_upgrade_active_and_manual_and_finish_match(tmp_path, commit):
    path = restore(tmp_path, commit)
    db = sqlite3.connect(path)
    original = bodies(db)
    receipts = list(db.execute("SELECT * FROM receipt ORDER BY id"))
    store = Store(path)
    assert dict(db.execute("SELECT source,body FROM checkpoint_backup")) == original
    assert list(db.execute("SELECT * FROM receipt ORDER BY id")) == receipts

    upgraded = bodies(db)
    for table, raw in upgraded.items():
        before, after = json.loads(original[table]), json.loads(raw)
        old, world = before.pop("world"), after.pop("world")
        assert before == after
        assert world["checkpointVersion"] == checkpoints.VERSION
        for key in old.keys() - {"history", "logs", "events", "agents", "plans", "checkpointVersion"}:
            assert world[key] == old[key]
        for player, prior in zip(world["agents"], old["agents"], strict=True):
            assert all(player[k] == value for k, value in prior.items())
            assert "approached" in player
        for side, plan in world["plans"].items():
            assert all(plan[k] == v for k, v in old["plans"][side].items())
            assert len(plan["orders"]["slots"]) == 5
            assert plan["captain"] in {
                p["id"] for p in world["agents"] if p["team"] == side
            }
        for prior, events in zip(rounds(db, old), rounds(db, world), strict=True):
            for e in prior:
                if e["kind"] == "round_end" and "side" not in e:
                    e.update(side=e["team"], team=None)
            assert prior == events
        for row, previous, events in zip(
            world["history"], old["history"], rounds(db, old)
        ):
            assert all(row[k] == v for k, v in previous.items())
            assert row["economy"] == {
                s: sum(
                    e["price"] for e in events if e["kind"] == "buy" and e["team"] == s
                )
                for s in ("T", "CT")
            }

    store.db.close()
    store = Store(path)
    assert bodies(db) == upgraded
    assert dict(db.execute("SELECT source,body FROM checkpoint_backup")) == original
    assert store.snapshot("full")["world"]["match"]["round"] == 2
    assert set(store.snapshot("T")["world"]["match"]["history"][0]["economy"]) == {"T"}
    store.apply(envelope(store.read(), "start"))
    assert store.tick()
    store.apply(envelope(store.read(), "load"))
    assert store.read()["world"] == json.loads(upgraded["slot"])["world"]
    store.apply(envelope(store.read(), "start"))
    assert store.tick()
    world = store.read()["world"]
    for _ in range(40000):
        if world["phase"] == "finished":
            break
        match.advance(world)
    assert world["phase"] == "finished"
    events_by_round = rounds(db, world)
    events = [e for batch in events_by_round for e in batch]
    assert [e["id"] for e in events] == list(range(1, world["serial"] + 1))
    assert len(world["history"]) == sum(world["score"])
    for summary, batch in zip(world["history"], events_by_round, strict=True):
        (end,) = [e for e in batch if e["kind"] == "round_end"]
        assert (end["side"], end["winner"]) == (summary["side"], summary["winner"])
        assert summary["economy"] == checkpoints.purchases(batch)
    for p in world["agents"]:
        own = [e for e in events if e.get("player") == p["id"]]
        stats = world["stats"][p["id"]]
        assert stats["k"] == sum(e["kind"] == "kill" and e["enemy"] for e in own)
        assert stats["d"] == sum(
            e["kind"] == "kill" and e["target"] == p["id"] for e in events
        )
        assert stats["spent"] == sum(e["price"] for e in own if e["kind"] == "buy")
        assert p["cash"] == sum(e["amount"] for e in own if e["kind"] == "money")
    db.close()
    store.db.close()


@pytest.mark.parametrize("damage", ["log", "economy", "future"])
def test_invalid_slot_rolls_back_both_checkpoints(tmp_path, damage):
    path = restore(tmp_path, "67e384f")
    db = sqlite3.connect(path)
    saved = json.loads(bodies(db)["slot"])
    world = saved["world"]
    if damage == "log":
        world["logs"][0] = "absent"
    elif damage == "economy":
        world["history"][0]["economy"] = {"T": 0, "CT": 0}
    else:
        world["checkpointVersion"] = 999
    db.execute("UPDATE slot SET body=?", (json.dumps(saved),))
    db.commit()
    before = bodies(db)
    blocks = list(db.execute("SELECT * FROM round_log"))
    with pytest.raises(Conflict, match="ручное сохранение"):
        Store(path)
    assert bodies(db) == before
    assert list(db.execute("SELECT * FROM round_log")) == blocks
    db.close()


def test_desktop_reports_failed_migration_before_browser_handoff(tmp_path, monkeypatch):
    import asyncio
    import socket
    import sys
    from backend.desktop import serve

    path = restore(tmp_path, "67e384f")
    db = sqlite3.connect(path)
    db.execute("DELETE FROM round_log")
    db.commit()
    db.close()
    monkeypatch.setattr(sys, "_MEIPASS", tmp_path, raising=False)
    index = tmp_path / "frontend" / "dist" / "index.html"
    index.parent.mkdir(parents=True)
    index.touch()  # The launcher checks the bundle before starting the database.
    descriptor = tmp_path / "instance.json"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        with pytest.raises(RuntimeError, match="журнал раунда 1"):
            asyncio.run(
                serve(tmp_path, descriptor, listener, lambda url: pytest.fail(url))
            )
    assert not descriptor.exists()
