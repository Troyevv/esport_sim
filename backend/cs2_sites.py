"""Bomb-target volumes in world coordinates from the Source 2 collision models."""

from math import atan2, dist, pi


def _difference(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


class Solid:
    def __init__(self, geometry):
        vertices = geometry["vertices"]
        self.bounds = tuple((min(axis), max(axis)) for axis in zip(*vertices))
        self.faces = [tuple(vertices[i] for i in face) for face in geometry["triangles"]]

    def contains(self, point):
        if any(x < lo - 1e-6 or x > hi + 1e-6 for x, (lo, hi) in zip(point, self.bounds)):
            return False
        # Sum signed solid angles. Shared triangle edges do not count twice as
        # they can when a ray goes through the diagonal of a quadrilateral.
        angle = 0.0
        for a, b, c in self.faces:
            u, v, w = (_difference(p, point) for p in (a, b, c))
            normal = _cross(_difference(b, a), _difference(c, a))
            normal2 = _dot(normal, normal)
            if normal2 < 1e-14:
                continue
            det = _dot(u, _cross(v, w))
            if abs(det) <= 1e-7 * normal2**0.5:
                # An interior point on any face, edge or vertex belongs to the trigger.
                if min(_dot(_cross(p, q), normal) for p, q in ((u, v), (v, w), (w, u))) >= -1e-8 * normal2:
                    return True
            lu, lv, lw = (dist(p, point) for p in (a, b, c))
            denom = lu * lv * lw + _dot(u, v) * lw + _dot(v, w) * lu + _dot(w, u) * lv
            angle += 2 * atan2(det, denom)
        return abs(angle) > 2 * pi


class BombSites:
    def __init__(self, entities):
        self.volumes = {"A": [], "B": []}
        for entity in entities:
            self.volumes[entity["site"]].extend(Solid(s) for s in entity["solids"])
        if not all(self.volumes.values()):
            raise ValueError("В карте отсутствует физический объём одного из плентов")

    def at(self, point):
        for site, solids in self.volumes.items():
            if any(solid.contains(point) for solid in solids):
                return site
        return None
