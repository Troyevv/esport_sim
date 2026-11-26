"""Resolve tactical labels against the versioned, directed map navigation."""

from collections import defaultdict
from math import dist

from .cs2_navigation import surface_height


def named_stages(data, nav, profile):
    names = {name for site in ("A", "B") for route in profile[site] for name in route}
    names.update(name for guards in profile["guards"].values() for name in guards)
    names.add(profile["middle"])
    names.update(profile.get("overwatch", ()))
    names.update(profile.get("probe", {}).values())
    markers = defaultdict(list)
    for place in data["places"]:
        name = place["name"]
        if name not in names:
            continue
        # env_cs_place is a label origin, not a walkable waypoint. Record
        # the distance to its representative NAV surface for human review.
        position = place["position"]
        ident = nav.locate(position, 96)
        if ident is None:
            ident = min(nav.centers, key=lambda i: (dist(position, nav.centers[i]), i))
            offset = dist(position, nav.centers[ident])
        else:
            offset = abs(position[2] - surface_height(nav.areas[ident]["corners"], *position[:2]))
        markers[name].append(dict(area=ident, offset=round(offset, 2)))
    missing = names.difference(markers)
    if missing:
        raise ValueError(f"{data['map']}: неизвестные позиции {sorted(missing)}")
    return dict(sorted(markers.items()))


def resolve_anchors(profile, markers, nav, nav_sha256):
    places = {name: {row["area"] for row in rows} for name, rows in markers.items()}
    if "navAnchors" in profile:
        binding = profile["navAnchors"]
        if binding["sha256"] != nav_sha256:
            raise ValueError("Версия NAV расходится с привязкой тактических позиций")
        for name, areas in binding["places"].items():
            if name not in places or not areas or not set(areas).issubset(nav.areas):
                raise ValueError(f"Неизвестная привязка NAV для {name}: {areas}")
            places[name] = set(areas)
    return places


