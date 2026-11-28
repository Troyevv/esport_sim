import { useState } from "react";
import type { Directory } from "./CompetitionCenter";
import { MatchReport } from "./CareerForms";
import { Dialog } from "./GameUI";
import { date, fixtureScore, useData, type Career, type Scene } from "./careerData";

export default function TeamRecord({c,scene,id,tab,revision}: {c:Career;scene:Scene;id:string;tab:string;revision:number}) {
  const fixtures = tab === "Календарь и результаты";
  const directory = useData<Directory>(!fixtures && c.competitions ? "/api/career/"+c.id+"/competitions" : null,revision);
  const [selected,setSelected] = useState("");
  const fixture = c.history.find(f=>f.id===selected);
  if (fixtures) {
    const games = [...c.history,...c.queue].filter(f=>f.kind==="match" && f.teams.includes(id)).sort((a,b)=>b.date.localeCompare(a.date));
    return <section className="surface panel-body"><h2>{tab}</h2>{games.map(f=><div key={f.id} className="staff-line">
      <time>{date(f.date)}</time><span>{f.teams.map(t=>c.teams[t] || scene.teams[t]?.name || t).join(" — ")} · {f.title || "Встреча календаря"}</span>
      {fixtureScore(f) ? <button onClick={()=>setSelected(f.id)}>{fixtureScore(f)} · Протокол</button> : <span>Запланирован</span>}</div>)}
      {!games.length && <p>Для команды ещё нет встреч в календаре карьеры.</p>}
      {fixture && <Dialog title="Результат встречи" close={()=>setSelected("")}><MatchReport careerId={c.id} event={fixture} teams={c.teams} close={()=>setSelected("")}/></Dialog>}</section>;
  }
  if (!c.competitions) return <p className="surface panel-body">Для этой карьеры турнирный календарь не ведётся.</p>;
  if (directory.error) return <p role="alert">{directory.error} <button onClick={directory.reload}>Повторить</button></p>;
  if (!directory.data) return <p role="status">Загружаем турнирную историю…</p>;
  const data = directory.data;
  if (tab === "VRS") {
    const entries = Object.entries(data.snapshots).filter(([d])=>d<=c.date).sort(([a],[b])=>b.localeCompare(a)).flatMap(([d,rows])=>
      rows.filter(r=>r.team===id).map(r=>({d,r})));
    return <section className="surface panel-body"><h2>Публикации VRS</h2>{entries.map(({d,r})=><div key={d} className="staff-line">
      <time>{date(d)}</time><strong>#{r.rank} · {r.points} очк.</strong><span>{r.nicks.join(" · ")}</span></div>)}
      {!entries.length && <p>В опубликованных снимках нет идентифицированного состава команды.</p>}</section>;
  }
  if (tab === "История составов") {
    const lineups = data.editions.flatMap(e=>(e.registrations[id] || []).filter(v=>v.date<=c.date).map(v=>({v,e})))
      .sort((a,b)=>b.v.date.localeCompare(a.v.date));
    return <section className="surface panel-body"><h2>Зарегистрированные составы</h2>{lineups.map(({v,e})=><article className="staff-line" key={e.id+"/"+v.version}>
      <time>{date(v.date)}</time><div><strong>{e.title} · версия {v.version}</strong><p>{v.players.map(p=>scene.players[p]?.name || p).join(" · ")}</p>
      {v.reserves.length>0 && <p>Запасные · {v.reserves.map(p=>scene.players[p]?.name || p).join(" · ")}</p>}
      {v.coach && <p>Тренер · {scene.staff[v.coach]?.name || v.coach}</p>}</div></article>)}
      {!lineups.length && <p>Сохранённых заявок на турниры пока нет.</p>}</section>;
  }
  const results = data.editions.filter(e=>e.status==="finished" && e.placements?.includes(id));
  return <section className="surface panel-body"><h2>Турнирные достижения</h2>{results.map(e=><p key={e.id}>{e.title} · {e.placements!.indexOf(id)+1} место · {date(e.end)}</p>)}
    {!results.length && <p>В завершённых турнирах карьеры места команды ещё не зафиксированы.</p>}</section>;
}
