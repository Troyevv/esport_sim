import { useEffect, useSyncExternalStore } from "react";
import { serverURL } from "./session";

export type GarmentRig = {
  width: number;
  height: number;
  collar: number[];
  span: number;
  seat: number[];
};
type InstalledKit = {
  sha256: string;
  rig: GarmentRig;
  observed: string;
  source: string;
};
let index: Record<string, InstalledKit> = {};
let pending: Promise<void> | undefined;
let loaded = false;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => {
  listeners.add(fn);
  return () => {
    listeners.delete(fn);
  };
};

export function refreshWardrobe() {
  if (!pending)
    pending = fetch(serverURL("/api/portraits/kit-index"), {
      credentials: "include",
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) return;
        index = await response.json();
        loaded = true;
        listeners.forEach((fn) => fn());
      })
      .catch(() => {})
      .finally(() => {
        pending = undefined;
      });
  return pending;
}
export function useGarment(team?: string) {
  const current = useSyncExternalStore(subscribe, () => index);
  useEffect(() => {
    if (team && !loaded) void refreshWardrobe();
  }, [team]);
  return team ? current[team] : undefined;
}
