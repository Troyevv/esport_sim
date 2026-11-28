import { useEffect, useRef, useState } from "react";
import { date, fixtureName, fixtureScore, type Career, type Fixture, type Scene } from "./careerData";
import { Heading } from "./GameUI";
import { MatchReport } from "./CareerForms";
import ProfileHistory from "./ProfileHistory";

export default function CareerArchive({ c, scene, revision, analytics }: { c:Career; scene:Scene; revision:number; analytics:boolean }) {
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
      {group==="players" && analytics ? <label>Игрок<select value={player} onChange={e=>setPlayer(e.target.value)}>
        {Object.values(scene.players).sort((a,b)=>a.name.localeCompare(b.name)).map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
        : <label>Команда<select value={team} onChange={e=>setTeam(e.target.value)}>{!analytics && <option value="">Все команды</option>}
          {Object.entries(c.teams).sort((a,b)=>a[1].localeCompare(b[1])).map(([id,name])=><option key={id} value={id}>{name}</option>)}</select></label>}
    </div>
    {analytics ? <ProfileHistory key={group} c={c} scene={scene} revision={revision} group={group} id={group==="teams"?team:player}/>
      : <section className="surface panel-body"><h2>Завершённые встречи · {rows.length}</h2>
        {rows.map(f=><button className="archive-match" id={"archive-"+f.id} key={f.id} onClick={()=>{lastFixture.current=f.id;setSelected(f)}}>
          <time>{date(f.date)}</time><span><strong>{fixtureName(c,f)}</strong><small>{f.title || (f.pcw?"Пракк":"Встреча календаря")}</small></span>
          <b>{fixtureScore(f) || "—"}</b></button>)}
        {!rows.length && <p>В истории карьеры пока нет завершённых встреч для выбранной команды.</p>}
      </section>}
  </div>;
}
