"""Installed Source 2 maps. Simulation coordinates use 1/12 Hammer units, Y down."""

import json
import os
import sys
from functools import cached_property, lru_cache, partial
from weakref import proxy
from math import atan2, dist, hypot
from heapq import heappop, heappush
from pathlib import Path

from .cs2_navigation import Navigation, surface_height
from .cs2_profiles import named_stages, resolve_anchors
from .cs2_sites import BombSites
from .match_rules import BLAST_RADIUS, ROLES

BUILD = 26879581
PROFILES = json.loads(
    Path(__file__).with_name("data").joinpath("maps_202611_tactics.json").read_bytes()
)
NAMES = dict(
    zip(
        PROFILES,
        (
            "Ancient",
            "Anubis",
            "Cache",
            "Dust II",
            "Inferno",
            "Mirage",
            "Nuke",
            "Train",
            "Vertigo",
        ),
    )
)
UNIT = 12.0


@lru_cache(maxsize=4)
def _root(override, local_data):
    if getattr(sys, "frozen", False) and not override:
        return Path(sys.executable).parent / "maps" / str(BUILD)
    if override:
        return Path(override)
    if os.name == "nt":
        from .paths import windows_data_dir

        return windows_data_dir() / "maps" / str(BUILD)
    return Path(__file__).resolve().parents[1] / "runtime-data" / "maps" / str(BUILD)


def root():
    return _root(os.environ.get("ESPORT_SIM_MAPS"), os.environ.get("LOCALAPPDATA"))


def installed():
    return [m for m in PROFILES if (root() / m / "provenance.json").is_file()]


@lru_cache(maxsize=2)
def _load(directory, name):
    if name not in NAMES:
        raise ValueError("Неизвестная карта CS2")
    folder = directory / name
    try:
        return Map(folder)
    except (OSError, KeyError) as exc:
        raise ValueError(
            f"Не удалось открыть {NAMES[name]}. Импортируйте карты версии {BUILD}: {exc}"
        ) from exc


def get(name):
    return _load(root(), name)


@lru_cache(maxsize=16)
def _description(directory, name):
    return _load(directory, name).descriptor


def description(name):
    return _description(root(), name)


def for_match(w):
    return get(w["mapId"]) if w.get("mapId") else None


def xyz(a):
    return a["x"], a["y"], a["z"]


