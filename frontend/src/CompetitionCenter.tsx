import { useState } from "react";
import { date, useData, type Act, type Career, type Scene } from "./careerData";
import { Heading, Tabs } from "./GameUI";
import { Load, MatchReport } from "./CareerForms";
import { Avatar } from "./SceneIdentity";
import "./competitions.css";

type Entry = { version:number; players:string[]; reserves:string[]; coach:string|null; date:string; reason:string|null };
type Game = { slots:(string|null|[string,number])[]; winner?:string; loser?:string; label:string; round:number;
  fixture?:string; score?:number[]; date?:string; historical?:boolean; bye?:boolean };
type Draw = { teams:string[]; format:string; games:Game[] };
type Phase = { name:string; format:string; start:string; end:string; bestOf:number; advance:number; finalBO?:number };
type Stats = {name:string; team:string; k:number; d:number; a:number; damage:number; rounds:number};
type Edition = {id:string;title:string;organizer:string;source:string;place:string;region:string;prestige:number;
  opens:string;lock:string;start:string;end:string;year:number;simulated:boolean;admission:string;status:string;
  capacity:number;rules:{pool:string[];timeouts:number;core:number;reserves:number;id:string};stages:Phase[];
  draws:Draw[][];prizes:number[];entries:Record<string,string>;registrations:Record<string,Entry[]>;stats:Record<string,Stats>;
  placements?:string[];payouts?:Record<string,number>;mvp?:string;reason?:string; feeds?:string; snapshot?:string; seedSnapshot?:string };
type Ranking = {rank:number;regional:number;region:string;name:string;points:number;nicks:string[];team?:string};
type Directory = { editions:Edition[]; available:string[]; snapshots:Record<string,Ranking[]>;live?:{date:string;rows:Ranking[];completeWindow:boolean} };
type Props = {c:Career;scene:Scene;act:Act;enabled:boolean;revision:number;rankings:boolean};
const status:Record<string,string> = {registration:"Регистрация",playing:"Идёт турнир",finished:"Завершён",cancelled:"Отменён",invited:"Приглашение",accepted:"Участие подтверждено",locked:"Состав зафиксирован",declined:"Отказ",qualified:"Отбор пройден",missed:"Пропущен дедлайн",notSelected:"Вне списка участников",qualifiedElsewhere:"Уже квалифицировались"};
const formats:Record<string,string> = {swiss:"Швейцарская система",single:"Single elimination",double:"Double elimination",gsl:"Группы GSL",roundRobin:"Круговая система"};
const admission:Record<string,string> = {open:"Открытая квалификация",qualified:"Победители квалификаций",invitation:"Приглашения VRS",rankedOpen:"Открытая заявка · отбор по VRS"};
const money = (n:number) => n.toLocaleString("ru-RU")+" $";
const span = (a:string,b:string) => a===b?date(a):date(a)+" — "+date(b);

function Rankings({data}: {data:Directory}) {
  const dates=Object.keys(data.snapshots).sort().reverse();
  const [publication,pick]=useState(dates[0]),[region,setRegion]=useState("Global"),[query,search]=useState("");
  const rows=publication==="live"?data.live?.rows||[]:data.snapshots[publication];
  return <><Heading title="Valve Regional Standings" sub="Составы, очки и история публикаций Valve"/>
    <div className="filter-bar"><label>Снимок <select value={publication} onChange={e=>pick(e.target.value)}>
      {data.live && <option value="live">Расчёт карьеры · {date(data.live.date)}</option>}
      {dates.map(d=><option key={d} value={d}>{date(d)}</option>)}</select></label>
      <label>Регион <select value={region} onChange={e=>setRegion(e.target.value)}>{["Global","Europe","Americas","Asia"].map(r=><option key={r}>{r}</option>)}</select></label>
      <label>Команда <input type="search" value={query} onChange={e=>search(e.target.value)} /></label></div>
    {publication==="live" && !data.live?.completeWindow && <p className="panel-body">Расчёт охватывает только сыгранные в карьере соревнования. Предыстория за 180 дней неполна.</p>}
    <section className="surface table-wrap"><table className="simple-table"><thead><tr><th>Место</th><th>Команда / состав</th><th>Регион</th><th>Очки</th></tr></thead>
      <tbody>{rows.filter(r=>(region==="Global"||r.region===region)&&r.name.toLowerCase().includes(query.toLowerCase())).map(r=><tr key={r.rank}><td>{region==="Global"?r.rank:r.regional}</td>
        <td><strong>{r.name}</strong><small className="tc-sub">{r.nicks.join(" · ")}</small></td><td>{r.region}</td><td className="mono accent">{r.points}</td></tr>)}</tbody></table></section></>;
}

