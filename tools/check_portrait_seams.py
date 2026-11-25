"""Measure the neck seam of every private head against every local uniform."""

import argparse
import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def alpha_at_joint(image, scale, dx, dy):
    # Both transforms in GamePortrait use the same 240 by 280 display coordinate system.
    # Inspect the central 24 px of the neck, from just below the jaw to inside the collar.
    a = np.asarray(image.convert("RGBA"))[:, :, 3]
    return (
        cv2.warpAffine(
            a, np.float32([[scale, 0, dx - 108], [0, scale, dy - 149]]), (24, 17)
        )
        / 255
    )


def check(archive):
    fits = json.loads((ROOT / "frontend/src/portraitFit.json").read_text())
    public = json.loads((ROOT / "frontend/src/kitArt.json").read_text())
    private = json.loads((ROOT / "backend/data/team-kits.json").read_text())
    heads = []
    outfits = []
    with ZipFile(archive) as files:
        for digest, (s, x, y, light) in fits.items():
            with Image.open(BytesIO(files.read(digest + ".png"))) as image:
                heads.append(alpha_at_joint(image, s / 2, x, y))
        for tid, entry in public.items():
            layers = [
                (
                    entry["rig"],
                    (
                        ROOT / "frontend/public/portraits/kits" / (tid + ".webp")
                    ).read_bytes(),
                )
            ]
            if tid in private:
                kit = private[tid]
                layers.append(
                    (kit["rig"], files.read("kits/" + kit["sha256"] + ".png"))
                )
            for rig, raw in layers:
                scale = 246 / rig["span"]
                x, y = [a - scale * b for a, b in zip(rig["seat"], rig["collar"])]
                with Image.open(BytesIO(raw)) as image:
                    outfits.append(alpha_at_joint(image, scale, x, y))
    worst = 0
    count = 0
    low = []
    for i, g in enumerate(outfits):
        alpha = 1 - (1 - np.stack(heads)) * (1 - g)
        holes = (alpha < 0.5).sum(axis=(1, 2))
        count += int(np.count_nonzero(holes))
        worst = max(worst, int(holes.max()))
        if holes.max():
            low.append((i, int(holes.max()), int(np.argmax(holes))))
    return {
        "players": len(heads),
        "garments": len(outfits),
        "pairs": len(heads) * len(outfits),
        "seamsWithGap": count,
        "maxUncoveredPixels": worst,
        "examples": low[:6],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    result = check(parser.parse_args().archive)
    print(json.dumps(result))
    raise SystemExit(bool(result["seamsWithGap"]))
