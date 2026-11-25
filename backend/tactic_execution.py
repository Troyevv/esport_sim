"""Resolve board intentions through the ordinary BO1 navigation and action pipeline."""

from math import atan2, pi, sin

from . import engine, tactics


def execute(a, steps, now, bomb, fire, walk, space=None):
    index = a["stepIndex"]
    if index >= len(steps):
        return None
    step = steps[index]
    kind = step["kind"]
    goal = tuple(step[k] for k in ("x","y","z") if k in step)
    a["status"] = tactics.LABELS[kind] + f" · точка {index + 1}"
    if kind in tactics.MOVES and tuple(a[k] for k in ("x","y","z") if k in a) != goal:
        if walk(
            a, goal, 2 if kind in ("exit", "retreat") else 1, fire, allow_detour=True
        ):
            if kind == "retreat":
                a["heading"] += pi
            return ("move", None)
        return ("hold", None)
    if kind in ("wait", "hold", "face"):
        if kind == "face":
            a["heading"] = atan2(step["y"] - a["y"], step["x"] - a["x"])
        if kind == "hold":
            a["heading"] = (pi if a["team"] == "CT" else 0) + 1.6 * sin(
                (now + a["slot"] * 12) / 16
            )
        if a["stepUntil"] is None:
            a["stepUntil"] = now + step["seconds"] * 10
        if now < a["stepUntil"]:
            return ("hold", None)
    a.update(stepIndex=index + 1, stepUntil=None)
    if kind == "plant" and bomb and bomb["carrier"] == a["id"]:
        return ("plant", space.site_at(goal) if space else tactics.zone_at(*goal))
    if kind == "throw":
        if not space and not engine.clear_line(a["x"], a["y"], *goal):
            a["status"] = "Пропускает бросок · путь перекрыт"
            return ("hold", None)
        if step["utility"] in a["utility"]:
            if now < a["throwAt"]:
                a["stepIndex"] = index
                return ("hold", None)
            return ("throw", step)
        a["status"] = "Пропускает бросок · нет гранаты"
    return ("hold", None)
