import { useEffect, useRef, useState } from "react";
import { serverURL, type Frame } from "./session";
import { Avatar, type Visual } from "./SceneIdentity";
import {
  AttributeGrid,
  Facts,
  ProfileHeading,
  RoleRatings,
} from "./SceneProfiles";
import { regions, roles } from "./databaseModel";
import "./career.css";

type Act = (kind: string, value?: object) => Promise<boolean>;
type Summary = {
  id: string;
  character: string;
  club: string;
  mode: string;
  scope: string;
  date: string;
};
type Fixture = {
  kind: "match" | "review";
  id: string;
  date: string;
  teams: string[];
  score?: number[];
  scoreByTeam?: Record<string,number>;
};
// Older completed reports stored their points in the frozen fixture's team order.
const fixtureScore = (e: Fixture) => (e.scoreByTeam ? e.teams.map(id => e.scoreByTeam![id]) : e.score)?.join(" : ");

type Player = {
  id: string;
  name: string;
  role: string;
  captain: boolean;
  born: string | null;
  realName: string | null;
  visual: Visual;
  skills: Record<string, number>;
  ratings: Record<string, number>;
};
type Career = Summary & {
  team: string;
  teams: Record<string, string>;
  start: string;
  source: string;
  edition: number;
  organization: string | null;
  region: string | null;
  visual: Visual;
  queue: Fixture[];
  history: Fixture[];
  regions: string[];
  milestones: { date: string; title: string; matches: number | null }[];
  progress: { done: number; total: number } | null;
  error: string | null;
  roster: Player[];
  slots: (Summary & { slot: string })[];
};
type Team = {
  id: string;
  name: string;
  region: string | null;
  tier: number | null;
};
type Scene = { date: string; teams: Team[] };
type Catalog = { id: string; title: string; revision: number }[];
type Report = {
  stats: {
    player: string;
    name: string;
    club: number;
    teamId?: string;
    k: number;
    d: number;
    a: number;
    damage: number;
  }[];
  rounds: unknown[];
};
const scopes: Record<string, string> = {
  fast: "Быстрый",
  standard: "Стандартный",
  full: "Полный",
};
const position = (mode: string) =>
  mode === "owner" ? "Владелец организации" : "Главный тренер";
const date = (value: string) =>
  new Date(value + "T12:00:00Z").toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
const slotName = (value: string) =>
  (value.startsWith("auto") ? "Автосохранение" : "Слот " + value[0]) +
  (value.endsWith(".bak") ? " · резерв" : "");

function useData<T>(path: string | null, revision = 0) {
  const [answer, setAnswer] = useState<{
    path: string;
    revision: number;
    data: T;
  } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    if (path)
      fetch(serverURL(path), {
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
      })
        .then(async (res) => {
          const data = await res.json();
          if (!res.ok)
            throw new Error(data.detail || "Не удалось прочитать данные");
          if (!controller.signal.aborted) setAnswer({ path, data, revision });
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    return () => controller.abort();
  }, [path, revision, retry]);
  return {
    revision: answer?.revision,
    data: answer?.path === path ? answer?.data : undefined,
    error,
    reload: () => setRetry((v) => v + 1),
  };
}

function Load({ error, reload }: { error: string; reload: () => void }) {
  return error ? (
    <div role="alert">
      {error} <button onClick={reload}>Повторить</button>
    </div>
  ) : (
    <p role="status">Загружаем данные…</p>
  );
}

