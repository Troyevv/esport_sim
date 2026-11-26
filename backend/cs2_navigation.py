"""Offline navigation in Source 2 world coordinates (Hammer units, Z up)."""

from collections import defaultdict
from dataclasses import dataclass, field
from heapq import heapify, heappop, heappush
from math import dist, floor


def surface_height(corners, x, y):
    """Height at XY on a convex NAV polygon, including slopes and edge points."""
    ax, ay, az = corners[0]
    for b, c in zip(corners[1:], corners[2:]):
        bx, by, bz = b
        cx, cy, cz = c
        det = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if abs(det) < 1e-8:
            continue
        u = ((x - ax) * (cy - ay) - (y - ay) * (cx - ax)) / det
        v = ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / det
        if min(u, v, 1 - u - v) >= -1e-7:
            return az + u * (bz - az) + v * (cz - az)
    return None


def _center(points):
    return tuple(sum(axis) / len(points) for axis in zip(*points))


@dataclass(frozen=True)
class Crossing:
    area: int
    leave: tuple
    enter: tuple
    ladder: int | None = None
    alternatives: tuple = ()
    _hash: int = field(init=False, repr=False, compare=False)

    def __post_init__(self):
        # A static portal is reused in millions of physical path-cache lookups.
        # Its alternate XY/Z segments are immutable throughout the map lifetime.
        geometry = (self.area, self.leave, self.enter, self.ladder, self.alternatives)
        object.__setattr__(self, "_hash", hash(geometry))

    def __hash__(self):
        return self._hash


def _point(a, b, t):
    return tuple(x + t * (y - x) for x, y in zip(a, b))


