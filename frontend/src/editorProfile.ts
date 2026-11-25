import {
  evidence,
  entityVisual,
  regions,
  teamTypes,
  roles,
  type Group,
  type Pack,
} from "./databaseModel";
import type { ProfileFact, ProfileLink, ProfileSection } from "./SceneProfiles";

// Only the pre-match editor builds profiles from the full package.
export function editorProfile(p: Pack, g: Group, id: string) {
  const r = p[g][id];
  if (!r) return null;
  const rosters = Object.entries(p.rosters),
    staff = Object.entries(p.staff),
    teams = Object.entries(p.teams);
  const related = rosters.filter(([key, s]) =>
    g === "players"
      ? s.players?.includes(id)
      : g === "rosters"
        ? key === id
        : g === "teams"
          ? s.team === id
          : g === "staff"
            ? s.team === r.team
            : p.teams[s.team!].organization === id,
  );
  const teamIds = new Set(related.map(([, s]) => s.team!));
  if (g === "staff" && r.team) teamIds.add(r.team);
  if (g === "teams") teamIds.add(id);
  if (g === "organizations")
    teams
      .filter(([, t]) => t.organization === id)
      .forEach(([k]) => teamIds.add(k));
  const links = (
    group: Group,
    ids: Iterable<string>,
    detail?: (id: string) => string,
  ): ProfileLink[] =>
    [...new Set(ids)].map((k) => ({
      group,
      id: k,
      name: p[group][k].name,
      visual: entityVisual(p, group, k),
      detail: detail?.(k),
    }));
  const sections: ProfileSection[] = [];
  function list(title: string, items: ProfileLink[], empty: string) {
    sections.push({ title, items, empty });
  }
  const sessionTeams = links(
    "teams",
    teamIds,
    (id) =>
      related
        .filter(([, s]) => s.team === id)
        .map(([, s]) => s.date || "")
        .sort()
        .reverse()[0] || "",
  );
  const teamNames = sessionTeams.map((t) => t.name).join(" / ");
  const results = Object.entries(p.history).filter(([, h]) =>
    g === "players" ? h.players.includes(id) : teamIds.has(h.team),
  );
  const facts: ProfileFact[] = [];
  const fact = (
    name: string,
    value: string | null | undefined,
    status?: string,
  ) =>
    facts.push({
      name,
      value: value || "Нет сведений",
      status: value ? status : undefined,
    });
  const field = (lbl: string, k: keyof typeof r, v?: string | null) =>
    fact(lbl, v, evidence(p, r, k, r[k]).status);
  let context = teamNames || "Команда неизвестна";
  if (g === "players") {
    if (r.contract === "free") context = "Свободный агент";
    else if (sessionTeams.length)
      context = sessionTeams.map((t) => t.name + " · " + t.detail).join(" / ");
    let age;
    if (r.born) {
      const years =
        Number(p.asOf.slice(0, 4)) -
        Number(r.born.slice(0, 4)) -
        (p.asOf.slice(5) < r.born.slice(5) ? 1 : 0);
      age = String(years);
    }
    field("Настоящее имя", "realName", r.realName);
    field(
      "Возраст на дату среза",
      r.born ? "born" : "ageEstimate",
      age || r.ageEstimate?.toString(),
    );
    field("Национальность", "nationality", r.nationality);
    field("Игровая роль", "role", roles[r.role || ""]);
    field(
      "Контракт",
      "contract",
      r.contract === "free" ? "Свободный агент" : null,
    );
    field("Потенциал", "potential", r.potential?.toString());
    if (r.performance) {
      const v = r.performance;
      field(
        v.version,
        "performance",
        v.rating.toFixed(2) + " · " + v.maps + " карт",
      );
      field(
        "Период рейтинга",
        "performance",
        v.window === "last 12 months" ? "Последние 12 месяцев" : v.window,
      );
      if (v.role) field("Роль в источнике", "performance", v.role);
    }
    if (r.sample) {
      field(
        "Период статистики",
        "sample",
        r.sample.from + " — " + r.sample.until,
      );
      field("Карты / серии", "sample", r.sample.maps + " / " + r.sample.series);
      field(
        "Победы в сериях",
        "sample",
        r.sample.wins + " из " + r.sample.series,
      );
      field(
        "Раунды с AWP при старте",
        "sample",
        r.sample.awpRounds + " из " + r.sample.rounds,
      );
    }
    list(
      "Команды в срезе",
      sessionTeams,
      "В пакете нет заявки с этим игроком.",
    );
    const seen = new Map<string, string>();
    for (const [, h] of results) {
      if (!seen.has(h.team) || seen.get(h.team)! < h.date)
        seen.set(h.team, h.date);
    }
    for (const [, s] of related) {
      if (!seen.has(s.team!) || seen.get(s.team!)! < s.date!)
        seen.set(s.team!, s.date!);
    }
    list(
      "История команд",
      links(
        "teams",
        [...seen].sort((a, b) => b[1].localeCompare(a[1])).map(([t]) => t),
        (k) => "Наблюдение " + seen.get(k),
      ),
      "Датированные наблюдения отсутствуют.",
    );
  } else if (g === "teams") {
    context = regions[r.region || ""] || "Регион неизвестен";
    field(
      "Принадлежность",
      r.nationality ? "nationality" : "region",
      r.nationality || r.region,
    );
    field("Тип команды", "teamType", teamTypes[r.teamType || "unknown"]);
    field("Тир", "tier", r.tier?.toString());
    fact(
      "Результаты в срезе",
      results.length
        ? results.filter(([, h]) => h.outcome === "W").length +
            " В / " +
            results.filter(([, h]) => h.outcome === "L").length +
            " П"
        : null,
    );
    list(
      "Организация",
      links("organizations", r.organization ? [r.organization] : []),
      "Принадлежность организации не установлена.",
    );
    if (r.organization)
      list(
        "Другие команды организации",
        links(
          "teams",
          teams
            .filter(
              ([key, t]) => key !== id && t.organization === r.organization,
            )
            .map(([key]) => key),
          (k) => teamTypes[p.teams[k].teamType || "unknown"],
        ),
        "Других команд в срезе нет.",
      );
    if (r.formerOrganization)
      list(
        "Прежняя организация",
        links("organizations", [r.formerOrganization], () =>
          r.affiliationEnded
            ? "До " + r.affiliationEnded
            : "Дата окончания неизвестна",
        ),
        "",
      );
  } else if (g === "organizations") {
    context = "Клуб · Counter-Strike 2";
    field("Принадлежность", "nationality", r.nationality);
    field("Год основания", "founded", r.founded?.toString());
    field("Сайт", "website", r.website);
    fact("Команды", String(teamIds.size));
    fact("Составы", String(related.length));
    fact(
      "Сотрудники",
      String(staff.filter(([, s]) => teamIds.has(s.team!)).length),
    );
    list(
      "Команды организации",
      links(
        "teams",
        teamIds,
        (k) => teamTypes[p.teams[k].teamType || "unknown"],
      ),
      "У организации пока нет команд.",
    );
    const former = teams
      .filter(([, t]) => t.formerOrganization === id)
      .map(([key]) => key);
    if (former.length)
      list(
        "Прежние команды",
        links(
          "teams",
          former,
          (k) =>
            teamTypes[p.teams[k].teamType || "unknown"] +
            (p.teams[k].affiliationEnded
              ? " · до " + p.teams[k].affiliationEnded
              : " · дата окончания неизвестна"),
        ),
        "",
      );
  } else if (g === "staff") {
    field("Национальность", "nationality", r.nationality);
    field("Настоящее имя", "realName", r.realName);
    field("Подготовка штаба", "preparation", r.preparation?.toString());
    field("Должность", "role", r.role);
    field("Назначение", "team", r.team ? p.teams[r.team].name : null);
    fact("Дата сведений", p.origins[r.fields.team || r.origin].date);
    list("Клуб", sessionTeams, "Назначение неизвестно.");
  } else {
    field("Дата заявки", "date", r.date);
    field("Капитан", "captain", r.captain ? p.players[r.captain].name : null);
    fact("Игроков", String(r.players?.length || 0));
    list("Команда", sessionTeams, "У заявки нет команды.");
  }
  if (g !== "rosters")
    list(
      "Заявки составов",
      related.map(([k, s]) => ({
        group: "rosters",
        id: k,
        name: s.name,
        visual: entityVisual(p, "rosters", k),
        detail: s.date,
      })),
      "Заявок пока нет.",
    );
  const peers = related
    .flatMap(([, s]) => s.players || [])
    .filter((k) => g !== "players" || k !== id);
  list(
    g === "players" ? "Партнёры по составу" : "Игроки составов",
    links("players", peers, (k) => roles[p.players[k].role || ""] || "Игрок"),
    "Другие участники не указаны.",
  );
  if (g !== "staff")
    list(
      "Тренерский штаб",
      links(
        "staff",
        staff.filter(([, s]) => teamIds.has(s.team!)).map(([k]) => k),
        (k) => p.staff[k].role || "",
      ),
      "Назначения штаба отсутствуют.",
    );
  return { facts, sections, context, results };
}
