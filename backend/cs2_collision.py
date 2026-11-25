"""BVH segment queries on the pinned CS2 collision export, in Hammer XYZ."""

import json
from collections import OrderedDict
from functools import lru_cache, partial
from weakref import proxy
from math import sqrt

import numpy as np
from .cs2_rays import TriangleScene

SIGHT, MOVEMENT, PROJECTILE, THROW, CLIMB = 1, 2, 4, 8, 16


def channels(tags, group, material):
    tags = set(tags)
    clip = tags & {"playerclip", "npcclip", "csgo_grenadeclip", "navclip"}
    if clip and not tags & {"solid", "window", "passbullets"}:
        move = (
            (MOVEMENT if "ladder" in tags else MOVEMENT | CLIMB)
            if "playerclip" in tags
            else 0
        )
        return move | (THROW if "csgo_grenadeclip" in tags else 0)
    if not (
        group in ("Default", "default", "", None)
        or tags & {"solid", "window", "passbullets", "sky", "blocklos"}
    ):
        return 0
    mask = MOVEMENT | THROW | (0 if "ladder" in tags else CLIMB)
    if "passbullets" not in tags:
        mask |= PROJECTILE
        if not (tags & {"window", "sky"} or "glass" in material):
            mask |= SIGHT
    return mask


def _roots(a, b, c):
    d = b * b - a * c
    if a <= 1e-15 or d < 0:
        return ()
    root = sqrt(d)
    return ((-b - root) / a, (-b + root) / a)


class Primitive:
    def __init__(self, desc, material):
        matrix = np.array(desc["transform"]).reshape(4, 3)
        self.inv = np.linalg.inv(matrix[:3])
        self.translation = matrix[3]
        self.centers = np.array(desc["centers"])
        delta = self.centers[-1] - self.centers[0]
        self.length = np.linalg.norm(delta)
        self.axis = delta / self.length if self.length else delta
        self.radius = desc["radius"]
        centers = self.centers @ matrix[:3] + matrix[3]
        pad = self.radius * np.linalg.norm(matrix[:3], axis=0)
        self.lo, self.hi = centers.min(axis=0) - pad, centers.max(axis=0) + pad
        self.mask = channels(desc["tags"], desc.get("group"), material)
        self.material = material

    def hit(self, start, delta):
        origin = (start - self.translation) @ self.inv
        ray = delta @ self.inv
        axis, length = self.axis, self.length
        hits = []
        if length > 0:
            offset = origin - self.centers[0]
            along, speed = offset @ axis, ray @ axis
            radial, velo = offset - along * axis, ray - speed * axis
            hits.extend(
                t
                for t in _roots(
                    velo @ velo, radial @ velo, radial @ radial - self.radius**2
                )
                if 0 <= along + t * speed <= length
            )
        for index, center in enumerate(self.centers):
            offset = origin - center
            for t in _roots(ray @ ray, offset @ ray, offset @ offset - self.radius**2):
                projection = (
                    ((origin + t * ray - self.centers[0]) @ axis) if length else 0
                )
                if not length or (
                    projection <= 0 if index == 0 else projection >= length
                ):
                    hits.append(t)
        inside = [t for t in hits if 0 <= t <= 1]
        if not inside:
            return None
        t = min(inside)
        position = origin + t * ray
        center = self.centers[0]
        if length:
            center = center + axis * np.clip((position - center) @ axis, 0, length)
        normal = (position - center) @ self.inv.T
        return t, normal


class Bounds:
    """AABB hierarchy for transformed sphere and capsule instances."""

    def __init__(self, shapes):
        self.lo = np.min([p.lo for p in shapes], axis=0).tolist()
        self.hi = np.max([p.hi for p in shapes], axis=0).tolist()
        self.mask = 0
        for shape in shapes:
            self.mask |= shape.mask
        self.children = []
        self.shapes = shapes
        if len(shapes) > 6:
            axis = max(range(3), key=lambda i: self.hi[i] - self.lo[i])
            ordered = sorted(shapes, key=lambda p: p.lo[axis] + p.hi[axis])
            m = len(ordered) // 2
            self.children = [Bounds(ordered[:m]), Bounds(ordered[m:])]
            self.shapes = []

    def candidates(self, origin, inverse, channel, limit=1.0):
        if not self.mask & channel:
            return
        near, far = 0.0, limit
        for x, inv, low, high in zip(origin, inverse, self.lo, self.hi):
            if inv is None:
                if not low <= x <= high:
                    return
            else:
                a, b = (low - x) * inv, (high - x) * inv
                if a > b:
                    a, b = b, a
                near, far = max(near, a), min(far, b)
                if near > far:
                    return
        if self.shapes:
            yield from (p for p in self.shapes if p.mask & channel)
        for child in self.children:
            yield from child.candidates(origin, inverse, channel, far)


def inverse_direction(a, b):
    return tuple(1.0 / (y - x) if x != y else None for x, y in zip(a, b))


