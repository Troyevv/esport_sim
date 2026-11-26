import { useState } from "react";
import { Avatar, type Visual } from "./SceneIdentity";
import { serverURL, type Frame } from "./session";
import "./series.css";

type Move = { kind: "ban" | "pick" | "side" | "decider"; team: string | null };
type Evidence = { games: number; wins: number; bans: number; picks: number; weight: number };
export interface SeriesView {
  bestOf: number;
  stage: "veto" | "ready" | "playing" | "interval" | "finished";
  teams: string[];
  coach: string;
  clubs: Record<string, { name: string; visual?: Visual }>;
  pool: string[];
  names: Record<string, string>;
  steps: Move[];
  actions: (Move & { map: string; side?: string; by: string })[];
  order: { map: string; picker: string | null; attack: string | null }[];
  evidence?: Record<string, Record<string, Evidence>>;
  advice?: string;
  results: { map: string; score: Record<string, number> }[];
  score: Record<string, number>;
  winner?: string;
  rounds?: number;
  stats?: { player: string; name: string; teamId: string; k: number; d: number; a: number; damage: number; opening: number; clutches: number }[];
}
type Props = { frame: Frame; enabled: boolean; act: (kind: string, value?: object) => Promise<boolean> };
const labels = { ban: "Бан", pick: "Пик", side: "Сторона", decider: "Решающая" };

export function FormatSelect({format, change}: {format: number; change: (format: number) => void}) {
  return <label>Формат матча<select value={format} onChange={e => change(Number(e.target.value))}>
    <option value={0}>BO1 · заданная карта</option>
    {[1, 3, 5].map(n => <option value={n} key={n}>BO{n} · Map Veto</option>)}
  </select></label>;
}

function MapOrder({s}: {s: SeriesView}) {
  return <ol className="series-order" aria-label="Порядок карт серии">
    {s.order.map((item, i) => {
      const result = s.results[i];
      const current = !result && i === s.results.length && s.stage === "playing";
      return <li key={item.map} data-current={current}>
        <small>Карта {i + 1} · {item.picker ? s.clubs[item.picker].name : "Решающая"}</small>
        <strong>{s.names[item.map]}</strong>
        <span>{result ? s.teams.map(t => result.score[t]).join(" : ") : s.winner ? "Не потребовалась" :
          current ? "Текущая карта" : item.attack ? s.clubs[item.attack].name + " · старт T" : "Выбор стороны"}</span>
      </li>;
    })}
  </ol>;
}

export function SeriesScore({frame, enabled, act}: Props) {
  const s = frame.world.series!;
  return <section className="series-score surface" aria-label="Счёт серии">
    <div className="series-scoreline"><b>BO{s.bestOf}</b>
      <strong>{s.teams.map(t => s.clubs[t].name + " " + s.score[t]).join("  /  ")}</strong>
      <span>{s.winner ? "Победа · " + s.clubs[s.winner].name : s.stage === "interval" ? "Перерыв между картами" : "До " + (Math.floor(s.bestOf / 2) + 1) + " побед"}</span>
    </div>
    <MapOrder s={s}/>
    <details className="series-totals" open={s.stage === "interval" || s.stage === "finished"}>
      <summary>Статистика игроков за серию</summary>
      <div className="series-stat-grid">{s.teams.map(t => <section key={t}>
        <h3>{s.clubs[t].name}</h3>
        <table><thead><tr><th>Игрок</th><th>K</th><th>D</th><th>A</th><th>ADR</th></tr></thead>
          <tbody>{s.stats?.filter(p => p.teamId === t).map(p => <tr key={p.player}><th>{p.name}</th>
            <td>{p.k}</td><td>{p.d}</td><td>{p.a}</td><td>{s.rounds ? (p.damage/s.rounds).toFixed(1) : "—"}</td></tr>)}</tbody></table>
      </section>)}</div>
    </details>
    {s.stage === "interval" && <button className="btn primary" disabled={!enabled} onClick={() => act("series-next")}>
      Подготовка к карте {s.results.length + 1} · {s.names[s.order[s.results.length].map]}</button>}
  </section>;
}

