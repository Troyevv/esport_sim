import { Avatar, type Visual } from "./SceneIdentity";
import "./report.css";

export function ResultScore({ teams, score }: {
  teams: { id: string; name: string; visual?: Visual }[];
  score: string;
}) {
  return <div className="report-score">
    {teams.map((team, index) => <div className="report-team" key={team.id}>
      {index === 1 && <strong className="report-points">{score}</strong>}
      <span><Avatar {...team.visual} club name={team.name}/>{team.name}</span>
    </div>)}
  </div>;
}
