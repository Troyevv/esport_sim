"""Register studio anatomy and kit necklines in the original photograph's plane."""

import argparse
import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit
from zipfile import ZipFile, ZipInfo

import cv2
import numpy as np
from PIL import Image

from backend.personal_portraits import catalog, kits
from backend.portrait_processing import PortraitProcessor

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend/src"
PUBLIC = ROOT / "frontend/public/portraits"
# The measurement canvas includes shoulders beyond the edges of the 240-unit head layer.
OFFSET = 120
W, H = 480, 300


def component(mask):
    count, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(mask > 0.48))
    if count < 2:
        raise ValueError("Не виден контур ткани")
    label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    return labels == label


def top_line(mask, default):
    present = np.flatnonzero(mask.any(axis=0))
    if len(present) < 8:
        raise ValueError("Недостаточно ткани для измерения воротника")
    values = np.argmax(mask[:, present], axis=0)
    result = np.interp(np.arange(W), present, values, left=default, right=default)
    return cv2.medianBlur(result.astype("float32")[None], 5)[0]


def rounded(values):
    return [round(float(v), 2) for v in values]


def anchors(line, center, left, right, neck, skin=None):
    def ridge(sign):
        offsets = np.arange(max(4, round(neck * 0.62)), max(7, round(neck * 1.48)))
        samples = np.clip(np.rint(center + offsets * sign).astype(int), 0, W - 1)
        # Prefer the shoulder-side end of a rounded collar lip.
        score = line[samples] + 0.13 * np.abs(offsets - neck)
        return float(samples[np.argmin(score)])

    nl, nr = ridge(-1), ridge(1)
    left = min(left, nl - 10)
    right = max(right, nr + 10)
    xs = np.concatenate(
        [
            np.linspace(left, nl, 7)[:-1],
            np.linspace(nl, center, 8)[:-1],
            np.linspace(center, nr, 8)[:-1],
            np.linspace(nr, right, 7),
        ]
    )
    ys = np.interp(xs, np.arange(W), line)
    if skin is not None:
        bottom, chin, eye_span = skin
        # Seat the front band just inside the original visible neck. Sample the
        # alpha contour along the entire throat, including either side of a V.
        for i, x in enumerate(xs):
            distal = abs(x - center) / eye_span
            if distal <= 0.92:
                y = bottom[int(np.clip(round(x), 0, W - 1))]
                if y > chin - 1:
                    ys[i] = min(ys[i], y - 2)
        # Hair can hide the collar in the source photo. Under it the cloth
        # continues to the shoulder instead of tracing the tips of long hair.
        ys = np.minimum(
            ys,
            np.interp(
                xs,
                [left, nl, center, nr, right],
                [ys[0], chin + eye_span * 0.56, ys[13], chin + eye_span * 0.56, ys[-1]],
            )
            + eye_span * 0.27,
        )
    return [rounded(xs - OFFSET), rounded(ys)]


def neckline(outline, full_depth):
    xs, measured = (np.array(row) for row in outline)
    middle = len(xs) // 2
    # The original neckline supplies tilt and depth. Smooth the front band
    # between its two endpoints without following individual segmentation pixels.
    # Old cutouts may end on a horizontal crop; give them a continuous neckline
    # inside that shorter skin contour.
    fitted = measured.copy()
    for ridge in (6, 20):
        side = np.arange(min(middle, ridge), max(middle, ridge) + 1)
        t = abs((xs[side] - xs[middle]) / (xs[ridge] - xs[middle]))
        arc = measured[ridge] + (measured[middle] - measured[ridge]) * (1 - t**1.45)
        original = np.array(full_depth)[side]
        loss = max(0, full_depth[middle] - measured[middle])
        fitted[side] = np.minimum(
            measured[side], 0.50 * arc + 0.50 * (original - loss * (1 - t**2))
        )
    return [rounded(xs), rounded(fitted)]


