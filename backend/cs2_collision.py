"""Read mesh blocks and transform primitive geometry from the Source 2 export."""
import json
import numpy as np


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

class CollisionData:
    def __init__(self, folder, make_scene):
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
        self.scene = make_scene(vertices, faces, self.mask)
        self.shapes = [
            Primitive(p, self.materials[materials[p["material"]]])
            for p in data["primitives"]
            if active(p)
        ]
