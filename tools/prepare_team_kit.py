"""Register a photographed jersey to the portrait collar, preserving its printed fabric."""

from io import BytesIO

import cv2
import numpy as np
from PIL import Image


def garment(raw, processor):
    img = np.asarray(Image.open(BytesIO(raw)).convert("RGBA"))
    h, w = img.shape[:2]
    alpha = img[:, :, 3].astype(np.float32) / 255
    rgb = img[:, :, :3]
    flat = np.uint8(rgb * alpha[:, :, None] + 153 * (1 - alpha[:, :, None]))
    face = processor.faces.detect(processor.image(flat))
    if len(face.face_landmarks) != 1:
        raise ValueError("Не определены опорные точки")
    points = face.face_landmarks[0]
    cx, chin = int(points[152].x * w), int(points[152].y * h)
    masks = processor.skin.segment(processor.image(flat)).confidence_masks
    cloth = masks[4].numpy_view().squeeze().copy()
    y, x = np.ogrid[:h, :w]
    cloth *= (y > chin - 0.065 * w) | (abs(x - cx) > w * 0.19)
    mask = np.clip((cloth - 0.22) / 0.61, 0, 1) * alpha
    _, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0.12).astype(np.uint8)
    )
    if len(stats) < 2:
        raise ValueError("Одежда не выделена")
    component = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    mask *= cv2.dilate(
        (labels == component).astype(np.uint8), np.ones((3, 3), np.uint8)
    )
    center = mask[:, max(0, cx - 3) : min(w, cx + 4)].mean(axis=1)
    valid = np.flatnonzero((center > 0.76) & (np.arange(h) >= chin))
    if len(valid) == 0:
        raise ValueError("Не виден воротник")
    collar = int(valid[0])
    spans = []
    for i in range(collar + int(w * 0.09), min(h, collar + int(w * 0.29))):
        xs = np.flatnonzero(mask[i] > 0.65)
        if xs.size:
            spans.append(xs[-1] - xs[0])
    if not spans or max(spans) < w * 0.34:
        raise ValueError("Не видны плечи")
    shoulder_width = float(np.percentile(spans, 85))
    # Find the centre of the collar opening independently of a tilted face.
    centres = []
    for row in range(max(chin, collar - int(w * 0.06)), collar):
        left = np.flatnonzero(mask[row, max(0, cx - int(w * 0.19)) : cx] > 0.78)
        right = np.flatnonzero(mask[row, cx : cx + int(w * 0.19)] > 0.78)
        if left.size and right.size:
            lo = max(0, cx - int(w * 0.19)) + left[-1]
            hi = cx + right[0]
            if 0.045 * w < hi - lo < 0.32 * w:
                centres.append((lo + hi) / 2)
    anchor_x = float(np.median(centres)) if centres else cx
    # An asymmetric V or half-open placket may extend below the centre of the face.
    # Register the deepest front join across the width of the visible neck, excluding pendants.
    half_width = max(2, round(shoulder_width * 6 / 246))
    fronts = []
    for column in range(round(anchor_x) - half_width, round(anchor_x) + half_width + 1):
        line = mask[chin:, column] > 0.78
        solid = np.flatnonzero(
            np.convolve(line.astype(int), np.ones(5, dtype=int), "valid") == 5
        )
        if len(solid):
            fronts.append(chin + int(solid[0]))
    if len(fronts) < half_width:
        raise ValueError("Передний край воротника не определён")
    collar = int(np.ceil(np.percentile(fronts, 95)))
    rig = {
        "width": w,
        "height": h,
        "collar": [round(anchor_x, 2), collar],
        "span": round(shoulder_width, 2),
        "seat": [120, 158.5],
    }
    scale = 492 / shoulder_width
    transform = np.float32(
        [[scale, 0, 240 - cx * scale], [0, scale, 317 - collar * scale]]
    )
    rgba = np.dstack((rgb * mask[:, :, None], mask))
    dst = cv2.warpAffine(rgba, transform, (480, 560), flags=cv2.INTER_LINEAR)
    a = dst[:, :, 3]
    if np.mean(a[520:550, 120:360]) < 0.94:
        raise ValueError("Руки или граница снимка перекрывают ткань")
    # Store source-space clothing so every consumer uses the same neck joint.
    opacity = np.uint8(mask * 255)
    dst = np.dstack((np.where(opacity[:, :, None] > 0, rgb, 0), opacity))
    stream = BytesIO()
    Image.fromarray(np.uint8(np.clip(dst, 0, 255))).save(stream, "PNG", optimize=True)
    return stream.getvalue(), rig
