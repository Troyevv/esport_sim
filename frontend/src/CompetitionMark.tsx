import type {CSSProperties} from "react";

type BadgeProps = {mark:string;name:string;year?:number;cycle?:string;size?:number};
const art = {
  // Organizers. These independent game identities also work without lettering.
  "org-pgl": <><path fill="#ff735c" d="M5 17 31 4l27 13-19 9-8-4-10 5-7-4 17-9-1-1-25 13z"/><path fill="#f6d29b" d="m6 30 10-5 12 7-9 5v12L6 42zm17 10 12-7 20-10v10l-20 11v13l-12 7z"/></>,
  "org-esl": <><path fill="#63e1bb" d="M3 48 22 12h12L16 48zM22 48 40 12h12L34 48z"/><path fill="#efffe9" d="m38 49 11-21 11 6-7 15zM5 53h48l-4 6H2z"/></>,
  "org-cct": <><path fill="#b19aff" d="M32 2 54 14l-6 9-16-10-16 10-6-9zM6 23l10 5v15l11 6v12L6 49zm52 0v26L37 61V49l11-6V28z"/><path fill="#ffce75" d="m32 19 11 7-4 14-7 4-7-4-4-14z"/></>,
  "org-blast": <><path fill="#f778af" d="m7 14 13 7 12-17 7 18 19-6-10 17 12 8-20 2-4 17-10-16-21 2 12-15z"/><path fill="#271735" d="m22 33 13-13-4 11 10-2-15 16 5-13z"/></>,
  // Singapore: a split vessel below a crescent, seen across the harbour.
  "major": <><path fill="#f5d18b" d="M44 3a20 20 0 0 0-18 26c-11-2-17-13-8-22C25 0 38 0 44 3Z"/><path fill="#f5a47b" d="M40 8 57 37H36zm-5 10-2 19H19z"/><path fill="#55dcd2" d="m4 40 25 5 30-6-10 12-22 5L9 49zm5 14 18 5 21-5-7 7-15 3z"/></>,
  "contenders": <><path fill="#fac76d" d="M8 28 5 13l11 7 4-14 11 12 13-13 1 15 13-4-5 16-15 7H23z"/><path fill="#ee7867" d="m11 35 13 5 8 10 10-12 12-6-6 19-17 12-17-12z"/><path fill="#fff0d1" d="m25 26 7-6 7 6-7 7z"/></>,
  "oq1": <><path fill="#77d5ec" d="m5 52 12-33 17-9-7 15-7 2-6 23zM21 53l10-26 11-4-8 23z"/><path fill="#eafff0" d="m36 51 9-23-5-5 16-8 5 8-13 29z"/><path fill="#399aaf" d="m7 56 44-2-10 6H6z"/></>,
  "oq2": <><path fill="#ef93ca" d="M3 19 28 5l-7 15 14-5-8 17-24 9 10-15zm25 17 32-19-7 24-16 7 5-12-15 9z"/><path fill="#ffdb9b" d="m17 45 10-4-3 11 13-2-21 13z"/></>,
  "eu13": <><path fill="#92d4ff" d="m31 2 7 16 18 5-16 9-8 28-9-27L6 23l19-5z"/><path fill="#203854" d="m32 16 3 9 9-1-10 7-2 16-4-17-9-6 10 1z"/><circle cx="45" cy="45" r="5" fill="#ffd473"/></>,
  "eu14": <><path fill="#d3fa83" d="m5 45 3-21 14-14-4 17-7 14 11-8-5 15zm16 11 7-24-5 1 14-25 9-5-8 24 9-3-17 31z"/><path fill="#7bc1b5" d="m36 55 15-24 8-3-3 17-12 9z"/></>,
  "north": <><path fill="#9cd8ff" d="M3 38 18 13l13 19 9-15 21 26-16-6-5-8-5 10-11 2-7-12-5 10z"/><path fill="#ff7e70" d="m5 45 18 1 9 7 9-8 17 2-25 14z"/><path fill="#fff4be" d="m48 4 2 5 6 1-5 4 1 5-5-3-5 3 1-6-4-3 6-1z"/></>,
  "south": <><path fill="#f49551" d="M7 41v-9l7 3-4-13 9 6-1-17 11 16 6-22 5 21 12-11-4 18 10-5-6 16z"/><path fill="#ffd977" d="m13 46 14-10 13 9 13-5-6 10-13 7-14-5z"/><path fill="#63cdaa" d="M12 54q19 13 39-1l-6 7-13 4-15-4z"/></>,
  "asia": <><path fill="#d99aff" d="M11 12 36 5l17 9-12 6-9-5-12 4 4 5 20-3 11 9-7 10-21 4 8 8 12-2-14 12L9 45l8-9 24-3 4-5-23 4-14-9z"/><circle cx="37" cy="12" r="2" fill="#32233c"/><path fill="#ffce6b" d="m5 5 12 4-4 5z"/></>,
  "oceania": <><path fill="#59d5c6" d="M2 36Q20 14 32 23q7 5 3 13 14-4 23-17 1 22-14 29-19 8-30-2z"/><path fill="#ffe2a9" d="m7 34 16-31 5 18q-10 1-21 13zm12 19q17 7 34-4l-5 9-19 4z"/></>,
  "eu-finals": <><path fill="#9dd2f2" d="M6 11h12v32l-7 9-5-7zm40 0h12v34l-5 7-7-9z"/><path fill="#ffd990" d="M21 7h22l-4 31-7 8-7-8zm7 40h8v6l10 4v4H18v-4l10-4z"/><path fill="#293b53" d="m28 13 4 16 4-16z"/></>,
  "north-finals": <><path fill="#fa936e" d="m32 3 25 15-6 5-19-11-19 12-6-6zM8 30l8-5v14l9 7v11L8 46zm48 0v16L39 57V46l9-7V25z"/><path fill="#fff3b3" d="m32 17 9 11-9 27-9-27z"/></>,
  "south-finals": <><path fill="#ffc356" d="M4 36 15 9l12 10 11-9 15 3 7 17-11-4-5-6-5 5 9 7-4 9-18 1-7 10-11-7 16-20-8-5z"/><path fill="#74dbac" d="m25 48 18-4 13-9-6 15-23 12-8-6z"/><path fill="#222a37" d="m35 23 8-2-5 6z"/></>,
  "asia-finals": <><ellipse cx="32" cy="34" rx="22" ry="20" fill="none" stroke="#b899fb" strokeWidth="6"/><path fill="#ffe1a1" d="m8 23 21-13 9-8-3 17 19 6-25 1-6 13 1-14zm12 21 18-8 20 1-13 7-6 12-6-10z"/></>,
  "epl25": <><path fill="#92f1dd" d="M6 13h48l-5 9H20v6h25l-5 9H16v6h18l-7 10H5z"/><path fill="#ffce7b" d="m35 50 19-24 5 16-11 16-13 2z"/></>,
  "epl26": <><path fill="#e4a8fb" d="m4 21 26-15 13 7-25 15 8 5-9 6-13-8zm23 17 27-16 6 4v12L33 55l-13-8z"/><path fill="#c6f3ff" d="m36 5 21 11-9 6-20-12zm-31 37 18 11-10 6-8-5z"/></>,
  "iem": <><path fill="#9deaff" d="M5 52 21 11l10-5-4 13-7 7-9 27zm17-8 8-21 9 2 5 12-6-3-6 12z"/><path fill="#d7c0fc" d="m38 11 8 4 15 37-10 1-8-20z"/><path fill="#ffc973" d="m14 56 18-5 22 6-22 5z"/></>,
  "global-cq": <><ellipse cx="30" cy="32" rx="20" ry="24" fill="none" stroke="#70bfe4" strokeWidth="5" transform="rotate(30 30 32)"/><path fill="#edc6ff" d="m6 48 18-17-8-5 30-5-10 21-6-7zM47 9l3-7 3 7 7 2-7 3-3 6-3-6-6-3z"/></>,
  "am-cq": <><path fill="#f0b76c" d="M6 50V23l17-13v12l-8 6v16zm18-5V19L40 6v14l-7 5v15zm17-11V22l17-9v14z"/><path fill="#e686a1" d="m5 57 51-28-8 17-29 14z"/></>,
  "rivals": <><path fill="#ff9173" d="M4 13 18 7l15 17-6 10-12-13-6 15zM6 40l8-11 12 12-5 9-10 4z"/><path fill="#8bdbe5" d="m60 51-14 6-15-17 6-10 12 13 6-15zm-2-27-8 11-12-12 5-9 10-4z"/></>,
  "last-chance": <><path fill="#eeaa8f" d="M9 7h46v7H9zm6 11h34l-6 9-8 6 12 12 3 9H14l4-11 11-10-11-10z"/><path fill="#513547" d="m23 20 10 9 8-9zm2 28h15l-8-9z"/><path fill="#ffda85" d="M8 57h48v5H8z"/></>,
};

