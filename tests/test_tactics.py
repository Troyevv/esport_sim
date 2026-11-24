import json
from copy import deepcopy
from uuid import uuid4

import pytest

from backend import engine, match, tactic_library, tactic_preview, tactics
from backend.match_events import damage
from backend.store import Conflict, Store
from test_server import envelope, local_server, send, snapshot


def hand_plan(side="T", buy="Пистолетная"):
    # Three independently authored plans. Coordinates belong to the fictional Depo board.
    s = tactics.step
    if side == "CT":
        slots = [
            [s("move", (275, 95)), s("face", (235, 95), seconds=3)],
            [s("hold", (275, 105), seconds=4)],
            [],
            [s("exit", (265, 145))],
            [s("wait", (275, 125), seconds=2), s("retreat", (285, 125))],
        ]
        name = "Восточная дуга"
    elif buy == "Эко":
        slots = [
            [s("wait", (25, 105), seconds=2), s("exit", (95, 105))],
            [],
            [s("plant", (215, 165))],
            [],
            [s("hold", (45, 125), seconds=3)],
        ]
        name = "Пауза у депо"
    else:
        slots = [
            [s("move", (55, 105)), s("throw", (65, 105), utility="Дым")],
            [s("face", (55, 115), seconds=4)],
            [s("plant", (235, 35))],
            [s("hold", (65, 105), seconds=2)],
            [s("retreat", (35, 125))],
        ]
        name = "Северная петля"
    return dict(
        format=1,
        map="depo",
        geometry=2,
        side=side,
        buy=buy,
        name=name,
        id=str(uuid4()),
        revision=0,
        slots=slots,
    )


@pytest.mark.parametrize(
    "side,buy,seed",
    [("T", "Пистолетная", 41), ("T", "Эко", 5), ("CT", "Оружейная", 17)],
)
def test_authored_board_runs_in_complete_bo1(side, buy, seed):
    board = dict(hand_plan(side, buy), revision=1)
    w = match.initial(seed)
    match.assign(w, board)
    for _ in range(50000):
        match.advance(w)
        if w["phase"] == "finished":
            break
    assert w["phase"] == "finished"
    events = [e for batch in [*w["archive"], w["events"]] for e in batch]
    used = [h for h in w["history"] if h.get("tactic") == tactics.reference(board)]
    assert used
    assert len(used) == sum(e["kind"] == "board" for e in events)
    assert all(h["tactic"]["side"] == side for h in used)
    assert any(e["kind"] == "board_step" and e["team"] == side for e in events)
    if seed == 41:
        assert any(
            e["kind"] == "throw"
            and e["utility"] == "Дым"
            and (e["x"], e["y"]) == (65, 105)
            for e in events
        )
    print(f"{seed}: {board['name']}, {w['score']}, раундов по плану {len(used)}")


def test_preview_matches_real_bo1_and_does_not_mutate_draft():
    plan = hand_plan()
    copy = deepcopy(plan)
    preview = tactic_preview.simulate(plan)
    w = match.initial(42)
    match.assign(w, dict(plan, revision=1))
    match.begin_live(w)
    for i, frame in enumerate(preview["frames"]):
        assert frame == [
            [a["x"], a["y"], round(a["heading"], 3), a["hp"]] for a in w["agents"]
        ]
        if i + 1 < len(preview["frames"]):
            match.advance(w)
    assert w["phase"] == "result"
    assert plan == copy


def test_fire_contact_and_casualty_interrupt_board_with_local_evidence():
    plan = dict(hand_plan(), revision=1)
    w = match.initial(42)
    match.assign(w, plan)
    match.begin_live(w)
    leader, support = w["agents"][0], w["agents"][4]
    enemy = w["agents"][5]
    # Visible fire occupies the next cell. The authored destination stays pending.
    fire = dict(kind="Огонь", x=35, y=105, land=0, end=50, radius=6, player=enemy["id"])
    w["effects"].append(fire)
    match.advance(w)
    assert leader["status"] == "Пережидает огонь за укрытием"
    assert leader["stepIndex"] == 0 and leader["x"] == 25
    w["effects"].clear()
    # A direct contact takes precedence over reaching the next waypoint.
    enemy.update(x=45, y=105, hp=100)
    leader["utility"].clear()
    match.advance(w)
    assert enemy["id"] in leader["knowledge"] and leader["status"] == "Держит контакт"
    # The new captain and surviving support coordinate without access to hidden targets.
    enemy.update(x=285, y=95)
    damage(w, enemy, leader, 100, "USP")
    support.update(x=115, y=105, path=[], dest=[], knowledge={}, visible=[])
    match.advance(w)
    assert w["plans"]["T"]["captain"] == w["agents"][1]["id"]
    assert any(
        e["kind"] == "adapt" and "потери союзника" in e["text"] for e in w["events"]
    )


