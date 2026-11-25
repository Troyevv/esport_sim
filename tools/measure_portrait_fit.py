"""Measure placement and incident light for existing head layers without changing faces."""

import argparse
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import numpy as np
from PIL import Image

from backend.portrait_processing import PortraitProcessor


def measure(raw, processor):
    image = np.asarray(Image.open(BytesIO(raw)).convert("RGBA"))
    alpha = image[:, :, 3:4] / 255
    gray = np.uint8(image[:, :, :3] * alpha + 145 * (1 - alpha))
    faces = processor.faces.detect(processor.image(gray)).face_landmarks
    if len(faces) != 1:
        raise ValueError("Ожидалось одно лицо")
    xy = np.array([(p.x * 480, p.y * 560) for p in faces[0]])
    chin_x, chin_y = xy[152] / 2
    jaw = np.linalg.norm(xy[234] - xy[454]) / 2
    scale = float(np.clip(77 / jaw, 0.72, 0.94))
    # Seat the original lower neck behind the front band, allowing for short necks.
    columns = range(round(2 * chin_x - 24 / scale), round(2 * chin_x + 24 / scale) + 1)
    extent = [np.flatnonzero(alpha[:, x, 0] > 0.72)[-1] / 2 for x in columns]
    bottom = min(extent)
    target_chin = max(136, 162 - (bottom - chin_y) * scale)
    tx, ty = 120 - chin_x * scale, target_chin - chin_y * scale

    def cheek(index):
        x, y = xy[index].astype(int)
        return gray[y - 3 : y + 4, x - 3 : x + 4].mean()

    light = float(np.clip((cheek(50) - cheek(280)) / 100, -0.55, 0.55))
    return [round(v, 3) for v in (scale, tx, ty, light)]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    processor = PortraitProcessor()
    try:
        with ZipFile(args.archive) as z:
            result = {
                name[:-4]: measure(z.read(name), processor)
                for name in z.namelist()
                if "/" not in name and name.endswith(".png")
            }
        args.output.write_text(
            json.dumps(result, sort_keys=True, indent=1) + "\n", encoding="utf-8"
        )
    finally:
        processor.close()
