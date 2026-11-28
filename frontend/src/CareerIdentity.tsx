import { createContext, useContext, Fragment, type ReactNode } from "react";
import { Avatar, LineupPortrait } from "./SceneIdentity";
import { type Profile, type Scene, type Fixture } from "./careerData";
import { Glyph } from "./GameUI";
import { Icon } from "./approved/Shared";
import { roles } from "./databaseModel";
import "./career-identity.css";

export const CareerLinks = createContext<{
  scene: Scene | undefined;
  open: (profile: Profile) => void;
  tournament: (id: string) => void;
} | null>(null);

export function ProfileAction({group, id, children, beforeOpen}: {
  group: Profile["group"]; id?: string; children: ReactNode; beforeOpen?: () => void;
}) {
  const nav = useContext(CareerLinks);
  if (!id || !nav?.scene?.[group][id]) return <>{children}</>;
  return <button className="profile-action" onClick={()=>{
    beforeOpen?.();
    nav.open({group,id});
  }}>{children}</button>;
}

export function EntityName({group, id, fallback, historicalTeam, recordedName, link = true}: Profile & { fallback?: string; historicalTeam?: string | null; recordedName?: string; link?: boolean }) {
  const nav = useContext(CareerLinks);
  const entity = nav?.scene?.[group][id];
  if (!entity) return <span>{recordedName || fallback || id}</span>;
  const displayName = recordedName || entity.name;
  const visual = entity.visual;
  const portrait = historicalTeam === undefined || visual.kit?.id === historicalTeam ? visual : {...visual,kit:null};
  const mark = group === "players"
    ? <LineupPortrait id={id} name={displayName} visual={portrait}/>
    : <Avatar name={displayName} {...portrait}/>;
  const content = <><span className="identity-mark" aria-hidden="true">{mark}</span><span>{displayName}</span></>;
  return link
    ? <button type="button" className="sport-identity profile-action" onClick={()=>nav.open({group,id})}>{content}</button>
    : <span className="sport-identity">{content}</span>;
}

export function FixtureTeams({teams, names, link = true}: Pick<Fixture,"teams"> & {names: Record<string,string>; link?: boolean}) {
  return <span className="fixture-identities">{teams.map((id,i)=><Fragment key={id}>{i>0 && <span className="versus-divider">—</span>}
    <EntityName group="teams" id={id} fallback={names[id]} link={link}/></Fragment>)}</span>;
}

export function EditionLink({id, children}: {id?: string | null; children: ReactNode}) {
  const nav = useContext(CareerLinks);
  return nav && id ? <button type="button" className="profile-action edition-link" onClick={()=>nav.tournament(id)}>
    <Glyph name="trophy"/>{children}</button> : <span>{children}</span>;
}

const roleIcons: Record<string,string> = {
  rifler:"training", entry:"bolt", lurker:"eye", awper:"search", support:"shield", igl:"tactic"
};
export function PlayerRole({role}: {role: string}) {
  return <span className="player-role">{roleIcons[role] && <Icon name={roleIcons[role]} size={15} aria-hidden="true"/>}{roles[role] || role || "—"}</span>;
}
