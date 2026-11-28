import { useState } from "react";
import {
  date,
  dayAt,
  isoDay,
  monday,
  useData,
  weekdays,
  type Act,
  type Career,
  type Fixture,
} from "./careerData";
import { roles, skillLabels } from "./databaseModel";
import { Dialog, Heading, Tabs } from "./GameUI";
import { Load, MatchReport } from "./CareerForms";
import "./training.css";

type Board = {
  id: string;
  revision: number;
  name: string;
  side: string;
  map: string;
};
type Session = {
  insight?: string;
  changes?: Record<string, Record<string, number>>;
  kind: string;
  player?: string;
  map?: string;
  tactic?: Board;
  opponent?: string;
  match?: string;
  quality?: number;
  specialist?: string;
};
type Practice = Fixture & {
  goal: string;
  watch: boolean;
  cancelled?: string;
  result?: string;
  rounds?: number;
  sides?: Record<string, number>;
  stats?: {
    player: string;
    name: string;
    k: number;
    d: number;
    damage: number;
  }[];
};
type Day = {
  date: string;
  sessions: Session[];
  official: boolean;
  manual: boolean;
  practices: Practice[];
  fatigue: Record<string, number>;
};
type Program = {
  skills: string[];
  maps: string[];
  role: string;
  intensity: number;
  coach: string | null;
};
type Athlete = {
  plannedLoad:number;
  metrics: { load?: number; recovery?: number };
  fatigue: number;
  practice: number;
  trend: [string, number][];
  skills: Record<string, number>;
  maps: Record<string, number>;
  roles: Record<string, number>;
  tactics: Record<string, number>;
};
export type TrainingState = {
  initial: Record<string, Record<string, number>>;
  days: Day[];
  players: Record<string, Athlete>;
  maps: string[];
  catalog: Record<string, [string, string, number, string | null, string]>;
  programs: Record<string, Program>;
  templates: string[];
  boards: Board[];
  teams: string[];
  history: Record<string, Record<string, Record<string, number>>>;
};
const screens = [
  "Расписание",
  "Индивидуальная подготовка",
  "Нагрузка",
  "Карты и тактики",
  "Пракки",
  "Отчёты",
  "Делегирование",
];
const slots = ["Утро", "День", "Вечер"];
const mapName = (s: string) =>
  s === "depo"
    ? "Депо"
    : s.replace(/^de_/, "").replace(/^./, (c) => c.toUpperCase());
const boardKey = (b: Board) => b.id + "@" + b.revision;
type Shared = {
  c: Career;
  data: TrainingState;
  enabled: boolean;
  submit: (v: object) => Promise<boolean>;
};
type Edit = { day: Day; index: number };

