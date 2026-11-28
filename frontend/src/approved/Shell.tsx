import React, { type ReactNode, type RefObject } from "react";
import { Icon, Button } from "./Shared";
import { TeamLogo } from "./Identity";
import { type Career, position, date } from "../careerData";
import "./reset.css";
import "./shell.css";
import "./adapters.css";
const groups = [
  [
    "КАРЬЕРА",
    [
      ["home", "Кабинет", "home"],
      ["inbox", "Входящие", "mail"],
      ["calendar", "Календарь", "calendar"],
      ["competitions", "Соревнования", "trophy"],
      ["rankings", "Рейтинг VRS", "chart"],
    ],
  ],
  [
    "МОЯ КОМАНДА",
    [
      ["roster", "Состав", "users"],
      ["training", "Тренировки", "training"],
      ["staff", "Тренерский штаб", "staff"],
      ["scouting", "Скаутинг", "search"],
      ["tactics", "Тактики", "tactic"],
      ["organization", "Организация", "shield"],
    ],
  ],
  [
    "НА СЕРВЕРЕ",
    [
      ["match", "Матч-центр", "play"],
      ["archive", "Архив матчей", "database"],
      ["analytics", "Аналитика", "chart"],
      ["scene", "База сцены", "grid"],
    ],
  ],
] as const;
const routes: Record<string, string> = {
  home: "Кабинет",
  inbox: "Входящие",
  calendar: "Календарь",
  competitions: "Соревнования",
  rankings: "Рейтинг VRS",
  roster: "Состав",
  training: "Тренировочный центр",
  staff: "Тренерский штаб",
  scouting: "Скаутский отдел",
  tactics: "Тактики",
  organization: "Организация",
  match: "Матч-центр",
  archive: "Архив матчей",
  analytics: "Аналитика",
  scene: "База сцены",
};
export function ApprovedShell({
  children,
  c,
  active,
  section,
  nav,
  menu,
  team,
  drawer,
  setDrawer,
  side,
  small,
  unread,
  search,
  advance,
  disabled,
  action,
  day,
  decisions,
  status,
}: {
  children: ReactNode;
  c: Career;
  active: string;
  section: string;
  nav: (p: string) => void;
  menu: () => void;
  team: () => void;
  drawer: boolean;
  setDrawer: (v: boolean) => void;
  side: RefObject<HTMLElement | null>;
  small: boolean;
  unread: number;
  search: () => void;
  advance: () => void;
  disabled: boolean;
  action: string;
  day: string;
  decisions: () => void;
  status: ReactNode;
}) {
  return (
    <div className="r571">
      <div className="app-shell">
        <a
          href="#main-content"
          className="skip-link"
          onClick={(e) => {
            e.preventDefault();
            document.getElementById("main-content")?.focus();
          }}
        >
          К содержимому
        </a>
        {drawer && (
          <button
            className="drawer-scrim"
            aria-label="Закрыть меню"
            onClick={() => setDrawer(false)}
          />
        )}
        <aside
          className={"sidebar" + (drawer ? " open" : "")}
          ref={side}
          inert={small && !drawer}
          aria-label="Навигация по игре"
        >
          <button className="brand" onClick={menu} aria-label="← Главное меню">
            <span className="brand-symbol">
              <Icon name="tactic" size={24} />
            </span>
            <span>
              <b>ESPORT SIM</b>
              <small>TEAM MANAGER</small>
            </span>
          </button>
          <button className="club-switch" onClick={() => team()} title={c.club}>
            <TeamLogo visual={c.visual} name={c.club} size={38} />
            <span>
              <strong>{c.club.toUpperCase()}</strong>
              <small>Сезон {c.date.slice(0, 4)}</small>
            </span>
            <Icon name="chevron" size={14} />
          </button>
          <nav className="side-nav">
            {groups.map(([title, items]) => (
              <React.Fragment key={title}>
                <div className="nav-group">{title}</div>
                {items
                  .filter(
                    ([id]) =>
                      c.competitions ||
                      !["competitions", "rankings"].includes(id),
                  )
                  .map(([id, label, icon]) => (
                    <button
                      key={id}
                      className={
                        "nav-link" + (active === routes[id] ? " active" : "")
                      }
                      onClick={() => nav(routes[id])}
                      title={label}
                      aria-label={
                        id === "inbox" ? label + " · " + unread : routes[id]
                      }
                      aria-current={active === routes[id] ? "page" : undefined}
                    >
                      <Icon name={icon} size={18} />
                      <span>{label}</span>
                      {id === "inbox" && (
                        <span className="nav-count">{unread}</span>
                      )}
                    </button>
                  ))}
              </React.Fragment>
            ))}
          </nav>

          <div className="sidebar-footer">
            <button className="nav-link" onClick={menu} title="Главное меню">
              <Icon name="grid" size={18} />
              <span>Главное меню</span>
            </button>
            <div className="manager-strip">
              <span className="avatar">{c.character.slice(0, 1)}</span>
              <div>
                <strong>{c.character}</strong>
                <small>{position(c.mode)}</small>
              </div>
              <button
                className="btn btn-ghost"
                aria-label="Настройки"
                onClick={() => nav("Настройки")}
              >
                <Icon name="settings" size={16} />
              </button>
            </div>
            <div className="sidebar-status">
              {status}
              <button
                className="btn btn-ghost"
                aria-label="Сохранения"
                onClick={() => nav("Сохранения")}
              >
                <Icon name="save" size={15} />
              </button>
            </div>
          </div>
        </aside>
        <div className="workspace" inert={small && drawer}>
          <header className="topbar">
            <button
              className="icon-button mobile-menu"
              aria-label="Открыть навигацию"
              aria-expanded={drawer}
              onClick={() => setDrawer(!drawer)}
            >
              <Icon name="menu" />
            </button>
            <div className="breadcrumb">
              <span>{c.club}</span>
              <Icon name="chevron" size={12} />
              <strong>{section}</strong>
            </div>
            <button
              className="top-search"
              onClick={search}
              aria-label="Глобальный поиск"
            >
              <Icon name="search" size={18} />
              <span>Поиск в мире</span>
              <kbd className="key">Ctrl K</kbd>
            </button>
            <div className="top-date">
              <strong>{date(day)}</strong>
              <small>
                {new Date(day + "T12:00:00Z").toLocaleDateString("ru", {
                  weekday: "long",
                  timeZone: "UTC",
                })}
              </small>
            </div>
            <Button variant="primary" onClick={advance} disabled={disabled}>
              {action}
            </Button>
          </header>
          <div className="demo-ribbon">
            <span>
              R5.7 · КАРЬЕРА <span className="source-label"> / {c.club}</span>
            </span>
            <button aria-label="Открыть центр решений" onClick={decisions}>
              Центр решений
            </button>
          </div>
          <main id="main-content" className="page-content" tabIndex={-1}>
            {children}
          </main>
        </div>
        <nav
          className="bottom-nav"
          aria-label="Быстрая навигация"
          inert={drawer}
        >
          {[
            ["home", "Кабинет", "home"],
            ["roster", "Состав", "users"],
            ["match", "Матч", "play"],
            ...(c.competitions ? [["competitions", "Турниры", "trophy"]] : []),
          ].map(([id, label, icon]) => (
            <button
              key={id}
              aria-label={"Быстрый переход · " + label}
              className={active === routes[id] ? "active" : ""}
              onClick={() => nav(routes[id])}
            >
              <Icon name={icon} />
              <span>{label}</span>
            </button>
          ))}
          <button onClick={() => setDrawer(!drawer)} aria-label="Все разделы">
            <Icon name="menu" />
            <span>Ещё</span>
          </button>
        </nav>
      </div>
    </div>
  );
}
