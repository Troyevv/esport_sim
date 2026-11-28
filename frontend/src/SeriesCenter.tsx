import { EntityName, ProfileAction } from "./CareerIdentity";
import { ForecastLine, type Quote } from "./ForecastLine";
import { useState } from "react";
import { clubColors, SeriesEvent } from "./SeriesIdentity";
import { Icon } from "./approved/Shared";
import { ResultScore } from "./ResultScore";
import { Tabs } from "./GameUI";
import { Avatar, LineupPortrait, type Visual } from "./SceneIdentity";
import { serverURL, type Frame } from "./session";
import "./series.css";

type Move = { kind: "ban" | "pick" | "side" | "decider"; team: string | null };
type Evidence = {
  games: number;
  wins: number;
  bans: number;
  picks: number;
  weight: number;
};
export interface SeriesView {
  bestOf: number;
  forecasts?:Quote[];
  award?: { name: string; player: string; teamId: string; version: string; impact: number; adr: number; rounds: number } | null;
  tournament?:string;
  edition?: {id:string; organizer:string; year?:number};
  spectator?:boolean;
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
  staffAvailable?: boolean;
  specialists?: Record<string,string>;
  advisor?: string;
  fit?: { knowledge: number; assessed: number; roles: number };
  results: { map: string; score: Record<string, number> }[];
  score: Record<string, number>;
  winner?: string;
  rounds?: number;
  completedRounds?: number;
  stats?: {
    player: string;
    name: string;
    teamId: string;
    k: number;
    d: number;
    a: number;
    damage: number;
    hs: number;
    kast: number;
    spent: number | null;
    opening: number;
    clutches: number;
  }[];
}
type Props = {
  frame: Frame;
  enabled: boolean;
  act: (kind: string, value?: object) => Promise<boolean>;
};
const labels = {
  ban: "Бан",
  pick: "Пик",
  side: "Сторона",
  decider: "Решающая",
};

export function FormatSelect({
  format,
  change,
}: {
  format: number;
  change: (format: number) => void;
}) {
  return (
    <label>
      Формат матча
      <select value={format} onChange={(e) => change(Number(e.target.value))}>
        <option value={0}>BO1 · заданная карта</option>
        {[1, 3, 5].map((n) => (
          <option value={n} key={n}>
            BO{n} · Map Veto
          </option>
        ))}
      </select>
    </label>
  );
}

