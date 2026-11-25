import { useEffect, useRef, useState } from "react";
import TacticMap from "./TacticMap";
import {
  colors,
  labels,
  newPlan,
  readJSON,
  symbols,
  timed,
  type Kind,
  type Library,
  type Plan,
  type Point,
  type Preview,
  type Side,
  type Step,
  type Tool,
} from "./tactics";
import { serverURL, type Frame } from "./session";
import "./tactics.css";

type Props = {
  commandNotice: string;
  clearNotice: () => void;
  frame: Frame;
  enabled: boolean;
  onClose: () => void;
  act: (name: string, value?: object) => Promise<boolean>;
};
const toolNames = { ...labels, select: "Выбор", pan: "Сдвиг" };
const tools: Tool[] = [
  "move",
  "hold",
  "face",
  "throw",
  "wait",
  "exit",
  "plant",
  "retreat",
  "select",
  "pan",
];
const help: Record<Tool, string> = {
  move: "Проведите линию или коснитесь цели. Карта покажет путь по проходам.",
  face: "Укажите, куда смотреть из предыдущей позиции.",
  throw: "Укажите цель броска из предыдущей позиции.",
  hold: "Отметьте позицию для удержания.",
  wait: "Отметьте место ожидания.",
  exit: "Укажите позицию для быстрого выхода.",
  plant: "Коснитесь площадки A или B. Игрок получит C4 на старте.",
  retreat: "Укажите точку отхода.",
  select: "Коснитесь маркера игрока или точки маршрута.",
  pan: "Перетащите карту. Два пальца перемещают и масштабируют её в любом режиме.",
};
const draftKey = "tactics-draft:" + serverURL("/").origin;
function readDraft(): Plan | null {
  try {
    const plan = JSON.parse(sessionStorage.getItem(draftKey) || "null");
    return plan?.format === 1 &&
      Array.isArray(plan.slots) &&
      plan.slots.length === 5 &&
      plan.slots.every(Array.isArray)
      ? plan
      : null;
  } catch {
    return null;
  }
}
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Домашний сервер недоступен";

