import { useState } from "react";
import Radar from "./Radar";
import type { Frame, View } from "./session";
import type { RadarPlayback } from "./playback";
import "./match.css";

type Side = "CT" | "T";
type Point = { x: number; y: number };
export interface MatchView {
  rules: string; round: number; phase: string; clock: number;
  teams: string[]; sides: Side[]; score: number[];
  history: { round: number; winner: number; side: Side; reason: string; score: number[]; duration: number }[];
  stats: { id: string; name: string; club: number; team: Side; role: string; k: number; d: number;
    a: number; hs: number; damage: number; opening: number; kast: number; spent: number; clutches: number }[];
  bomb: (Point & { carrier: string | null; site: string | null }) | null;
  action: { player: string; kind: string; start: number; end: number } | null;
  effects: (Point & {kind: string; sx: number; sy: number; land: number; end: number; start: number; radius: number})[];
  shots: (Point & {tx: number; ty: number; tick: number})[];
  kills: {id: number; player: string; target: string; weapon: string; head: boolean}[];
  plans: Partial<Record<Side,{site:string; style:string; buy:string}>>;
  remaining: number; pending: boolean; call: string | null; calls: string[];
  feedback: {player:string; id:number; round:number; text:string}[];
}
const phases: Record<string,string> = { freeze:"Подготовка", live:"В игре", planted:"C4 установлена",
  result:"Раунд завершён", timeout:"Тактический тайм-аут", finished:"Матч завершён" };
const tabs = ["Составы","Статистика","Раунды","Журнал"] as const;
const clock = (ticks:number) => {
  const seconds = Math.ceil(ticks/10);
  return Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");
};
type Props = { frame: Frame; playback: RadarPlayback; connected: boolean; enabled: boolean;
  act: (name:string, value?:number|string)=>Promise<void>; setView: (v:View)=>void };

