import type { CSSProperties } from "react";

type BadgeProps = {
  mark: string;
  name: string;
  year?: number;
  cycle?: string;
  size?: number;
};
const art = {
  // Organizers. These independent game identities also work without lettering.
  "org-pgl": (
    <>
      <path
        fill="#ff735c"
        d="M5 17 31 4l27 13-19 9-8-4-10 5-7-4 17-9-1-1-25 13z"
      />
      <path
        fill="#f6d29b"
        d="m6 30 10-5 12 7-9 5v12L6 42zm17 10 12-7 20-10v10l-20 11v13l-12 7z"
      />
    </>
  ),
  "org-esl": (
    <>
      <path fill="#63e1bb" d="M3 48 22 12h12L16 48zM22 48 40 12h12L34 48z" />
      <path fill="#efffe9" d="m38 49 11-21 11 6-7 15zM5 53h48l-4 6H2z" />
    </>
  ),
  "org-cct": (
    <>
      <path
        fill="#b19aff"
        d="M32 2 54 14l-6 9-16-10-16 10-6-9zM6 23l10 5v15l11 6v12L6 49zm52 0v26L37 61V49l11-6V28z"
      />
      <path fill="#ffce75" d="m32 19 11 7-4 14-7 4-7-4-4-14z" />
    </>
  ),
  "org-blast": (
    <>
      <path
        fill="#f778af"
        d="m7 14 13 7 12-17 7 18 19-6-10 17 12 8-20 2-4 17-10-16-21 2 12-15z"
      />
      <path fill="#271735" d="m22 33 13-13-4 11 10-2-15 16 5-13z" />
    </>
  ),
  "cct-europe": (
    <>
      <path
        fill="#94baff"
        d="M4 36 15 11l17 13 21-18 6 7-16 33-9-6 8-17-13 13-9-8-6 13z"
      />
      <path fill="#ffd275" d="m5 49 17-8 12 8 18-5 6-8-3 16-24 9-13-9-14 6z" />
    </>
  ),
  "cct-playin": (
    <>
      <path
        fill="#e49ac6"
        d="M5 23 23 4l12 9-8 9-6-4-7 10 8 9-6 6L4 31zM42 9l12 8 7 15-15 19-9-5 12-16-4-5-7-2z"
      />
      <path fill="#ffddb2" d="m19 44 20-25 6 8-13 19 10 7-10 8-15-10z" />
    </>
  ),
  "org-firesports": (
    <>
      <path fill="#ff916c" d="M4 46 21 9h10l-6 16 14-6-14 21-9 4-4 11z" />
      <path
        fill="#fff0a0"
        d="M26 56 38 30l-7 2 19-24-4 16 13-7-13 27-10 4-5 10z"
      />
    </>
  ),
  "org-perfect world": (
    <>
      <path
        fill="#89cae8"
        d="m3 31 14-18 14-8-4 10-13 14 12-6-6 12-15 7zm30-16 12-7 10 10-10-1-11 7-7 9-5-2z"
      />
      <path
        fill="#ffba95"
        d="m27 39 13-17 9-2-6 11 16-6-5 12-12 14-16 8-10-2 17-12-1-5-10 5z"
      />
    </>
  ),
  buenos: (
    <>
      <path
        fill="#a5dcf5"
        d="M2 48 14 35l12-3 4-18 4-9 4 9 1 19 12 6 9 12-9-2-10-8-8-1-13 4-10 8z"
      />
      <path fill="#ffd676" d="m8 54 17-9 13-1 16 8-6 5-10-4-13 2-11 6z" />
      <circle cx="15" cy="18" r="6" fill="#ffab77" />
    </>
  ),
  shanghai: (
    <>
      <path
        fill="#df98c6"
        d="M3 50q14-1 20-10l6-11-4 1 7-12 3-14 3 15 7 10-5-1 7 13 14 9-18-5-8-7-12 10-18 6z"
      />
      <path
        fill="#f3ce74"
        d="m8 57 18-7 9-8 13 9 10 3-6 5-13-4-5-4-9 6-14 4z"
      />
      <path fill="#80c9ce" d="m10 28 4-14 8 4-4 9z" />
    </>
  ),
  "org-digital crusade": (
    <>
      <path
        fill="#fa9c87"
        d="M5 12h26l-6 9H14v15L5 47zm32-1 23 11v13L37 54l-10-4 22-18v-5l-18-7z"
      />
      <path
        fill="#b4eac5"
        d="M19 28h11l7-6 7 9-15 13-10-3zM5 53l10-9 10 6-12 8H5z"
      />
    </>
  ),
  draculan: (
    <>
      <path
        fill="#daa9ed"
        d="M3 15 20 21l8 12 3-18 3 5 4-7 2 18 8-12 14-8-6 20-13 2-10 17-8-14-12 2z"
      />
      <path fill="#ffbe81" d="m12 43 10-2 9 11 12-13 9-2-9 14-12 10-9-11z" />
      <circle cx="16" cy="8" r="5" fill="#f4d2a5" />
    </>
  ),
  // Singapore: a split vessel below a crescent, seen across the harbour.
  major: (
    <>
      <path
        fill="#f5d18b"
        d="M44 3a20 20 0 0 0-18 26c-11-2-17-13-8-22C25 0 38 0 44 3Z"
      />
      <path fill="#f5a47b" d="M40 8 57 37H36zm-5 10-2 19H19z" />
      <path
        fill="#55dcd2"
        d="m4 40 25 5 30-6-10 12-22 5L9 49zm5 14 18 5 21-5-7 7-15 3z"
      />
    </>
  ),
  contenders: (
    <>
      <path
        fill="#fac76d"
        d="M8 28 5 13l11 7 4-14 11 12 13-13 1 15 13-4-5 16-15 7H23z"
      />
      <path fill="#ee7867" d="m11 35 13 5 8 10 10-12 12-6-6 19-17 12-17-12z" />
      <path fill="#fff0d1" d="m25 26 7-6 7 6-7 7z" />
    </>
  ),
  oq1: (
    <>
      <path
        fill="#77d5ec"
        d="m5 52 12-33 17-9-7 15-7 2-6 23zM21 53l10-26 11-4-8 23z"
      />
      <path fill="#eafff0" d="m36 51 9-23-5-5 16-8 5 8-13 29z" />
      <path fill="#399aaf" d="m7 56 44-2-10 6H6z" />
    </>
  ),
  oq2: (
    <>
      <path
        fill="#ef93ca"
        d="M3 19 28 5l-7 15 14-5-8 17-24 9 10-15zm25 17 32-19-7 24-16 7 5-12-15 9z"
      />
      <path fill="#ffdb9b" d="m17 45 10-4-3 11 13-2-21 13z" />
    </>
  ),
  eu13: (
    <>
      <path fill="#92d4ff" d="m31 2 7 16 18 5-16 9-8 28-9-27L6 23l19-5z" />
      <path fill="#203854" d="m32 16 3 9 9-1-10 7-2 16-4-17-9-6 10 1z" />
      <circle cx="45" cy="45" r="5" fill="#ffd473" />
    </>
  ),
  eu14: (
    <>
      <path
        fill="#d3fa83"
        d="m5 45 3-21 14-14-4 17-7 14 11-8-5 15zm16 11 7-24-5 1 14-25 9-5-8 24 9-3-17 31z"
      />
      <path fill="#7bc1b5" d="m36 55 15-24 8-3-3 17-12 9z" />
    </>
  ),
  north: (
    <>
      <path
        fill="#9cd8ff"
        d="M3 38 18 13l13 19 9-15 21 26-16-6-5-8-5 10-11 2-7-12-5 10z"
      />
      <path fill="#ff7e70" d="m5 45 18 1 9 7 9-8 17 2-25 14z" />
      <path fill="#fff4be" d="m48 4 2 5 6 1-5 4 1 5-5-3-5 3 1-6-4-3 6-1z" />
    </>
  ),
  south: (
    <>
      <path
        fill="#f49551"
        d="M7 41v-9l7 3-4-13 9 6-1-17 11 16 6-22 5 21 12-11-4 18 10-5-6 16z"
      />
      <path fill="#ffd977" d="m13 46 14-10 13 9 13-5-6 10-13 7-14-5z" />
      <path fill="#63cdaa" d="M12 54q19 13 39-1l-6 7-13 4-15-4z" />
    </>
  ),
  asia: (
    <>
      <path
        fill="#d99aff"
        d="M11 12 36 5l17 9-12 6-9-5-12 4 4 5 20-3 11 9-7 10-21 4 8 8 12-2-14 12L9 45l8-9 24-3 4-5-23 4-14-9z"
      />
      <circle cx="37" cy="12" r="2" fill="#32233c" />
      <path fill="#ffce6b" d="m5 5 12 4-4 5z" />
    </>
  ),
  oceania: (
    <>
      <path
        fill="#59d5c6"
        d="M2 36Q20 14 32 23q7 5 3 13 14-4 23-17 1 22-14 29-19 8-30-2z"
      />
      <path
        fill="#ffe2a9"
        d="m7 34 16-31 5 18q-10 1-21 13zm12 19q17 7 34-4l-5 9-19 4z"
      />
    </>
  ),
  "eu-finals": (
    <>
      <path fill="#9dd2f2" d="M6 11h12v32l-7 9-5-7zm40 0h12v34l-5 7-7-9z" />
      <path
        fill="#ffd990"
        d="M21 7h22l-4 31-7 8-7-8zm7 40h8v6l10 4v4H18v-4l10-4z"
      />
      <path fill="#293b53" d="m28 13 4 16 4-16z" />
    </>
  ),
  "north-finals": (
    <>
      <path
        fill="#fa936e"
        d="m32 3 25 15-6 5-19-11-19 12-6-6zM8 30l8-5v14l9 7v11L8 46zm48 0v16L39 57V46l9-7V25z"
      />
      <path fill="#fff3b3" d="m32 17 9 11-9 27-9-27z" />
    </>
  ),
  "south-finals": (
    <>
      <path
        fill="#ffc356"
        d="M4 36 15 9l12 10 11-9 15 3 7 17-11-4-5-6-5 5 9 7-4 9-18 1-7 10-11-7 16-20-8-5z"
      />
      <path fill="#74dbac" d="m25 48 18-4 13-9-6 15-23 12-8-6z" />
      <path fill="#222a37" d="m35 23 8-2-5 6z" />
    </>
  ),
  "asia-finals": (
    <>
      <ellipse
        cx="32"
        cy="34"
        rx="22"
        ry="20"
        fill="none"
        stroke="#b899fb"
        strokeWidth="6"
      />
      <path
        fill="#ffe1a1"
        d="m8 23 21-13 9-8-3 17 19 6-25 1-6 13 1-14zm12 21 18-8 20 1-13 7-6 12-6-10z"
      />
    </>
  ),
  epl25: (
    <>
      <path fill="#92f1dd" d="M6 13h48l-5 9H20v6h25l-5 9H16v6h18l-7 10H5z" />
      <path fill="#ffce7b" d="m35 50 19-24 5 16-11 16-13 2z" />
    </>
  ),
  epl26: (
    <>
      <path
        fill="#e4a8fb"
        d="m4 21 26-15 13 7-25 15 8 5-9 6-13-8zm23 17 27-16 6 4v12L33 55l-13-8z"
      />
      <path fill="#c6f3ff" d="m36 5 21 11-9 6-20-12zm-31 37 18 11-10 6-8-5z" />
    </>
  ),
  iem: (
    <>
      <path
        fill="#9deaff"
        d="M5 52 21 11l10-5-4 13-7 7-9 27zm17-8 8-21 9 2 5 12-6-3-6 12z"
      />
      <path fill="#d7c0fc" d="m38 11 8 4 15 37-10 1-8-20z" />
      <path fill="#ffc973" d="m14 56 18-5 22 6-22 5z" />
    </>
  ),
  "global-cq": (
    <>
      <ellipse
        cx="30"
        cy="32"
        rx="20"
        ry="24"
        fill="none"
        stroke="#70bfe4"
        strokeWidth="5"
        transform="rotate(30 30 32)"
      />
      <path
        fill="#edc6ff"
        d="m6 48 18-17-8-5 30-5-10 21-6-7zM47 9l3-7 3 7 7 2-7 3-3 6-3-6-6-3z"
      />
    </>
  ),
  "am-cq": (
    <>
      <path
        fill="#f0b76c"
        d="M6 50V23l17-13v12l-8 6v16zm18-5V19L40 6v14l-7 5v15zm17-11V22l17-9v14z"
      />
      <path fill="#e686a1" d="m5 57 51-28-8 17-29 14z" />
    </>
  ),
  rivals: (
    <>
      <path
        fill="#ff9173"
        d="M4 13 18 7l15 17-6 10-12-13-6 15zM6 40l8-11 12 12-5 9-10 4z"
      />
      <path
        fill="#8bdbe5"
        d="m60 51-14 6-15-17 6-10 12 13 6-15zm-2-27-8 11-12-12 5-9 10-4z"
      />
    </>
  ),
  "open-usa": (
    <>
      <path
        fill="#ffcb7d"
        d="m3 39 9-24 13-7 8 12-7 10-4-8-6 20zm26-5 13-20 18 6-6 9-8-3-8 15z"
      />
      <path fill="#99d9ec" d="m2 49 21-13 13 10 22-12-5 16-19 9-14-11-15 9z" />
    </>
  ),
  krakow: (
    <>
      <path
        fill="#de9aee"
        d="M7 50V28l7-8 6 8v15l7-6V18l7-14 7 14v24l8 7V26l6-8 6 8v30l-13-3-15-7-16 11z"
      />
      <path fill="#ffc990" d="m4 58 18-3 11-5 14 6 13 3-4 4H8z" />
    </>
  ),
  "bo-eu": (
    <>
      <path
        fill="#96dfe9"
        d="M7 46V21l18-12 16 1-2 8-11 2-10 8v15zm15 7V34l16-11 16-1-3 11-10 2-9 6v12z"
      />
      <path fill="#ffc68b" d="M37 57V42l9-5 10-1-3 8-7 4v9z" />
    </>
  ),
  "bc-eu": (
    <>
      <path
        fill="#bf9de8"
        d="M7 14h17v8h-7v21h9v9H7zm50 0H40v8h7v21h-9v9h19z"
      />
      <path fill="#ffe59e" d="m31 5 6 10-6 9-5-9zm-5 24 10-3 3 12-8 20-7-19z" />
    </>
  ),
  "bo-na": (
    <>
      <path
        fill="#fa977a"
        d="M3 42q5-22 27-32l-8 15 14-5-19 20zM9 51l27-23 17-6-9 16-19 11 9-1-10 10z"
      />
      <circle cx="50" cy="12" r="6" fill="#ffe89c" />
    </>
  ),
  "bc-na": (
    <>
      <path
        fill="#8fd1ee"
        d="m32 3 24 8v21l-8 10-5-9 4-5V17l-15-5-15 6v12l5 7-6 9L7 33V12z"
      />
      <path fill="#f39c93" d="m32 19 8 14-4 12 9-4-13 21-14-21 10 4-5-12z" />
    </>
  ),
  "bo-sa": (
    <>
      <path fill="#ffc978" d="m4 34 18-19 20-7 16 3-10 7-13 1 4 5-22 8-7 12z" />
      <path fill="#79d9a7" d="m18 40 29-14 12-1-9 10-16 7 3 3-14 11-9 2z" />
      <circle cx="37" cy="15" r="2" fill="#52473d" />
    </>
  ),
  "bc-sa": (
    <>
      <path
        fill="#d6e0a7"
        d="M4 22 14 8l14 8 5 12-11-4-6-5-3 7 9 9-7 4zm54 0L48 8l-12 8-3 12 10-4 5-5 3 7-8 9 6 4z"
      />
      <path fill="#ed836b" d="m18 39 12-9 15 10-9 15-5 7-8-10z" />
    </>
  ),
  "bo-as": (
    <>
      <path
        fill="#e99acc"
        d="m3 41 31-30 23-4-8 13-12 4-16 17zm10 9 34-22 12-2-7 10-13 6-17 13z"
      />
      <path fill="#ffe39e" d="m30 54 15-10 12-1-5 9-19 8z" />
    </>
  ),
  "bc-as": (
    <>
      <path
        fill="#8dd4d4"
        d="m8 25 5-15 19-6 19 7 5 14-13-6-11-6-13 6zM6 30l17-7 9 7-9 5-8-2-6 10zm52 0-17-7-9 7 9 5 8-2 6 10z"
      />
      <path fill="#f8bc88" d="m16 43 14-9 3 7 3-7 12 10-15 18z" />
    </>
  ),
  "lcq-eu": (
    <>
      <path
        d="M5 50 14 26 29 9l10-4-1 12-12 12-5 12 11-6-6 14-16 9z"
        fill="#dce08b"
      />
      <path d="m32 42 17-21 10-5-2 18-13 16-15 8z" fill="#91b9f4" />
    </>
  ),
  "lcq-am": (
    <>
      <path
        d="m2 27 17-8 9-14 5 19-18 15 6-12zm31 2 9-12 19-3-10 17-11 4 9-11z"
        fill="#ffa978"
      />
      <path
        d="m10 47 16-9 7-9-2 14 13-6 12-3-16 13-11 1-8 11z"
        fill="#7fe2c3"
      />
    </>
  ),
  "lcq-as": (
    <>
      <path
        fill="#eeaa8f"
        d="M9 7h46v7H9zm6 11h34l-6 9-8 6 12 12 3 9H14l4-11 11-10-11-10z"
      />
      <path fill="#513547" d="m23 20 10 9 8-9zm2 28h15l-8-9z" />
      <path fill="#ffda85" d="M8 57h48v5H8z" />
    </>
  ),
};

