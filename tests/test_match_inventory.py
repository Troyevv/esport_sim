from copy import deepcopy
import json

from backend import checkpoints, match, match_ai, match_inventory as inventory
from backend.match_events import damage
from backend.match_rules import equipment_value
from backend.store import Store


def marker(w, a, view="full"):
    return next(p for p in match.project(w, view)["agents"] if p["id"] == a["id"])


def test_two_slots_drop_pickup_and_ammo():
    w = match.initial(23)
    donor, receiver, shooter = w["agents"][0], w["agents"][1], w["agents"][5]
    donor.update(cash=12000, ammo=4, reserve=8)
    assert match.purchase(w, donor, "AK-47")
    assert match.purchase(w, donor, "Desert Eagle")
    donor.update(ammo=2, reserve=0)
    assert inventory.slots(donor) == ("AK-47", "Desert Eagle")
    assert marker(w, donor)["secondary"] == "Desert Eagle"
    receiver.update(x=donor["x"], y=donor["y"], ammo=3, reserve=2)
    damage(w, shooter, donor, 100, "AWP", head=True)
    assert marker(w, donor)["primary"] is None
    assert marker(w, donor)["equipmentValue"] == 0
    receiver["blind"] = 12
    assert inventory.take_nearby(w, receiver) is None
    receiver["blind"] = 0
    assert match.project(w)["match"]["groundWeapons"][0]["weapon"] == "AK-47"
    gun = inventory.take_nearby(w, receiver)
    assert (
        inventory.in_hand(gun)
        == inventory.in_hand(receiver)
        == dict(weapon="AK-47", ammo=2, reserve=0)
    )
    assert not w["groundWeapons"] and inventory.take_nearby(w, shooter) is None
    receiver["ammo"] = 0
    inventory.switch_if_empty(receiver)
    assert inventory.in_hand(receiver) == dict(weapon="Glock", ammo=3, reserve=2)
    assert receiver["holster"] == dict(weapon="AK-47", ammo=0, reserve=0)
    inventory.validate(w)
    assert equipment_value(receiver) > equipment_value(shooter)


def test_pistol_exchange_and_grenade_use():
    w = match.initial(83)
    a, owner, ct = w["agents"][0], w["agents"][1], w["agents"][5]
    a.update(ammo=4, reserve=9, cash=16000)
    owner.update(cash=1000, x=a["x"], y=a["y"])
    assert match.purchase(w, owner, "Desert Eagle")
    owner.update(ammo=3, reserve=1)
    damage(w, ct, owner, 100, "HE")
    assert inventory.take_nearby(w, a)["weapon"] == "Desert Eagle"
    assert inventory.in_hand(w["groundWeapons"][0]) == dict(
        weapon="Glock", ammo=4, reserve=9
    )
    assert inventory.take_nearby(w, a) is None
    assert match.purchase(w, a, "Свет") and match.purchase(w, a, "Свет")
    assert marker(w, a)["utility"] == ["Свет", "Свет"]
    match_ai.throw(w, a, dict(x=a["x"], y=a["y"], utility="Свет"))
    assert marker(w, a)["utility"] == ["Свет"]
    assert w["recentEffects"][-1]["kind"] == "Свет"
    assert w["kills"][-1]["weapon"] == "HE"
    a["visible"] = [ct["id"]]
    assert {"weapon"} <= marker(w, ct, "T").keys()
    assert {"primary", "secondary", "utility", "equipmentValue"}.isdisjoint(
        marker(w, ct, "T")
    )


def test_upgrade_v5_keeps_score_helmets_ammo_and_backup(tmp_path):
    store = Store(tmp_path / "state.sqlite")
    state = store.read()
    w = state["world"] = match.initial(193)
    a = w["agents"][0]
    a.update(cash=8000, armor=48, helmet=True)
    match.purchase(w, a, "AK-47")
    a.update(ammo=5, reserve=17)
    state["world"].update(checkpointVersion=5, rules="depo-bo1.3")
    w.pop("groundWeapons")
    for p in w["agents"]:
        p.pop("holster")
    before = deepcopy(w)
    raw = json.dumps(state)
    assert store.upgrade_checkpoint(state, "active", raw)
    assert w["checkpointVersion"] == checkpoints.VERSION
    assert (
        a["holster"] == inventory.stocked("Glock") and w["agents"][5]["holster"] is None
    )
    assert (
        inventory.in_hand(a) == inventory.in_hand(before["agents"][0]) and a["helmet"]
    )
    assert all(
        w[key] == before[key]
        for key in ("scoreByTeam", "events", "firstAttackTeamId", "coachTeamId")
    )
    assert (
        store.db.execute(
            "SELECT body FROM checkpoint_backup WHERE source='active'"
        ).fetchone()[0]
        == raw
    )
    assert not store.upgrade_checkpoint(state, "active", json.dumps(state))


def test_save_and_resume_with_loose_weapon_and_live_slots(tmp_path):
    path = tmp_path / "resume.sqlite"
    store = Store(path)
    state = store.read()
    w = state["world"] = match.initial(293)
    match.begin_live(w)
    a, victim, ct = w["agents"][0], w["agents"][1], w["agents"][5]
    a.update(cash=12000)
    assert match.purchase(w, a, "AK-47") and match.purchase(w, a, "Desert Eagle")
    a["holster"]["ammo"] = 2
    damage(w, ct, victim, 100, "USP")
    saved = deepcopy(w)
    store.write(state)
    store.db.close()
    reopened = Store(path)
    restored = reopened.read()["world"]
    assert restored == saved
    for _ in range(55):
        match.advance(w)
        match.advance(restored)
    assert w == restored
    reopened.db.close()
