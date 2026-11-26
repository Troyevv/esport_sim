"""Intersect a vertical NAV probe with exported Source 2 faces and primitives."""

import json
from math import sqrt

import numpy as np


def _quadratic_roots(a, b, c):
    # Equation a*t² + 2*b*t + c = 0.
    if a == 0:
        return [] if b == 0 else [-c / (2 * b)]
    delta = b * b - a * c
    if delta < 0:
        return []
    return [(-b - sqrt(delta)) / a, (-b + sqrt(delta)) / a]


def _primitive_interval(shape, origin, end):
    # System.Numerics transforms row vectors. Inverse-transform the probe so
    # non-uniform scaling preserves the original local radius.
    transform = np.asarray(shape["transform"], dtype=float).reshape(4, 3)
    start, finish = np.linalg.solve(transform[:3].T,
                                    (np.array([origin, end]) - transform[3]).T).T
    delta = finish - start
    centers = np.asarray(shape["centers"])
    axis = centers[-1] - centers[0]
    length = np.linalg.norm(axis)
    radius = shape["radius"]
    offset = start - centers[0]
    roots = []
    if length:
        axis = axis / length
        axial = offset @ axis
        speed = delta @ axis
        radial = offset - axial * axis
        velocity = delta - speed * axis
        roots.extend(t for t in _quadratic_roots(velocity @ velocity, radial @ velocity,
                                                 radial @ radial - radius**2)
                     if 0 <= axial + t * speed <= length)
    for center in centers:
        diff = start - center
        roots.extend(_quadratic_roots(delta @ delta, diff @ delta, diff @ diff - radius**2))
    if roots and max(roots) >= 0 and min(roots) <= 1:
        return max(0, min(roots)), min(1, max(roots))
    return None


def _edge_heights(points, x, y):
    # The XY projection of a vertical face is a segment. Clip its three
    # edges at the probe XY to recover the overlapping Z interval.
    heights = []
    for a, b in zip(points, np.roll(points, -1, axis=0)):
        dx, dy, dz = b - a
        length2 = dx * dx + dy * dy
        if length2 == 0:
            if abs(a[0] - x) < 1e-7 and abs(a[1] - y) < 1e-7:
                heights.extend((a[2], b[2]))
            continue
        t = ((x - a[0]) * dx + (y - a[1]) * dy) / length2
        if -1e-9 <= t <= 1 + 1e-9 and abs(dx * (y - a[1]) - dy * (x - a[0])) < 1e-7:
            heights.append(a[2] + t * dz)
    return heights


def _face_hits(triangles, x, y, bottom, top):
    # Discard faces outside the segment's bounding box before interpolation.
    indices, = np.nonzero(((triangles.min(axis=1) <= (x, y, top)) &
                           (triangles.max(axis=1) >= (x, y, bottom))).all(axis=1))
    for index in indices:
        points = triangles[index].astype(float)
        a, b, c = points
        ab, ac = b - a, c - a
        det = ab[0] * ac[1] - ab[1] * ac[0]
        if abs(det) < 1e-10:
            heights = _edge_heights(points, x, y)
            if heights and max(heights) >= bottom and min(heights) <= top:
                yield index, max(bottom, min(heights)), min(top, max(heights))
            continue
        u = ((x - a[0]) * ac[1] - (y - a[1]) * ac[0]) / det
        v = (ab[0] * (y - a[1]) - ab[1] * (x - a[0])) / det
        if min(u, v, 1 - u - v) >= -1e-9:
            z = a[2] + ab[2] * u + ac[2] * v
            if bottom <= z <= top:
                yield index, z, z


def trace_probes(folder, probes):
    geometry = json.loads((folder / "collision.json").read_bytes())
    if geometry["format"] != 1 or geometry["missingModels"]:
        raise ValueError(f"{folder.name}: неполная геометрия коллизий")
    binary = np.memmap(folder / "collision.bin", dtype="u1", mode="r")
    for probe in probes:
        probe["physicalHits"] = []

    def record(probe, block, kind, material, lo, hi):
        probe["physicalHits"].append(dict(
            kind=kind, entity=block["entity"], group=block.get("group"),
            tags=block["tags"], material=int(material),
            surface=geometry["surfaces"][str(material)], z=[float(lo), float(hi)],
        ))

    for block in geometry["blocks"]:
        nv, nf, offset = block["vertices"], block["triangles"], block["offset"]
        vertices = np.frombuffer(binary, "<f4", nv * 3, offset).reshape(nv, 3)
        lower, upper = vertices.min(axis=0), vertices.max(axis=0)
        candidates = [p for p in probes if lower[0] <= p["x"] <= upper[0]
                      and lower[1] <= p["y"] <= upper[1]
                      and p["bottom"] <= upper[2] and p["top"] >= lower[2]]
        if not candidates:
            continue
        indices = np.frombuffer(binary, "<i4", nf * 3, offset + 12 * nv).reshape(nf, 3)
        materials = (np.frombuffer(binary, "<u4", nf, offset + 12 * (nv + nf))
                     if block["perFace"] else None)
        triangles = vertices[indices]
        for p in candidates:
            for face, lo, hi in _face_hits(triangles, p["x"], p["y"], p["bottom"], p["top"]):
                material = materials[face] if materials is not None else block["material"]
                record(p, block, "triangle", material, lo, hi)
    for p in probes:
        for shape in geometry["primitives"]:
            interval = _primitive_interval(shape, (p["x"], p["y"], p["bottom"]),
                                           (p["x"], p["y"], p["top"]))
            if interval is not None:
                lo, hi = (p["bottom"] + t * (p["top"] - p["bottom"]) for t in interval)
                record(p, shape, shape["kind"], shape["material"], lo, hi)
        p["physicalHits"].sort(key=lambda h: h["z"])
