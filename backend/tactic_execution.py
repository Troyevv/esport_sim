"""Resolve board intentions through the ordinary BO1 navigation and action pipeline."""

from math import atan2

from . import tactics


def execute(a, steps, now, bomb, fire, walk):
    index = a["stepIndex"]
    if index >= len(steps):
        return None
    step = steps[index]
    kind = step["kind"]
    goal = step["x"], step["y"]
    a["status"] = tactics.LABELS[kind] + f" · точка {index + 1}"
    if kind in tactics.MOVES and (a["x"], a["y"]) != goal:
        if walk(a, goal, 2 if kind in ("exit", "retreat") else 1, fire):
            return ("move", None)
        return ("hold", None)
    if kind in ("wait", "hold", "face"):
        if kind == "face":
            a["heading"] = atan2(step["y"] - a["y"], step["x"] - a["x"])
        if a["stepUntil"] is None:
            a["stepUntil"] = now + step["seconds"] * 10
        if now < a["stepUntil"]:
            return ("hold", None)
    a.update(stepIndex=index + 1, stepUntil=None)
    if kind == "plant" and bomb and bomb["carrier"] == a["id"]:
        return ("plant", tactics.zone_at(*goal))
    if kind == "throw":
        if step["utility"] in a["utility"]:
            if now < a["throwAt"]:
                a["stepIndex"] = index
                return ("hold", None)
            return ("throw", step)
        a["status"] = "Пропускает бросок · нет гранаты"
    return ("hold", None)
