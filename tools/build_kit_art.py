"""Bake editable garment specifications onto the project's licensed neutral fabric."""

import hashlib
import json
import colorsys
from pathlib import Path
from random import Random

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageFont

from backend import club_art


ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "frontend/public/portraits"
TEXTILE = (
    Image.open(PUBLIC / "jersey.webp")
    .convert("RGBA")
    .resize((560, 373), Image.Resampling.LANCZOS)
)
BASE = Image.new("RGBA", (480, 560))
BASE.paste(TEXTILE, (-40, 228))
FABRIC = np.asarray(BASE)


def rgb(c):
    return ImageColor.getrgb(c) if isinstance(c, str) else c


def mix(a, b, t):
    return tuple(round(x * (1 - t) + y * t) for x, y in zip(rgb(a), rgb(b)))


def fictional(name, rng):
    filename = club_art.ROOT / (club_art.catalog()[name]["sha256"] + ".png")
    im = Image.open(filename).convert("RGBA").resize((32, 32))
    pixels = [
        tuple(p[:3]) for p in np.asarray(im).reshape(-1, 4).tolist() if p[3] > 200
    ]
    colors = sorted(
        pixels,
        key=lambda p: colorsys.rgb_to_hsv(*[v / 255 for v in p])[1],
        reverse=True,
    )
    accent = colors[len(colors) // 8] if colors else (122, 150, 144)
    base = mix(accent, (20, 24, 29), rng.uniform(0.56, 0.85))
    return dict(
        base=base,
        accent=mix(accent, (222, 225, 219), 0.13),
        style=rng.choice(("piping", "camo", "wing", "jacquard", "brush", "shoulders")),
        chest=name,
        badgeX=160,
    )


def bake(name, spec, rng, modeled):
    base, trim = rgb(spec["base"]), rgb(spec["accent"])
    canvas = Image.new("RGB", (480, 560), base)
    d = ImageDraw.Draw(canvas)
    shape = spec["style"]
    # All coordinates use the same neck and shoulder anchors as the photographic kits.
    if shape == "gradient":
        for y in range(260, 560):
            d.line([(0, y), (480, y)], fill=mix(base, trim, (y - 260) / 380))
    if shape in ("chestband", "doubleband"):
        d.rectangle((0, 376, 480, 456), fill=trim)
        if shape == "doubleband":
            d.rectangle((0, 399, 480, 455), fill=(30, 46, 70))
    if shape in ("pinstripe", "stripes"):
        for x in range(-20, 510, 20 if shape == "pinstripe" else 72):
            d.polygon(
                [
                    (x, 266),
                    (x + 3 if shape == "pinstripe" else x + 30, 266),
                    (x + 10 if shape == "pinstripe" else x + 37, 560),
                    (x + 7, 560),
                ],
                fill=trim,
            )
    if shape == "hoops":
        for y in range(340, 560, 17):
            d.line((20, y, 460, y), fill=mix(base, trim, 0.4), width=2)
    if shape == "map":
        for pts in [
            [
                (32, 340),
                (105, 340),
                (105, 371),
                (148, 371),
                (148, 425),
                (201, 425),
                (201, 470),
            ],
            [
                (218, 565),
                (218, 464),
                (256, 464),
                (256, 414),
                (304, 414),
                (304, 349),
                (363, 349),
                (363, 312),
            ],
            [(326, 558), (326, 481), (404, 481), (404, 438), (465, 438)],
        ]:
            d.line(pts, fill=mix(base, trim, 0.8), width=11, joint="curve")
            d.line(
                [(x + 7, y + 7) for x, y in pts], fill=mix(base, trim, 0.48), width=3
            )
    if shape in (
        "raglan",
        "wing",
        "piping",
        "shoulders",
        "raglanline",
        "triple",
        "gold",
    ):
        for side in (1, -1):

            def reflect(pts):
                return [(x if side == 1 else 480 - x, y) for x, y in pts]

            seam = reflect(
                [(142, 268), (102, 301), (61, 356), (44, 418), (40, 470), (54, 560)]
            )
            if shape in ("raglan", "shoulders", "wing", "piping"):
                d.polygon(
                    reflect(
                        [
                            (0, 247),
                            (140, 268),
                            (101, 307),
                            (67, 365),
                            (52, 443),
                            (63, 560),
                            (0, 560),
                        ]
                    ),
                    fill=trim if shape in ("raglan", "wing") else mix(base, trim, 0.47),
                )
            width = 3 if shape != "gold" else 5
            d.line(
                seam,
                fill=trim if shape != "raglan" else (211, 211, 201),
                width=width,
                joint="curve",
            )
            if shape == "triple":
                for j in range(3):
                    d.line(
                        reflect(
                            [
                                (156 - j * 5, 268 + j * 6),
                                (82 - j * 6, 298 + j * 8),
                                (32 - j * 4, 326 + j * 9),
                            ]
                        ),
                        fill=trim,
                        width=5,
                    )
    if shape == "glitch":
        for i in range(104):
            x = rng.choice([rng.randrange(-8, 78), rng.randrange(402, 480)])
            y = rng.randrange(295, 560)
            d.rectangle(
                (x, y, x + rng.randint(3, 25), y + rng.choice([2, 4, 8])),
                fill=rng.choice([trim, (35, 123, 169), mix(base, trim, 0.4)]),
            )
    if shape == "camo":
        for i in range(180):
            x = rng.randrange(0, 60) * 8
            y = rng.randrange(33, 70) * 8
            r = rng.randrange(1, 5) * 8
            d.polygon(
                [
                    (x, y),
                    (x + r, y),
                    (x + r, y + 8),
                    (x + r - 8, y + 8),
                    (x + r - 8, y + 16),
                    (x - 8, y + 16),
                    (x - 8, y + 8),
                    (x, y + 8),
                ],
                fill=mix(base, trim, rng.uniform(0.10, 0.62)),
            )
    if shape == "brush":
        for i in range(56):
            x = rng.randrange(-80, 370)
            y = rng.randrange(385, 575)
            d.polygon(
                [(x, y), (x + 85, y - 69), (x + 46, y - 27), (x + 5, y + 2)],
                fill=mix(base, trim, rng.uniform(0.18, 0.9)),
            )
    if shape == "jacquard" or modeled:
        ink = mix(base, trim, 0.09)
        for y in range(307, 566, 21):
            for x in range((y % 4) * 4 - 12, 488, 25):
                d.line([(x, y + 6), (x + 8, y), (x + 18, y + 6)], fill=ink, width=2)
    # Ribbing follows the textile's cut. Ink is shaded with the underlying cloth.
    d.arc((169, 225, 309, 317), 0, 180, fill=trim, width=5 if shape != "washed" else 2)
    if name in {
        "Natus Vincere",
        "FURIA Esports",
        "TYLOO",
        "Team Vitality",
        "Wanted Goons",
    }:
        d.line([(181, 287), (239, 323), (297, 287)], fill=trim, width=7, joint="curve")
    if name in {"Team Falcons", "BBL Esports"}:
        for pts in [
            [(174, 260), (215, 292), (232, 312), (208, 326), (173, 287)],
            [(306, 260), (265, 292), (248, 312), (272, 326), (307, 287)],
        ]:
            d.polygon(pts, fill=mix(base, trim, 0.25))
            d.line(pts[1:4], fill=trim, width=3)
    if spec["chest"]:
        size = 36 if len(spec["chest"]) < 8 else min(30, int(330 / len(spec["chest"])))
        font = ImageFont.load_default(size=size)
        ink = (230, 229, 219) if sum(base) < 480 else (44, 43, 43)
        d.text(
            (240, 446), spec["chest"], font=font, fill=ink, anchor="mm", stroke_width=0
        )
    for word, x, y, size in spec.get("marks", []):
        ink = (230, 229, 219) if sum(base) < 480 else (44, 43, 43)
        d.text(
            (x, y), word, anchor="mm", fill=ink, font=ImageFont.load_default(size=size)
        )
    luminance = FABRIC[:, :, 0:1].astype(float)
    shade = np.clip(0.46 + luminance / 171, 0.43, 1.52)
    pix = np.uint8(np.clip(np.asarray(canvas) * shade, 0, 255))
    return Image.fromarray(np.dstack((pix, FABRIC[:, :, 3])))


def cut_and_measure(image, style, rng, name):
    """Shape the neckline in fabric space, then measure the finished front and shoulders."""
    canvas = np.asarray(image)
    h, w = canvas.shape[:2]
    xx = np.arange(w)
    yy, grid_x = np.indices((h, w), dtype=np.float32)
    collar = (
        "polo"
        if style == "gold" or name == "BBL Esports"
        else (
            "v"
            if name
            in {
                "FURIA Esports",
                "Natus Vincere",
                "Team Vitality",
                "TYLOO",
                "Wanted Goons",
            }
            else "crew"
        )
    )
    radius = rng.uniform(53, 68)
    centre = w / 2
    norm = np.abs((xx - centre) / radius)
    neck = np.maximum(0, 1 - norm)
    curve = neck if collar == "v" else np.sqrt(np.maximum(0, 1 - norm**2))
    drop = {
        "crew": rng.uniform(7, 16),
        "polo": rng.uniform(4, 8),
        "v": rng.uniform(17, 25),
    }[collar]
    shoulder_drop = (
        rng.uniform(-5, 6) * np.minimum(1, norm) * np.exp(-(((xx - centre) / 185) ** 4))
    )
    displacement = (drop * curve + shoulder_drop) * np.exp(-(((yy - 307) / 65) ** 2))
    # The sleeve pitch and ease at the upper arm vary independently of collar depth.
    # Measure the sewn shirt after this warp, so the player always keeps the same shoulder span.
    shoulder_ease = rng.uniform(0.88, 0.985)
    chest_ease = rng.uniform(0.92, 1.025)
    horizontal = chest_ease + (shoulder_ease - chest_ease) * np.exp(
        -(((yy - 375) / 72) ** 2)
    )
    cut = cv2.remap(
        canvas,
        np.float32(centre + (grid_x - centre) / horizontal),
        np.float32(yy - displacement),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    mask = cut[:, :, 3] > 180
    fronts = [np.flatnonzero(mask[:, x])[0] for x in range(235, 246)]
    front = round(float(np.median(fronts)), 1)
    spans = []
    for y in range(int(front) + 42, int(front) + 77):
        xs = np.flatnonzero(mask[y])
        if len(xs):
            spans.append(int(xs[-1] - xs[0]))
    rig = {
        "width": w,
        "height": h,
        "collar": [centre, front],
        "span": float(np.percentile(spans, 85)),
        "seat": [120, {"crew": 157.0, "polo": 158.0, "v": 160.0}[collar]],
        "cut": collar,
    }
    return Image.fromarray(cut), rig


def build():
    from tools.november_scene import build as scene

    teams = scene()["teams"]
    specs = json.loads((ROOT / "tools/scene_sources/kit-designs.json").read_text())
    out = PUBLIC / "kits"
    out.mkdir(exist_ok=True)
    catalog = {}
    for tid, t in teams.items():
        name = t["name"]
        rng = Random(int(hashlib.sha256(tid.encode()).hexdigest(), 16))
        spec = specs.get(name) or fictional(name, rng)
        im = bake(name, spec, rng, name not in specs)
        im, rig = cut_and_measure(im, spec["style"], rng, name)
        im.save(out / (tid + ".webp"), quality=86, method=3)
        catalog[tid] = {
            "rig": rig,
            "name": name,
            "badgeX": spec["badgeX"],
            "source": spec.get("source"),
        }
    (ROOT / "frontend/src/kitArt.json").write_text(
        json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=1) + "\n"
    )


if __name__ == "__main__":
    build()
