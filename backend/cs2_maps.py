"""Installed Source 2 maps. Simulation coordinates use 1/12 Hammer units, Y down."""

import json
import os
import sys
from functools import cached_property, lru_cache, partial
from weakref import proxy
from math import dist
from pathlib import Path

from .cs2_navigation import Navigation, surface_height
from .cs2_profiles import named_stages, resolve_anchors
from .cs2_sites import BombSites
from .match_rules import BLAST_RADIUS, ROLES, UTILITY

BUILD = 26879581
# These rule revisions share map schema 2 and the same checkpoint migration.
# The build ID and checkpoint version are validated independently on load.
SUPPORTED_RULES = tuple(f"cs2-bo1.{version}" for version in range(20, 0, -1))
RULES, PREVIOUS_RULES = SUPPORTED_RULES[:2]
PROFILES = json.loads(
    Path(__file__).with_name("data").joinpath("maps_202611_tactics.json").read_bytes()
)
CT_OPENINGS = json.loads(
    Path(__file__).with_name("data").joinpath("ct_openings.json").read_bytes()
)
RUNTIME_FILES = json.loads(
    Path(__file__).with_name("data").joinpath(f"maps-runtime-{BUILD}.json").read_bytes()
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


_active_root = None


def use_runtime(folder):
    global _active_root
    _active_root = folder
    _load.cache_clear()
    _description.cache_clear()


def root():
    return _active_root or _root(os.environ.get("ESPORT_SIM_MAPS"), os.environ.get("LOCALAPPDATA"))


def installed():
    directory = root()
    return [m for m in PROFILES if all((directory / m / file).is_file() for file in RUNTIME_FILES[m])]


@lru_cache(maxsize=2)
def _load(directory, name):
    if name not in NAMES:
        raise ValueError("Неизвестная карта CS2")
    folder = directory / name
    try:
        from .native_physics import NativePerceptionMap
        return NativePerceptionMap(folder)
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
        self.nav = self._make_navigation(data)
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
        self.defense = CT_OPENINGS[name]
        self.places = resolve_anchors(
            self.profile,
            named_stages(
                data,
                self.nav,
                self.profile,
                {
                    label
                    for _, seat, watch in self.defense["zones"].values()
                    for label in (seat, watch)
                },
            ),
            self.nav,
            src["navSha256"],
        )
        approaches = {site: {area for route in self.profile[site] for label in route[-2:]
                            for area in self.places[label]} for site in ("A", "B")}
        self.entry_sites = {i: site for site, areas in approaches.items()
                            for i in areas - approaches["B" if site == "A" else "A"]}
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
        self.site_costs = {site: self.nav.routes_through([areas]).costs for site, areas in self.plants.items()}
        self.path = lru_cache(maxsize=4096)(partial(type(self)._path, proxy(self)))
        self.approach = lru_cache(maxsize=32)(partial(Map._approach, proxy(self)))
        self.contest = lru_cache(maxsize=4)(partial(Map._contest, proxy(self)))
        self.ingress = lru_cache(maxsize=4)(partial(Map._ingress, proxy(self)))
        self.locate = lru_cache(maxsize=8192)(partial(Map._locate, proxy(self)))

    @cached_property
    def attack_spawns(self):
        return tuple(self.spawn("T", i)[2] for i in range(len(self.spawns["T"])))

    @cached_property
    def plant_surfaces(self):
        """Representative legal locations including trigger edges cutting NAV polygons."""
        from math import ceil, floor
        result = {}
        for site, solids in self.sites.volumes.items():
            positions = {self.centers[i] for i in self.plants[site]}
            for solid in solids:
                (xmin,xmax),(ymin,ymax),_ = solid.bounds
                # Only consult NAV bins overlapping this trigger's bounds.
                for ix in range(floor(xmin/64),ceil(xmax/64)+1):
                    x = max(xmin,min(xmax,ix*64))
                    for iy in range(floor(ymin/64),ceil(ymax/64)+1):
                        y = max(ymin,min(ymax,iy*64))
                        for area in self.nav._sectors.get((floor(x/256),floor(y/256)),()):
                            z = surface_height(self.nav.areas[area]["corners"],x,y)
                            if z is not None and solid.contains((x,y,z+1)):
                                positions.add(self.to_sim((x,y,z)))
            # Distribute samples over the surface without overweighting a dense NAV patch.
            samples = [self.site_points[site]]
            gaps = {p:dist(p,samples[0]) for p in sorted(positions)}
            while len(samples)<24 and gaps:
                point = max(gaps,key=gaps.get)
                if gaps.pop(point)<3:
                    break
                samples.append(point)
                for p in gaps:
                    gaps[p] = min(gaps[p],dist(p,point))
            result[site] = tuple(samples)
        return result

    @staticmethod
    def _make_navigation(data):
        return Navigation(data)

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

    def _contest(self, site, lane):
        # Both teams know legal spawns. Estimate a race to the final approach
        # without knowing which opposing spawn or opening a player actually drew.
        label = self.profile[site][lane][-1]
        center = self.site_points[site]
        entrances = [q for q in self.ingress(site,lane) if dist(q,center) < 60]
        if not entrances:
            entrances = [self.centers[i] for i in sorted(self.places[label])]
        # Leaving the last doorway is the contested event. A defender can
        # already cover it from the site without ever entering that doorway.
        crossing = min(entrances, key=lambda q:abs(30-dist(q,center)))
        entry = self.locate(crossing)
        costs = self.nav.routes_through([[entry] if entry is not None else self.places[label]]).costs
        guards = [self.spawn("CT", i)[2] for i in range(len(self.spawns["CT"]))]
        candidates = sorted(set(self.nearby_areas(center,52)) |
                            {i for label in self.profile["guards"][site] for i in self.places[label]})
        def eye(q):
            x,y,z=self.world(q)
            return x,y,z+64
        end = eye(crossing)
        positions = [(i,(eye(self.centers[i]),end)) for i in candidates if 5 < dist(self.centers[i],crossing) < 95]
        visible = self.collision.sight_many([line for _,line in positions])
        defensible = [i for i,line in positions if visible.get(line)]
        defence = self.nav.routes_through([defensible]).costs if defensible else costs
        return costs, min((defence.get(i,float("inf")) for i in guards),default=0)

    def _ingress(self, site, variant):
        # A defender knows the map entrances, not the opponents' live route.
        # Sample navigable approaches behind the final named entry as well as
        # the approach to the plant, so an anchor can see a crossing in time.
        _, _, start = self.spawn("T", 0)
        route = self.approach(site, variant).route(start)
        samples = []
        if route:
            crossings, stages = route
            entrance = (
                self.centers[stages[-2]] if len(stages) > 1 else self.site_points[site]
            )
            for cross in crossings:
                p = self.to_sim(cross.enter)
                if (
                    dist(p, entrance) < 65 or dist(p, self.site_points[site]) < 55
                ) and (not samples or dist(p, samples[-1]) >= 6):
                    samples.append(p)
        return samples

    def hit(self, p, q, channel, up=0, target_up=None, *, terminal=False):
        a, b = self.world(p), self.world(q)
        return self.collision.trace(
            (*a[:2], a[2] + up),
            (*b[:2], b[2] + (up if target_up is None else target_up)),
            channel, terminal,
        )

    def clear(self, a, b):
        # Actor positions are feet. Dropped equipment and landed effects
        # are close to the surface, including when they are behind low cover.
        eye_a = 64 if "hp" in a else 5
        eye_b = 64 if "hp" in b else 5
        return self.hit(xyz(a), xyz(b), 1, eye_a, eye_b) is None

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
