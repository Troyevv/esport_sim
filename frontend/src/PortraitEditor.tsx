import { useState } from "react";
import {
  photoLicenses,
  resolvePortrait,
  type PhotoRef,
  type PhotoAsset,
} from "./portraits";
export default function PortraitEditor({
  value,
  change,
  layer = false,
}: {
  value?: PhotoRef;
  layer?: boolean;
  change: (v: PhotoRef) => void;
}) {
  const p = resolvePortrait(value);
  const [error, setError] = useState("");
  const set = (v: Partial<PhotoAsset>) =>
    change({
      ...{
        image: "",
        author: "",
        source: "",
        license: "CC BY 4.0",
        changes: "",
      },
      ...p,
      ...v,
    });
  return (
    <details className="db-editor-extra">
      <summary>
        {layer ? "Слой головы и шеи" : "Исходное изображение и лицензия"}
      </summary>
      {layer && (
        <p>
          Прозрачный RGBA PNG 240×280 или 480×560. Для базового размера линия
          глаз проходит около y=73, подбородка — y=135. Шея должна заходить под
          воротник до y=182.
        </p>
      )}
      {!p ? (
        <button onClick={() => set({})}>Добавить фотографию</button>
      ) : (
        <div className="db-form">
          <label>
            Изображение · JPEG или PNG
            <input
              type="file"
              accept={layer ? "image/png" : "image/jpeg,image/png"}
              onChange={async (e) => {
                const file = e.target.files?.[0];
                if (!file) return;
                if (
                  file.size > 1024 * 1024 ||
                  !["image/jpeg", "image/png"].includes(file.type)
                ) {
                  setError("Выберите JPEG или PNG размером до 1 МиБ");
                  return;
                }
                const reader = new FileReader();
                reader.onerror = () =>
                  setError("Не удалось прочитать изображение");
                reader.onload = () => {
                  setError("");
                  set({ image: String(reader.result) });
                };
                reader.readAsDataURL(file);
              }}
            />
          </label>
          <label>
            Автор фотографии
            <input
              value={p.author}
              onChange={(e) => set({ author: e.target.value })}
            />
          </label>
          <label>
            Страница источника
            <input
              type="url"
              placeholder="https://"
              value={p.source}
              onChange={(e) => set({ source: e.target.value })}
            />
          </label>
          <label>
            Лицензия
            <select
              value={p.license}
              onChange={(e) => set({ license: e.target.value })}
            >
              {Object.keys(photoLicenses).map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </label>
          <label>
            Изменения изображения
            <input
              value={p.changes}
              placeholder="Например, кадрирование"
              onChange={(e) => set({ changes: e.target.value })}
            />
          </label>
          {p.image && (
            <img
              src={p.image}
              alt="Портрет в пакете"
              referrerPolicy="no-referrer"
              width="64"
            />
          )}
          <button onClick={() => change(null)}>Убрать фотографию</button>
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </details>
  );
}
