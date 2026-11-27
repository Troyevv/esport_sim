"""Import installed map geometry once and share its native owners."""
import json
from math import dist
from functools import cached_property, lru_cache, partial
from weakref import proxy

from . import _match_native as native
from .cs2_collision import CollisionData
from .cs2_maps import BUILD, Map, UNIT, xyz
from .match_rules import BLAST_RADIUS, ROLES
from .native_navigation import NativeNavigation


class NativeCollision(CollisionData):
    def __init__(self, folder):
        super().__init__(folder, native.TriangleScene)
        materials = {name: i for i, name in enumerate(self.materials)}
        shapes = [native.Primitive(
            s.inv, s.translation, s.centers[0], s.centers[-1], s.axis, s.length,
            s.radius, s.lo, s.hi, s.mask, materials[s.material],
        ) for s in self.shapes]
        self.world = native.CollisionWorld(self.scene, self.material, shapes)
        self.trace = lru_cache(maxsize=32768)(partial(NativeCollision._trace, proxy(self)))

    def _trace(self, source, target, channel, terminal=False):
        hit = self.world.trace(source, target, channel, terminal)
        if hit is not None:
            distance, material, normal = hit
            return distance, self.materials[material], tuple(normal) if normal is not None else None
        return None

    def sight_many(self, segments):
        return dict(zip(segments, self.world.visible(segments), strict=True))


class NativePhysicalMap(Map):
    """Own one planner for the installed map; all search nodes stay in C++."""

    _make_navigation = staticmethod(NativeNavigation)

    @cached_property
    def collision(self):
        return NativeCollision(self.folder)

    @cached_property
    def planner(self):
        edges = [native.PhysicalCrossing(area, cross.area, cross.ladder is not None,
                                         [(cross.leave, cross.enter), *cross.alternatives])
                 for area, links in self.nav.links.items() for cross in links]
        return native.PhysicalNavigation(
            self.collision.world, self.nav.graph, self.nav.surfaces,
            (self.overview["pos_x"], self.overview["pos_y"], 0), UNIT, self.centers,
            [(area, desc["corners"]) for area, desc in self.nav.areas.items()],
            self.ladder_mounts, edges,
        )

    def _path(self, area, start, zone, goal, avoided):
        if area is None or zone is None:
            return None
        path = self.planner.path(area, start, zone, goal, avoided)
        return None if path is None else tuple(path)

    def orders(self, side, site, squad, lane, style=None):
        # Editor drafts have spawn slots but no assigned playing roles.
        world = dict(mapId=self.name, map_version=BUILD,
                     agents=[{"playingRole":"", **actor, "team":side} for actor in squad])
        return json.loads(self.opening.editor_orders(json.dumps(world), side, site, lane, style or ""))


class NativePerceptionMap(NativePhysicalMap):
    @cached_property
    def objectives(self):
        solids = {site: [solid.faces for solid in volumes] for site, volumes in self.sites.volumes.items()}
        ingress = {site: [self.ingress(site, lane) for lane in (0, 1)] for site in self.sites.volumes}
        data = native.SiteData(solids, self.site_costs, self.plant_surfaces, ingress)
        return native.Objectives(self.planner, data)

    @cached_property
    def opening(self):
        # Static costs and named NAV surfaces are shared by matches on this map.
        contest = {site: [self.contest(site, lane) for lane in (0, 1)] for site in self.site_points}
        stations = {label: [self.centers[i] for i in sorted(ids)] for label, ids in self.places.items()}
        stages = {i for site in self.site_points for lane in self.profile[site]
                  for label in lane for i in self.places[label]}
        nearby = {i: sorted(self.nearby_areas(self.centers[i], 12),
                            key=lambda j: dist(self.centers[j], self.centers[i])) for i in stages}
        plant_corners = {i: [self.to_sim(p) for p in self.nav.areas[i]["corners"]]
                         for ids in self.plants.values() for i in ids}
        orders = native.OrderData({label: list(ids) for label, ids in self.places.items()}, self.plants, self.holds, nearby, ROLES, [p for _, p in self.cover], self.attack_spawns, plant_corners)
        return native.OpeningMap(self.objectives, json.dumps(self.profile), json.dumps(self.defense),
                                 contest, stations, self.site_points, orders)