function MapOrder({ s }: { s: SeriesView }) {
  return (
    <ol className="series-order" data-results={true} aria-label="Порядок карт серии">
      {s.order.map((item, i) => {
        const result = s.results[i];
        const current =
          !result && i === s.results.length && s.stage === "playing";
        return (
          <li key={item.map} data-current={current} data-won={result ? result.score[s.coach] > result.score[s.teams.find(t=>t!==s.coach)!] : undefined}>
            <img className="series-map-preview" alt="" src={serverURL("/api/maps/"+item.map+"/radar.png").href}/>
            <small>
              Карта {i + 1} ·{" "}
              {item.picker ? s.clubs[item.picker].name : "Решающая"}
            </small>
            <strong>{s.names[item.map]}</strong>
            <span>
              {result
                ? s.teams.map((t) => result.score[t]).join(" : ")
                : s.winner
                  ? "Не потребовалась"
                  : current
                    ? "Текущая карта"
                    : item.attack
                      ? "T · " + s.clubs[item.attack].name + " / CT · " + s.clubs[s.teams.find(t=>t!==item.attack)!].name
                      : "Выбор стороны"}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function SeriesScore({ frame, enabled, act }: Props) {
  const s = frame.world.series!;
  const [view, setView] = useState("Итоги серии");
  const finished = s.stage === "finished";
  const award = s.award;
  const matchAgent = award && frame.world.agents.find(agent => agent.playerId === award.player);
  const portrait = matchAgent && frame.world.match?.stats.find(p => p.id === matchAgent.id)?.visual;
  return (
    <section className={"series-score surface" + (finished ? " final-series" : "")} aria-label="Счёт серии">
      {finished ? <>
        <header className="report-meta"><div><small>{s.tournament || "Выставочный матч"} · BO{s.bestOf}</small>
          <h1>Итоги серии</h1></div></header>
        <ResultScore teams={s.teams.map(id => ({ id, ...s.clubs[id] }))} score={s.teams.map(id => s.score[id]).join(" : ")}/>
        <Tabs items={["Итоги серии", "Статистика серии"]} value={view} change={setView}/>
      </> : <div className="series-scoreline">
        <b>BO{s.bestOf}</b>
        <strong>
          {s.teams.map((t) => s.clubs[t].name + " " + s.score[t]).join("  /  ")}
        </strong>
        <span>
          {s.winner
            ? "Победа · " + s.clubs[s.winner].name
            : s.stage === "interval"
              ? "Перерыв между картами"
              : "До " + (Math.floor(s.bestOf / 2) + 1) + " побед"}
        </span>
      </div>}
      {(!finished || view === "Итоги серии") && <MapOrder s={s}/>}
      {finished && view === "Итоги серии" && <section className="report-panel">
        <h3>MVP серии</h3>
        {award ? <div className="report-award"><div><LineupPortrait id={award.player} name={award.name} visual={{player:true, ...portrait}}/></div>
          <div><small>{s.clubs[award.teamId]?.name}</small><h4><ProfileAction group="players" id={award.player}>{award.name}</ProfileAction></h4>
            <p>{award.rounds} раундов · {award.version}</p><dl>
              <div><dt>Impact</dt><dd>{award.impact.toFixed(2)}</dd></div><div><dt>ADR</dt><dd>{award.adr.toFixed(1)}</dd></div>
            </dl></div></div> : <p>Для определения MVP недостаточно данных протокола.</p>}
      </section>}
      {(!finished || view === "Статистика серии") && <details
        className="series-totals"
        open={s.stage === "interval" || s.stage === "finished"}
      >
        <summary>Статистика игроков за серию</summary>
        <div className="series-stat-grid">
          {s.teams.map((t) => (
            <section key={t}>
              <h3>{s.clubs[t].name}</h3>
              <div
                className="series-table-scroll"
                role="region"
                aria-label={"Показатели · " + s.clubs[t].name}
                tabIndex={0}
              >
                <table>
                  <thead>
                    <tr>
                      <th>Игрок</th>
                      <th>K</th>
                      <th>D</th>
                      <th>A</th>
                      <th>ADR</th>
                      <th>KAST</th>
                      <th>HS</th>
                      <th>Первые</th>
                      <th>Клатчи</th>
                      <th>Закупки</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.stats
                      ?.filter((p) => p.teamId === t)
                      .map((p) => (
                        <tr key={p.player}>
                          <th><EntityName group="players" id={p.player} recordedName={p.name} historicalTeam={t}/></th>
                          <td>{p.k}</td>
                          <td>{p.d}</td>
                          <td>{p.a}</td>
                          <td>
                            {s.rounds ? (p.damage / s.rounds).toFixed(1) : "—"}
                          </td>
                          <td>
                            {s.completedRounds
                              ? Math.round((100 * p.kast) / s.completedRounds) +
                                "%"
                              : "—"}
                          </td>
                          <td>{p.hs}</td>
                          <td>{p.opening}</td>
                          <td>{p.clutches}</td>
                          <td>
                            {p.spent === null
                              ? "—"
                              : "$" + p.spent.toLocaleString("ru-RU")}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}
        </div>
      </details>}
      {s.stage === "interval" && (
        <button
          className="btn primary"
          disabled={!enabled}
          onClick={() => act("series-next")}
        >
          Подготовка к карте {s.results.length + 1} ·{" "}
          {s.names[s.order[s.results.length].map]}
        </button>
      )}
    </section>
  );
}

export function VetoCenter({ frame, enabled, act }: Props) {
  const s = frame.world.series!;
  const turn = frame.context + "/" + s.actions.length;
  const [selection, select] = useState<{turn: string; map: string} | null>(null);
  const step = s.steps[s.actions.length];
  const actor = step?.team && s.clubs[step.team];
  const choosingMap = step?.kind === "ban" || step?.kind === "pick";
  const ready = s.stage === "ready";
  const canAct = enabled && !ready && !s.spectator && step?.team === s.coach;
  const choose = async (choice: string) => {
    if (canAct && await act("series-veto", { choice })) select(null);
  };
  const advice = s.advice;
  const opponent = s.teams.find(t => t !== s.coach)!;
  const advised = advice ? s.evidence?.[s.coach]?.[advice] : undefined;
  const rivalMap = advice ? s.evidence?.[opponent]?.[advice] : undefined;
  const chosen = selection?.turn === turn && !s.actions.some(a => a.map === selection.map) ? selection.map : null;
  const form = s.pool.flatMap(map => {
    const row = s.evidence?.[opponent]?.[map];
    return row?.games ? [{map, rate: row.wins/row.games, games: row.games}] : [];
  }).sort((a,b) => b.rate-a.rate || b.games-a.games);
  const high = form[0], low = form.at(-1);
  const distinctRates = high && low && high.rate > low.rate;
  const actionName = {ban:"BAN", pick:"PICK", side:"T / CT", decider:"DECIDER"};
  return (
    <article className="veto-center">
      <header className="veto-heading">
        <div>
          <SeriesEvent series={s} fallback="Выставочный матч"/>
          <h1>Map Veto</h1>
        </div>
        <div className="veto-tools">
          <button
            className="btn sm"
            disabled={!enabled}
            onClick={() => act("save")}
          >
            Сохранить
          </button>
          <button
            className="btn sm"
            disabled={!enabled || !frame.hasSave}
            onClick={() => act("load")}
          >
            Загрузить
          </button>
        </div>
      </header>
      <div className="veto-matchup">
        <div className="veto-versus"><b>VS</b><strong>BEST OF {s.bestOf}</strong></div>
        {s.teams.map((t) => (
          <div key={t} className="veto-club" style={clubColors(t,s.clubs[t])}>
            <Avatar name={s.clubs[t].name} club {...s.clubs[t].visual} />
            <div>
              <small>{s.spectator?"Участник":t === s.coach ? "Ваша команда" : "Соперник"}</small>
              <strong><ProfileAction group="teams" id={t}>{s.clubs[t].name}</ProfileAction></strong>
            </div>
          </div>
        ))}
      </div>
      {s.forecasts && <details><summary>Предматчевая линия</summary><ForecastLine quotes={s.forecasts} names={Object.fromEntries(s.teams.map(t=>[t,s.clubs[t].name]))}/></details>}
      <div className="veto-layout" data-action={step?.kind ?? "ready"}>
        <section>
          <header className="veto-turn" data-kind={step?.kind} aria-live="polite">
            <b className="veto-action-code">{step ? actionName[step.kind] : "BO" + s.bestOf}</b>
            <div><small>{actor ? actor.name + " · Ход " + (s.actions.length+1) + " из " + s.steps.length : "Порядок карт определён"}</small>
              <h2>{ready ? "Вето завершено" : step?.kind === "side" ? "Стартовая сторона · " + s.names[s.order.at(-1)!.map]
                : step?.kind === "ban" ? "Исключение карты" : "Выбор карты в серию"}</h2></div>
            {step?.kind === "side" && <div className="veto-sides">{["T","CT"].map(side =>
              <button key={side} disabled={!canAct} data-side={side} onClick={()=>choose(side)}>
                <Icon name={side==="T"?"tactic":"shield"}/>{side==="T"?"Атака · T":"Защита · CT"}
              </button>)}</div>}
          </header>
          <ol className="veto-progress" aria-label="Этапы вето">{s.steps.map((move,i) =>
            <li key={i} data-kind={move.kind} data-done={i<s.actions.length}
              aria-current={i===s.actions.length?"step":undefined}
              title={[String(i+1), labels[move.kind], move.team && s.clubs[move.team].name, s.names[s.actions[i]?.map]].filter(Boolean).join(" · ")}>
              {actionName[move.kind]}</li>)}</ol>
          {ready ? <section className="veto-locked">
            <MapOrder s={s}/>
            <button className="btn primary" disabled={!enabled} onClick={()=>act("series-next")}>Перейти к подготовке</button>
          </section> : <nav className="veto-shortcuts" aria-label="Разделы вето">
            <a href="#veto-staff"><Icon name="tactic" size={15}/>{advice ? "Совет · " + (s.names[advice] || advice) : "Разбор штаба"}</a>
            <a href="#veto-moves"><Icon name="calendar" size={15}/>История ходов</a>
          </nav>}
          <div className="veto-pool">
            {s.pool.map((id) => {
              const action = s.actions.find((a) => a.map === id);
              return (
                <div
                  key={id}
                  className="veto-card"
                  data-state={action?.kind || "available"}
                  data-selected={chosen === id}
                >
                  <div className="veto-art">
                    <img
                      src={serverURL("/api/maps/" + id + "/radar.png").href}
                      alt=""
                    />
                    <span>
                      {action
                        ? labels[action.kind] +
                          (action.team ? " · " + s.clubs[action.team].name : "")
                        : chosen === id ? "К подтверждению" : "Доступна"}
                    </span>
                    <strong>{s.names[id]}</strong>
                  </div>
                  <div className="veto-evidence">
                    {s.teams.map((t) => {
                      const row = s.evidence?.[t]?.[id];
                      return (
                        <div key={t}>
                          <Avatar name={s.clubs[t].name} club {...s.clubs[t].visual}/>
                          <span title={s.clubs[t].name}>{s.clubs[t].name}</span>
                          <b>{row?.games ? Math.round(100*row.wins/row.games)+"%" : "—"}</b>
                          <small>{row ? "Карт · "+row.games : "Нет сведений"}</small>
                        </div>
                      );
                    })}
                  </div>
                  {!action && choosingMap && (
                    <button
                      className="veto-select"
                      aria-pressed={chosen === id}
                      disabled={!canAct}
                      aria-label={"Выбрать " + s.names[id]}
                      onClick={() => select({map:id, turn})}
                    />
                  )}
                </div>
              );
            })}
          </div>
          {choosingMap && chosen && (
            <div className="veto-commit">
              <div><small>{step.kind==="ban"?"Будет исключена":"Войдёт в серию"}</small><strong>{s.names[chosen]}</strong></div>
              <button
                className="btn primary"
                disabled={!canAct}
                onClick={() => choose(chosen)}
              >
                {step.kind === "ban" ? "Забанить карту" : "Пикнуть карту"}
              </button>
            </div>
          )}
          <details className="veto-history surface">
            <summary>Статистика команд по картам</summary>
            <p>
              Вес встречи уменьшается вдвое за 90 игровых дней. Свежая выборка
              показывает эквивалентное число карт с учётом давности.
            </p>
            {s.teams.map((t) => (
              <section key={t}>
                <h3>{s.clubs[t].name}</h3>
                <table>
                  <thead>
                    <tr>
                      {[
                        "Карта",
                        "Игры",
                        "Победы",
                        "Пики",
                        "Баны",
                        "Свежая выборка",
                      ].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {s.pool.map((m) => {
                      const row = s.evidence?.[t]?.[m];
                      return (
                        <tr key={m}>
                          <th>{s.names[m]}</th>
                          <td>{row?.games ?? "—"}</td>
                          <td>
                            {row?.games
                              ? Math.round((row.wins * 100) / row.games) + "%"
                              : "—"}
                          </td>
                          <td>{row?.picks ?? "—"}</td>
                          <td>{row?.bans ?? "—"}</td>
                          <td>{row?.weight.toFixed(1) ?? "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </section>
            ))}
          </details>
          {!ready && s.order.length > 0 && (
            <section className="veto-order">
              <h2>Карты серии</h2>
              <MapOrder s={s} />
            </section>
          )}
        </section>
        <aside className="veto-desk">
          {!ready && (
            <section id="veto-staff" className="surface">
              <h2><Icon name="tactic" size={20}/> Разбор штаба</h2>
              <div className="veto-advice">
                <small>{s.advisor ? "РЕКОМЕНДАЦИЯ · " + s.advisor : s.staffAvailable === false ? "РЕКОМЕНДАЦИЯ КАПИТАНА" : "РЕКОМЕНДАЦИЯ ШТАБА"}</small>
                <strong>
                  {advice &&
                    (s.names[advice] ||
                      (advice === "T"
                        ? "Начать за атаку"
                        : "Начать за защиту"))}
                </strong>
                <p>
                  {advised
                    ? advised.games || rivalMap?.games
                      ? s.teams.map(t => { const r=s.evidence?.[t]?.[advice!]; return s.clubs[t].name + " · " + (r?.games ? r.wins + " побед из " + r.games : "нет сыгранных карт"); }).join(". ")
                      : "Нет сыгранных встреч на карте. Оценка по знанию карты и ролям своей пятёрки."
                    : "Оценка по игре сторон и стилю капитана."}
                </p>
                {s.fit && (
                  <dl className="veto-fit">
                    <dt>Знание карты</dt>
                    <dd>
                      {s.fit.assessed
                        ? s.fit.knowledge +
                          "/100 · оценки " +
                          s.fit.assessed +
                          "/5"
                        : "Нет оценок"}
                    </dd>
                    <dt>Соответствие ролей</dt>
                    <dd>{s.fit.roles}/100</dd>
                  </dl>
                )}
              </div>
              {distinctRates && <div className="veto-opponent-form">
                <small>Карты соперника · по доле побед</small>
                {[high,low].map((edge,i) => {
                  return <p key={i}><b>{i===0?"Лучший результат":"Худший результат"}</b>{" "}
                    {form.filter(row=>row.rate===edge.rate).map(row=>s.names[row.map]+" ("+row.games+")").join(", ")}
                    {" · "+Math.round(edge.rate*100)+"%"}</p>;
                })}
                <small>В скобках — число сыгранных карт.</small>
              </div>}
              <details>
                <summary>Делегировать оставшиеся ходы</summary>
                <div className="veto-tools">
                  {(["captain", "staff"] as const).filter(by => by !== "staff" || s.staffAvailable !== false).map((by) => (
                    <button
                      key={by}
                      className="btn"
                      disabled={!canAct}
                      onClick={() => act("series-veto", { delegate: by })}
                    >
                      {by === "captain" ? "Капитану" : "Штабу"}
                    </button>
                  ))}
                </div>
              </details>
            </section>
          )}
          <section className="surface" id="veto-moves">
            <h2>Порядок действий</h2>
            <ol className="veto-timeline">
              {s.steps.map((move, i) => {
                const a = s.actions[i];
                return (
                  <li
                    key={i}
                    aria-current={i === s.actions.length ? "step" : undefined}
                  >
                    <b>{i + 1}</b>
                    {move.team ? <Avatar name={s.clubs[move.team].name} club {...s.clubs[move.team].visual}/> : <Icon name="flag" size={22}/>}
                    <div>
                      <strong>
                        {labels[move.kind]} ·{" "}
                        {move.team ? s.clubs[move.team].name : "Регламент"}
                      </strong>
                      <small>
                        {a
                          ? [
                              s.names[a.map],
                              a.side,
                              (
                                {
                                  captain: "капитан",
                                  staff: (move.team && s.specialists?.[move.team]) || "штаб",
                                  manager: "вручную",
                                } as Record<string, string>
                              )[a.by],
                            ]
                              .filter(Boolean)
                              .join(" · ")
                          : i === s.actions.length
                            ? "Сейчас"
                            : "Далее"}
                      </small>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        </aside>
      </div>
    </article>
  );
}
