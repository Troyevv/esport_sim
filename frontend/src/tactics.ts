import type { RadarMap } from "./Radar";
import { serverURL } from "./session";

export type Side = "T" | "CT";
export type Point = { x: number; y: number; z?: number };
export const labels = {
  move: "Маршрут",
  hold: "Удержание",
  face: "Направление",
  exit: "Выход",
  throw: "Граната",
  wait: "Ожидание",
  plant: "Установка",
  retreat: "Отход",
};
export type Kind = keyof typeof labels;
export type Tool = Kind | "pan" | "select";
export type Step = Point & { kind: Kind; seconds?: number; utility?: string };
export interface PlanRef {
  id: string;
  revision: number;
  name: string;
  side: Side;
  buy: string;
}
export interface Plan extends PlanRef {
  format: number;
  map: string;
  geometry: number;
  slots: Step[][];
  standard: boolean;
  familiarity?: number;
}
export interface Library {
  maps: RadarMap[];
  roles: string[];
  players: string[];
  buys: string[];
  plans: Plan[];
}
export interface Preview {
  frames: [number, number, number, number, number?][][];
  tickMs: number;
  events: { tick: number; text: string }[];
  effects: (Point & {
    utility: string;
    land: number;
    end: number;
    radius: number;
  })[];
}
export const colors = ["#b2eea4", "#7ed4f6", "#f9bf76", "#c3abff", "#ef9fa6"];
export const symbols: Record<Tool, string> = {
  move: "⌁",
  hold: "◇",
  face: "↗",
  exit: "➜",
  throw: "◉",
  wait: "◷",
  plant: "▣",
  retreat: "↶",
  pan: "✥",
  select: "◎",
};
export const spawn = (map: RadarMap, side: Side, slot: number) =>
  map.spawns.filter((p) => p.team === side)[slot];
export const snap = (p: Point) => ({
  x: Math.floor(p.x / 10) * 10 + 5,
  y: Math.floor(p.y / 10) * 10 + 5,
});
export const same = (a: Point, b: Point) => a.x === b.x && a.y === b.y;
export const walks = (kind: Kind) => kind !== "face" && kind !== "throw";
export const timed = (kind: Tool) =>
  kind === "face" || kind === "wait" || kind === "hold";
export const floor = (map: RadarMap, p: Point) =>
  p.x >= 0 &&
  p.y >= 0 &&
  p.x < map.width &&
  p.y < map.height &&
  !map.walls.some(
    (r) => p.x >= r.x && p.x < r.x + r.w && p.y >= r.y && p.y < r.y + r.h,
  );

export async function readJSON<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(serverURL(path), {
    credentials: "include",
    cache: "no-store",
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "Домашний сервер отклонил запрос",
    );
  }
  return response.json();
}

export function newPlan(map: RadarMap, side: Side, buy: string): Plan {
  return {
    id: crypto.randomUUID(),
    revision: 0,
    format: 1,
    map: map.id,
    geometry: Number(map.version),
    name: "Новая тактика",
    side,
    buy,
    standard: false,
    slots: [[], [], [], [], []],
  };
}

// Same grid centres and stable neighbour order as engine.route. Draw the actual detour.
export function gridRouter(map: RadarMap) {
  const cols = map.width / 10,
    size = (cols * map.height) / 10;
  const index = (p: Point) =>
    Math.floor(p.y / 10) * cols + Math.floor(p.x / 10);
  const point = (i: number) => ({
    x: (i % cols) * 10 + 5,
    y: Math.floor(i / cols) * 10 + 5,
  });
  const open = Array.from({ length: size }, (_, i) => floor(map, point(i)));
  const cache = new Map<number, Point[]>();
  return (a: Point, b: Point) => {
    const start = index(a),
      end = index(b),
      key = start * size + end;
    const known = cache.get(key);
    if (known) return known;
    const queue = [start],
      parent = new Map([[start, -1]]);
    for (let i = 0; i < queue.length && !parent.has(end); i++) {
      for (const n of [
        queue[i] + 1,
        queue[i] + cols,
        queue[i] - 1,
        queue[i] - cols,
      ]) {
        if (open[n] && !parent.has(n)) {
          queue.push(n);
          parent.set(n, queue[i]);
        }
      }
    }
    const route: Point[] = [];
    if (parent.has(end))
      for (let i = end; i !== start; i = parent.get(i)!) route.push(point(i));
    route.reverse();
    if (cache.size > 4096) cache.clear();
    cache.set(key, route);
    return route;
  };
}
