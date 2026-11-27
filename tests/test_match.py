import json
import time
from copy import deepcopy
from uuid import uuid4

import pytest
from tests.test_server import envelope, local_server, send, snapshot

from tests.reference_kernel import match
from tests.reference_kernel import match_ai as ai
from backend import match as production
from backend.match_rules import RULES
from backend.store import Store


def until(w, condition, limit=40000):
    for _ in range(limit):
        if condition():
            return
        match.advance(w)
    pytest.fail(f"Unreached condition at {w['round']}, {w['phase']}, {w['tick']}")


def ledger(w):
    return [e for batch in w["archive"] + [w["events"]] for e in batch]


@pytest.mark.parametrize("seed", [1, 42, 610])
def test_complete_maps_reconcile_each_player_and_round(seed):
    w = match.initial(seed)
    until(w, lambda: w["phase"] == "finished")
    events = ledger(w)
    assert [e["id"] for e in events] == list(range(1, w["serial"] + 1))
    assert w["remaining"] == 3
    ends = [e for e in events if e["kind"] == "round_end"]
    assert len(ends) == sum(w["score"])
    assert [sum(e["winner"] == i for e in ends) for i in range(2)] == w["score"]
    assert all(
        h["reason"] == e["reason"] for h, e in zip(w["history"], ends, strict=True)
    )
    assert len({e["side"] for e in ends}) == 2
    assert set(k for e in events if e["kind"] == "throw" for k in [e["utility"]]) == {
        "Дым",
        "Свет",
        "Огонь",
        "HE",
        "Ложная",
    }
    for a in w["agents"]:
        id = a["id"]
        rows = [e for e in events if e.get("player") == id]
        own = w["stats"][id]
        assert own["k"] == sum(e["kind"] == "kill" and e["enemy"] for e in rows)
        assert own["d"] == sum(
            e["kind"] == "kill" and e["target"] == id for e in events
        )
        assert own["a"] == sum(
            e["kind"] == "kill" and id in e["assists"] for e in events
        )
        account = 0
        for e in rows:
            if e["kind"] == "money":
                account += e["amount"]
                assert account == e["balance"] and 0 <= account <= 16000
        assert account == a["cash"]
        assert own["spent"] == sum(e["price"] for e in rows if e["kind"] == "buy")
        assert 0 <= own["kast"] <= len(ends)


def duel():
    w = match.initial(10)
    match.begin_live(w)
    for a in w["agents"]:
        a["hp"] = 0
    attacker, defender = w["agents"][2], w["agents"][5]
    attacker.update(hp=100, x=235, y=35, utility=[])
    defender.update(hp=100, x=275, y=145, utility=[])
    return w, attacker, defender


def test_plant_duration_interrupt_and_expiry_precedence():
    w, t, ct = duel()
    match.advance(w)
    end = w["action"]["end"]
    assert end - w["tick"] == RULES["plant"]
    # A teammate can retrieve C4 from the dead carrier instead of inheriting progress.
    from tests.reference_kernel.match_events import damage

    damage(w, ct, t, 100, "USP")
    w["agents"][1].update(hp=100, x=t["x"], y=t["y"])
    match.advance(w)
    assert w["bomb"]["carrier"] == w["agents"][1]["id"]
    assert w["action"]["start"] > end - RULES["plant"]
    assert any(e["kind"] == "interrupt" for e in w["events"])
    w["deadline"] = w["action"]["end"]
    until(w, lambda: w["phase"] == "result")
    assert w["history"][-1]["reason"] == "Время"


@pytest.mark.parametrize(
    ("kit", "margin", "reason"),
    [(False, 1, "Обезвреживание"), (True, 1, "Обезвреживание"), (True, 0, "Взрыв C4")],
)
def test_dead_attackers_cannot_cancel_planted_bomb(kit, margin, reason):
    w, t, ct = duel()
    until(w, lambda: w["phase"] == "planted", 100)
    t["hp"] = 0
    ct.update(x=w["bomb"]["x"], y=w["bomb"]["y"], kit=kit)
    match.advance(w)
    assert w["phase"] == "planted"
    assert w["action"]["end"] - w["tick"] == (50 if kit else 100)
    w["deadline"] = w["action"]["end"] + margin
    until(w, lambda: w["phase"] == "result", 102)
    assert w["history"][-1]["reason"] == reason


