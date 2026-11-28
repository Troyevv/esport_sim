import { useState, type ReactNode } from "react";
import { useData, date, type Act, type Career, type Scene } from "./careerData";
import { Flag, LineupPortrait } from "./SceneIdentity";
import { EntityName, PlayerRole } from "./CareerIdentity";
import { Heading, Dialog } from "./GameUI";
import { Load } from "./CareerForms";
import { roles, regions, skillLabels } from "./databaseModel";
import "./scouting.css";

type Band = [number, number];
export type Knowledge = {
  confidence: number;
  inSquad?: boolean;
  score: number;
  level: string;
  count: number;
  last?: string;
  age?: number;
  skills: Record<string, Band>;
  current: Band | null;
  potential: Band | null;
};
type Candidate = {
  id: string;
  name: string;
  age: number | null;
  country: string | null;
  region: string | null;
  role: string | null;
  language: string | null;
  team: string | null;
  free: boolean;
  knowledge?: Knowledge;
};
type Task = {
  id: number;
  start: string;
  due: string;
  kind: string;
  target: string | string[] | null;
  criteria: Filters;
  author: string | null;
  priority: number;
  cost: number;
  results: string[];
  status: string;
};
type Trial = {
  host: string;
  id: number;
  player: string;
  start: string;
  end: string;
  origin: string | null;
  consent: boolean;
  permission: boolean | null;
  status: string;
  report?: number | null;
};
type Filters = Record<string, string | number | boolean>;
type Version = {
  player: string;
  version: number;
  date: string;
  count: number;
  author: string;
};
type Center = {
  publicSkills: string[];
  players: Record<string, Candidate>;
  tasks: Task[];
  reports: Version[];
  lists: Record<string, string[]>;
  cost: number;
  trials: Trial[];
  incoming: Trial[];
  regionNames: string[];
  tournaments: Record<string, string>;
  coverage: Record<string, Record<string, number>>;
  workload: Record<string, { cost: number; days: number; peak: number }>;
  observers: {
    id: string;
    name: string;
    region: string;
    languages: string[];
    capacity: number;
    attributes: Record<string, number>;
    quality: number;
  }[];
};
type Report = Knowledge & {
  trialObservations?: number;
  version: number;
  published: string;
  author: string;
  strength: string | null;
  roleEvidence?: string;
  weakness: string | null;
  role: string | null;
  style: string;
  character: string;
  language: string | null;
  fit: string;
  communication: string;
  recommendation: string;
  evidence: {
    event: string;
    source: string;
    date: string;
    name: string;
    quality: number;
    basis: string;
  }[];
};
const sections = [
  "Обзор",
  "Поиск игроков",
  "Задания",
  "Отчёты",
  "Шорт-листы",
  "Сравнение",
  "Просмотры",
  "Региональное покрытие",
  "Персонал",
];
const kinds: Record<string, string> = {
  player: "Изучить игрока",
  team: "Изучить команду",
  tournament: "Наблюдать турнир",
  compare: "Сравнить кандидатов",
  search: "Поиск по критериям",
};
const statuses: Record<string, string> = {
  active: "В работе",
  complete: "Завершено",
  finished: "Завершён",
  cancelled: "Отменено",
  declined: "Игрок отказался",
  expired: "Срок ответа истёк",
  requested: "Ожидает разрешения клуба",
  blocked: "Клуб отказал",
};
const sources: Record<string, string> = {
  match: "Официальная встреча",
  practice: "Пракк",
  training: "Занятие",
  archive: "Архив",
};
export const range = (value?: Band | null) =>
  value ? (value[0] === value[1] ? String(value[0]) : value.join("–")) : "—";
const familiarity = (k?: Knowledge) =>
  k?.inSquad ? "Данные штаба" : k?.level || "Неизвестный";
