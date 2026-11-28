import { useData, type Report, type Decision } from "./careerData";
import type { Quote } from "./ForecastLine";
import type { Directory } from "./CompetitionCenter";
import { roles } from "./databaseModel";
import "./home.css";
import { useState } from "react";
import { Avatar, LineupPortrait } from "./SceneIdentity";
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
  edition?:string;
};
export function letters(c: Career): Letter[] {
  const box: Letter[] = c.milestones.map((m) => ({
    edition:m.edition,
    id: m.id || "club/" + m.date + "/" + m.title,
    date: m.date,
    title: m.title,
    from: m.sender || c.organization || c.club,
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
  tournament,
}: {
  box: Letter[];
  read: string[];
  selected: Letter | null;
  select: (id: string | null) => void;
  calendar: (d: string) => void;
  tournament:(id:string)=>void;
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
                {(selected.edition || selected.event?.edition) && <button className="btn primary" onClick={()=>tournament((selected.edition || selected.event?.edition)!)}>Открыть турнир</button>}
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

export function Dashboard({c,scene,box,go,calendar,open,letter,prepare,tournament,resolve,revision}: {
  c:Career;scene:Scene;box:Letter[];go:(page:string)=>void;calendar:(day:string)=>void;
  open:(p:Profile)=>void;letter:(id:string)=>void;prepare:(id:string)=>void;tournament:(id:string)=>void;
  resolve:(row:Decision)=>void;revision:number;
}) {
  const next = c.queue.find(e=>e.kind==="match" && !e.pcw && e.teams.includes(c.team));
  const recent = c.history.filter(e=>e.kind==="match" && e.teams.includes(c.team)).slice(-3).reverse();
  const plan = useData<{forecasts:Quote[]}> (next ? "/api/career/"+c.id+"/prematch/"+next.id : null,revision);
  const directory = useData<Directory>(!next && c.competitions ? "/api/career/"+c.id+"/competitions" : null,revision);
  const upcoming = directory.data?.editions.filter(e=>["accepted","confirmed","qualified","locked","playing"].includes(e.entries[c.team]) && e.status!=="finished")
    .sort((a,b)=>a.start.localeCompare(b.start))[0];
  const last = useData<Report>(recent.length ? "/api/career/"+c.id+"/report/"+recent[0].id : null);
  const mvp = last.data?.performance.players.find(p=>p.player===last.data?.performance.mvp);
  const start=monday(c.date);
  const training=useData<Record<string,string[]>>("/api/career/"+c.id+"/training-calendar?since="+start+"&count=7",revision);
  const quote=plan.data?.forecasts.at(-1);
  const team=(id:string)=>scene.teams[id]?.name || c.teams[id] || id;
  return <div className="manager-home"><div className="home-caption"><span className="eyebrow">{c.character} · {position(c.mode)}</span><h1>Кабинет менеджера</h1></div>
    <div className="home-layout"><div className="home-main"><section className="match-hero">
      <div className="hero-topline"><button className="event-wordmark" onClick={()=>next?.edition ? tournament(next.edition) : upcoming ? tournament(upcoming.id) : calendar(next?.date || c.date)}>{next?.title || upcoming?.title || "Календарь команды"}</button>
        {next && <span>BO{next.bestOf || 1} · MR12</span>}</div>
      <h2>{next ? "Следующий матч" : upcoming ? "Следующий турнир" : "Расписание команды"}</h2>
      <div className="hero-versus">{(next?.teams || [c.team]).map((tid,i)=><div key={tid} className="hero-team">
        <button onClick={()=>open({group:"teams",id:tid})}><Avatar name={team(tid)} club {...scene.teams[tid]?.visual}/><strong>{team(tid)}</strong></button>
        {quote && <small>{Math.round(100*quote.probability[i])}%</small>}</div>)}
        <div className="versus-time"><strong>{next ? "VS" : upcoming ? date(upcoming.start) : "—"}</strong><small>{next ? date(next.date) : "Соперник ещё не определён"}</small></div></div>
      {quote && <><div className="probability-line"><i style={{width:100*quote.probability[0]+"%"}}/></div><div className="hero-odds">{quote.odds.map((v,i)=><small key={i}>{team(quote.teams[i])} · {v.toFixed(2)}</small>)}</div></>}
      <button className="btn primary" onClick={()=>next ? prepare(next.id) : upcoming ? tournament(upcoming.id) : calendar(c.date)}>{next ? "Подготовка к матчу" : upcoming ? "Открыть турнир" : "Открыть календарь"}</button>
    </section><section><div className="section-heading"><h2>Основная пятёрка</h2><button className="text-button" onClick={()=>go("Состав")}>Весь состав</button></div>
      <div className="lineup-five">{c.roster.map(p=><button className="home-player" key={p.id} onClick={()=>open({group:"players",id:p.id})}>
        <div className="portrait"><LineupPortrait id={p.id} name={p.name} visual={p.visual}/></div><div className="home-player-info"><strong>{p.name}</strong><small>{roles[p.role] || p.role}</small>
        <div className="readiness-label">Готовность</div><Readiness fatigue={p.fatigue}/></div></button>)}</div></section>
      <section><div className="section-heading"><h2>Неделя команды</h2><button className="text-button" onClick={()=>calendar(c.date)}>Открыть календарь</button></div>
        <div className="week-strip">{weekdays.map((d,i)=>{const day=isoDay(dayAt(start,i));
          const e=[...recent,...c.queue].find(g=>g.date===day && g.kind==="match" && g.teams.includes(c.team));
          return <button className={"week-day"+(day===c.date?" today":"")} onClick={()=>calendar(day)} key={day}><small>{d}</small><b>{Number(day.slice(-2))}</b><span>{e?fixtureName(c,e):training.data?.[day]?.join(" · ") || "Свободно"}</span></button>})}</div>
      </section></div><aside className="home-aside">
        <section className="panel"><div className="section-heading"><h2>Решения тренера</h2><b>{c.attention.length}</b></div>
          {c.attention.slice(0,3).map(a=><div key={a.id} className="decision-item"><small>{date(a.due)}</small><h3>{a.title}</h3><p>{a.detail}</p><button className="btn" onClick={()=>resolve(a)}>Открыть решение</button></div>)}
          {!c.attention.length && <p>Обязательных решений сейчас нет.</p>}
          {box[0] && <div className="decision-item"><small>{box[0].from}</small><h3>{box[0].title}</h3><button className="btn" onClick={()=>letter(box[0].id)}>Открыть письмо</button></div>}
        </section><section className="panel"><h2>Последние встречи</h2>{recent.map(e=><div className="result-mini" key={e.id}><button onClick={()=>calendar(e.date)}>{team(e.teams.find(t=>t!==c.team)!)}<small>{date(e.date)}</small></button><strong>{fixtureScore(e)}</strong></div>)}
          {!recent.length && <p>В этой карьере команда ещё не сыграла официальный матч.</p>}</section>
        <section className="panel"><h2>MVP последней встречи</h2>{mvp ? <button className="focus-player" onClick={()=>open({group:"players",id:mvp.player})}>
          <LineupPortrait id={mvp.player} name={mvp.name} visual={{...scene.players[mvp.player]?.visual, kit:scene.players[mvp.player]?.visual.kit?.id===mvp.teamId ? scene.players[mvp.player].visual.kit : null}}/>
          <span><strong>{mvp.name}</strong><small>Impact {mvp.impact?.toFixed(2)} · {mvp.rounds} раундов</small></span></button>
          : <p>{last.error || (recent.length && !last.data ? "Загружаем протокол…" : "Для определения MVP пока недостаточно данных.")}</p>}</section>
      </aside></div></div>;
}
