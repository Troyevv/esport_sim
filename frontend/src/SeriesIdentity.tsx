import { useContext, type CSSProperties } from "react";
import { CareerLinks } from "./CareerIdentity";
import { CompetitionMark, eventMark } from "./CompetitionMark";
import { kitDesign } from "./GamePortrait";
import { Icon } from "./approved/Shared";
import type { Visual } from "./SceneIdentity";
import type { SeriesView } from "./SeriesCenter";

export function clubColors(id: string, club: {name: string; visual?: Visual}) {
  const kit = kitDesign(club.visual?.kit || {id, name: club.name});
  return {"--club-primary": kit.primary, "--club-accent": kit.accent} as CSSProperties;
}

export function SeriesEvent({series, fallback}: {series?: SeriesView; fallback: string}) {
  const edition = series?.edition;
  const name = series?.tournament || fallback;
  const links = useContext(CareerLinks);
  const content = <>
    {edition ? <CompetitionMark mark={eventMark(edition.id, edition.organizer)} name={name}
      year={edition.year} cycle={edition.id} size={26}/> : <Icon name="trophy" size={18}/>}
    {name}
  </>;
  return edition && links
    ? <button type="button" className="series-event event-link" onClick={()=>links.tournament(edition.id)}>{content}</button>
    : <span className="series-event">{content}</span>;
}
