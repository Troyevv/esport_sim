"""Embree 4 triangle queries with the same traversal kernel on every x64 host."""

import ctypes as ct
from functools import lru_cache
from pathlib import Path
from weakref import finalize

import numpy as np
from embreex import rtcore  # Load the pinned wheel's native dependencies first.

# RTCRayHit from rtcore_ray.h in the pinned Embree 4 wheel. A row occupies a
# multiple of 16 bytes and includes room for instance and instance-primitive IDs.
RAY_HIT = np.dtype([
    ("origin", "f4", 3), ("near", "f4"), ("direction", "f4", 3), ("time", "f4"),
    ("far", "f4"), ("mask", "u4"), ("ray_id", "u4"), ("flags", "u4"),
    ("normal", "f4", 3), ("uv", "f4", 2), ("face", "i4"), ("geometry", "i4"),
    ("instance", "i4", 5),
])


from backend.cs2_rays import _library_path


@lru_cache(maxsize=1)
def _library():
    lib = ct.CDLL(str(_library_path()))
    ptr, uint, size = ct.c_void_p, ct.c_uint, ct.c_size_t
    signatures = {
        "rtcNewDevice": (ptr, [ct.c_char_p]),
        "rtcGetDeviceError": (uint, [ptr]),
        "rtcNewScene": (ptr, [ptr]),
        "rtcSetSceneFlags": (None, [ptr, uint]),
        "rtcNewGeometry": (ptr, [ptr, uint]),
        "rtcSetGeometryMask": (None, [ptr, uint]),
        "rtcSetSharedGeometryBuffer": (None, [ptr, uint, uint, uint, ptr, size, size, size]),
        "rtcSetNewGeometryBuffer": (ptr, [ptr, uint, uint, uint, size, size]),
        "rtcCommitGeometry": (None, [ptr]),
        "rtcAttachGeometry": (uint, [ptr, ptr]),
        "rtcCommitScene": (None, [ptr]),
        "rtcIntersect1": (None, [ptr, ptr, ptr]),
        "rtcReleaseGeometry": (None, [ptr]),
        "rtcReleaseScene": (None, [ptr]),
        "rtcReleaseDevice": (None, [ptr]),
    }
    for name, (result, args) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, args
    return lib


class TriangleScene:
    def __init__(self, vertices, faces, masks):
        lib = _library()
        # Different CPU kernels resolve rays exactly on a portal edge differently.
        # SSE2 is the x64 baseline. A single builder fixes the order of coplanar faces.
        device = lib.rtcNewDevice(b"isa=sse2,threads=1")
        if not device:
            raise RuntimeError("Embree не удалось создать воспроизводимое устройство SSE2")
        scene = None
        try:
            scene = lib.rtcNewScene(device)
            if not scene:
                raise RuntimeError("Embree не удалось выделить память для геометрии карты")
            lib.rtcSetSceneFlags(scene, 4)  # RTC_SCENE_FLAG_ROBUST
            # Native masks exclude playerclip or glass before the closest-hit
            # comparison, including where a solid triangle shares their plane.
            # Share a single vertex buffer with the 16-byte tail required by Embree.
            self.vertices = np.zeros((len(vertices) + 1, 3), dtype=np.float32)
            self.vertices[:-1] = vertices
            ordered = np.argsort(masks, kind="stable")
            self.face_ids = ordered.astype(np.int32)
            offsets = np.searchsorted(masks[ordered], np.arange(257))
            self.offsets = []
            for mask in np.unique(masks):
                if not mask:
                    continue
                lo, hi = offsets[int(mask):int(mask)+2]
                mesh = lib.rtcNewGeometry(device, 0)  # RTC_GEOMETRY_TYPE_TRIANGLE
                if not mesh:
                    raise MemoryError("Не удалось разместить группу поверхностей карты")
                try:
                    lib.rtcSetGeometryMask(mesh, int(mask))
                    lib.rtcSetSharedGeometryBuffer(mesh, 1, 0, 0x9003,
                                                   self.vertices.ctypes.data, 0, 12, len(vertices))
                    indices = faces[ordered[lo:hi]]
                    buffer = lib.rtcSetNewGeometryBuffer(mesh, 0, 0, 0x5003, 12, len(indices))
                    if not buffer:
                        raise MemoryError("Не удалось разместить грани карты")
                    ct.memmove(buffer, indices.ctypes.data, indices.nbytes)
                    lib.rtcCommitGeometry(mesh)
                    ident = lib.rtcAttachGeometry(scene, mesh)
                    if ident != len(self.offsets):
                        raise RuntimeError("Неверный индекс группы поверхностей Embree")
                    self.offsets.append(lo)
                finally:
                    lib.rtcReleaseGeometry(mesh)
            self.offsets = np.array(self.offsets, dtype=np.int32)
            lib.rtcCommitScene(scene)
            error = lib.rtcGetDeviceError(device)
            if error:
                raise RuntimeError(f"Не удалось построить BVH карты, ошибка Embree {error}")
            self.handle = scene
            self.intersect = lib.rtcIntersect1
            finalize(self, lib.rtcReleaseScene, scene)
            scene = None
        finally:
            if scene:
                lib.rtcReleaseScene(scene)
            lib.rtcReleaseDevice(device)

    def first_many(self, starts, directions, limits, channel):
        rays = np.zeros(len(starts), dtype=RAY_HIT)
        rays["origin"] = starts
        rays["direction"] = directions
        rays["far"] = limits
        rays["mask"] = channel
        for field in ("face", "geometry", "instance"):
            rays[field] = -1
        address = rays.ctypes.data
        for _ in range(len(rays)):
            self.intersect(self.handle, address, None)
            address += rays.strides[0]
        faces = rays["face"]
        hit = rays["geometry"] >= 0
        faces[hit] = self.face_ids[self.offsets[rays["geometry"][hit]] + faces[hit]]
        return faces, rays["far"], rays["normal"]