function SessionEditor({
  c,
  data,
  edit,
  enabled,
  submit,
  close,
  reason,
}: Shared & { edit: Edit; close: () => void; reason: string }) {
  const row = edit.day.sessions[edit.index];
  const [kind, setKind] = useState(row?.kind || "mechanics");
  const [who, setWho] = useState(row?.player || "");
  const [map, setMap] = useState(row?.map || data.maps[0]);
  const [board, setBoard] = useState(row?.tactic ? boardKey(row.tactic) : "");
  const [opponent, setOpponent] = useState(row?.opponent || data.teams[0]);
  const matches = c.history.filter((e) => e.teams.includes(c.team)).reverse();
  const [match, setMatch] = useState(row?.match || matches[0]?.id || "");

  const [, goal, load, competency, targets] = data.catalog[kind];
  const available = data.boards.filter(
    (b) =>
      b.map === map &&
      (kind !== "attack" || b.side === "T") &&
      (kind !== "defense" || b.side === "CT"),
  );
  const onMap = [
    "map",
    "attack",
    "defense",
    "team",
    "retake",
    "utility",
  ].includes(kind);
  return (
    <Dialog title="Редактор занятия" close={close}>
      <form
        className="training-form"
        onSubmit={async (e) => {
          e.preventDefault();
          if (
            await submit({
              action: "session",
              date: edit.day.date,
              index: edit.index,
              kind,
              player: who || null,
              map: onMap ? map : null,
              tactic: onMap
                ? available.find((b) => boardKey(b) === board)
                : null,
              opponent,
              match,
            })
          )
            close();
        }}
      >
        <p>
          {date(edit.day.date)} · {slots[edit.index]}
        </p>
        <label>
          Направление
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setBoard("");
              if (e.target.value === "program" && !who) setWho(c.roster[0].id);
            }}
          >
            {Object.entries(data.catalog)
              .filter(([id]) => id !== "pcw")
              .map(([id, [label]]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
          </select>
        </label>
        <p className="training-goal">{goal}</p>
        <label>
          Участники
          <select value={who} onChange={(e) => setWho(e.target.value)}>
            {kind !== "program" && <option value="">Вся команда</option>}
            {c.roster.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </label>
        {onMap && (
          <label>
            Карта
            <select
              value={map}
              onChange={(e) => {
                setMap(e.target.value);
                setBoard("");
              }}
            >
              {data.maps.map((m) => (
                <option key={m} value={m}>
                  {mapName(m)}
                </option>
              ))}
            </select>
          </label>
        )}
        {["attack", "defense", "retake", "team"].includes(kind) && (
          <label>
            Тактика из библиотеки
            <select value={board} onChange={(e) => setBoard(e.target.value)}>
              <option value="">Общие принципы</option>
              {available.map((b) => (
                <option key={boardKey(b)} value={boardKey(b)}>
                  {b.name} · {b.side} · в{b.revision}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "opponent" && (
          <label>
            Изучаемый соперник
            <select
              value={opponent}
              onChange={(e) => setOpponent(e.target.value)}
            >
              {data.teams.map((t) => (
                <option key={t} value={t}>
                  {c.teams[t]}
                </option>
              ))}
            </select>
          </label>
        )}
        {kind === "review" && (
          <label>
            Матч для разбора
            <select value={match} onChange={(e) => setMatch(e.target.value)}>
              {!matches.length && (
                <option value="">Сыгранных встреч пока нет</option>
              )}
              {matches.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.date} · {f.teams.map((t) => c.teams[t]).join(" — ")}
                </option>
              ))}
            </select>
          </label>
        )}
        <dl className="training-facts">
          <dt>Нагрузка</dt>
          <dd>{load}</dd>
          {competency && (
            <>
              <dt>Компетенция штаба</dt>
              <dd>
                {
                  Object.assign({}, ...Object.values(c.office.groups))[
                    competency
                  ]
                }
              </dd>
            </>
          )}
          {kind === "program" && (
            <>
              <dt>Характеристики</dt>
              <dd>По индивидуальной программе игрока</dd>
            </>
          )}
          {targets && kind !== "program" && (
            <>
              <dt>Характеристики</dt>
              <dd>
                {targets
                  .split(" ")
                  .map((k) => skillLabels[k])
                  .join(", ")}
              </dd>
            </>
          )}
        </dl>
        {reason && <p role="alert">{reason}</p>}
        <div className="training-actions">
          <button
            className="btn primary"
            disabled={!enabled || (kind === "review" && !match)}
          >
            Сохранить занятие
          </button>
          {row && (
            <button
              type="button"
              className="btn"
              disabled={!enabled}
              onClick={async () => {
                if (
                  await submit({
                    action: "remove",
                    date: edit.day.date,
                    index: edit.index,
                  })
                )
                  close();
              }}
            >
              Убрать занятие
            </button>
          )}
        </div>
      </form>
    </Dialog>
  );
}

function PlayerProgram({
  c,
  data,
  pid,
  enabled,
  submit,
}: Shared & { pid: string }) {
  const player = c.roster.find((p) => p.id === pid)!;
  const [form, set] = useState<Program>(
    data.programs[pid] || {
      role: player.role,
      skills: [],
      maps: [],
      intensity: 1,
      coach: null,
    },
  );
  const choose = (key: "maps", value: string) => {
    const list = form[key];
    set({
      ...form,
      [key]: list.includes(value)
        ? list.filter((s) => s !== value)
        : [...list, value],
    });
  };
  return (
    <section className="surface panel-body">
      <h2>Программа · {player.name}</h2>
      <form
        className="training-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit({ action: "program", player: pid, ...form });
        }}
      >
        <div className="training-fields">
          <label>
            Осваиваемая роль
            <select
              value={form.role}
              onChange={(e) => set({ ...form, role: e.target.value })}
            >
              {Object.entries(roles).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            Интенсивность
            <select
              value={form.intensity}
              onChange={(e) =>
                set({ ...form, intensity: Number(e.target.value) })
              }
            >
              <option value={0.65}>Щадящая</option>
              <option value={1}>Обычная</option>
              <option value={1.25}>Высокая</option>
            </select>
          </label>
          <label>
            Ответственный специалист
            <select
              value={form.coach || ""}
              onChange={(e) => set({ ...form, coach: e.target.value || null })}
            >
              <option value="">По назначению штаба</option>
              {Object.values(c.office.people).map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <fieldset>
          <legend>Приоритетные карты · до трёх</legend>
          <div className="training-checks">
            {data.maps.map((k) => (
              <label key={k}>
                <input
                  type="checkbox"
                  checked={form.maps.includes(k)}
                  disabled={!form.maps.includes(k) && form.maps.length >= 3}
                  onChange={() => choose("maps", k)}
                />
                {mapName(k)}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend>Приоритетные характеристики</legend>
          <div className="training-fields">
            {[0, 1, 2].map((i) => (
              <label key={i}>
                Приоритет {i + 1}
                <select
                  aria-label={"Приоритет "+(i+1)}
                  value={form.skills[i] || ""}
                  onChange={(e) => {
                    const next = [...form.skills];
                    next[i] = e.target.value;
                    set({ ...form, skills: next.filter(Boolean) });
                  }}
                >
                  <option value="">По игровой роли</option>
                  {Object.keys(player.skills).map((k) => (
                    <option
                      key={k}
                      value={k}
                      disabled={form.skills.includes(k) && form.skills[i] !== k}
                    >
                      {skillLabels[k]}
                    </option>
                  ))}
                </select>
              </label>
            ))}
          </div>
        </fieldset>
        <button className="btn primary" disabled={!enabled}>
          Сохранить программу
        </button>
      </form>
    </section>
  );
}

function PracticeDesk({ c, data, enabled, submit }: Shared) {
  const [opponent, setOpponent] = useState(data.teams[0]),
    [day, setDay] = useState(c.date),
    [map, setMap] = useState(data.maps[0]);
  const [goal, setGoal] = useState("synergy"),
    [games, setGames] = useState(1),
    [watch, setWatch] = useState(false),
    [tactic, setTactic] = useState("");
  return (
    <section className="surface panel-body">
      <h2>Организовать пракк</h2>
      <form
        className="training-form"
        onSubmit={(e) => {
          e.preventDefault();
          void submit({
            action: "pcw",
            date: day,
            opponent,
            map,
            goal,
            games,
            watch,
            tactic: data.boards.find((b) => boardKey(b) === tactic),
          });
        }}
      >
        <div className="training-fields">
          <label>
            Соперник
            <select
              value={opponent}
              onChange={(e) => setOpponent(e.target.value)}
            >
              {data.teams.map((t) => (
                <option key={t} value={t}>
                  {c.teams[t]}
                </option>
              ))}
            </select>
          </label>
          <label>
            Дата пракка
            <input
              type="date"
              min={c.date}
              value={day}
              onChange={(e) => setDay(e.target.value)}
              required
            />
          </label>
          <label>
            Карта пракка
            <select
              value={map}
              onChange={(e) => {
                setMap(e.target.value);
                setTactic("");
              }}
            >
              {data.maps.map((m) => (
                <option key={m} value={m}>
                  {mapName(m)}
                </option>
              ))}
            </select>
          </label>
          <label>
            Формат
            <select
              value={games}
              onChange={(e) => setGames(Number(e.target.value))}
            >
              <option value={1}>Одна карта</option>
              <option value={2}>Две игры со сменой сторон</option>
            </select>
          </label>
          <label>
            Цель подготовки
            <select value={goal} onChange={(e) => setGoal(e.target.value)}>
              {["synergy", "attack", "defense", "retake", "utility"].map(
                (k) => (
                  <option key={k} value={k}>
                    {data.catalog[k][0]}
                  </option>
                ),
              )}
            </select>
          </label>
          <label>
            Тактика
            <select value={tactic} onChange={(e) => setTactic(e.target.value)}>
              <option value="">Без отдельного плана</option>
              {data.boards
                .filter((b) => b.map === map)
                .map((b) => (
                  <option key={boardKey(b)} value={boardKey(b)}>
                    {b.name} · {b.side}
                  </option>
                ))}
            </select>
          </label>
        </div>
        <label className="training-check">
          <input
            type="checkbox"
            checked={watch}
            onChange={(e) => setWatch(e.target.checked)}
          />
          Наблюдать в матч-центре
        </label>
        <button className="btn primary" disabled={!enabled}>
          Назначить пракк
        </button>
      </form>
    </section>
  );
}

function Scale({ value }: { value: number }) {
  return (
    <span className="training-scale">
      <meter min="0" max="100" value={value} />
      <b>{value.toFixed(1)}</b>
    </span>
  );
}

function PracticeRow({
  p,
  c,
  data,
  enabled,
  submit,
}: Shared & { p: Practice }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="training-practice">
      <strong>{p.teams.map((t) => c.teams[t]).join(" — ")}</strong>
      <span>
        {p.date} · {mapName(p.mapId || "depo")} · {data.catalog[p.goal]?.[0]} ·{" "}
        {p.cancelled || (p.watch ? "Просмотр" : "По раундам")}
      </span>
      {!p.score && !p.cancelled && (
        <button
          className="btn sm"
          disabled={!enabled}
          onClick={() =>
            void submit({ action: "watch-pcw", date: p.date, id: p.id })
          }
        >
          {p.watch ? "Рассчитать в фоне" : "Наблюдать пракк"}
        </button>
      )}
      {p.score ? (
        <>
          <b>
            {p.score.join(" : ")} · {p.rounds} раундов
          </b>
          <details>
            <summary>Результаты по игрокам</summary>
            <p>
              Победы за T · {p.sides?.T} / за CT · {p.sides?.CT}
            </p>
            {p.stats?.map((s) => (
              <p key={s.player}>
                {s.name} · {s.k}/{s.d} · урон {s.damage}
              </p>
            ))}
          </details>
          {p.result && (
            <button className="btn sm" onClick={() => setOpen(true)}>
              Протокол пракка
            </button>
          )}
        </>
      ) : (
        !p.cancelled && (
          <button
            className="btn sm"
            disabled={!enabled}
            onClick={() =>
              void submit({ action: "cancel-pcw", date: p.date, id: p.id })
            }
          >
            Отменить пракк
          </button>
        )
      )}
      {open && (
        <Dialog title="Отчёт по пракку" close={() => setOpen(false)}>
          <MatchReport careerId={c.id} event={p} teams={c.teams} close={() => setOpen(false)} />
        </Dialog>
      )}
    </article>
  );
}

export function TrainingCenter({
  c,
  enabled,
  act,
  revision,
  initial,
  reports,
}: {
  c: Career;
  enabled: boolean;
  act: Act;
  revision: number;
  initial?: string;
  reports?: boolean;
}) {
  const [week, setWeek] = useState(monday(initial || c.date)),
    [tab, setTab] = useState(reports ? "Отчёты" : screens[0]);
  const [day, setDay] = useState(initial || c.date);
  const [pid, setPid] = useState(c.roster[0].id),
    [edit, setEdit] = useState<Edit | null>(null);
  const [name, setName] = useState(""),
    [template, setTemplate] = useState(""),
    [message, setMessage] = useState("");
  const [pending, setPending] = useState(false),
    [fault, setFault] = useState(false),
    [focus, setFocus] = useState("aim");
  const response = useData<TrainingState>(
    "/api/career/" + c.id + "/training?week=" + week,
    revision,
  );
  if (!response.data || response.error) return <Load {...response} />;
  const data = response.data;
  const allowed = enabled && !pending && response.revision === revision;
  async function send(kind: string, value: object) {
    setPending(true);
    setMessage("");
    setFault(false);
    try {
      const ok = await act(kind, value, (reason) => {
        setFault(true);
        setMessage(reason);
      });
      if (ok) setMessage("Изменения сохранены");
      return ok;
    } finally {
      setPending(false);
    }
  }
  const shared = {
    c,
    data,
    enabled: allowed,
    submit: (value: object) => send("career-training", value),
  };
  const player = data.players[pid];
  const who = (
    <label>
      Игрок
      <select value={pid} onChange={(e) => setPid(e.target.value)}>
        {c.roster.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
  const activeDay = data.days.find(d=>d.date===day) || data.days[0];
  const changeWeek = (d: number) => setWeek(isoDay(dayAt(week, d)));
  const navigator = (
    <div className="training-week">
      <button
        className="btn sm"
        aria-label="Предыдущая неделя"
        onClick={() => changeWeek(-7)}
      >
        ←
      </button>
      <strong>
        {date(week)} — {date(isoDay(dayAt(week, 6)))}
      </strong>
      <button
        className="btn sm"
        aria-label="Следующая неделя"
        onClick={() => changeWeek(7)}
      >
        →
      </button>
      <button className="btn sm" onClick={() => setWeek(monday(c.date))}>
        Текущая неделя
      </button>
    </div>
  );
  return (
    <div className="training-center">
      <Heading title="Тренировки" eyebrow={c.club+" / Подготовка"} sub="Расписание, индивидуальная подготовка и пракки">
        <button className="btn primary" disabled={!allowed || !activeDay || activeDay.date<c.date || activeDay.sessions.length+activeDay.practices.filter(p=>!p.cancelled).length>=3}
          onClick={()=>activeDay && setEdit({day:activeDay,index:activeDay.sessions.length})}>Добавить тренировку</button></Heading>
      {activeDay && <div className="training-brief"><strong>{date(activeDay.date)}</strong><span>{activeDay.official?"Матч / турнир":"Тренировочный день"} · занятий {activeDay.sessions.length}</span></div>}
      <div className="training-nav">
        <Tabs
          items={screens}
          value={tab}
          change={(t) => {
            setTab(t);
            setMessage("");
          }}
        />
        <label>
          Раздел центра
          <select
            value={tab}
            onChange={(e) => {
              setTab(e.target.value);
              setMessage("");
            }}
          >
            {screens.map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </label>
      </div>
      {message && (
        <p
          role={fault ? "alert" : "status"}
          className={fault ? "training-error" : "training-status"}
        >
          {message}
        </p>
      )}
      {tab === "Расписание" && (
        <>
          {navigator}
          <nav className="training-day-picker" aria-label="Выбор дня тренировки">
            {data.days.map((d,i) => <button key={d.date} aria-pressed={d.date===activeDay?.date}
              aria-label={date(d.date)} onClick={()=>setDay(d.date)}><span>{weekdays[i].slice(0,2)}</span><b>{d.date.slice(8)}</b></button>)}
          </nav>
          <div className="training-week-grid">
            {data.days.map((d, i) => (
              <section
                className="surface training-day"
                key={d.date}
                data-today={d.date === c.date}
                data-selected={d.date === activeDay?.date}
              >
                <header>
                  <h2>{weekdays[i]}</h2>
                  <time>
                    {d.date.slice(8)}.{d.date.slice(5, 7)}
                  </time>
                </header>
                {d.official && (
                  <strong className="training-official">Матч / турнир</strong>
                )}
                {d.practices
                  .filter((p) => !p.cancelled)
                  .map((p) => (
                    <span className="training-official" key={p.id}>
                      Пракк · {c.teams[p.teams.find((t) => t !== c.team)!]}
                    </span>
                  ))}
                {d.sessions.map((s, j) => (
                  <button
                    className="training-block"
                    key={j}
                    disabled={!allowed || d.date < c.date}
                    onClick={() => setEdit({ day: d, index: j })}
                  >
                    <small>
                      {slots[j]} ·{" "}
                      {s.player
                        ? c.roster.find((p) => p.id === s.player)?.name
                        : "Команда"}
                    </small>
                    <b>{data.catalog[s.kind][0]}</b>
                    <span>
                      {s.map && mapName(s.map) + " · "}нагрузка{" "}
                      {data.catalog[s.kind][2]}
                    </span>
                    {s.tactic && <span>{s.tactic.name}</span>}
                  </button>
                ))}
                {d.date >= c.date &&
                  d.sessions.length +
                    d.practices.filter((p) => !p.cancelled).length <
                    3 && (
                    <button
                      className="btn sm"
                      aria-label={"Добавить занятие " + d.date}
                      disabled={!allowed}
                      onClick={() =>
                        setEdit({ day: d, index: d.sessions.length })
                      }
                    >
                      + Занятие
                    </button>
                  )}
                {d.manual && (
                  <button
                    className="link-button"
                    disabled={!allowed}
                    onClick={() =>
                      void shared.submit({ action: "auto", date: d.date })
                    }
                  >
                    Вернуть план штаба
                  </button>
                )}
                {!d.sessions.length && d.date < c.date && (
                  <small>Нет занятий</small>
                )}
              </section>
            ))}
          </div>
          <section className="surface panel-body">
            <h2>Шаблоны недели</h2>
            <div className="training-fields">
              <label>
                Название шаблона
                <input
                  maxLength={48}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <button
                className="btn"
                disabled={!allowed || !name.trim()}
                onClick={() =>
                  void shared.submit({ action: "template", date: week, name })
                }
              >
                Сохранить неделю
              </button>
              <label>
                Сохранённая неделя
                <select
                  value={template}
                  onChange={(e) => setTemplate(e.target.value)}
                >
                  <option value="">Выберите шаблон</option>
                  {data.templates.map((n) => (
                    <option key={n}>{n}</option>
                  ))}
                </select>
              </label>
              <button
                className="btn"
                disabled={!allowed || !template || data.days[6].date < c.date}
                onClick={() =>
                  void shared.submit({
                    action: "apply",
                    date: week,
                    name: template,
                  })
                }
              >
                Применить шаблон
              </button>
            </div>
          </section>
          {edit && (
            <SessionEditor
              {...shared}
              reason={fault ? message : ""}
              edit={edit}
              close={() => setEdit(null)}
            />
          )}
        </>
      )}
      {tab === "Индивидуальная подготовка" && (
        <>
          {who}
          <PlayerProgram key={pid} {...shared} pid={pid} />
          <section className="surface panel-body">
            <h2>Динамика характеристик</h2>
            <label>
              Характеристика
              <select value={focus} onChange={(e) => setFocus(e.target.value)}>
                {Object.keys(player.skills).map((k) => (
                  <option value={k} key={k}>
                    {skillLabels[k]}
                  </option>
                ))}
              </select>
            </label>
            <p>
              С начала карьеры · {player.skills[focus] > 0 ? "+" : ""}
              {player.skills[focus]}
            </p>
            {Object.entries(data.history)
              .slice(-12)
              .map(([d, rows]) => (
                <div className="staff-line" key={d}>
                  <time>{date(d)}</time>
                  <Scale
                    value={rows[pid]?.[focus] ?? data.initial[pid][focus]}
                  />
                </div>
              ))}
          </section>
        </>
      )}
      {tab === "Нагрузка" && (
        <div className="training-cards">
          {c.roster.map((p) => {
            const a = data.players[p.id],
              trend = a.trend,
              prev = trend.at(-2)?.[1];
            return (
              <section className="surface panel-body" key={p.id}>
                <h2>{p.name}</h2>
                <div className="staff-line">
                  Усталость <Scale value={a.fatigue} />
                </div>
                <p>Плановая нагрузка сегодня · {a.plannedLoad}</p>
                <p>Игровая практика · {a.practice.toFixed(1)} / 40</p>
                {a.metrics.load !== undefined && (
                  <p>
                    Последний день · нагрузка {a.metrics.load.toFixed(1)} ·
                    восстановлено {a.metrics.recovery?.toFixed(1)}
                  </p>
                )}
                <p>
                  {a.fatigue >= 60
                    ? "Рекомендация штаба · назначить восстановление"
                    : a.practice < 3
                      ? "Рекомендация штаба · запланировать пракк"
                      : "Рекомендация штаба · сохранить текущий режим"}
                </p>
                {prev !== undefined && (
                  <p>Изменение за день · {(a.fatigue - prev).toFixed(1)}</p>
                )}
                {!!trend.length && (
                  <details>
                    <summary>Усталость по дням</summary>
                    {trend.map(([d, v]) => (
                      <div className="staff-line" key={d}>
                        <time>{date(d)}</time>
                        <Scale value={v} />
                      </div>
                    ))}
                  </details>
                )}
              </section>
            );
          })}
        </div>
      )}
      {tab === "Карты и тактики" && (
        <>
          {who}
          <div className="training-cards">
            {[
              ["Карты", player.maps, mapName],
              ["Освоение ролей", player.roles, (k: string) => roles[k] || k],
              [
                "Тактики",
                player.tactics,
                (k: string) =>
                  data.boards.find((b) => boardKey(b) === k)?.name || k,
              ],
            ].map(([title, values, label]) => (
              <section className="surface panel-body" key={String(title)}>
                <h2>{String(title)}</h2>
                {Object.entries(values as Record<string, number>).map(
                  ([k, v]) => (
                    <div className="staff-line" key={k}>
                      {(label as (s: string) => string)(k)}
                      <Scale value={v} />
                    </div>
                  ),
                )}
                {!Object.keys(values).length && (
                  <p>Пока нет освоенных тактик.</p>
                )}
              </section>
            ))}
          </div>
        </>
      )}
      {tab === "Пракки" && (
        <>
          <PracticeDesk {...shared} />
          {navigator}
          <section className="surface panel-body">
            <h2>Пракки недели</h2>
            {data.days
              .flatMap((d) => d.practices)
              .map((p) => (
                <PracticeRow key={p.id} {...shared} p={p} />
              ))}
            {data.days.every((d) => !d.practices.length) && (
              <p>На эту неделю пракки не назначены.</p>
            )}
          </section>
        </>
      )}
      {tab === "Отчёты" && (
        <>
          {navigator}
          <div className="training-cards">
            {data.days
              .filter(
                (d) =>
                  (d.date < c.date && d.sessions.length) ||
                  d.practices.some((p) => p.score || p.cancelled),
              )
              .map((d) => (
                <section className="surface panel-body" key={d.date}>
                  <h2>{date(d.date)}</h2>
                  {d.sessions
                    .filter((s) => s.quality !== undefined)
                    .map((s, i) => (
                      <div className="training-log" key={i}>
                        <strong>{data.catalog[s.kind][0]}</strong>
                        <p>
                          {s.player
                            ? c.roster.find((p) => p.id === s.player)?.name
                            : "Команда"}{" "}
                          · {s.specialist || "Самостоятельно"} · качество{" "}
                          {s.quality}/100
                        </p>
                        {s.insight && <p>{s.insight}</p>}
                        {s.changes && Object.keys(s.changes).length > 0 && (
                          <details>
                            <summary>Изменение характеристик</summary>
                            {Object.entries(s.changes).map(([id, values]) => (
                              <p key={id}>
                                <b>
                                  {c.roster.find((p) => p.id === id)?.name ||
                                    id}
                                </b>{" "}
                                ·{" "}
                                {Object.entries(values)
                                  .map(([k, v]) => skillLabels[k] + " +" + v)
                                  .join(", ")}
                              </p>
                            ))}
                          </details>
                        )}
                        {s.match && <small>Матч · {s.match}</small>}
                        {s.opponent && (
                          <small>Соперник · {c.teams[s.opponent]}</small>
                        )}
                      </div>
                    ))}
                  {d.practices.map((p) => (
                    <PracticeRow key={p.id} {...shared} p={p} />
                  ))}
                </section>
              ))}
          </div>
          {data.days.every(
            (d) =>
              (d.date >= c.date || !d.sessions.length) &&
              !d.practices.some((p) => p.score || p.cancelled),
          ) && (
            <p className="surface panel-body">
              За выбранную неделю завершённых занятий пока нет.
            </p>
          )}
        </>
      )}
      {tab === "Делегирование" && (
        <section className="surface panel-body">
          <h2>Ответственные за подготовку</h2>
          {["schedule", "individual", "tactics", "practice", "recovery"].map(
            (k) => (
              <label className="staff-assignment" key={k}>
                {c.office.duties[k].title}
                <select
                  disabled={!allowed}
                  value={c.office.owners[k] || ""}
                  onChange={(e) =>
                    void send("career-staff", {
                      duty: k,
                      person: e.target.value || null,
                    })
                  }
                >
                  <option value="">Менеджер</option>
                  {Object.values(c.office.people).map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} · {p.suitability[k]}
                    </option>
                  ))}
                </select>
              </label>
            ),
          )}
        </section>
      )}
    </div>
  );
}
