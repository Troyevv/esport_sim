"""Checkpoint boundary for the C++ owner of a detailed match."""
from dataclasses import asdict
import json

from . import _match_native, cs2_maps
from .match_rules import CALLS, RULES, SIDEARMS, THROW_RECOVERY, UTILITY, WEAPONS
from .match_performance import WEAPON_CLASS, GRENADE_SKILL

_RULEBOOK = json.dumps(dict(rules=RULES, weapons={k: asdict(v) for k, v in WEAPONS.items()},
                            sidearms=sorted(SIDEARMS), classes=WEAPON_CLASS, grenadeSkills=GRENADE_SKILL,
                            utility=UTILITY, throwRecovery=THROW_RECOVERY), ensure_ascii=False)


def restore(checkpoint, space=None, *, physics=None):
    owner = _match_native.MatchState(checkpoint, cs2_maps.RULES, set(cs2_maps.SUPPORTED_RULES[1:]),
                                    set(CALLS), RULES["freeze"], cs2_maps.BUILD, _RULEBOOK)
    if space is not None:
        table = {side: [space.spawn(side, 0, i) for i in range(len(space.spawns[side]))]
                 for side in ("T", "CT")}
        owner.attach_spawns(space.name, json.dumps(table))
    if physics is not None:
        owner.attach_physics(physics.name, physics.planner, physics.collision.materials)
    return owner