def test_hidden_enemy_radio_and_smoke():
    w, a, b = duel()
    a.update(x=35, y=55, heading=0)
    b.update(x=55, y=55)
    twin = deepcopy(w)
    twin["agents"][5]["y"] = 65
    match.advance(w)
    match.advance(twin)
    assert w["agents"][2] == twin["agents"][2]
    a.update(x=25, y=55, heading=0)
    b.update(x=35, y=55)
    mate = w["agents"][1]
    mate.update(hp=100, x=235, y=15)
    ai.observe(w, [a, b, mate])
    assert b["id"] in a["visible"] and not mate["knowledge"]
    pos = a["knowledge"][b["id"]].copy()
    w["effects"] = [dict(kind="Дым", land=0, end=200, x=30, y=55, radius=4)]
    b["x"] = 36
    for _ in range(6):
        w["tick"] += 1
        ai.observe(w, [a, b, mate])
    assert not a["visible"] and a["knowledge"][b["id"]] == pos
    assert mate["knowledge"][b["id"]] == dict(pos, source="Радио")
    assert b["id"] not in {p["id"] for p in match.project(w, "T")["agents"]}


def test_overtime_sides_money_and_timeout_budget():
    w = match.initial(21)
    w["remaining"] = 0
    for n in range(1, 31):
        assert w["round"] == n
        if n in (25, 28):
            assert all(a["cash"] == RULES["overtimeMoney"] for a in w["agents"])
        side = w["agents"][0 if n % 2 else 5]["team"]
        match.finish_round(w, side, "Устранение")
        assert w["phase"] == "result" and w["remaining"] == 0
        match.next_round(w)
    for _ in range(4):
        match.finish_round(w, w["agents"][0]["team"], "Устранение")
        if w["phase"] != "finished":
            match.next_round(w)
    assert w["score"] == [19, 15] and w["phase"] == "finished"


@pytest.mark.parametrize("speed", [8, 128])
def test_engine_and_store_replay_share_all_events_after_midround_load(tmp_path, speed):
    store = Store(tmp_path / "match.sqlite")

    def command(kind, value=None):
        s = store.read()
        store.apply(
            dict(
                id=str(uuid4()),
                context=s["context"],
                revision=s["revision"],
                kind=kind,
                value=value,
            )
        )

    try:
        command("match", 17)
        command("start")
        for _ in range(171):
            store.tick()
        command("save")
        command("speed", 8)
        for _ in range(10):
            store.tick()
        command("load")
        command("speed", speed)
        while store.read()["running"]:
            store.tick()
        server = store.read()["world"]
        archive = [
            json.loads(
                store.db.execute(
                    "select body from round_log where digest=?", (ref,)
                ).fetchone()[0]
            )
            for ref in server.pop("logs")
        ]
        server["archive"] = archive
        headless = production.initial(17)
        production.play_map(headless)
        assert server == json.loads(json.dumps(headless))
    finally:
        store.db.close()


