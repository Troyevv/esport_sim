"""Validate the three manually transcribed HLTV regulation scorecards used in QA."""

import json
from pathlib import Path

# A kill ending can follow a plant. These icons establish a minimum plant count.
CARDS = (
    (
        "de_cache",
        "2026-11-02",
        "IEM Beijing",
        "FURIA–FaZe",
        "243504/furia-vs-faze",
        17,
        9,
        8,
        [13, 2, 0, 2],
    ),
    (
        "de_train",
        "2025-11-04",
        "IEM Chengdu",
        "FURIA–G2",
        "212588/furia-vs-g2",
        18,
        9,
        9,
        [12, 1, 5, 0],
    ),
    (
        "de_vertigo",
        "2024-12-07",
        "Shanghai Major",
        "paiN–FURIA",
        "189274/pain-vs-furia",
        24,
        11,
        13,
        [11, 4, 5, 4],
    ),
)


def main():
    directory = Path("build/pro-tournaments")
    directory.mkdir(parents=True, exist_ok=True)
    for name, date, event, teams, slug, total, t, ct, reasons in CARDS:
        assert sum(reasons) == total == t + ct
        result = dict(
            map=name,
            date=date,
            event=event,
            teams=teams,
            rounds=total,
            t=t,
            ct=ct,
            source="https://www.hltv.org/stats/matches/mapstatsid/" + slug,
            endings=dict(
                zip(("elimination", "timeout", "explosion", "defuse"), reasons)
            ),
            minimumPlants=reasons[2] + reasons[3],
        )
        (directory / (name + ".json")).write_text(
            json.dumps(result, ensure_ascii=False)
        )
        print(name, event, total)


if __name__ == "__main__":
    main()