export function eventMark(id:string,org:string) {
  if(id.includes("-lcq-"))return "last-chance";
  if(id.startsWith("pgl-"))return "major";
  if(id.includes("-oq1"))return "oq1";
  if(id.includes("-oq2"))return "oq2";
  if(id.startsWith("cct-"))return "contenders";
  if(id.startsWith("epl-"))return id.endsWith("25")?"epl25":"epl26";
  if(id.startsWith("iem-"))return id.endsWith("Global")?"global-cq":id.endsWith("Americas")?"am-cq":"iem";
  if(id.startsWith("blast-"))return "rivals";
  if(id.startsWith("ecl-eu-"))return id.includes("-13")?"eu13":"eu14";
  const district=id.toLowerCase();
  if(id.startsWith("ecl-finals-"))return district.includes("europe")?"eu-finals":district.includes("north")?"north-finals":district.includes("south")?"south-finals":"asia-finals";
  return district.includes("north")?"north":district.includes("south")?"south":district.includes("oceania")?"oceania":district.includes("asia")?"asia":"org-"+org.toLowerCase();
}

export function CompetitionMark({mark,name,year,cycle="",size=44}:BadgeProps) {
  const emblem=art[mark as keyof typeof art];
  if(!emblem)return null;
  const next=!!year && year>2026;
  return <svg className="competition-mark" viewBox="-5 -5 74 74" role="img" aria-label={"Игровая эмблема · "+name}
    style={{"--mark-size":size+"px"} as CSSProperties}>
    {next && (cycle.endsWith("-spring")?<path d="m-3 42 2 16 15 7M49 1l13 5 2 12" fill="none" stroke="#a7ce9b" strokeWidth="3"/>:
      cycle.endsWith("-summer")?<path d="m-4 16 9-12 10-3-7 11zm56 46 7-11 8-5-3 14z" fill="#e9ad81"/>:
      <path d="m-1 51 4 10 11 4m35-65 10 4 5 10" fill="none" stroke="#a5b7c7" strokeWidth="2"/>)}
    {emblem}
  </svg>;
}
