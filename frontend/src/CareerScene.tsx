import { useState } from "react";
import { Avatar, Flag } from "./SceneIdentity";
import {
  roles,
  regions,
  teamTypes,
  skillGroups,
  skillLabels,
} from "./databaseModel";
import { RoleRatings, Familiarity } from "./SceneProfiles";
import { Heading, Tabs, Glyph, Dialog, Readiness } from "./GameUI";
import {
  age,
  date,
  groupTitle,
  type Career,
  type Group,
  type Profile,
  type Scene,
} from "./careerData";

type Props = { scene: Scene; c: Career; open: (p: Profile) => void };
export function EntityButton({
  scene,
  group,
  id,
  open,
}: {
  scene: Scene;
  group: Group;
  id: string;
  open: Props["open"];
}) {
  const item = scene[group][id];
  return item ? (
    <button className="entity-button" onClick={() => open({ group, id })}>
      <Avatar name={item.name} {...item.visual} />
      <span>{item.name}</span>
      <Glyph name="chevron-right" />
    </button>
  ) : null;
}
export function Squad({
  scene,
  c,
  open,
  filter,
  setFilter,
  query,
  setQuery,
  sort,
  setSort,
}: {
  filter: string;
  setFilter: (s: string) => void;
  query: string;
  setQuery: (s: string) => void;
  sort: string;
  setSort: (s: string) => void;
} & Props) {
  const [context, setContext] = useState<string | null>(null);
  const org = scene.teams[c.team]?.organization;
  const teams = Object.values(scene.teams).filter(
    (t) => t.id === c.team || (org && t.organization === org),
  );
  const chosen = teams.filter(
    (t) =>
      filter === "Все игроки" ||
      (filter === "Академия"
        ? t.teamType === "academy"
        : t.teamType !== "academy"),
  );
  const members = Array.from(new Set(chosen.flatMap((t) => t.members)))
    .map((id) => scene.players[id])
    .filter(Boolean);
  const rows = members.map((p) => {
    const own = c.roster.find((r) => r.id === p.id),
      role = own?.role || p.role || "";
    return {
      p,
      own,
      name: p.name,
      role: roles[role] || "—",
      ovr: own?.ratings[role] ?? null,
      age: age(p.born, c.date),
      captain: own?.captain,
    };
  });
  const key = sort.slice(1) as "name" | "age" | "role" | "ovr";
  const display = rows
    .filter((r) =>
      (r.name + " " + (r.p.realName || "") + " " + r.role)
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
    )
    .sort((a, b) => {
      const x = a[key],
        y = b[key];
      if (x === null) return Number(y !== null);
      if (y === null) return -1;
      return (
        (sort[0] === "-" ? -1 : 1) *
        (typeof x === "number" && typeof y === "number"
          ? x - y
          : String(x).localeCompare(String(y), "ru"))
      );
    });
  const sortBy = (k: string) =>
    setSort((sort === "+" + k || (k !== key && k === "ovr") ? "-" : "+") + k);
  const ages = rows.flatMap((r) => (r.age === null ? [] : [r.age]));
  return (
    <>
      <Heading title="Состав команды" sub={c.organization || c.club} />
      <Tabs
        items={["Основной состав", "Академия", "Все игроки"]}
        value={filter}
        change={setFilter}
      />
      <div className="roster-summary">
        <div>
          <strong>{rows.length}</strong>
          <span>Игроков</span>
        </div>
        <div>
          <strong>
            {ages.length
              ? (ages.reduce((a, b) => a + b, 0) / ages.length).toFixed(1)
              : "—"}
          </strong>
          <span>Средний возраст</span>
        </div>
        <div>
          <strong>{chosen.length}</strong>
          <span>Составов</span>
        </div>
      </div>
      <div className="filter-bar">
        <label className="filter-input">
          <Glyph name="search" />
          <input
            aria-label="Поиск по составу"
            placeholder="Найти игрока или роль"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>
      <section className="surface table-wrap">
        <table className="simple-table">
          <thead>
            <tr>
              {Object.entries({
                name: "Игрок",
                age: "Возраст",
                role: "Роль",
                ovr: "Ролевой OVR",
              }).map(([k, v]) => (
                <th
                  key={k}
                  aria-sort={
                    k !== key
                      ? "none"
                      : sort[0] === "+"
                        ? "ascending"
                        : "descending"
                  }
                >
                  <button className="sort-button" onClick={() => sortBy(k)}>
                    {v} <Glyph name="arrows-sort" />
                  </button>
                </th>
              ))}
              <th>Форма</th>
              <th>Готовность</th>
              <th>Мораль</th>
              <th>Контракт</th>
              <th aria-label="Действия" />
            </tr>
          </thead>
          <tbody>
            {display.map((r) => (
              <tr
                key={r.p.id}
                onClick={(event) => {
                  if (!(event.target as Element).closest("button"))
                    open({ group: "players", id: r.p.id });
                }}
                onContextMenu={(e) => {
                  e.preventDefault();
                  setContext(r.p.id);
                }}
              >
                <td>
                  <button
                    className="player-identity"
                    onClick={() => open({ group: "players", id: r.p.id })}
                  >
                    <Avatar name={r.name} {...r.p.visual} />
                    <span>
                      <strong>{r.name}</strong>
                      <small>{r.p.realName || "Игрок"}</small>
                    </span>
                  </button>
                </td>
                <td>
                  <Flag value={r.p.visual.flag} /> {r.age ?? "—"}
                </td>
                <td>
                  {r.role}
                  {r.captain ? " · C" : ""}
                </td>
                <td>
                  <span className="ovr">{r.ovr ?? "—"}</span>
                </td>
                <td>{r.own?.form ?? "—"}</td>
                <td>
                  <Readiness fatigue={r.own?.fatigue} />
                </td>
                <td>{r.own?.morale ?? "—"}</td>
                <td>
                  {r.p.contract === "free" ? "Свободный агент" : "Нет сведений"}
                </td>
                <td>
                  <button
                    className="icon-button"
                    aria-label={"Действия · " + r.name}
                    onClick={() => setContext(r.p.id)}
                  >
                    <Glyph name="dots" />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!display.length && (
          <p className="empty-state">
            {members.length
              ? "Игроков по запросу нет."
              : "В выбранной редакции нет игроков этого состава."}
          </p>
        )}
      </section>
      {context && (
        <Dialog
          title={scene.players[context].name}
          close={() => setContext(null)}
        >
          <div className="panel-body stack">
            <button
              className="btn"
              onClick={() => open({ group: "players", id: context })}
            >
              Открыть профиль
            </button>
            {scene.players[context].teams.map((id) => (
              <EntityButton key={id} group="teams" {...{ scene, id, open }} />
            ))}
          </div>
        </Dialog>
      )}
    </>
  );
}
export function useDirectoryView() {
  const [group, setGroup] = useState<Group>("teams");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  return { group, setGroup, query, setQuery, page, setPage };
}
export function Directory({
  scene,
  open,
  view,
}: {
  scene: Scene;
  open: Props["open"];
  view: ReturnType<typeof useDirectoryView>;
}) {
  const { group, setGroup, query, setQuery, page, setPage } = view;
  const rows = Object.values(scene[group])
    .filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  return (
    <>
      <Heading
        title="Профессиональная сцена"
        sub="Игроки, клубы и персонал редакции карьеры"
      />
      <Tabs
        items={Object.values(groupTitle)}
        value={groupTitle[group]}
        change={(s) => {
          setGroup(
            (Object.keys(groupTitle) as Group[]).find(
              (k) => groupTitle[k] === s,
            )!,
          );
          setPage(0);
        }}
      />
      <label className="filter-input directory-search">
        <Glyph name="search" />
        <input
          aria-label="Поиск по сцене"
          placeholder="Имя или название"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
        />
      </label>
      <section className="surface">
        <div className="panel-head">
          <h2>{groupTitle[group]}</h2>
          <span className="pill">{rows.length}</span>
        </div>
        {rows.slice(page * 25, page * 25 + 25).map((r) => (
          <EntityButton key={r.id} {...{ scene, open, group }} id={r.id} />
        ))}
        {!rows.length && <p className="empty-state">Ничего не найдено.</p>}
        <div className="panel-head">
          <button
            className="btn"
            disabled={!page}
            onClick={() => setPage(page - 1)}
          >
            Назад
          </button>
          <span>
            {page + 1} / {Math.max(1, Math.ceil(rows.length / 25))}
          </span>
          <button
            className="btn"
            disabled={(page + 1) * 25 >= rows.length}
            onClick={() => setPage(page + 1)}
          >
            Далее
          </button>
        </div>
      </section>
    </>
  );
}
export function EntityProfile({
  scene,
  c,
  open,
  profile,
  back,
}: Props & { profile: Profile; back: () => void }) {
  const [tab, setTab] = useState("Обзор");
  const [chosenRole, setRole] = useState("");
  const { group, id } = profile,
    item = scene[group][id];
  if (!item) return <p role="alert">Запись отсутствует в редакции карьеры.</p>;
  const player = group === "players" ? scene.players[id] : null,
    own = player ? c.roster.find((p) => p.id === id) : null,
    team = group === "teams" ? scene.teams[id] : null,
    org = group === "organizations" ? scene.organizations[id] : null,
    staff = group === "staff" ? scene.staff[id] : null;
  const orgTeams = Object.values(scene.teams).filter(
    (t) => t.organization === org?.id,
  );
  const link = (g: Group, k: string) => (
    <EntityButton key={g + k} group={g} id={k} {...{ scene, open }} />
  );
  const panel = (title: string, content: React.ReactNode) => (
    <section className="surface">
      <div className="panel-head">
        <h2>{title}</h2>
      </div>
      {content}
    </section>
  );
  const staffList = Object.values(scene.staff).filter((s) =>
    team ? s.team === id : orgTeams.some((t) => t.id === s.team),
  );
  const selectedRole = chosenRole || own?.role || "";
  const rating = own?.ratings[selectedRole];
  if (org)
    return (
      <>
        <div className="org-title">
          <Avatar name={org.name} {...org.visual} />
          <Heading title={org.name} sub="Организация · команды и персонал">
            <button className="btn" onClick={back}>
              Назад
            </button>
          </Heading>
        </div>
        <div className="org-grid">
          <div className="stack">
            {panel(
              "Команды организации",
              orgTeams.length ? (
                orgTeams.map((t) => (
                  <button
                    className="entity-button roster-branch"
                    key={t.id}
                    onClick={() => open({ group: "teams", id: t.id })}
                  >
                    <Avatar {...t.visual} name={t.name} />
                    <span>
                      <strong>{t.name}</strong>
                      <small>
                        {teamTypes[t.teamType] || "Команда"} ·{" "}
                        {t.members.length} игроков
                      </small>
                    </span>
                    <Glyph name="chevron-right" />
                  </button>
                ))
              ) : (
                <p className="panel-body muted">Нет связанных команд.</p>
              ),
            )}
            {panel(
              "Персонал",
              staffList.length ? (
                staffList.map((s) => link("staff", s.id))
              ) : (
                <p className="panel-body muted">
                  В редакции нет сведений о штабе.
                </p>
              ),
            )}
          </div>
          {panel(
            "Профиль организации",
            <dl className="club-facts">
              <div>
                <dt>Название</dt>
                <dd>{org.name}</dd>
              </div>
              <div>
                <dt>Основание</dt>
                <dd>{org.founded || "Нет сведений"}</dd>
              </div>
              <div>
                <dt>Команд</dt>
                <dd>{orgTeams.length}</dd>
              </div>
              {orgTeams.some((t) => t.id === c.team) && (
                <div>
                  <dt>Менеджер</dt>
                  <dd>{c.character}</dd>
                </div>
              )}
            </dl>,
          )}
        </div>
      </>
    );

  return (
    <>
      <Heading
        title={
          player
            ? "Профиль игрока"
            : team
              ? "Профиль команды"
              : org
                ? "Организация"
                : "Профиль сотрудника"
        }
        sub={c.club}
      >
        <button className="btn" onClick={back}>
          <Glyph name="arrow-left" />
          Назад
        </button>
      </Heading>
      <section className="surface profile-hero pf-heading">
        <div className="profile-photo">
          <Avatar {...(own?.visual || item.visual)} name={item.name} />
        </div>
        <div className="profile-info">
          <span className="eyebrow">
            {player
              ? roles[own?.role || player.role || ""] || "Игрок"
              : team
                ? teamTypes[team.teamType]
                : staff?.role || "Организация"}
          </span>
          <h2>{item.name}</h2>
          <div className="fullname">{player?.realName || staff?.realName}</div>
          {item.visual.head?.includes("/generated/") && <small>Синтетический игровой портрет</small>}
          <div className="profile-meta">
            <Flag value={item.visual.flag} />
            {player?.born && (
              <span>
                {date(player.born)} · {age(player.born, c.date)} лет
              </span>
            )}
            {team && (
              <span>{regions[team.region || ""] || "Регион неизвестен"}</span>
            )}
          </div>
        </div>
        {player && (
          <div className="profile-rating">
            <div className="profile-rating-top">
              <span className="ovr large">{rating ?? "—"}</span>
              <span>Ролевой OVR</span>
            </div>
            {own && (
              <select
                aria-label="Роль для оценки OVR"
                value={selectedRole}
                onChange={(e) => setRole(e.target.value)}
              >
                {Object.keys(own.ratings).map((r) => (
                  <option value={r} key={r}>
                    {roles[r]}
                  </option>
                ))}
              </select>
            )}
          </div>
        )}
      </section>
      {player && (
        <Tabs
          items={["Обзор", "Характеристики · 58", "Статистика", "Контракт"]}
          value={tab}
          change={setTab}
        />
      )}
      {tab === "Характеристики · 58" ? (
        <div className="attribute-groups">
          {Object.entries(skillGroups).map(([g, keys]) => (
            <section className="surface" key={g}>
              <div className="panel-head">
                <h2>{g}</h2>
                <span className="pill">{keys.length}</span>
              </div>
              <div className="attribute-rows">
                {keys.map((k) => (
                  <div className="attribute-row" key={k}>
                    <span>{skillLabels[k]}</span>
                    <strong
                      title={
                        own?.skills[k] === undefined
                          ? "Нет доступной оценки"
                          : undefined
                      }
                    >
                      {own?.skills[k] ?? "—"}
                    </strong>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : tab === "Статистика" ? (
        panel(
          "Статистика игрока",
          player?.statistics ? (
            <div className="panel-body">
              <h3>{player.statistics.event}</h3>
              <p>
                K / D / A · {player.statistics.kills} /{" "}
                {player.statistics.deaths} / {player.statistics.assists}
              </p>
              <p>ADR · {player.statistics.adr}</p>
            </div>
          ) : (
            <p className="panel-body muted">
              В редакции нет подтверждённой статистики.
            </p>
          ),
        )
      ) : tab === "Контракт" ? (
        panel(
          "Действующий контракт",
          <p className="panel-body">
            {player?.contract === "free"
              ? "Свободный агент"
              : "Условия контракта неизвестны."}
          </p>,
        )
      ) : (
        <div className="org-grid">
          {player && (
            <>
              {own && (
                <Familiarity
                  title="Ключевые характеристики"
                  names={skillLabels}
                  values={Object.fromEntries(
                    [
                      "aim",
                      "positioning",
                      "rifles",
                      "communication",
                      "concentration",
                      "endurance",
                    ]
                      .filter((k) => own.skills[k] !== undefined)
                      .map((k) => [k, own.skills[k]]),
                  )}
                />
              )}
              {own &&
                panel(
                  "Состояние игрока",
                  <dl className="club-facts">
                    <div>
                      <dt>Готовность</dt>
                      <dd>
                        <Readiness fatigue={own.fatigue} />
                      </dd>
                    </div>
                    <div>
                      <dt>Мораль</dt>
                      <dd>{own.morale} / 100</dd>
                    </div>
                    <div>
                      <dt>Форма</dt>
                      <dd>{own.form} / 100</dd>
                    </div>
                  </dl>,
                )}
              {panel(
                "Команды",
                player.teams.length ? (
                  player.teams.map((t) => link("teams", t))
                ) : (
                  <p className="panel-body">Нет подтверждённой заявки.</p>
                ),
              )}
              {own &&
                panel(
                  "Оценки по ролям",
                  <div className="panel-body">
                    <RoleRatings values={own.ratings} />
                  </div>,
                )}
            </>
          )}
          {team && (
            <>
              {panel(
                "Состав",
                team.members.length ? (
                  team.members.map((p) => link("players", p))
                ) : (
                  <p className="panel-body">Нет заявки.</p>
                ),
              )}
              {team.organization &&
                panel("Организация", link("organizations", team.organization))}
            </>
          )}
          {team &&
            panel(
              "Персонал",
              staffList.length ? (
                staffList.map((s) => link("staff", s.id))
              ) : (
                <p className="panel-body muted">
                  В редакции нет сведений о штабе.
                </p>
              ),
            )}
          {staff &&
            panel(
              "Команда",
              staff.team ? (
                link("teams", staff.team)
              ) : (
                <p className="panel-body">Нет сведений.</p>
              ),
            )}
        </div>
      )}
    </>
  );
}
