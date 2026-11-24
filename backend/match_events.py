"""The match ledger and its incremental scoreboard projection."""

from .match_rules import RULES, WEAPONS


def emit(w, kind, text, side=None, **data):
    w["serial"] += 1
    event = dict(id=w["serial"], round=w["round"], tick=w["tick"],
                 kind=kind, text=text, team=side, **data)
    w["events"].append(event)
    return event


def money(w, a, delta, reason):
    before = a["cash"]
    after = min(RULES["cap"], before + delta)
    if after < 0:
        raise ValueError("Недостаточно средств")
    event = emit(w, "money", f"{a['name']} · {reason} ({after - before:+}$)",
                 a["team"], player=a["id"], amount=after-before, balance=after, reason=reason)
    a["cash"] = event["balance"]
    if delta < 0 and reason.startswith("Покупка"):
        w["stats"][a["id"]]["spent"] -= event["amount"]
    return event


def damage(w, shooter, target, amount, weapon, head=False):
    if not target["hp"]:
        return
    amount = min(target["hp"], amount)
    enemy = shooter["team"] != target["team"]
    event = emit(w, "damage", f"{shooter['name']} → {target['name']} · {amount} HP",
                 shooter["team"], player=shooter["id"], target=target["id"],
                 amount=amount, weapon=weapon, head=head)
    target["hp"] -= event["amount"]
    if enemy:
        w["stats"][shooter["id"]]["damage"] += amount
        hits = target["attackers"]
        hits[shooter["id"]] = hits.get(shooter["id"], 0) + amount
    if target["hp"]:
        return
    ids = {a["id"]: a for a in w["agents"]}
    assists = [i for i, dmg in target["attackers"].items() if i != shooter["id"] and dmg >= 40]
    kills = w["kills"]
    trade = next((k for k in reversed(kills) if k["player"] == target["id"]
                  and w["tick"]-k["tick"] <= 50 and ids[k["target"]]["team"] == shooter["team"]), None)
    event = emit(w, "kill", f"{shooter['name']}   {weapon}   {target['name']}", player=shooter["id"],
                 target=target["id"], weapon=weapon, head=head, assists=assists,
                 trade=trade["target"] if trade else None, enemy=enemy, opening=enemy and not any(k["enemy"] for k in kills))
    kills.append(event)
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
        w["bomb"].update(carrier=None, x=target["x"], y=target["y"])
        emit(w, "drop", f"{target['name']} потерял C4", "T", x=target["x"], y=target["y"])
    target["evidence"] = dict(id=event["id"], round=w["round"],
                              text=f"Я выбыл в раунде {w['round']}. В следующий раз мне нужна поддержка.")
