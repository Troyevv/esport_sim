"""Summarise server positions from professional demos by map, side and elapsed time."""

from collections import Counter
from itertools import combinations
import argparse
import json
from math import dist
from pathlib import Path
from statistics import median


def analyse(games, geometry):
    places = [(place["name"], place["position"]) for place in geometry["places"]]
    summary = {}
    for elapsed in (10, 25, 45, 70):
        sides = {}
        for team, side in ((2, "T"), (3, "CT")):
            count = Counter()
            separation = []
            for game in games:
                for row in game["rounds"]:
                    frame = row["radar"].get(str(elapsed), [])
                    points = [p[2:5] for p in frame if p[0] == team]
                    for point in points:
                        label, marker = min(
                            places, key=lambda place: dist(point, place[1])
                        )
                        if (
                            dist(point, marker) <= 512
                            and abs(point[2] - marker[2]) < 128
                        ):
                            count[label] += 1
                        else:
                            count["?"] += 1
                    if len(points) >= 2:
                        separation.append(
                            median(dist(a, b) for a, b in combinations(points, 2))
                        )
            sides[side] = dict(
                samples=len(separation),
                medianPairDistanceHU=round(median(separation)) if separation else None,
                labels=count.most_common(6),
            )
        summary[elapsed] = sides
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--maps", type=Path, required=True)
    p.add_argument("files", type=Path, nargs="+")
    args = p.parse_args()
    for file in args.files:
        games = json.loads(file.read_bytes())
        name = games[0]["map"]
        geo = json.loads((args.maps / name / "gameplay.json").read_bytes())
        print(json.dumps({name: analyse(games, geo)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