class Collision:
    def __init__(self, folder):
        data = json.loads((folder / "collision.json").read_bytes())
        if data["format"] != 1 or data["missingModels"]:
            raise ValueError(f"{folder.name}: неполная физика карты")
        raw = np.memmap(folder / "collision.bin", mode="r", dtype="u1")
        enabled = {i["id"] for i in data.get("instances", []) if i["active"]}

        def active(record):
            instance = record.get("instance", -1)
            return instance < 0 or instance in enabled

        blocks = [b for b in data["blocks"] if active(b)]
        self.blocks = blocks
        self.materials = list(data["surfaces"].values())
        materials = {int(k): i for i, k in enumerate(data["surfaces"])}
        ordered = np.array(sorted(materials), dtype=np.uint32)
        indices = np.array([materials[h] for h in ordered], dtype=np.uint16)
        vertices = np.empty((sum(b["vertices"] for b in blocks), 3), np.float32)
        faces = np.empty((sum(b["triangles"] for b in blocks), 3), np.int32)
        self.material = np.empty(len(faces), np.uint16)
        self.mask = np.empty(len(faces), np.uint8)
        v = f = 0
        masks = {}
        for b in blocks:
            nv, nf, offset = b["vertices"], b["triangles"], b["offset"]
            vertices[v : v + nv] = np.frombuffer(raw, "<f4", nv * 3, offset).reshape(
                -1, 3
            )
            faces[f : f + nf] = (
                np.frombuffer(raw, "<i4", nf * 3, offset + 12 * nv).reshape(-1, 3) + v
            )
            material = self.material[f : f + nf]
            if b["perFace"]:
                hashes = np.frombuffer(raw, "<u4", nf, offset + 12 * (nv + nf))
                material[:] = indices[np.searchsorted(ordered, hashes)]
            else:
                material[:] = materials[b["material"]]
            key = tuple(b["tags"]), b["group"]
            if key not in masks:
                masks[key] = np.array(
                    [channels(*key, m) for m in self.materials], dtype=np.uint8
                )
            self.mask[f : f + nf] = masks[key][material]
            v += nv
            f += nf
        self.scene = TriangleScene(vertices, faces)
        self.shapes = [
            Primitive(p, self.materials[materials[p["material"]]])
            for p in data["primitives"]
            if active(p)
        ]
        self.bounds = Bounds(self.shapes) if self.shapes else None
        # Cache only exact segments and bound retention to this map.
        self.sight_cache = OrderedDict()
        self.trace = lru_cache(maxsize=32768)(partial(Collision._trace, proxy(self)))

    def sight_many(self, segments):
        # Trace the same directed segment even when the other observer asks first.
        # On an edge, reversing a float ray can select a different coplanar face.
        result = {}
        missing = {}
        for a, b in segments:
            key = (a, b) if a <= b else (b, a)
            if key in self.sight_cache:
                result[(a, b)] = self.sight_cache[key]
            elif a == b:
                result[(a, b)] = True
            else:
                missing.setdefault(key, []).append((a, b))
        if not missing:
            return result
        starts = np.asarray([a for a, _ in missing], dtype=np.float32)
        delta = np.asarray([b for _, b in missing], dtype=np.float32) - starts
        rays, _, _ = self.scene.first_many(starts, delta, 1.0)
        for idx, ((a, b), face) in enumerate(zip(missing, rays)):
            if face >= 0:
                visible = (
                    False
                    if self.mask[face] & SIGHT
                    else self.trace(a, b, SIGHT) is None
                )
            else:
                visible = True
            if visible and self.bounds and face < 0:
                inverse = inverse_direction(a, b)
                visible = not any(
                    p.hit(starts[idx], delta[idx]) is not None
                    for p in self.bounds.candidates(a, inverse, SIGHT)
                )
            self.sight_cache[(a, b)] = visible
            for pair in missing[(a, b)]:
                result[pair] = visible
        while len(self.sight_cache) > 32768:
            self.sight_cache.popitem(last=False)
        return result

    def _trace(self, source, target, channel):
        if source == target:
            return None
        start = np.array([source], dtype=np.float32)
        delta = np.array([target], dtype=np.float32) - start
        current = start
        offset = 0.0
        best = None
        while offset < 1:
            faces, distances, normals = self.scene.first_many(current, delta, 1 - offset)
            face = int(faces[0])
            if face < 0:
                break
            t = offset + float(distances[0])
            if self.mask[face] & channel:
                best = (t, self.materials[self.material[face]], normals[0])
                break
            offset = t + max(1e-6, 0.01 / max(0.01, float(abs(delta).max())))
            current = start + offset * delta
        if self.bounds:
            inverse = inverse_direction(source, target)
            for p in self.bounds.candidates(
                source, inverse, channel, best[0] if best else 1
            ):
                hit = p.hit(start[0], delta[0])
                if hit is not None and (best is None or hit[0] < best[0]):
                    best = (hit[0], p.material, hit[1])
        if best is None:
            return None
        if channel != THROW:
            return best[0], best[1], None
        normal = best[2]
        size = float(np.linalg.norm(normal))
        # The map adapter flips Hammer Y when converting to simulation axes.
        n = tuple(float(x) / size for x in normal) if size else (0.0, 0.0, 1.0)
        return best[0], best[1], (n[0], -n[1], n[2])
