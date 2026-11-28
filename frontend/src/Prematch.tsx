import { useState } from "react";
import { Avatar, LineupPortrait } from "./SceneIdentity";
import { Tabs } from "./GameUI";
import { ForecastLine, type Quote } from "./ForecastLine";
import { date, fixtureMap, useData, type Career, type Fixture, type Profile, type Scene } from "./careerData";
import "./prematch.css";

type Past = {id:string;date:string;teams:string[];score:number[];winnerTeamId:string};
type Club = {players:string[];version:number|null;rank:number|null;points:number|null;recent:Past[];
  publicRatings:{player:string;rating:number;maps:number;source:string}[]};
type Prep = {day:string;clubs:Record<string,Club>;publication:string|null;h2h:Past[];
  evidence:Record<string,Record<string,{games:number;wins:number;picks:number;bans:number}>>;mapProbabilities:Record<string,number>;
  advice:{author:string;minimum:number;strongest:string|null;weakest:string|null}|null;
  staff:{duty:string;name:string;due:string}[]; forecasts:Quote[];calibration:{count:number;brier:number|null}};
const tabs=["План на серию","Состав и готовность","Соперник","Маппул","Сравнение","Прогнозы"];
export default function Prematch({c,scene,event,revision,open,calendar,tournament,board,play}:{
  c:Career;scene:Scene;event:Fixture;revision:number;open:(p:Profile)=>void;calendar:(d:string)=>void;
  tournament:(id:string)=>void;board:()=>void;play?:()=>void;
}) {
  const [tab,setTab] = useState(tabs[0]);
  const request = useData<Prep>("/api/career/"+c.id+"/prematch/"+event.id,revision);
  if(request.error) return <p role="alert">{request.error} <button onClick={request.reload}>Повторить</button></p>;
  if(!request.data) return <p role="status">Загружаем предматчевую подготовку…</p>;
  const data=request.data;
  const teams = event.teams.includes(c.team) ? [c.team,event.teams.find(t=>t!==c.team)!] : event.teams;
  const name=(id:string)=>scene.teams[id]?.name || c.teams[id] || id;
  const mapName=(key:string)=>fixtureMap({...event,mapId:key,bestOf:undefined});
  const results=(rows:Past[])=>rows.length ? rows.map(r=><p key={r.id}><time>{date(r.date)}</time> · {r.teams.map(name).join(" — ")} · {r.score?.join(" : ")}</p>) : <p>Завершённых встреч в доступной истории нет.</p>;
  const lineup=(tid:string)=> <section key={tid} className="surface panel-body"><h2>{name(tid)}</h2><small>{data.clubs[tid].version ? "Турнирная заявка · версия "+data.clubs[tid].version : "Пятёрка редакции карьеры"}</small>
    {data.clubs[tid].players.map(pid=>{const p=scene.players[pid], own=c.roster.find(r=>r.id===pid);
      const rating=data.clubs[tid].publicRatings.find(r=>r.player===pid);
      return <button className="entity-button" key={pid} onClick={()=>open({group:"players",id:pid})}>
        {p && <LineupPortrait id={pid} name={p.name} visual={p.visual}/>}<span><strong>{p?.name || pid}</strong>
        <small>{own ? "Форма "+own.form+" · готовность "+(100-own.fatigue)+"%" : rating ? "Публичный рейтинг "+rating.rating.toFixed(2)+" · карт "+rating.maps : "Публичной оценки нет"}</small></span></button>})}</section>;
  const rival=teams[1], maps=Object.keys(data.mapProbabilities);
  const ranked=maps.map(m=>({m,...data.evidence[rival][m]})).filter(r=>r.games>0).sort((a,b)=>(b.wins+2)/(b.games+4)-(a.wins+2)/(a.games+4));
  return <div className="cp-module">
    <button className="cp-back" onClick={()=>event.edition ? tournament(event.edition) : calendar(event.date)}>{event.title || "Календарь"}</button>
    <div className="cp-prematch-hero">{teams.map((t,i)=><div key={t} className={"cp-prematch-team"+(i?" cp-opponent":"")}><Avatar name={name(t)} club {...scene.teams[t]?.visual}/><div>
      <span>{t===c.team?"ВАША КОМАНДА":teams.includes(c.team)?"СОПЕРНИК":"УЧАСТНИК"}</span><h1>{name(t)}</h1><p>VRS {data.clubs[t].rank ? "#"+data.clubs[t].rank : "—"} · {data.clubs[t].recent.slice(0,5).map(r=>r.winnerTeamId===t?"W":"L").join(" ") || "Истории пока нет"}</p></div></div>)}
      <div className="cp-versus"><span>BO{event.bestOf || 1} · MR12</span><b>VS</b><span>{date(event.date)}</span></div></div>
    <div className="cp-prematch-toolbar"><span>{event.title || "Выставочный матч"} · сведения на {date(data.day)}</span>
      {play ? <button className="btn primary" onClick={play}>{event.bestOf?"Перейти к veto":"В матч-центр"}</button> : <button className="btn" onClick={()=>calendar(event.date)}>Открыть календарь</button>}</div>
    <Tabs items={tabs} value={tab} change={setTab}/>
    {tab===tabs[0] && <div className="cp-two-col"><section className="surface panel-body"><h2>Подготовка к серии</h2>
      {ranked.length ? <p>Самая успешная карта {name(rival)} по доступным результатам · {mapName(ranked[0].m)} ({ranked[0].wins} побед из {ranked[0].games}).</p> : <p>У штаба пока нет сыгранных соперником карт для оценки маппула.</p>}
      {data.staff.map(s=><p key={s.duty}>{s.duty==="opponent"?"Анализ соперника":"Подготовка veto"} · {s.name} · {date(s.due)}</p>)}
      {data.advice && <p>Отчёт · {data.advice.author}. {data.advice.strongest ? "Подготовить ответ на "+mapName(data.advice.strongest)+"." : "Для рекомендации нужно не менее "+data.advice.minimum+" карт соперника на одной карте."}
        {data.advice.weakest && " Кандидат для своего пика · "+mapName(data.advice.weakest)+"."}</p>}
      {c.team===teams[0] && <button className="btn" onClick={board}>Открыть редактор тактик</button>}{event.edition && <button className="btn" onClick={()=>tournament(event.edition!)}>Регламент и заявка</button>}</section>
      <section className="surface panel-body"><h2>Последние очные встречи</h2>{results(data.h2h)}</section></div>}
    {tab===tabs[1] && <div className="cp-two-col">{teams.map(lineup)}</div>}
    {tab===tabs[2] && <div className="cp-two-col">{lineup(rival)}<section className="surface panel-body"><h2>Последние результаты соперника</h2>{results(data.clubs[rival].recent)}</section></div>}
    {tab===tabs[3] && <section className="surface panel-body"><h2>Маппул · по {date(data.day)}</h2>{maps.map(m=><article key={m} className="cp-map-rate"><strong>{mapName(m)}</strong>
      {teams.map(t=>{const v=data.evidence[t][m];return <p key={t}>{name(t)} · {v.games?Math.round(100*v.wins/v.games)+"%":"—"} · {v.wins}/{v.games} · пики {v.picks} / баны {v.bans}</p>})}</article>)}</section>}
    {tab===tabs[4] && <div className="cp-two-col">{teams.map(t=><section key={t} className="surface panel-body"><h2>{name(t)}</h2><p>Очки VRS · {data.clubs[t].points ?? "—"}{data.publication && " · "+date(data.publication)}</p>{results(data.clubs[t].recent)}</section>)}</div>}
    {tab===tabs[5] && <ForecastLine quotes={data.forecasts} names={c.teams} calibration={data.calibration}/>}
  </div>;
}
