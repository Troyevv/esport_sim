import { fixtureMap } from "./careerData";
import { Fragment, useState } from "react";
import { Avatar } from "./SceneIdentity";
import { Glyph, Heading } from "./GameUI";
import {
  date,
  dayAt,
  isoDay,
  monday,
  fixtureName,
  fixtureScore,
  weekdays,
  position,
  type Career,
  type Scene,
  type Fixture,
  type Profile,
} from "./careerData";
import { Readiness } from "./GameUI";
export type Letter = {
  id: string;
  date: string;
  title: string;
  from: string;
  body: string;
  event?: Fixture;
};
export function letters(c: Career): Letter[] {
  const box: Letter[] = c.milestones.map((m) => ({
    id: "club/" + m.date + "/" + m.title,
    date: m.date,
    title: m.title,
    from: c.organization || c.club,
    body:m.body || (
      m.matches === null
        ? c.character + " · " + position(c.mode) + " · " + c.club
        : "Сыграно матчей за неделю: " + m.matches + "."),
  }));
  for (const e of c.history.filter((e) => e.teams.includes(c.team)))
    box.push({
      id: "result/" + e.id,
      date: e.date,
      title: "Результат встречи",
      from: "Матч-центр",
      body: fixtureName(c, e) + " · " + fixtureScore(e),
      event: e,
    });
  const next = c.queue.find((e) => e.teams.includes(c.team));
  if (next)
    box.push({
      id: "fixture/" + next.id,
      date: c.date,
      title: "Ближайший соперник",
      from: "Календарь",
      body:
        fixtureName(c, next) + " · " + date(next.date) + " · "+(next.title||"Выставочный")+" BO" + (next.bestOf ?? 1) + ".",
      event: next,
    });
  return box.reverse().sort((a, b) => b.date.localeCompare(a.date));
}
export function Inbox({
  box,
  read,
  selected,
  select,
  calendar,
}: {
  box: Letter[];
  read: string[];
  selected: Letter | null;
  select: (id: string | null) => void;
  calendar: (d: string) => void;
}) {
  const [filter, setFilter] = useState(false);
  const filtered = box.filter(
    (m) => !filter || !read.includes(m.id) || selected?.id === m.id,
  );
  return (
    <>
      <Heading title="Входящие" sub="Сообщения клуба и протоколы встреч" />
      <section
        className={"surface inbox-layout " + (selected ? "message-open" : "")}
      >
        <div className="inbox-list">
          <div className="inbox-controls">
            <button
              className="btn sm"
              aria-pressed={filter}
              onClick={() => setFilter(!filter)}
            >
              {filter ? "Непрочитанные" : "Все сообщения"}
            </button>
          </div>
          {filtered.map((m) => (
            <button
              key={m.id}
              className={
                "inbox-item " + (selected?.id === m.id ? "active" : "")
              }
              onClick={() => select(m.id)}
            >
              <span className="sender">{m.from}</span>
              <strong>{m.title}</strong>
              <small>{date(m.date)}</small>
              {!read.includes(m.id) && (
                <span className="unread-dot" aria-label="Не прочитано" />
              )}
            </button>
          ))}
          {!filtered.length && (
            <p className="panel-body muted">Новых сообщений нет.</p>
          )}
        </div>
        <article className="message-content">
          {selected ? (
            <>
              <button className="btn mobile-back" onClick={() => select(null)}>
                Все сообщения
              </button>
              <span className="pill info">Уведомление</span>
              <h2>{selected.title}</h2>
              <div className="message-author">
                <span className="manager-avatar">
                  <Glyph name="inbox" />
                </span>
                <span>
                  <strong>{selected.from}</strong>
                  <small>{date(selected.date)}</small>
                </span>
              </div>
              <p className="message-body">{selected.body}</p>
              <div className="message-actions">
                <button
                  className="btn"
                  onClick={() =>
                    calendar(selected.event?.date || selected.date)
                  }
                >
                  Открыть календарь
                </button>
              </div>
            </>
          ) : (
            <p className="muted">Выберите сообщение.</p>
          )}
        </article>
      </section>
    </>
  );
}

