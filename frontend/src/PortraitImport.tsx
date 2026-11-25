import { useEffect, useRef, useState } from "react";
import { serverURL } from "./session";
import { refreshWardrobe } from "./wardrobe";
import { refKey, type Pack } from "./databaseModel";
type Status = {
  state: string;
  pack?: string;
  revision?: number;
  message?: string;
  counts: Record<string, number>;
  recent: { name: string; state: string; reason: string }[];
};
const labels: Record<string, string> = {
  idle: "Готов к запуску",
  running: "Идёт обработка",
  paused: "Приостановлено",
  blocked: "Требуется повтор",
  finished: "Завершено",
};
async function api(path: string, body?: object) {
  const r = await fetch(serverURL("/api/portraits/" + path), {
    credentials: "include",
    cache: "no-store",
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json();
  if (!r.ok) throw Error(data.detail || "Ошибка библиотеки портретов");
  return data as Status;
}
export function PortraitImport({
  pack,
  onRefresh,
}: {
  pack: Pack;
  onRefresh: () => Promise<void>;
}) {
  const [status, setStatus] = useState<Status | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [open, setOpen] = useState(false);
  const refreshing = useRef(onRefresh);
  refreshing.current = onRefresh;
  const previous = useRef(-1);
  useEffect(() => {
    if (!open) return;
    let live = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const s = await api("status");
        if (!live) return;
        setStatus(s);
        const count = s.counts.done || 0;
        if (
          s.pack === pack.id &&
          s.revision === pack.revision &&
          count > 0 &&
          count !== previous.current
        )
          await refreshing.current();
        previous.current = count;
        setError("");
        if (live)
          timer = setTimeout(poll, s.state === "running" ? 2500 : 10000);
      } catch (e) {
        if (live) {
          setError(String(e));
          timer = setTimeout(poll, 10000);
        }
      }
    }
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [open, pack.id, pack.revision]);
  const [installed, setInstalled] = useState<number | null>(null);
  const [kitCount, setKitCount] = useState(0);
  async function installFile(file: File) {
    setError("");
    setInstalled(null);
    setBusy(true);
    try {
      const response = await fetch(
        serverURL("/api/portraits/" + refKey(pack) + "/offline"),
        {
          method: "POST",
          credentials: "include",
          body: file,
        },
      );
      const result = await response.json();
      if (!response.ok)
        throw Error(result.detail || "Не удалось установить личные портреты");
      await onRefresh();
      await refreshWardrobe();
      setKitCount(result.kits || 0);
      setInstalled(result.installed);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function command(mode: string) {
    setBusy(true);
    try {
      const s =
        mode === "pause"
          ? await api("pause", {})
          : await api(refKey(pack) + "/start", { mode });
      setStatus(s);
      previous.current = s.counts.done || 0;
      setError("");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  const running = status?.state === "running",
    same = status?.pack === pack.id && status?.revision === pack.revision;
  const c = status?.counts || {};
  const total = Object.values(c).reduce((a, b) => a + b, 0);
  return (
    <details
      className="db-import-studio"
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Студийные портреты</summary>
      <div>
        <p>
          Готовые портреты устанавливаются на домашний сервер. В профилях,
          составах и матчах внешность игрока сохраняется при смене клубной
          формы.
        </p>
        <label>
          Личный пакет портретов (.esportraits)
          <input
            type="file"
            accept=".esportraits"
            disabled={busy || running}
            onChange={(e) => {
              const file = e.currentTarget.files?.[0];
              e.currentTarget.value = "";
              if (file) void installFile(file);
            }}
          />
        </label>
        {kitCount > 0 && (
          <p role="status">Подключено комплектов формы: {kitCount}</p>
        )}
        {installed !== null && (
          <p role="status">Подключено студийных портретов: {installed}</p>
        )}
        <p>
          Для дальнейших обновлений можно запустить поиск и обработку
          фотографий. Игроки без подходящего портрета отображаются с нейтральной
          внешностью.
        </p>
        <div className="db-actions">
          <button
            className="primary"
            disabled={busy || running}
            onClick={() => command("pilot")}
          >
            Пилот · 3 игрока
          </button>
          <button disabled={busy || running} onClick={() => command("all")}>
            Обработать всю базу
          </button>
          {running && (
            <button disabled={busy} onClick={() => command("pause")}>
              Приостановить
            </button>
          )}
          {same && !running && (
            <button disabled={busy} onClick={() => command("retry")}>
              Повторить пропущенные
            </button>
          )}
        </div>
        {status && (
          <p role="status">
            {labels[status.state]}
            {total > 0 &&
              ` · Готово ${c.done || 0} · Пропущено ${c.skipped || 0} · В очереди ${c.queued || 0}`}
            {status.message && " · " + status.message}
          </p>
        )}
        {!!status?.recent.length && (
          <ul>
            {status.recent.map((r, i) => (
              <li key={i}>
                <b>{r.name}</b> · {r.reason}
              </li>
            ))}
          </ul>
        )}
        {error && <p role="alert">{error}</p>}
      </div>
    </details>
  );
}
