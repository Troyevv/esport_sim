from concurrent.futures import ThreadPoolExecutor
import gc

import pytest

native = pytest.importorskip("backend._match_native")
import numpy as np

from tests.reference_kernel.cs2_rays import TriangleScene


def geometry():
    vertices = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0],
                         [0, 0, 10], [10, 0, 10], [0, 10, 10]], dtype=np.float32)
    faces = np.array([[0, 1, 2], [3, 4, 5], [0, 1, 2]], dtype=np.int32)
    return vertices, faces, np.array([1, 2, 3], dtype=np.uint8)


def test_masks_original_face_ids_limits_and_shared_scene():
    vertices, faces, masks = geometry()
    ref = TriangleScene(vertices, faces, masks)
    scene = native.TriangleScene(vertices, faces, masks)
    vertices.fill(0)
    faces.fill(0)
    masks.fill(0)
    del vertices, faces, masks
    gc.collect()
    starts = np.array([[2, 2, -3], [0, 0, -1], [20, 20, -3]], dtype=np.float32)
    unaligned = np.ndarray(starts.shape, dtype="f4", buffer=bytearray(starts.nbytes + 1), offset=1)
    unaligned[:] = starts
    starts = unaligned
    directions = np.array([0, 0, 1], dtype=np.float32)
    limits = np.array([20, 10, 20], dtype=np.float32)

    def check(channel):
        for dirs, distances in ((directions, limits), (np.tile(directions, (3, 1)), 1.0)):
            expected = ref.first_many(starts, dirs, distances, channel)
            actual = scene.first_many(starts, dirs, distances, channel)
            for old, new in zip(expected, actual, strict=True):
                np.testing.assert_array_equal(old, new)
                assert old.dtype == new.dtype

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(check, [0, 1, 2, 3] * 8))
    for output in scene.first_many(np.empty((0, 3)), directions, 1, 1):
        assert len(output) == 0


def test_invalid_indices_and_batch_shapes():
    vertices, faces, masks = geometry()
    with pytest.raises(ValueError):
        native.TriangleScene(vertices, faces, masks[:-1])
    with pytest.raises(ValueError):
        native.TriangleScene(vertices[:-1], faces, masks)
    with pytest.raises(ValueError):
        native.TriangleScene(vertices, -faces - 1, masks)
    scene = native.TriangleScene(vertices, faces, masks)
    for directions, limits in (([1, 2], 1), (np.zeros((4, 3)), 1), ([0, 0, 1], [1, 2]),
                               ([0, np.nan, 1], 1), ([0, 0, 1], -1)):
        with pytest.raises(ValueError):
            scene.first_many([[1, 2, 3]], directions, limits, 1)
