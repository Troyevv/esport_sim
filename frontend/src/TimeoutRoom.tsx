import { useState } from "react";
import type { MatchView } from "./MatchCenter";
import { GamePortrait } from "./GamePortrait";
import "./timeout.css";

type Topic = {id:number; round:number; kind:string; text:string};
export interface Room {
  seconds: number;
  players: Record<string,{state:string; morale:string; fatigue:string; topics:Topic[]; order?:{kind:string}|null; head?:string}>;
  history: {action:string; target:string; replies:{player:string; text:string}[]}[];
}
const actions: Record<string,string> = {
  opinion:"Запросить мнение", discuss:"Обсудить тактическую проблему", praise:"Похвалить",
  mistake:"Указать на ошибку", critique:"Конструктивно раскритиковать", harsh:"Жёстко раскритиковать",
  motivate:"Мотивировать", calm:"Успокоить", support:"Поддержать после неудачи", focus:"Попросить сосредоточиться",
  discipline:"Потребовать дисциплины", order:"Дать индивидуальное указание",
};
const orders: Record<string,string> = {
  position:"Сменить позицию", cautious:"Играть осторожнее", aggressive:"Взять инициативу", hold:"Удерживать направление",
  discipline:"Избегать поджимов", support:"Поддерживать напарника", utility:"Отдать приоритет гранатам",
  trade:"Играть на размен", tempo:"Ускорить исполнение",
};
type Props = {match:MatchView; map:string; enabled:boolean; saved:boolean; openBoard:()=>void;
  act:(name:string,value?:number|string|object)=>Promise<boolean>};
export default function TimeoutRoom({match:m,map,enabled,saved,act,openBoard}:Props) {
  const room=m.room!;
  const club=m.clubs.find(c=>c.id===m.coachTeamId)!;
  const five=m.stats.filter(p=>p.teamId===club.id);
  const [target,setTarget]=useState("team"), [topic,setTopic]=useState("");
  const [action,setAction]=useState("opinion"), [order,setOrder]=useState("cautious");
  const [site,setSite]=useState("A"), [mate,setMate]=useState(""), [call,setCall]=useState(m.calls[0]);
  const selected=five.find(p=>p.id===target);
  const subjects=five.filter(p=>!selected || p.id===target).flatMap(p=>room.players[p.id].topics.map(t=>({...t,speaker:p.id,name:p.name,key:p.id+"/"+t.id})));
  const fact=subjects.find(t=>t.key===topic);
  const partners=five.filter(p=>p.id!==target);
  const select=(id:string)=>{setTarget(id); setTopic(""); setMate(""); if(id==="team" && action==="order") setAction("opinion")};
  const cost=action==="order" || action==="discuss" ? 15 : 10;
  const send=()=>act("address",{target,action,subject:fact?.id??0,speaker:fact?.speaker??"",order,site,mate:mate||partners[0].id});
  return <section className="timeout-room coaching" aria-label="Тактический перерыв">
    <header className="timeout-head"><div><span>{map} · {club.side} · Раунд {m.round}</span>
      <h1>Тактический перерыв</h1><p>{m.clubs[0].name} <b>{m.score.join(" : ")}</b> {m.clubs[1].name}</p></div>
      <div className="round-clock"><small>ПАУЗА</small><strong>{room.seconds} с</strong><small>на разговор</small></div>
    </header>
    <div className="timeout-line"><h2>{club.name}</h2><span>Тайм-ауты <b>{m.remaining} / {m.timeoutLimit}</b></span></div>
    <div className="bench-five">{five.map(p=>{
      const state=room.players[p.id];
      return <button key={p.id} aria-pressed={p.id===target} onClick={()=>select(p.id)}>
        <GamePortrait name={p.name} head={p.visual?.head || state.head} kit={p.visual?.kit || {id:club.id,name:club.name}} showShoulders/>
        <span className="bench-identity"><small>{p.role}</small><strong>{p.name}</strong></span>
        <span className="bench-state">{state.state}</span><small>{state.fatigue} · Мораль: {state.morale.toLowerCase()}</small>
        <span className="bench-kda">K / D / A <b>{p.k} / {p.d} / {p.a}</b></span>
      </button>;
    })}</div>
    <div className="bench-columns"><section><div className="timeout-line"><h2>{selected ? selected.name : "Разговор с пятёркой"}</h2>
      {selected && <button onClick={()=>select("team")}>Ко всей команде</button>}</div>
      <div className="bench-notes">{(selected?[selected]:five).map(p=>{
        const t=room.players[p.id].topics.at(-1) ?? m.feedback.find(f=>f.player===p.name);
        return t && <blockquote key={p.id}><b>{p.name} · R{t.round}</b>{t.text}</blockquote>;
      })}{!subjects.length && !m.feedback.length && <p>Пока нет игровых эпизодов для разбора.</p>}</div>
      <label>Предмет разговора<select value={topic} onChange={e=>setTopic(e.target.value)}>
        <option value="">Состояние перед раундом</option>{subjects.map(t=><option key={t.key} value={t.key}>{t.name} · R{t.round} · {t.text}</option>)}</select></label>
      <label>Обращение<select aria-label="Обращение" value={action} onChange={e=>setAction(e.target.value)}>{Object.entries(actions).filter(([k])=>k!=="order" || selected).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
      {action==="order" && <><label>Индивидуальная задача<select value={order} onChange={e=>setOrder(e.target.value)}>{Object.entries(orders).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select></label>
        {order==="support" && <label>Напарник<select value={mate||partners[0].id} onChange={e=>setMate(e.target.value)}>{partners.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>}
        {["hold","position"].includes(order) && <label>Направление<select value={site} onChange={e=>setSite(e.target.value)}><option>A</option><option>B</option></select></label>}</>}
      <button className="bench-send" disabled={!enabled || room.seconds<cost || (!fact && ["mistake","discuss"].includes(action))} onClick={send}>Обратиться · {cost} с</button>
      <div aria-live="polite">{room.history.map((h,i)=><details key={i} open={i===room.history.length-1}><summary>{actions[h.action]} · {five.find(p=>p.id===h.target)?.name || "Вся команда"}</summary>
        {h.replies.map(r=><blockquote key={r.player}><b>{r.player}</b>{r.text}</blockquote>)}</details>)}</div>
    </section><section><h2>План на раунд</h2>
      {five.filter(p=>room.players[p.id].order).map(p=><p key={p.id}>{p.name} · {orders[room.players[p.id].order!.kind]}</p>)}
      <label>План на ближайший раунд<select value={call} onChange={e=>setCall(e.target.value)}>{m.calls.map(c=><option key={c}>{c}</option>)}</select></label>
      <div className="bench-controls"><button disabled={!enabled} onClick={()=>act("call",call)}>Передать колл</button><button onClick={openBoard}>Выбрать тактику</button></div>
      {m.call && <p role="status">Принято · {m.call}</p>}
      <button className="primary" disabled={!enabled} onClick={()=>act("resume")}>Завершить тайм-аут</button>
      <div className="bench-controls bench-save"><button disabled={!enabled} onClick={()=>act("save")}>Сохранить</button><button disabled={!enabled || !saved} onClick={()=>act("load")}>Загрузить</button></div>
    </section></div>
  </section>;
}
