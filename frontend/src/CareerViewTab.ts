import { createContext, useContext, useState } from "react";

export const CareerViewTab = createContext<{
  tab?: string;
  select: (tab: string) => void;
} | null>(null);

// Career navigation stores the selected tab in the same history entry as the profile or fixture.
export function useCareerViewTab(initial: string): [string, (tab: string) => void] {
  const route = useContext(CareerViewTab);
  const [local, selectLocal] = useState(initial);
  return route ? [route.tab ?? initial, route.select] : [local, selectLocal];
}
