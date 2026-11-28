import { useState } from "react";
import { date, fixtureMap, useData, type Career, type Scene } from "./careerData";
import { Dialog } from "./GameUI";
import { MatchReport } from "./CareerForms";
import "./report.css";

type Subject = "players" | "teams";
type Row = {
  fixture: string; date: string; edition: string | null; tournament: string | null;
  index: number; mapId: string | null; team: string | null; opponent: string | null;
  score: Record<string, number> | null; won: boolean | null; rounds: number; playerRounds: number;
  counts: Record<string, number | null>; impact: number | null; mapMvp: string | null; seriesMvp: string | null;
};
type Result = {version: string; asOf: string; rows: Row[]};
type Props = {c: Career; scene: Scene; group: Subject; id: string; revision: number};

const labelMap = (key: string | null) => key ? fixtureMap({ mapId:key, kind:"match", id:"", date:"", teams:[] }) : "Карта неизвестна";
function rate(rows: Row[], field: string, scale=1) {
  const known = rows.filter(r=>r.counts[field] != null && r.playerRounds > 0);
  const samples = known.reduce((n,r)=>n+r.playerRounds,0);
  return samples ? (scale * known.reduce((n,r)=>n+r.counts[field]!,0)/samples).toFixed(1) : "—";
}

function Summary({result, name}: {result: Result; name: string}) {
  const known = result.rows.filter(r=>r.won !== null);
  const wins = known.filter(r=>r.won).length;
  return <article className="report-panel"><h3>{name}</h3><p>{result.rows.length} карт · {result.rows.reduce((n,r)=>n+r.rounds,0)} раундов</p>
    <dl className="history-metrics"><div><dt>Победы</dt><dd>{known.length ? wins+"/"+known.length : "—"}</dd></div>
      <div><dt>ADR</dt><dd>{rate(result.rows,"damage")}</dd></div>
      <div><dt>KAST</dt><dd>{rate(result.rows,"kast",100)}{result.rows.some(r=>r.counts.kast!=null && r.playerRounds>0) ? "%" : ""}</dd></div></dl>
    <small>ADR и KAST учитывают только карты с записанным показателем.</small></article>;
}

export default function ProfileHistory({c,scene,group,id,revision}: Props) {
  const [days,setDays] = useState("30");
  const [map,setMap] = useState("");
  const [event,setEvent] = useState("");
  const [other,setOther] = useState("");
  const [selected,setSelected] = useState("");
  const since = new Date(c.date+"T00:00:00Z");
  since.setUTCDate(since.getUTCDate()-Number(days)+1);
  const query = new URLSearchParams({since: days === "0" ? c.start : since.toISOString().slice(0,10),map_id:map,edition:event});
  const path = (key:string) => "/api/career/"+c.id+"/performance/"+group+"/"+encodeURIComponent(key)+"?"+query;
  const current = useData<Result>(path(id),revision);
  const compare = useData<Result>(other ? path(other) : null,revision);
  const directory = scene[group];
  const editions = new Map(c.history.filter(f=>f.edition).map(f=>[f.edition!, f.title || f.edition!]));
  const fixture = c.history.find(f=>f.id===selected);
  const maps = new Set(c.history.flatMap(f=>f.maps?.map(m=>m.map) || [f.mapId || "depo"]));
  return <section className="match-report history-profile">
    <h2>История выступлений</h2><p>Официальные матчи карьеры · по {date(c.date)}</p>
    <div className="history-filters">
      <label>Период<select value={days} onChange={e=>setDays(e.target.value)}><option value="7">7 дней</option><option value="30">30 дней</option><option value="0">Вся карьера</option></select></label>
      <label>Карта<select value={map} onChange={e=>setMap(e.target.value)}><option value="">Все карты</option>{Array.from(maps).sort().map(m=><option key={m} value={m}>{labelMap(m)}</option>)}</select></label>
      <label>Турнир<select value={event} onChange={e=>setEvent(e.target.value)}><option value="">Все турниры</option>{Array.from(editions,([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      <label>Сравнить с<select value={other} onChange={e=>setOther(e.target.value)}><option value="">Без сравнения</option>{Object.values(directory).filter(e=>e.id!==id).sort((a,b)=>a.name.localeCompare(b.name)).map(e=><option key={e.id} value={e.id}>{e.name}</option>)}</select></label>
    </div>
    <div className="report-lineups">{[current,...(other?[compare]:[])].map((request,i)=>request.error ? <p key={i} role="alert">{request.error} <button onClick={request.reload}>Повторить</button></p>
      : request.data ? <Summary key={i} result={request.data} name={directory[i ? other : id]?.name || id}/> : <p key={i} role="status">Загружаем историю…</p>)}</div>
    {current.data && (current.data.rows.length ? <div className="report-table" tabIndex={0} role="region" aria-label="История выступлений"><table><caption>Карты и результаты</caption>
      <thead><tr>{["Дата","Команда на дату","Соперник","Турнир","Карта","Итог","K / D / A","ADR","Impact","MVP"].map(t=><th key={t}>{t}</th>)}</tr></thead>
      <tbody>{current.data.rows.map(r=><tr key={r.fixture+"/"+r.index}><th><button onClick={()=>setSelected(r.fixture)}>{date(r.date)}</button></th>
        <td>{r.team ? scene.teams[r.team]?.name || r.team : "—"}</td><td>{r.opponent ? scene.teams[r.opponent]?.name || r.opponent : "—"}</td><td>{r.tournament || "Встреча календаря"}</td>
        <td>{labelMap(r.mapId)}</td><td>{r.score && r.team && r.opponent ? r.score[r.team]+" : "+r.score[r.opponent] : "—"}</td>
        <td>{["k","d","a"].map(k=>r.counts[k] ?? "—").join(" / ")}</td><td>{rate([r],"damage")}</td><td>{r.impact?.toFixed(2) ?? "—"}</td>
        <td>{r.mapMvp ? scene.players[r.mapMvp]?.name || r.mapMvp : "—"}</td></tr>)}</tbody></table></div> : <p>В выбранном периоде и турнире нет завершённых карт для этого профиля.</p>)}
    {fixture && <Dialog title="Результат встречи" close={()=>setSelected("")}><MatchReport event={fixture} careerId={c.id} teams={c.teams} close={()=>setSelected("")}/></Dialog>}
  </section>;
}
