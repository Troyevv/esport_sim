"""Map import and differential adapter for the C++ physical world."""
from functools import cached_property, lru_cache, partial
from weakref import proxy

from . import _match_native as native
from .cs2_collision import Collision
from .cs2_maps import Map, UNIT, xyz
from .match_rules import BLAST_RADIUS
from .native_navigation import NativeNavigation


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
