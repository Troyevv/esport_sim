import type { KitDesign, ClubKit } from "./GamePortrait";
import { resolvePortrait, type PhotoAsset, type PhotoRef } from "./portraits";
export const skillLabels: Record<string, string> = {
  aim: "AIM",
  reaction: "Реакция",
  flick: "Flick",
  tracking: "Tracking",
  recoil: "Контроль отдачи",
  first_shot: "Первый выстрел",
  burst_control: "Контроль очередей",
  target_switch: "Перевод между целями",
  movement: "Передвижение",
  counter_strafe: "Контрстрейф",
  peeking: "Пики",
  pistols: "Пистолеты",
  rifles: "Штурмовые винтовки",
  sniper_rifles: "Снайперские винтовки",
  smgs: "ПП",
  shotguns: "Дробовики",
  machine_guns: "Пулемёты",
  flashes: "Флешки",
  smokes: "Дымы",
  he: "HE",
  incendiaries: "Зажигательные",
  decoys: "Ложные",
  positioning: "Позиционирование",
  game_reading: "Чтение игры",
  decisions: "Решения",
  timing: "Тайминги",
  map_control: "Контроль карты",
  entry: "Энтри",
  lurking: "Люркинг",
  clutch: "Клатчи",
  retakes: "Ретейки",
  postplant: "Постплант",
  adaptability: "Адаптивность",
  discipline: "Игровая дисциплина",
  communication: "Коммуникация",
  coordination: "Координация",
  leadership: "Лидерство",
  calling: "Коллы",
  trades: "Размены",
  support: "Поддержка",
  synchronization: "Синхронизация",
  execution: "Исполнение тактик",
  consistency: "Стабильность",
  concentration: "Концентрация",
  stress_resistance: "Стрессоустойчивость",
  composure: "Самообладание",
  confidence: "Уверенность",
  patience: "Терпение",
  aggression: "Агрессивность",
  risk: "Склонность к риску",
  endurance: "Выносливость",
  fatigue_resistance: "Устойчивость к усталости",
  recovery: "Восстановление",
  motivation: "Мотивация",
  professionalism: "Профессионализм",
  learning: "Обучаемость",
  ambition: "Амбициозность",
  loyalty: "Лояльность",
};
export const skillGroups: Record<string, string[]> = {
  Механика: [
    "aim",
    "reaction",
    "flick",
    "tracking",
    "recoil",
    "first_shot",
    "burst_control",
    "target_switch",
    "movement",
    "counter_strafe",
    "peeking",
  ],
  "Оружие и гранаты": [
    "pistols",
    "rifles",
    "sniper_rifles",
    "smgs",
    "shotguns",
    "machine_guns",
    "flashes",
    "smokes",
    "he",
    "incendiaries",
    "decoys",
  ],
  Тактика: [
    "positioning",
    "game_reading",
    "decisions",
    "timing",
    "map_control",
    "entry",
    "lurking",
    "clutch",
    "retakes",
    "postplant",
    "adaptability",
    "discipline",
  ],
  "Командная игра": [
    "communication",
    "coordination",
    "leadership",
    "calling",
    "trades",
    "support",
    "synchronization",
    "execution",
  ],
  "Психология и развитие": [
    "consistency",
    "concentration",
    "stress_resistance",
    "composure",
    "confidence",
    "patience",
    "aggression",
    "risk",
    "motivation",
    "professionalism",
    "ambition",
    "loyalty",
    "learning",
  ],
  Физические: ["endurance", "fatigue_resistance", "recovery"],
};
export const teamTypes: Record<string, string> = {
  main: "Основная",
  academy: "Академическая",
  reserve: "Резервная",
  other: "Другая",
  unknown: "Тип не подтверждён",
};
export const groups = {
  players: "Игроки",
  teams: "Команды",
  rosters: "Составы",
  staff: "Персонал",
  organizations: "Организации",
};
export type Group = keyof typeof groups;
export const roles: Record<string, string> = {
  rifler: "Рифлер",
  entry: "Энтри",
  lurker: "Люркер",
  awper: "Снайпер",
  support: "Поддержка",
  igl: "Капитан",
};
export const regions: Record<string, string> = {
  Europe: "Европа",
  Americas: "Америка",
  Asia: "Азия",
};
export const statuses: Record<string, string> = {
  confirmed: "Подтверждено",
  estimated: "Расчёт",
  modeled: "Модель",
  unknown: "Неизвестно",
};
export const mapNames: Record<string, string> = {
  depo: "Депо",
  ancient: "Ancient",
  anubis: "Anubis",
  cache: "Cache",
  dust2: "Dust II",
  inferno: "Inferno",
  mirage: "Mirage",
  nuke: "Nuke",
  overpass: "Overpass",
  train: "Train",
  vertigo: "Vertigo",
};
export interface Entity {
  appearance?: PhotoAsset | null;
  kit?: KitDesign | null;
  logo?: PhotoRef;
  ageEstimate?: number | null;
  performance?: {
    rating: number;
    maps: number;
    version: string;
    window: string;
    role: string | null;
  };
  sample?: {
    maps: number;
    series: number;
    wins: number;
    rounds: number;
    awpRounds: number;
    utilityRounds: number;
    from: string;
    until: string;
  };
  founded?: number | null;
  website?: string | null;
  preparation?: number;
  realName?: string | null;
  born?: string | null;
  nationality?: string | null;
  photo?: PhotoRef;
  mapKnowledge?: Record<string, number>;
  roleMastery?: Record<string, number>;
  statistics?: {
    event: string;
    date: string;
    opponent: string;
    maps: number;
    kills: number;
    deaths: number;
    assists: number;
    adr: number;
  } | null;
  name: string;
  origin: string;
  fields: Record<string, string>;
  role?: string | null;
  skills?: Record<string, number>;
  potential?: number | null;
  contract?: string | null;
  region?: string | null;
  tier?: number | null;
  organization?: string | null;
  teamType?: string;
  formerOrganization?: string | null;
  affiliationEnded?: string | null;
  team?: string | null;
  players?: string[];
  captain?: string | null;
  date?: string;
}
export type Origin = { date: string; status: string; reference: string };
export type Result = {
  team: string;
  opponent: string;
  event: string | null;
  outcome: string;
  date: string;
  origin: string;
  players: string[];
};
export type Pack = Record<Group, Record<string, Entity>> & {
  id: string;
  revision: number;
  title: string;
  asOf: string;
  origins: Record<string, Origin>;
  history: Record<string, Result>;
};
export type Ref = { id: string; revision: number };
export const groupKeys = Object.keys(groups) as Group[];
export const refKey = (r: Ref) => r.id + "/" + r.revision;
export function emptyEntity(g: Group, p: Pack): Entity {
  const base = { name: "", origin: "", fields: {} };
  switch (g) {
    case "players":
      return {
        ...base,
        role: null,
        contract: null,
        potential: null,
        realName: null,
        born: null,
        nationality: null,
        photo: null,
        statistics: null,
        mapKnowledge: { depo: 65 },
        roleMastery: Object.fromEntries(Object.keys(roles).map((k) => [k, 65])),
        skills: Object.fromEntries(
          Object.keys(skillLabels).map((k) => [k, 65]),
        ),
      };
    case "teams":
      return {
        ...base,
        organization: null,
        teamType: "unknown",
        region: null,
        tier: null,
      };
    case "rosters":
      return {
        ...base,
        team: Object.keys(p.teams)[0] || null,
        players: [],
        date: p.asOf,
        captain: null,
      };
    case "staff":
      return {
        ...base,
        team: null,
        role: "Тренер",
        realName: null,
        preparation: 65,
      };
    default:
      return { ...base, founded: null, website: null };
  }
}
export function evidence(
  p: Pack,
  r: Entity,
  field: string,
  value: unknown,
): Origin {
  const key = r.fields[field] ?? r.fields[field.split(".")[0]] ?? r.origin;
  if (value == null)
    return {
      status: "unknown",
      date: p.asOf,
      reference: "В пакете нет подтверждённых сведений",
    };
  return (
    p.origins[key] || {
      status: "modeled",
      date: p.asOf,
      reference: "Правка пользователя",
    }
  );
}