def test_network_timeout_receipts_pause_save_and_reconnect(tmp_path):
    with local_server(tmp_path / "local.sqlite") as client:
        send(client, "match", 610)
        for phase in ["freeze", "pause", "live"]:
            if phase == "pause":
                send(client, "pause")
            elif phase == "live":
                send(client, "speed", 8)
                send(client, "start")
                deadline = time.monotonic() + 4
                while snapshot(client)["world"]["match"]["phase"] == "freeze":
                    assert time.monotonic() < deadline
                    time.sleep(0.03)
            assert (
                client.post(
                    "/api/command", json=envelope(snapshot(client), "call", "Выход B")
                ).status_code
                == 422
            )
        request, result = send(client, "timeout")
        assert client.post("/api/command", json=request).json() == result
        send(client, "speed", 128)
        for remaining in [2, 1, 0]:
            if remaining != 2:
                send(client, "timeout")
            deadline = time.monotonic() + 8
            while (s := snapshot(client))["world"]["match"]["phase"] != "timeout":
                assert time.monotonic() < deadline
                time.sleep(0.03)
            assert s["world"]["match"]["remaining"] == remaining
            assert not s["running"]
            send(client, "call", "Выход B")
            send(client, "save")
            send(client, "load")
            assert snapshot(client)["world"]["match"]["call"] == "Выход B"
            send(client, "resume")
        assert (
            client.post(
                "/api/command", json=envelope(snapshot(client), "timeout")
            ).status_code
            == 422
        )


def test_flash_he_fire_and_route_safety():
    w, a, b = duel()
    a.update(x=25, y=55)
    b.update(x=35, y=55, hp=100)
    ids = {p["id"]: p for p in w["agents"]}
    for name in ("Свет", "HE", "Огонь"):
        a["utility"] = [name]
        ai.throw(w, a, b)
        flight = w["effects"][-1]
        w["tick"] = flight["land"] - 1
        ai.apply_effects(w, ids)
        assert b["hp"] == 100
        w["tick"] += 1
        ai.apply_effects(w, ids)
        if name == "Свет":
            assert b["blind"] > w["tick"]
        else:
            assert b["hp"] < 100
        b["hp"] = 100
        w["effects"] = []
    a.update(x=25, y=55, path=[], dest=[])
    assert not ai.walk(a, (55, 55), 1, [dict(x=35, y=55, radius=8)])
    assert (a["x"], a["y"]) == (25, 55)


def test_side_view_removes_hidden_gear_and_intermediate_motion():
    w = match.initial(101)
    match.begin_live(w)
    until(w, lambda: any(a["visible"] for a in w["agents"] if a["team"] == "CT"))
    view = match.project(w, "CT")
    rivals = [a for a in view["agents"] if a["team"] == "T"]
    assert rivals
    assert all("cash" not in a and "hp" not in a and not a["knowledge"] for a in rivals)
    assert set(view["match"]["plans"]) == {"CT"}
    assert all(e["team"] in (None, "CT") for e in view["events"])


def test_timeout_comments_reference_author_experience_and_survive_boundary():
    w = match.initial(42)
    until(w, lambda: w["round"] == 1 and w["phase"] == "result")
    match.command(w, "timeout")
    until(w, lambda: w["phase"] == "timeout")
    events = {e["id"]: e for e in ledger(w)}
    assert w["feedback"]
    for feedback in w["feedback"]:
        author = next(p for p in w["agents"] if p["name"] == feedback["player"])
        source = events[feedback["id"]]
        assert source["round"] == feedback["round"] and author["club"] == 0
        assert (
            source["target" if source["kind"] == "kill" else "player"] == author["id"]
        )
    saved = json.loads(json.dumps(w))
    for checkpoint in [w, saved]:
        match.command(checkpoint, "call", "Выход B")
        match.command(checkpoint, "resume")
        until(checkpoint, lambda: checkpoint["phase"] == "finished")
    assert json.dumps(w, sort_keys=True) == json.dumps(saved, sort_keys=True)


def test_shot_targets_only_the_position_available_at_decision_time():
    w, a, b = duel()
    a.update(x=25, y=55)
    sight = dict(id=b["id"], x=35, y=55)
    # Between observation and resolution the target is now behind the solid pillar.
    b.update(x=55, y=55)
    before = a["ammo"]
    ai.shoot(w, a, sight, b)
    shot = w["traces"][-1]
    assert (shot["tx"], shot["ty"]) == (35, 55)
    assert a["ammo"] == before - 1 and b["hp"] == 100
