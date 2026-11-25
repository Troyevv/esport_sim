import { useEffect, useState } from "react";
import type { GarmentRig } from "./wardrobe";
import anatomy from "./portraitAnatomy.json";
import contours from "./garmentContours.json";

type Outline = number[][];
type Registration = {
  camera: number[];
  body: Outline;
  legacy: Outline;
  image: string;
};
const outlines: Record<string, Outline> = contours;
const frames = new Map<
  string,
  { camera: number[]; body: Outline; original: string }
>();
for (const [original, row] of Object.entries(anatomy) as [
  string,
  Registration,
][]) {
  frames.set(original, { camera: row.camera, body: row.legacy, original });
  frames.set(row.image, { camera: row.camera, body: row.body, original });
}

export function portraitFrame(digest?: string) {
  return digest ? frames.get(digest) : undefined;
}

export function shoulderFrame(
  frame: NonNullable<ReturnType<typeof portraitFrame>>,
) {
  const [left, top, width] = frame.camera;
  const shoulders = frame.body[0];
  const chestWidth = Math.max(
    width,
    Math.min(
      width * 1.34,
      (shoulders[shoulders.length - 1] - shoulders[0]) * 0.94,
    ),
  );
  return [
    left + (width - chestWidth) / 2,
    top,
    chestWidth,
    (chestWidth * 280) / 240,
  ];
}

// Place the photographed shirt on the player's own outline. The stamp encodes
// inverse texture coordinates across the two shoulders, the neck and the front
// collar. It only acts on fabric. The shared camera frames the resulting figure.
export const mapBounds = { x: -48, y: 0, width: 336, height: 288 };
const cache = new Map<string, { image: string; placement: string }>();
export function tailor(digest: string, garment: string) {
  const frame = portraitFrame(digest);
  const from = outlines[garment];
  if (!frame || !from) return undefined;
  const key = digest + "/" + garment;
  const cached = cache.get(key);
  if (cached) return cached;
  const [sx, sy] = from;
  const [tx, ty] = frame.body;
  const last = tx.length - 1;
  const mid = Math.floor(last / 2);
  const span = (tx[last] - tx[0]) / (sx[last] - sx[0]);
  const dx = tx[mid] - span * sx[mid],
    dy = ty[mid] - span * sy[mid];
  const canvas = document.createElement("canvas");
  canvas.width = mapBounds.width;
  canvas.height = 48;
  const context = canvas.getContext("2d");
  if (!context) return undefined;
  const rgba = context.createImageData(canvas.width, canvas.height);
  let i = 0;
  for (let col = 0; col < canvas.width; col++) {
    const x = mapBounds.x + col + 0.5;
    while (i < last - 1 && x > tx[i + 1]) i++;
    const t = (x - tx[i]) / (tx[i + 1] - tx[i]);
    const blend = (a: number[]) => a[i] + t * (a[i + 1] - a[i]);
    const texX = dx + span * blend(sx);
    // Outside the sleeve use the terminal offset, so its edge stays straight.
    const k = Math.min(1, Math.max(0, t));
    const sourceY = dy + span * (sy[i] + k * (sy[i + 1] - sy[i]));
    const targetY = ty[i] + k * (ty[i + 1] - ty[i]);
    for (let row = 0; row < canvas.height; row++) {
      const y = ((row + 0.5) * mapBounds.height) / canvas.height;
      const below = Math.max(0, y - targetY);
      const weight = Math.exp((-below * below) / (2 * 65 * 65));
      const p = 4 * (row * canvas.width + col);
      rgba.data[p] = 127.5 + texX - x;
      rgba.data[p + 1] = 127.5 + (sourceY - targetY) * weight;
      rgba.data[p + 3] = 255;
    }
  }
  context.putImageData(rgba, 0, 0);
  const fit = {
    image: canvas.toDataURL(),
    placement: `translate(${dx} ${dy}) scale(${span})`,
  };
  if (cache.size >= 160) cache.delete(cache.keys().next().value!);
  cache.set(key, fit);
  return fit;
}

// Sample the garment at source resolution. Browser displacement filters round
// coordinates at display resolution, which leaves a stair-step around a 120px
// profile collar. The same column map fits crew, V and polo necks.

