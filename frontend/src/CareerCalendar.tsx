import { useCareerViewTab } from "./CareerViewTab";
import { useEffect, useState } from "react";
import { FixtureTeams, EditionLink } from "./CareerIdentity";
import { MatchReport } from "./CareerForms";
import {
  date,
  dayAt,
  isoDay,
  monday,
  weekdays,
  useData,
  fixtureName,
  fixtureScore,
  type Career,
  type Fixture,
} from "./careerData";
import { Dialog, Glyph, Heading, Tabs } from "./GameUI";
export function Calendar({ c, selected, select, filter, setFilter, tournament, prepare, revision, training }: {
  c: Career; selected: string; select:(day:string)=>void; filter:string; setFilter:(scope:string)=>void;
  prepare:(id:string)=>void; revision:number; tournament:(edition:string)=>void; training:(day:string)=>void;
}) {
  const [mode, setMode] = useCareerViewTab(matchMedia("(max-width:700px)").matches ? "Повестка" : "Месяц");
  const [report,setReport] = useState<Fixture | null>(null);
  const [jumpTo, setJumpTo] = useState("");
  useEffect(() => {
    if (!jumpTo || mode !== "Повестка") return;
    document.getElementById("agenda-fixture-"+jumpTo)?.focus();
    setJumpTo("");
  }, [jumpTo,mode,selected]);
  const next = c.queue.find(f=>f.kind==="match" && !f.pcw && f.teams.includes(c.team) && f.date>=c.date);
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
  const preparation = useData<Record<string,string[]>>("/api/career/"+c.id+"/training-calendar?since="+start+"&count="+count,revision);
  const sessions=preparation.data?.[selected]||[];
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
      <div className="day-agenda-item" key={e.id} id={mode==="Повестка" ? "agenda-fixture-"+e.id : undefined} tabIndex={-1}>
        <small className="event-time">
          <Glyph name={e.kind === "match" ? "crosshair" : "calendar"}/>{date(e.date)} · {e.kind === "match" ? "BO"+(e.bestOf ?? 1) : "Клуб"}
        </small>
        <h3>{e.kind === "match" ? <>{e.pcw && "Пракк · "}<FixtureTeams teams={e.teams} names={c.teams}/></> : fixtureName(c,e)}</h3>
        {e.edition && <EditionLink id={e.edition}>{e.title}</EditionLink>}
        {e.agenda?.map(a=><p key={a.edition+a.title}><button className="link-button" onClick={()=>tournament(a.edition)}>{a.tournament}</button> · {a.title}</p>)}
        {!fixtureScore(e) && !e.pcw && e.kind === "match" && <button className="btn sm" onClick={()=>prepare(e.id)}>Предматчевая подготовка и линия</button>}
        {fixtureScore(e) && (
          <button
            className="btn sm"
            aria-label={"Протокол " + fixtureScore(e)}
            onClick={() => setReport(e)}
          >
            {fixtureScore(e)} <Glyph name="report-analytics" />
            <small>{e.simulation?.mode === "round" ? "По раундам" : "Подробный"}</small>
          </button>
        )}
      </div>
    ));
  const today = events.filter((e) => e.date === selected),
    notes = c.milestones.filter((m) => m.date === selected);
  return (
    <>
      <Heading title="Календарь" eyebrow={c.club+" / Сезон "+c.date.slice(0,4)} sub="Матчи, турниры и подготовка команды">
        <Tabs items={["Месяц", "Неделя", "Повестка"]} value={mode} change={setMode} />
      </Heading>
      <div className="filter-bar calendar-filters">
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
        {next && <button className="btn sm" onClick={()=>{select(next.date);setMode("Повестка");setJumpTo(next.id)}}>
          <Glyph name="crosshair"/> Ближайший матч клуба · {date(next.date)}
        </button>}
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
          {mode === "Повестка" ? <div className="calendar-agenda">{Array.from({length:end.getUTCDate()},(_,i)=>{
            const d=isoDay(dayAt(first,i)), games=events.filter(e=>e.date===d), notes=c.milestones.filter(m=>m.date===d), sessions=preparation.data?.[d] || [];
            if(!games.length && !notes.length && !sessions.length && d!==selected)return null;
            return <article key={d} data-selected={d===selected}><button className="agenda-date" onClick={()=>select(d)}><b>{d.slice(-2)}</b><small>{date(d)}</small></button><div>
              {buttons(games)}{notes.map((m,i)=><p key={i}>{m.title}</p>)}{sessions.length>0 && <button onClick={()=>training(d)}>Тренировки · {sessions.length}</button>}
              {!games.length && !notes.length && !sessions.length && <small>Событий нет</small>}
            </div></article>;
          })}</div> : <><div className="calendar-weekdays">
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
                  {!!preparation.data?.[d]?.length && <span className="cal-event">{preparation.data[d][0]}{preparation.data[d].length>1?" +"+(preparation.data[d].length-1):""}</span>}
                  {milestone && (
                    <span className="cal-event">{milestone.title}</span>
                  )}
                </button>
              );
            })}
          </div></>}
        </section>
        {mode!=="Повестка" && <section className="surface day-details mobile-open">
          <div className="panel-head">
            <h2>{date(selected)}</h2>
          </div>
          {buttons(today)}
          {preparation.error && <p role="alert">{preparation.error} <button className="btn sm" onClick={preparation.reload}>Повторить</button></p>}
          {!!sessions.length && <div className="day-agenda-item"><h3>Подготовка команды</h3>{sessions.map((s,i)=><p key={i}>{s}</p>)}<button className="btn sm" onClick={()=>training(selected)}>Открыть расписание</button></div>}
          {notes.map((m) => (
            <div className="day-agenda-item" key={m.id||m.title}>
              {m.title}
            </div>
          ))}
          {!today.length && !notes.length && !sessions.length && (
            <p className="panel-body muted">Событий нет.</p>
          )}
        </section>}
      </div>
      {mode!=="Повестка" && events.some((e) => fixtureScore(e) && e.date.startsWith(month)) && (
        <section className="surface completed-fixtures">
          <div className="panel-head">
            <h2>Результаты месяца</h2>
          </div>
          {buttons(
            events.filter((e) => fixtureScore(e) && e.date.startsWith(month)).reverse(),
          )}
        </section>
      )}
      {report && (
        <Dialog title="Результат встречи" close={() => setReport(null)}>
          <MatchReport careerId={c.id}
            event={report}
            teams={c.teams}
            close={() => setReport(null)}
          />
        </Dialog>
      )}
    </>
  );
}
