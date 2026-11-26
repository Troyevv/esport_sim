"""Summarize the explicit BO1 audit, resampling paired seeds and side swaps together."""

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from backend.cs2_maps import NAMES

METRICS = (
    ("T", "T", "rounds", 100),
    ("CT", "CT", "rounds", 100),
    ("plant", "plants", "rounds", 100),
    ("retake", "defuses", "plants", 100),
    ("T_utility", "utility_T", "rounds", 1),
    ("CT_utility", "utility_CT", "rounds", 1),
    ("trade", "trades", "kills", 100),
    ("rotate", "rotation_rounds", "rounds", 100),
    ("orders", "orders", "rounds", 1),
    ("arrive", "arrived", "orders", 100),
    ("cancel", "revoked", "orders", 100),
    ("latency", "latency_ticks", "responses", 0.1),
    ("speed", "ticks", "cpu", 1),
)
COLUMNS = sorted({key for _, num, den, _ in METRICS for key in (num, den)})


def load_pairs(old, new):
    # Seed is the independent unit. Both sides and all maps stay in each block.
    data = np.zeros((len(NAMES), 2, 15, len(COLUMNS)))
    for m, name in enumerate(NAMES):
        for index in range(30):
            key = f"{name}-{index:02d}.json"
            a, b = (
                json.loads((directory / key).read_bytes()) for directory in (old, new)
            )
            if any(
                a[field] != b[field]
                for field in ("seed", "rosters", "first", "map", "index")
            ):
                raise ValueError(f"Unpaired inputs: {key}")
            if (
                a["map"] != name
                or a["index"] != index
                or a["seed"] != 65400 + index // 2
            ):
                raise ValueError(f"Unexpected fixture: {key}")
            if index % 2:
                if a["rosters"] != mirror["rosters"] or a["first"] == mirror["first"]:
                    raise ValueError(f"Missing side swap: {key}")
            else:
                mirror = a
            for version, r in enumerate((a, b), 19):
                if r["rules"] != f"cs2-bo1.{version}" or r["counts"]["rounds"] != sum(
                    r["score"]
                ):
                    raise ValueError(f"Incomplete match or incorrect version: {key}")
                counts = dict(
                    r["counts"],
                    ticks=r["ticks"],
                    cpu=r["cpu"],
                    latency_ticks=sum(r["latency"]),
                    responses=len(r["latency"]),
                )
                data[m, version - 19, index // 2] += [counts.get(k, 0) for k in COLUMNS]
    return data


def summarize(old, new):
    blocks = load_pairs(old, new)
    sample = np.random.default_rng(19730).integers(0, 15, (5000, 15))
    for name, versions in zip([*NAMES, "Все"], [*blocks, blocks.sum(axis=0)]):
        totals = versions.sum(axis=1)
        draws = versions[:, sample, :].sum(axis=2)
        for metric, numerator, denominator, scale in METRICS:
            n, d = COLUMNS.index(numerator), COLUMNS.index(denominator)
            means = scale * totals[:, n] / totals[:, d]
            with np.errstate(invalid="ignore", divide="ignore"):
                paired = np.diff(scale * draws[:, :, n] / draws[:, :, d], axis=0)[0]
            lower, upper = np.nanquantile(paired, [0.025, 0.975])
            yield dict(
                map=name,
                metric=metric,
                old=round(means[0], 4),
                new=round(means[1], 4),
                delta=round(means[1] - means[0], 4),
                lower=round(lower, 4),
                upper=round(upper, 4),
                den19=round(totals[0, d], 3),
                den20=round(totals[1, d], 3),
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("old", type=Path)
    parser.add_argument("new", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    rows = list(summarize(args.old, args.new))
    with args.output.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0], lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
