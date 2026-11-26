import { useId, useRef, useEffect, useState } from "react";

import {
  mapBounds,
  portraitFrame,
  tailor,
  useFittedFabric,
  shoulderFrame,
} from "./portraitAnatomy";
import calibrations from "./portraitFit.json";
import drawings from "./kitArt.json";
import { type GarmentRig, useGarment } from "./wardrobe";

const stockRig: GarmentRig = {
  width: 660,
  height: 440,
  collar: [330, 103],
  span: 615.4,
  seat: [120, 157],
};

const fittings: Record<string, number[]> = calibrations;
const catalogue: Record<
  string,
  { name: string; source: string | null; badgeX: number; rig?: GarmentRig }
> = drawings;
export function artwork(kit?: ClubKit | null) {
  return kit && !kit.design ? catalogue[kit.id] : undefined;
}

export type KitDesign = {
  primary: string;
  accent: string;
  pattern: "plain" | "sash" | "panels" | "chevron";
};
export type ClubKit = {
  id: string;
  name: string;
  badge?: string | null;
  badgeLicense?: string | null;
  design?: KitDesign | null;
};
export function badgeSurface(name: string, license?: string | null) {
  if (license === "Условия Team Spirit") return "#000";
  if (
    license === "PD-textlogo" &&
    ["ENVY", "100 Thieves", "MIBR Academy"].includes(name)
  )
    return "#dae0de";
  return undefined;
}
export const neutralKit: KitDesign = {
  primary: "#555f69",
  accent: "#808992",
  pattern: "plain",
};
const palettes = [
  "#1e6679",
  "#713856",
  "#514790",
  "#285749",
  "#384976",
  "#8d4b31",
];
const signature: Record<string, [string, string, KitDesign["pattern"]]> = {
  vitality: ["#272829", "#ffda24", "chevron"],
  "team vitality": ["#272829", "#ffda24", "chevron"],
  astralis: ["#a82636", "#202531", "panels"],
  "100 thieves": ["#20252b", "#e63b49", "sash"],
  "team falcons": ["#165c47", "#a4cc53", "panels"],
  falcons: ["#165c47", "#a4cc53", "panels"],
  mouz: ["#b92846", "#ef8691", "chevron"],
  "team spirit": ["#e4e5e6", "#20282c", "panels"],
  "natus vincere": ["#191d23", "#e9d338", "sash"],
};
export function kitDesign(club?: ClubKit | null): KitDesign {
  if (!club) return neutralKit;
  if (club.design) return club.design;
  const preset = signature[club.name.toLowerCase()];
  if (preset)
    return { primary: preset[0], accent: preset[1], pattern: preset[2] };
  const seed = Array.from(club.id).reduce(
    (a, c) => (31 * a + c.charCodeAt(0)) >>> 0,
    0,
  );
  return {
    primary: palettes[seed % palettes.length],
    accent: "#d2d8dd",
    pattern: (["panels", "chevron", "sash"] as const)[seed % 3],
  };
}

