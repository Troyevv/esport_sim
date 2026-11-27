"""Checkpoint boundary for the C++ owner of a detailed match."""
from dataclasses import asdict
from functools import lru_cache
import json

from . import _match_native, cs2_maps, tactics
from .match_rules import BLAST_RADIUS, CALLS, PRICES, RULES, SIDEARMS, THROW_RECOVERY, UTILITY, WEAPONS
from .match_performance import WEAPON_CLASS, GRENADE_SKILL

_RULEBOOK = json.dumps(
    dict(
        rules=RULES,
        prices=PRICES,
        boardLabels=tactics.LABELS,
        longApproaches={
            name: {site: len(profile[site][0]) > 1 for site in ("A", "B")}
            for name, profile in cs2_maps.PROFILES.items()
        },
        weapons={name: asdict(spec) for name, spec in WEAPONS.items()},
        sidearms=sorted(SIDEARMS),
        classes=WEAPON_CLASS,
        grenadeSkills=GRENADE_SKILL,
        utility=UTILITY,
        blastRadius=BLAST_RADIUS,
        throwRecovery=THROW_RECOVERY,
    ),
    ensure_ascii=False,
)


def assign(owner, board):
    """Validate editable map data at the boundary, then commit the call on the native owner."""
    validated = tactics.validate(board) | tactics.reference(board)
    owner.assign_board(json.dumps(validated, ensure_ascii=False))


def _spawns(space):
    return json.dumps({side: [space.spawn(side, 0, i) for i in range(len(space.spawns[side]))]
                       for side in ("T", "CT")})


def start_round(world, space):
    return json.loads(_match_native.round_checkpoint(json.dumps(world), _RULEBOOK, _spawns(space)))


def restore(checkpoint, space=None, *, physics=None):
    owner = _match_native.MatchState(checkpoint, cs2_maps.RULES, set(cs2_maps.SUPPORTED_RULES[1:]),
                                    set(CALLS), RULES["freeze"], cs2_maps.BUILD, _RULEBOOK)
    if space is not None:
        owner.attach_spawns(space.name, _spawns(space))
    if physics is not None:
        owner.attach_physics(physics.name, physics.planner, physics.collision.materials)
        owner.attach_objectives(physics.name, physics.objectives)
        owner.attach_opening(physics.name, physics.opening)
    return owner


@lru_cache(maxsize=2)
def physical_map(folder):
    """Share the immutable installed geometry across matches on this map."""
    from .native_physics import NativePerceptionMap
    return NativePerceptionMap(folder)


def open_game(world):
    space = physical_map(cs2_maps.root() / world["mapId"])
    return restore(json.dumps(world, ensure_ascii=False, separators=(",", ":")), space, physics=space)


def play_map(world):
    owner = open_game(world)
    while owner.advance(2048) == 2048:
        pass
    final = json.loads(owner.snapshot())
    if final["phase"] == "timeout":
        raise ValueError("Для продолжения матча требуется завершить тактический тайм-аут")
    world.clear()
    world.update(final)
