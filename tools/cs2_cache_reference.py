"""Reduce the public Cache replay to the same round and radar fields as GOTV."""

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path

UTILITY = {
    "flash": "flashbang",
    "he": "hegrenade",
    "smoke": "smokegrenade",
    "molotov": "fire",
    "incendiary": "fire",
    "decoy": "decoy",
}


def extract(directory):
    manifest = json.loads((directory / "early/source.json").read_bytes())["meta"]
    rounds, team_wins, halves = [], Counter(), []
    for source in manifest["rounds"]:
        n = source["round"]
        if source["startTick"] == source["endTick"]:
            continue
        part = "early" if n <= 20 else "late"
        data = json.loads(
            gzip.decompress((directory / part / f"round-{n}.gz").read_bytes())
        )
        frames = data["frames"]
        first, last = frames[0], frames[-1]
        start, end = first["tick"], source["endTick"]
        if first["phase"] != "live" or abs(last["tick"] - end) > 2:
            raise ValueError(f"Incomplete live round {n}")
        winner = data["winner"]
        faze = next(
            p["team"] for p in first["players"].values() if p["name"] == "Twistzz"
        )
        club = "FaZe" if faze == winner else "magic"
        team_wins[club] += 1
        halves.append(club)
        plant = any(f["bombActive"] for f in frames)
        deaths = data["roundStats"]
        alive = Counter(
            p["team"]
            for sid, p in last["players"].items()
            if (not deaths[sid]["d"] if sid in deaths else p["alive"])
        )
        if plant and winner == "CT":
            reason = "bomb_defused"
        elif plant and winner == "T" and not (last["bombSecsLeft"] or 0):
            reason = "bomb_exploded"
        elif (
            not plant
            and winner == "CT"
            and not (last["roundSecsLeft"] or 0)
            and alive["T"]
        ):
            reason = "time_ran_out"
        else:
            reason = "ct_killed" if winner == "T" else "t_killed"
            if alive["CT" if winner == "T" else "T"]:
                raise ValueError(f"Unreconciled elimination in round {n}")
        radar = {}
        for sec in (0, 10, 25, 45, 70):
            wanted = start + 64 * sec
            if wanted >= end:
                continue
            f = min(frames, key=lambda frame: abs(frame["tick"] - wanted))
            radar[sec] = [
                [
                    2 if p["team"] == "T" else 3,
                    sid,
                    round(p["x"]),
                    round(p["y"]),
                    round(p["z"]),
                    data["economy"][sid]["equipValue"],
                ]
                for sid, p in f["players"].items()
                if p["alive"] and p["team"] in ("T", "CT")
            ]
        grenades = Counter(UTILITY[g["type"]] for g in data["grenadeSpans"])
        rounds.append(
            dict(
                round=n - 2,
                winner=winner.lower(),
                reason=reason,
                plant=plant,
                plantSeconds=next(
                    ((f["tick"] - start) / 64 for f in frames if f["bombActive"]), None
                ),
                touched=any(f["defusing"] for f in frames),
                duration=(end - start) / 64,
                survivingCT=alive["CT"],
                radar=radar,
                wallets={
                    sid: dict(
                        side=p["team"],
                        remaining=data["economy"][sid]["cashRemaining"],
                        spent=None,
                        loadout=p["inventory"],
                    )
                    for sid, p in first["players"].items()
                    if p["team"] in ("T", "CT")
                },
                grenades=dict(grenades),
            )
        )
    accounts = [account for r in rounds for account in r["wallets"].values()]
    if any(Counter(v["side"] for v in r["wallets"].values()) != {"T": 5, "CT": 5} for r in rounds):
        raise ValueError("Incomplete playing roster in freeze-time economy")
    # This radar encodes missing balances as zero for all ten players even
    # after repeated wins. A constant series supplies no cash information.
    if accounts and all(account["remaining"] == 0 for account in accounts):
        for account in accounts:
            account["remaining"] = None
    # A completed defuse is a positive control for this viewer field. If
    # absent, don't represent missing use-button telemetry as zero attempts.
    if any(r["reason"] == "bomb_defused" and not r["touched"] for r in rounds):
        for r in rounds:
            r["touched"] = None
    half_scores = [
        Counter(halves[i:j])["magic"] for i, j in ((0, 12), (12, 24), (24, 35))
    ]
    if team_wins != {"magic": 19, "FaZe": 16} or half_scores != [7, 5, 7]:
        raise ValueError(f"Official halves do not match: {team_wins} {half_scores}")
    return [
        dict(
            map="de_cache",
            match="2397607",
            event="FISSURE Playground 3",
            date="2026-09-09",
            patch=None,
            source="https://cs2replays.com/?replay=M7NNAFXCRBwL",
            rounds=rounds,
        )
    ]


if __name__ == "__main__":
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--dir", type=Path, required=True)
    args.add_argument("--out", type=Path, required=True)
    p = args.parse_args()
    p.out.write_text(json.dumps(extract(p.dir), separators=(",", ":")))
