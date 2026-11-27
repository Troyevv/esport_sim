"""A private one-round sparring simulation, isolated from the authoritative game."""

import json

from . import native_match_state, cs2_maps, match, match_inventory, tactics
from .match_rules import RULES, SMG


def simulate(draft):
    board = dict(tactics.validate(draft), id="preview", revision=0)
    world = match.initial(42,map_id=board["map"])
    first = 1 if board["side"] == "T" else RULES["half"] + 1
    world["round"] = first - 1
    world = native_match_state.start_round(world, cs2_maps.for_match(world))
    if board["buy"] != "Пистолетная":
        world["round"] += 1
        for player in world["agents"]:
            player["cash"] = 1100 if board["buy"] == "Эко" else 5400
    if world.get("mapId"):
        scenario = "Полная" if board["buy"] == "Оружейная" else board["buy"]
        world.update(previewBuy=scenario,nextBoard=board)
        wallets = {"Эко":900, "Частичная":2900, "Форс":2300, "Полная":5600,
                   "Антиэко":3950, "Бонусная":2700, "Пистолетная":800}
        for a in world["agents"]:
            if a["team"] == board["side"]:
                a["cash"] = wallets[scenario]
                if scenario == "Бонусная" and a["slot"] < 3:
                    match_inventory.equip(a,match_inventory.stocked(SMG[a["team"]]))
                    a["armor"] = 75
    world["playbook"] = {board["side"] + "/" + board["buy"]: board}
    owner = native_match_state.open_game(world)
    owner.begin_live()
    world = json.loads(owner.snapshot())
    summary = {}
    if world.get("mapId"):
        purchases = [e for e in world["events"] if e["kind"]=="buy" and e["team"]==board["side"]]
        plan=world["plans"][board["side"]]
        summary["economy"] = dict(scenario=plan["economy"]["scenario"],spent=sum(e["price"] for e in purchases),
                                  drops=sum(e["player"]!=e["recipient"] for e in purchases))
    frames = json.loads(owner.advance_preview(world["deadline"] - world["tick"] + RULES["fuse"] + 1))
    world = json.loads(owner.snapshot())
    for frame in frames:
        for pose in frame:
            pose[2] = round(pose[2], 3)
    return dict(
        **summary,
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