export function eventMark(id: string, org: string) {
  if (id.includes("-lcq-"))
    return id.endsWith("Europe")
      ? "lcq-eu"
      : id.endsWith("Americas")
        ? "lcq-am"
        : "lcq-as";
  if (id.startsWith("fire-major")) return "buenos";
  if (id.startsWith("pw-major")) return "shanghai";
  if (id.startsWith("draculan-")) return "draculan";
  if (id.startsWith("pgl-")) return "major";
  if (id.includes("-oq1")) return "oq1";
  if (id.includes("-oq2")) return "oq2";
  if (id.startsWith("cct-europe-"))
    return id.endsWith("-playin") ? "cct-playin" : "cct-europe";
  if (id.startsWith("cct-")) return "contenders";
  if (id.startsWith("epl-")) return id.endsWith("25") ? "epl25" : "epl26";
  if (id.startsWith("iem-krakow")) return "krakow";
  if (id.startsWith("blast-open-")) {
    if (!id.includes("-cq-") && !id.includes("-oq-")) return "open-usa";
    const region = id.endsWith("europe")
      ? "eu"
      : id.endsWith("asia-pacific")
        ? "as"
        : id.endsWith("north-america")
          ? "na"
          : "sa";
    return (id.includes("-oq-") ? "bo-" : "bc-") + region;
  }
  if (id.startsWith("iem-"))
    return id.endsWith("Global")
      ? "global-cq"
      : id.endsWith("Americas")
        ? "am-cq"
        : "iem";
  if (id.startsWith("blast-")) return "rivals";
  if (id.startsWith("ecl-eu-")) return id.includes("-13") ? "eu13" : "eu14";
  const district = id.toLowerCase();
  if (id.startsWith("ecl-finals-"))
    return district.includes("europe")
      ? "eu-finals"
      : district.includes("north")
        ? "north-finals"
        : district.includes("south")
          ? "south-finals"
          : "asia-finals";
  return district.includes("north")
    ? "north"
    : district.includes("south")
      ? "south"
      : district.includes("oceania")
        ? "oceania"
        : district.includes("asia")
          ? "asia"
          : "org-" + org.toLowerCase();
}

