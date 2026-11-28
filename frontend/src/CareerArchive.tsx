import { EntityPicker } from "./EntityPicker";
import { useEffect, useRef, useState } from "react";
import { date, fixtureScore, type Career, type Fixture, type Scene } from "./careerData";
import { EntityName, EditionLink } from "./CareerIdentity";
import { Heading } from "./GameUI";
import { MatchReport } from "./CareerForms";
import ProfileHistory from "./ProfileHistory";

export default function CareerArchive({ c, scene, revision, analytics }: { c:Career; scene:Scene; revision:number; analytics:boolean }) {
  const [limit,setLimit] = useState(25);
  const [team,setTeam] = useState(c.team);
  const [group,setGroup] = useState<"teams"|"players">("teams");
  const [player,setPlayer] = useState(c.roster[0]?.id || "");
  const [selected,setSelected] = useState<Fixture | null>(null);
  const lastFixture = useRef<string | null>(null);
  useEffect(() => {
    if (!selected && lastFixture.current) {
      document.getElementById("archive-" + lastFixture.current)?.focus();
      lastFixture.current = null;
    }
  }, [selected]);
  if (selected && !analytics) return <div className="archive-protocol" onKeyDown={e => {
    if (e.key === "Escape" && !e.defaultPrevented) setSelected(null);
  }}>
    <button className="link-button" onClick={() => setSelected(null)}>← Архив матчей</button>
    <MatchReport event={selected} careerId={c.id} teams={c.teams} close={() => setSelected(null)}/>
  </div>;
  const rows = c.history.filter(f=>f.kind === "match" && (!team || f.teams.includes(team))).slice().reverse();
  return <div className="career-archive">
    <Heading title={analytics?"Аналитика":"Архив матчей"} sub={c.club+" · "+date(c.date)}/>
    <div className="history-filters">
      {analytics && <label>Участники<select value={group} onChange={e=>setGroup(e.target.value as typeof group)}>
        <option value="teams">Команды</option><option value="players">Игроки</option></select></label>}
      {group==="players" && analytics
        ? <EntityPicker label="Игрок" group="players" options={scene.players} value={player} select={setPlayer}/>
        : <EntityPicker label="Команда" group="teams" options={c.teams} value={team} empty={analytics ? undefined : "Все команды"}
            select={id=>{setTeam(id);setLimit(25)}}/>}
    </div>
    {analytics ? <ProfileHistory key={group} c={c} scene={scene} revision={revision} group={group} id={group==="teams"?team:player}/>
      : <section className="surface panel-body"><h2>Завершённые встречи · {rows.length}</h2>
        {rows.slice(0,limit).map(f=><article className="archive-score-row" key={f.id}>
          <div className="archive-event"><time>{date(f.date)}</time><EditionLink id={f.edition}>{f.title || (f.pcw?"Пракк":"Встреча календаря")}</EditionLink></div>
          <div className="archive-versus">{f.teams.map((id,i)=><div key={id} className="archive-contender">
            <EntityName group="teams" id={id} fallback={c.teams[id]}/>
            <b>{f.scoreByTeam?.[id] ?? f.score?.[i] ?? "—"}</b></div>)}</div>
          <button className="btn sm" id={"archive-"+f.id} aria-label={"Протокол "+f.teams.map(t=>c.teams[t] || t).join(" — ")+" · "+fixtureScore(f)} onClick={()=>{lastFixture.current=f.id;setSelected(f)}}>Протокол</button>
        </article>)}
        {limit<rows.length && <button className="btn" onClick={()=>setLimit(n=>n+25)}>Показать ещё · {Math.min(25,rows.length-limit)}</button>}
        {!rows.length && <p>В истории карьеры пока нет завершённых встреч для выбранной команды.</p>}
      </section>}
  </div>;
}
