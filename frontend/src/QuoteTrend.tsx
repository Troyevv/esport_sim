import type { Quote } from "./ForecastLine";

/** Quote positions correspond to recorded veto steps, not elapsed time. */
export function QuoteTrend({ quotes, team }: { quotes: Quote[]; team: string }) {
  if (quotes.length < 2) return null;
  const values = quotes.map(quote => quote.probability[quote.teams.indexOf(team)]);
  if (!values.every(Number.isFinite)) return null;
  const change = Math.round((values[values.length - 1] - values[0]) * 1000) / 10;
  const x = (index: number) => 2 + 156 * index / (values.length - 1);
  const y = (p: number) => 34 - 32 * p;
  return <div className="quote-trend">
    <svg viewBox="0 0 160 36" preserveAspectRatio="none" role="img" aria-label={"Шанс по шагам veto: "+values.map(p=>(p*100).toFixed(1)+"%").join(", ")}>
      <path d="M0 18H160" className="quote-even"/>
      <polyline points={values.map((p,i)=>x(i)+","+y(p)).join(" ")}/>
      {values.map((p,i)=><circle key={i} cx={x(i)} cy={y(p)} r={2}/>)}
    </svg>
    <small><b>{change > 0 ? "+" : ""}{change.toLocaleString("ru-RU")} п. п.</b> с первой линии</small>
  </div>;
}