function imprint(identity: string) {
  let value = 2166136261;
  for (const ch of identity)
    value = Math.imul(value ^ ch.charCodeAt(0), 16777619);
  return value >>> 0;
}

// Archive emblems combine a silhouette, a cut-out and a device. Edition IDs keep
// the same composition after loading a save or changing the list order.
function ArchiveEmblem({ identity }: { identity: string }) {
  const code = imprint(identity);
  const silhouettes = [
    "M4 43 10 17 29 6l22 6 10 14-13-3-11 9-12 17-18 9z",
    "M3 17 24 6l31 6-10 17-17 9 24-1-16 17-27 5 9-22z",
    "M7 11 24 21 32 4l11 19 16-9-6 26-21 20-21-23z",
    "m3 50 11-31 15-8-3 24L41 6l11 7-5 23 12-10-4 20-27 13z",
    "M5 37 16 9l18 5 15-7 9 23-12 20-19 10-18-9 16-8z",
    "M4 49 28 5l10 13-7 16 18-13 11 3-22 29-16 8 1-13z",
    "M3 31 23 8l20-2-9 15 24-6-8 20-16 7 9 7-26 10-9-7 16-15z",
    "M6 21 27 6l24 4 8 12-16-5-14 8-5 12 12-3 18-8-7 20-26 14L6 48z",
  ];
  const palette = [
    ["#76d9dc", "#ffc380"],
    ["#f29299", "#ffe3a8"],
    ["#b7a2ef", "#89dcd2"],
    ["#f3c770", "#94c8ef"],
    ["#99d9ae", "#e9b0cc"],
    ["#91bdef", "#f8b987"],
  ];
  const [main, accent] = palette[(code >>> 3) % palette.length];
  const devices = [
    "m-13 7 10-20 7 2-5 9 13-2-7 9z",
    "M-12 9-4-9 1-3 11-12 7 5 0 11z",
    "m-12-7 10 4 10-6-4 11-10 7z",
    "M-13 3-2-9 11-6 3 0 11 4-3 11z",
    "m-12 9 5-16 6-4-2 13 9-10 6-1-5 12z",
    "M-11-5 0-12 10-4 6 5-3 12-9 4z",
  ];
  const angle = (((code >>> 15) % 7) - 3) * 8;
  return (
    <g transform={code & 256 ? "translate(64) scale(-1 1)" : undefined}>
      <path fill={main} d={silhouettes[code % 8]} />
      <g
        transform={`translate(${30 + ((code >>> 10) % 6)} ${27 + ((code >>> 22) % 7)}) rotate(${angle})`}
      >
        <path
          d={devices[(code >>> 7) % devices.length]}
          stroke="#172334"
          strokeWidth="3"
          strokeLinejoin="round"
          fill={accent}
        />
      </g>
    </g>
  );
}

