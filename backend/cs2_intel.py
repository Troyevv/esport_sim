"""What an observer can report and the captain can infer from dated contacts."""

from math import dist, hypot

from .cs2_maps import xyz


def observe_contact(sight, opponent, prior, nearby, continuous):
    """Only the item in the visible player's hands and other nearby visible models."""
    sight["weapon"] = opponent["weapon"]
    sight["groupSize"] = len(nearby)
    if continuous:
        delta = [v - old for v, old in zip(xyz(sight), xyz(prior))]
        speed = hypot(*delta)
        if speed > 0.05:
            sight["direction"] = [round(v / speed, 3) for v in delta]


def pressure(space, contacts, now):
    """Aggregate unique opponents. Evidence loses value as they have time to move."""
    counts = dict.fromkeys(("A", "B"), 0.0)
    seen = {}
    for report in contacts:
        old = seen.get(report["id"])
        if report["source"] != "Слух" and (old is None or report["tick"] > old["tick"]):
            seen[report["id"]] = report
    for report in seen.values():
        age = now - report["tick"]
        if not 0 <= age < 75:
            continue
        pos = xyz(report)
        site = space.reported_site(pos)
        if not site:
            continue
        weight = 1 - age / 75
        direction = report.get("direction")
        if direction and age <= 20:
            target = space.site_points[site]
            offset = [b - a for a, b in zip(pos, target)]
            length = hypot(*offset)
            if length > 3:
                alignment = sum(d * v for d, v in zip(direction, offset)) / length
                weight *= 1 + 0.25 * alignment
        counts[site] += weight
    return counts


def sniper_lane(space, reports, order, now):
    """Identify a long, exposed crossing covered by a recently reported AWP."""
    for report in reports:
        if report.get("weapon") != "AWP" or now - report["tick"] > 25:
            continue
        pos = xyz(report)
        for point in order["via"][-2:]:
            if 30 < dist(pos, point) < 100 and space.hit(pos, point, 1, 64) is None:
                return True
    return False
