import { useState } from "react";
import { date, monday, useData, type Career } from "./careerData";
import { skillLabels } from "./databaseModel";
import type { TrainingState } from "./TrainingCenter";

export default function ProfileDevelopment({c,id,revision}: {c:Career; id:string; revision:number}) {
  const [selected,setSelected] = useState("aim");
  const own = c.roster.some(p => p.id === id);
  const response = useData<TrainingState>(own ? "/api/career/"+c.id+"/training?week="+monday(c.date) : null,revision);
  if (!own) return <p className="surface panel-body">История индивидуальных тренировок доступна штабу команды игрока.</p>;
  if (response.error) return <p role="alert">{response.error} <button onClick={response.reload}>Повторить</button></p>;
  const athlete = response.data?.players[id];
  if (!response.data) return <p role="status">Загружаем тренировочные отчёты…</p>;
  if (!athlete) return <p>Данных тренировочного центра по игроку пока нет.</p>;
  const skill = Object.hasOwn(athlete.skills,selected) ? selected : Object.keys(athlete.skills)[0];
  const snapshots = Object.entries(response.data.history).filter(([,players]) => players[id]?.[skill] != null);
  const delta = athlete.skills[skill];
  return <section className="surface panel-body"><h2>Динамика развития</h2>
    <label className="club-filter">Характеристика<select value={skill} onChange={e=>setSelected(e.target.value)}>
      {Object.keys(athlete.skills).map(k=><option key={k} value={k}>{skillLabels[k] || k}</option>)}</select></label>
    <p>Изменение с начала карьеры · {delta > 0 ? "+" : ""}{delta} · на {date(c.date)}</p>
    {snapshots.length ? snapshots.map(([d,players])=><div className="staff-line" key={d}><time>{date(d)}</time>
      <meter aria-label={skillLabels[skill]} min={0} max={100} value={players[id][skill]}/><strong>{players[id][skill]}</strong></div>)
      : <p>В журнале ещё нет недельных измерений этой характеристики.</p>}
  </section>;
}
