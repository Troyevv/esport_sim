import { useMemo } from "react";
import { serverURL } from "./session";
import type { Result } from "./ProfileHistory";
import "./map-record.css";

type Counts = { wins: number; losses: number; played: number };

function summarize(rows: Result["rows"]) {
  const maps = new Map<string, Counts>();
  for (const row of rows) {
    if (!row.mapId) continue;
    const counts = maps.get(row.mapId) ?? { wins: 0, losses: 0, played: 0 };
    counts.played++;
    if (row.won === true) counts.wins++;
    if (row.won === false) counts.losses++;
    maps.set(row.mapId, counts);
  }
  return maps;
}

function MapResult({ counts }: { counts?: Counts }) {
  if (!counts) return <span className="map-record-empty">Нет карт</span>;
  const known = counts.wins + counts.losses;
  return <div className="map-record-result">
    <strong>{known ? Math.round(counts.wins * 100 / known) + "%" : "—"}</strong>
    <small>{counts.wins} В · {counts.losses} П{known < counts.played && " · без итога " + (counts.played - known)}</small>
    {known > 0 && <meter aria-label="Доля побед" min={0} max={known} value={counts.wins}/>}
  </div>;
}

export function MapRecord({ current, compared, names, active, select, label }: {
  current: Result; compared?: Result; names: string[]; active: string;
  select: (id: string) => void; label: (id: string) => string;
}) {
  const records = useMemo(() => [summarize(current.rows), ...(compared ? [summarize(compared.rows)] : [])], [current, compared]);
  const maps = Array.from(new Set(records.flatMap(group => [...group.keys()])));
  const sample = (id: string) => records.reduce((sum, group) => sum + (group.get(id)?.played ?? 0), 0);
  maps.sort((a,b) => sample(b) - sample(a) || label(a).localeCompare(label(b)));
  if (!maps.length && !active) return null;
  return <section className="map-record" aria-label="Результаты по картам">
    <header><h3>Результаты по картам</h3>{active && <button onClick={()=>select("")}>Сбросить карту</button>}</header>
    <table><thead><tr><th scope="col">Карта</th>{records.map((_,i)=><th key={i} scope="col">{names[i]}</th>)}</tr></thead>
      <tbody>{maps.map(id=><tr key={id}>
        <th scope="row"><button type="button" aria-pressed={active===id} onClick={()=>select(active===id ? "" : id)}>
          <img loading="lazy" decoding="async" alt="" src={serverURL("/api/maps/"+encodeURIComponent(id)+"/radar.png").href}
            onError={e=>{e.currentTarget.hidden=true}}/>{label(id)}</button></th>
        {records.map((group,i)=><td key={i}><MapResult counts={group.get(id)}/></td>)}
      </tr>)}</tbody></table>
  </section>;
}
