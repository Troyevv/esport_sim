"""Paired counterfactual BO1s on installed maps using the production match loop."""

import argparse
from collections import Counter
from itertools import combinations
import gzip
import json
from pathlib import Path
import random
import sys

from tests.reference_kernel import cs2_maps, match
from backend import career, database, skills, world
from backend.match_rules import WEAPONS


MECHANICS = ("aim", "reaction", "first_shot", "rifles")
TACTICS = ("game_reading", "decisions", "positioning", "calling")
PROFILES = (
    "balanced",
    "mechanical",
    "tactical",
    "captain",
    "executors",
    "together",
    "unfamiliar",
    "support",
    "home",
    "away",
    "misassigned",
    "matched",
    "stamina",
    "composure",
    "utility",
)


CONTEXT_PROFILES = (
    "high_form", "low_morale", "fatigued",
    "mechanics_only", "tactics_only", "weak_mechanics",
    "weak_mechanics_captain", "weak_mechanics_teamplay",
)


class SkillReads(dict):
    """Instrument individual reads without changing match state or drawing randomness."""

    def __init__(self, values, reads):
        super().__init__(values)
        self.reads = reads

    def __getitem__(self, key):
        caller = sys._getframe(1)
        self.reads[key].add(caller.f_globals["__name__"] + "." + caller.f_code.co_name)
        return super().__getitem__(key)


def lineups(pack, pair, order, name, profile):
    domain = database.match_input(pack, order)
    for club, roster in enumerate(pair):
        members = world.lineup(domain, roster)
        for m in members:
            p = domain["players"][m["player"]]
            s = dict.fromkeys(skills.KEYS, 65)
            mastery, knowledge = 65, 65
            if club == 0:
                if profile in ("mechanical", "tactical"):
                    s.update(
                        dict.fromkeys(MECHANICS, 85 if profile == "mechanical" else 45)
                    )
                    s.update(
                        dict.fromkeys(TACTICS, 45 if profile == "mechanical" else 85)
                    )
                if profile in ("mechanics_only", "weak_mechanics", "weak_mechanics_captain", "weak_mechanics_teamplay"):
                    s.update(dict.fromkeys(MECHANICS, 85 if profile == "mechanics_only" else 45))
                if profile == "weak_mechanics_teamplay":
                    s.update(dict.fromkeys(("communication", "coordination", "synchronization", "trades", "support"), 90))
                if profile in TACTICS:
                    s[profile] = 85
                if profile == "tactics_only":
                    s.update(dict.fromkeys(TACTICS, 85))
                if profile in ("captain", "executors", "weak_mechanics_captain"):
                    if m["captain"]:
                        s.update(
                            dict.fromkeys(
                                (
                                    "calling",
                                    "communication",
                                    "leadership",
                                    "adaptability",
                                ),
                                40 if profile == "executors" else 90,
                            )
                        )
                    elif profile == "executors":
                        s.update(dict.fromkeys(MECHANICS, 85))
                if profile == "support" and m["role"] == "support":
                    s.update(
                        dict.fromkeys(
                            (
                                "support",
                                "synchronization",
                                "coordination",
                                "trades",
                                "smokes",
                                "flashes",
                            ),
                            90,
                        )
                    )
                if profile in ("home", "away"):
                    knowledge = 90 if profile == "home" else 35
                if profile == "stamina":
                    s.update(
                        dict.fromkeys(
                            ("endurance", "recovery", "fatigue_resistance"), 90
                        )
                    )
                if profile == "composure":
                    s.update(
                        dict.fromkeys(
                            (
                                "consistency",
                                "stress_resistance",
                                "composure",
                                "concentration",
                            ),
                            90,
                        )
                    )
                if profile == "utility":
                    s.update(
                        dict.fromkeys(
                            ("smokes", "flashes", "he", "incendiaries", "decoys"), 90
                        )
                    )
                if profile in ("misassigned", "matched"):
                    mastery = 25 if profile == "misassigned" else 90
                    s.update(dict.fromkeys(MECHANICS, 85))
            p.update(
                skills=s,
                form=90 if club == 0 and profile == "high_form" else 50,
                morale=20 if club == 0 and profile == "low_morale" else 50,
                fatigue=60 if club == 0 and profile == "fatigued" else 0,
                mapKnowledge={name.removeprefix("de_"): knowledge},
                roleMastery={m["role"]: mastery},
            )
        for x, y in combinations(members, 2):
            chemistry = (
                {"together": 95, "unfamiliar": 20}.get(profile, 65) if club == 0 else 65
            )
            domain["chemistry"][world.pair_key(x["player"], y["player"])] = chemistry
    return domain


def play(pack, name, pair, seed, mirror, profile, trace):
    order = list(reversed(pair)) if mirror else pair
    domain = lineups(pack, pair, order, name, profile)
    game = match.initial(seed, domain, order, map_id=name)
    reads = {key: set() for key in skills.KEYS}
    if trace:
        for p in game["domain"]["players"].values():
            p["skills"] = SkillReads(p["skills"], reads)
    team = {a["id"] for a in game["agents"] if a["club"] == int(mirror)}
    totals, statuses = Counter(), Counter()
    while game["phase"] != "finished":
        due = game["tick"] + 1
        for message in game["messages"]:
            if (
                message["due"] == due
                and message["sender"] in team
                and "sight" in message
            ):
                sight = message["sight"]
                if sight["source"] == "Зрение":
                    totals["sightCalls"] += 1
                    totals["sightCallTicks"] += due - sight["tick"]
        match.advance(game)
        if game["phase"] in ("live", "planted") and game["tick"] % 10 == 0:
            statuses.update(
                a["status"] for a in game["agents"] if a["hp"] and a["id"] in team
            )
    for batch in [*game["archive"], game["events"]]:
        rotated = False
        for e in batch:
            if e["kind"] == "round_end" and rotated:
                totals["wonAfterTurn"] += int(e["winner"] == int(mirror))
            if e.get("player") not in team:
                continue
            totals[e["kind"]] += 1
            if e["kind"] == "rotate":
                rotated = True
            if (
                e["kind"] == "damage"
                and e["weapon"] in ("Огонь", "HE")
                and e["target"] not in team
            ):
                totals["grenadeDamage"] += e["amount"]
            if (
                e["kind"] == "damage"
                and e["weapon"] in WEAPONS
                and e["target"] not in team
            ):
                totals["gunHits"] += 1
            if e["kind"] == "kill" and e["enemy"] and e["trade"]:
                totals["trades"] += 1
    return dict(
        map=name,
        seed=seed,
        teams=order,
        profile=profile,
        mirror=mirror,
        rounds=sum(game["score"]),
        won=game["score"][int(mirror)],
        events=totals,
        statusSeconds=statuses,
        reads={k: sorted(v) for k, v in reads.items() if v},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--map", choices=cs2_maps.NAMES, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[41000, 59000])
    parser.add_argument("--profiles", nargs="+", choices=PROFILES + CONTEXT_PROFILES + TACTICS, default=PROFILES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pack = json.loads(gzip.decompress(database.RELEASE.read_bytes()))["package"]
    rosters = sorted(career.roster_index(pack).values())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for seed in args.seeds:
            pair = random.Random(seed).sample(rosters, 2)
            for profile in args.profiles:
                for mirror in (False, True):
                    row = play(
                        pack,
                        args.map,
                        pair,
                        seed,
                        mirror,
                        profile,
                        profile == "balanced",
                    )
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()


if __name__ == "__main__":
    main()
