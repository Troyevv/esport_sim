import { memo } from "react";
import { Icon } from "./approved/Shared";
import { ItemIcon } from "./MatchEquipment";
import type { MatchView } from "./MatchCenter";
import type { SeriesView } from "./SeriesCenter";

type Notice = {title: string; detail: string; icon: string; tone: string};

// Walk back only through the uninterrupted deficit preceding this equalizer.
function recoveredDeficit(history: MatchView["history"], winner: string, rival: string) {
  const last = history.at(-1);
  if (!last || last.scoreByTeam[winner] !== last.scoreByTeam[rival]) return 0;
  let deficit = 0;
  for (let i = history.length - 2; i >= 0; i--) {
    const scores = history[i].scoreByTeam;
    const gap = scores[rival] - scores[winner];
    if (gap <= 0) break;
    deficit = Math.max(deficit, gap);
  }
  return deficit;
}

export function broadcastNotices(m: MatchView, series?: SeriesView): Notice[] {
  const notices: Notice[] = [];
  if (m.phase === "timeout" || m.breakOwner) {
    const owner = m.clubs.find(c => c.id === m.breakOwner);
    return [{title:"Тактический тайм-аут", detail:owner?.name || "", icon:"tactic", tone:"break"}];
  }
  const result = m.phase === "result" || m.phase === "finished";
  const last = m.history.at(-1);
  if (result && last?.round === m.round) {
    const winner = m.clubs.find(c => c.id === last.winnerTeamId);
    const rival = m.clubs.find(c => c.id !== last.winnerTeamId);
    if (winner && rival) {
      const deficit = recoveredDeficit(m.history,winner.id,rival.id);
      if (deficit >= 5) notices.push({title:"Камбэк",detail:winner.name+" сравнивает после −"+deficit,icon:"chart",tone:"moment"});
    }
  }
  if (m.kills.length >= 5) {
    const eliminations = new Map<string, Set<string>>();
    for (const kill of m.kills) {
      if (!kill.enemy || kill.weapon === "C4") continue;
      const victims = eliminations.get(kill.player) || new Set<string>();
      victims.add(kill.target);
      eliminations.set(kill.player,victims);
      if (victims.size === 5) {
        notices.push({title:"Эйс",detail:m.stats.find(p=>p.id===kill.player)?.name || kill.player,icon:"bolt",tone:"moment"});
        break;
      }
    }
  }
  if (result || !m.roundFormat) return notices;
  const {half,overtimeHalf} = m.roundFormat;
  const overtime = Math.max(0,Math.ceil((m.round - 2*half)/(2*overtimeHalf)));
  const target = half + overtime*overtimeHalf + 1;
  const contenders = m.clubs.filter(c => c.score === target-1);
  for (const club of contenders) {
    const clinches = !series || series.score[club.id] === Math.floor(series.bestOf/2);
    notices.push({title:clinches?"Матч-пойнт":"Мап-пойнт",detail:club.name,icon:"flag",tone:"point"});
  }
  if (overtime) notices.push({title:"Овертайм "+overtime,detail:"До "+target+" раундов",icon:"clock",tone:"extra"});
  return notices;
}

export const OnAirNotice = memo(function OnAirNotice({title,detail,icon,tone}: Notice) {
  return <span className="mx-onair-notice" data-tone={tone}>
    {icon==="C4" || icon==="Набор" ? <ItemIcon name={icon}/> : <Icon name={icon} size={16}/>}
    <b>{title}</b>{detail && <span>{detail}</span>}
  </span>;
});
