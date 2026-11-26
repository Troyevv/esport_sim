import { useState, useEffect } from "react";
import { serverURL } from "./session";
import type { Visual } from "./SceneIdentity";
export type Act = (kind: string, value?: object) => Promise<boolean>;
export type Summary = {
  id: string;
  character: string;
  club: string;
  mode: string;
  scope: string;
  date: string;
};
export const fixtureMap = (e: Fixture) => ({de_dust2: "Dust II", depo: "Депо"}[e.mapId || "depo"] || e.mapId!.slice(3,4).toUpperCase() + e.mapId!.slice(4));
export type Fixture = {
  mapId?: string;
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
  milestones: { date: string; title: string; matches: number | null }[];
  progress: { done: number; total: number } | null;
  error: string | null;
  roster: Player[];
  teamRating: number;
  slots: (Summary & { slot: string })[];
};
type Team = {
  id: string;
  name: string;
  region: string | null;
  tier: number | null;
};
export type Options = { date: string; teams: Team[] };
export type Catalog = { id: string; title: string; revision: number }[];
export type Report = {
  stats: {
    player: string;
    name: string;
    club: number;
    teamId?: string;
    k: number;
    d: number;
    a: number;
    damage: number;
  }[];
  rounds: unknown[];
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
    ? "Итоги недели"
    : e.teams.map((t) => c.teams[t]).join(" — ");
export const age = (born: string | null, now: string) =>
  born
    ? Number(now.slice(0, 4)) -
      Number(born.slice(0, 4)) -
      Number(now.slice(5) < born.slice(5))
    : null;
