import type { CSSProperties } from "react";
import { Avatar, LineupPortrait, type Visual } from "../SceneIdentity";

export function TeamLogo({
  name,
  visual,
  size = 40,
}: {
  name: string;
  visual?: Visual;
  size?: number;
}) {
  return (
    <span
      className="team-logo"
      style={{ "--logo-size": size + "px" } as CSSProperties}
    >
      <Avatar club name={name} {...visual} />
    </span>
  );
}
export function Portrait({
  id,
  name,
  visual,
  size = "medium",
}: {
  id: string;
  name: string;
  visual?: Visual;
  size?: string;
}) {
  return (
    <div className={"portrait portrait-" + size}>
      <LineupPortrait id={id} name={name} visual={visual || {}} />
    </div>
  );
}
