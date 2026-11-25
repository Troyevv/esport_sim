"""A private one-round sparring simulation, isolated from the authoritative game."""

from . import match, tactics
from .match_rules import RULES


def simulate(draft):
    board = dict(tactics.validate(draft), id="preview", revision=0)
    world = match.initial(42,map_id=board["map"])
    first = 1 if board["side"] == "T" else RULES["half"] + 1
    world["round"] = first - 1
    match.next_round(world)
    if board["buy"] != "Пистолетная":
        world["round"] += 1
        for player in world["agents"]:
            player["cash"] = 1100 if board["buy"] == "Эко" else 5400
    world["playbook"] = {board["side"] + "/" + board["buy"]: board}
    match.begin_live(world)
    frames = []
    while True:
        frames.append(
            [[a["x"], a["y"], round(a["heading"], 3), a["hp"], *([a["z"]] if "z" in a else [])] for a in world["agents"]]
        )
        if world["phase"] in ("result", "finished"):
            break
        match.advance(world)
    return dict(
        frames=frames,
        tickMs=100,
        events=[
            dict(tick=e["tick"], text=e["text"])
            for e in world["events"]
            if e["kind"]
            in (
                "board_step",
                "adapt",
                "throw",
                "kill",
                "plant",
                "defuse",
                "rotate",
                "round_end",
            )
        ],
        effects=[
            {k: e[k] for k in ("utility", "x", "y", "z", "land", "end", "radius") if k in e}
            for e in world["events"]
            if e["kind"] == "throw"
        ],
    )