@pytest.mark.parametrize(
    "modify,diagnostic",
    [
        (lambda p: p.update(geometry=1), "геометрии"),
        (lambda p: p.update(side="CT"), "установку"),
        (lambda p: p["slots"][0][0].update(x=5), "стена"),
        (lambda p: p.update(buy="Эко"), "граната недоступна"),
        (lambda p: p["slots"][0][1].update(utility="нет"), "граната"),
        (lambda p: p["slots"][1][0].update(seconds=-1), "длительность"),
    ],
)
def test_invalid_edit_rolls_back_without_touching_library(tmp_path, modify, diagnostic):
    store = Store(tmp_path / "board.sqlite")
    draft = hand_plan()
    store.apply(envelope(store.read(), "tactic-save", draft))
    saved = tactic_library.catalog(store.db)
    draft["revision"] = 1
    modify(draft)
    with pytest.raises(ValueError, match=diagnostic):
        store.apply(envelope(store.read(), "tactic-save", draft))
    assert tactic_library.catalog(store.db) == saved
    store.db.close()


def test_pinned_versions_receipts_timeout_rules_and_save_restart(tmp_path):
    path = tmp_path / "board.sqlite"
    s = Store(path)

    def apply(kind, value=None):
        cmd = envelope(s.read(), kind, value)
        result = s.apply(cmd)
        assert s.apply(cmd) == result

    board = hand_plan()
    apply("tactic-save", board)
    ref = {"id": board["id"], "revision": 1}
    apply("match", 41)
    apply("tactic-assign", ref)
    apply("start")
    apply("pause")
    with pytest.raises(ValueError, match="тайм-аут"):
        apply("tactic-assign", ref)
    apply("timeout")
    apply("tactic-assign", ref)
    apply("save")
    apply("tactic-save", dict(board, revision=1, name="Новая версия"))
    with pytest.raises(Conflict, match="другом устройстве"):
        apply("tactic-save", dict(board, revision=1))
    apply("tactic-delete", dict(ref, revision=2))
    assert not any(p["id"] == ref["id"] for p in tactic_library.catalog(s.db)["plans"])
    assert s.db.execute(
        "SELECT revision,familiarity FROM tactic_mastery WHERE id=? ORDER BY revision",
        (ref["id"],),
    ).fetchall() == [(1, 0), (2, 0)]
    assert (
        s.db.execute("SELECT count(*) FROM tactic WHERE id=?", (ref["id"],)).fetchone()[
            0
        ]
        == 3
    )
    s.db.close()
    s = Store(path)
    apply("load")
    assert s.read()["world"]["remaining"] == 2
    apply("resume")
    apply("speed", 8)
    while s.read()["world"]["phase"] != "live":
        s.tick()
    assert s.read()["world"]["plans"]["T"]["board"]["name"] == board["name"]
    for _ in range(5):
        s.tick()
    apply("save")
    expected = deepcopy(s.read()["world"])
    s.db.close()
    s = Store(path)
    apply("load")
    for _ in range(8):
        match.advance(expected)
    s.tick()
    assert s.read()["world"] == json.loads(json.dumps(expected))
    s.db.close()


def test_api_assignment_windows_and_authoritative_side(tmp_path):
    with local_server(tmp_path / "tactics.sqlite") as client:
        send(client, "match", 22)
        board = hand_plan()
        send(client, "tactic-save", board)
        ref = dict(id=board["id"], revision=1)
        send(client, "tactic-assign", ref)
        send(client, "start")
        send(client, "pause")

        def reject(value):
            response = client.post(
                "/api/command", json=envelope(snapshot(client), "tactic-assign", value)
            )
            assert response.status_code == 422

        reject(ref)
        send(client, "timeout")
        reject(dict(id="std-CT-0", revision=1))
        reject(dict(id="std-T-2", revision=1))
        send(client, "tactic-assign", ref)
        send(client, "resume")
        reject(ref)
        assert snapshot(client)["world"]["match"]["remaining"] == 2
