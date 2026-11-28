import { ProfileAction } from "./CareerIdentity";
import { Avatar, type Visual } from "./SceneIdentity";
import "./report.css";

export function ResultScore({ teams, score, beforeOpen }: {
  teams: { id: string; name: string; visual?: Visual }[];
  score: string;
  beforeOpen?: () => void;
}) {
  return <div className="report-score">
    {teams.map((team, index) => <div className="report-team" key={team.id}>
      {index === 1 && <strong className="report-points">{score}</strong>}
      <span><ProfileAction group="teams" id={team.id} beforeOpen={beforeOpen}><span className="result-club"><Avatar {...team.visual} club name={team.name}/>{team.name}</span></ProfileAction></span>
    </div>)}
  </div>;
}