function SeasonInsignia({ year, cycle }: { year: number; cycle: string }) {
  const code = imprint(cycle);
  const trim = [
    "m-2 45 4 12 14 6M48 1l10 3 5 11",
    "m-2 50 11 9 11 3m30-60 10 7 2 9",
    "m0 38 3 17 6 5m41-60 11 5 2 7",
    "m-1 53 7 7 13 2m27-61 14 2 4 8",
  ];
  const color = cycle.endsWith("-spring")
    ? "#b7dda3"
    : cycle.endsWith("-summer")
      ? "#ffc18a"
      : "#a9bfdb";
  // Engraved binary year on the lower rim gives successive seasons a permanent device.
  const yearBits = (year - 2000).toString(2);
  return (
    <>
      <path
        d={trim[(code >>> 2) % 4]}
        stroke={color}
        strokeWidth="3"
        fill="none"
      />
      {yearBits.split("").map((bit, i) => (
        <path
          key={i}
          d={bit === "1" ? `m${20 + i * 4} 66 2-4` : `m${20 + i * 4} 66 1-1`}
          stroke={color}
          strokeWidth="2"
        />
      ))}
    </>
  );
}

export function CompetitionMark({
  mark,
  name,
  year,
  cycle = "",
  size = 44,
}: BadgeProps) {
  const emblem =
    mark === "archive" ? (
      <ArchiveEmblem identity={cycle} />
    ) : (
      art[mark as keyof typeof art]
    );
  if (!emblem) return null;
  return (
    <svg
      className="competition-mark"
      viewBox="-5 -5 74 74"
      role="img"
      aria-label={"Игровая эмблема · " + name}
      style={{ "--mark-size": size + "px" } as CSSProperties}
    >
      {year && year > 2026 && <SeasonInsignia year={year} cycle={cycle} />}
      {emblem}
    </svg>
  );
}
