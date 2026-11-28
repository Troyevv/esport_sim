import { date } from "./careerData";

export type Quote = {
  version:string; date:string; stage:"opening"|"veto"|"locked"; bestOf:number; teams:string[];
  order:string[]; bans:string[]; move?:number; margin:number; probability:number[]; odds:number[];
  scores:{score:number[]; probability:number; odds:number}[];
};
const percent = (p:number) => (p*100).toFixed(1)+"%";
const stages = {opening:"До veto",veto:"В ходе veto",locked:"Veto завершено"};
export function ForecastLine({quotes,names,calibration}: {quotes:Quote[];names:Record<string,string>;calibration?:{count:number;brier:number|null}}) {
  const line = quotes.at(-1);
  if (!line) return <p>Датированная предматчевая линия отсутствует.</p>;
  return <section className="surface panel-body forecast-line"><h2>Виртуальная линия</h2>
    <p>{date(line.date)} · {stages[line.stage]} · {line.version}</p>
    <div className="cp-two-col">{line.teams.map((t,i)=><div className="forecast-side" key={t}>
      <span>{names[t] || t}</span><strong>{percent(line.probability[i])}</strong><b>Коэффициент {line.odds[i].toFixed(2)}</b></div>)}</div>
    <details><summary>Точный счёт BO{line.bestOf}</summary><table className="simple-table"><thead><tr><th>Счёт</th><th>Вероятность</th><th>Коэффициент</th></tr></thead>
      <tbody>{line.scores.map(r=><tr key={r.score.join("-")}><th>{r.score.join(" : ")}</th><td>{percent(r.probability)}</td><td>{r.odds.toFixed(2)}</td></tr>)}</tbody></table></details>
    <details><summary>История линии · {quotes.length}</summary>{quotes.map((q,i)=><p key={i}>{date(q.date)} · {stages[q.stage]}{q.move ? " · ход "+q.move : ""} · {q.odds.map(n=>n.toFixed(2)).join(" / ")}</p>)}</details>
    <details><summary>Модель и выборка</summary><p>Модель учитывает опубликованный VRS, составы, датированные рейтинги, результаты и карты соперников. Для неизвестных карт она усредняет допустимые варианты без повторений. При недостатке наблюдений оценки приближаются к равным. Маржа виртуальной линии {percent(line.margin)}.</p>
      {calibration && <p>Калибровка по последней предматчевой линии · {calibration.count} завершённых встреч · Brier {calibration.brier?.toFixed(3) ?? "—"}. Меньшее значение означает меньшую ошибку вероятности.</p>}</details>
  </section>;
}
