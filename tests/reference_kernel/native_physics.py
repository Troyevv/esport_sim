"""Map import and differential adapter for the C++ physical world."""
import json
from math import dist
from functools import cached_property, lru_cache, partial
from weakref import proxy

from backend import _match_native as native
from backend.cs2_collision import Collision
from .cs2_maps import Map, UNIT, xyz
from backend.match_rules import BLAST_RADIUS, ROLES
from backend.native_navigation import NativeNavigation


class NativeCollision(Collision):
    _make_scene = staticmethod(native.TriangleScene)

    def _finish_geometry(self):
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

    def _physical_exit(self, area, origin, bomb):
        result = self.planner.escape(area, origin, bomb, BLAST_RADIUS + 4)
        if result is not None:
            distance, path = result
            return distance, tuple(path)
        return None


class NativeMovementMap(NativePhysicalMap):
    def walk(self, actor, goal, pace, hazards):
        prior = actor["dest"]
        destination = (prior[0], prior[1:4], set(prior[4])) if len(prior) == 5 and prior[0] is not None else None
        current = native.MotionState(
            xyz(actor), actor["navArea"], actor["heading"], actor.get("blockedTicks", 0),
            actor["path"], destination,
        )
        updated, result = self.planner.walk(
            current, goal, pace, [(xyz(f), f["radius"]) for f in hazards],
        )
        actor["blockedTicks"] = updated.blocked_ticks
        if result.replanned:
            zone, point, avoided = updated.destination
            actor["dest"] = [zone, *point, sorted(avoided)]
            actor["path"] = [list(node) for node in updated.path]
        elif result.consumed:
            del actor["path"][:result.consumed]
        if result.moved:
            actor["x"], actor["y"], actor["z"] = updated.position
            actor["heading"] = updated.heading
        actor["navArea"] = updated.area
        if result.waiting:
            actor["status"] = "Пережидает огонь за укрытием"
        return result.moved

    def grenade(self, origin, target, flight):
        track = [tuple(p) for p in self.planner.grenade(origin, target, flight)]
        return *track[-1], track


class NativePerceptionMap(NativeMovementMap):
    @cached_property
    def sensors(self):
        return native.MapSensors(self.planner, self.collision.materials)

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

    def shot_transmission(self, start, end, power):
        return self.sensors.shot_transmission(start, end, power)


def observed_players(space, players, now, smoke):
    observers = [native.Observer(xyz(a), a["heading"], a["team"] == "T", a["blind"] > now)
                 for a in players]
    seen = space.sensors.observe(observers, [(xyz(f), f["radius"]) for f in smoke])
    return {actor["id"]: [players[i] for i in targets]
            for actor, targets in zip(players, seen, strict=True)}


def hearing_estimates(w, space, source, guards, radius):
    from backend.world import match_player

    guards = list(guards)
    skills = [match_player(w, a)["skills"] for a in guards]
    listeners = [native.Listener(xyz(a), s["game_reading"], a["team"] == "CT" and bool(a["hp"])
                                 and source.get("id") not in a["visible"])
                 for a, s in zip(guards, skills, strict=True)]
    for cue in space.sensors.hear(xyz(source), radius, listeners):
        yield guards[cue.listener], skills[cue.listener], cue.estimate, cue.confidence
