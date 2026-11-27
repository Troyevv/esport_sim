"""Permanent club identities for BO1. Numeric indices are legacy wire projections."""

from collections import Counter


def team_ids(w):
    return [w["domain"]["rosters"][rid]["team"] for rid in w["rosterIds"]]


def side_team(w, side):
    ids = {a["teamId"] for a in w["agents"] if a["team"] == side}
    if len(ids) != 1:
        raise ValueError("Сторона раунда не привязана к одной команде")
    return ids.pop()


def side_for(w, team_id):
    return next(a["team"] for a in w["agents"] if a["teamId"] == team_id)


def initialize(w):
    ids = team_ids(w)
    w["firstAttackTeamId"] = ids[0]
    w.setdefault("coachTeamId", ids[0])
    w["scoreByTeam"] = dict.fromkeys(ids, 0)
    w["winnerTeamId"] = None


def validate(w):
    ids = team_ids(w)
    if (
        len(set(ids)) != 2
        or w["firstAttackTeamId"] not in ids
        or w["coachTeamId"] not in ids
        or {side_team(w, side) for side in ("T", "CT")} != set(ids)
    ):
        raise ValueError("Некорректная привязка команд к сторонам")
    ledger = Counter()
    for row in w["history"]:
        tid = row["winnerTeamId"]
        if tid not in ids or row["winner"] != ids.index(tid):
            raise ValueError("Победитель раунда расходится с заявкой")
        ledger[tid] += 1
        if row["scoreByTeam"] != {t: ledger[t] for t in ids} or row["score"] != [
            ledger[t] for t in ids
        ]:
            raise ValueError("Счёт раунда расходится с историей")
    totals = {tid: ledger[tid] for tid in ids}
    winner = w["history"][-1]["winnerTeamId"] if w["phase"] == "finished" else None
    if (
        w["scoreByTeam"] != totals
        or w["score"] != [totals[t] for t in ids]
        or w["winnerTeamId"] != winner
        or (winner and totals[winner] != max(w["score"]))
    ):
        raise ValueError("Счёт матча расходится с историей раундов")


def upgrade(w):
    ids = team_ids(w)
    for agent in w["agents"]:
        agent.update(teamId=ids[agent["club"]], helmet=False)
    initialize(w)
    for row in w["history"]:
        row["winnerTeamId"] = ids[row["winner"]]
        w["scoreByTeam"][row["winnerTeamId"]] += 1
        row["scoreByTeam"] = w["scoreByTeam"].copy()
    if w["phase"] == "finished":
        w["winnerTeamId"] = w["history"][-1]["winnerTeamId"]
    validate(w)
