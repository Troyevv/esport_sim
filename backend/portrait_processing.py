"""Offline geometric quality checks and semantic head/neck segmentation.

Landmarks are used for framing and pose only. Sporting identity is determined
from publisher metadata before this module receives pixels.
"""

import hashlib
import math
from io import BytesIO
from pathlib import Path


class Unsuitable(ValueError):
    pass


VERSION = "studio-v1"
MODELS = Path(__file__).with_name("data") / "portrait-models"
DIGESTS = {
    "face_landmarker.task": "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    "selfie_multiclass.tflite": "c6748b1253a99067ef71f7e26ca71096cd449baefa8f101900ea23016507e0e0",
}


class PortraitProcessor:
    def __init__(self):
        import mediapipe as mp
        from mediapipe.tasks.python import vision

        self.mp = mp

        def model(name):
            data = (MODELS / name).read_bytes()
            if hashlib.sha256(data).hexdigest() != DIGESTS[name]:
                raise RuntimeError("Повреждена локальная модель " + name)
            return mp.tasks.BaseOptions(model_asset_buffer=data)

        self.faces = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=model("face_landmarker.task"),
                num_faces=3,
                output_face_blendshapes=True,
                min_face_detection_confidence=0.65,
            )
        )
        try:
            self.skin = vision.ImageSegmenter.create_from_options(
                vision.ImageSegmenterOptions(
                    base_options=model("selfie_multiclass.tflite"),
                    output_confidence_masks=True,
                )
            )
        except Exception:
            self.faces.close()
            raise

    def close(self):
        self.faces.close()
        self.skin.close()

    def image(self, array):
        import numpy as np

        return self.mp.Image(
            image_format=self.mp.ImageFormat.SRGB, data=np.ascontiguousarray(array)
        )

    def render(self, raw):
        return self._render(raw, studio=False)[0]

    def render_roster(self, raw):
        """For reviewed studio roster sources, also return the natural display width."""
        return self._render(raw, studio=True)

    def _render(self, raw, studio, register=None):
        import cv2
        import numpy as np
        from PIL import Image, ImageOps, UnidentifiedImageError

        try:
            with Image.open(BytesIO(raw)) as im:
                if (
                    im.format not in ("JPEG", "PNG", "WEBP")
                    or im.width * im.height > 24_000_000
                ):
                    raise Unsuitable("Неподходящий формат или размер")
                im = ImageOps.exif_transpose(im).convert("RGBA")
                im.thumbnail((1400, 1400))
                original = np.asarray(im)
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as e:
            raise Unsuitable("Изображение не читается") from e
        if min(original.shape[:2]) < 300:
            raise Unsuitable("Недостаточное разрешение")
        if studio and original[:, :, 3].min() != 0:
            raise Unsuitable("Нет прозрачного студийного исходника")
        # Flatten transparent studio backgrounds to middle gray for the two models.
        rgba = original.astype(np.float32) / 255
        rgb = np.uint8(
            (rgba[:, :, :3] * rgba[:, :, 3:] + 0.61 * (1 - rgba[:, :, 3:])) * 255
        )
        h, w = rgb.shape[:2]
        detected = self.faces.detect(self.image(rgb))
        if len(detected.face_landmarks) != 1:
            raise Unsuitable("Требуется одно видимое лицо")
        lm = np.array([(p.x * w, p.y * h) for p in detected.face_landmarks[0]])
        left = lm[[33, 133]].mean(0)
        right = lm[[362, 263]].mean(0)
        eyes = (left + right) / 2
        delta = right - left
        span = float(np.linalg.norm(delta))
        chin = lm[152]
        # The semantic crop below already removes excess torso and margins.
        # 120 CSS pixels is the largest normal profile header (78 eye pixels at 480).
        native_width = math.floor(span * 480 / 78)
        if span < 45 and (not studio or native_width < 160):
            raise Unsuitable("Лицо слишком мало в кадре")
        if (
            abs(math.degrees(math.atan2(delta[1], delta[0]))) > 9
            or abs(lm[1, 0] - eyes[0]) / span > 0.22
        ):
            raise Unsuitable("Разворот или наклон головы")
        if not 0.83 < (chin[1] - eyes[1]) / span < 2.05:
            raise Unsuitable("Наклон головы относительно камеры")
        expression = {b.category_name: b.score for b in detected.face_blendshapes[0]}
        if (
            max(
                expression.get(k, 0)
                for k in ("jawOpen", "mouthSmileLeft", "mouthSmileRight")
            )
            > 0.78
        ):
            raise Unsuitable("Требуется нейтральное выражение")
        if studio:
            # Measure the original face, excluding silhouette edges and jersey detail.
            face = rgb[
                max(0, int(eyes[1] - 0.35 * span)) : min(h, int(chin[1] - 0.2 * span)),
                max(0, int(eyes[0] - 0.75 * span)) : min(w, int(eyes[0] + 0.75 * span)),
            ]
            if not face.size:
                raise Unsuitable("Лицо за границей кадра")
            gray = cv2.cvtColor(face, cv2.COLOR_RGB2GRAY)
            if np.std(gray) < 12 or cv2.Laplacian(gray, cv2.CV_64F).var() < 70:
                raise Unsuitable("Недостаточная детализация лица")
        x0 = max(0, round(eyes[0] - 1.85 * span))
        x1 = min(w, round(eyes[0] + 1.85 * span))
        y0 = max(0, round(eyes[1] - 3.15 * span))
        y1 = min(h, round(chin[1] + 1.4 * span))
        results = self.skin.segment(self.image(rgb[y0:y1, x0:x1]))
        probs = [m.numpy_view().copy().squeeze() for m in results.confidence_masks]
        rows, cols = np.ogrid[y0:y1, x0:x1]
        central = np.abs(cols - chin[0]) / span
        neck = (
            (central < 0.96)
            & (rows > eyes[1] + 0.42 * span)
            & (rows < chin[1] + 1.26 * span)
        )
        ears = (
            (central > 0.68)
            & (central < 1.48)
            & (rows > eyes[1] - 0.58 * span)
            & (rows < eyes[1] + 0.65 * span)
        )
        if np.mean(probs[5][ears] > 0.6) > 0.13:
            raise Unsuitable("Предмет закрывает уши или лицо")
        conf = probs[1] + probs[3] + probs[2] * neck
        alpha = np.clip((conf - 0.15) / 0.73, 0, 1) * rgba[y0:y1, x0:x1, 3]
        # Retain only the head attached to the nose, discard detached hands/people.
        _, labels = cv2.connectedComponents(np.uint8(alpha > 0.18))
        ny, nx = np.rint(lm[1] - [x0, y0]).astype(int)[::-1]
        if (
            not (0 <= ny < labels.shape[0] and 0 <= nx < labels.shape[1])
            or not labels[ny, nx]
        ):
            raise Unsuitable("Не удалось выделить лицо")
        component = np.uint8(labels == labels[ny, nx])
        if y0 == 0 and component[0].sum() > span * 0.55:
            raise Unsuitable("Верх головы обрезан")
        alpha *= cv2.dilate(component, np.ones((3, 3), np.uint8))
        top = np.flatnonzero((component > 0).sum(axis=1) > span * 0.12)[0] + y0
        scale = min(78 / span, 153 / max(1, eyes[1] - top))
        target_eye_y = max(156, 12 + (eyes[1] - top) * scale)
        mat = cv2.getRotationMatrix2D(
            tuple(eyes - [x0, y0]), math.degrees(math.atan2(delta[1], delta[0])), scale
        )
        mat[:, 2] += np.array([240, target_eye_y]) - (eyes - [x0, y0])
        if register is not None:
            full_transform = mat.copy()
            full_transform[:, 2] -= mat[:, :2] @ [x0, y0]
            register(original, rgb, lm, full_transform)
        color = rgb[y0:y1, x0:x1].astype(np.float32) * alpha[:, :, None]
        output = cv2.warpAffine(
            np.dstack([color, alpha]), mat, (480, 560), flags=cv2.INTER_LINEAR
        )
        a = output[:, :, 3]
        if np.mean(a[298:311, 209:270]) < 0.7 or np.mean(a[318:327, 226:254]) < 0.6:
            raise Unsuitable("Шея не доходит до воротника")
        if a[:5].max() > 0.5:
            raise Unsuitable("Волосы выходят за рамку")
        output[:, :, :3] /= np.maximum(a[:, :, None], 0.001)
        # The jersey overlaps the bottom of the neck on the canonical canvas.
        output[354:368, :, 3] *= np.linspace(1, 0, 14)[:, None]
        output[368:, :, 3] = 0
        output[:, :, 3] *= 255
        dst = BytesIO()
        Image.fromarray(np.uint8(np.clip(output, 0, 255))).save(
            dst, format="PNG", optimize=True
        )
        return dst.getvalue(), native_width
