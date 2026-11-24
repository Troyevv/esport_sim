import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import Radar from "./Radar";
import HostSettings from "./HostSettings";
import { useSession, type View } from "./session";
import "./style.css";

const formatTime = (seconds: number) =>
  [
    Math.floor(seconds / 3600),
    Math.floor(seconds / 60) % 60,
    Math.floor(seconds) % 60,
  ]
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
type Glyph =
  | "radar"
  | "play"
  | "pause"
  | "save"
  | "load"
  | "reset"
  | "activity"
  | "layers"
  | "log";
const strokes: Record<Glyph, string> = {
  radar: "M3 12a9 9 0 1 0 9-9M7 12a5 5 0 1 0 5-5M12 12l8-8",
  play: "M7 4l13 8-13 8z",
  pause: "M8 5v14m8-14v14",
  save: "M3 3h15l3 3v15H3zM7 3v6h9V3m-9 18v-8h10v8",
  load: "M3 9V5h7l3 3h8v3M3 11h19l-4 9H4z",
  reset: "M4 9a8 8 0 1 1 0 7M4 3v6h6",
  activity: "M2 13h5l3-9 5 16 3-8h4",
  layers: "M2 8l10-5 10 5-10 5zM2 13l10 5 10-5M2 17l10 5 10-5",
  log: "M5 5h14M5 12h14M5 19h9",
};
function Icon({ name }: { name: Glyph }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={strokes[name]} />
    </svg>
  );
}
function takePairingCode() {
  const params = new URLSearchParams(location.hash.slice(1));
  const value = params.get("pair");
  if (!value) return "";
  params.delete("pair");
  const rest = params.toString();
  history.replaceState(history.state, "", location.pathname + location.search + (rest ? "#" + rest : ""));
  return value;
}

