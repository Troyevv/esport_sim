import type { ReactNode } from "react";
import { type Career, type Scene, age } from "../careerData";
import { roles, skillLabels } from "../databaseModel";
import { range, type Knowledge } from "../ScoutingCenter";
import { Flag } from "../SceneIdentity";
import { Badge, Button, Icon } from "./Shared";
import { Portrait, TeamLogo } from "./Identity";
import "./Club.css";

export function Section({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="club-section">
      <div className="club-section-head">
        <h2>{title}</h2>
      </div>
      {children}
    </section>
  );
}
export function SkillRow({
  label,
  value,
}: {
  label: string;
  value?: number | [number, number];
}) {
  const lo = Array.isArray(value) ? value[0] : 0,
    hi = Array.isArray(value) ? value[1] : value;
  return (
    <div className="club-meter-row">
      <span>{label}</span>
      <div className="club-meter-track">
        {hi != null && (
          <i style={{ width: hi - lo + "%", marginLeft: lo + "%" }} />
        )}
      </div>
      <strong>{Array.isArray(value) ? range(value) : (value ?? "—")}</strong>
    </div>
  );
}
type PlayerProps = {
  c: Career;
  scene: Scene;
  id: string;
  assessment?: Knowledge | null;
};
export function PlayerHero({
  c,
  scene,
  id,
  assessment,
  role,
  setRole,
  back,
  team,
  navigate,
  tab,
  canTalk, compare,
}: PlayerProps & {
  canTalk: boolean;
  compare: () => void;
  role: string;
  setRole: (s: string) => void;
  back: () => void;
  team: (id: string) => void;
  navigate?: (p: string) => void;
  tab: (s: string) => void;
}) {
  const p = scene.players[id],
    own = c.roster.find((p) => p.id === id),
    tid = p.teams[0],
    club = scene.teams[tid];
  const roleName =
    roles[own?.role || p.role || ""] || p.role || "Роль не указана";
  return (
    <>
      <button className="club-breadcrumb" onClick={back}>
        <Icon name="back" size={16} />
        Назад
      </button>
      <header className="club-profile-hero">
        <div className="club-profile-portrait">
          <Portrait
            id={id}
            name={p.name}
            size="large"
            visual={own?.visual || p.visual}
          />
          {club && <TeamLogo size={42} name={club.name} visual={club.visual} />}
        </div>
        <div className="club-profile-copy">
          <div className="club-kicker">
            ПРОФИЛЬ ИГРОКА{" "}
            <span>
              {own
                ? "№ " + String(c.roster.indexOf(own) + 1).padStart(2, "0")
                : "SC"}
            </span>
          </div>
          <h1>{p.name}</h1>
          <p className="club-fullname">{p.realName}</p>
          <div className="club-profile-meta">
            <Flag value={p.visual.flag} />
            <span>
              {p.born ? age(p.born, c.date) + " лет" : "Возраст не указан"}
            </span>
            <span>•</span>
            {club && (
              <button className="club-text-link" onClick={() => team(tid)}>
                {club.name}
              </button>
            )}
            <Badge>{roleName}</Badge>
          </div>
          <p className="club-profile-brief">
            {own
              ? (own.captain ? "Капитан " : "Игрок основного состава ") +
                c.club +
                ". Роль в заявке — " +
                roleName.toLowerCase() +
                ". Штаб обновляет оценку по мере тренировок и выступлений."
              : assessment?.level || "Сведения из базы сцены."}
          </p>
          <div className="club-actions">
            <Button
              variant="primary"
              disabled={!!own && !canTalk}
              title={
                own && !canTalk
                  ? "Разговор доступен в тренерской комнате во время своего тайм-аута"
                  : undefined
              }
              onClick={() => (own ? navigate?.("Матч-центр") : tab("Скаутинг"))}
            >
              {own ? "Поговорить с игроком" : "Оценка скаута"}
            </Button>
            <Button
              onClick={() =>
                navigate?.(own ? "Тренировочный центр" : "Скаутский отдел")
              }
            >
              {own ? "Программа развития" : "Скаутский отдел"}
            </Button>
            <Button onClick={compare}><Icon name="chart" size={16}/> Сравнить игроков</Button>
          </div>
        </div>
        <div className="club-profile-overall">
          <span>{own ? "ОЦЕНКА РОЛИ" : "ОЦЕНКА СКАУТА"}</span>
          <strong>{own?.ratings[role] ?? range(assessment?.current)}</strong>
          {own && (
            <label className="club-filter">
              <span>Роль для оценки</span>
              <select
                aria-label="Роль для оценки OVR"
                value={role}
                onChange={(e) => setRole(e.target.value)}
              >
                {Object.keys(own.ratings).map((r) => (
                  <option key={r} value={r}>
                    {roles[r] || r}
                  </option>
                ))}
              </select>
            </label>
          )}
          <small>
            {own
              ? "Внутренние данные клуба"
              : assessment?.level || "Нет наблюдений"}
          </small>
        </div>
      </header>
    </>
  );
}
export function PlayerOverview({
  c,
  scene,
  id,
  assessment,
  maps,
  tab,
}: PlayerProps & {
  maps: { key: string; name: string; impact: number | null }[];
  tab: (s: string) => void;
}) {
  const p = scene.players[id],
    own = c.roster.find((p) => p.id === id);
  return (
    <>
      <div className="club-two-col">
        <Section title="Игровой профиль">
          <p className="club-lead">
            {p.name} · {roles[own?.role || p.role || ""] || p.role}
          </p>
          {["aim", "positioning", "communication", "concentration"].map((k) => (
            <SkillRow
              key={k}
              label={skillLabels[k]}
              value={own?.skills[k] ?? assessment?.skills[k]}
            />
          ))}
          <button
            className="club-text-link"
            onClick={() => tab("Характеристики · 58")}
          >
            Все 58 характеристик →
          </button>
        </Section>
        <Section title="Состояние и контекст">
          {own ? (
            <>
              <SkillRow label="Готовность" value={100 - own.fatigue} />
              <SkillRow label="Настрой" value={own.morale} />
              <SkillRow label="Усталость" value={own.fatigue} />
              <SkillRow label="Форма" value={own.form} />
              <div className="club-note-callout">
                <strong>Оценка тренерского штаба</strong>
                <p>Состояние игрока на текущий день карьеры.</p>
              </div>
            </>
          ) : (
            <div className="club-note-callout">
              <Icon name="eye" />
              <strong>Внутреннее состояние недоступно</strong>
              <p>Наблюдения штаба доступны в скаутском отчёте.</p>
            </div>
          )}
        </Section>
      </div>
      <div className="club-two-col">
        <Section title="Биография">
          <dl className="club-facts">
            <dt>Имя</dt>
            <dd>{p.realName || "Не указано"}</dd>
            <dt>Команда</dt>
            <dd>
              {p.teams.map((t) => scene.teams[t]?.name).join(", ") ||
                "Нет заявки"}
            </dd>
            <dt>Дата рождения</dt>
            <dd>{p.born || "Не указана"}</dd>
          </dl>
        </Section>
        <Section title="Последние выступления">
          {maps.length ? (
            <div className="club-perform-bars">
              {[...maps].reverse().map((m) => (
                <button
                  key={m.key}
                  onClick={() => tab("Статистика")}
                  title={m.name + " · Impact " + (m.impact?.toFixed(2) ?? "—")}
                >
                  <span
                    style={{
                      height:
                        m.impact == null
                          ? 0
                          : Math.max(1, 75 * m.impact) + "px",
                    }}
                  />
                  <b>{m.impact?.toFixed(2) ?? "—"}</b>
                  <small>{m.name}</small>
                </button>
              ))}
            </div>
          ) : (
            <p>В карьере пока нет завершённых карт игрока.</p>
          )}

          <button className="club-text-link" onClick={() => tab("Статистика")}>
            Статистика по картам →
          </button>
        </Section>
      </div>
    </>
  );
}
