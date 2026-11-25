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


@lru_cache(maxsize=1)
def _library():
    package = Path(rtcore.__file__).resolve().parent
    folders = (package.parent / "embreex.libs", package / ".dylibs", package)
    for folder in folders:
        for path in sorted(folder.glob("*embree4*")):
            if path.name.endswith((".dll", ".dylib")) or ".so" in path.name:
                lib = ct.CDLL(str(path))
                break
        else:
            continue
        break
    else:
        raise RuntimeError("Не найдена библиотека Embree 4 из пакета embreex")

    ptr, uint, size = ct.c_void_p, ct.c_uint, ct.c_size_t
    signatures = {
        "rtcNewDevice": (ptr, [ct.c_char_p]),
        "rtcGetDeviceError": (uint, [ptr]),
        "rtcNewScene": (ptr, [ptr]),
        "rtcSetSceneFlags": (None, [ptr, uint]),
        "rtcNewGeometry": (ptr, [ptr, uint]),
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
    def __init__(self, vertices, faces):
        lib = _library()
        # Different CPU kernels resolve rays exactly on a portal edge differently.
        # SSE2 is the x64 baseline. A single builder fixes the order of coplanar faces.
        device = lib.rtcNewDevice(b"isa=sse2,threads=1")
        if not device:
            raise RuntimeError("Embree не удалось создать воспроизводимое устройство SSE2")
        scene = None
        geometry = None
        try:
            scene = lib.rtcNewScene(device)
            geometry = lib.rtcNewGeometry(device, 0)  # RTC_GEOMETRY_TYPE_TRIANGLE
            if not scene or not geometry:
                raise RuntimeError("Embree не удалось выделить память для геометрии карты")
            lib.rtcSetSceneFlags(scene, 4)  # RTC_SCENE_FLAG_ROBUST at shared NAV edges.
            for kind, fmt, array in ((1, 0x9003, vertices), (0, 0x5003, faces)):
                # RTC_FORMAT_FLOAT3 vertices / RTC_FORMAT_UINT3 triangle indices.
                buffer = lib.rtcSetNewGeometryBuffer(geometry, kind, 0, fmt, 12, len(array))
                if len(array):
                    if not buffer:
                        raise MemoryError("Embree не удалось разместить треугольники карты")
                    ct.memmove(buffer, array.ctypes.data, array.nbytes)
            lib.rtcCommitGeometry(geometry)
            lib.rtcAttachGeometry(scene, geometry)
            lib.rtcCommitScene(scene)
            error = lib.rtcGetDeviceError(device)
            if error:
                raise RuntimeError(f"Не удалось построить BVH карты, ошибка Embree {error}")
            self.handle = scene
            self.intersect = lib.rtcIntersect1
            finalize(self, lib.rtcReleaseScene, scene)
            scene = None
        finally:
            if geometry:
                lib.rtcReleaseGeometry(geometry)
            if scene:
                lib.rtcReleaseScene(scene)
            lib.rtcReleaseDevice(device)

    def first_many(self, starts, directions, limits):
        rays = np.zeros(len(starts), dtype=RAY_HIT)
        rays["origin"] = starts
        rays["direction"] = directions
        rays["far"] = limits
        rays["mask"] = 0xffffffff
        for field in ("face", "geometry", "instance"):
            rays[field] = -1
        address = rays.ctypes.data
        for _ in range(len(rays)):
            self.intersect(self.handle, address, None)
            address += rays.strides[0]
        return rays["face"], rays["far"], rays["normal"]