// The normalized RGBA face is a replaceable input. The same geometry accepts a
// future generated appearance. Membership and all clothing live outside it.
export function GamePortrait({
  name,
  head,
  kit,
  showShoulders = false,
  staff = false,
}: {
  name: string;
  showShoulders?: boolean;
  staff?: boolean;
  head?: string | null;
  kit?: ClubKit | null;
}) {
  const id = useId().replace(/:/g, "_");
  const [badHead, setBadHead] = useState("");
  const [badBadge, setBadBadge] = useState("");
  const design = kitDesign(kit);
  const measured = head?.match(
    /^\/api\/portraits\/image\/[0-9a-f]{64}\?nativeWidth=(\d+)$/,
  );

  const digest = head?.match(/\/portraits\/image\/([0-9a-f]{64})/)?.[1];
  const frame = portraitFrame(digest);
  const surfaceFrame = frame && shoulderFrame(frame);
  const camera = showShoulders ? surfaceFrame : frame?.camera;
  const fit = digest ? fittings[frame?.original || digest] : undefined;
  const naturalWidth = measured
    ? Number(measured[1]) * (camera ? camera[2] / 240 : 1)
    : undefined;
  const art = artwork(kit);
  const personal = useGarment(art ? kit?.id : undefined);
  const [failedCloth, setFailedCloth] = useState("");
  const pattern =
    art && kit ? "/portraits/kits/" + kit.id + ".webp" : undefined;
  const localImage = personal && "/api/portraits/image/" + personal.sha256;
  const photographed =
    localImage && localImage !== failedCloth ? personal : undefined;
  const textile = photographed ? localImage : pattern;
  const garment = photographed?.sha256 || (art && kit ? kit.id : "neutral");
  const fitted =
    digest && badHead !== head ? tailor(digest, garment) : undefined;
  const rig = photographed?.rig || art?.rig || stockRig;
  const scale = 246 / rig.span;
  const clothTransform = `translate(${rig.seat[0]} ${rig.seat[1]}) scale(${scale}) translate(${-rig.collar[0]} ${-rig.collar[1]})`;
  const box = {
    width: rig.width,
    height: rig.height,
    transform: clothTransform,
  };
  const headTransform = frame
    ? undefined
    : fit
      ? `translate(${fit[1]} ${fit[2]}) scale(${fit[0]})`
      : undefined;
  const portrait = useRef<SVGSVGElement>(null);
  const spirit = kit?.badgeLicense === "Условия Team Spirit";
  const [largePatch, setLargePatch] = useState(false);
  useEffect(() => {
    if (!spirit || !portrait.current) return;
    const svg = portrait.current;
    const measure = () => {
      const { width, height } = svg.getBoundingClientRect();
      // The mark occupies 2/3 of its 40-unit patch. Keep the 18px brand minimum.
      setLargePatch(Math.min(width / 240, height / 280) * 40 * (2 / 3) >= 18);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(svg);
    return () => observer.disconnect();
  }, [spirit]);
  const badgeX = art?.badgeX || 162;
  const patch = spirit
    ? { x: badgeX - 20, y: 180, width: 40, height: 40 }
    : { x: badgeX - 12, y: 187, width: 24, height: 24 };
  const surface = kit && badgeSurface(kit.name, kit.badgeLicense);
  const paths = {
    plain: "",
    sash: "M29 174l18-18 163 106-19 23z",
    panels: "M0 168l42-11 22 17-29 84H0z M240 168l-42-11-22 17 29 84h35z",
    chevron: "M-6 160l63 5 63 45 63-45 63-5v13l-60 7-66 48-66-48-60-7z",
  };
  const href = (s: string) => "url(#" + id + s + ")";
  const surfaceImage = textile || "/portraits/jersey.webp";
  const smooth = useFittedFabric(
    badHead !== head ? digest : undefined,
    garment,
    surfaceImage,
    rig,
  );
  const fittedBox = surfaceFrame && {
    x: surfaceFrame[0],
    y: surfaceFrame[1],
    width: surfaceFrame[2],
    height: surfaceFrame[3],
  };
  const placedFabric = smooth && (
    <image
      data-layer="fitted-fabric"
      href={smooth}
      {...fittedBox}
      preserveAspectRatio="none"
    />
  );
  const cloth = <image href="/portraits/jersey.webp" {...box} />;
  // A channel transfer keeps the highlights, seams and folds of the jersey in
  // both colour regions, including nearly black or white fabrics.
  const tint = (suffix: string, hex: string) => (
    <filter id={id + suffix} colorInterpolationFilters="sRGB">
      <feComponentTransfer>
        {([0, 1, 2] as const).map((c) => {
          const Channel = (["feFuncR", "feFuncG", "feFuncB"] as const)[c];
          const value = parseInt(hex.slice(1 + c * 2, 3 + c * 2), 16) / 255;
          return (
            <Channel
              key={c}
              type="table"
              tableValues={`0 ${value * 0.59} ${value} ${value + (1 - value) * 0.32} ${value + (1 - value) * 0.72}`}
            />
          );
        })}
      </feComponentTransfer>
    </filter>
  );
  return (
    <svg
      ref={portrait}
      style={
        naturalWidth
          ? { maxWidth: naturalWidth, maxHeight: (naturalWidth * 280) / 240 }
          : undefined
      }
      className="scene-avatar game-portrait"
      viewBox={camera && badHead !== head ? camera.join(" ") : "0 0 240 280"}
      role="img"
      aria-label={
        name + (head?.includes("/generated/") ? " · синтетический портрет · " : " · ") + (kit ? "форма " + kit.name : "нейтральная одежда")
      }
      data-team={kit?.id || ""}
      data-synthetic={head?.includes("/generated/") || undefined}
    >
      <defs>
        {fitted && (
          <filter
            id={id + "drape"}
            filterUnits="userSpaceOnUse"
            primitiveUnits="userSpaceOnUse"
            {...mapBounds}
            colorInterpolationFilters="sRGB"
          >
            <feImage
              href={fitted.image}
              {...mapBounds}
              preserveAspectRatio="none"
              result="coordinates"
            />
            <feDisplacementMap
              in="SourceGraphic"
              in2="coordinates"
              scale="255"
              xChannelSelector="R"
              yChannelSelector="G"
            />
          </filter>
        )}
        <filter id={id + "edge"} x="-4%" y="-4%" width="108%" height="108%">
          <feGaussianBlur in="SourceAlpha" stdDeviation=".42" result="edge" />
          <feComposite in="SourceGraphic" in2="edge" operator="in" />
        </filter>
        <linearGradient id={id + "light"} x1="0" x2="1" y1="0" y2=".15">
          <stop
            stopColor="#0d1014"
            stopOpacity={Math.max(0, -(fit?.[3] || 0)) * 0.4}
          />
          <stop offset=".53" stopColor="#0d1014" stopOpacity="0" />
          <stop
            offset="1"
            stopColor="#0d1014"
            stopOpacity={Math.max(0, fit?.[3] || 0) * 0.4}
          />
        </linearGradient>
        {smooth && (
          <mask
            id={id + "fitted-alpha"}
            maskUnits="userSpaceOnUse"
            {...fittedBox}
            style={{ maskType: "alpha" }}
          >
            {placedFabric}
          </mask>
        )}
        <mask id={id + "fabric"} style={{ maskType: "alpha" }}>
          <image href={surfaceImage} {...box} />
        </mask>
        {fit && head && (
          <mask
            id={id + "neck"}
            maskUnits="userSpaceOnUse"
            x="0"
            y="0"
            width="240"
            height="280"
            style={{ maskType: "alpha" }}
          >
            <image
              href={head}
              width="240"
              height="280"
              transform={headTransform}
            />
          </mask>
        )}
        <filter
          id={id + "contact"}
          x="-15%"
          y="-15%"
          width="130%"
          height="130%"
        >
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.6" />
          <feOffset dx={-(fit?.[3] || 0)} dy="-1.1" />
        </filter>
        {tint("cloth", design.primary)}
        {tint("trim", design.accent)}
        <clipPath id={id + "panel"}>
          <path d={paths[design.pattern]} />
        </clipPath>
        <linearGradient
          id={id + "silhouette"}
          x2=".9"
          y2="1"
          gradientUnits="objectBoundingBox"
        >
          <stop stopColor="#899697" />
          <stop offset=".55" stopColor="#718080" />
          <stop offset="1" stopColor="#546363" />
        </linearGradient>
      </defs>
      {staff && <image href="/portraits/club-jacket.webp" x="0" y="121" width="240" height="160" preserveAspectRatio="none"/>}
      {head && badHead !== head ? (
        <image
          data-layer="appearance"
          href={head}
          transform={headTransform}
          filter={fit && !frame ? href("edge") : undefined}
          width="240"
          height="280"
          onError={() => setBadHead(head)}
        />
      ) : (
        <path
          data-layer="placeholder"
          fill={href("silhouette")}
          d="M88 140c7-1 9-9 9-18-8-7-13-20-16-30-5-2-7-10-6-17 0-3 2-5 4-5-3-29 9-54 40-55 29-1 45 18 43 54 4-1 6 2 6 7 0 9-2 15-7 17-3 14-9 23-16 30 0 10 2 15 10 18l5 15-6 28H85l-6-29z"
        />
      )}
      {fit && (
        <g mask={href("neck")} opacity=".34">
          <g filter={href("contact")}>
            {smooth ? (
              placedFabric
            ) : (
              <g filter={fitted ? href("drape") : undefined}>
                <g transform={fitted?.placement}>
                  <image href={surfaceImage} {...box} />
                </g>
              </g>
            )}
          </g>
        </g>
      )}
      <g data-layer="kit" transform={!staff && head?.includes("/generated/") ? "translate(0 8)" : undefined}>
        {smooth && (
          <g filter={textile ? undefined : href("cloth")}>{placedFabric}</g>
        )}
        <g filter={fitted ? href("drape") : undefined}>
          <g transform={fitted?.placement}>
            {staff && <image href="/portraits/club-jacket-front.webp" x="0" y="121" width="240" height="160" preserveAspectRatio="none"/>}
            {!staff && !smooth &&
              (textile && textile !== failedCloth ? (
                <image
                  data-layer="garment"
                  href={textile}
                  {...box}
                  onError={() => setFailedCloth(textile)}
                />
              ) : (
                <g filter={href("cloth")}>{cloth}</g>
              ))}
            {!staff && (!textile || textile === failedCloth) &&
              design.pattern !== "plain" && (
                <g clipPath={href("panel")}>
                  <g filter={href("trim")}>{cloth}</g>
                </g>
              )}
            {!photographed &&
              kit?.badge &&
              badBadge !== kit.badge &&
              (!spirit || largePatch) && (
                <g>
                  {surface && (
                    <rect {...patch} fill={surface} rx={spirit ? 0 : 4} />
                  )}
                  <image
                    href={kit.badge}
                    {...patch}
                    onError={() => setBadBadge(kit.badge!)}
                  />
                </g>
              )}
            {fit && !smooth && (
              <rect
                width="240"
                height="280"
                fill={href("light")}
                mask={href("fabric")}
              />
            )}
          </g>
        </g>
        {smooth && (
          <rect
            {...fittedBox}
            fill={href("light")}
            mask={href("fitted-alpha")}
          />
        )}
      </g>
    </svg>
  );
}
