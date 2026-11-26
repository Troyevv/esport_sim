import { ManagerAttention } from "./ManagerAttention";
import { fixtureMap, type Decision } from "./careerData";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Brand, Dialog, Glyph, Heading } from "./GameUI";
import { Avatar } from "./SceneIdentity";
import { type Frame } from "./session";
import {
  date,
  groupTitle,
  position,
  useData,
  type Act,
  type Career,
  type Group,
  type Profile,
  type Scene,
  type Summary,
} from "./careerData";
import { Load, MatchReport, NewCareer, Saves } from "./CareerForms";
import { StaffOffice } from "./StaffOffice";
import { CareerMenu } from "./CareerMenu";
import { CompetitionCenter } from "./CompetitionCenter";
import { Calendar } from "./CareerCalendar";
import { Dashboard, Inbox, letters } from "./CareerHome";
import {
  Directory,
  EntityProfile,
  Squad,
  useDirectoryView,
} from "./CareerScene";
import "./career.css";

const sections = [
  [
    "Карьера",
    [
      ["Кабинет", "home"],
      ["Входящие", "inbox"],
      ["Календарь", "calendar"],
      ["Соревнования","trophy"],
      ["Рейтинг VRS","users"],
    ],
  ],
  [
    "Моя команда",
    [
      ["Состав", "users"],
      ["Тренерский штаб", "users"],
      ["Скаутский отдел", "search"],
      ["Тактики", "crosshair"],
      ["Организация", "building"],
    ],
  ],
  [
    "На сервере",
    [
      ["Матч-центр", "device-gamepad-2"],
      ["База сцены", "book"],
    ],
  ],
] as const;
type Props = {
  frame: Frame;
  enabled: boolean;
  act: Act;
  screen: "menu" | "hub";
  go: (s: "menu" | "hub" | "lab" | "match") => void;
  database: () => void;
  board: () => void;
  settings: ReactNode;
  status: ReactNode;
  tool?: ReactNode;
  toolName?: string;
  leaveTool: () => void;
};
export default function CareerScreen(props: Props) {
  const { frame, act, screen, go, database, status, settings } = props;
  const res = useData<{ careers: Summary[]; active: Career | null }>(
    "/api/career",
    frame.calendarProgress ? -1 : frame.careerRevision,
  );
  const [create, setCreate] = useState(false);
  const enabled = props.enabled && res.revision === (frame.careerRevision || 0);
  if (res.error || !res.data) return <Load {...res} />;
  const c = res.data.active;
  if (create)
    return (
      <>
        <header className="menu-top">
          <Brand menu={() => setCreate(false)} />
          {status}
          {settings}
        </header>
        <div className="form-workspace">
          <NewCareer
            act={act}
            enabled={enabled}
            back={() => setCreate(false)}
            opened={() => {
              setCreate(false);
              go("hub");
            }}
          />
        </div>
      </>
    );
  if (!c || screen === "menu")
    return (
      <CareerMenu
        current={c}
        careers={res.data.careers}
        create={() => setCreate(true)}
        resume={() => go("hub")}
        enabled={enabled}
        open={async (s) => {
          if (c?.id === s.id || (await act("career-open", { career: s.id })))
            go("hub");
        }}
        database={database}
        lab={async () => {
          if (!c || (await act("career-lab"))) go("lab");
        }}
        settings={
          <div className="menu-settings">
            {status}
            {settings}
          </div>
        }
      />
    );
  return <Manager key={c.id} {...props} c={c} enabled={enabled} pauseEnabled={props.enabled && frame.careerId===c.id} />;
}
type Route = { page: string; profile?: Profile; edition?:string; entry?:Decision["action"]; jump?:number };
function Manager({
  pauseEnabled,
  c,
  frame,
  enabled,
  act,
  go,
  board,
  settings,
  status,
  tool,
  toolName,
  leaveTool,
}: Props & { c: Career; pauseEnabled:boolean }) {
  const progress = frame.calendarProgress;
  const currentDate = progress?.date || c.date;
  const directory = useData<Scene>("/api/career/" + c.id + "/scene");
  const [route, setRoute] = useState<Route>({ page: "Кабинет" }),
    [drawer, setDrawer] = useState(false),
    [search, setSearch] = useState(false),
    [q, setQ] = useState("");
  const [day, setDay] = useState(c.date),
    [filter, setFilter] = useState("Основной состав"),
    [query, setQuery] = useState(""),
    [sort, setSort] = useState("-ovr");
  const [inboxId, setInboxId] = useState<string | null>(null);
  const readKey = "esport-sim/read/" + c.id;
  const [read, setRead] = useState<string[]>(() => {
    try {
      const v = JSON.parse(localStorage.getItem(readKey) || "[]");
      return Array.isArray(v) ? v.filter((s) => typeof s === "string") : [];
    } catch {
      return [];
    }
  });
  const [compact, setCompact] = useState(
      () => localStorage.getItem("esport-sim/compact") === "true",
    ),
    [motion, setMotion] = useState(
      () => localStorage.getItem("esport-sim/motion") !== "false",
    );
  const [decisions, setDecisions] = useState(false);
  const [quickResult, setQuickResult] = useState<string | null>(null);
  const completedQuick = quickResult && c.history.find(e => e.id === quickResult);
  const [decisionError, setDecisionError] = useState("");
  const required = c.attention.filter(row=>row.level==="required");
  const directMatch = required.length===1 && ["play","match"].includes(required[0].action);
  const directoryView = useDirectoryView();
  const historyStack = useRef<Route[]>([]);
  const scene = directory.data,
    box = letters(c),
    unread = box.filter((m) => !read.includes(m.id)).length;
  const next = c.queue.find((e) => e.teams.includes(c.team) || e.id===c.watchFixture),
    ready = !!next && next.date === c.date && c.queue[0]?.id === next.id;
  const closeOverlays = () => {
    setDrawer(false);
    setSearch(false);
  };
  const to = (page: string, profile?: Profile, edition?:string, entry?:Decision["action"]) => {
    closeOverlays();
    if (tool) leaveTool();
    historyStack.current.push(route);
    setRoute({ page, profile, edition, entry, jump: historyStack.current.length });
    window.scrollTo(0, 0);
  };
  const tournament = (id:string) => to("Соревнования",undefined,id);
  const open = (p: Profile) => to("Профиль", p);
  const back = () => {
    setRoute(historyStack.current.pop() || { page: "Кабинет" });
    window.scrollTo(0, 0);
  };
  const calendar = (d: string) => {
    setDay(d);
    to("Календарь");
  };
  const showLetter = (id: string | null) => {
    setInboxId(id);
    if (id && !read.includes(id)) {
      const list = [...read, id];
      setRead(list);
      localStorage.setItem(readKey, JSON.stringify(list));
    }
    if (route.page !== "Входящие" || tool) to("Входящие");
  };
  const repair = async () => {
    setDecisionError("");
    await act("career-repair",{},setDecisionError);
  };
  const resolve = async (row: Decision) => {
    setDecisionError("");
    if (row.action === "repair") return repair();
    if (row.action === "retry") {
      await act("career-retry",{},setDecisionError);
      return;
    }
    setDecisions(false);
    if (row.action === "match" || row.action === "play") {
      if (row.action === "match" || await act("career-play",{},msg=>{setDecisionError(msg);setDecisions(true)})) {
        leaveTool();
        go("match");
      }
    } else if (row.edition) to("Соревнования",undefined,row.edition,row.action);
    else showLetter(null);
  };
  const quick = async () => {
    const fixture = c.queue[0];
    if (fixture && await act("career-quick", {fixture:fixture.id}, msg=>{setDecisionError(msg);setDecisions(true)})) {
      setDecisions(false);
      setQuickResult(fixture.id);
    }
  };
  const advance = async () => {
    if (!enabled || progress) return;
    if (directMatch) await resolve(required[0]);
    else if (required.length) {setDecisionError("");setDecisions(true)}
    else await act("career-advance",{},msg=>{setDecisionError(msg);setDecisions(true)});
  };
  const nav = (page: string) => {
    closeOverlays();
    if (page === "Календарь") {
      calendar(c.date);
      return;
    }
    if (page === "Тактики") {
      board();
      return;
    }
    if (page === "Матч-центр" && (frame.world.match || frame.world.series || ready)) {
      void advance();
      return;
    }
    if (page === "Организация" && scene) {
      const org = scene.teams[c.team]?.organization;
      to(
        page,
        org
          ? { group: "organizations", id: org }
          : { group: "teams", id: c.team },
      );
      return;
    }
    to(page);
  };
  const active = toolName || route.page;
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setDrawer(false);
        setQ("");
        setSearch((s) => !s);
      }
      if (e.key === "Escape") setDrawer(false);
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);
  const [narrow, setNarrow] = useState(
    () => matchMedia("(max-width:800px)").matches,
  );
  useEffect(() => {
    const m = matchMedia("(max-width:800px)");
    const change = () => {
      setNarrow(m.matches);
      setDrawer(false);
    };
    m.addEventListener("change", change);
    return () => m.removeEventListener("change", change);
  }, []);
  const menuButton = useRef<HTMLButtonElement>(null),
    side = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!drawer) return;
    const prev = document.activeElement as HTMLElement;
    side.current?.querySelector("button")?.focus();
    return () => prev?.focus();
  }, [drawer]);
  const navButton = (label: string, icon: string) => (
    <button
      aria-label={label}
      className={"nav-item " + (active === label ? "active" : "")}
      aria-current={active === label ? "page" : undefined}
      key={label}
      onClick={() => nav(label)}
    >
      <Glyph name={icon} />
      <span>{label}</span>
      {label === "Входящие" && unread > 0 && (
        <small className="nav-badge">{unread}</small>
      )}
    </button>
  );
  const matches = scene
    ? (Object.keys(groupTitle) as Group[]).flatMap((g) =>
        Object.values(scene[g])
          .filter((r) =>
            (r.name + " " + ("realName" in r ? r.realName || "" : ""))
              .toLowerCase()
              .includes(q.trim().toLowerCase()),
          )
          .slice(0, 6)
          .map((r) => ({ group: g, id: r.id, name: r.name, visual: r.visual })),
      )
    : [];
  return (
    <div
      className={
        (compact ? "density-compact " : "") + (motion ? "" : "reduced-motion")
      }
    >
      {drawer && (
        <button
          className="responsive-overlay visible"
          aria-label="Закрыть навигацию"
          onClick={() => setDrawer(false)}
        />
      )}
      <aside
        className={"sidebar " + (drawer ? "mobile-open" : "")}
        ref={side}
        inert={narrow && !drawer}
        aria-hidden={narrow && !drawer}
        aria-label="Основная навигация"
      >
        <Brand
          menu={() => {
            leaveTool();
            go("menu");
          }}
        />
        <button className="club-switch" onClick={() => nav("Организация")}>
          <Avatar name={c.club} {...c.visual} />
          <span>
            <strong>{c.club}</strong>
            <small>Сезон {c.date.slice(0, 4)}</small>
          </span>
          <Glyph name="chevron-down" />
        </button>
        <div className="side-scroll">
          {sections.map(([caption, items]) => (
            <div key={caption}>
              <div className="nav-caption">{caption}</div>
              <nav className="nav-list">
                {items.filter(([label])=>c.competitions || !["Соревнования","Рейтинг VRS"].includes(label)).map(([label, icon]) => navButton(label, icon))}
              </nav>
            </div>
          ))}
        </div>
        <div className="sidebar-bottom">
          <div className="row">
            <span className="manager-avatar">{c.character.slice(0, 1)}</span>
            <div className="manager-info">
              {c.character}
              <small>{position(c.mode)}</small>
            </div>
            <button
              className="icon-button"
              aria-label="Настройки"
              onClick={() => nav("Настройки")}
            >
              <Glyph name="settings" />
            </button>
          </div>
          <div className="sidebar-footer">
            {status}
            <button
              className="icon-button"
              aria-label="Сохранения"
              onClick={() => nav("Сохранения")}
            >
              <Glyph name="device-floppy" />
            </button>
          </div>
        </div>
      </aside>
      <div className="workspace" inert={narrow && drawer}>
        <header className="topbar">
          <div className="breadcrumbs">
            <button
              ref={menuButton}
              className="icon-button mobile-menu"
              aria-label="Открыть навигацию"
              aria-expanded={drawer}
              onClick={() => setDrawer(true)}
            >
              <Glyph name="menu" />
            </button>
            <span>{c.club}</span>
            <span>
              <Glyph name="chevron-right" />
            </span>
            <strong>{active}</strong>
          </div>
          <div className="top-actions">
            <button
              className="search-trigger"
              aria-label="Глобальный поиск"
              onClick={() => {
                setQ("");
                setSearch(true);
              }}
            >
              <Glyph name="search" />
              <span>Поиск в мире</span>
              <kbd className="shortcut">Ctrl K</kbd>
            </button>
            <div className="game-date cr-time">
              <time>{date(currentDate)}</time>
              <small>
                {new Date(currentDate + "T12:00:00Z").toLocaleDateString("ru", {
                  weekday: "long",
                  timeZone: "UTC",
                })}
              </small>
            </div>
            <button
              className="btn primary"
              disabled={!enabled || !!progress}
              onClick={advance}
            >
              {directMatch ? "В матч-центр" : required.length ? "Решения · " + required.length : "Продолжить"}
              <Glyph name="player-play" />
            </button>
          </div>
        </header>
        <div className="main-content" id="main-content">
          {progress && (
            <div className="cr-progress" role="status">
              Рассчитано встреч · {progress.done}
              <progress aria-label="Расчёт календаря до следующего решения" />
              <button className="btn" disabled={!pauseEnabled} onClick={()=>act("career-pause",{runId:progress.runId})}>Остановить расчёт</button>
            </div>
          )}
          {!tool && (!progress || required.length > 0) && <button className="attention-summary surface" data-blocked={!!required.length}
            aria-label={"Открыть центр решений · обязательных: " + required.length} aria-describedby="decision-explanation"
            onClick={()=>{setDecisionError("");setDecisions(true)}}>
            <span id="decision-explanation"><strong>{required.length ? required[0].title : "Центр решений"}</strong>
            <small>{required.length ? required[0].detail : "Обязательных решений нет"}</small></span>
            <b>{required.length ? "Требуют внимания · " + required.length : "Открыть"}</b>
          </button>}
          {directMatch && required[0].action === "play" && !progress && <div className="quick-fixture surface">
            <div><strong>{c.queue[0].teams.map(t=>c.teams[t]).join(" — ")}</strong><small>Расчёт по раундам с автоматическим выбором карт</small></div>
            <button className="btn" disabled={!enabled} onClick={quick}>Быстро рассчитать матч</button>
          </div>}
          {completedQuick && <Dialog title="Матч завершён" close={()=>setQuickResult(null)}><MatchReport event={completedQuick} teams={c.teams} close={()=>setQuickResult(null)}/></Dialog>}
          <ManagerAttention quick={quick} items={c.attention} open={decisions} close={()=>setDecisions(false)}
            enabled={enabled && !progress} resolve={resolve} repair={repair} error={decisionError}
            saves={()=>{setDecisions(false);to("Сохранения")}}/>
          <div key={active} className="screen-enter">
            {tool ||
              (active === "Календарь" ? (
                <Calendar key={day} c={c} initial={day} tournament={tournament}/>
              ) : active === "Входящие" ? (
                <Inbox
                  box={box}
                  read={read}
                  selected={box.find((m) => m.id === inboxId) || null}
                  select={showLetter}
                  calendar={calendar} tournament={tournament}
                />
              ) : active === "Сохранения" ? (
                <>
                  <Heading title="Сохранения" sub={c.club} />
                  <Saves {...{ act, c, enabled }} />
                </>
              ) : active === "Настройки" ? (
                <>
                  <Heading
                    title="Настройки"
                    sub="Отображение и домашний сервер"
                  />
                  <div className="surface panel-body settings-list">
                    <label>
                      <input
                        type="checkbox"
                        checked={compact}
                        onChange={(e) => {
                          setCompact(e.target.checked);
                          localStorage.setItem(
                            "esport-sim/compact",
                            String(e.target.checked),
                          );
                        }}
                      />
                      Компактные таблицы
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={motion}
                        onChange={(e) => {
                          setMotion(e.target.checked);
                          localStorage.setItem(
                            "esport-sim/motion",
                            String(e.target.checked),
                          );
                        }}
                      />
                      Анимации интерфейса
                    </label>
                    {settings}
                  </div>
                </>
              ) : !scene || directory.error ? (
                <Load {...directory} />
              ) : route.profile?.group === "staff" && c.office.people[route.profile.id] ? (
                <StaffOffice key={route.profile.id} {...{c,scene,act}} enabled={enabled && !frame.world.series && !frame.world.match} initial="Тренерский штаб" personId={route.profile.id}/>
              ) : ["Тренерский штаб","Скаутский отдел"].includes(active) ? (
                <StaffOffice {...{c,scene,act}} enabled={enabled && !frame.world.series && !frame.world.match} initial={active}/>
              ) : route.profile ? (
                <EntityProfile
                  key={route.profile.group + route.profile.id}
                  {...{ profile: route.profile, scene, c, open, back }}
                />
              ) : active === "Организация" ? (
                <EntityProfile
                  {...{
                    profile: { group: "teams", id: c.team },
                    scene,
                    c,
                    open,
                    back,
                  }}
                />
              ) : active === "Состав" ? (
                <Squad
                  {...{
                    scene,
                    c,
                    open,
                    filter,
                    setFilter,
                    query,
                    setQuery,
                    sort,
                    setSort,
                  }}
                />
              ) : active === "Соревнования" || active === "Рейтинг VRS" ? (
                <CompetitionCenter key={(route.edition||"directory")+":"+route.jump} initialEdition={route.edition} initialEntry={route.entry==="entry" || route.entry==="calendar"} initialConflict={route.entry==="calendar"} {...{c,scene,act,enabled}} revision={frame.careerRevision||0} rankings={active==="Рейтинг VRS"}/>
              ) : active === "База сцены" ? (
                <Directory {...{ scene, open }} view={directoryView} />
              ) : active === "Матч-центр" ? (
                <>
                  <Heading title="Матч-центр" sub="Ближайшая встреча" />
                  <section className="surface panel-body">
                    {next && (
                      <>
                        <h2>{next.teams.map((t) => c.teams[t]).join(" — ")}</h2>
                        <p>{date(next.date)} · {next.title || "Выставочный"} BO{next.bestOf ?? 1} · {fixtureMap(next)}</p>
                        <button
                          className="btn"
                          onClick={() => calendar(next.date)}
                        >
                          Открыть календарь
                        </button>
                      </>
                    )}
                  </section>
                </>
              ) : (
                <Dashboard
                  {...{
                    c,
                    scene,
                    box,
                    go: nav,
                    calendar,
                    open,
                    letter: showLetter,
                  }}
                />
              ))}
          </div>
        </div>
      </div>
      {search && (
        <Dialog title="Глобальный поиск" close={() => setSearch(false)}>
          <label className="search-box">
            <Glyph name="search" />
            <input
              autoFocus
              placeholder="Игрок, команда, организация или раздел"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter")
                  e.currentTarget
                    .closest("dialog")
                    ?.querySelector<HTMLButtonElement>(".search-result")
                    ?.click();
              }}
            />
          </label>
          <div className="search-results">
            {sections.flatMap(([, items]) =>
              items
                .filter(([s]) => s.toLowerCase().includes(q.toLowerCase()))
                .map(([s, i]) => (
                  <button
                    className="search-result"
                    key={s}
                    onClick={() => nav(s)}
                  >
                    <Glyph name={i} />
                    <span>
                      <strong>{s}</strong>
                      <small>Раздел карьеры</small>
                    </span>
                  </button>
                )),
            )}
            {matches.map((r) => (
              <button
                className="search-result"
                key={r.group + r.id}
                onClick={() => open(r)}
              >
                <Avatar name={r.name} {...r.visual} />
                <span>
                  <strong>{r.name}</strong>
                  <small>{groupTitle[r.group]}</small>
                </span>
              </button>
            ))}
            {!scene && <Load {...directory} />}
            {scene &&
              !matches.length &&
              !sections.some(([, items]) =>
                items.some(([s]) => s.toLowerCase().includes(q.toLowerCase())),
              ) && <p className="empty-state">Ничего не найдено.</p>}
          </div>
        </Dialog>
      )}
    </div>
  );
}
