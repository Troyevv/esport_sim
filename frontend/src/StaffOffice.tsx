import { useState } from "react";
import { Heading } from "./GameUI";
import { resolvePortrait } from "./portraits";
import { Avatar } from "./SceneIdentity";
import { date, type Act, type Career, type Scene } from "./careerData";
import "./staff.css";

type Person = {
  id: string; name: string; publishedRole?: string; realName: string | null; role: string; capacity: number;
  attributes: Record<string, number>; ratings: Record<string, number>;
  philosophy: Record<string, string>; suitability: Record<string, number>;
};
export type Office = {
  people: Record<string, Person>; roles: Record<string, string>; groups: Record<string, Record<string, string>>;
  owners: Record<string, string>; duties: Record<string, {title: string; stage: string}>;
  jobs: {person:string; team:string; date:string; due:string; duty:string; event:string; cost:number; quality:number}[];
};
const departments = ["Тренерский штаб", "Скаутский отдел"];
const screens = [...departments, "Обязанности", "Занятость", "Должности"];
function Rating({value}: {value:number}) {
  return <span className="staff-rating">{value}</span>;
}

export function StaffOffice({c, scene, act, enabled, initial, personId}: {
  c: Career; scene: Scene; act: Act; enabled:boolean; initial:string; personId?:string;
}) {
  const [section, setSection] = useState(initial);
  const [id, setId] = useState(personId || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const office = c.office;
  const people = Object.values(office.people);
  const p = office.people[id];
  const original = p && resolvePortrait(scene.staff[p.id]?.visual.photo);
  const allowed = enabled && !busy && !c.progress;
  const change = async (value:object) => {
    setBusy(true); setError("");
    try { await act("career-staff", value, setError); }
    finally { setBusy(false); }
  };
  const dayLoad = (sid:string) => office.jobs.filter(j => j.person === sid && j.date === c.date).reduce((s,j) => s + j.cost,0);
  const owners = (sid:string) => Object.keys(office.owners).filter(d => office.owners[d] === sid);
  const picture = (person:Person) => <Avatar name={person.name} {...scene.staff[person.id]?.visual}/>;
  const nav = (s:string) => {setId("");setSection(s);setError("")};
  const roleSelect = (person:Person) => <select aria-label={"Должность · " + person.name} disabled={!allowed}
    value={person.role} onChange={e=>void change({person:person.id,role:e.target.value})}>
    {Object.entries(office.roles).map(([k,title])=><option key={k} value={k}
      disabled={k==="head" && people.some(other=>other.id!==person.id && other.role==="head")}>{title}</option>)}</select>;
  return <div className="staff-office">
    <Heading title={p ? p.name : section} sub={c.club + " · " + date(c.date)} />
    <nav className="staff-tabs" aria-label="Управление персоналом">{screens.map(s=>
      <button key={s} aria-current={!p && s===section ? "page" : undefined} onClick={()=>nav(s)}>{s}</button>)}</nav>
    {error && <p role="alert">{error}</p>}
    {p ? <>
      <section className="surface staff-profile">
        {picture(p)}<div><small>Профиль сотрудника</small><h2>{p.realName || p.name}</h2>
        <p>{office.roles[p.role]}</p>{p.publishedRole && <small>Должность в источнике · {p.publishedRole}</small>}{scene.staff[p.id]?.visual.head?.includes("/generated/") && <small>Синтетический портрет</small>}<span>{dayLoad(p.id)} / {p.capacity} ед. нагрузки сегодня</span></div>
        {original && <a href={original.source} target="_blank" rel="noreferrer">Архивное фото · {original.author} · {original.license}</a>}
        <Rating value={p.ratings[p.role]}/>
      </section>
      <div className="staff-columns">
        <section className="surface panel-body"><h2>Ролевые рейтинги</h2>{Object.entries(office.roles).map(([key,title])=>
          <div className="staff-line" key={key}><span>{title}</span><Rating value={p.ratings[key]}/></div>)}</section>
        <section className="surface panel-body"><h2>Тренерская философия</h2>{Object.entries(p.philosophy).map(([k,v])=>
          <div className="staff-line" key={k}><span>{k}</span><strong>{v}</strong></div>)}</section>
      </div>
      <h2>Характеристики</h2><p className="muted">Навыки и предпочтения — игровые оценки модели staff.1.</p>
      <div className="staff-columns">{Object.entries(office.groups).map(([group,keys])=><section key={group} className="surface panel-body">
        <h3>{group}</h3>{Object.entries(keys).map(([k,label])=><div className="staff-line" key={k}><span>{label}</span>
          <meter aria-label={label} min={0} max={100} value={p.attributes[k]}/><strong>{p.attributes[k]}</strong></div>)}</section>)}</div>
    </> : departments.includes(section) ? <>
      <div className="staff-cards">{Object.entries(office.roles).filter(([key])=>key.includes("scout")===(section===departments[1])).map(([key,title])=>{
        const members=people.filter(s=>s.role===key);
        return <section key={key} className="surface staff-role"><h2>{title}</h2>{members.length ? members.map(person=>
          <button key={person.id} className="staff-member" onClick={()=>setId(person.id)}>{picture(person)}
            <span><strong>{person.name}</strong><small>{person.realName || c.club}</small></span><Rating value={person.ratings[key]}/></button>) :
          <p className="muted">Должность свободна</p>}</section>;
      })}</div>
    </> : section==="Обязанности" ? <div className="surface panel-body">
      {Object.entries(office.duties).map(([key,duty])=><div className="staff-assignment" key={key}><div>
        <strong>{duty.title}</strong><small>{key==="tactics" ? "Черновик по запросу в редакторе тактик" : duty.stage==="R5.1" ? "Подготовка к серии по календарю" : "Планирование · задачи появятся в " + duty.stage}</small></div>
        <select aria-label={duty.title} value={office.owners[key]||""} disabled={!allowed}
          onChange={e=>void change({duty:key,person:e.target.value || null})}><option value="">Личное управление</option>
          {[...people].sort((a,b)=>b.suitability[key]-a.suitability[key]).map(s=><option key={s.id} value={s.id}
            disabled={owners(s.id).length>=s.capacity && office.owners[key]!==s.id}>{s.name} · пригодность {s.suitability[key]}</option>)}</select></div>)}
    </div> : section==="Должности" ? <section className="surface panel-body">
      {people.map(s=><div key={s.id} className="staff-assignment"><button className="staff-link" onClick={()=>setId(s.id)}>{s.name}</button>{roleSelect(s)}</div>)}
      {!people.length && <p>В клубе нет сотрудников для назначения.</p>}</section> :
      <div className="staff-columns">{people.map(s=><section key={s.id} className="surface panel-body">
        <button className="staff-link" onClick={()=>setId(s.id)}>{s.name}</button><p>{office.roles[s.role]}</p>
        <div className="staff-line"><span>Свободно сегодня</span><strong>{s.capacity-dayLoad(s.id)} из {s.capacity} ед.</strong></div>
        <progress max={s.capacity} value={dayLoad(s.id)} aria-label="Занятость сегодня"/>
        <h3>Обязанности</h3><p>{owners(s.id).map(d=>office.duties[d].title).join(" · ") || "Нет назначений"}</p>
        <h3>Задания по календарю</h3>{office.jobs.filter(j=>j.person===s.id).map(j=><div className="staff-job" key={j.event+j.duty}>
          <strong>{office.duties[j.duty].title}</strong><small>{j.duty==="tactics" ? "Черновик в редакторе" : c.queue.find(e=>e.id===j.event)?.teams.map(t=>c.teams[t]).join(" — ") || "Сыгранная серия"}</small>
          <small>Срок {date(j.due)} · {j.cost} ед.</small></div>)}
        {!office.jobs.some(j=>j.person===s.id) && <p className="muted">Запланированных заданий нет</p>}</section>)}
        {!people.length && <p>В клубе нет сотрудников.</p>}</div>}
  </div>;
}