const archiveClubs = new WeakMap<Pack, Record<string, PhotoAsset>>();
export function attachArchiveClubs(
  pack: Pack,
  clubs: Record<string, PhotoAsset>,
) {
  archiveClubs.set(pack, clubs);
}
export function archiveClubsFor(pack: Pack) {
  return archiveClubs.get(pack) || {};
}
function clubBadge(pack: Pack, group: "teams" | "organizations", id: string) {
  return archiveClubs.get(pack)?.[group + "/" + id] || pack[group][id]?.logo;
}
type StudioAsset = PhotoAsset & {lineupPhoto?: {team:string;url:string}};
const studioCache = new WeakMap<Pack, Record<string, StudioAsset>>();
export function attachPortraitCache(
  pack: Pack,
  cache: Record<string, StudioAsset>,
) {
  studioCache.set(pack, cache);
}
export function portraitCacheFor(pack: Pack) {
  return studioCache.get(pack) || {};
}
export function playerAppearance(pack: Pack, id: string) {
  return pack.players[id]?.appearance ?? studioCache.get(pack)?.[id] ?? null;
}
const memberships = new WeakMap<
  Pack,
  Map<string, { id: string | null; date: string }>
>();
function latestTeam(p: Pack, player: string) {
  let index = memberships.get(p);
  if (!index) {
    index = new Map();
    for (const roster of Object.values(p.rosters))
      for (const member of roster.players || []) {
        const previous = index.get(member);
        const date = roster.date || "";
        if (!previous || date > previous.date)
          index.set(member, { id: roster.team || null, date });
        else if (date === previous.date && previous.id !== roster.team)
          index.set(member, { id: null, date });
      }
    memberships.set(p, index);
  }
  return p.players[player].contract === "free" ? null : index.get(player)?.id;
}
export function teamKit(p: Pack, id?: string | null): ClubKit | null {
  if (!id || !p.teams[id]) return null;
  const t = p.teams[id];
  const badge = resolvePortrait(clubBadge(p, "teams", id));
  return {
    id,
    name: t.name,
    design: t.kit,
    badge: badge?.image,
    badgeLicense: badge?.license,
  };
}
export function entityVisual(p: Pack, g: Group, id: string) {
  const r = p[g][id];
  const team = g === "rosters" && r.team ? p.teams[r.team] : r;
  const club = g === "teams" || g === "organizations" || g === "rosters";
  return {
    club,
    player: g === "players" || g === "staff",
    staff: g === "staff",
    lineupPhoto: g === "players" ? portraitCacheFor(p)[id]?.lineupPhoto : undefined,
    head: g === "players" ? playerAppearance(p, id)?.image : g === "staff" ? portraitCacheFor(p)[id]?.image : null,
    kit: g === "players" ? teamKit(p, latestTeam(p, id)) : g === "staff" ? teamKit(p,r.team) : null,
    photo: club
      ? clubBadge(
          p,
          g === "organizations" ? "organizations" : "teams",
          g === "rosters" && r.team ? r.team : id,
        )
      : r.photo,
    flag: club ? team.nationality || team.region : r.nationality,
  };
}
