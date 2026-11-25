"""BVH segment queries on the pinned CS2 collision export, in Hammer XYZ."""

import json
from functools import lru_cache
from math import sqrt

import numpy as np
from embreex.mesh_construction import TriangleMesh
from embreex.rtcore_scene import EmbreeScene

SIGHT, MOVEMENT, PROJECTILE, THROW = 1, 2, 4, 8


def channels(tags, group, material):
    tags = set(tags)
    clip = tags & {"playerclip", "npcclip", "csgo_grenadeclip", "navclip"}
    if clip and not tags & {"solid", "window", "passbullets"}:
        return (MOVEMENT if "playerclip" in tags else 0) | (THROW if "csgo_grenadeclip" in tags else 0)
    if not (group in ("Default", "default", "", None) or tags & {"solid", "window", "passbullets", "sky", "blocklos"}):
        return 0
    mask = MOVEMENT | THROW
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
        self.radius = desc["radius"]
        centers = self.centers @ matrix[:3] + matrix[3]
        pad = self.radius * np.linalg.norm(matrix[:3], axis=0)
        self.lo, self.hi = centers.min(axis=0) - pad, centers.max(axis=0) + pad
        self.mask = channels(desc["tags"], desc.get("group"), material)
        self.material = material

    def hit(self, start, delta):
        origin = (start - self.translation) @ self.inv
        ray = delta @ self.inv
        axis = self.centers[-1] - self.centers[0]
        length = np.linalg.norm(axis)
        hits = []
        if length > 0:
            axis = axis / length
            offset = origin - self.centers[0]
            along, speed = offset @ axis, ray @ axis
            radial, velo = offset - along * axis, ray - speed * axis
            hits.extend(t for t in _roots(velo @ velo, radial @ velo, radial @ radial - self.radius**2)
                        if 0 <= along + t * speed <= length)
        for center in self.centers:
            offset = origin - center
            hits.extend(_roots(ray @ ray, offset @ ray, offset @ offset - self.radius**2))
        if not hits or max(hits) < 0 or min(hits) > 1:
            return None
        return max(0., min(hits))


class Collision:
    def __init__(self, folder):
        data = json.loads((folder / "collision.json").read_bytes())
        if data["format"] != 1 or data["missingModels"]:
            raise ValueError(f"{folder.name}: неполная физика карты")
        raw = np.memmap(folder / "collision.bin", mode="r", dtype="u1")
        blocks = data["blocks"]
        self.materials = list(data["surfaces"].values())
        materials = {int(k): i for i,k in enumerate(data["surfaces"])}
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
            vertices[v:v+nv] = np.frombuffer(raw, "<f4", nv*3, offset).reshape(-1, 3)
            faces[f:f+nf] = np.frombuffer(raw, "<i4", nf*3, offset+12*nv).reshape(-1, 3) + v
            material = self.material[f:f+nf]
            if b["perFace"]:
                hashes = np.frombuffer(raw, "<u4", nf, offset+12*(nv+nf))
                material[:] = indices[np.searchsorted(ordered, hashes)]
            else:
                material[:] = materials[b["material"]]
            key = tuple(b["tags"]), b["group"]
            if key not in masks:
                masks[key] = np.array([channels(*key, m) for m in self.materials], dtype=np.uint8)
            self.mask[f:f+nf] = masks[key][material]
            v += nv
            f += nf
        self.scene = EmbreeScene()
        self.mesh = TriangleMesh(self.scene, vertices, faces)
        self.shapes = [Primitive(p, self.materials[materials[p["material"]]]) for p in data["primitives"]]
        self.bounds = [(p.lo.tolist(), p.hi.tolist()) for p in self.shapes]
        # Cache only exact segments and bound retention to this map.
        self.trace = lru_cache(maxsize=32768)(self._trace)

    def _trace(self, source, target, channel):
        if source == target:
            return None
        start = np.array([source], dtype=np.float32)
        delta = np.array([target], dtype=np.float32) - start
        current = start
        offset = 0.
        best = None
        while offset < 1:
            hit = self.scene.run(current, delta, dists=np.array([1-offset], dtype=np.float32), output=True)
            face = int(hit["primID"][0])
            if face < 0:
                break
            t = offset + float(hit["tfar"][0])
            if self.mask[face] & channel:
                best = (t, self.materials[self.material[face]])
                break
            offset = t + max(1e-6, 0.01/max(0.01, float(abs(delta).max())))
            current = start + offset * delta
        for p, (lo, hi) in zip(self.shapes, self.bounds):
            if p.mask & channel and all(min(a,b) <= upper and max(a,b) >= lower
                                         for a,b,lower,upper in zip(source,target,lo,hi)):
                t = p.hit(start[0], delta[0])
                if t is not None and (best is None or t < best[0]):
                    best = (t, p.material)
        return best