type Fabric = { image: HTMLImageElement; roof: Float32Array };
const fabrics = new Map<string, Promise<Fabric>>();
const finished = new Map<string, Promise<string>>();
function readFabric(url: string) {
  const cached = fabrics.get(url);
  if (cached) return cached;
  const image = new Image();
  image.src = url;
  const work = image
    .decode()
    .then(() => {
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const ctx = canvas.getContext("2d")!;
      ctx.drawImage(image, 0, 0);
      const pixels = ctx.getImageData(0, 0, image.width, image.height).data;
      const roof = new Float32Array(image.width);
      for (let x = 0; x < image.width; x++) {
        let y = 0;
        while (y < image.height && pixels[4 * (y * image.width + x) + 3] < 120)
          y++;
        roof[x] = y;
      }
      return { image, roof };
    })
    .catch((e) => {
      fabrics.delete(url);
      throw e;
    });
  if (fabrics.size >= 32) fabrics.delete(fabrics.keys().next().value!);
  fabrics.set(url, work);
  return work;
}

function cutFabric(
  digest: string,
  garment: string,
  url: string,
  rig: GarmentRig,
) {
  const key = digest + "/" + url;
  const ready = finished.get(key);
  if (ready) return ready;
  const frame = frames.get(digest)!;
  const [sx] = outlines[garment];
  const [tx, ty] = frame.body;
  const last = tx.length - 1;
  const worldPerNative = 246 / rig.span;
  const scale = (worldPerNative * (tx[last] - tx[0])) / (sx[last] - sx[0]);
  const [left, top, width, height] = shoulderFrame(frame);
  const work = readFabric(url)
    .then(({ image, roof }) => {
      const c = document.createElement("canvas");
      c.width = Math.ceil(width * 2);
      c.height = Math.ceil(height * 2);
      const ctx = c.getContext("2d")!;
      const pixel = width / c.width,
        syRatio = c.height / height;
      let i = 0;
      for (let x = 0; x < c.width; x++) {
        const pos = left + (x + 0.5) * pixel;
        while (i < last - 1 && pos > tx[i + 1]) i++;
        const u = (pos - tx[i]) / (tx[i + 1] - tx[i]);
        const nx =
          (sx[i] + u * (sx[i + 1] - sx[i]) - rig.seat[0]) / worldPerNative +
          rig.collar[0];
        if (nx < 0 || nx >= image.width - 1) continue;
        const leftPx = Math.floor(nx),
          fraction = nx - leftPx;
        const edge =
          roof[leftPx] + fraction * (roof[leftPx + 1] - roof[leftPx]);
        // Ignore isolated transparent columns at the sleeve and extrapolate
        // its natural edge outside the measured shoulder cross-section.
        if (edge >= image.height - 1) continue;
        const v = Math.max(0, Math.min(1, u));
        const dest = ty[i] + v * (ty[i + 1] - ty[i]);
        const measuredEdge = outlines[garment][1];
        const nominal =
          (measuredEdge[i] +
            v * (measuredEdge[i + 1] - measuredEdge[i]) -
            rig.seat[1]) /
            worldPerNative +
          rig.collar[1];
        const baseline = u < 0 || u > 1 ? nominal : edge;
        const sw =
          (pixel * (sx[i + 1] - sx[i])) / (tx[i + 1] - tx[i]) / worldPerNative;
        ctx.drawImage(
          image,
          nx - sw / 2,
          0,
          sw,
          image.height,
          x,
          (dest - top - baseline * scale) * syRatio,
          1,
          image.height * scale * syRatio,
        );
      }
      return c.toDataURL();
    })
    .catch((e) => {
      finished.delete(key);
      throw e;
    });
  if (finished.size >= 72) finished.delete(finished.keys().next().value!);
  finished.set(key, work);
  return work;
}

export function useFittedFabric(
  digest: string | undefined,
  garment: string,
  url: string,
  rig: GarmentRig,
) {
  const key = digest + "/" + url;
  const [result, setResult] = useState({ key: "", image: "" });
  useEffect(() => {
    if (!digest || !frames.has(digest) || !outlines[garment]) return;
    let active = true;
    cutFabric(digest, garment, url, rig)
      .then((image) => {
        if (active) setResult({ key, image });
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [key, digest, garment, url, rig]);
  return result.key === key ? result.image : undefined;
}
