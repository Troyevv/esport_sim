import { useState, useEffect } from "react";
import { serverURL } from "./session";
import type { Office } from "./StaffOffice";
import type { Visual } from "./SceneIdentity";
export type Decision = {
  id:string; kind:string; level:"required"|"warning"|"info"; title:string; detail:string;
  action:"entry"|"calendar"|"play"|"match"|"retry"|"repair"|"inbox"|"overview"|"training";
  due:string; edition:string|null;
};
export type Act = (kind: string, value?: object, rejected?:(detail:string)=>void) => Promise<boolean>;
export type Summary = {
  id: string;
  character: string;
  club: string;
  mode: string;
  scope: string;
  date: string;
};
export const fixtureMap = (e: Fixture) => e.bestOf ? "Map Veto" : ({de_dust2: "Dust II", depo: "Депо"}[e.mapId || "depo"] || e.mapId!.slice(3,4).toUpperCase() + e.mapId!.slice(4));
type Simulation = { mode: "detailed" | "round"; version: number };
export type Fixture = {
  pcw?: boolean;
  simulation?: Simulation;
  mapId?: string;
  title?:string;
  agenda?: {edition:string;tournament:string;title:string}[];
  edition?:string;
  bestOf?: number;
  kind: "match" | "review";
  id: string;
  date: string;
  teams: string[];
  score?: number[];
  scoreByTeam?: Record<string, number>;
};
// Older completed reports stored their points in the frozen fixture's team order.
export const fixtureScore = (e: Fixture) =>
  (e.scoreByTeam ? e.teams.map((id) => e.scoreByTeam![id]) : e.score)?.join(
    " : ",
  );

export type Player = {
  id: string;
  name: string;
  role: string;
  captain: boolean;
  form: number;
  morale: number;
  fatigue: number;
  born: string | null;
  realName: string | null;
  visual: Visual;
  skills: Record<string, number>;
  ratings: Record<string, number>;
};
export type Career = Summary & {
  office: Office;
  attention: Decision[];
  team: string;
  teams: Record<string, string>;
  start: string;
  source: string;
  edition: number;
  organization: string | null;
  region: string | null;
  visual: Visual;
  queue: Fixture[];
  history: Fixture[];
  regions: string[];
  milestones: { id?:string; edition?:string; sender?:string; date: string; title: string; body?:string; matches: number | null }[];
  progress: { done: number; total: number } | null;
  error: string | null;
  roster: Player[];
  teamRating: number;
  competitions?: boolean;
  watchFixture?:string|null;
  slots: (Summary & { slot: string })[];
};
type Team = {
  id: string;
  name: string;
  region: string | null;
  tier: number | null;
};
export type Options = { circuit?:boolean; date: string; teams: Team[] };
export type Catalog = { id: string; title: string; revision: number }[];
export type RoundSummary = { round: number; winnerTeamId: string | null; side: string; score: number[]; buys?: string[] };
export type Report = {
  simulation?: Simulation;
  maps?: { mapId: string; scoreByTeam: Record<string, number>; rounds: RoundSummary[] }[];
  stats: {
    player: string;
    name: string;
    club: number;
    teamId: string | null;
    k: number;
    d: number;
    a: number;
    damage: number;
    kast: number;
    opening: number;
    openingDeaths?: number;
  }[];
  rounds: RoundSummary[];
};
export const scopes: Record<string, string> = {
  fast: "Быстрый",
  standard: "Стандартный",
  full: "Полный",
};
export const position = (mode: string) =>
  mode === "owner" ? "Владелец организации" : "Главный тренер";
export const date = (value: string) =>
  new Date(value + "T12:00:00Z").toLocaleDateString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
export const slotName = (value: string) =>
  (value.startsWith("auto") ? "Автосохранение" : "Слот " + value[0]) +
  (value.endsWith(".bak") ? " · резерв" : "");

export function useData<T>(path: string | null, revision = 0) {
  const [answer, setAnswer] = useState<{
    path: string;
    revision: number;
    data: T;
  } | null>(null);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    if (path)
      fetch(serverURL(path), {
        credentials: "include",
        cache: "no-store",
        signal: controller.signal,
      })
        .then(async (res) => {
          const data = await res.json();
          if (!res.ok)
            throw new Error(data.detail || "Не удалось прочитать данные");
          if (!controller.signal.aborted) setAnswer({ path, data, revision });
        })
        .catch((e) => {
          if (!controller.signal.aborted) setError(e.message);
        });
    return () => controller.abort();
  }, [path, revision, retry]);
  return {
    revision: answer?.revision,
    data: answer?.path === path ? answer?.data : undefined,
    error,
    reload: () => setRetry((v) => v + 1),
  };
}

export type Group = "players" | "teams" | "organizations" | "staff";
export type Profile = { group: Group; id: string };
export type Person = {
  id: string;
  name: string;
  visual: Visual;
  role: string | null;
  teams: string[];
  realName: string | null;
  born: string | null;
  contract: string | null;
  statistics: {
    event: string;
    kills: number;
    deaths: number;
    assists: number;
    adr: number;
    maps: number;
  } | null;
};
export type Scene = {
  players: Record<string, Person>;
  teams: Record<
    string,
    {
      id: string;
      name: string;
      visual: Visual;
      organization: string | null;
      region: string | null;
      teamType: string;
      tier: number | null;
      members: string[];
      rosterDate?: string;
    }
  >;
  organizations: Record<
    string,
    { id: string; name: string; visual: Visual; founded: string | null }
  >;
  staff: Record<
    string,
    {
      id: string;
      name: string;
      visual: Visual;
      team: string | null;
      role: string;
      realName: string | null;
      professional: Pick<Office["people"][string], "attributes" | "ratings" | "philosophy">;
    }
  >;
};
export const groupTitle: Record<Group, string> = {
  players: "Игроки",
  teams: "Команды",
  organizations: "Организации",
  staff: "Персонал",
};
export const isoDay = (d: Date) => d.toISOString().slice(0, 10);
export const dayAt = (iso: string, offset = 0) =>
  new Date(Date.parse(iso + "T12:00:00Z") + 86400000 * offset);
export const monday = (iso: string) =>
  isoDay(dayAt(iso, -((dayAt(iso).getUTCDay() + 6) % 7)));
export const weekdays = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
export const fixtureName = (c: Career, e: Fixture) =>
  e.kind === "review"
    ? e.title || "Итоги недели"
    : (e.pcw ? "Пракк · " : "") + e.teams.map((t) => c.teams[t]).join(" — ");
export const age = (born: string | null, now: string) =>
  born
    ? Number(now.slice(0, 4)) -
      Number(born.slice(0, 4)) -
      Number(now.slice(5) < born.slice(5))
    : null;