def _portal(a, b, c, d, fraction=.5):
    """Pair of edge points within the overlapping width of a split NAV edge."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    if not length2:
        return tuple(a), tuple(min((c, d), key=lambda p: dist(a, p)))
    cpos = ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / length2
    dpos = ((d[0] - a[0]) * dx + (d[1] - a[1]) * dy) / length2
    lo, hi = sorted((cpos, dpos))
    start = min(1, max(0, lo))
    end = min(1, max(0, hi))
    t = start+(end-start)*fraction
    if abs(dpos - cpos) < 1e-8:
        midpoint = _point(a, b, t)
        return midpoint, tuple(min((c, d), key=lambda p: dist(midpoint, p)))
    u = min(1, max(0, (t - cpos) / (dpos - cpos)))
    return _point(a, b, t), _point(c, d, u)


class Navigation:
    """Each map owns its own XYZ surfaces, directed portals and ladder links."""

    def __init__(self, data):
        if data["format"] != 1 or data["space"] != "Hammer XYZ":
            raise ValueError("Неизвестная версия навигации CS2")
        self.areas = {a["id"]: a for a in data["areas"]}
        self.centers = {}
        self._sectors = defaultdict(list)
        for ident, area in self.areas.items():
            corners = area["corners"]
            self.centers[ident] = _center(corners)
            xs, ys, _ = zip(*corners)
            for x in range(floor(min(xs) / 256), floor(max(xs) / 256) + 1):
                for y in range(floor(min(ys) / 256), floor(max(ys) / 256) + 1):
                    self._sectors[x, y].append(ident)
        self.links = defaultdict(list)
        ladders = {l["id"]: l for l in data["ladders"]}
        for ident, area in self.areas.items():
            corners = area["corners"]
            for index, edge in enumerate(area["edges"]):
                a, b = corners[index], corners[(index + 1) % len(corners)]
                for link in edge:
                    other = self.areas[link["to"]]["corners"]
                    j = link["edge"]
                    if j >= len(other):
                        raise ValueError(f"Некорректное встречное ребро NAV: {ident} → {link['to']} ({j})")
                    leave, enter = _portal(a, b, other[j], other[(j + 1) % len(other)])
                    variants=tuple(dict.fromkeys(_portal(a,b,other[j],other[(j+1)%len(other)],fraction)
                                   for fraction in (.2,.8,.05,.95)))
                    self.links[ident].append(Crossing(link["to"], tuple(leave), tuple(enter),alternatives=variants))
            for upward, refs in ((True, area["up"]), (False, area["down"])):
                for ladder_id in refs:
                    ladder = ladders[ladder_id]
                    leave, enter = ladder["bottom"], ladder["top"]
                    targets = ladder["above"] if upward else ladder["below"]
                    if not upward:
                        leave, enter = enter, leave
                    for target in targets:
                        if target != ident:
                            self.links[ident].append(Crossing(target, tuple(leave), tuple(enter), ladder_id))

        self._incoming = defaultdict(list)
        self._outgoing = {}
        for here, crossings in self.links.items():
            # The portal cost belongs to frozen map geometry. Both searches
            # use the same float and preserve the original order of parallel edges.
            weighted = [(crossing, self._cost(here, crossing)) for crossing in crossings]
            self._outgoing[here] = weighted
            for crossing, cost in weighted:
                self._incoming[crossing.area].append((here, crossing, cost))

    def _cost(self, here, crossing):
        return (dist(self.centers[here], crossing.leave) + dist(crossing.leave, crossing.enter)
                + dist(crossing.enter, self.centers[crossing.area]))

    def routes_through(self, stages):
        """Shortest portal paths through ordered sets of alternative NAV areas.

        Plan backwards once for all spawns. Seed each preceding stage with
        the remaining cost, so a nearby landmark on a dead end cannot win.
        Costs are Hammer units along the same centre/portal metric as route().
        """
        legs = []
        remaining_costs = dict.fromkeys(self.areas, 0.0)
        for choices in reversed(stages):
            costs = {area: remaining_costs[area] for area in choices if area in remaining_costs}
            queue = [(cost, i) for i, cost in costs.items()]
            heapify(queue)
            onward = dict.fromkeys(costs)
            while queue:
                remaining, area = heappop(queue)
                if remaining != costs[area]:
                    continue
                for prior, crossing, length in self._incoming[area]:
                    candidate = remaining + length
                    if candidate < costs.get(prior, float("inf")):
                        costs[prior] = candidate
                        onward[prior] = crossing
                        heappush(queue, (candidate, prior))
            legs.append(onward)
            remaining_costs = costs
        return OrderedRoutes(remaining_costs, tuple(reversed(legs)))

    def locate(self, point, max_vertical):
        x, y, z = point
        candidates = []
        for ident in self._sectors.get((floor(x / 256), floor(y / 256)), ()):
            height = surface_height(self.areas[ident]["corners"], x, y)
            if height is not None and abs(z - height) <= max_vertical:
                candidates.append((abs(z - height), ident))
        return min(candidates)[1] if candidates else None

    def route(self, start, goal, *, avoided=frozenset(), excluded=frozenset()):
        """Return directed crossings to a goal, or None for an unreachable area."""
        if start not in self.areas or goal not in self.areas or goal in avoided:
            return None
        queue = [(dist(self.centers[start], self.centers[goal]), 0.0, start)]
        costs = {start: 0.0}
        parents = {}
        while queue:
            _, cost, here = heappop(queue)
            if cost != costs[here]:
                continue
            if here == goal:
                path = []
                while here != start:
                    here, crossing = parents[here]
                    path.append(crossing)
                return path[::-1]
            for crossing, edge_cost in self._outgoing.get(here, ()):
                target = crossing.area
                if target in avoided or (here, target) in excluded:
                    continue
                next_cost = cost + edge_cost
                if next_cost >= costs.get(target, float("inf")):
                    continue
                costs[target] = next_cost
                parents[target] = here, crossing
                estimate = dist(self.centers[target], self.centers[goal])
                heappush(queue, (next_cost + estimate, next_cost, target))
        return None


@dataclass
class OrderedRoutes:
    costs: dict
    legs: tuple

    def route(self, start):
        """Return directed crossings and the selected area at each stage."""
        if start not in self.costs:
            return None
        path, waypoints = [], []
        here = start
        for leg in self.legs:
            while (crossing := leg[here]) is not None:
                path.append(crossing)
                here = crossing.area
            waypoints.append(here)
        return path, waypoints
