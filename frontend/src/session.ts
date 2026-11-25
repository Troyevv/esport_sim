import { useEffect, useRef, useState } from "react";
import { RadarPlayback } from "./playback";
import type { MatchView } from "./MatchCenter";
import type { Agent, RadarMap } from "./Radar";

export type View = "full" | "CT" | "T";
export interface Frame {
  libraryRevision?: number;
  careerId?: string;
  careerRevision?: number;
  sequence: number;
  revision: number;
  context: string;
  running: boolean;
  speed: number;
  hasSave: boolean;
  world: {
    match?: MatchView;
    map: RadarMap;
    agents: Agent[];
    motion?: { startTick: number; tracks: Record<string, [number, number, number, number?][]> };
    seed: number;
    tick: number;
    time: number;
    view: View;
    events: { kind?: string; weapon?: string; utility?: string; player?: string; target?: string; head?: boolean; tick: number; team: string | null; text: string }[];
  };
}
type Intent = {
  id: string;
  context: string;
  revision: number;
  kind: string;
  value?: number|string|object;
};
const base = new URL(import.meta.env.VITE_SERVER_URL || location.origin);
export const serverURL = (path: string) => new URL(path, base);
const storageKey = "pending-command:" + base.origin;
async function request(path: string, body?: unknown) {
  return fetch(new URL(path, base), {
    method: body === undefined ? "GET" : "POST",
    credentials: "include",
    cache: "no-store",
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: AbortSignal.timeout(8000),
  });
}

export function useSession(view: View) {
  const [playback] = useState(() => new RadarPlayback());
  const [frame, setFrame] = useState<Frame | null>(null);
  const [connection, setConnection] = useState("Подключение");
  const [notice, setNotice] = useState("");
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [generation, setGeneration] = useState(0);
  const current = useRef<Frame | null>(null);
  const locked = useRef(false);
  const resync = () => setGeneration((v) => v + 1);

  async function settle(intent: Intent, recovering: boolean) {
    let result = recovering ? await request("/api/command/" + intent.id) : null;
    if (!result || result.status === 404)
      result = await request("/api/command", intent);
    if (result.status === 401 || result.status >= 500)
      throw new Error("Требуется сверка с сервером");
    const answer = await result.json();
    if (result.ok || result.status === 409 || result.status === 422) {
      sessionStorage.removeItem(storageKey);
      if (!result.ok)
        setNotice(
          typeof answer.detail === "string"
            ? answer.detail
            : "Команда отклонена сервером",
        );
      else
        setNotice(
          (
            {
              "career-save": "Карьера сохранена",
              "career-load": "Сохранение загружено",
              save: "Снимок сохранён",
              load: "Снимок загружен",
              reset: "Сценарий сброшен",
            } as Record<string, string>
          )[intent.kind] || "",
        );
    } else throw new Error("Сервер отклонил подключение");
    return result.ok;
  }

  useEffect(() => {
    let active = true;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout>;
    let heartbeat: ReturnType<typeof setTimeout>;
    let delay = 300;
    if (current.current) playback.push(current.current, false, performance.now());
    current.current = null;
    setConnection("Подключение");
    setFrame(null);
    setLoadError("");
    const retry = () => {
      if (!active) return;
      if (current.current) playback.push(current.current, false, performance.now());
      setConnection("Переподключение");
      current.current = null;
      timer = setTimeout(connect, delay);
      delay = Math.min(5000, delay * 2);
    };
    async function connect() {
      try {
        const response = await request("/api/state?view=" + view);
        if (!active) return;
        if (response.status === 401) {
          setConnection("Требуется код");
          return;
        }
        if (response.status === 500 || response.status === 403) {
          setConnection("Ошибка загрузки");
          setLoadError(response.status === 500
            ? "Сервер не смог прочитать состояние (HTTP 500). На домашнем ПК проверьте launcher.log в папке %LOCALAPPDATA%\\EsportSim."
            : "Сервер отклонил этот адрес (HTTP 403). Откройте игру по адресу, выданному домашним сервером.");
          return;
        }
        if (!response.ok) throw new Error();
        const pending = sessionStorage.getItem(storageKey);
        if (pending) await settle(JSON.parse(pending), true);
        if (!active) return;
        const url = new URL("/api/stream?view=" + view, base);
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(url);
        const resetHeartbeat = () => {
          clearTimeout(heartbeat);
          heartbeat = setTimeout(() => socket?.close(), 7000);
        };
        resetHeartbeat();
        socket.onmessage = (event) => {
          resetHeartbeat();
          if (!active) return;
          const snapshot: Frame = JSON.parse(event.data);
          if (current.current && snapshot.sequence < current.current.sequence)
            return;
          playback.push(snapshot, true, performance.now());
          current.current = snapshot;
          setFrame(snapshot);
          setConnection("На связи");
          delay = 300;
        };
        socket.onclose = () => {
          clearTimeout(heartbeat);
          retry();
        };
        socket.onerror = () => socket?.close();
      } catch {
        retry();
      }
    }
    void connect();
    return () => {
      active = false;
      clearTimeout(timer);
      clearTimeout(heartbeat);
      if (socket) {
        socket.onclose = null;
        socket.close();
      }
    };
  }, [view, generation]);

  async function act(kind: string, value?: number|string|object) {
    const seen = current.current;
    if (!seen || locked.current) return false;
    locked.current = true;
    setBusy(true);
    setNotice("");
    try {
      const intent = {
        id: crypto.randomUUID(),
        context: seen.context,
        revision: seen.revision,
        kind,
        value,
      };
      sessionStorage.setItem(storageKey, JSON.stringify(intent));
      const accepted = await settle(intent, false);
      // Read immediately as well as subscribing, so the next action uses the committed revision.
      const response = await request("/api/state?view=" + view);
      if (!response.ok) throw new Error();
      const snapshot: Frame = await response.json();
      if (
        current.current?.world.view === view &&
        snapshot.sequence >= current.current.sequence
      ) {
        playback.push(snapshot, true, performance.now());
        current.current = snapshot;
        setFrame(snapshot);
      }
      return accepted;
    } catch {
      setConnection("Переподключение");
      setNotice("Сверяем результат команды с сервером");
      resync();
      return false;
    } finally {
      locked.current = false;
      setBusy(false);
    }
  }
  async function pair(code: string, name: string) {
    try {
      const result = await request("/api/pair", { code, name });
      if (result.ok) {
        setNotice("");
        resync();
      } else setNotice("Код недействителен. Проверьте код на домашнем ПК.");
    } catch {
      setNotice("Домашний сервер недоступен");
    }
  }
  return { frame, playback, connection, loadError, resync, notice, clearNotice: () => setNotice(""), busy, act, pair };
}