const midpoint = (b?: Band | null) => (b ? (b[0] + b[1]) / 2 : -1);
function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="surface panel-body scout-panel">
      <h2>{title}</h2>
      {children}
    </section>
  );
}
function Comparison({
  players,
  remove,
}: {
  players: Candidate[];
  remove: (pid: string) => void;
}) {
  const attributes = [
    ...new Set(players.flatMap((p) => Object.keys(p.knowledge?.skills || {}))),
  ];
  const rows: [string, (p: Candidate) => string | number][] = [
    ["Изученность", (p) => familiarity(p.knowledge)],
    ["Роль", (p) => roles[p.role || ""] || "—"],
    ["Возраст", (p) => p.age ?? "—"],
    ["Игровой язык", (p) => p.language || "—"],
    ["Текущий OVR", (p) => range(p.knowledge?.current)],
    ["Потенциал", (p) => range(p.knowledge?.potential)],
    ["Наблюдения", (p) => p.knowledge?.count || 0],
    [
      "Последнее наблюдение",
      (p) => (p.knowledge?.last ? date(p.knowledge.last) : "—"),
    ],
    ...attributes.map((k): [string, (p: Candidate) => string] => [
      skillLabels[k],
      (p) => range(p.knowledge?.skills[k]),
    ]),
  ];
  return (
    <div
      className="scout-table-scroll"
      role="region"
      aria-label="Сравнение по доступным сведениям"
      tabIndex={0}
    >
      <table className="scout-matrix">
        <thead>
          <tr>
            <th scope="col">Показатель</th>
            {players.map((p) => (
              <th scope="col" key={p.id}>
                <EntityName group="players" id={p.id} fallback={p.name}/>
                <button
                  className="btn"
                  aria-label={"Убрать " + p.name}
                  onClick={() => remove(p.id)}
                >
                  Убрать
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}>
              <th scope="row">{label}</th>
              {players.map((p) => (
                <td key={p.id}>{value(p)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function ReportBody({ url }: { url: string }) {
  const result = useData<Report>(url);
  if (!result.data || result.error) return <Load {...result} />;
  const r = result.data;
  return (
    <div className="scout-report">
      <p>
        {date(r.published)} · {r.author} · Версия {r.version}
      </p>
      <h3>{r.recommendation}</h3>
      {r.trialObservations && (
        <p>Итоги просмотра · изучено занятий и пракков {r.trialObservations}</p>
      )}
      <p className="confidence-row">Уверенность автора <meter aria-label="Уверенность автора" min={0} max={100} value={r.confidence}/> {r.confidence}/100</p>
      <p>
        {r.level} · {r.score}/100 · наблюдений {r.count}
      </p>
      <dl className="scout-facts">
        {Object.entries({
          "Текущий OVR": range(r.current),
          Потенциал: range(r.potential),
          "Сильная сторона": r.strength && skillLabels[r.strength],
          "Зона развития": r.weakness && skillLabels[r.weakness],
          Роль: roles[r.role || ""],
          ...(r.roleEvidence ? { "Основания оценки роли": r.roleEvidence } : {}),
          Стиль: r.style,
          "Характер в игре": r.character,
          "Язык в симуляции": r.language,
          Коммуникация: r.communication,
          "Соответствие составу": r.fit,
          ...Object.fromEntries(
            Object.entries(r.skills).map(([k, v]) => [
              skillLabels[k],
              range(v),
            ]),
          ),
        }).map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v || "Недостаточно данных"}</dd>
          </div>
        ))}
      </dl>
      <h3>Основания оценки</h3>
      {[...r.evidence].reverse().map((o) => (
        <p key={o.event + o.name}>
          {date(o.date)} · {sources[o.source]} · {o.basis}
          <br />
          <small>
            {o.name} · качество наблюдения {o.quality}/100
          </small>
        </p>
      ))}
    </div>
  );
}
export function ScoutingCenter({
  c,
  scene,
  act,
  enabled,
  revision,
  open,
}: {
  c: Career;
  scene: Scene;
  act: Act;
  enabled: boolean;
  revision: number;
  open: (p: string) => void;
}) {
  const res = useData<Center>("/api/career/" + c.id + "/scouting", revision);
  if (!res.data || res.error) return <Load {...res} />;
  return (
    <CenterView
      {...{ c, scene, act, open }}
      enabled={enabled && res.revision === revision}
      data={res.data}
    />
  );
}
function CenterView({
  c,
  scene,
  act,
  enabled,
  data: d,
  open,
}: {
  c: Career;
  scene: Scene;
  act: Act;
  enabled: boolean;
  data: Center;
  open: (p: string) => void;
}) {
  const [tab, setTab] = useState(sections[0]),
    [query, setQuery] = useState(""),
    [criteria, setCriteria] = useState<Filters>({}),
    [sort, setSort] = useState("name"),
    [page, setPage] = useState(0);
  const players = Object.values(d.players),
    own = c.roster.map((p) => p.id);
  const [selected, select] = useState(
      () => players.find((p) => !own.includes(p.id))?.id || players[0].id,
    ),
    [compare, setCompare] = useState<string[]>([]);
  const [kind, setKind] = useState("player"),
    [team, setTeam] = useState(c.team),
    [edition, setEdition] = useState(Object.keys(d.tournaments)[0] || "");
  const [author, setAuthor] = useState(""),
    [priority, setPriority] = useState(2),
    [duration, setDuration] = useState(14),
    [trialDays, setTrialDays] = useState(7);
  const [category, setCategory] = useState(""),
    [newCategory, setNewCategory] = useState(""),
    [report, setReport] = useState<Version | null>(null);
  const [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const p = d.players[selected],
    list = (d.lists[category] ? category : "") || Object.keys(d.lists)[0] || "",
    locked = !enabled || busy;
  const name = (id: string) => d.players[id]?.name || id;
  const run = async (value: object, command = "career-scouting") => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (await act(command, value, setError))
        setMessage("Изменения сохранены");
    } finally {
      setBusy(false);
    }
  };
  const navigate = (v: string) => {
    setTab(v);
    setMessage("");
    setError("");
  };
  const filter = (k: string, v: string, numeric = false) => {
    const next = { ...criteria };
    if (v === "") delete next[k];
    else next[k] = numeric ? Number(v) : v;
    setCriteria(next);
    setPage(0);
  };
  const options = (values: Record<string, string>) =>
    Object.entries(values).map(([k, v]) => (
      <option key={k} value={k}>
        {v}
      </option>
    ));
  const values = (key: "country" | "language") =>
    Object.fromEntries(
      [...new Set(players.map((p) => p[key]).filter((s): s is string => !!s))]
        .sort()
        .map((s) => [s, s]),
    );
  const selector = (
    title: string,
    key: string,
    items: Record<string, string>,
  ) => (
    <label>
      {title}
      <select
        value={String(criteria[key] ?? "")}
        onChange={(e) => filter(key, e.target.value)}
      >
        <option value="">Все</option>
        {options(items)}
      </select>
    </label>
  );
  const number = (title: string, key: string) => (
    <label>
      {title}
      <input
        type="number"
        min="0"
        max="100"
        value={String(criteria[key] ?? "")}
        onChange={(e) => filter(key, e.target.value, true)}
      />
    </label>
  );
  const filters = (
    <div className="scout-fields">
      {selector("Регион", "region", regions)}
      {selector("Страна", "country", values("country"))}
      {selector("Роль", "role", roles)}
      {selector("Игровой язык", "language", values("language"))}
      {number("Возраст от", "minAge")}
      {number("Возраст до", "maxAge")}
      {number("Оценка OVR от", "current")}
      {number("Оценка потенциала от", "potential")}
      {selector(
        "Приоритетный навык",
        "skill",
        Object.fromEntries(d.publicSkills.map((k) => [k, skillLabels[k]])),
      )}
      {number("Оценка навыка от", "minimum")}
      <label>
        <span>Статус</span>
        <select
          value={criteria.free ? "free" : ""}
          onChange={(e) => {
            const n = { ...criteria };
            if (e.target.value) n.free = true;
            else delete n.free;
            setCriteria(n);
            setPage(0);
          }}
        >
          <option value="">Все игроки</option>
          <option value="free">Свободный агент</option>
        </select>
      </label>
    </div>
  );
  const metric = (p: Candidate, key: string) =>
    key === "score"
      ? p.knowledge?.score || 0
      : midpoint(p.knowledge?.[key as "current" | "potential"]);
  const found = players
    .filter(
      (p) =>
        p.name.toLowerCase().includes(query.trim().toLowerCase()) &&
        ["region", "role", "country", "language", "free"].every(
          (k) => !(k in criteria) || p[k as keyof Candidate] === criteria[k],
        ) &&
        (!("minAge" in criteria) ||
          (p.age != null && p.age >= Number(criteria.minAge))) &&
        (!("maxAge" in criteria) ||
          (p.age != null && p.age <= Number(criteria.maxAge))) &&
        ["current", "potential"].every(
          (k) => !(k in criteria) || metric(p, k) >= Number(criteria[k]),
        ) &&
        (!criteria.skill ||
          midpoint(p.knowledge?.skills[String(criteria.skill)]) >=
            Number(criteria.minimum || 0)),
    )
    .sort(
      (a, b) =>
        (sort === "name" ? 0 : metric(b, sort) - metric(a, sort)) ||
        a.name.localeCompare(b.name),
    );
  const toggle = (id: string) =>
    setCompare((old) =>
      old.includes(id) ? old.filter((v) => v !== id) : [...old, id].slice(0, 8),
    );
  const active = d.tasks.filter((t) => t.status === "active");
  const candidateSelect = (
    <label>
      Игрок
      <select
        aria-label="Игрок"
        value={selected}
        onChange={(e) => select(e.target.value)}
      >
        {players.map((p) => (
          <option value={p.id} key={p.id}>
            {p.name}
          </option>
        ))}
      </select>
    </label>
  );
  const action = (label: string, fn: () => void, disabled = false) => (
    <button className="btn" disabled={disabled} onClick={fn}>
      {label}
    </button>
  );
  const task = () =>
    run({
      action: "task",
      kind,
      target:
        kind === "player"
          ? [selected]
          : kind === "compare"
            ? compare
            : kind === "team"
              ? team
              : edition,
      criteria:
        kind === "search"
          ? { ...criteria, ...(query.trim() ? { name: query.trim() } : {}) }
          : {},
      priority,
      author: author || null,
      days: duration,
    });
  const card = (id: string) => {
    const row = d.players[id];
    return (
      <div className="scout-row" key={id}>
        <button className="entity-button" onClick={() => open(id)}>
          <LineupPortrait id={id} name={row.name} visual={scene.players[id]?.visual || {}}/>
          <span>
            <strong>{row.name} {row.country && <Flag value={row.country}/>}</strong>
            <small>
              {row.role ? <PlayerRole role={row.role}/> : "Роль неизвестна"} ·{" "}
              {scene.teams[row.team || ""]?.name || "Клуб неизвестен"}
            </small>
          </span>
        </button>
        <span>
          {familiarity(row.knowledge)}
          <small>
            OVR {range(row.knowledge?.current)} · Потенциал{" "}
            {range(row.knowledge?.potential)}
          </small>
        </span>
        <div className="scout-actions">
          {action("Изучить", () => {
            select(id);
            setKind("player");
            navigate("Задания");
          })}
          {action(
            compare.includes(id) ? "Убрать из сравнения" : "Сравнить",
            () => toggle(id),
            !compare.includes(id) && compare.length >= 8,
          )}
        </div>
      </div>
    );
  };
  const reportRows = (rows: Version[]) =>
    rows.length ? (
      rows.map((v) => (
        <button
          className="scout-entry"
          key={v.player + v.version}
          onClick={() => setReport(v)}
        >
          <strong>
            <EntityName group="players" id={v.player} fallback={name(v.player)} link={false}/> · версия {v.version}
          </strong>
          <span>
            {date(v.date)} · {v.author} · наблюдений {v.count}
          </span>
        </button>
      ))
    ) : (
      <p className="muted">Отчёты появятся после разбора наблюдений.</p>
    );
  const recent = [...d.reports].sort(
    (a, b) => b.date.localeCompare(a.date) || b.version - a.version,
  );
  return (
    <div className="scout-center">
      <Heading title="Скаутский центр" sub={c.club + " · " + date(c.date)} />
      <nav className="view-tabs scout-tabs" aria-label="Разделы скаутинга">
        {sections.map((s) => (
          <button
            key={s}
            className={tab === s ? "active" : ""}
            aria-current={tab === s ? "page" : undefined}
            onClick={() => navigate(s)}
          >
            {s}
          </button>
        ))}
      </nav>
      <label className="scout-mobile">
        Раздел скаутинга
        <select
          aria-label="Раздел скаутинга"
          value={tab}
          onChange={(e) => navigate(e.target.value)}
        >
          {sections.map((s) => (
            <option key={s}>{s}</option>
          ))}
        </select>
      </label>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {message && <p role="status">{message}</p>}
      {tab === "Обзор" && (
        <>
          <div className="scout-counts">
            {[
              [active.length, "Активные задания", "Задания"],
              [d.reports.length, "Отчёты", "Отчёты"],
              [
                Object.values(d.lists)
                  .flat()
                  .filter((v, i, a) => a.indexOf(v) === i).length,
                "В шорт-листах",
                "Шорт-листы",
              ],
              [
                d.trials.filter((t) => t.status === "active").length,
                "На просмотре",
                "Просмотры",
              ],
            ].map(([n, s, target]) => (
              <button
                className="surface"
                key={s}
                onClick={() => navigate(String(target))}
              >
                <strong>{n}</strong>
                {s}
              </button>
            ))}
          </div>
          <div className="scout-columns">
            <Panel title="Последние отчёты">
              {reportRows(recent.slice(0, 5))}
            </Panel>
            <Panel title="Работа отдела">
              <p>Накопленная нагрузка · {d.cost} ед.</p>
              <p>
                Игроков с наблюдениями ·{" "}
                {players.filter((p) => p.knowledge?.count).length}
              </p>
              {action("Найти кандидата", () => navigate("Поиск игроков"))}
            </Panel>
          </div>
        </>
      )}
      {tab === "Поиск игроков" && (
        <>
          <Panel title="Поиск игроков">
            <label>
              Имя игрока
              <input
                type="search"
                value={query}
                onChange={(e) => {
                  setQuery(e.target.value);
                  setPage(0);
                }}
              />
            </label>
            <details>
              <summary>Критерии поиска</summary>
              {filters}
            </details>
            <div className="scout-actions">
              <label>
                Сортировка
                <select
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value);
                    setPage(0);
                  }}
                >
                  {options({
                    name: "Имя",
                    score: "Изученность",
                    current: "Оценка OVR",
                    potential: "Оценка потенциала",
                  })}
                </select>
              </label>
              {action("Поручить поиск", () => {
                setKind("search");
                navigate("Задания");
              })}
            </div>
          </Panel>
          <Panel title={"Кандидаты · " + found.length}>
            {found.slice(page * 16, page * 16 + 16).map((p) => card(p.id))}
            {!found.length && (
              <p>Нет игроков с такими доступными сведениями.</p>
            )}
            <div className="scout-actions">
              {action("Назад", () => setPage(page - 1), !page)}
              <span>
                {page + 1} / {Math.max(1, Math.ceil(found.length / 16))}
              </span>
              {action(
                "Далее",
                () => setPage(page + 1),
                (page + 1) * 16 >= found.length,
              )}
            </div>
          </Panel>
        </>
      )}
      {tab === "Задания" && (
        <>
          <Panel title="Новое задание">
            <div className="scout-fields">
              <label>
                Тип задания
                <select value={kind} onChange={(e) => setKind(e.target.value)}>
                  {options(kinds)}
                </select>
              </label>
              {kind === "player" ? (
                candidateSelect
              ) : kind === "team" ? (
                <label>
                  Команда
                  <select
                    value={team}
                    onChange={(e) => setTeam(e.target.value)}
                  >
                    {options(
                      Object.fromEntries(
                        Object.values(scene.teams).map((t) => [t.id, t.name]),
                      ),
                    )}
                  </select>
                </label>
              ) : kind === "tournament" ? (
                <label>
                  Турнир
                  <select
                    value={edition}
                    onChange={(e) => setEdition(e.target.value)}
                  >
                    {options(d.tournaments)}
                  </select>
                </label>
              ) : null}
              <label>
                Исполнитель
                <select
                  value={author}
                  onChange={(e) => setAuthor(e.target.value)}
                >
                  <option value="">Распределить в отделе</option>
                  {d.observers.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Приоритет
                <select
                  value={priority}
                  onChange={(e) => setPriority(+e.target.value)}
                >
                  {options({ 1: "Обычный", 2: "Повышенный", 3: "Срочный" })}
                </select>
              </label>
              <label>
                Срок, дней
                <input
                  type="number"
                  min="1"
                  max="90"
                  value={duration}
                  onChange={(e) => setDuration(+e.target.value)}
                />
              </label>
            </div>
            {kind === "search" && (
              <>
                <label>
                  Имя игрока
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                  />
                </label>
                {filters}
              </>
            )}
            {kind === "compare" && (
              <p>
                Выбрано для сравнения ·{" "}
                {compare.map(name).join(", ") ||
                  "Выберите игроков в разделе сравнения"}
              </p>
            )}
            {action(
              "Назначить задание",
              task,
              locked ||
                (kind === "compare" && compare.length < 2) ||
                (kind === "tournament" && !edition),
            )}
          </Panel>
          <Panel title="Журнал заданий">
            {!d.tasks.length && <p>В отделе пока нет заданий.</p>}
            {[...d.tasks].reverse().map((t) => (
              <article key={t.id} className="scout-item">
                <strong>
                  {kinds[t.kind]} ·{" "}
                  {Array.isArray(t.target)
                    ? t.target.map(name).join(", ")
                    : scene.teams[t.target || ""]?.name ||
                      d.tournaments[t.target || ""] ||
                      "Поиск"}
                </strong>
                <p>
                  {statuses[t.status]} · до {date(t.due)} · приоритет{" "}
                  {t.priority}
                </p>
                <small>
                  {d.observers.find((s) => s.id === t.author)?.name ||
                    "Ожидает распределения"}{" "}
                  · затраты {t.cost} ед. · кандидатов {t.results.length}
                </small>
                {t.results.map((id) => (
                  <button className="btn" key={id} onClick={() => open(id)}>
                    {name(id)}
                  </button>
                ))}
                {t.status === "active" &&
                  action(
                    "Отменить задание",
                    () => run({ action: "cancel", id: t.id }),
                    locked,
                  )}
              </article>
            ))}
          </Panel>
        </>
      )}
      {tab === "Отчёты" && (
        <Panel title="История отчётов">{reportRows(recent)}</Panel>
      )}
      {tab === "Шорт-листы" && (
        <>
          <Panel title="Категории">
            <div className="scout-actions">
              <label>
                Новая категория
                <input
                  maxLength={48}
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                />
              </label>
              {action(
                "Создать категорию",
                () => run({ action: "category", category: newCategory }),
                locked || !newCategory.trim(),
              )}
              {list &&
                action(
                  "Переименовать категорию",
                  async () => {
                    await run({
                      action: "renameCategory",
                      category: list,
                      name: newCategory,
                    });
                    setCategory("");
                  },
                  locked || !newCategory.trim(),
                )}
              {list &&
                action(
                  "Удалить пустую категорию",
                  async () => {
                    await run({ action: "deleteCategory", category: list });
                    setCategory("");
                  },
                  locked || !!d.lists[list]?.length,
                )}
            </div>
          </Panel>
          {Object.keys(d.lists).length > 0 && (
            <Panel title="Кандидаты в списке">
              <div className="scout-fields">
                <label>
                  Категория
                  <select
                    value={list}
                    onChange={(e) => setCategory(e.target.value)}
                  >
                    {Object.keys(d.lists).map((s) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </label>
                {candidateSelect}
              </div>
              {action(
                "Добавить игрока",
                () => run({ action: "list", category: list, player: selected }),
                locked || d.lists[list]?.includes(selected),
              )}
              {d.lists[list]?.map((id) => (
                <div key={id}>
                  {card(id)}
                  {action(
                    "Удалить из списка",
                    () => run({ action: "remove", category: list, player: id }),
                    locked,
                  )}
                </div>
              ))}
            </Panel>
          )}
        </>
      )}
      {tab === "Сравнение" && (
        <Panel title="Сравнение кандидатов">
          <div className="scout-actions">
            {candidateSelect}
            {action(
              "Добавить к сравнению",
              () => toggle(selected),
              compare.includes(selected) || compare.length >= 8,
            )}
          </div>
          {compare.length ? (
            <Comparison
              players={compare.map((id) => d.players[id])}
              remove={toggle}
            />
          ) : (
            <p>Выберите игроков для сравнения.</p>
          )}
          {action(
            "Поручить сравнение",
            () => {
              setKind("compare");
              navigate("Задания");
            },
            compare.length < 2,
          )}
        </Panel>
      )}
      {tab === "Просмотры" && (
        <>
          <Panel title="Приглашение на просмотр">
            <div className="scout-fields">
              {candidateSelect}
              <label>
                Длительность
                <select
                  value={trialDays}
                  onChange={(e) => setTrialDays(+e.target.value)}
                >
                  {[3, 7, 14].map((n) => (
                    <option key={n} value={n}>
                      {n} дн.
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <p>
              {p.free
                ? "Свободный агент"
                : p.team
                  ? "Требуется разрешение клуба " + scene.teams[p.team]?.name
                  : "Действующий клуб не указан"}
            </p>
            {action(
              "Пригласить игрока",
              () => run({ action: "trial", player: selected, days: trialDays }),
              locked || own.includes(selected) || !!p.knowledge?.inSquad,
            )}
          </Panel>
          {d.incoming.length > 0 && (
            <Panel title="Запросы других клубов">
              {d.incoming.map((t) => (
                <article className="scout-item" key={t.id}>
                  <strong>
                    {name(t.player)} · {scene.teams[t.host]?.name}
                  </strong>
                  <p>
                    {date(t.start)} — {date(t.end)}
                  </p>
                  {t.status === "requested" ? (
                    <div className="scout-actions">
                      {action(
                        "Разрешить просмотр",
                        () => run({ action: "permit", id: t.id }),
                        locked,
                      )}
                      {action(
                        "Отказать клубу",
                        () => run({ action: "deny", id: t.id }),
                        locked,
                      )}
                    </div>
                  ) : (
                    <p>Просмотр разрешён</p>
                  )}
                </article>
              ))}
            </Panel>
          )}
          <Panel title="Игроки на просмотре">
            {!d.trials.length && <p>Приглашений пока нет.</p>}
            {[...d.trials].reverse().map((t) => (
              <article key={t.id} className="scout-item">
                <strong>
                  {name(t.player)} ·{" "}
                  {t.status === "active" ? "На просмотре" : statuses[t.status]}
                </strong>
                <p>
                  {date(t.start)} — {date(t.end)}
                </p>
                <small>
                  Согласие игрока · {t.consent ? "получено" : "отказ"} /
                  Разрешение клуба ·{" "}
                  {t.permission === null
                    ? "не требуется"
                    : t.permission
                      ? "получено"
                      : "отказ"}
                </small>
                {t.report
                  ? action("Итоговый отчёт", () =>
                      setReport(
                        d.reports.find(
                          (r) =>
                            r.player === t.player && r.version === t.report,
                        )!,
                      ),
                    )
                  : t.status === "finished" && (
                      <p>Недостаточно наблюдений за просмотр.</p>
                    )}
              </article>
            ))}
          </Panel>
        </>
      )}
      {tab === "Региональное покрытие" && (
        <Panel title="Знание профессиональной сцены">
          <div className="scout-columns">
            {d.regionNames.map((region) => (
              <article className="scout-item" key={region}>
                <h3>{regions[region] || region}</h3>
                {d.observers.map((s) => (
                  <p key={s.id}>
                    {s.name} ·{" "}
                    {s.region === region
                      ? "профильный регион"
                      : "выездной регион"}
                    <small>
                      Наблюдений · {d.coverage[s.id]?.[region] || 0}
                    </small>
                  </p>
                ))}
                {action("Искать в регионе", () => {
                  setCriteria({ region });
                  setKind("search");
                  navigate("Задания");
                })}
              </article>
            ))}
          </div>
        </Panel>
      )}
      {tab === "Персонал" && (
        <>
          <Panel title="Делегирование">
            <div className="scout-fields">
              {["dispatch", "search"].map((duty) => (
                <label key={duty}>
                  {c.office.duties[duty].title}
                  <select
                    disabled={locked}
                    value={c.office.owners[duty] || ""}
                    onChange={(e) =>
                      run(
                        { duty, person: e.target.value || null },
                        "career-staff",
                      )
                    }
                  >
                    <option value="">Менеджер</option>
                    {options(
                      Object.fromEntries(
                        Object.values(c.office.people).map((p) => [
                          p.id,
                          p.name,
                        ]),
                      ),
                    )}
                  </select>
                </label>
              ))}
            </div>
          </Panel>
          <Panel title="Нагрузка отдела">
            {d.observers.map((s) => (
              <div className="scout-item" key={s.id}>
                <strong>{s.name}</strong>
                <p>
                  {regions[s.region]} ·{" "}
                  {s.languages.join(", ") || "язык неизвестен"} · пригодность{" "}
                  {s.quality}/100
                </p>
                <small>
                  Способности {s.attributes.ability} · потенциал{" "}
                  {s.attributes.potential} · совместимость {s.attributes.fit} ·
                  поиск талантов {s.attributes.discovery}
                </small>
                <small>
                  Сегодня ·{" "}
                  {c.office.jobs
                    .filter((j) => j.person === s.id && j.date === c.date)
                    .reduce((n, j) => n + j.cost, 0)}{" "}
                  из {s.capacity} ед. · За карьеру {d.workload[s.id]?.cost || 0}{" "}
                  ед. за {d.workload[s.id]?.days || 0} дн.
                </small>
              </div>
            ))}
          </Panel>
        </>
      )}
      {report && (
        <Dialog
          title={"Скаутский отчёт · " + name(report.player)}
          close={() => setReport(null)}
        >
          <ReportBody
            url={
              "/api/career/" +
              c.id +
              "/scouting/" +
              encodeURIComponent(report.player) +
              "/" +
              report.version
            }
          />
        </Dialog>
      )}
    </div>
  );
}
