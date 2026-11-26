"""Coordinated freeze-time spending and an opponent estimate from public information."""

from collections import Counter

from . import match_inventory
from .match_rules import PRICES, RULES, SIDEARMS, WEAPONS

PISTOL, ECO, HALF, FORCE, FULL = "Пистолетная", "Эко", "Частичная", "Форс", "Полная"
ANTI, BONUS = "Антиэко", "Бонусная"
SCENARIOS = (PISTOL, ECO, HALF, FORCE, FULL, ANTI, BONUS)
RIFLE = {"T": "AK-47", "CT": "M4A1-S"}
SMG = {"T": "MAC-10", "CT": "MP9"}


def loss_income(level):
    return min(RULES["lossMax"], RULES["lossBase"] + RULES["lossStep"] * level)


def items_for(actor, site, profile, board):
    """A saved board has priority over optional lane utility."""
    slot = actor["slot"]
    required = []
    if board:
        required = [s["utility"] for s in board["slots"][slot] if s["kind"] == "throw"]
    side, role = actor["team"], actor["playingRole"]
    if side == "CT":
        extras = ["Огонь", "Дым"] if slot in (0, 1) else ["Свет", "Дым"]
    elif role == "support":
        extras = ["Дым", "Свет"]
    elif role == "entry":
        extras = ["Свет", "HE"]
    elif site and len(profile.get(site, [[], []])[0]) > 1:
        extras = ["Дым", "Свет"]
    else:
        extras = ["Свет", "Огонь"]
    if role == "support":
        extras += ["Свет", "HE"]
    elif slot in (0, 1):
        extras += ["HE"]
    # A group with rifles can carry utility for both entry and postplant.
    # Required board throws retain priority when the four inventory slots fill.
    extras += ["Дым", "Свет", "Огонь" if side == "CT" else "HE"]
    options = list(required)
    for g in extras:
        if options.count(g) < (2 if g == "Свет" else 1):
            options.append(g)
    return options[:4]


def target_cost(a, side, grenades):
    needs = Counter(grenades) - Counter(a["utility"])
    return (
        (650 if a["armor"] < 45 else 0)
        + (350 if not a["helmet"] else 0)
        + (400 if side == "CT" and a["slot"] in (0, 1) and not a["kit"] else 0)
        + sum(PRICES[g] * n for g, n in needs.items())
    )


