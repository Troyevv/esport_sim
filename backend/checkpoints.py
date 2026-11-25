"""Persisted BO1 checkpoint format, independent of engine and map versions."""

import hashlib
import json

from .match_rules import role_orders
from . import tactics

VERSION = 6


class CheckpointError(ValueError):
    pass


def purchases(events):
    totals = {"T": 0, "CT": 0}
    for event in events:
        if event["kind"] == "buy":
            totals[event["team"]] += event["price"]
    return totals


def put_round(db, events):
    body = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(body.encode()).hexdigest()
    db.execute("INSERT OR IGNORE INTO round_log VALUES(?,?)", (digest, body))
    return digest


def upgrade_match(db, world):
    """Upgrade both unmarked PR formats, including saves continued between builds."""
    logs = world.get("logs", [])
    if len(logs) != world["round"] - 1 or len(world["history"]) != len(logs) + int(
        world["phase"] in ("result", "finished")
    ):
        raise CheckpointError("Число журналов не соответствует истории раундов")
    for n, history in enumerate(world["history"], start=1):
        archived = n <= len(logs)
        if archived:
            digest = logs[n - 1]
            row = db.execute(
                "SELECT body FROM round_log WHERE digest=?", (digest,)
            ).fetchone()
            if not row or hashlib.sha256(row[0].encode()).hexdigest() != digest:
                raise CheckpointError(f"Отсутствует или повреждён журнал раунда {n}")
            events = json.loads(row[0])
        else:
            events = world["events"]
        ends = [e for e in events if e["kind"] == "round_end"]
        if (
            len(ends) != 1
            or history["round"] != n
            or any(e["round"] != n for e in events)
        ):
            raise CheckpointError(f"Нарушена последовательность событий раунда {n}")
        end = ends[0]
        if (end.get("side", end["team"]), end["winner"], end["reason"]) != (
            history["side"],
            history["winner"],
            history["reason"],
        ):
            raise CheckpointError(f"Результат раунда {n} расходится с журналом")
        economy = purchases(events)
        if "economy" in history and history["economy"] != economy:
            raise CheckpointError(f"Расходы раунда {n} расходятся с журналом покупок")
        history["economy"] = economy
        if "side" not in end:
            # In the first PR build the winning side occupied the audience field.
            end.update(side=end["team"], team=None)
            if archived:
                logs[n - 1] = put_round(db, events)

    for side, plan in world["plans"].items():
        squad = [p for p in world["agents"] if p["team"] == side]
        leader = min(squad, key=lambda p: (not p["hp"], p["slot"]))
        plan.setdefault("captain", leader["id"])
        plan.setdefault("orders", role_orders(side, plan["site"]))
    for player in world["agents"]:
        # Legacy attackers already followed the direct route to their called site.
        plan = world["plans"].get("T") if player["team"] == "T" else None
        player.setdefault("approached", plan["site"] if plan else None)
    world["checkpointVersion"] = 2


def validate_current(world):
    playbook = world.get("playbook", {})
    for key, board in playbook.items():
        if key != board["side"] + "/" + board["buy"]:
            raise CheckpointError("Назначение не соответствует стороне или закупке")
    boards = list(playbook.values())
    if world.get("nextBoard"):
        boards.append(world["nextBoard"])
    for side, plan in world["plans"].items():
        if plan.get("board"):
            board = plan["board"]
            boards.append(board)
            if board["side"] != side:
                raise CheckpointError("Сторона назначенной тактики не совпадает")
            for a in world["agents"]:
                if a["team"] == side and not (
                    (a["stepUntil"] is None or type(a["stepUntil"]) is int)
                    and type(a.get("stepIndex")) is int
                    and 0 <= a["stepIndex"] <= len(board["slots"][a["slot"]])
                ):
                    raise CheckpointError("Повреждён прогресс маршрута")
    for board in boards:
        tactics.validate(board)
        if (
            not isinstance(board.get("id"), str)
            or type(board.get("revision")) is not int
        ):
            raise CheckpointError("Повреждена ссылка на версию тактики")

    for row in world["history"]:
        totals = row["economy"]
        if set(totals) != {"T", "CT"} or any(
            type(v) is not int or v < 0 for v in totals.values()
        ):
            raise CheckpointError(f"Некорректные расходы раунда {row['round']}")
    for player in world["agents"]:
        if player["approached"] not in (None, "A", "B"):
            raise CheckpointError("Неизвестная точка маршрута игрока")
    for side, plan in world["plans"].items():
        orders = plan["orders"]
        if world.get("mapId"):
            if (orders["map"]!=world["mapId"] or orders["geometry"]!=world["map_version"]
                    or len(orders["slots"])!=5):
                raise CheckpointError("Версия карты в тактическом приказе не совпадает")
        elif orders != role_orders(side, plan["site"]):
            raise CheckpointError("Приказы игроков не соответствуют сохранённому плану")
        if not any(
            p["id"] == plan["captain"] and p["team"] == side for p in world["agents"]
        ):
            raise CheckpointError("Капитан отсутствует в составе стороны")