class Map:
    def __init__(self, folder):
        self.folder = folder
        self.name = name = folder.name
        src = json.loads((folder / "provenance.json").read_bytes())
        data = json.loads((folder / "gameplay.json").read_bytes())
        if (
            src["map"] != name
            or data["map"] != name
            or int(src["steamBuild"]) != BUILD
            or src["unresolvedModels"]
        ):
            raise ValueError(f"{name}: неверная версия карты или неполные ресурсы")
        self.overview = src["overview"]
        self.nav = Navigation(data)
        self.sites = BombSites(data["targets"])
        self.spawns = {
            s: [p for p in data["spawns"] if p["enabled"] and p["side"] == s]
            for s in ("T", "CT")
        }
        self.profile = PROFILES[name]
        self.ladder_mounts = {
            self.to_sim(p)
            for ladder in data["ladders"]
            for p in (ladder["top"], ladder["bottom"])
        }
        self.places = resolve_anchors(
            self.profile,
            named_stages(data, self.nav, self.profile),
            self.nav,
            src["navSha256"],
        )
        self.centers = {}
        self.plants = {"A": [], "B": []}
        self.cover = []
        for i, center in self.nav.centers.items():
            x, y, z = center
            height = surface_height(self.nav.areas[i]["corners"], x, y)
            pos = (x, y, height if height is not None else z)
            self.centers[i] = self.to_sim(pos)
            site = self.sites.at((x, y, pos[2] + 1))
            if site:
                self.plants[site].append(i)
            for spot in self.nav.areas[i]["cover"]:
                point = spot["position"]
                if self.nav.locate(point, 64) == i:
                    height = surface_height(self.nav.areas[i]["corners"], *point[:2])
                    self.cover.append((i, self.to_sim((*point[:2], height))))
        self.site_points = {}
        self.holds = {}
        for site, areas in self.plants.items():
            if not areas or min(map(len, self.spawns.values())) < 5:
                raise ValueError(f"{name}: неполные спавны или плент {site}")
            mean = tuple(
                sum(self.centers[i][axis] for i in areas) / len(areas)
                for axis in range(3)
            )
            center = min(areas, key=lambda i: dist(self.centers[i], mean))
            self.site_points[site] = self.centers[center]
            self.holds[site] = sorted(self.cover, key=lambda item: dist(item[1], mean))[
                :16
            ]
        self.passage = lru_cache(maxsize=32768)(partial(Map._passage, proxy(self)))
        self.gate = lru_cache(maxsize=32768)(partial(Map._gate, proxy(self)))
        self.inside = lru_cache(maxsize=32768)(partial(Map._inside, proxy(self)))
        self.path = lru_cache(maxsize=4096)(partial(Map._path, proxy(self)))
        self.route = lru_cache(maxsize=8192)(self.nav.route)
        self.approach = lru_cache(maxsize=32)(partial(Map._approach, proxy(self)))
        self.escape = lru_cache(maxsize=16)(partial(Map._escape, proxy(self)))
        self.locate = lru_cache(maxsize=8192)(partial(Map._locate, proxy(self)))

    @cached_property
    def collision(self):
        from .cs2_collision import Collision

        return Collision(self.folder)

    def to_sim(self, p):
        return (
            (p[0] - self.overview["pos_x"]) / UNIT,
            (self.overview["pos_y"] - p[1]) / UNIT,
            p[2] / UNIT,
        )

    def world(self, p):
        return (
            self.overview["pos_x"] + p[0] * UNIT,
            self.overview["pos_y"] - p[1] * UNIT,
            p[2] * UNIT,
        )

    def _locate(self, point):
        return self.nav.locate(self.world(point), 96)

    def site_at(self, pos):
        x, y, z = self.world(pos)
        return self.sites.at((x, y, z + 1))

    def spawn(self, side, slot, selection=0):
        choices = self.spawns[side]
        spawn = choices[(selection + slot) % len(choices)]
        p = spawn["position"]
        ident = self.nav.locate(p, 96)
        height = surface_height(self.nav.areas[ident]["corners"], *p[:2])
        return self.to_sim((*p[:2], height)), -spawn["heading"], ident

    def _approach(self, site, variant):
        labels = self.profile[site][variant]
        return self.nav.routes_through(
            [self.places[n] for n in labels] + [self.plants[site]]
        )

    def _escape(self, bomb):
        goals = [
            i for i, p in self.centers.items() if dist(p, bomb) >= BLAST_RADIUS + 4
        ]
        return self.nav.routes_through([goals])

    def orders(self, side, site, squad, lane, style=None):
        slots = []
        for player in sorted(squad, key=lambda a: a["slot"]):
            i = player["slot"]
            defended = (
                ("A" if i in (0, 2) else "B") if side == "CT" and i != 4 else site
            )
            variant = lane if i in (0, 2, 4) else 1 - lane
            if side == "T" and style == "Групповой выход":
                variant = lane
            elif side == "T" and player.get("playingRole") in ("entry", "support"):
                variant = lane
            start = player["navArea"]
            if side == "T":
                options = self.approach(site, variant)
                selected = options.route(start)
                if selected is None:
                    # A mid-round call can originate beyond a one-way transition.
                    selected = self.approach(site, 1 - variant).route(start)
                waypoints = (
                    [self.centers[j] for j in selected[1][:-1]] if selected else []
                )
                plant = (
                    self.centers[selected[1][-1]]
                    if selected
                    else self.site_points[site]
                )
            else:
                guards = self.profile["guards"][defended]
                choices = self.places[guards[(i // 2) % len(guards)]]
                usable = [
                    j for j in sorted(choices) if self.route(start, j) is not None
                ]
                waypoints = (
                    [
                        self.centers[
                            min(
                                usable, key=lambda j: dist(xyz(player), self.centers[j])
                            )
                        ]
                    ]
                    if usable
                    else []
                )
                plant = self.site_points[defended]
            hold = waypoints[-1] if side == "CT" and waypoints else plant
            if side == "T" or i == 4:
                covers = [
                    p
                    for j, p in self.holds[defended]
                    if self.route(start, j) is not None and dist(p, plant) < 55
                ]
                if covers:
                    hold = covers[(i + lane * 3) % len(covers)]
            # Validate consecutive orders against this map's active physical
            # state. A label is a region; its representative centre can be
            # inside a prop even when adjacent parts of the region are usable.
            pos = xyz(player)
            reachable = []
            for marker in waypoints:
                nearby = sorted(
                    self.nearby_areas(marker, 12),
                    key=lambda j: dist(self.centers[j], marker),
                )
                landing = self._reachable(
                    pos,
                    [
                        marker,
                        *(self.centers[j] for j in nearby if self.centers[j] != marker),
                    ],
                )
                if landing is not None:
                    reachable.append(landing)
                    pos = landing
            waypoints = reachable
            if side == "T":
                options = sorted(
                    self.plants[site], key=lambda j: dist(self.centers[j], plant)
                )
                landing = self._reachable(pos, [self.centers[j] for j in options])
                if landing is None:
                    # A one-way staging area can disconnect the site. Replan
                    # from the last reachable earlier stage before issuing a call.
                    while waypoints and landing is None:
                        waypoints.pop()
                        pos = waypoints[-1] if waypoints else xyz(player)
                        landing = self._reachable(
                            pos, [self.centers[j] for j in options]
                        )
                if landing is not None:
                    plant = landing
            hold = (
                self._reachable(
                    pos, [hold, *(p for _, p in self.holds[defended]), plant]
                )
                or pos
            )
            slots.append(
                dict(
                    role=ROLES[i],
                    approach=list(waypoints[0] if waypoints else hold),
                    via=[list(p) for p in waypoints],
                    stage=list(waypoints[-1] if waypoints else plant),
                    hold=list(hold),
                    plant=list(plant),
                    site=defended,
                    watch=list(self._watch(defended, hold, variant)),
                )
            )
        return dict(version=1, map=self.name, geometry=BUILD, slots=slots)

    def _watch(self, site, pos, variant):
        label = self.profile[site][variant][-1]
        options = [self.centers[i] for i in self.places[label]]
        return min(options, key=lambda p: dist(p, pos))

    def hit(self, p, q, channel, up=0, target_up=None):
        a, b = self.world(p), self.world(q)
        return self.collision.trace(
            (*a[:2], a[2] + up),
            (*b[:2], b[2] + (up if target_up is None else target_up)),
            channel,
        )

    def shot_transmission(self, start, end, power):
        length = dist(start, end)
        if not length:
            return 1.0
        # Game surfaces may be open meshes or nested closed hulls. Trace the
        # whole segment, so a thin pane in front of solid world geometry
        # cannot make the geometry behind it penetrable.
        open_layers = {}
        transmission = 1.0
        offset = 0.0
        while offset < 1:
            origin = tuple(a + (b - a) * offset for a, b in zip(start, end))
            hit = self.hit(origin, end, 4, 56)
            if not hit:
                break
            t, material, _ = hit
            at = offset + (1 - offset) * t
            resistance = {
                "glass": 0.08,
                "cardboard": 0.09,
                "plastic": 0.16,
                "wood": 0.25,
                "wood_panel": 0.25,
                "metalgrate": 0.18,
            }.get(material)
            if resistance is None:
                return 0.0
            if material in open_layers:
                width = (at - open_layers.pop(material)) * length
                transmission -= resistance * width / max(0.1, power)
            else:
                open_layers[material] = at
                transmission -= resistance * 0.5 / max(0.1, power)
            if transmission <= 0:
                return 0.0
            offset = at + max(1e-6, 0.002 / length)
        return transmission

    def grenade(self, origin, target, flight):
        # Tick-integrated game projectile. Resolve the remaining fraction of a
        # tick after each bounce in the same geometry used for gunfire.
        pos = (*origin[:2], origin[2] + 4)
        gravity = 8 * min(18, flight) / flight**2
        velocity = [(target[i] - pos[i]) / flight for i in range(3)]
        velocity[2] += gravity * (flight - 1) / 2
        track = [pos]
        for _ in range(flight):
            remaining = 1.0
            for _ in range(4):
                end = tuple(p + v * remaining for p, v in zip(pos, velocity))
                hit = self.hit(pos, end, 8)
                if hit is None:
                    pos = end
                    break
                t, _, normal = hit
                dot = sum(v * n for v, n in zip(velocity, normal))
                if dot > 0:
                    normal = tuple(-n for n in normal)
                    dot = -dot
                pos = tuple(
                    p + v * remaining * t + n * 0.02
                    for p, v, n in zip(pos, velocity, normal)
                )
                velocity = [
                    0.65 * (v - 1.55 * dot * n) for v, n in zip(velocity, normal)
                ]
                remaining *= 1 - t
            track.append(pos)
            velocity[2] -= gravity
        return *pos, track

    def visible_pairs(self, pairs):
        if not pairs:
            return set()
        eyes = {}
        for pair in pairs:
            for agent in pair:
                if agent["id"] not in eyes:
                    x, y, z = self.world(xyz(agent))
                    eyes[agent["id"]] = (x, y, z + 64)
        segments = [(eyes[a["id"]], eyes[b["id"]]) for a, b in pairs]
        clear = self.collision.sight_many(segments)
        return {
            (a["id"], b["id"])
            for (a, b), segment in zip(pairs, segments)
            if clear[segment]
        }

    def clear(self, a, b):
        # Actor positions are feet. Dropped equipment and landed effects
        # are close to the surface, including when they are behind low cover.
        eye_a = 64 if "hp" in a else 5
        eye_b = 64 if "hp" in b else 5
        return self.hit(xyz(a), xyz(b), 1, eye_a, eye_b) is None

    def _passage(self, start, end, climbing=False):
        # NAV already accounts for hull width. Check the body above the NAV
        # step height, including props and player clips absent from NAV.
        return start == end or self.hit(start, end, 16 if climbing else 2, 34) is None

    def _inside(self, area, start, end, climbing=False):
        climbing = climbing or start in self.ladder_mounts
        if self.passage(start, end, climbing):
            return [(end, area)]
        # A convex NAV surface can contain a placed prop. Build a small
        # local visibility graph only when that prop interrupts a straight leg.
        center = self.centers[area]
        corners = self.nav.areas[area]["corners"]
        candidates = [center]
        for index, corner in enumerate(corners):
            other = corners[(index + 1) % len(corners)]
            for t in (0.0, 0.5):
                edge = self.to_sim(
                    tuple(a + (b - a) * t for a, b in zip(corner, other))
                )
                for fraction in (0.45, 0.9):
                    point = tuple(c + (e - c) * fraction for c, e in zip(center, edge))
                    wx, wy, _ = self.world(point)
                    z = surface_height(corners, wx, wy)
                    if z is not None:
                        candidates.append((point[0], point[1], z / UNIT))
        candidates = list(dict.fromkeys([*candidates, end]))
        queue = [(dist(start, end), 0.0, start)]
        cost = {start: 0.0}
        parent = {}
        while queue:
            _, length, pos = heappop(queue)
            if length != cost[pos]:
                continue
            if pos == end:
                steps = []
                while pos != start:
                    steps.append((pos, area))
                    pos = parent[pos]
                return steps[::-1]
            for nex in candidates:
                n = length + dist(pos, nex)
                if n >= cost.get(nex, float("inf")) or not self.passage(
                    pos, nex, climbing
                ):
                    continue
                cost[nex], parent[nex] = n, pos
                heappush(queue, (n + dist(nex, end), n, nex))
        return None

    def _gate(self, area, start, cross):
        for a, b in ((cross.leave, cross.enter), *cross.alternatives):
            leave, enter = self.to_sim(a), self.to_sim(b)
            inside = self.inside(area, start, leave, cross.ladder is not None)
            if inside is None:
                continue
            if self.passage(leave, enter, cross.ladder is not None):
                return [*inside, (enter, cross.area)]
            # A raised NAV edge is a step or jump. Crossing it on the
            # diagonal can strike the vertical riser. Test the rise/drop
            # and the horizontal segment individually against the same body mask.
            if cross.ladder is None and 1 < abs(a[2] - b[2]) <= 64:
                high = max(leave[2], enter[2]) + 0.1
                corner = (*((leave if leave[2] < enter[2] else enter)[:2]), high)
                if self.passage(leave, corner) and self.passage(corner, enter):
                    return [*inside, (corner, area), (enter, cross.area)]
        return None

    def _path(self, area, start, zone, goal, avoided):
        route = (
            self.nav.route(area, zone, avoided=avoided)
            if avoided
            else self.route(area, zone)
        )
        if route is None:
            return None
        points = []
        here, pos = area, start
        for crossing in route:
            leg = self.gate(here, pos, crossing)
            if leg is None:
                break
            points.extend(leg)
            pos, here = leg[-1]
        else:
            end = self.inside(zone, pos, goal)
            if end is not None:
                return tuple((*p, i) for p, i in points + end)

        # The same NAV polygon can be entered on either side of a placed prop.
        # Preserve the entry point in the search state, including for one-way links.
        initial = (area, start)
        queue = [(dist(start, goal), 0.0, initial)]
        costs = {initial: 0.0}
        parents = {}
        while queue:
            _, length, key = heappop(queue)
            if length != costs[key]:
                continue
            here, pos = key
            if here == zone:
                end = self.inside(zone, pos, goal)
                if end is not None:
                    legs = [end]
                    while key != initial:
                        key, leg = parents[key]
                        legs.append(leg)
                    return tuple((*q, i) for chain in reversed(legs) for q, i in chain)
            for cross in self.nav.links[here]:
                if cross.area in avoided:
                    continue
                leg = self.gate(here, pos, cross)
                if leg is None:
                    continue
                tip, other = leg[-1]
                target = (other, tip)
                traveled = length
                prev = pos
                for q, _ in leg:
                    traveled += dist(prev, q)
                    prev = q
                if traveled >= costs.get(target, float("inf")):
                    continue
                parents[target] = (key, leg)
                costs[target] = traveled
                heappush(queue, (traveled + dist(tip, goal), traveled, target))
        return None

    def _reachable(self, origin, points):
        start = self.locate(origin)
        if start is None:
            return None
        for point in points:
            point = tuple(point)
            target = self.locate(point)
            if (
                target is not None
                and self.path(start, origin, target, point, frozenset()) is not None
            ):
                return point
        return None

    def walk(self, a, goal, pace, hazards):
        here = a["navArea"]
        goal = tuple(goal)
        zone = self.locate(goal)
        pos = xyz(a)
        if dist(goal, pos) < 1e-6:
            a["blockedTicks"] = 0
            return False
        if zone is None:
            a["blockedTicks"] = a.get("blockedTicks", 0) + 1
            return False
        avoided = frozenset()
        if hazards:
            avoided = frozenset(
                i
                for fire in hazards
                for i in self.nearby_areas(xyz(fire), fire["radius"])
                if i not in (here, zone)
            )
        dest = [zone, *goal, sorted(avoided)]
        crossing = bool(a["path"] and a["path"][0][3] != here)
        if (a["dest"] != dest and not crossing) or not a["path"]:
            path = self.path(here, pos, zone, goal, avoided)
            if path is None:
                a["blockedTicks"] = a.get("blockedTicks", 0) + 1
                return False
            a["path"], a["dest"] = [list(node) for node in path], dest
        a["blockedTicks"] = 0
        moved = False
        while a["path"] and pace > 0:
            node = a["path"][0]
            endpoint = tuple(node[:3])
            length = dist(pos, endpoint)
            if any(
                dist(endpoint, xyz(f)) < f["radius"] <= dist(pos, xyz(f))
                for f in hazards
            ):
                a["status"] = "Пережидает огонь за укрытием"
                return moved
            if length > 0:
                fraction = min(1, pace / length)
                nxt = (
                    tuple(p + (q - p) * fraction for p, q in zip(pos, endpoint))
                    if fraction < 1
                    else endpoint
                )
                if hypot(nxt[0] - pos[0], nxt[1] - pos[1]) > 1e-6:
                    a["heading"] = atan2(nxt[1] - pos[1], nxt[0] - pos[0])
                a["x"], a["y"], a["z"] = nxt
                pos = nxt
                moved = True
            pace -= length
            if pace >= 0:
                a["navArea"] = node[3]
                a["path"].pop(0)
        return moved

    def nearby_areas(self, pos, radius):
        from math import floor

        x, y, _ = self.world(pos)
        reach = radius * UNIT
        candidates = set()
        for ix in range(floor((x - reach) / 256), floor((x + reach) / 256) + 1):
            for iy in range(floor((y - reach) / 256), floor((y + reach) / 256) + 1):
                candidates.update(self.nav._sectors.get((ix, iy), ()))
        return [i for i in candidates if dist(pos, self.centers[i]) < radius]

    def pick(self, x, y, layer, previous_z):
        from math import floor

        wx, wy, _ = self.world((x, y, 0))
        bounds = self.overview.get("verticalsections", {}).get(layer, {})
        options = []
        for i in self.nav._sectors.get((floor(wx / 256), floor(wy / 256)), ()):
            z = surface_height(self.nav.areas[i]["corners"], wx, wy)
            if z is not None and float(bounds.get("AltitudeMin", -1e8)) <= z <= float(
                bounds.get("AltitudeMax", 1e8)
            ):
                options.append(z / UNIT)
        if not options:
            raise ValueError("В этой точке на выбранном этаже нет поверхности NAV")
        return min(options, key=lambda z: (abs(z - previous_z), z))

    @cached_property
    def descriptor(self):
        scale = self.overview["scale"] / UNIT
        spawns = []
        for side in ("T", "CT"):
            for i in range(len(self.spawns[side])):
                (x, y, z), _, _ = self.spawn(side, i)
                spawns.append(dict(team=side, x=x, y=y, z=z))
        zones = []
        for site, p in self.site_points.items():
            zones.append(dict(name=site, x=p[0] - 4, y=p[1] - 4, z=p[2], w=8, h=8))
        return dict(
            id=self.name,
            version=BUILD,
            name=NAMES[self.name],
            author=f"Valve · Steam {BUILD}",
            width=1024 * scale,
            height=1024 * scale,
            walls=[],
            zones=zones,
            spawns=spawns,
            radar=f"/api/maps/{self.name}/radar.png",
            layers=self.overview.get("verticalsections", {}),
        )
