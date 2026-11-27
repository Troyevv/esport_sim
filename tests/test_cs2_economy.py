from copy import deepcopy

import pytest

from tests.reference_kernel import cs2_economy as eco, match, match_inventory
from backend import tactics


def setup(money, round_number=5):
    w = match.initial(42)
    squad = w["agents"][:5]
    w.update(round=round_number, streak=[1, 1])
    for a, cash in zip(squad, money):
        a["cash"] = cash
    return w, squad


def test_all_seven_calls_and_no_hidden_opponent_inventory():
    w, s = setup([800] * 5, 1)
    assert eco.decision(w, s)["scenario"] == eco.PISTOL
    w["round"] = 5
    assert eco.decision(w, s)["scenario"] == eco.ECO
    for a in s:
        a["cash"] = 3100
    assert eco.decision(w, s)["scenario"] == eco.HALF
    w["round"] = 12
    assert eco.decision(w, s)["scenario"] == eco.FORCE
    w["round"] = 5
    for a in s:
        a["cash"] = 6500
    assert eco.decision(w, s)["scenario"] == eco.FULL
    known = {p["id"]: dict(saved=None, balance=1800) for p in w["agents"][5:]}
    w["opponentEconomy"] = {"T": known}
    assert eco.decision(w, s)["scenario"] == eco.ANTI
    for enemy in w["agents"][5:]:
        enemy.update(cash=16000, weapon="AWP")
    assert eco.decision(w, s)["scenario"] == eco.ANTI
    for account in known.values():
        account.update(balance=5000)
    for a in s[:3]:
        match_inventory.equip(a, match_inventory.stocked("MAC-10"))
    plan = eco.decision(w, s)
    assert (plan["context"], plan["budget"]) == (eco.BONUS, eco.HALF)
    eco.buy(w, s, plan, match.purchase, None)
    assert all(match_inventory.slots(a)[0] == "MAC-10" for a in s[:3])


def test_individual_wallets_and_losses_limit_spending():
    w, s = setup([0, 900, 950, 13800, 16000])
    plan = eco.decision(w, s)
    assert plan["budget"] == eco.FULL
    eco.buy(w, s, plan, match.purchase, None)
    assert all(match_inventory.slots(a)[0] for a in s)
    assert any(
        e["kind"] == "buy" and e["recipient"] != e["player"] for e in w["events"]
    )
    w, s = setup([3100] * 5)
    plan = eco.decision(w, s)
    eco.buy(w, s, plan, match.purchase, None)
    assert all(a["cash"] + plan["lossIncome"] >= plan["nextTarget"] for a in s)
    assert all(a["cash"] >= 0 for a in s)
    w, s = setup([350, 500, 800, 1000, 1200])
    orig = [a["cash"] for a in s]
    eco.buy(w, s, eco.decision(w, s), match.purchase, None)
    assert [a["cash"] for a in s] == orig


def test_enemy_estimate_uses_only_public_facts():
    w, _ = setup([3200] * 5)
    altered = deepcopy(w)
    for a in altered["agents"][5:]:
        a.update(cash=16000, utility=["Дым", "HE"], weapon="AWP", armor=100)
    for g in (w, altered):
        eco.update_opponents(g, "CT", "Устранение")
    assert w["opponentEconomy"]["T"] == altered["opponentEconomy"]["T"]


def test_old_generic_rifle_board_follows_specific_plan():
    assert match.board_categories({"mapId": "de_train"}, eco.BONUS) == (
        eco.BONUS,
        "Оружейная",
    )
    assert match.board_categories({}, eco.FORCE) == ("Оружейная",)
    assert tactics.LEGACY_BUYS == ("Пистолетная", "Эко", "Оружейная")


def test_full_buy_upgrades_retained_light_gun_after_equipping_squad():
    w, squad = setup([16000] * 5)
    for a in squad:
        match_inventory.equip(a, match_inventory.stocked("MP9"))
    plan = eco.decision(w, squad)
    eco.buy(w, squad, plan, match.purchase, None)
    assert all(match_inventory.slots(a)[0] == "AK-47" for a in squad)
    assert all(len(a["utility"]) == 4 for a in squad)
    assert all(a["cash"] >= plan["nextTarget"] - plan["lossIncome"] for a in squad)
