import { useCareerViewTab } from "./CareerViewTab";
import { PlayerRole } from "./CareerIdentity";
import {PlayerHero,PlayerOverview,SkillRow,Section} from "./approved/Player";
import {Tabs as ApprovedTabs} from "./approved/Shared";
import "./club.css";
import { lazy, Suspense, useState } from "react";
import { range, type Knowledge } from "./ScoutingCenter";
import { StaffSkills } from "./StaffOffice";
import { Avatar, Flag, LineupPortrait } from "./SceneIdentity";
import {
  roles,
  regions,
  teamTypes,
  skillGroups,
  skillLabels,
} from "./databaseModel";
import { Heading, Tabs, Glyph, Dialog, Readiness } from "./GameUI";
import {
  age,
  date,
  groupTitle,
  useDirectoryView,
  useData,
  type Career,
  type Group,
  type Profile,
  type Scene,
} from "./careerData";

const TeamRecord = lazy(() => import("./TeamRecord"));
const ProfileDevelopment = lazy(() => import("./ProfileDevelopment"));
const PlayerRecord = lazy(() => import("./ProfileHistory").then(m => ({default:m.PlayerRecord})));
const ProfileHistory = lazy(() => import("./ProfileHistory"));

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
      {group === "players" ? <LineupPortrait id={id} name={item.name} visual={item.visual}/> : <Avatar name={item.name} {...item.visual}/>}
      <span className="directory-entity-name"><strong>{item.name}</strong>{group === "staff" && <small>{scene.staff[id]?.realName && scene.staff[id].realName !== item.name ? scene.staff[id].realName : null}</small>}</span>
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
  const [view,setView] = useState("Карточки");
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
      roleKey: role,
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
  const ownAverage = (select: (row: typeof rows[number])=>number|null) => {
    const values = rows.map(select).filter((v): v is number=>v!==null);
    return values.length ? (values.reduce((sum,v)=>sum+v,0)/values.length).toFixed(1) : "—";
  };
  const ages = rows.flatMap((r) => (r.age === null ? [] : [r.age]));
  return (
    <>
      <div className="club-kicker">{c.organization || c.club} / Команда</div><h1 className="club-title">Состав</h1>
      <div className="club-roster-summary">
        {[
          ["Средний OVR", ownAverage(r=>r.ovr),"По доступным оценкам"],
          ["Готовность",ownAverage(r=>r.own ? 100-r.own.fatigue : null),"По данным штаба"],
          ["Средний возраст",ages.length ? (ages.reduce((a,b)=>a+b,0)/ages.length).toFixed(1) : "—","Известные даты рождения"],
          ["Игроки",rows.length,filter]
        ].map(([label,value,note])=><div className="stat" key={label}><span>{label}</span><strong>{value}</strong><small>{note}</small></div>)}
      </div>
      <Tabs items={["Основной состав","Академия","Все игроки"]} value={filter} change={setFilter}/>
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
        <label className="club-filter">Сортировка<select value={sort} onChange={e=>setSort(e.target.value)}>
          {[["+name","По имени"],["-name","По имени · обратно"],["+age","По возрасту"],["-age","По возрасту · обратно"],["+role","По роли"],["-role","По роли · обратно"],["-ovr","По OVR"],["+ovr","По OVR · по возрастанию"]].map(([value,label])=><option key={value} value={value}>{label}</option>)}
        </select></label>
        <div className="club-segment" aria-label="Представление состава">{["Карточки","Таблица"].map(v=>
          <button key={v} aria-pressed={v===view} className={v===view?"active":""} onClick={()=>setView(v)}>{v}</button>)}</div>
      </div>
      {view === "Карточки" && display.length > 0 ? <div className="club-roster-grid">{display.map(r=><article className="club-player-card" key={r.p.id}>
        <button className="club-player-visual" aria-label={"Профиль · "+r.name} onClick={()=>open({group:"players",id:r.p.id})}>
          <span className="club-card-ovr"><b>{r.ovr ?? "—"}</b><small>OVR</small></span>
          <LineupPortrait id={r.p.id} name={r.name} visual={r.p.visual}/></button>
        <div className="club-player-card-body"><button className="club-player-name" onClick={()=>open({group:"players",id:r.p.id})}>{r.name} <Flag value={r.p.visual.flag}/></button>
          <span><PlayerRole role={r.roleKey}/>{r.captain && r.roleKey !== "igl" && " · Капитан"}</span>
          <div className="club-card-metrics"><span>Форма <b>{r.own?.form ?? "—"}</b></span><span>Настрой <b>{r.own?.morale ?? "—"}</b></span></div>
          <Readiness fatigue={r.own?.fatigue}/>
          <button className="club-text-link" aria-label={"Действия · "+r.name} onClick={()=>setContext(r.p.id)}>Действия</button>
        </div></article>)}</div> : <section className="surface table-wrap">
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
                  <PlayerRole role={r.roleKey}/>
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
      </section>}
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
  canTalk = false,
  navigate,
  revision = 0,
  initialTab = "Обзор",
}: Props & {
  profile: Profile;
  back: () => void;
  canTalk?: boolean;
  navigate?: (p: string) => void;
  revision?: number;
  initialTab?: string;
}) {
  const [tab, setTab] = useCareerViewTab(initialTab);
  const [skillQuery, setSkillQuery] = useState("");
  const [chosenRole, setRole] = useState("");
  const { group, id } = profile,
    item = scene[group][id];
  const scouting = useData<Knowledge>(
    group === "players"
      ? "/api/career/" + c.id + "/scouting/" + encodeURIComponent(id)
      : null,
    revision,
  );
  const assessment = scouting.data;
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
  if (org)
    return (
      <>
        <header className="organization-banner">
          <Avatar name={org.name} {...org.visual} />
          <div><span className="eyebrow">Организация</span><h1>{org.name}</h1>
            <p>{[org.founded ? "Основана "+org.founded : "Дата основания неизвестна", orgTeams.some(t=>t.id===c.team) && "Менеджер · "+c.character].filter(Boolean).join(" · ")}</p></div>
          <button className="btn" onClick={back}><Glyph name="arrow-left"/>Назад</button>
        </header>
        <div className="org-grid organization-directory">
            {panel(
              "Команды организации · "+orgTeams.length,
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
                        {t.visual.flag && <Flag value={t.visual.flag}/>} {teamTypes[t.teamType] || "Команда"} ·{" "}
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
      </>
    );

  const Container = player ? "div" : "section";
  return (
    <Container className={player ? "club" : undefined}>
      {player ? (
        <PlayerHero
          {...{ c, scene, id, assessment, setRole, back, navigate, canTalk }}
          role={selectedRole}
          tab={setTab}
          team={(id) => open({ group: "teams", id })}
        />
      ) : (
        <>
          <button className="club-breadcrumb" onClick={back}>
            <Glyph name="arrow-left" /> Назад
          </button>
          <header
            className={"club-profile-hero" + (staff ? " club-staff-hero" : "")}
          >
            <div className="club-profile-portrait">
              <LineupPortrait
                id={id}
                name={item.name}
                visual={own?.visual || item.visual}
              />
            </div>
            <div className="club-profile-copy">
              <div className="club-kicker">
                {player
                  ? "Профиль игрока"
                  : team
                    ? "Профиль команды"
                    : "Профиль сотрудника"}
              </div>
              <h2>{item.name}</h2>
              <p className="club-fullname">{staff?.realName}</p>
              <div className="club-profile-meta">
                <Flag value={item.visual.flag} />
                <span>{team ? teamTypes[team.teamType] : staff?.role}</span>
                {team && (
                  <span>
                    {regions[team.region || ""] || "Регион неизвестен"}
                  </span>
                )}
              </div>
            </div>
          </header>{" "}
        </>
      )}
      {player && (
        <ApprovedTabs
          items={[
            "Обзор",
            "Характеристики · 58",
            "Развитие",
            "Статистика",
            "История",
            "Достижения",
            "Скаутинг",
            "Контракт",
          ]}
          value={tab}
          onChange={setTab}
        />
      )}
      {player && tab === "Скаутинг" && (
        <section className="surface panel-body">
          <h2>Знания организации</h2>
          {scouting.error ? (
            <p role="alert">{scouting.error}</p>
          ) : assessment ? (
            <>
              <p>
                {assessment.inSquad
                  ? "Текущие навыки известны штабу"
                  : assessment.level}{" "}
                · Изученность {assessment.score}/100 · наблюдений{" "}
                {assessment.count}
              </p>
              <p>
                Оценка потенциала · {range(assessment.potential)}
                {assessment.last &&
                  " · последнее наблюдение " + date(assessment.last)}
              </p>
            </>
          ) : (
            <p>Загрузка оценок…</p>
          )}
        </section>
      )}
      {player && ["Обзор", "История", "Достижения"].includes(tab) && (
        <Suspense fallback={<p role="status">Загружаем профиль…</p>}>
          <PlayerRecord
            {...{ c, id, scene, revision, tab }}
            overview={(maps) => (
              <PlayerOverview
                {...{ c, scene, id, assessment, maps }}
                tab={setTab}
              />
            )}
          />
        </Suspense>
      )}
      {player && tab === "Развитие" && (
        <Suspense fallback={<p role="status">Загружаем развитие…</p>}>
          <ProfileDevelopment {...{ c, id, revision }} />
        </Suspense>
      )}
      {team && (
        <Tabs
          items={[
            "Обзор",
            "Статистика",
            "VRS",
            "Календарь и результаты",
            "История составов",
            "Достижения",
          ]}
          value={tab}
          change={setTab}
        />
      )}
      {team && !["Обзор", "Статистика"].includes(tab) && (
        <Suspense fallback={<p role="status">Загружаем историю…</p>}>
          <TeamRecord {...{ c, id, scene, revision, tab }} />
        </Suspense>
      )}
      {tab === "Статистика" && (group === "teams" || group === "players") && (
        <Suspense fallback={<p role="status">Загружаем статистику…</p>}>
          <ProfileHistory
            key={group + id}
            c={c}
            scene={scene}
            group={group}
            id={id}
            revision={revision}
          />
        </Suspense>
      )}
      {tab === "Характеристики · 58" ? (
        <>
          <div className="club-toolbar">
            <div>
              <h2>Полный набор характеристик</h2>
              <p className="club-muted">
                58 навыков · шкала 0–100{!own && " · диапазоны наблюдения"}
              </p>
            </div>
            <label className="club-search">
              <Glyph name="search" />
              <input
                aria-label="Найти характеристику"
                placeholder="Найти характеристику"
                type="search"
                value={skillQuery}
                onChange={(e) => setSkillQuery(e.target.value)}
              />
            </label>
          </div>
          <div className="club-skill-grid">
            {Object.entries(skillGroups).map(([group, all]) => {
              const keys = all.filter((k) =>
                skillLabels[k]
                  .toLowerCase()
                  .includes(skillQuery.trim().toLowerCase()),
              );
              return (
                keys.length > 0 && (
                  <Section key={group} title={group + " · " + keys.length}>
                    {keys.map((k) => (
                      <SkillRow
                        key={k}
                        label={skillLabels[k]}
                        value={own?.skills[k] ?? assessment?.skills[k]}
                      />
                    ))}
                  </Section>
                )
              );
            })}
          </div>
          {!Object.values(skillLabels).some((name) =>
            name.toLowerCase().includes(skillQuery.trim().toLowerCase()),
          ) && <p>Характеристик с таким названием нет.</p>}
        </>
      ) : [
          "История",
          "Достижения",
          "Развитие",
          "Скаутинг",
          "VRS",
          "Календарь и результаты",
          "История составов",
        ].includes(tab) ? null : tab === "Статистика" && team ? null : tab ===
        "Статистика" ? (
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
      ) : player ? null : (
        <div className="org-grid">
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
      {staff && (
        <div className="staff-office">
          {staff.visual.head?.includes("/generated/") && (
            <small>Синтетический портрет · OpenAI ImageGen</small>
          )}
          {c.office.people[id] && (
            <section className="surface panel-body">
              <h2>Обязанности и нагрузка</h2>
              <p>
                {Object.entries(c.office.owners)
                  .filter(([, person]) => person === id)
                  .map(([d]) => c.office.duties[d]?.title || d)
                  .join(" · ") || "Постоянные обязанности не назначены"}
              </p>
              <p>
                Нагрузка на {date(c.date)} ·{" "}
                {c.office.jobs
                  .filter((j) => j.person === id && j.date === c.date)
                  .reduce((n, j) => n + j.cost, 0)}{" "}
                / {c.office.people[id].capacity}
              </p>
              {c.office.jobs
                .filter((j) => j.person === id)
                .map((j, i) => (
                  <div className="staff-line" key={i}>
                    <time>{date(j.date)}</time>
                    <strong>{c.office.duties[j.duty]?.title || j.duty}</strong>
                    <span>Срок · {date(j.due)}</span>
                  </div>
                ))}
            </section>
          )}
          {staff.professional ? (
            <StaffSkills
              p={staff.professional}
              roles={c.office.roles}
              groups={c.office.groups}
            />
          ) : (
            <p className="surface panel-body muted">
              Оценки компетенций доступны для собственного штаба.
            </p>
          )}
        </div>
      )}
    </Container>
  );
}