def body(original, rgb, lm, matrix, old, processor):
    masks = processor.skin.segment(processor.image(rgb)).confidence_masks
    masks = [m.numpy_view().squeeze().copy() for m in masks]
    face = lm @ matrix[:, :2].T + matrix[:, 2]
    eyes = (face[[33, 133]].mean(0) + face[[362, 263]].mean(0)) / 4
    chin = face[152] / 2
    span = np.linalg.norm(face[[33, 133]].mean(0) - face[[362, 263]].mean(0)) / 2
    cx = chin[0] + OFFSET
    rgba = np.asarray(Image.open(BytesIO(old)).convert("RGBA")).copy()
    # Recover only lower-neck skin from the original pixels. Keep existing
    # hair, ears and all face pixels byte-identical, including their matte.
    # Segment around the jaw at portrait resolution. The full body model can
    # assign adjoining rows of the same neck to its face-skin and body-skin
    # classes. Both are real skin. Restrict additions to the neck outside the
    # protected facial hull.
    native_span = np.linalg.norm(lm[[33, 133]].mean(0) - lm[[362, 263]].mean(0))
    px, py = lm[152]
    x0, x1 = (
        max(0, int(px - 2.25 * native_span)),
        min(rgb.shape[1], int(px + 2.25 * native_span) + 1),
    )
    y0, y1 = (
        max(0, int(py - 2.1 * native_span)),
        min(rgb.shape[0], int(py + 3 * native_span) + 1),
    )
    local = processor.skin.segment(processor.image(rgb[y0:y1, x0:x1])).confidence_masks
    score = local[2].numpy_view().squeeze() + local[3].numpy_view().squeeze()
    if original[:, :, 3].min() == 0:
        # On transparent studio originals the photographed outside edge is
        # stronger evidence than the segmenter's low-resolution background
        # label. Keep that edge where neither clothing nor accessories occur.
        clothing = local[4].numpy_view().squeeze()
        accessory = local[5].numpy_view().squeeze()
        bare = np.clip((0.23 - clothing) / 0.20, 0, 1) * np.clip(
            (0.25 - accessory) / 0.2, 0, 1
        )
        score = np.maximum(score, bare)
    skin = np.zeros(rgb.shape[:2], dtype=np.float32)
    skin[y0:y1, x0:x1] = np.clip((score - 0.12) / 0.73, 0, 1)
    skin *= original[:, :, 3] / 255
    neck = cv2.warpAffine(np.dstack((rgb * skin[:, :, None], skin)), matrix, (480, 560))
    alpha = neck[:, :, 3]
    yy, xx = np.ogrid[:560, :480]
    dist = (xx - 2 * chin[0]) / (2 * span)
    gate = np.clip((yy - 2 * chin[1] + span * 2.0) / (span * 0.30), 0, 1) * np.clip(
        (1.38 - np.abs(dist)) / 0.18, 0, 1
    )
    gate *= np.clip((2 * chin[1] + span * 4.3 - yy) / (span * 0.5), 0, 1)
    protected = np.zeros((560, 480), np.uint8)
    cv2.fillConvexPoly(protected, cv2.convexHull(np.int32(np.rint(face))), 1)
    gate *= 1 - cv2.erode(
        protected, np.ones((max(3, round(span * 0.60)),) * 2, np.uint8)
    )
    a = alpha * gate
    oa = rgba[:, :, 3] / 255
    add = np.maximum(0, a - oa)
    final = oa + add
    color = np.divide(neck[:, :, :3], np.maximum(alpha[:, :, None], 0.00001))
    change = add > 1 / 255
    out = (rgba[:, :, :3] * oa[:, :, None] + color * add[:, :, None]) / np.maximum(
        final[:, :, None], 0.00001
    )
    rgba[:, :, :3][change] = np.uint8(np.clip(out[change], 0, 255))
    rgba[:, :, 3][change] = np.uint8(255 * final[change])
    result = BytesIO()
    Image.fromarray(rgba).save(result, "PNG", optimize=True)
    transform = matrix / 2
    transform[:, 2] += [OFFSET, 0]
    cloth = cv2.warpAffine(masks[4] * original[:, :, 3] / 255, transform, (W, H))
    keep = component(cloth)
    line = top_line(keep, chin[1] + 2 * span)
    row = int(np.clip(chin[1] + span * 2, 0, H - 1))
    # Two clavicles and the observed outline in the upper chest retain
    # asymmetry, body build and studio pose even when sleeves are cropped.
    band = keep[max(0, row - 5) : row + 6].sum(axis=0) > 3
    visible = np.flatnonzero(band)
    if not len(visible):
        visible = np.flatnonzero(keep.any(axis=0))
    left = max(visible[0] + 3, cx - 4.3 * span)
    right = min(visible[-1] - 3, cx + 4.3 * span)
    opacity = cv2.resize(rgba[:, :, 3], (240, 280))
    scalp = np.flatnonzero((opacity > 96).sum(axis=1) > 3)[0]
    eye_chin = chin[1] - eyes[1]

    foreground = original[:, :, 3] / 255
    if foreground.min() > 0.99:
        foreground = 1 - masks[0]
    subject = cv2.warpAffine(foreground, transform, (W, H))

    def guide(a):
        visible = np.pad(a > 100, ((0, H - 280), (OFFSET, W - 240 - OFFSET)))
        bottom = np.where(
            visible.any(axis=0), H - 1 - np.argmax(visible[::-1], axis=0), 0
        )
        # Within the actual subject, the jersey begins where exposed skin ends.
        # Read several consecutive pixels so a soft beard or a stray hair does
        # not introduce a collar spur.
        rows = np.arange(H)[:, None]
        start = np.maximum(chin[1] - 0.22 * span, line - 0.85 * span)
        interior = (subject > 0.78) & ~visible & (rows >= start)
        solid = interior[:-2] & interior[1:-1] & interior[2:]
        edge = np.where(solid.any(axis=0), np.argmax(solid, axis=0), line)
        seam = np.minimum(line, cv2.medianBlur(edge.astype("float32")[None], 5)[0])
        return anchors(seam, cx, left, right, span * 0.89, (bottom, chin[1], span))

    registered = guide(opacity)
    legacy = guide(
        cv2.resize(np.asarray(Image.open(BytesIO(old)))[:, :, 3], (240, 280))
    )
    # Frame from hair to clavicles. Keep the full crown and temples for broad
    # hairstyles without zooming back out to show the sponsor panel.
    top = scalp - max(3, (chin[1] - scalp) * 0.048)
    bottom = max(chin[1] + 0.69 * eye_chin, registered[1][13] + 0.24 * eye_chin)
    hair = np.flatnonzero((opacity[: int(chin[1])] > 96).sum(axis=0) > 2)
    height = max(bottom - top, (hair[-1] - hair[0] + 9) * 280 / 240)
    width = height * 240 / 280
    mid = np.clip(eyes[0], hair[-1] + 4 - width / 2, hair[0] - 4 + width / 2)
    camera = rounded([mid - width / 2, top, width, height])
    return result.getvalue(), dict(
        camera=camera,
        body=neckline(registered, registered[1]),
        legacy=neckline(legacy, registered[1]),
    )


