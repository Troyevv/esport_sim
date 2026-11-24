"""Deterministic R0 test range. All positions use map units, time uses ticks."""

from __future__ import annotations

from collections import deque
from math import atan2, cos, sin

TICK_SECONDS = 0.1
VERSION = 1
CELL = 10
COLUMNS, ROWS = 31, 21
VISION_RADIUS = 84
MEMORY_TICKS = 80
STEP = 2
MASK = (1 << 32) - 1

# Original grid geometry for Depo. Each rectangle occupies whole opaque cells.
# Walkable space is the complement inside the perimeter. Coordinates grow south.
_BLOCKS = (
    (0, 0, 31, 1),
    (0, 20, 31, 1),
    (0, 1, 1, 19),
    (30, 1, 1, 19),
    (4, 3, 5, 1),
    (4, 4, 1, 3),
    (8, 4, 1, 2),
    (12, 1, 1, 4),
    (13, 4, 3, 1),
    (17, 2, 2, 2),
    (21, 2, 1, 4),
    (22, 5, 4, 1),
    (27, 2, 2, 2),
    (2, 8, 3, 1),
    (7, 7, 4, 2),
    (10, 9, 1, 3),
    (6, 11, 2, 2),
    (13, 7, 2, 2),
    (16, 8, 2, 1),
    (14, 11, 3, 2),
    (19, 7, 1, 4),
    (20, 10, 3, 1),
    (24, 8, 3, 1),
    (4, 15, 1, 3),
    (5, 17, 3, 1),
    (8, 14, 3, 1),
    (11, 16, 1, 4),
    (14, 16, 3, 1),
    (18, 15, 1, 4),
    (21, 13, 4, 1),
    (24, 14, 1, 3),
    (27, 17, 2, 1),
)
_BLOCKED = frozenset(
    (col, row)
    for x, y, w, h in _BLOCKS
    for col in range(x, x + w)
    for row in range(y, y + h)
)
_FLOOR = tuple(
    (col, row)
    for row in range(1, ROWS - 1)
    for col in range(1, COLUMNS - 1)
    if (col, row) not in _BLOCKED
)
_FLOOR_SET = frozenset(_FLOOR)
_NEIGHBORS = {
    (x, y): tuple(
        p for p in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)) if p in _FLOOR_SET
    )
    for x, y in _FLOOR
}
_SPAWN_CELLS = {
    "T": [(2, 10), (3, 11), (2, 12), (4, 10), (4, 12)],
    "CT": [(28, 9), (27, 10), (28, 11), (26, 11), (27, 12)],
}
_NAMES = {
    "T": ["Sable", "Echo", "Vega", "Rune", "Kite"],
    "CT": ["Atlas", "Iris", "Volt", "Lynx", "Nova"],
}


def _rect(x, y, w, h):
    return dict(x=x * CELL, y=y * CELL, w=w * CELL, h=h * CELL)


