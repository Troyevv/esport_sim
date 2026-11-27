"""The match ledger and its incremental scoreboard projection."""

from . import match_inventory
from backend.match_rules import RULES, WEAPONS


def emit(w, kind, text, audience=None, **data):
    w["serial"] += 1
    event = dict(
        id=w["serial"],
        round=w["round"],
        tick=w["tick"],
        kind=kind,
        text=text,
        team=audience,
        **data,
    )
    w["events"].append(event)
    return event


def money(w, a, delta, reason):
    before = a["cash"]
    after = min(RULES["cap"], before + delta)
    if after < 0:
        raise ValueError("Недостаточно средств")
    event = emit(
        w,
        "money",
        f"{a['name']} · {reason} ({after - before:+}$)",
        a["team"],
        player=a["id"],
        amount=after - before,
        balance=after,
        reason=reason,
    )
    a["cash"] = event["balance"]
    if delta < 0 and reason.startswith("Покупка"):
        w["stats"][a["id"]]["spent"] -= event["amount"]
    return event


def impact(w, shooter, target, base, weapon, group):
    """Resolve one game hit into HP and armor loss, then use the single death ledger."""
    spec = WEAPONS.get(weapon)
    multiplier = {
        "head": spec.head_multiplier if spec else 1,
        "stomach": 1.25,
        "leg": 0.75,
    }.get(group, 1)
    raw = base * multiplier
    protected = group in ("chest", "arm", "stomach", "blast") or (
        group == "head" and target["helmet"]
    )
    if raw <= 0 or not target["hp"]:
        return
    armor_loss = 0
    if target["armor"] and protected:
        ratio = spec.penetration if spec else 0.5
        absorbed = min(raw * (1 - ratio), 2 * target["armor"])
        armor_loss = (
            min(target["armor"], max(1, round(absorbed * 0.5))) if absorbed else 0
        )
        raw -= absorbed
    target["armor"] -= armor_loss
    if not target["armor"]:
        target["helmet"] = False
    damage(
        w, shooter, target, max(1, int(raw)), weapon, group == "head", group, armor_loss
    )


def damage(w, shooter, target, amount, weapon, head=False, group=None, armor_loss=0):
    if not target["hp"]:
        return
    amount = min(target["hp"], amount)
    enemy = shooter["team"] != target["team"]
    event = emit(
        w,
        "damage",
        f"{shooter['name']} → {target['name']} · {amount} HP",
        shooter["team"],
        player=shooter["id"],
        target=target["id"],
        amount=amount,
        weapon=weapon,
        head=head,
        hitgroup=group,
        armorLoss=armor_loss,
    )
    target["lastHurt"] = w["tick"]
    target["hp"] -= event["amount"]
    if enemy:
        w["stats"][shooter["id"]]["damage"] += amount
        hits = target["attackers"]
        hits[shooter["id"]] = hits.get(shooter["id"], 0) + amount
    if target["hp"]:
        return
    ids = {a["id"]: a for a in w["agents"]}
    assists = [
        i for i, dmg in target["attackers"].items() if i != shooter["id"] and dmg >= 40
    ]
    kills = w["kills"]
    trade = next(
        (
            k
            for k in reversed(kills)
            if k["enemy"]
            and k["player"] == target["id"]
            and w["tick"] - k["tick"] <= 50
            and ids[k["target"]]["team"] == shooter["team"]
        ),
        None,
    )
    event = emit(
        w,
        "kill",
        f"{shooter['name']}   {weapon}   {target['name']}",
        player=shooter["id"],
        target=target["id"],
        weapon=weapon,
        head=head,
        assists=assists,
        trade=trade["target"] if trade else None,
        enemy=enemy,
        opening=enemy and not any(k["enemy"] for k in kills),
    )
    kills.append(event)
    match_inventory.drop_on_death(w, target, event["id"])
    if enemy:
        # The kill feed identifies the killer, never their position.
        for mate in ids.values():
            if mate["hp"] and mate["team"] == target["team"]:
                mate.update(tradeTarget=shooter["id"], tradeUntil=w["tick"] + 50)
    target.update(status="Выбыл", visible=[], path=[])
    stats = w["stats"]
    stats[target["id"]]["d"] += 1
    if enemy:
        stats[shooter["id"]]["k"] += 1
        stats[shooter["id"]]["hs"] += int(head)
        stats[shooter["id"]]["opening"] += int(event["opening"])
        money(w, shooter, WEAPONS[weapon].reward if weapon in WEAPONS else 300, "Фраг")
    for ident in assists:
        stats[ident]["a"] += 1
    if w["bomb"]["carrier"] == target["id"]:
        w["bomb"].update(carrier=None, **{k:target[k] for k in ("x","y","z") if k in target})
        emit(
            w, "drop", f"{target['name']} потерял C4", "T", x=target["x"], y=target["y"]
        )
    target["evidence"] = dict(
        id=event["id"],
        round=w["round"],
        text=f"Я выбыл в раунде {w['round']}. В следующий раз мне нужна поддержка.",
    )
