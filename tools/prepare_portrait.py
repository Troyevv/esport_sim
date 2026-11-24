"""Cut a reviewed head contour from one authorized source and normalize it for a kit.

Contributor tool, Pillow==13.0.0. Coordinates are measured on a preview of
referenceWidth pixels. The two eye centres set scale and roll. The traced outline
includes ears, hair and exposed neck, stopping inside the source collar.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps


def prepare(source, recipe, output):
    if hashlib.sha256(source.read_bytes()).hexdigest() != recipe["sha256"]:
        raise ValueError("Изображение отличается от размеченного оригинала")
    original = ImageOps.exif_transpose(Image.open(source)).convert("RGBA")
    scale = original.width / recipe["referenceWidth"]

    def points(items):
        return [(x * scale, y * scale) for x, y in items]

    contour = points(recipe["contour"])
    mask = Image.new("L", original.size)
    ImageDraw.Draw(mask).polygon(contour, fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.22 * scale))
    original.putalpha(ImageChops.multiply(original.getchannel("A"), mask))
    (lx, ly), (rx, ry) = points(recipe["eyes"])
    span = recipe.get("eyeSpan", 36)
    if rx <= lx or not 25 <= span <= 44:
        raise ValueError("Проверьте метки глаз")
    # Inverse similarity transform from a double-size canonical frame to source.
    a, b = (rx - lx) / (2 * span), (ry - ly) / (2 * span)
    if not math.isfinite(a + b):
        raise ValueError("Неизвестный масштаб")
    cx, cy = (lx + rx) / 2, (ly + ry) / 2
    ey = recipe.get("eyeY", 78) * 2
    affine = (a, -b, cx - a * 240 + b * ey, b, a, cy - b * 240 - a * ey)
    result = original.transform(
        (480, 560), Image.Transform.AFFINE, affine, Image.Resampling.BICUBIC
    )
    result.save(output, optimize=True)


if __name__ == "__main__":
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ("source", "recipe", "output"):
        cli.add_argument(name, type=Path)
    args = cli.parse_args()
    prepare(
        args.source, json.loads(args.recipe.read_text(encoding="utf-8")), args.output
    )