export default function MatchCenter({frame,playback,connected,enabled,act,setView}:Props) {
  const world=frame.world, m=world.match!;
  const [tab,setTab]=useState<typeof tabs[number]>("Составы");
  const [selected,select]=useState<string|null>(null);
  const [seed,setSeed]=useState(String(world.seed));
  const [nextCall,setNextCall]=useState(m.calls[0]);
  const selectedAgent=world.agents.find(a=>a.id===selected);
  const name=(id:string)=>m.stats.find(p=>p.id===id)?.name ?? id;
  const finished=m.phase==="finished", timeout=m.phase==="timeout";
  const rounds=m.history.length;
  return <article className="match-center">
    <header className="match-title"><div><span className="eyebrow">МАТЧ-ЦЕНТР</span><h1>Депо <small>/ BO1</small></h1></div>
      <span className="match-format">Выставочный матч<br/>Тестовые составы</span></header>
    <section className="scoreboard" aria-label="Счёт матча">
      {m.teams.map((club,i)=><div key={club} className={'club club-'+i}>
        <span className="club-side">{m.sides[i]} · {i===0?"Ваша команда":"Соперник"}</span>
        <strong>{club}</strong><b>{m.score[i]}</b>
      </div>)}
      <div className="round-clock"><small>РАУНД {m.round}</small>
        <b>{finished?"ФИНАЛ":timeout?"ПАУЗА":m.phase==="result"?"ИТОГ":clock(m.clock)}</b>
        <span>{phases[m.phase]}</span></div>
    </section>
    {finished && <p className="match-result">Победитель матча — <strong>{m.teams[m.score[0]>m.score[1]?0:1]}</strong></p>}
    <div className="match-grid">
      <div className="match-main">
        <section className="panel">
          <div className="maphead"><div className="mapname"><h2>Тактический радар</h2></div>
            <select aria-label="Режим обзора" value={world.view} onChange={e=>{select(null);setView(e.target.value as View);}}>
              <option value="full">Полная карта · анализ</option><option value="T">Видимость T</option><option value="CT">Видимость CT</option>
            </select></div>
          <Radar frame={frame} playback={playback} connected={connected} selected={selectedAgent?.id??null} onSelect={select}/>
          <div className="match-legend"><span>● CT</span><span>◆ T</span><span>▣ C4</span>
            <span>{selectedAgent ? selectedAgent.name+" · "+selectedAgent.status : "Выберите игрока на карте"}</span></div>
        </section>
        <section className="panel match-data"><nav aria-label="Данные матча">
          {tabs.map(t=><button key={t} aria-pressed={tab===t} onClick={()=>setTab(t)}>{t}</button>)}</nav>
          {tab==="Составы" && <div className="lineups">{m.teams.map((club,i)=><div key={club}><h3>{club} <small>{m.sides[i]}</small></h3>
            {m.stats.filter(row=>row.club===i).map(row=>{
              const a=world.agents.find(p=>p.id===row.id);
              return <button className="player-card" key={row.id} aria-pressed={selected===row.id} disabled={!a} onClick={()=>select(row.id)}>
                <b>{row.name}<small>{row.role}</small></b>
                <span>{a ? a.alive ? a.weapon : "Выбыл" : "Вне обзора"}
                  <small>{a?.hp!==undefined ? a.hp+" HP · "+a.cash+" $" : "—"}</small></span>
              </button>})}</div>)}</div>}
          {tab==="Составы" && selectedAgent && <p className="inventory"><b>{selectedAgent.name}</b> · {selectedAgent.status}
            {selectedAgent.hp!==undefined && <> · Броня {selectedAgent.armor} · Патроны {selectedAgent.ammo}/{selectedAgent.reserve}
              {selectedAgent.kit && " · Набор обезвреживания"} · Гранаты {selectedAgent.utility?.join(", ")||"—"}</>}</p>}
          {tab==="Статистика" && <div className="table-scroll" tabIndex={0} aria-label="Таблица статистики">
            <table><thead><tr>{["Игрок","K","A","D","ADR","KAST","HS","Первые","Клатчи","Расходы"].map(h=><th key={h}>{h}</th>)}</tr></thead>
            <tbody>{m.stats.map(p=><tr key={p.id}><th>{p.name}<small>{m.teams[p.club]}</small></th>
              {[p.k,p.a,p.d,(p.damage/Math.max(1,m.round)).toFixed(1),rounds?Math.round(100*p.kast/rounds)+"%":"—",p.hs,p.opening,p.clutches,p.spent+" $"].map((v,i)=><td key={i}>{v}</td>)}</tr>)}</tbody></table></div>}
          {tab==="Раунды" && <div className="round-list">{!rounds && <p>История появится после первого раунда.</p>}
            {m.history.slice().reverse().map(r=><div key={r.round}><small>R{r.round}</small><b>{r.score.join(" : ")}</b><span>{m.teams[r.winner]} · {r.side}</span><span>{r.reason}</span></div>)}</div>}
          {tab==="Журнал" && <ol className="match-events">{world.events.slice().reverse().map((e,i)=><li key={e.tick+"-"+i}><time>{clock(e.tick)}</time>{e.text}</li>)}</ol>}
        </section>
      </div>
      <aside className="match-aside">
        <section className="panel live-feed"><h2>Лента убийств</h2>
          {!m.kills.length && <p>В этом раунде ещё нет фрагов.</p>}
          {m.kills.slice().reverse().map(k=><div key={k.id}><b>{name(k.player)}</b><span>{k.weapon}{k.head?" · HS":""}</span><b>{name(k.target)}</b></div>)}</section>
        <section className="panel coaching"><h2>Скамейка тренера</h2><p>Север · осталось тайм-аутов <b>{m.remaining} / 3</b></p>
          {!timeout ? <button disabled={!enabled||finished||m.pending||m.remaining===0} onClick={()=>act("timeout")}>{m.pending?"Тайм-аут запрошен":"Запросить тайм-аут"}</button> :
          <><h3>Обратная связь</h3>{m.feedback.length ? m.feedback.map(f=><blockquote key={f.player}><b>{f.player} · R{f.round}</b>{f.text}</blockquote>) :
            <p>{world.view!=="full" && world.view!==m.sides[0]?"Переключитесь на обзор своей команды.":"У состава пока нет наблюдений."}</p>}
            <label>План на ближайший раунд<select value={nextCall} onChange={e=>setNextCall(e.target.value)}>{m.calls.map(c=><option key={c}>{c}</option>)}</select></label>
            <button disabled={!enabled} onClick={()=>act("call",nextCall)}>Передать колл</button>
            {m.call && <p role="status">Принято · {m.call}</p>}
            <button className="primary" disabled={!enabled} onClick={()=>act("resume")}>Завершить тайм-аут</button></>}
          {Object.entries(m.plans).map(([side,p])=><p className="plan-line" key={side}><b>{side} · IGL</b> {p.style} · {p.site} · {p.buy}</p>)}
        </section>
        <section className="panel broadcast"><h2>Просмотр</h2>
          <button className="primary" disabled={!enabled||finished||timeout} onClick={()=>act(frame.running?"pause":"start")}>{frame.running?"Пауза просмотра":"Запустить"}</button>
          <div className="speed-list">{[1,2,4,8,128].map(n=><button key={n} disabled={!enabled} aria-pressed={frame.speed===n} onClick={()=>act("speed",n)}>{n===128?"Быстро":n+"×"}</button>)}</div>
          <div className="slots"><button disabled={!enabled} onClick={()=>act("save")}>Сохранить</button><button disabled={!enabled||!frame.hasSave} onClick={()=>act("load")}>Загрузить</button></div>
          <details><summary>Новый сценарий</summary><label>Seed<input value={seed} inputMode="numeric" onChange={e=>setSeed(e.target.value)}/></label>
            <div className="slots">{[["match","Новый BO1"],["reset","Стенд R0"]].map(([kind,label])=><button key={kind}
              disabled={!enabled||!/^\d+$/.test(seed)||Number(seed)>2147483647} onClick={()=>act(kind,Number(seed))}>{label}</button>)}</div></details>
        </section>
      </aside>
    </div>
  </article>
}
