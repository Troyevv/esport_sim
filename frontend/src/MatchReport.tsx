import { useEffect, useRef, useState } from "react";
import { Avatar, LineupPortrait } from "./SceneIdentity";
import { ForecastLine } from "./ForecastLine";
import { Tabs } from "./GameUI";
import { date, fixtureMap, fixtureScore, useData, type Career, type Fixture, type Report, type Scene } from "./careerData";
import { serverURL } from "./session";
import "./report.css";

const pages = ["Итоги серии", "Статистика", "Раунды", "Составы на дату", "Протокол и данные"];
const buyNames: Record<string, string> = { pistol: "Пистолетный", full: "Полная закупка", force: "Форс", eco: "Эко" };
const reasonNames: Record<string, string> = { objective: "Задача карты", elimination: "Устранение соперника",
  defuse: "Обезвреживание", explosion: "Взрыв C4", time: "Время истекло" };
type Props = { careerId: string; event: Fixture; teams: Career["teams"]; close: () => void };

export default function MatchReport({ careerId, event, teams, close }: Props) {
  const data = useData<Report>("/api/career/" + careerId + "/report/" + event.id);
  const directory = useData<Scene>("/api/career/" + careerId + "/scene");
  const [page, setPage] = useState(pages[0]);
  const [mapIndex, setMapIndex] = useState(-1);
  const [roundIndex, setRoundIndex] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus(); }, []);
  const report = data.data;
  const maps = report?.maps || (report ? [report] : []);
  const selection = page === "Раунды" ? Math.max(0, mapIndex) : mapIndex;
  const current = maps[selection] || report;
  const metrics = current?.performance;
  const award = metrics?.players.find(p => p.player === metrics.mvp);
  const mapName = (m: Report) => fixtureMap({ ...event, bestOf: undefined, mapId: m.mapId || event.mapId });
  const teamName = (id: string | null | undefined) => id ? teams[id] || directory.data?.teams[id]?.name || id : "Команда неизвестна";
  const groups = [...event.teams, ...(current?.stats.some(p => p.teamId === null) ? [null] : [])];
  const round = current?.rounds[roundIndex];
  const utilityRecorded = current?.stats.some(p => [p.flashesThrown,p.enemiesFlashed,p.flashAssists,p.heDamage,p.fireDamage,p.smokesThrown].some(n => n != null));

  const chooseMap = (index: number) => { setMapIndex(index); setRoundIndex(0); };
  const choosePage = (next: string) => { setPage(next); setRoundIndex(0); };
  const visual = (pid: string, tid: string | null) => {
    const portrait = directory.data?.players[pid]?.visual;
    // The current directory can supply a head, but a later transfer cannot change the shirt in a past match.
    return { ...portrait, player: true, kit: portrait?.kit?.id === tid ? portrait.kit : null };
  };
  return <section className="match-report" aria-labelledby="report-title">
    <header className="report-meta"><div><h2 id="report-title" ref={heading} tabIndex={-1}>Протокол матча</h2>
      <p>{date(event.date)} · BO{event.bestOf || 1}{event.title && " · " + event.title}</p></div>
      <button onClick={close}>Закрыть протокол</button></header>
    <div className="report-score">
      {event.teams.map((tid, index) => <div className="report-team" key={tid}>
        {index === 1 && <strong className="report-points">{fixtureScore(event) || "—"}</strong>}
        <span><Avatar {...directory.data?.teams[tid]?.visual} club name={teamName(tid)} />{teamName(tid)}</span>
      </div>)}
    </div>
    {data.error ? <p role="alert">{data.error} <button onClick={data.reload}>Повторить</button></p> :
      !report || !current || !metrics ? <p role="status">Загружаем данные…</p> : <>
      <Tabs items={pages} value={page} change={choosePage}/>
      <p className="report-source">{report.simulation?.mode === "round" ? "Быстрый расчёт по раундам" :
        report.simulation?.mode === "detailed" ? "Подробная симуляция" : "Архив карьеры"} · {metrics.maps} карт · {metrics.rounds} раундов</p>
      {page === pages[0] && <div className="report-maps">{maps.map((m,i) =>
        <button key={i} onClick={() => { chooseMap(i); choosePage("Раунды"); }}>
          {m.mapId?.startsWith("de_") && <img loading="lazy" src={serverURL("/api/maps/"+m.mapId+"/radar.png").href} alt=""/>}
          <small>КАРТА {i+1}</small><b>{mapName(m)}</b><strong>{event.teams.map(t => m.scoreByTeam?.[t] ?? "—").join(" : ")}</strong>
          <span>{m.winnerTeamId ? "Победа · "+teamName(m.winnerTeamId) : "Победитель неизвестен"}</span>
        </button>)}</div>}
      {page !== pages[4] && <label className="report-filter">Выборка
        <select value={selection} onChange={e => chooseMap(Number(e.target.value))}>
          {page !== "Раунды" && <option value={-1}>Вся встреча</option>}
          {maps.map((m,i) => <option key={i} value={i}>{i+1} · {mapName(m)}</option>)}
        </select></label>}
      {page === pages[0] && <div className="report-panel">
        <h3>MVP {selection < 0 && report.maps ? "серии" : "карты"}</h3>
        {award ? <div className="report-award"><div><LineupPortrait id={award.player} name={award.name} visual={visual(award.player,award.teamId)}/></div>
          <div><small>{teamName(award.teamId)}</small><h4>{award.name}</h4>
            <p>{award.rounds} раундов · {metrics.version}</p><dl>
              <div><dt>Impact</dt><dd>{award.impact?.toFixed(2)}</dd></div>
              <div><dt>ADR</dt><dd>{award.adr?.toFixed(1)}</dd></div>
              <div><dt>KAST</dt><dd>{award.kastPercent?.toFixed(1)}%</dd></div>
            </dl></div></div> : <p>Для определения MVP недостаточно данных протокола.</p>}
        <details><summary>Методология Impact и MVP</summary>
          <p>Impact = 0,50 × (убийства за раунд / 0,70) + 0,20 × (ADR / 75) + 0,20 × (доля KAST / 0,70) + 0,10 × (доля выигранных первых контактов / 0,50). Без первых контактов последний вклад равен нулю.</p>
          <p>MVP получает игрок победившей команды, сыгравший не менее половины раундов. При равном Impact учитываются ADR, KAST и идентификатор игрока. Формула игры · {metrics.version}.</p></details>
      </div>}
      {page === "Статистика" && groups.map(tid => <div key={tid || "unknown"} className="report-table" role="region" tabIndex={0} aria-label={teamName(tid)}>
        <table><caption>{teamName(tid)}</caption><thead><tr>{["Игрок","K","D","A","ADR","KAST","FK / FD","Клатчи","Закупки, $","Impact"].map(h=><th key={h} scope="col">{h}</th>)}</tr></thead>
        <tbody>{current.stats.filter(p=>p.teamId===tid).map(p=>{
          const summary = metrics.players.find(r=>r.player===p.player);
          const count = summary?.rounds;
          return <tr key={p.player}><th scope="row">{p.name || p.player}</th>
            <td>{p.k ?? "—"}</td><td>{p.d ?? "—"}</td><td>{p.a ?? "—"}</td>
            <td>{count && p.damage != null ? (p.damage/count).toFixed(1) : "—"}</td><td>{count && p.kast != null ? (100*p.kast/count).toFixed(1)+"%" : "—"}</td>
            <td>{p.opening ?? "—"} / {p.openingDeaths ?? "—"}</td><td>{p.clutches ?? "—"}</td><td>{p.spent ?? "—"}</td><td>{summary?.impact?.toFixed(2) ?? "—"}</td></tr>;
        })}</tbody></table></div>)}
      {page === "Статистика" && <section className="report-panel"><h3>Раунды по сторонам</h3>
        {groups.filter(t => t !== null).map(t => {
          const played = current.rounds.filter(r => r.winnerTeamId === t);
          const known = current.rounds.length > 0 && current.rounds.every(r => r.winnerTeamId && ["T","CT"].includes(r.side));
          return <p key={t}>{teamName(t)} · T {known ? played.filter(r => r.side === "T").length : "—"} / CT {known ? played.filter(r => r.side === "CT").length : "—"}</p>;
        })}</section>}
      {page === "Статистика" && !utilityRecorded && <p className="report-panel">Эффективность гранат в этом протоколе не записана.</p>}
      {page === "Статистика" && utilityRecorded && <div className="report-table" role="region" tabIndex={0} aria-label="Эффективность гранат"><table>
        <caption>Эффективность гранат</caption><thead><tr>{["Игрок","Световые","Ослепления соперника","Флеш-ассисты","Урон HE","Урон огнём","Дымовые"].map(h => <th scope="col" key={h}>{h}</th>)}</tr></thead>
        <tbody>{current.stats.map(p => <tr key={p.player}><th scope="row">{p.name || p.player}</th>
          {[p.flashesThrown,p.enemiesFlashed,p.flashAssists,p.heDamage,p.fireDamage,p.smokesThrown].map((v,i) => <td key={i}>{v ?? "—"}</td>)}</tr>)}</tbody></table></div>}
      {page === "Раунды" && <section className="report-panel"><h3>История раундов</h3>
        <div className="report-rounds">{current.rounds.map((r,i)=><button aria-pressed={i===roundIndex} key={i} onClick={()=>setRoundIndex(i)}>{r.round ?? i+1}</button>)}</div>
        {round ? <><h4>Раунд {round.round ?? roundIndex+1} · {round.score?.join(" : ") || "Счёт неизвестен"}</h4>
          <p>{teamName(round.winnerTeamId)} · {round.side} · {reasonNames[round.reason || ""] || round.reason || "Причина не записана"}</p>
          <p>{round.buys?.map((b,i)=>teamName((current.teams || event.teams)[i])+" · "+(buyNames[b] || b)).join(" / ") || "Данные закупки не записаны"}</p></> : <p>Журнал раундов отсутствует.</p>}</section>}
      {page === "Составы на дату" && <div className="report-lineups">{groups.map(tid=><section className="report-panel" key={tid || "unknown"}><h3>{teamName(tid)}</h3>
        {current.stats.filter(p=>p.teamId===tid).map(p=><div className="report-member" key={p.player}><Avatar {...visual(p.player,tid)} name={p.name || p.player}/>
          <span>{p.name || p.player}</span></div>)}</section>)}</div>}
      {page === "Протокол и данные" && report.forecasts && <ForecastLine quotes={report.forecasts} names={teams}/>}
      {page === "Протокол и данные" && <section className="report-panel"><h3>Происхождение и полнота</h3>
        <p>Встреча {event.id} · {date(event.date)}</p><p>Источник — сохранённые протоколы завершённых карт. Составы и принадлежность игроков определяются по записям встречи.</p>
        <p>Методика {report.performance.version}. Прочерк означает, что показатель не записан или для его расчёта недостаточно сведений.</p></section>}
    </>}
  </section>;
}