def _center(cell):
    return tuple(n * CELL + CELL // 2 for n in cell)


def _cell(x, y):
    return x // CELL, y // CELL


MAP = {
    "id": "depo",
    "version": 1,
    "name": "Депо",
    "author": "Оригинальная тестовая геометрия проекта esport_sim",
    "width": COLUMNS * CELL,
    "height": ROWS * CELL,
    "walls": [_rect(*block) for block in _BLOCKS],
    "zones": [
        dict(name="A", **_rect(4, 1, 5, 2)),
        dict(name="B", **_rect(20, 15, 3, 4)),
    ],
    "spawns": [
        dict(x=_center(p)[0], y=_center(p)[1], team=team)
        for team, cells in _SPAWN_CELLS.items()
        for p in cells
    ],
}


def route(start, goal):
    """Shortest traversable route between cells, excluding the starting cell."""
    if start not in _FLOOR_SET or goal not in _FLOOR_SET:
        raise ValueError("Недоступная точка маршрута")
    frontier = deque([start])
    parents = {start: None}
    while frontier:
        here = frontier.popleft()
        if here == goal:
            path = []
            while here != start:
                path.append(list(_center(here)))
                here = parents[here]
            return path[::-1]
        for neighbor in _NEIGHBORS[here]:
            if neighbor not in parents:
                parents[neighbor] = here
                frontier.append(neighbor)
    raise ValueError("Нет пути между точками")


def clear_line(x, y, tx, ty):
    """Traverse every intersected grid cell, including both sides at corners."""
    cx, cy = _cell(x, y)
    end = _cell(tx, ty)
    dx, dy = tx - x, ty - y
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    # Numerators for distances to next horizontal/vertical crossing.
    nx = (cx + 1) * CELL - x if dx > 0 else x - cx * CELL
    ny = (cy + 1) * CELL - y if dy > 0 else y - cy * CELL
    while (cx, cy) in _FLOOR_SET:
        if (cx, cy) == end:
            return True
        cross_x, cross_y = nx * abs(dy), ny * abs(dx)
        if dx and (not dy or cross_x < cross_y):
            cx += sx
            nx += CELL
        elif dy and (not dx or cross_y < cross_x):
            cy += sy
            ny += CELL
        else:
            if (cx + sx, cy) in _BLOCKED or (cx, cy + sy) in _BLOCKED:
                return False
            cx, cy = cx + sx, cy + sy
            nx, ny = nx + CELL, ny + CELL
    return False


def sees(agent, other):
    dx, dy = other["x"] - agent["x"], other["y"] - agent["y"]
    distance2 = dx * dx + dy * dy
    if distance2 > VISION_RADIUS**2:
        return False
    dot = dx * cos(agent["heading"]) + dy * sin(agent["heading"])
    # 120-degree field of view. Coincident cells are observable as well.
    return (
        dot >= 0
        and 4 * dot * dot >= distance2
        and clear_line(agent["x"], agent["y"], other["x"], other["y"])
    )


def _event(state, team, text):
    state["events"].append(dict(tick=state["tick"], team=team, text=text))
    del state["events"][:-64]


def _draw(agent):
    # LCG with an independent stream per agent, stored in snapshots.
    agent["rng"] = (1664525 * agent["rng"] + 1013904223) & MASK
    return agent["rng"]


def initial(seed: int):
    state = dict(
        version=VERSION,
        map_version=MAP["version"],
        seed=seed,
        tick=0,
        agents=[],
        events=[],
    )
    for team, cells in _SPAWN_CELLS.items():
        for i, cell in enumerate(cells):
            x, y = _center(cell)
            agent = dict(
                id=f"{team}{i + 1}",
                name=_NAMES[team][i],
                team=team,
                x=x,
                y=y,
                heading=0.0 if team == "T" else atan2(0, -1),
                status="На старте",
                visible=[],
                knowledge={},
                path=[],
                rng=(seed + 0x9E3779B9 * (len(state["agents"]) + 1)) & MASK,
            )
            state["agents"].append(agent)
        _event(state, team, f"Группа {team} заняла стартовые позиции")
    _observe(state)
    return state


def _observe(state):
    tick = state["tick"]
    for agent in state["agents"]:
        visible = []
        memory = agent["knowledge"]
        for other in state["agents"]:
            if other["team"] == agent["team"] or not sees(agent, other):
                continue
            target = other["id"]
            visible.append(target)
            memory[target] = dict(id=target, x=other["x"], y=other["y"], tick=tick)
            if target not in agent["visible"]:
                _event(state, agent["team"], f"{agent['name']} видит {other['name']}")
        agent["visible"] = visible
        agent["knowledge"] = {
            k: v for k, v in memory.items() if tick - v["tick"] <= MEMORY_TICKS
        }


def _move(agent):
    """Choose a goal from this agent's own memory or explore walkable space."""
    if not agent["path"]:
        start = _cell(agent["x"], agent["y"])
        memory = sorted(agent["knowledge"].values(), key=lambda sight: -sight["tick"])
        goal = next(
            (_cell(s["x"], s["y"]) for s in memory if _cell(s["x"], s["y"]) != start),
            None,
        )
        if goal is not None:
            agent["status"] = "Проверяет контакт"
        else:
            goal = _FLOOR[_draw(agent) % len(_FLOOR)]
            agent["status"] = "Исследует карту"
        agent["path"] = route(start, goal)
    if not agent["path"]:
        return
    gx, gy = agent["path"][0]
    dx, dy = gx - agent["x"], gy - agent["y"]
    agent["heading"] = atan2(dy, dx)
    agent["x"] += min(STEP, max(-STEP, dx))
    agent["y"] += min(STEP, max(-STEP, dy))
    if (agent["x"], agent["y"]) == (gx, gy):
        agent["path"].pop(0)


def advance(state):
    """Advance all decisions from the previous tick's observations."""
    state["tick"] += 1
    for agent in state["agents"]:
        started_path = not agent["path"]
        _move(agent)
        if started_path and state["tick"] > 1:
            _event(state, agent["team"], f"{agent['name']} · {agent['status'].lower()}")
    _observe(state)


def motion_sample(state):
    """View-filterable poses at an actual model tick during accelerated playback."""
    known = {team: {target for a in state["agents"] if a["team"] == team
                    for target in a["visible"]} for team in ("T", "CT")}
    return {
        a["id"]: ((a["x"], a["y"], a["heading"]),
                  tuple(team for team in known if a["team"] == team or a["id"] in known[team]))
        for a in state["agents"]
    }


def project(state, view="full"):
    if view not in ("full", "T", "CT"):
        raise ValueError("Неизвестный режим обзора")
    seen = {
        target for a in state["agents"] if a["team"] == view for target in a["visible"]
    }
    agents = []
    for a in state["agents"]:
        friendly = view == "full" or a["team"] == view
        if not friendly and a["id"] not in seen:
            continue
        marker = {k: a[k] for k in ("id", "name", "team", "x", "y", "heading")}
        marker.update(
            status=a["status"] if friendly else "В поле зрения",
            visible=list(a["visible"]) if friendly else [],
            knowledge=list(a["knowledge"].values()) if friendly else [],
        )
        agents.append(marker)
    return dict(
        seed=state["seed"],
        tick=state["tick"],
        time=state["tick"] / 10,
        map=MAP,
        agents=agents,
        view=view,
        events=[
            e for e in state["events"] if view == "full" or e["team"] in (view, None)
        ],
    )