function Registration({event,c,scene,available,act,enabled}:Omit<Props,"rankings"|"revision">&{event:Edition;available:string[]}) {
  const versions=event.registrations[c.team]||[], old=versions.at(-1);
  const [five,setFive]=useState(old?.players||c.roster.map(p=>p.id)),[res,setRes]=useState(old?.reserves||[]),
    [coach,setCoach]=useState(old?.coach||""),[reason,setReason]=useState(""),[alert,setAlert]=useState("");
  const state=event.entries[c.team],before=c.date>=event.opens && c.date<event.lock,
    locked=state==="locked" && event.status==="playing", allowed=event.region==="Global"||event.region===c.region;
  const send=async(action:string)=>{
    const ok=await act("career-entry",{edition:event.id,action,players:five,reserves:res,coach:coach||null,reason});
    setAlert(ok?"Изменения сохранены.":"Сервер отклонил заявку. Проверьте состав, сроки и пересечение дат.");
  };
  const candidates=locked && old ? [...old.players,...old.reserves]:available;
  const toggle=(id:string,target:"main"|"reserve")=>{
    const main=five.filter(p=>p!==id),bench=res.filter(p=>p!==id);
    setFive(target==="main" && !five.includes(id)?[...main,id]:main);
    setRes(target==="reserve" && !res.includes(id)?[...bench,id]:bench);
  };
  return <section className="surface panel-body tc-entry"><h2>Заявка · {c.club}</h2><p>{status[state]||admission[event.admission]} · Регистрация с {date(event.opens)}. Фиксация {date(event.lock)}.</p>
    {!allowed && <p>Ограничение по региону: {event.region}.</p>}
    {before && allowed && (state==="invited"||(!state||state==="declined")&&["open","rankedOpen"].includes(event.admission)) && <button className="btn primary" disabled={!enabled} onClick={()=>send("accept")}>{state==="invited"?"Принять приглашение":"Заявиться на участие"}</button>}
    {before && ["accepted","invited"].includes(state) && <button className="btn" disabled={!enabled} onClick={()=>send("decline")}>Отказаться от участия</button>}
    {((before && ["accepted","qualified"].includes(state)) || (locked && !!old?.reserves.length)) && <>
      <div className="tc-entry-players">{candidates.map(p=><div key={p}><strong>{scene.players[p]?.name||p}</strong>
        <button className="btn sm" aria-pressed={five.includes(p)} onClick={()=>toggle(p,"main")}>Основа</button>
        <button className="btn sm" aria-pressed={res.includes(p)} onClick={()=>toggle(p,"reserve")}>Запас</button></div>)}</div>
      <label>Тренер <select disabled={locked} value={coach} onChange={e=>setCoach(e.target.value)}><option value="">Без тренера</option>{Object.values(scene.staff).filter(s=>s.team===c.team).map(s=><option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      {locked && <label>Основание экстренной замены <input value={reason} maxLength={240} onChange={e=>setReason(e.target.value)} /></label>}
      <p>Основа {five.length}/5 · Запас {res.length}/{event.rules.reserves}</p>
      <button className="btn primary" disabled={!enabled||five.length!==5||res.length>event.rules.reserves||(locked&&!reason.trim())} onClick={()=>send(locked?"replace":"submit")}>{locked?"Подать экстренную замену":"Сохранить заявку"}</button></>}
    {versions.map(v=><p key={v.version}><b>Версия {v.version}</b> · {date(v.date)} · {v.players.map(p=>scene.players[p]?.name).join(", ")} {v.reason && " · "+v.reason}</p>)}
    {alert && <p role="status">{alert}</p>}</section>;
}

function GameDraw({draw,c}:{draw:Draw;c:Career}){
  const slot=(s:Game["slots"][number])=>{
    if(s===null)return "Свободный слот";
    if(typeof s==="string")return c.teams[s]||s;
    const parent=draw.games[s[1]],t=s[0]==="winner"?parent.winner:parent.loser;
    return t?c.teams[t]:(s[0]==="winner"?"Победитель":"Проигравший")+" матча "+(s[1]+1);
  };
  return <div className="tc-games">{draw.games.map((g,n)=>!g.bye && <article key={n}><small>{g.label} · № {n+1}{g.date && " · "+date(g.date)}</small>
    {g.slots.map((s,i)=><div key={i}><b>{slot(s)}</b><span>{g.score?.[i]??"—"}</span></div>)}{g.historical&&<small>До начала карьеры</small>}</article>)}</div>;
}

export function CompetitionCenter(props:Props) {
  const {c,scene,enabled,revision,rankings}=props;
  const res=useData<Directory>("/api/career/"+c.id+"/competitions",revision);
  const [picked,select]=useState(""),[tab,show]=useState("Обзор"),[archive,setArchive]=useState(false);
  const [report,openReport]=useState("");
  if(res.error||!res.data)return <Load {...res}/>;
  const data=res.data, event=data.editions.find(e=>e.id===picked);
  if(rankings)return <Rankings data={data}/>;
  if(!event) return <><Heading title="Соревнования" sub="Календарь профессиональной сцены"/>
    <Tabs items={["Календарь турниров","Архив"]} value={archive?"Архив":"Календарь турниров"} change={s=>setArchive(s==="Архив")}/>
    <div className="tc-list">{data.editions.filter(e=>archive?e.status==="finished":e.status!=="finished").sort((a,b)=>a.start.localeCompare(b.start)).map(e=>
      <button className="surface tc-card" key={e.id} onClick={()=>{select(e.id);show("Обзор")}}>
        <small>{e.organizer} · {e.region} · {status[e.status]}</small><strong>{e.title}</strong><span>{span(e.start,e.end)}</span>
        <footer>{e.prizes.length?money(e.prizes.reduce((a,b)=>a+b,0)):"Отбор"} · {e.capacity} команд{e.simulated?" · Игровой сезон":""}</footer>
        {e.placements?.[0] && <b>Победитель · {c.teams[e.placements[0]]}</b>}</button>)}</div>
    {archive && !data.editions.some(e=>e.status==="finished") && <p>В этой карьере пока нет завершённых турниров.</p>}</>;
  const rows=Object.entries(event.stats).sort(([,a],[,b])=>b.damage/b.rounds-a.damage/a.rounds);
  const teamStats:Record<string,{k:number;d:number;damage:number}>={};
  for(const [,r] of rows){const t=teamStats[r.team]||={k:0,d:0,damage:0};t.k+=r.k;t.d+=r.d;t.damage+=r.damage;}
  const fixture=c.history.find(e=>e.id===report);
  return <><button className="link-button" onClick={()=>select("")}>← Все соревнования</button>
    <Heading title={event.title} sub={event.place+" · "+span(event.start,event.end)}/>
    <div className="tc-facts surface">{[[event.organizer,"Организатор"],[money(event.prizes.reduce((a,b)=>a+b,0)),"Призовой фонд"],
      [event.capacity,"Команд"],["Тир "+event.prestige,"Игровой престиж"]].map(([a,b])=><div key={b}><small>{b}</small><b>{b==="Организатор" && event.organizer!=="CCT" && <img src={event.organizer==="ESL"?"/competitions/esl.svg":"/competitions/pgl.png"} alt=""/>}{a}</b></div>)}</div>
    <Tabs items={["Обзор","Участники","Сетки","Матчи","Статистика","Моя заявка"]} value={tab} change={show}/>
    {tab==="Обзор" && <section className="surface panel-body"><h2>Регламент</h2><p>{status[event.status]} · {admission[event.admission]} · {event.simulated?"Игровой сезон":"Календарь организатора"}.</p>
      <p>Фиксация состава {date(event.lock)}. Запасных до {event.rules.reserves}. Тактических тайм-аутов на карту: {event.rules.timeouts}.</p>
      <p>{event.rules.pool.map(m=>m.slice(3)).join(" · ")}</p>{event.stages.map(s=><p key={s.name}><b>{s.name}</b> · {formats[s.format]} · BO{s.bestOf}{s.format==="swiss"&&s.bestOf===1?" / BO3":""}{s.finalBO?" · финал BO"+s.finalBO:""}</p>)}
      <p><a href={event.source} target="_blank" rel="noreferrer">Публикация организатора ↗</a></p>{event.reason&&<p>{event.reason}</p>}
      {!!event.prizes.length && <details><summary>Распределение призовых</summary>{event.prizes.map((n,i)=><p key={i}>{i+1} место · {money(n)} {event.placements?.[i]&&" · "+c.teams[event.placements[i]]}</p>)}</details>}</section>}
    {tab==="Моя заявка" && <Registration key={picked+":"+event.entries[c.team]+":"+event.registrations[c.team]?.length} {...props} enabled={enabled && res.revision===revision} event={event} available={data.available}/>}
    {tab==="Участники" && <section className="surface panel-body">{Object.keys(event.entries).length===0&&<p>Заявок пока нет.</p>}{Object.entries(event.entries).map(([t,state])=>{
      const entry=event.registrations[t]?.at(-1);return <details key={t} className="tc-team"><summary><Avatar name={c.teams[t]} {...scene.teams[t]?.visual}/><b>{c.teams[t]}</b> · {status[state]}</summary>
        {entry && <><p>{entry.players.map(p=>scene.players[p]?.name).join(" · ")}</p><p>Запасные: {entry.reserves.map(p=>scene.players[p]?.name).join(", ")||"нет"} · Тренер: {entry.coach?scene.staff[entry.coach]?.name:"не заявлен"} · Версия {entry.version}</p></>}</details>})}</section>}
    {tab==="Сетки" && <>{!event.draws.length&&<p>Жеребьёвка после фиксации составов {date(event.lock)}.</p>}{event.draws.map((draws,i)=><section key={i}><h2>{event.stages[i].name}</h2>{draws.map((d,j)=><details className="surface panel-body" key={j} open={i===event.draws.length-1}><summary>{draws.length>1?"Группа "+(j+1):formats[d.format]} · {d.teams.length} команд</summary>
      {(d.format==="swiss"||d.format==="roundRobin"||draws.length>1)&&<table className="simple-table"><thead><tr><th>Команда</th><th>В</th><th>П</th></tr></thead><tbody>{d.teams.map(t=>[t,d.games.filter(g=>g.winner===t&&!g.bye).length,d.games.filter(g=>g.loser===t).length] as const).sort((a,b)=>b[1]-a[1]||a[2]-b[2]).map(([t,w,l])=><tr key={t}><td>{c.teams[t]}</td><td>{w}</td><td>{l}</td></tr>)}</tbody></table>}
      <GameDraw draw={d} c={c}/></details>)}</section>)}</>}
    {tab==="Матчи" && <section className="surface panel-body">{[...c.history,...c.queue].filter(e=>e.edition===picked).map(e=><div key={e.id} className="tc-result"><small>{date(e.date)} · BO{e.bestOf}</small><b>{e.teams.map(t=>c.teams[t]).join(" — ")}</b>{e.score&&<button className="btn sm" onClick={()=>openReport(e.id)}>{e.score.join(" : ")} · Протокол</button>}</div>)}{!event.draws.length&&<p>Расписание появится после жеребьёвки.</p>}{fixture && <MatchReport event={fixture} teams={c.teams} close={()=>openReport("")}/>}</section>}
    {tab==="Статистика" && <section className="surface panel-body">{!rows.length?<p>После первой завершённой в карьере серии здесь появится статистика по протоколам карт.</p>:<>
      {event.mvp&&<p>MVP турнира · <b>{event.stats[event.mvp].name}</b> · максимальный ADR</p>}
      <div className="table-wrap"><table className="simple-table"><thead><tr><th>Игрок</th><th>Команда</th><th>K</th><th>D</th><th>A</th><th>ADR</th></tr></thead>
      <tbody>{rows.map(([p,r])=><tr key={p}><td>{r.name}</td><td>{c.teams[r.team]}</td><td>{r.k}</td><td>{r.d}</td><td>{r.a}</td><td>{(r.damage/r.rounds).toFixed(1)}</td></tr>)}</tbody></table></div>
      <h2>Команды</h2>{Object.entries(teamStats).map(([t,r])=><p key={t}>{c.teams[t]} · {r.k} убийств · {r.d} смертей · {r.damage} урона</p>)}</>}</section>}</>;
}