function App() {
  const [view, setView] = useState<View>("full");
  const [selected, setSelected] = useState<string | null>(null);
  const [seed, setSeed] = useState("42");
  const [code, setCode] = useState(takePairingCode);
  const [deviceName, setDeviceName] = useState(() => {
    const platform = navigator.userAgent.match(/iPhone|iPad|Android/i)?.[0];
    return platform || "Мой браузер";
  });
  const { frame, connection, busy, notice, act, pair } = useSession(view);
  useEffect(() => {
    if (connection === "На связи") setCode("");
  }, [connection]);
  const world = frame?.world;
  const agent = world?.agents.find((item) => item.id === selected);
  const enabled = !!frame && connection === "На связи" && !busy;
  const validSeed = /^\d+$/.test(seed) && Number(seed) <= 2147483647;
  useEffect(() => {
    if (world) setSeed(String(world.seed));
  }, [world?.seed]);
  return (
    <>
      <header className="mast">
        <div className="identity">
          <i className="brandmark">
            <b />
            <b />
            <b />
          </i>
          esport<span>_sim</span>
        </div>
        <div className="mastline" />
        <span className="masttitle">Лаборатория симуляции</span>
        <span
          className={"connection " + (connection === "На связи" ? "up" : "")}
          data-testid="connection"
        >
          <i />
          {connection}
        </span>
        <HostSettings connected={connection === "На связи"}/>
      </header>
      <main>
        <div className="intro">
          <div>
            <div className="eyebrow">
              <i /> СТЕНД СИМУЛЯЦИИ <span>/ R0</span>
            </div>
            <h1>Тактический радар</h1>
          </div>
          {world && (
            <div className="clock">
              <span>МОДЕЛЬНОЕ ВРЕМЯ</span>
              <strong>{formatTime(world.time)}</strong>
            </div>
          )}
        </div>
        {connection === "Требуется код" && (
          <form
            className="panel pair"
            onSubmit={(e) => {
              e.preventDefault();
              void pair(code, deviceName.trim());
            }}
          >
            <h2>Подключение устройства</h2>
            <label>Название устройства<input value={deviceName} onChange={e => setDeviceName(e.target.value)} maxLength={48} required autoComplete="off"/></label>
            <label>
              Одноразовый код с домашнего ПК{" "}
              <input
                type="password"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                required
              />
            </label>
            <button>Подключить</button>
          </form>
        )}
        {!world && connection !== "Требуется код" && (
          <p role="status">Получаем состояние домашнего сервера…</p>
        )}
        {notice && (
          <p className="notice" role="status">
            {notice}
          </p>
        )}
        {world && frame && (
          <div className="dashboard">
            <div className="column">
              <section className="panel mapcard">
                <div className="maphead">
                  <div className="mapname">
                    <s>
                      <Icon name="layers" />
                    </s>
                    <div>
                      <small>ТЕСТОВАЯ КАРТА</small>
                      <h2>{world.map.name}</h2>
                    </div>
                  </div>
                  <label className="view">
                    <span>Режим обзора</span>
                    <select
                      aria-label="Режим обзора"
                      value={view}
                      disabled={busy}
                      onChange={(e) => {
                        setView(e.target.value as View);
                        setSelected(null);
                      }}
                    >
                      <option value="full">Полный · отладка</option>
                      <option value="CT">Видимость CT</option>
                      <option value="T">Видимость T</option>
                    </select>
                  </label>
                </div>
                <Radar
                  frame={frame}
                  connected={connection === "На связи"}
                  selected={agent?.id ?? null}
                  onSelect={setSelected}
                />
                <div className="mapfoot">
                  <span>
                    <i className="legend ct" />
                    Спецназ
                  </span>
                  <span>
                    <i className="legend t" />
                    Атака
                  </span>
                  {agent && <span className="selected-agent" aria-label={`Выбран ${agent.id} ${agent.name}`}>
                    {agent.id} · {agent.name}
                  </span>}
                  <span className="tick">
                    ТИК <b data-testid="tick">{world.tick}</b>
                  </span>
                </div>
              </section>
              <section className="panel roster">
                <div className="sectionhead">
                  <h2>
                    <Icon name="radar" /> Участники
                  </h2>
                  <span>{world.agents.length} в обзоре</span>
                </div>
                <div className="teams">
                  {(["CT", "T"] as const).map((team) => (
                    <div className={"team " + team} key={team}>
                      <h3>
                        <i className={"legend " + team.toLowerCase()} />
                        {team === "CT" ? "Спецназ" : "Атака"}{" "}
                        <span>{team}</span>
                      </h3>
                      {world.agents
                        .filter((a) => a.team === team)
                        .map((a) => (
                          <button
                            key={a.id}
                            aria-pressed={agent?.id === a.id}
                            onClick={() => setSelected(a.id)}
                          >
                            {a.name}
                            <span>
                              {Math.round(a.x)} · {Math.round(a.y)}
                            </span>
                          </button>
                        ))}
                      {!world.agents.some((a) => a.team === team) && (
                        <small>Вне видимости</small>
                      )}
                    </div>
                  ))}
                </div>
                {agent && (
                  <div className="agentinfo">
                    <strong>{agent.name}</strong> · {agent.status}{" "}
                    <span>
                      Видит: {agent.visible.join(", ") || "—"}. Известные
                      позиции:{" "}
                      {agent.knowledge
                        .map(
                          (k) =>
                            k.id +
                            " (" +
                            Math.round(k.x) +
                            ", " +
                            Math.round(k.y) +
                            ", тик " +
                            k.tick +
                            ")",
                        )
                        .join(", ") || "—"}
                    </span>
                  </div>
                )}
              </section>
            </div>
            <div className="column">
              <aside className="panel control">
                <h2>
                  <Icon name="activity" /> Управление
                </h2>
                <div className="state">
                  <i className={frame.running ? "moving" : ""} />
                  {frame.running ? "Симуляция идёт" : "На паузе"}
                </div>
                <button
                  className="primary"
                  disabled={!enabled}
                  onClick={() => act(frame.running ? "pause" : "start")}
                >
                  <Icon name={frame.running ? "pause" : "play"} />
                  {frame.running ? "Пауза" : "Запустить"}
                </button>
                <div className="field">
                  <label>Скорость симуляции</label>
                  <div className="speeds">
                    {[1, 2, 4, 8].map((x) => (
                      <button
                        key={x}
                        aria-pressed={frame.speed === x}
                        disabled={!enabled}
                        onClick={() => act("speed", x)}
                      >
                        {x}×
                      </button>
                    ))}
                  </div>
                </div>
                <div className="field scenario">
                  <label htmlFor="seed">Seed</label>
                  <div className="seedrow">
                    <input
                      id="seed"
                      type="text"
                      inputMode="numeric"
                      value={seed}
                      onChange={(e) => setSeed(e.target.value)}
                    />
                    <button
                      disabled={!enabled || !validSeed}
                      onClick={() => act("reset", Number(seed))}
                    >
                      <Icon name="reset" />
                      Сбросить
                    </button>
                  </div>
                  {!validSeed && <small>Целое число от 0 до 2147483647</small>}
                </div>
                <div className="field">
                  <label>Снимок состояния</label>
                  <div className="slots">
                    <button disabled={!enabled} onClick={() => act("save")}>
                      <Icon name="save" />
                      Сохранить
                    </button>
                    <button
                      disabled={!enabled || !frame.hasSave}
                      onClick={() => act("load")}
                    >
                      <Icon name="load" />
                      Загрузить
                    </button>
                  </div>
                </div>
                <div className="metadata">
                  <span>Текущий seed</span>
                  <b data-testid="current-seed">{world.seed}</b>
                </div>
              </aside>
              <section className="panel journal">
                <div className="sectionhead">
                  <h2>
                    <Icon name="log" /> Журнал событий
                  </h2>
                </div>
                <ol>
                  {world.events
                    .slice()
                    .reverse()
                    .map((event, i) => (
                      <li key={event.tick + "-" + i}>
                        <time>{formatTime(event.tick / 10).slice(3)}</time>
                        <span>{event.text}</span>
                      </li>
                    ))}
                </ol>
                {!world.events.length && <p>Пока нет наблюдений.</p>}
              </section>
            </div>
          </div>
        )}
      </main>
    </>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
