import { useState } from "react";
import { MatchReport } from "./CareerForms";
import {
  date,
  dayAt,
  isoDay,
  monday,
  weekdays,
  fixtureName,
  fixtureScore,
  type Career,
  type Fixture,
} from "./careerData";
import { Dialog, Glyph, Heading, Tabs } from "./GameUI";
export function Calendar({ c, initial,tournament }: { c: Career; initial: string; tournament:(edition:string)=>void }) {
  const [selected, select] = useState(initial),
    [mode, setMode] = useState("Месяц"),
    [filter, setFilter] = useState("club"),
    [report, setReport] = useState<Fixture | null>(null);
  const month = selected.slice(0, 7),
    first = month + "-01";
  const end = dayAt(first);
  end.setUTCMonth(end.getUTCMonth() + 1, 0);
  const start = monday(mode === "Неделя" ? selected : first);
  const count =
    mode === "Неделя"
      ? 7
      : 7 *
        Math.ceil(
          (((dayAt(first).getUTCDay() + 6) % 7) + end.getUTCDate()) / 7,
        );
  const events = [...c.history, ...c.queue].filter(
    (e) => filter === "all" || e.kind === "review" || e.teams.includes(c.team),
  );
  const shift = (n: number) => {
    const d = dayAt(mode === "Неделя" ? selected : first);
    if (mode === "Неделя") d.setUTCDate(d.getUTCDate() + 7 * n);
    else d.setUTCMonth(d.getUTCMonth() + n);
    select(isoDay(d));
  };
  const buttons = (rows: Fixture[]) =>
    rows.map((e) => (
      <div className="day-agenda-item" key={e.id}>
        <small className="event-time">
          {date(e.date)} · {e.kind === "match" ? "BO"+(e.bestOf ?? 1) : "Клуб"}
        </small>
        <h3>{fixtureName(c, e)}</h3>
        {e.edition && <button className="link-button" onClick={()=>tournament(e.edition!)}>{e.title}</button>}
        {e.agenda?.map(a=><p key={a.edition+a.title}><button className="link-button" onClick={()=>tournament(a.edition)}>{a.tournament}</button> · {a.title}</p>)}
        {e.score && (
          <button
            className="btn sm"
            aria-label={"Протокол " + fixtureScore(e)}
            onClick={() => setReport(e)}
          >
            {fixtureScore(e)} <Glyph name="report-analytics" />
          </button>
        )}
      </div>
    ));
  const today = events.filter((e) => e.date === selected),
    notes = c.milestones.filter((m) => m.date === selected);
  return (
    <>
      <Heading title="Календарь" sub={c.club + " · матчи и события клуба"}>
        <Tabs items={["Месяц", "Неделя"]} value={mode} change={setMode} />
      </Heading>
      <div className="filter-bar">
        <label>
          Показать{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="club">Моя команда</option>
            <option value="all">Весь мир</option>
          </select>
        </label>
        <button className="btn sm" onClick={() => select(c.date)}>
          Сегодня
        </button>
      </div>
      <div className="calendar-layout">
        <section className="surface">
          <div className="calendar-toolbar">
            <button
              className="icon-button"
              aria-label="Назад по календарю"
              onClick={() => shift(-1)}
            >
              <Glyph name="chevron-left" />
            </button>
            <h2>
              {dayAt(selected).toLocaleDateString("ru", {
                month: "long",
                year: "numeric",
                timeZone: "UTC",
              })}
            </h2>
            <button
              className="icon-button"
              aria-label="Вперёд по календарю"
              onClick={() => shift(1)}
            >
              <Glyph name="chevron-right" />
            </button>
          </div>
          <div className="calendar-weekdays">
            {weekdays.map((w) => (
              <span key={w}>{w}</span>
            ))}
          </div>
          <div className="calendar-grid">
            {Array.from({ length: count }, (_, i) => {
              const d = isoDay(dayAt(start, i));
              const matches = events.filter((e) => e.date === d);
              const milestone = c.milestones.find((m) => m.date === d);
              return (
                <button
                  key={d}
                  aria-label={date(d)}
                  aria-pressed={d === selected}
                  onClick={() => select(d)}
                  className={
                    "calendar-day " +
                    (d === selected ? "selected " : "") +
                    (d === c.date ? "today " : "") +
                    (d.startsWith(month) ? "" : "other")
                  }
                >
                  <span className="date-number">{+d.slice(-2)}</span>
                  {matches.slice(0, 2).map((e) => (
                    <span key={e.id} className="cal-event match">
                      {fixtureName(c, e)}
                    </span>
                  ))}
                  {matches.length > 2 && <small>+{matches.length - 2}</small>}
                  {milestone && (
                    <span className="cal-event">{milestone.title}</span>
                  )}
                </button>
              );
            })}
          </div>
        </section>
        <section className="surface day-details mobile-open">
          <div className="panel-head">
            <h2>{date(selected)}</h2>
          </div>
          {buttons(today)}
          {notes.map((m) => (
            <div className="day-agenda-item" key={m.id||m.title}>
              {m.title}
            </div>
          ))}
          {!today.length && !notes.length && (
            <p className="panel-body muted">Событий нет.</p>
          )}
        </section>
      </div>
      {events.some((e) => e.score && e.date.startsWith(month)) && (
        <section className="surface completed-fixtures">
          <div className="panel-head">
            <h2>Результаты месяца</h2>
          </div>
          {buttons(
            events.filter((e) => e.score && e.date.startsWith(month)).reverse(),
          )}
        </section>
      )}
      {report && (
        <Dialog title="Результат встречи" close={() => setReport(null)}>
          <MatchReport
            event={report}
            teams={c.teams}
            close={() => setReport(null)}
          />
        </Dialog>
      )}
    </>
  );
}