export default function TacticEditor({
  frame,
  enabled,
  act,
  onClose,
  commandNotice,
  clearNotice,
}: Props) {
  const [library, setLibrary] = useState<Library | null>(null),
    [plan, setPlan] = useState<Plan | null>(readDraft);
  const [slot, setSlot] = useState(0),
    [tool, setTool] = useState<Tool>("move");
  const [seconds, setSeconds] = useState(3),
    [utility, setUtility] = useState("Дым");
  const [index, selectIndex] = useState<number | null>(null),
    [replace, setReplace] = useState(false);
  const [dirty, setDirty] = useState(!!plan),
    [history, setHistory] = useState<Plan[]>([]);
  const [libOpen, setLibOpen] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0),
    [working, setWorking] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null),
    [tick, setTick] = useState(0),
    [playing, play] = useState(false),
    [rate, setRate] = useState(2);
  const coachSide = frame.world.match?.clubs.find(c => c.id === frame.world.match?.coachTeamId)?.side;
  const clock = useRef(0),
    version = frame.libraryRevision || 0;
  const request = useRef(0);
  useEffect(() => {
    if (dirty && plan) sessionStorage.setItem(draftKey, JSON.stringify(plan));
    else sessionStorage.removeItem(draftKey);
  }, [plan, dirty]);
  useEffect(() => {
    let live = true;
    readJSON<Library>("/api/tactics")
      .then((data) => {
        if (!live) return;
        setLibrary(data);
        const match = frame.world.match;
        const initial =
          data.plans.find(
            (p) =>
              p.standard &&
              p.side === coachSide &&
              p.buy === match?.nextBuy,
          ) || data.plans.find((p) => p.standard)!;
        setPlan((old) => old || initial);
      })
      .catch((e) => {
        if (live) setError(errorText(e));
      });
    return () => {
      live = false;
    };
  }, [version, retry]);
  useEffect(
    () => () => {
      request.current++;
    },
    [],
  );
  useEffect(() => {
    if (!playing || !preview) return;
    let id = 0,
      last = performance.now();
    const update = (now: number) => {
      clock.current = Math.min(
        preview.frames.length - 1,
        clock.current + (Math.max(0, now - last) * rate) / preview.tickMs,
      );
      last = Math.max(last, now);
      setTick(clock.current);
      if (clock.current < preview.frames.length - 1)
        id = requestAnimationFrame(update);
      else play(false);
    };
    id = requestAnimationFrame(update);
    return () => cancelAnimationFrame(id);
  }, [playing, preview, rate]);
  useEffect(() => {
    const point = /Игрок (\d+), точка (\d+)/.exec(commandNotice || error);
    if (point) {
      setSlot(Number(point[1]) - 1);
      selectIndex(Number(point[2]) - 1);
    }
  }, [commandNotice, error]);
  if (!plan || !library)
    return (
      <section className="board-loading">
        <h1>Редактор тактик</h1>
        {error ? (
          <p role="alert">
            {error}{" "}
            <button
              onClick={() => {
                setError("");
                setRetry((v) => v + 1);
              }}
            >
              Повторить
            </button>
          </p>
        ) : (
          <p>Загрузка библиотеки…</p>
        )}
        <button onClick={onClose}>Вернуться</button>
      </section>
    );
  const map = library.maps.find((m) => m.id === plan.map)!;
  const steps = plan.slots[slot],
    chosen = index === null ? null : steps[index],
    match = frame.world.match;
  const assignable =
    match &&
    ((match.pregame && !frame.running) ||
      (match.phase === "timeout" &&
        coachSide === plan.side &&
        match.nextBuy === plan.buy));
  const stale =
    plan.revision > 0 &&
    !library.plans.some(
      (p) => p.id === plan.id && p.revision === plan.revision,
    );
  const canDiscard = () =>
    !dirty || window.confirm("Закрыть черновик без сохранения изменений?");
  function stopPreview() {
    request.current++;
    play(false);
    setPreview(null);
    clock.current = 0;
    setTick(0);
  }
  function open(p: Plan, changed = false) {
    clearNotice();
    stopPreview();
    setPlan(p);
    setDirty(changed);
    setHistory([]);
    selectIndex(null);
    setReplace(false);
    setSlot(0);
    setTool("move");
    setLibOpen(false);
    setError("");
    setNotice("");
  }
  function edit(p: Plan) {
    clearNotice();
    stopPreview();
    setHistory((h) => [...h.slice(-24), plan!]);
    if (p.standard)
      p = {
        ...p,
        id: crypto.randomUUID(),
        standard: false,
        revision: 0,
        name: p.name + " · копия",
      };
    setPlan(p);
    setDirty(true);
    setError("");
    setNotice("");
  }
  function changeSteps(next: Step[]) {
    edit({
      ...plan!,
      slots: plan!.slots.map((s, i) => (i === slot ? next : s)),
    });
  }
  function draw(points: Point[]) {
    if (working || tool === "pan" || tool === "select") return;
    if (
      tool === "plant" &&
      !map.zones.some(
        (z) =>
          points[0].x >= z.x &&
          points[0].x < z.x + z.w &&
          points[0].y >= z.y &&
          points[0].y < z.y + z.h,
      )
    ) {
      setError("Для установки выберите площадку A или B.");
      return;
    }
    if (tool === "throw" && plan!.buy === "Эко") {
      setError("В эко-плане закупка гранат недоступна.");
      return;
    }
    const added = points.map((p) => ({
      ...p,
      kind: tool,
      ...(timed(tool) ? { seconds } : {}),
      ...(tool === "throw" ? { utility } : {}),
    }));
    const next = [...steps];
    if (replace && index !== null) next.splice(index, 1, ...added);
    else next.push(...added);
    if (next.length > 96) {
      setError("Для одного игрока можно поставить до 96 точек.");
      return;
    }
    changeSteps(next);
    selectIndex(replace ? index : next.length - 1);
    setReplace(false);
  }
  function pick(i: number, j: number | null) {
    setSlot(i);
    selectIndex(j);
    setReplace(false);
    setError("");
  }
  async function save() {
    if (!plan) return;
    setWorking(true);
    try {
      if (await act("tactic-save", plan)) {
        setPlan({ ...plan, revision: plan.revision + 1 });
        setDirty(false);
        setHistory([]);
        setNotice("Сохранено в библиотеке");
        setError("");
      }
    } finally {
      setWorking(false);
    }
  }
  async function remove() {
    if (
      !plan ||
      !window.confirm("Удалить тактику «" + plan.name + "» из библиотеки?")
    )
      return;
    setWorking(true);
    try {
      if (
        await act("tactic-delete", { id: plan.id, revision: plan.revision })
      ) {
        open(library!.plans.find((p) => p.standard)!);
        setNotice("Тактика удалена");
      }
    } finally {
      setWorking(false);
    }
  }
  async function proposal() {
    if (!canDiscard()) return;
    setWorking(true);
    try {
      const p = await readJSON<Plan>(
        "/api/tactics/proposal?" +
          new URLSearchParams({ side: plan!.side, buy: plan!.buy }),
      );
      open(
        { ...p, id: crypto.randomUUID(), revision: 0, standard: false },
        true,
      );
      setNotice("План штаба готов к редактированию");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setWorking(false);
    }
  }
  async function spar() {
    const token = ++request.current;
    setWorking(true);
    setError("");
    setNotice("");
    try {
      const result = await readJSON<Preview>("/api/tactics/preview", plan);
      if (token === request.current) {
        setPreview(result);
        clock.current = 0;
        setTick(0);
        play(true);
      }
    } catch (e) {
      if (token === request.current) setError(errorText(e));
    } finally {
      setWorking(false);
    }
  }
  function copy() {
    open(
      {
        ...plan!,
        id: crypto.randomUUID(),
        revision: 0,
        standard: false,
        name: plan!.name.slice(0, 55) + " · копия",
      },
      true,
    );
  }
  const disabled = working || !enabled;
  const previewEvent = preview?.events.filter((e) => e.tick <= tick).at(-1);
  return (
    <article className="tactics">
      <header className="board-title">
        <div>
          <span className="eyebrow">ТРЕНЕРСКАЯ · СЕВЕР</span>
          <h1>Редактор тактик</h1>
        </div>
        <div className="board-buttons">
          <button
            onClick={() => {
              if (canDiscard()) {
                sessionStorage.removeItem(draftKey);
                onClose();
              }
            }}
          >
            ← {match ? "К матчу" : "К радару"}
          </button>
          <button aria-expanded={libOpen} onClick={() => setLibOpen(!libOpen)}>
            ▤ Библиотека
          </button>
        </div>
      </header>
      {libOpen && (
        <section className="panel board-library">
          <div className="board-section">
            <h2>Библиотека тактик</h2>
            <button onClick={() => setLibOpen(false)}>Закрыть</button>
          </div>
          {[false, true].map((standard) => (
            <section key={String(standard)}>
              <h3>{standard ? "Стандартные" : "Мои тактики"}</h3>
              <div className="board-cards">
                {library.plans
                  .filter((p) => p.standard === standard)
                  .map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        if (canDiscard()) open(p);
                      }}
                    >
                      <b>{p.name}</b>
                      <small>
                        {p.side} · {p.buy} · в{p.revision}
                      </small>
                    </button>
                  ))}
              </div>
              {!library.plans.some((p) => p.standard === standard) && (
                <p>Сохранённые планы появятся здесь.</p>
              )}
            </section>
          ))}
        </section>
      )}
      <fieldset className="board-fieldset" disabled={working}>
        <div className="board-grid">
          <section className="panel board-map-panel">
            <div className="board-section">
              <div>
                <small>
                  {map.name.toUpperCase()} · {plan.side} ·{" "}
                  {plan.buy.toUpperCase()}
                </small>
                <h2>{plan.name || "Без названия"}</h2>
              </div>
              <button
                className={preview ? "" : "accent-outline"}
                disabled={disabled}
                onClick={preview ? stopPreview : spar}
              >
                {preview ? "К редактированию" : "▷ Предпросмотр"}
              </button>
            </div>
            <div className="board-players" aria-label="Выбор игрока">
              {library.roles.map((role, i) => (
                <button
                  key={role}
                  aria-label={
                    "Игрок " +
                    (i + 1) +
                    " · " +
                    library.players[i] +
                    " · " +
                    role
                  }
                  aria-pressed={slot === i}
                  onClick={() => pick(i, null)}
                >
                  <b style={{ background: colors[i] }}>{i + 1}</b>
                  <span>
                    {library.players[i]}
                    <small>{role}</small>
                  </span>
                </button>
              ))}
            </div>
            <TacticMap
              map={map}
              plan={plan}
              slot={slot}
              tool={tool}
              selected={index}
              preview={preview}
              tick={tick}
              onPick={pick}
              onDraw={draw}
              onError={setError}
            />
            {preview ? (
              <div className="board-preview">
                <strong>Спарринг · один раунд против «Контура»</strong>
                <span>
                  Seed 42 · {plan.buy} · {Math.floor(tick / 10)} с
                </span>
                <div className="board-buttons">
                  <button
                    onClick={() => {
                      if (tick >= preview.frames.length - 1) {
                        clock.current = 0;
                        setTick(0);
                      }
                      play(!playing);
                    }}
                  >
                    {playing ? "Пауза" : "Воспроизвести"}
                  </button>
                  <input
                    aria-label="Время спарринга"
                    type="range"
                    min={0}
                    max={preview.frames.length - 1}
                    value={Math.floor(tick)}
                    onChange={(e) => {
                      clock.current = +e.target.value;
                      setTick(clock.current);
                    }}
                  />
                  <select
                    aria-label="Скорость спарринга"
                    value={rate}
                    onChange={(e) => setRate(+e.target.value)}
                  >
                    {[1, 2, 4, 8].map((v) => (
                      <option key={v} value={v}>
                        {v}×
                      </option>
                    ))}
                  </select>
                </div>
                <p>{previewEvent?.text || "Начало раунда"}</p>
              </div>
            ) : (
              <>
                <div className="board-tools" aria-label="Инструменты доски">
                  {tools.map((t) => (
                    <button
                      key={t}
                      disabled={t === "plant" && plan.side !== "T"}
                      aria-pressed={tool === t}
                      onClick={() => {
                        setTool(t);
                        if (t === "pan" || t === "select") setReplace(false);
                        setError("");
                      }}
                    >
                      <i>{symbols[t]}</i>
                      {toolNames[t]}
                    </button>
                  ))}
                </div>
                <div className="board-hint">
                  {timed(tool) && (
                    <label>
                      Длительность{" "}
                      <select
                        value={seconds}
                        onChange={(e) => setSeconds(+e.target.value)}
                      >
                        {Array.from({ length: 30 }, (_, i) => (
                          <option value={i + 1} key={i}>
                            {i + 1} с
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  {tool === "throw" && (
                    <label>
                      Граната{" "}
                      <select
                        value={utility}
                        onChange={(e) => setUtility(e.target.value)}
                      >
                        {["Дым", "Свет", "HE", "Огонь", "Ложная"].map((g) => (
                          <option key={g}>{g}</option>
                        ))}
                      </select>
                    </label>
                  )}
                  <span>
                    {replace ? "Укажите новую точку на карте." : help[tool]}
                  </span>
                </div>
              </>
            )}
            {error && (
              <p role="alert" className="board-error">
                {error}
              </p>
            )}
            {commandNotice && (
              <p role="status" className="board-error">
                {commandNotice}
              </p>
            )}
          </section>
          <aside className="board-side">
            <section className="panel board-sheet">
              <div className="board-section">
                <h2>План команды</h2>
                <small>
                  {dirty
                    ? "Черновик"
                    : plan.standard
                      ? "Стандартный"
                      : "Версия " + plan.revision}
                </small>
              </div>
              <label>
                Название
                <input
                  aria-label="Название тактики"
                  maxLength={64}
                  value={plan.name}
                  onChange={(e) =>
                    edit({
                      ...plan,
                      name: e.target.value,
                      ...(plan.standard
                        ? {
                            standard: false,
                            id: crypto.randomUUID(),
                            revision: 0,
                          }
                        : {}),
                    })
                  }
                />
              </label>
              <div className="board-fields">
                <label>
                  Карта
                  <select
                    value={plan.map}
                    onChange={(e) => {
                      if (canDiscard())
                        open(
                          newPlan(
                            library.maps.find((m) => m.id === e.target.value)!,
                            plan.side,
                            plan.buy,
                          ),
                        );
                    }}
                  >
                    {library.maps.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Сторона
                  <select
                    value={plan.side}
                    onChange={(e) => {
                      if (canDiscard()) {
                        open(newPlan(map, e.target.value as Side, plan.buy));
                        setTool("move");
                      }
                    }}
                  >
                    <option value="T">T · атака</option>
                    <option value="CT">CT · защита</option>
                  </select>
                </label>
              </div>
              <label>
                Закупка
                <select
                  value={plan.buy}
                  onChange={(e) => edit({ ...plan, buy: e.target.value })}
                >
                  {library.buys.map((b) => (
                    <option key={b}>{b}</option>
                  ))}
                </select>
              </label>
              <div className="board-buttons">
                <button
                  onClick={() => {
                    if (canDiscard()) open(newPlan(map, plan.side, plan.buy));
                  }}
                >
                  Новая тактика
                </button>
                <button disabled={disabled} onClick={proposal}>
                  Предложение штаба
                </button>
              </div>
              <button
                className="primary"
                disabled={disabled || !dirty}
                onClick={save}
              >
                Сохранить тактику
              </button>
              <div className="board-buttons">
                <button onClick={copy}>Создать копию</button>
                <button
                  disabled={disabled || plan.standard || !plan.revision}
                  onClick={remove}
                >
                  Удалить
                </button>
              </div>
              {plan.revision > 0 && !plan.standard && !dirty && (
                <small>
                  Освоение версии {plan.revision} · {plan.familiarity || 0}%
                </small>
              )}
              {stale && (
                <p role="alert" className="board-error">
                  В библиотеке другая версия. Откройте её или сохраните черновик
                  как копию.
                </p>
              )}
              {notice && (
                <p role="status" className="board-success">
                  {notice}
                </p>
              )}
              {match && (
                <div className="board-assign">
                  <button
                    disabled={
                      disabled ||
                      !assignable ||
                      dirty ||
                      !plan.revision ||
                      stale
                    }
                    onClick={async () => {
                      if (
                        await act("tactic-assign", {
                          id: plan.id,
                          revision: plan.revision,
                        })
                      )
                        setNotice(
                          "Тактика назначена · " +
                            plan.name +
                            " · в" +
                            plan.revision,
                        );
                    }}
                  >
                    Назначить в BO1
                  </button>
                  <small>
                    {match.pregame
                      ? "До старта можно подготовить план для каждой стороны и закупки."
                      : match.phase === "timeout"
                        ? "Ближайший раунд · " +
                          coachSide +
                          " · " +
                          match.nextBuy
                        : "Назначение откроется в свой тактический тайм-аут."}
                  </small>
                </div>
              )}
            </section>
            <section className="panel board-sequence">
              <div className="board-section">
                <h2>
                  Маршрут №{slot + 1} · {library.players[slot]}
                </h2>
                <small>{steps.length} точ.</small>
              </div>
              <ol>
                {steps.map((s, j) => (
                  <li key={j}>
                    <button
                      aria-pressed={index === j}
                      onClick={() => {
                        selectIndex(j);
                        setReplace(false);
                      }}
                    >
                      <i>{j + 1}</i>
                      <span>
                        {labels[s.kind]} {s.utility || ""}
                      </span>
                      <small>
                        {s.seconds ? s.seconds + " с · " : ""}
                        {s.x}, {s.y}
                      </small>
                    </button>
                  </li>
                ))}
              </ol>
              {!steps.length && (
                <p>
                  Коснитесь свободной клетки на карте, чтобы начать маршрут.
                </p>
              )}
              {chosen && index !== null && (
                <div className="board-buttons">
                  <button
                    onClick={() => {
                      stopPreview();
                      setReplace(true);
                      setTool(chosen.kind);
                      setSeconds(chosen.seconds || 3);
                      setUtility(chosen.utility || "Дым");
                    }}
                  >
                    Переставить
                  </button>
                  <button
                    onClick={() => {
                      changeSteps(steps.filter((_, i) => i !== index));
                      selectIndex(null);
                      setReplace(false);
                    }}
                  >
                    Убрать точку
                  </button>
                </div>
              )}
              <button
                disabled={!history.length}
                onClick={() => {
                  stopPreview();
                  const prior = history[history.length - 1];
                  setPlan(prior);
                  setDirty(!prior.revision || history.length > 1);
                  setHistory(history.slice(0, -1));
                  selectIndex(null);
                  setReplace(false);
                }}
              >
                ↶ Отменить правку
              </button>
            </section>
          </aside>
        </div>
      </fieldset>
    </article>
  );
}