def read_source(roots, e):
    _, owner, repo, _, _, rel = urlsplit(e["source"]).path.split("/", 5)
    raw = (roots / owner / repo / unquote(rel)).read_bytes()
    if sha256(raw).hexdigest() != e["originalSha256"]:
        raise ValueError("Изменился исходник " + e["name"])
    if e.get("frame"):
        stream = BytesIO()
        Image.open(BytesIO(raw)).convert("RGBA").crop(e["frame"]).save(stream, "PNG")
        raw = stream.getvalue()
    return raw


def kit_guide(image, rig):
    alpha = np.asarray(image.convert("RGBA"))[:, :, 3] / 255
    scale = 246 / rig["span"]
    x, y = np.array(rig["seat"]) - scale * np.array(rig["collar"])
    placed = cv2.warpAffine(
        alpha, np.float32([[scale, 0, OFFSET + x], [0, scale, y]]), (W, H)
    )
    line = top_line(component(placed), rig["seat"][1] + 80)
    # Use the same chest cross-section as the portrait; do not treat the
    # farthest sleeve pixel as an anatomical shoulder joint.
    row = round(rig["seat"][1] + 45)
    cols = np.flatnonzero(placed[row] > 0.52)
    return anchors(line, OFFSET + rig["seat"][0], cols[0] + 2, cols[-1] - 2, 26)


def build(roots, pack, output):
    from tempfile import NamedTemporaryFile

    players = {}
    garments = {}
    processor = PortraitProcessor()
    temp = NamedTemporaryFile(dir=output.parent, delete=False)
    temp.close()
    try:
        with ZipFile(pack) as src, ZipFile(temp.name, "w") as dst:
            for pid, e in catalog().items():
                old = src.read(e["sha256"] + ".png")

                def register(original, rgb, lm, matrix):
                    nonlocal fit, pixels
                    pixels, fit = body(original, rgb, lm, matrix, old, processor)

                fit = pixels = None
                regenerated, _ = processor._render(
                    read_source(roots, e), studio=not e.get("frame"), register=register
                )
                if regenerated != old:
                    raise ValueError(e["name"] + " · слой не совпал с исходником")
                digest = sha256(pixels).hexdigest()
                dst.writestr(ZipInfo(digest + ".png", (2026, 11, 25, 0, 0, 0)), pixels)
                players[e["sha256"]] = {**fit, "image": digest}
            drawings = json.loads((SRC / "kitArt.json").read_text(encoding="utf-8"))
            for tid, entry in drawings.items():
                with Image.open(PUBLIC / "kits" / (tid + ".webp")) as im:
                    garments[tid] = kit_guide(im, entry["rig"])
            for tid, k in sorted(kits().items()):
                filename = "kits/" + k["sha256"] + ".png"
                raw = src.read(filename)
                garments[k["sha256"]] = kit_guide(Image.open(BytesIO(raw)), k["rig"])
                dst.writestr(src.getinfo(filename), raw)
            garments["neutral"] = kit_guide(
                Image.open(PUBLIC / "jersey.webp"),
                dict(span=615.4, collar=[330, 103], seat=[120, 157]),
            )
        for path, data in [
            (SRC / "portraitAnatomy.json", players),
            (SRC / "garmentContours.json", garments),
            (
                ROOT / "backend/data/portrait-anatomy.json",
                {k: v["image"] for k, v in players.items()},
            ),
        ]:
            path.write_text(
                json.dumps(data, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        Path(temp.name).replace(output)
    finally:
        processor.close()
        Path(temp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("roots", "pack", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    build(args.roots, args.pack, args.output)
