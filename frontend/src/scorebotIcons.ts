// Panorama identifiers shared by the DOM scoreboard and Pixi's map.
const items: Record<string, string> = {
  "AK-47": "ak47",
  "M4A1-S": "m4a1_silencer",
  AWP: "awp",
  "Desert Eagle": "deagle",
  Glock: "glock",
  USP: "usp_silencer",
  MP9: "mp9",
  "MAC-10": "mac10",
  Nova: "nova",
  Negev: "negev",
  HE: "hegrenade",
  Свет: "flashbang",
  Дым: "smokegrenade",
  Ложная: "decoy",
  Огонь: "molotov",
  Броня: "kevlar",
  Шлем: "helmet",
  Набор: "defuser",
  C4: "c4",
  "В голову": "icon_headshot",
  Помощь: "stat_assists",
  Размен: "trade",
  Самоустранение: "icon_suicide",
  Время: "clock",
  Устранение: "elimination",
};

export function iconURL(name: string, side?: string) {
  const file = name === "Огонь" && side === "CT" ? "incgrenade" : items[name];
  return file ? "/scorebot/" + file + ".svg" : undefined;
}

const labels: Record<string, string> = {
  Glock: "Glock-18",
  USP: "USP-S",
  Набор: "Набор для разминирования",
  HE: "Осколочная граната",
  Свет: "Световая граната",
  Дым: "Дымовая граната",
  Ложная: "Ложная граната",
};
export function itemLabel(name: string, side?: string) {
  if (name === "Огонь")
    return side === "CT" ? "Зажигательная граната" : "Коктейль Молотова";
  return labels[name] || name;
}