export function VetoCenter({frame, enabled, act}: Props) {
  const s = frame.world.series!;
  const [selected, select] = useState<string | null>(null);
  const step = s.steps[s.actions.length];
  const choosingMap = step?.kind === "ban" || step?.kind === "pick";
  const ready = s.stage === "ready";
  const choose = async (choice: string) => {
    if (await act("series-veto", {choice})) select(null);
  };
  const advice = s.advice;
  const advised = advice && s.evidence?.[s.coach][advice];
  const opponent = s.teams.find(t => t !== s.coach)!;
  const chosen = selected && !s.actions.some(a => a.map === selected) ? selected : null;
  return <article className="veto-center">
    <header className="veto-heading"><div><span className="eyebrow">ВЫСТАВОЧНЫЙ МАТЧ · BO{s.bestOf}</span>
      <h1>Map Veto</h1></div><div className="veto-tools"><button className="btn sm" disabled={!enabled} onClick={() => act("save")}>Сохранить</button>
        <button className="btn sm" disabled={!enabled || !frame.hasSave} onClick={() => act("load")}>Загрузить</button></div></header>
    <div className="veto-matchup">{s.teams.map(t => <div key={t} className="veto-club">
      <Avatar name={s.clubs[t].name} club {...s.clubs[t].visual}/><div><small>{t === s.coach ? "Ваша команда" : "Соперник"}</small>
        <strong>{s.clubs[t].name}</strong></div></div>)}</div>
    <div className="veto-layout"><section><header className="veto-pool-title">
      <h2>{ready ? "Вето завершено" : step.kind === "ban" ? "Заблокируйте карту" : step.kind === "pick" ? "Выберите карту" : "Выберите стартовую сторону"}</h2>
      <small>{s.actions.length} / {s.steps.length}</small></header>
      <div className="veto-pool">{s.pool.map(id => {
        const action = s.actions.find(a => a.map === id);
        return <div key={id} className="veto-card" data-state={action?.kind || "available"} data-selected={chosen === id}>
          <div className="veto-art"><img src={serverURL("/api/maps/"+id+"/radar.png").href} alt=""/>
            <span>{action ? labels[action.kind] + (action.team ? " · "+s.clubs[action.team].name : "") : "Доступна"}</span>
            <strong>{s.names[id]}</strong></div>
          <div className="veto-evidence">{s.teams.map(t => {
            const row = s.evidence![t][id];
            return <div key={t} title={s.clubs[t].name + " · пиков " + row.picks + " · банов " + row.bans}>
              <span>{s.clubs[t].name}</span><b>{row.games ? Math.round(100*row.wins/row.games)+"% · "+row.games+" игр" : "Нет игр"}</b></div>;
          })}</div>
          {!action && choosingMap && <button className="veto-select" aria-pressed={chosen === id} disabled={!enabled}
            aria-label={"Выбрать " + s.names[id]} onClick={() => select(id)}/>}
        </div>;
      })}</div>
      {s.order.length > 0 && <section className="veto-order"><h2>Карты серии</h2><MapOrder s={s}/></section>}
    </section><aside className="veto-desk">
      {ready ? <section className="surface"><h2>Первая карта</h2><p>{s.names[s.order[0].map]} · старт за {s.order[0].attack === s.coach ? "T" : "CT"}</p>
        <button className="btn primary" disabled={!enabled} onClick={() => act("series-next")}>Перейти к подготовке</button></section>
      : <section className="surface"><small className="eyebrow">ХОД {s.actions.length+1} · {s.clubs[s.coach].name}</small>
        <h2>{choosingMap ? chosen ? s.names[chosen] : "Ваш выбор" : s.names[s.order.at(-1)!.map]}</h2>
        {choosingMap ? <button className="btn primary" disabled={!enabled || !chosen} onClick={() => chosen && choose(chosen)}>
          {step.kind === "ban" ? "Подтвердить бан" : "Подтвердить пик"}</button>
          : <div className="veto-tools">{["T","CT"].map(side => <button className="btn primary" key={side} disabled={!enabled}
            onClick={() => choose(side)}>{side === "T" ? "Атака · T" : "Защита · CT"}</button>)}</div>}
        <div className="veto-advice"><small>РЕКОМЕНДАЦИЯ ШТАБА</small><strong>{advice && (s.names[advice] || (advice === "T" ? "Начать за атаку" : "Начать за защиту"))}</strong>
          <p>{advised ? advised.games || s.evidence![opponent][advice!].games
            ? "Учтены винрейт, давность встреч и история выбора обеих команд."
            : "Нет сыгранных встреч на карте. Оценка по знанию карты и ролям своей пятёрки."
            : "Оценка по игре сторон и стилю капитана."}</p></div>
        <details><summary>Делегировать оставшиеся ходы</summary><div className="veto-tools">
          {(["captain","staff"] as const).map(by => <button key={by} className="btn" disabled={!enabled}
            onClick={() => act("series-veto",{delegate:by})}>{by === "captain" ? "Капитану" : "Штабу"}</button>)}</div></details>
      </section>}
      <section className="surface"><h2>Порядок действий</h2><ol className="veto-timeline">{s.steps.map((move,i) => {
        const a = s.actions[i];
        return <li key={i} aria-current={i === s.actions.length ? "step" : undefined}><b>{i+1}</b><div><strong>{labels[move.kind]} · {move.team ? s.clubs[move.team].name : "Регламент"}</strong>
          <small>{a ? [s.names[a.map], a.side, ({captain:"капитан",staff:"штаб",manager:"вручную"} as Record<string,string>)[a.by]].filter(Boolean).join(" · ") : i === s.actions.length ? "Сейчас" : "Далее"}</small></div></li>;
      })}</ol></section>
    </aside></div>
  </article>;
}