function NewCareer({
  act,
  enabled,
  back,
  opened,
}: {
  act: Act;
  enabled: boolean;
  back: () => void;
  opened: () => void;
}) {
  const catalog = useData<Catalog>("/api/database");
  const [edition, setEdition] = useState("");
  const source =
    edition ||
    (catalog.data?.[0]
      ? catalog.data[0].id + "/" + catalog.data[0].revision
      : "");
  const options = useData<Scene>(
    source ? "/api/career/options/" + source : null,
  );
  const [team, setTeam] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState("manager");
  const [scope, setScope] = useState("standard");
  const [areas, setAreas] = useState(["Europe"]);
  const teams = (options.data?.teams || [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const club = teams.find((t) => t.id === team) || teams[0];
  const submit = async () => {
    const [id, rev] = source.split("/");
    if (
      club &&
      (await act("career-create", {
        id,
        revision: Number(rev),
        team: club.id,
        name,
        mode,
        scope,
        regions: scope === "fast" ? areas : [],
      }))
    )
      opened();
  };
  return (
    <section className="career">
      <button onClick={back}>← Главное меню</button>
      <header className="cr-title">
        <small>Карьера</small>
        <h1>Новая карьера</h1>
      </header>
      <form
        className="cr-grid"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="cr-card cr-form">
          <h2>Стартовый мир</h2>
          {(!catalog.data || catalog.error) && <Load {...catalog} />}
          <label>
            Редакция базы
            <select
              value={source}
              onChange={(e) => {
                setEdition(e.target.value);
                setTeam("");
              }}
            >
              {catalog.data?.map((p) => (
                <option key={p.id + p.revision} value={p.id + "/" + p.revision}>
                  {p.title} · ред. {p.revision}
                </option>
              ))}
            </select>
          </label>
          {(!options.data || options.error) && <Load {...options} />}
          <label>
            Команда
            <select
              required
              value={club?.id || ""}
              onChange={(e) => setTeam(e.target.value)}
            >
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          {options.data && (
            <p>
              {date(options.data.date)} · {teams.length} команд с полной
              пятёркой
            </p>
          )}
          <label>
            Охват симуляции
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              {Object.entries(scopes).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {scope === "fast" ? (
            <fieldset>
              <legend>Регионы фоновых встреч</legend>
              {Object.entries(regions).map(([k, v]) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={areas.includes(k)}
                    onChange={(e) =>
                      setAreas(
                        e.target.checked
                          ? [...areas, k]
                          : areas.filter((a) => a !== k),
                      )
                    }
                  />
                  {v}
                </label>
              ))}
            </fieldset>
          ) : (
            <p>
              {scope === "full"
                ? "Все доступные составы, включая тир-3."
                : "Основная сцена (тир-1 и тир-2) и ваша команда. В базах без тиров участвуют все доступные составы."}
            </p>
          )}
        </div>
        <div className="cr-card cr-form">
          <h2>Игровой персонаж</h2>
          <label>
            Имя персонажа
            <input
              required
              maxLength={64}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            Должность
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="manager">Наёмный менеджер</option>
              <option value="owner">Владелец организации</option>
            </select>
          </label>
          {club && (
            <div className="cr-selection">
              <small>Стартовая команда</small>
              <strong>{club.name}</strong>
              <span>
                {regions[club.region || ""] || "Регион неизвестен"}
                {club.tier && " · Тир " + club.tier}
              </span>
            </div>
          )}
          <button
            className="primary"
            disabled={
              !enabled ||
              !name.trim() ||
              !club ||
              !!options.error ||
              (scope === "fast" && !areas.length)
            }
          >
            Создать карьеру
          </button>
        </div>
      </form>
    </section>
  );
}

function MatchReport({
  event,
  teams,
  close,
}: {
  event: Fixture;
  teams: Record<string, string>;
  close: () => void;
}) {
  const data = useData<Report>("/api/career/report/" + event.id);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus();
  }, [event.id]);
  const rounds = data.data?.rounds.length || 0;
  return (
    <section className="cr-card cr-report">
      <div className="cr-line">
        <h2 ref={title} tabIndex={-1}>
          Протокол матча
        </h2>
        <button onClick={close}>Закрыть протокол</button>
      </div>
      <h3 className="cr-result-title">
        {teams[event.teams[0]]} <strong>{fixtureScore(event)}</strong>{" "}
        {teams[event.teams[1]]}
      </h3>
      {!data.data || data.error ? (
        <Load {...data} />
      ) : (
        <>
          <p>
            {date(event.date)} · Депо · {rounds} раундов
          </p>
          {event.teams.map((tid, club) => (
            <table key={tid}>
              <caption>{teams[tid]}</caption>
              <thead>
                <tr>
                  <th>Игрок</th>
                  <th>K</th>
                  <th>D</th>
                  <th>A</th>
                  <th>ADR</th>
                </tr>
              </thead>
              <tbody>
                {data
                  .data!.stats.filter((p) => p.teamId ? p.teamId === tid : p.club === club)
                  .map((p) => (
                    <tr key={p.player}>
                      <th scope="row">{p.name}</th>
                      <td>{p.k}</td>
                      <td>{p.d}</td>
                      <td>{p.a}</td>
                      <td>{(p.damage / rounds).toFixed(1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ))}
        </>
      )}
    </section>
  );
}

function Calendar({ c }: { c: Career }) {
  const [filter, setFilter] = useState("club"),
    [report, setReport] = useState<Fixture | null>(null);
  const [chosenMonth, setMonth] = useState("");
  const trigger = useRef<HTMLButtonElement | null>(null);
  const month = chosenMonth || c.date.slice(0, 7);
  const months = Array.from(
    new Set(
      [...c.queue, ...c.history, ...c.milestones].map((e) =>
        e.date.slice(0, 7),
      ),
    ),
  ).sort();
  const relevant = (e: Fixture) =>
    e.date.startsWith(month) &&
    (e.kind === "review" || filter === "all" || e.teams.includes(c.team));

  const list = (items: Fixture[], empty: string) =>
    items.length ? (
      <ol className="cr-fixtures">
        {items.map((e) => (
          <li key={e.id}>
            <time>{date(e.date)}</time>
            <span>
              {e.kind === "review"
                ? "Итоги недели"
                : e.teams.map((t) => c.teams[t]).join(" — ")}
            </span>
            {e.score ? (
              <button
                aria-label={"Протокол " + fixtureScore(e)}
                onClick={(click) => {
                  trigger.current = click.currentTarget;
                  setReport(e);
                }}
              >
                {fixtureScore(e)} ↗
              </button>
            ) : (
              <b>{e.kind === "review" ? "Обзор" : "BO1"}</b>
            )}
          </li>
        ))}
      </ol>
    ) : (
      <p>{empty}</p>
    );
  return (
    <>
      <section className="cr-card">
        <div className="cr-line">
          <h2>Календарь</h2>
          <label>
            Месяц{" "}
            <select
              value={month}
              onChange={(e) => {
                setMonth(e.target.value);
                setReport(null);
              }}
            >
              {months.map((m) => (
                <option key={m} value={m}>
                  {new Date(m + "-01T12:00:00Z").toLocaleDateString("ru-RU", {
                    month: "long",
                    year: "numeric",
                    timeZone: "UTC",
                  })}
                </option>
              ))}
            </select>
          </label>
          <label>
            Показать{" "}
            <select
              value={filter}
              onChange={(e) => {
                setFilter(e.target.value);
                setReport(null);
              }}
            >
              <option value="club">Моя команда</option>
              <option value="all">Весь мир</option>
            </select>
          </label>
        </div>
        <h3>Расписание</h3>
        {list(
          c.queue.filter(relevant),
          "На этот месяц встреч не запланировано.",
        )}
        <h3>Результаты</h3>
        {list(
          c.history.filter(relevant).slice().reverse(),
          "Завершённых встреч за этот месяц нет.",
        )}
        <h3>События клуба</h3>
        <ol className="cr-fixtures">
          {c.milestones
            .filter((m) => m.date.startsWith(month))
            .reverse()
            .map((m) => (
              <li key={m.date + m.title}>
                <time>{date(m.date)}</time>
                <span>
                  {m.title}
                  {m.matches !== null && " · матчей за неделю: " + m.matches}
                </span>
              </li>
            ))}
        </ol>
      </section>
      {report && (
        <MatchReport
          event={report}
          teams={c.teams}
          close={() => {
            setReport(null);
            trigger.current?.focus();
          }}
        />
      )}
    </>
  );
}

function Squad({ c }: { c: Career }) {
  const [id, setId] = useState("");
  const p = c.roster.find((p) => p.id === id);
  return (
    <div className="cr-grid">
      <section className="cr-card">
        <h2>Состав команды</h2>
        <div className="cr-roster">
          {c.roster.map((p) => (
            <button
              key={p.id}
              aria-pressed={p.id === id}
              onClick={() => setId(p.id)}
            >
              <Avatar name={p.name} {...p.visual} />
              <span>
                <strong>{p.name}</strong>
                <small>
                  {roles[p.role]}
                  {p.captain && " · Капитан"}
                </small>
              </span>
              <b>↗</b>
            </button>
          ))}
        </div>
      </section>
      {p && (
        <section className="cr-card">
          <ProfileHeading
            name={p.name}
            subtitle={p.realName}
            type={roles[p.role]}
            context={c.club}
            visual={p.visual}
          />
          <Facts
            rows={[
              {
                name: "Дата рождения",
                value: p.born ? date(p.born) : "Нет сведений",
              },
            ]}
          />
          <RoleRatings values={p.ratings} />
          <AttributeGrid values={p.skills} />
        </section>
      )}
    </div>
  );
}

function Saves({ c, act, enabled }: { c: Career; act: Act; enabled: boolean }) {
  const [slot, setSlot] = useState("1");
  return (
    <section className="cr-card cr-form">
      <h2>Сохранения</h2>
      <div className="cr-line">
        <label>
          Ручной слот
          <select value={slot} onChange={(e) => setSlot(e.target.value)}>
            {["1", "2", "3"].map((s) => (
              <option key={s} value={s}>
                {slotName(s)}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={!enabled}
          onClick={() => act("career-save", { slot })}
        >
          Сохранить карьеру
        </button>
      </div>
      {c.slots.map((s) => (
        <div className="cr-save" key={s.slot}>
          <span>
            <strong>{slotName(s.slot)}</strong>
            <small>
              {date(s.date)} · {s.club}
            </small>
          </span>
          <button
            disabled={!enabled}
            onClick={() => act("career-load", { slot: s.slot })}
          >
            Загрузить
          </button>
        </div>
      ))}
    </section>
  );
}

type Props = {
  frame: Frame;
  enabled: boolean;
  act: Act;
  screen: "menu" | "hub";
  go: (s: "menu" | "hub" | "lab" | "match") => void;
  database: () => void;
  board: () => void;
};
export default function CareerScreen({
  frame,
  enabled,
  act,
  screen,
  go,
  database,
  board,
}: Props) {
  const response = useData<{ careers: Summary[]; active: Career | null }>(
    "/api/career",
    frame.careerRevision,
  );
  const [create, setCreate] = useState(false),
    [tab, setTab] = useState("Обзор");
  const c = response.data?.active;
  enabled = enabled && response.revision === (frame.careerRevision || 0);
  useEffect(() => {
    setTab("Обзор");
  }, [frame.careerId]);
  if (create)
    return (
      <NewCareer
        enabled={enabled}
        act={act}
        back={() => setCreate(false)}
        opened={() => {
          setCreate(false);
          go("hub");
        }}
      />
    );
  if (!response.data || response.error) return <Load {...response} />;
  if (screen === "menu" || !c)
    return (
      <section className="career">
        <div className="cr-cover">
          <small>Counter-Strike · Менеджер команды</small>
          <h1>Главное меню</h1>
          <div className="cr-actions">
            {c && (
              <button className="primary" onClick={() => go("hub")}>
                Продолжить карьеру
              </button>
            )}
            <button
              className={c ? "" : "primary"}
              onClick={() => setCreate(true)}
            >
              Новая карьера
            </button>
          </div>
        </div>
        <div className="cr-grid">
          <section className="cr-card">
            <h2>Мои карьеры</h2>
            {response.data.careers.length ? (
              response.data.careers.map((s) => (
                <div className="cr-save" key={s.id}>
                  <span>
                    <strong>{s.club}</strong>
                    <small>
                      {s.character} · {date(s.date)}
                    </small>
                  </span>
                  <button
                    disabled={!enabled}
                    onClick={async () => {
                      if (
                        c?.id === s.id ||
                        (await act("career-open", { career: s.id }))
                      )
                        go("hub");
                    }}
                  >
                    Открыть
                  </button>
                </div>
              ))
            ) : (
              <p>Здесь появятся созданные карьеры.</p>
            )}
          </section>
          <section className="cr-card">
            <h2>Инструменты</h2>
            <div className="cr-actions">
              <button onClick={database}>База сцены</button>
              <button
                onClick={async () => {
                  if (!c || (await act("career-lab"))) go("lab");
                }}
              >
                Стенд симуляции
              </button>
            </div>
          </section>
        </div>
      </section>
    );
  const next = c.queue.find((e) => e.teams.includes(c.team))!;
  const matchNow = !!frame.world.match;
  const ready =
    !c.progress && next.date === c.date && c.queue[0].id === next.id;
  return (
    <section className="career">
      <button onClick={() => go("menu")}>← Главное меню</button>
      <header className="cr-banner">
        <Avatar {...c.visual} name={c.club} />
        <div>
          <small>
            {c.organization || "Команда"} · {regions[c.region || ""] || "Сцена"}
          </small>
          <h1>{c.club}</h1>
          <span>
            {c.character} · {position(c.mode)}
          </span>
        </div>
        <div className="cr-time">
          <time>{date(c.date)}</time>
          <button
            className="primary"
            disabled={!enabled || !!c.progress}
            onClick={async () => {
              if (matchNow) go("match");
              else if (ready) {
                if (await act("career-play")) go("match");
              } else await act("career-advance");
            }}
          >
            {matchNow || ready ? "В матч-центр" : "Продолжить"}
          </button>
        </div>
      </header>
      {c.progress && (
        <div role="status" className="cr-progress">
          Расчёт встреч · {c.progress.done} / {c.progress.total}
          <progress max={c.progress.total || 1} value={c.progress.done} />
        </div>
      )}
      {c.milestones.at(-1)?.date === c.date &&
        c.milestones.at(-1)?.matches != null && (
          <div className="cr-card">
            Итоги недели · сыграно матчей: {c.milestones.at(-1)?.matches}
          </div>
        )}
      {c.error && <p role="alert">{c.error}</p>}
      <nav className="cr-tabs" aria-label="Карьера">
        {["Обзор", "Календарь", "Состав", "Сохранения"].map((t) => (
          <button aria-pressed={t === tab} key={t} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
        <button onClick={board}>Тактики ↗</button>
      </nav>
      {tab === "Календарь" ? (
        <Calendar c={c} />
      ) : tab === "Состав" ? (
        <Squad c={c} />
      ) : tab === "Сохранения" ? (
        <Saves c={c} act={act} enabled={enabled} />
      ) : (
        <div className="cr-grid">
          <section className="cr-card cr-next">
            <small>Ближайшая встреча</small>
            <h2>
              {c.teams[next.teams[0]]} <em>—</em> {c.teams[next.teams[1]]}
            </h2>
            <p>{date(next.date)} · Выставочный BO1 · Депо</p>
            <button onClick={() => setTab("Календарь")}>
              Открыть календарь
            </button>
          </section>
          <section className="cr-card">
            <h2>Игровой мир</h2>
            <Facts
              rows={[
                { name: "База", value: c.source + " · ред. " + c.edition },
                {
                  name: "Охват",
                  value:
                    scopes[c.scope] +
                    (c.scope === "fast"
                      ? " · " + c.regions.map((r) => regions[r]).join(", ")
                      : ""),
                },
                {
                  name: "Команд в календаре",
                  value: String(Object.keys(c.teams).length),
                },
                { name: "Сыграно матчей", value: String(c.history.length) },
              ]}
            />
          </section>
        </div>
      )}
    </section>
  );
}
