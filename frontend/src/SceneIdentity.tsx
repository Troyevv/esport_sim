import { badgeSurface, GamePortrait, type ClubKit } from "./GamePortrait";
import { useState } from "react";
import { resolvePortrait, type PhotoRef } from "./portraits";

const flags = new Map<string, string>();
const names = new Intl.DisplayNames(["ru"], { type: "region" });
const english = new Intl.DisplayNames(["en"], { type: "region" });
for (let a = 65; a <= 90; a++)
  for (let b = 65; b <= 90; b++) {
    const code = String.fromCharCode(a, b);
    const ru = names.of(code),
      en = english.of(code);
    if (ru && ru !== code) {
      flags.set(ru.toLowerCase(), code);
      if (en) flags.set(en.toLowerCase(), code);
      flags.set(code.toLowerCase(), code);
    }
  }
const regions: Record<string, [string, string]> = {
  Europe: ["Европа", "EUR"],
  Americas: ["Америка", "AM"],
  Asia: ["Азия", "AS"],
  World: ["Международный состав", "INT"],
};
export function Flag({ value }: { value?: string | null }) {
  const region = value && regions[value];
  const code = flags.get((value || "").trim().toLowerCase());
  const label = region
    ? region[0]
    : code
      ? names.of(code)!
      : value || "Страна не установлена";
  if (code && !region)
    return (
      <span className="scene-flag" title={label}>
        <img src={"/flags/" + code.toLowerCase() + ".svg"} alt={label} />
      </span>
    );
  return (
    <span className="scene-flag" title={label}>
      <svg role="img" aria-label={label} viewBox="0 0 34 23">
        <title>{label}</title>
        <rect
          width="34"
          height="23"
          rx="2"
          fill={region ? "#324e60" : "#3c4a50"}
        />
        <g stroke="#b8cbd0" strokeWidth=".9" fill="none">
          <circle cx="11" cy="11" r="7.5" />
          <ellipse cx="11" cy="11" rx="3.8" ry="7.5" />
          <path d="M4 9h14M4 13h14" />
        </g>
        <text x="19" y="14" fill="white" fontSize="7.5" fontWeight="700">
          {region ? region[1] : "?"}
        </text>
      </svg>
    </span>
  );
}
export type Visual = {
  photo?: PhotoRef;
  url?: string | null;
  flag?: string | null;
  club?: boolean;
  badgeLicense?: string | null;
  gameBadge?: boolean;
  player?: boolean;
  head?: string | null;
  kit?: ClubKit | null;
};
export function Avatar({
  name,
  photo,
  url,
  club = false,
  badgeLicense,
  gameBadge,
  player = false,
  head,
  kit,
}: { name: string } & Visual) {
  const asset = resolvePortrait(photo);
  const [failed, setFailed] = useState("");
  const src = url || asset?.image;
  if (player) return <GamePortrait name={name} head={head} kit={kit} />;
  if (src && failed !== src)
    return (
      <img
        className={club ? "scene-avatar club-mark" : "scene-avatar"}
        data-spirit={
          (club &&
            (asset?.license ?? badgeLicense) === "Условия Team Spirit") ||
          undefined
        }
        style={
          club
            ? {
                backgroundColor: badgeSurface(
                  name,
                  asset?.license ?? badgeLicense,
                ),
              }
            : undefined
        }
        alt={
          (club
            ? gameBadge || asset?.changes.startsWith("Игровая эмблема")
              ? "Игровая эмблема · "
              : "Эмблема · "
            : "Фотография · ") + name
        }
        src={src}
        referrerPolicy="no-referrer"
        onError={() => setFailed(src)}
      />
    );
  return (
    <svg
      className="scene-avatar scene-placeholder"
      viewBox="0 0 40 40"
      aria-hidden="true"
    >
      <rect width="40" height="40" rx="7" fill="#233738" />
      {club ? (
        <path
          d="M10 9l10-3 10 3v12c-1 6-6 10-10 13-4-3-9-7-10-13z"
          fill="#759490"
        />
      ) : (
        <g fill="#8aa3a0">
          <circle cx="20" cy="14" r="7" />
          <path d="M6 36c1-9 6-14 14-14s13 5 14 14z" />
        </g>
      )}
    </svg>
  );
}
export function Identity({ name, visual }: { name: string; visual?: Visual }) {
  return (
    <span className="scene-identity">
      <Avatar name={name} {...visual} />
      <span>{name}</span>
      <Flag value={visual?.flag} />
    </span>
  );
}
