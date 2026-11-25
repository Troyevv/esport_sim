import { useEffect, useRef, useState } from "react";
import { serverURL } from "./session";

type Report = {
  mode: "off" | "personal" | "copy";
  running: boolean;
  ready: number;
  available: number;
  explicit: number;
  errors: Record<string, string>;
};
export function PersonalBadges({ refresh }: { refresh: () => Promise<void> }) {
  const [open, setOpen] = useState(false),
    [report, setReport] = useState<Report | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  const onRefresh = useRef(refresh);
  onRefresh.current = refresh;
  const latest = useRef("");
  async function accept(next: Report) {
    setReport(next);
    const stamp = [next.mode, next.ready, next.running].join("/");
    const changed = latest.current && latest.current !== stamp;
    latest.current = stamp;
    if (changed && !next.running) await onRefresh.current();
  }
  useEffect(() => {
    if (!open) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const response = await fetch(
          serverURL("/api/database/personal-badges/status"),
          { credentials: "include", cache: "no-store" },
        );
        if (!response.ok)
          throw Error("Не удалось прочитать состояние личного пакета");
        const next: Report = await response.json();
        if (!live) return;
        await accept(next);
        if (next.running && live) timer = setTimeout(poll, 1100);
      } catch (e) {
        if (live) setError(String(e));
      }
    }
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [open, report?.running, report?.mode]);
  async function offline(file: File) {
    setBusy(true);
    setError("");
    try {
      const response = await fetch(
        serverURL("/api/database/personal-badges/offline"),
        {
          method: "POST",
          credentials: "include",
          body: file,
        },
      );
      const result = await response.json();
      if (!response.ok)
        throw Error(result.detail || "Не удалось установить файл");
      await accept(result);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function change(mode: Report["mode"]) {
    setError("");
    setBusy(true);
    try {
      const response = await fetch(
        serverURL("/api/database/personal-badges/action"),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ mode }),
        },
      );
      if (!response.ok) throw Error("Не удалось изменить личный пакет");
      await accept(await response.json());
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details
      className="kit-studio private-badges"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Оригинальные эмблемы для личной игры</summary>
      {open && (
        <div className="badge-library">
          <p>
            Домашний сервер хранит этот пакет отдельно от базы. Установленные
            оригиналы появляются в профилях, составах, на форме и в матч-центре.
            Экспорт базы содержит поставляемые эмблемы.
          </p>
          {report && (
            <>
              <p role="status">
                {report.running
                  ? "Загрузка оригиналов…"
                  : report.mode === "off"
                    ? "Личный пакет отключён"
                    : "Личный пакет подключён"}{" "}
                · Установлено и активно: <strong>{report.ready}</strong>
              </p>
              <div className="badge-library-options">
                <div>
                  <strong>По условиям издателей · {report.explicit}</strong>
                  <p>
                    Источники прямо предлагают эти файлы для личного
                    использования.
                  </p>
                  <button
                    disabled={busy || report.running}
                    onClick={() => change("personal")}
                  >
                    Установить по условиям издателей
                  </button>
                </div>
                <div>
                  <strong>Полный личный пакет · {report.available}</strong>
                  <p>
                    Дополнительно включает опубликованные знаки клубов.
                    Выбирайте, если по применимому к вам праву разрешена личная
                    копия этих изображений.
                  </p>
                  <button
                    disabled={busy || report.running}
                    onClick={() => change("copy")}
                  >
                    Установить полный личный пакет
                  </button>
                </div>
              </div>
              <label>
                Готовый личный пакет с диска (.eslogos)
                <input
                  type="file"
                  accept=".eslogos"
                  disabled={busy || report.running}
                  onChange={(e) => {
                    const f = e.currentTarget.files?.[0];
                    e.currentTarget.value = "";
                    if (f) void offline(f);
                  }}
                />
              </label>
              <small>
                Файл устанавливается без интернета и включает опубликованные
                изображения для личного использования при наличии
                соответствующего права.
              </small>
              {busy && <p role="status">Установка пакета…</p>}
              {Object.keys(report.errors).length > 0 && (
                <details>
                  <summary>
                    Не удалось загрузить · {Object.keys(report.errors).length}
                  </summary>
                  <ul>
                    {Object.entries(report.errors).map(([n, msg]) => (
                      <li key={n}>
                        <strong>{n}</strong> — {msg}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {report.mode !== "off" && (
                <button disabled={busy} onClick={() => change("off")}>
                  Отключить личный пакет
                </button>
              )}
            </>
          )}
          {error && <p role="alert">{error}</p>}
        </div>
      )}
    </details>
  );
}