def affordable_guns(squad, wallets, price):
    armed = {a["id"] for a in squad if match_inventory.slots(a)[0]}
    # An unarmed player can receive a drop only if a single payer can fund it.
    return min(
        len(squad), len(armed) + sum(max(0, wallets[a["id"]]) // price for a in squad)
    )


def decision(
    w, squad, call=None, *, site=None, profile=None, board=None, requested=None
):
    side = squad[0]["team"]
    club = squad[0]["club"]
    n = w["round"]
    half = RULES["half"] if n <= 2 * RULES["half"] else RULES["overtimeHalf"]
    remaining = half - (n - 1) % half
    income = loss_income(w["streak"][club])
    rifle = WEAPONS[RIFLE[side]].price
    needs = {a["id"]: items_for(a, site, profile or {}, board) for a in squad}
    costs = {a["id"]: target_cost(a, side, needs[a["id"]]) for a in squad}
    wallets = {a["id"]: a["cash"] - costs[a["id"]] for a in squad}
    rifles = affordable_guns(squad, wallets, rifle)
    light = sum(match_inventory.slots(a)[0] in ("MP9", "MAC-10", "Nova") for a in squad)
    estimate = w.get("opponentEconomy", {}).get(side, {})
    enemy_side = "CT" if side == "T" else "T"
    likely_guns = sum(
        bool(r["saved"]) or r["balance"] >= WEAPONS[RIFLE[enemy_side]].price
        for r in estimate.values()
    )
    low_opponent = len(estimate) == 5 and likely_guns <= 1
    # Budget after a loss with all five eliminated; no assumed kills, plant or donated future guns.
    next_kit = rifle + 1000 + PRICES["Дым"] + PRICES["Свет"]
    reserves = {a["id"]: min(a["cash"], max(0, next_kit - income)) for a in squad}
    spare = sum(a["cash"] - reserves[a["id"]] for a in squad)
    match_target = RULES["half"] + 1 if n <= 24 else 16 + 3 * ((n - 25) // 6)
    must_buy = remaining == 1 or w["score"][1 - club] >= match_target - 1
    pistol = n in (1, RULES["half"] + 1)
    if requested in SCENARIOS:
        budget = requested
    elif pistol:
        budget = PISTOL
    elif call == "Экономить":
        budget = ECO
    elif (
        low_opponent and affordable_guns(squad, wallets, WEAPONS[SMG[side]].price) >= 4
    ):
        budget = FULL
    elif rifles >= 4:
        budget = FULL
    elif must_buy or (rifles >= 3 and (low_opponent or light >= 2)):
        budget = FORCE
    elif spare >= 2 * PRICES["Свет"] + PRICES["Дым"]:
        budget = HALF
    else:
        budget = ECO
    context = None
    if requested in (ANTI, BONUS):
        context, budget = requested, FULL if requested == ANTI else HALF
    elif budget not in (PISTOL, ECO) and low_opponent:
        context = ANTI
    elif (
        budget not in (PISTOL, ECO)
        and light >= 2
        and len(estimate) == 5
        and likely_guns >= 3
        and sum(max(0, wallets[a["id"]] - reserves[a["id"]]) // rifle for a in squad) < light
        and not must_buy
    ):
        context = BONUS
    if context == BONUS:
        budget = HALF
    limits = {
        a["id"]: (
            0
            if budget == ECO
            else a["cash"] - reserves[a["id"]]
            if budget == HALF
            else a["cash"]
        )
        for a in squad
    }
    return dict(
        budget=budget,
        context=context,
        scenario=context or budget,
        limit=limits,
        needs=needs,
        lossIncome=income,
        roundsLeft=remaining,
        opponentGuns=likely_guns if estimate else None,
        nextTarget=next_kit,
        expectedAfterLoss={
            a["id"]: min(RULES["cap"], a["cash"] - limits[a["id"]] + income)
            for a in squad
        },
    )


def buy(w, squad, strategy, purchase, board):
    budget, context = strategy["budget"], strategy["context"]
    if budget == ECO:
        return
    side = squad[0]["team"]
    funds = strategy["limit"].copy()

    def pay(p, item, recipient=None):
        price = WEAPONS[item].price if item in WEAPONS else PRICES[item]
        if price <= funds[p["id"]] and purchase(w, p, item, recipient):
            funds[p["id"]] -= price
            return True
        return False

    def grenades(a, required, legacy=False):
        for g in (Counter(required) - Counter(a["utility"])).elements():
            if len(a["utility"]) < 4 and a["utility"].count(g) < (
                2 if legacy or g == "Свет" else 1
            ):
                pay(a, g)

    def protect(a):
        if a["armor"] < 45:
            pay(a, "Броня")

    for a in squad:
        if board:
            grenades(
                a,
                [
                    s["utility"]
                    for s in board["slots"][a["slot"]]
                    if s["kind"] == "throw"
                ],
                legacy=board["format"]==1,
            )
    if budget == PISTOL:
        # Assign support utility and a CT kit before others buy Kevlar.
        for a in squad:
            if side == "CT" and a["slot"] == 1 and not a["kit"]:
                pay(a, "Набор")
            if a["playingRole"] == "support" or (side == "CT" and a["slot"] == 1):
                grenades(a, strategy["needs"][a["id"]])
            protect(a)
        return
    for a in squad:
        protect(a)
    rifle, smg = RIFLE[side], SMG[side]
    unarmed = [a for a in squad if not match_inventory.slots(a)[0]]
    # Equip the entry and AWP roles while donors still have a full gun's price.
    unarmed.sort(
        key=lambda a: (
            a["playingRole"] not in ("entry", "awper"),
            funds[a["id"]],
            a["slot"],
        )
    )
    for index, a in enumerate(unarmed):
        choices = [rifle, smg]
        if context == ANTI and a["playingRole"] != "awper":
            choices = [smg, rifle]
        if a["playingRole"] == "awper" and budget == FULL and context != ANTI:
            if (
                sum(funds.values())
                >= 4750 + WEAPONS[rifle].price * (len(unarmed) - index - 1) + 500
            ):
                choices.insert(0, "AWP")
        if budget in (FORCE, HALF):
            choices.append("Desert Eagle")
        for item in choices:
            payers = sorted(
                squad,
                key=lambda p: (
                    funds[p["id"]] < WEAPONS[item].price,
                    p is not a,
                    -funds[p["id"]],
                    p["slot"],
                ),
            )
            if any(pay(p, item, a if p is not a else None) for p in payers):
                break
    for a in sorted(squad, key=lambda p: (p["playingRole"] != "support", p["slot"])):
        if a["armor"] and not a["helmet"] and (budget == FULL or context == ANTI):
            pay(a, "Шлем")
        if side == "CT" and not a["kit"] and sum(p["kit"] for p in squad) < 2:
            pay(a, "Набор")
        grenades(a, strategy["needs"][a["id"]])
    if budget == FULL and not context and all(match_inventory.slots(a)[0] for a in squad):
        # Upgrade a retained close-range weapon after buying the team's kit.
        # Preserve enough cash to replace the owner's gun after a lost round.
        for a in squad:
            primary = match_inventory.slots(a)[0]
            if primary in ("MP9", "MAC-10", "Nova", "Negev"):
                reserve = max(0, strategy["nextTarget"] - strategy["lossIncome"])
                if funds[a["id"]] >= WEAPONS[rifle].price + reserve:
                    pay(a, rifle)



def update_opponents(w, winner, reason):
    """Use only the public score/kill feed, the plant and the captain's received reports."""
    memory = w.setdefault("opponentEconomy", {})
    kills = w["kills"]
    dead = {e["target"] for e in kills}
    for side in ("T", "CT"):
        rival = "CT" if side == "T" else "T"
        roster = [a["id"] for a in w["agents"] if a["team"] == rival]
        club = next(a["club"] for a in w["agents"] if a["team"] == rival)
        income = (
            (
                RULES["objectiveWin"]
                if reason in ("Взрыв C4", "Обезвреживание")
                else RULES["win"]
            )
            if rival == winner
            else loss_income(w["streak"][club])
        )
        if rival == "T" and reason == "Обезвреживание":
            income += 600
        if rival == "CT":
            income += 50 * sum(1 for k in kills if k["enemy"] and k["player"] in roster)
        known = {
            pid: r["weapon"]
            for pid, r in w["plans"].get(side, {}).get("economicSightings", {}).items()
        }
        for event in kills:
            if event["player"] in roster and event["weapon"] in WEAPONS:
                known[event["player"]] = event["weapon"]
        accounts = memory.setdefault(side, {})
        for pid in roster:
            prior = accounts.get(pid, dict(balance=RULES["startMoney"], saved=None))
            gun = known.get(pid, prior["saved"])
            bought = (
                WEAPONS[gun].price if gun in WEAPONS and gun != prior["saved"] else 0
            )
            # Unknown vest/utility spending is an estimate, never an inventory read.
            predicted = max(0, prior["balance"] - bought)
            if not gun and predicted >= WEAPONS[RIFLE[rival]].price + 650:
                predicted -= WEAPONS[RIFLE[rival]].price
            predicted = max(0, predicted - min(1000, predicted))
            reward = sum(
                WEAPONS[k["weapon"]].reward if k["weapon"] in WEAPONS else 300
                for k in kills
                if k["enemy"] and k["player"] == pid
            )
            paid = (
                0 if rival == "T" and reason == "Время" and pid not in dead else income
            )
            accounts[pid] = dict(
                balance=min(RULES["cap"], predicted + paid + reward),
                saved=gun if pid not in dead and gun not in SIDEARMS else None,
            )