export function Dashboard({
  c,
  scene,
  box,
  go,
  calendar,
  open,
  letter,
}: {
  c: Career;
  scene: Scene;
  box: Letter[];
  go: (s: string) => void;
  calendar: (d: string) => void;
  open: (p: Profile) => void;
  letter: (id: string) => void;
}) {
  const next = c.queue.find((e) => e.teams.includes(c.team)),
    start = monday(c.date);
  const played = c.history.filter((e) => e.teams.includes(c.team)),
    latest = played.at(-1);
  const metrics = [
    ["users", "Сила состава", c.teamRating, "Командный OVR"],
    [
      "calendar",
      "До матча",
      next ? Math.round((+dayAt(next.date) - +dayAt(c.date)) / 86400000) : "—",
      "Дней по календарю",
    ],
    ["trophy", "Сыграно матчей", played.length, "В текущей карьере"],
    [
      "building",
      "Команд в календаре",
      Object.keys(c.teams).length,
      "Охват симуляции",
    ],
  ] as const;
  return (
    <>
      <Heading
        title="Кабинет менеджера"
        sub={c.character + " · " + position(c.mode)}
      >
        <span className="pill accented">{c.club}</span>
      </Heading>
      <div className="dashboard-top">
        <section className="surface match-preview">
          <div className="panel-head">
            <span className="eyebrow">Следующий матч</span>
            {next && (
              <span className="match-preview-header">
                {date(next.date)} <span className="pill">BO{next.bestOf ?? 1}</span>
              </span>
            )}
          </div>
          {next ? (
            <>
              <div className="match-matchup">
                {next.teams.map((tid, i) => (
                  <Fragment key={tid}>
                    {i === 1 && (
                      <div>
                        <div className="versus">VS</div>
                        <div className="match-meta">{fixtureMap(next)}</div>
                      </div>
                    )}
                    <button
                      className="match-team"
                      onClick={() => open({ group: "teams", id: tid })}
                    >
                      <Avatar
                        name={c.teams[tid]}
                        {...scene.teams[tid]?.visual}
                      />
                      <strong>{c.teams[tid]}</strong>
                      <small>
                        {tid === c.team ? "Ваша команда" : "Соперник"}
                      </small>
                    </button>
                  </Fragment>
                ))}
              </div>
              <div className="match-preview-foot">
                <span>{next.title||"Выставочная встреча"}</span>
                <button className="btn" onClick={() => calendar(next.date)}>
                  Открыть календарь <Glyph name="calendar" />
                </button>
              </div>
            </>
          ) : (
            <p className="panel-body">Предстоящих встреч нет.</p>
          )}
        </section>
        <section className="surface priority-card">
          <span className="eyebrow">Внимание тренера</span>
          <h2>{box[0]?.title || "Клубная почта"}</h2>
          <p>{box[0]?.body}</p>
          <button
            className="btn primary"
            onClick={() => (box[0] ? letter(box[0].id) : go("Входящие"))}
          >
            Открыть письмо <Glyph name="inbox" />
          </button>
        </section>
      </div>
      <section className="metrics-strip">
        {metrics.map(([icon, title, value, caption]) => (
          <div className="metric" key={title}>
            <div className="metric-label">
              <Glyph name={icon} />
              {title}
            </div>
            <div className="metric-main">
              <strong>{value}</strong>
            </div>
            <div className="metric-foot">{caption}</div>
          </div>
        ))}
      </section>
      <div className="dashboard-middle">
        <section className="surface">
          <div className="panel-head">
            <h2>На этой неделе</h2>
            <button className="link-button" onClick={() => calendar(c.date)}>
              В календарь
            </button>
          </div>
          <div className="week-grid">
            {weekdays.map((w, i) => {
              const d = isoDay(dayAt(start, i));
              const e = [...c.history, ...c.queue].find(
                (e) =>
                  e.date === d &&
                  (e.kind === "review" || e.teams.includes(c.team)),
              );
              return (
                <button
                  key={w}
                  className={"week-day " + (d === c.date ? "today" : "")}
                  onClick={() => calendar(d)}
                >
                  <span className="dayname">{w}</span>
                  <span className="daynumber">{+d.slice(-2)}</span>
                  <span className="event-name">
                    {e ? fixtureName(c, e) : "Свободный день"}
                  </span>
                </button>
              );
            })}
          </div>
        </section>
        <section className="surface">
          <div className="panel-head">
            <h2>Входящие</h2>
            <button className="link-button" onClick={() => go("Входящие")}>
              Все
            </button>
          </div>
          {box.slice(0, 3).map((m) => (
            <button
              className="message-preview"
              key={m.id}
              onClick={() => letter(m.id)}
            >
              <span className="message-symbol">
                <Glyph name="mail" />
              </span>
              <span>
                <strong>{m.title}</strong>
                <small>{m.from}</small>
              </span>
            </button>
          ))}
        </section>
      </div>
      <div className="dashboard-bottom">
        <section className="surface">
          <div className="panel-head">
            <h2>Основной состав</h2>
            <button className="link-button" onClick={() => go("Состав")}>
              Весь состав
            </button>
          </div>
          <div className="table-wrap">
            <table className="simple-table compact">
              <thead>
                <tr>
                  <th>Игрок</th>
                  <th>OVR</th>
                  <th>Готовность</th>
                  <th>Мораль</th>
                  <th>Форма</th>
                </tr>
              </thead>
              <tbody>
                {c.roster.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <button
                        className="player-identity"
                        onClick={() => open({ group: "players", id: p.id })}
                      >
                        <Avatar name={p.name} {...p.visual} />
                        <strong>{p.name}</strong>
                      </button>
                    </td>
                    <td className="mono accent">{p.ratings[p.role] ?? "—"}</td>
                    <td>
                      <Readiness fatigue={p.fatigue} />
                    </td>
                    <td>{p.morale}</td>
                    <td>{p.form}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="surface">
          <div className="panel-head">
            <h2>Последняя встреча</h2>
          </div>
          <div className="panel-body">
            {latest ? (
              <button
                className="link-button"
                onClick={() => calendar(latest.date)}
              >
                {fixtureName(c, latest)} · {fixtureScore(latest)}
              </button>
            ) : (
              <p className="muted">
                Команда ещё не завершила свой первый матч.
              </p>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
