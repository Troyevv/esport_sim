import { useState } from "react";
import type { PlanRef } from "./tactics";
import Radar from "./Radar";
import type { Frame, View } from "./session";
import type { RadarPlayback } from "./playback";
import "./match.css";
import { Avatar, Identity, type Visual } from "./SceneIdentity";
import { itemLabel } from "./scorebotIcons";
import { Gear, ItemIcon, WeaponSlots } from "./MatchEquipment";
import { RoleRatings } from "./SceneProfiles";

type Side = "CT" | "T";
type Point = { x: number; y: number };
export interface MatchView {
  rules: string;
  clubs: {
    id: string;
    name: string;
    side: Side;
    score: number;
    visual?: Visual;
  }[];
  coachTeamId: string;
  winnerTeamId: string | null;
  source?: { id: string; revision: number };
  roleRatings: Record<string, Record<string, number>>;
  teamRating: number | null;
  round: number;
  phase: string;
  clock: number;
  teams: string[];
  teamVisuals?: (Visual | null)[];
  sides: Side[];
  score: number[];
  pregame: boolean;
  nextBuy: string | null;
  prepared: PlanRef[];
  history: {
    tactic?: PlanRef;
    round: number;
    winner: number;
    winnerTeamId: string;
    scoreByTeam: Record<string, number>;
    side: Side;
    reason: string;
    score: number[];
    duration: number;
    economy: Partial<Record<Side, number>>;
  }[];
  stats: {
    id: string;
    name: string;
    club: number;
    teamId: string;
    visual?: Visual;
    team: Side;
    role: string;
    k: number;
    d: number;
    a: number;
    hs: number;
    damage: number;
    opening: number;
    kast: number;
    spent: number | null;
    clutches: number;
  }[];
  bomb: (Point & { carrier: string | null; site: string | null }) | null;
  action: { player: string; kind: string; start: number; end: number } | null;
  effects: (Point & {
    team?: Side;
    kind: string;
    sx: number;
    sy: number;
    land: number;
    end: number;
    start: number;
    radius: number;
  })[];
  resolution: { kind: string; tick: number } | null;
  groundWeapons: (Point & { id: number; weapon: string })[];
  shots: (Point & { tx: number; ty: number; tick: number })[];
  kills: {
    id: number;
    player: string;
    target: string;
    weapon: string;
    head: boolean;
    assists: string[];
    opening: boolean;
    trade: string | null;
    enemy: boolean;
  }[];
  plans: Partial<
    Record<Side, { site: string; style: string; buy: string; tactic?: PlanRef }>
  >;
  remaining: number;
  timeoutLimit: number;
  pending: boolean;
  call: string | null;
  calls: string[];
  feedback: { player: string; id: number; round: number; text: string }[];
}

const phases: Record<string, string> = {
  freeze: "Подготовка",
  live: "В игре",
  planted: "C4 установлена",
  result: "Раунд завершён",
  timeout: "Тактический тайм-аут",
  finished: "Матч завершён",
};
const tabs = ["Составы", "Статистика", "Раунды", "Журнал"] as const;
const clock = (ticks: number) => {
  const seconds = Math.ceil(ticks / 10);
  return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
};
type Props = {
  frame: Frame;
  playback: RadarPlayback;
  connected: boolean;
  enabled: boolean;
  act: (name: string, value?: number | string) => Promise<boolean>;
  openBoard: () => void;
  setView: (v: View) => void;
};

const money = (amount: number) => "$" + amount.toLocaleString("ru-RU");
function RosterPanel({
  club,
  frame,
  selected,
  select,
}: {
  club: MatchView["clubs"][number];
  frame: Frame;
  selected: string | null;
  select: (id: string) => void;
}) {
  const { match: m, agents } = frame.world;
  const players = m!.stats.filter((row) => row.teamId === club.id);
  return (
    <section
      className="hud-team"
      data-team={club.id}
      data-side={club.side}
      aria-label={"Пятёрка · " + club.name}
    >
      <h3>
        <span>{club.name}</span>
        <small>
          {club.side}
          {club.id === m!.coachTeamId &&
            m!.teamRating != null &&
            " · OVR " + m!.teamRating}
        </small>
      </h3>
      {players.map((row) => {
        const a = agents.find((p) => p.id === row.id);
        const dead =
          a?.alive === false || m!.kills.some((k) => k.target === row.id);
        const hp = dead ? 0 : a?.hp;
        return (
          <button
            key={row.id}
            className="player-card"
            data-player={row.id}
            data-dead={dead}
            aria-pressed={selected === row.id}
            disabled={!a}
            onClick={() => select(row.id)}
          >
            <span className="hud-head">
              <Avatar name={row.name} {...row.visual} />
              <span>
                <strong>{row.name}</strong>
                <small>{row.role}</small>
              </span>
              <b className="hud-hp">
                {hp ?? "—"}
                <small>HP</small>
              </b>
            </span>
            <span
              className="hud-health"
              role="meter"
              aria-label={"Здоровье · " + row.name}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={hp}
            >
              <i style={{ width: (hp ?? 0) + "%" }} />
            </span>
            <span className="hud-loadout">
              <WeaponSlots a={a} dead={dead} />
              <span>{a?.cash !== undefined ? money(a.cash) : "—"}</span>
            </span>
            <Gear a={a} dead={dead} carrier={m!.bomb?.carrier === row.id} />
            <span className="hud-figures">
              <span title="Убийства / смерти / передачи">
                K/D/A{" "}
                <b>
                  {row.k}/{row.d}/{row.a}
                </b>
              </span>
              <span>
                ADR <b>{Math.round(row.damage / m!.round)}</b>
              </span>
              <span title="Стоимость экипировки">
                Инв.{" "}
                <b>
                  {a?.equipmentValue !== undefined
                    ? money(a.equipmentValue)
                    : "—"}
                </b>
              </span>
            </span>
          </button>
        );
      })}
    </section>
  );
}

export default function MatchCenter({
  frame,
  playback,
  openBoard,
  connected,
  enabled,
  act,
  setView,
}: Props) {
  const world = frame.world,
    m = world.match!;
  const [tab, setTab] = useState<(typeof tabs)[number]>("Статистика");
  const [pane, setPane] = useState(0);
  const [selected, select] = useState<string | null>(null);
  const [seed, setSeed] = useState(String(world.seed));
  const [nextCall, setNextCall] = useState(m.calls[0]);
  const selectedAgent = world.agents.find((a) => a.id === selected);
  const name = (id: string) => m.stats.find((p) => p.id === id)?.name ?? id;
  const finished = m.phase === "finished",
    timeout = m.phase === "timeout";
  const rounds = m.history.length;
  const coach = m.clubs.find((c) => c.id === m.coachTeamId)!;
  const opponent = m.clubs.find((c) => c.id !== m.coachTeamId)!;
  const clubName = (id: string) => m.clubs.find((c) => c.id === id)?.name;
  const roster = (club: MatchView["clubs"][number]) => (
    <RosterPanel
      club={club}
      frame={frame}
      selected={selected}
      select={(id) => {
        select(id);
        setTab("Составы");
      }}
    />
  );
  const played = new Map<
    string,
    { plan: PlanRef; rounds: number; wins: number }
  >();
  if (tab === "Раунды") {
    for (const row of m.history) {
      if (!row.tactic) continue;
      const key = row.tactic.id + "/" + row.tactic.revision;
      const entry = played.get(key) || { plan: row.tactic, rounds: 0, wins: 0 };
      entry.rounds++;
      if (row.winnerTeamId === coach.id) entry.wins++;
      played.set(key, entry);
    }
  }
  return (
    <article className="match-center">
      <header className="match-title">
        <div>
          <span className="eyebrow">МАТЧ-ЦЕНТР</span>
          <h1>{m.clubs.map((c) => c.name).join(" — ")}</h1>
        </div>
        <button onClick={openBoard}>Редактор тактик</button>
        <span
          className={
            "match-format" +
            (m.source && m.source.id !== "depo-exhibition" ? " sourced" : "")
          }
        >
          Выставочный матч · <br />
          {m.source && m.source.id !== "depo-exhibition"
            ? "Составы из базы · ред. " + m.source.revision
            : "Тестовые составы"}
        </span>
      </header>
      <div className="match-meta-strip">
        <span>{world.map.name} · BO1</span>
        <span>{phases[m.phase]}</span>
      </div>
      <section className="scoreboard" aria-label="Счёт матча">
        {m.clubs.map((club, i) => (
          <div
            key={club.id}
            data-team={club.id}
            data-side={club.side}
            className={"club club-" + i}
          >
            <span className="club-side">
              {club.side} · {club.id === coach.id ? "Ваша команда" : "Соперник"}
            </span>
            <strong>
              <Avatar name={club.name} club {...club.visual} />
              <span>{club.name}</span>
            </strong>
            <b>{club.score}</b>
          </div>
        ))}
        <div className="round-clock" data-planted={m.phase === "planted"}>
          <small>РАУНД {m.round}</small>
          <b>
            {finished
              ? "ФИНАЛ"
              : timeout
                ? "ПАУЗА"
                : m.phase === "result"
                  ? "ИТОГ"
                  : clock(m.clock)}
          </b>
          <span>{phases[m.phase]}</span>
        </div>
      </section>
      {finished && (
        <p className="match-result">
          Победитель матча — <strong>{clubName(m.winnerTeamId!)}</strong>
        </p>
      )}
      {rounds > 0 && (
        <div className="hud-history" aria-label="Последние раунды">
          <strong>Раунды</strong>
          {m.history.slice(-12).map((r) => (
            <button
              data-side={r.side}
              key={r.round}
              onClick={() => {
                setTab("Раунды");
                document
                  .querySelector(".match-data")
                  ?.scrollIntoView({ block: "start" });
              }}
              title={clubName(r.winnerTeamId) + " · " + r.reason}
              aria-label={
                "Раунд " +
                r.round +
                " · " +
                clubName(r.winnerTeamId) +
                " · " +
                r.reason
              }
            >
              <b>{r.round}</b>
              <ItemIcon
                name={
                  { "Взрыв C4": "C4", Обезвреживание: "Набор" }[r.reason] ||
                  r.reason
                }
                label={r.reason}
              />
            </button>
          ))}
        </div>
      )}

      <nav className="touch-lineup" aria-label="Панель матча">
        {["Радар", ...m.clubs.map((c) => c.name)].map((label, i) => (
          <button key={i} aria-pressed={pane === i} onClick={() => setPane(i)}>
            {label}
          </button>
        ))}
      </nav>
      <div className="lineups" data-pane={pane}>
        {roster(m.clubs[0])}
        <section className="panel hud-map">
          <div className="maphead">
            <div className="mapname">
              <h2>Тактический радар</h2>
            </div>
            <select
              aria-label="Режим обзора"
              value={world.view}
              onChange={(e) => {
                select(null);
                setView(e.target.value as View);
              }}
            >
              <option value="full">Полная карта · анализ</option>
              <option value="T">Видимость T</option>
              <option value="CT">Видимость CT</option>
            </select>
          </div>
          {m.phase === "planted" && (
            <div className="hud-bomb">
              <strong>
                <ItemIcon name="C4" /> · {m.bomb?.site || "Установлена"}
              </strong>
              <span>
                {m.action?.kind === "defuse" ? "Обезвреживание" : "До взрыва"} ·{" "}
                {clock(m.clock)}
              </span>
              <progress
                aria-label="Время до взрыва"
                value={m.clock}
                max={400}
              />
            </div>
          )}
          <div className="radar-broadcast">
            <Radar
              frame={frame}
              playback={playback}
              connected={connected}
              selected={selectedAgent?.id ?? null}
              onSelect={select}
            />
            <section className="live-feed" aria-label="Лента убийств">
              {m.kills
                .slice()
                .reverse()
                .map((k) => (
                  <div key={k.id} className="kill-row" data-kill={k.id}>
                    <span className="kill-attacker">
                      {k.weapon !== "C4" && <b>{name(k.player)}</b>}
                      {k.assists?.length > 0 && (
                        <span className="assist">
                          <ItemIcon name="Помощь" />
                          {k.assists.map(name).join(", ")}
                        </span>
                      )}
                    </span>
                    <span className="kill-method">
                      <ItemIcon
                        name={k.weapon}
                        side={m.stats.find((p) => p.id === k.player)?.team}
                        label={
                          ["HE", "Огонь"].includes(k.weapon)
                            ? "Убийство гранатой · " +
                              itemLabel(
                                k.weapon,
                                m.stats.find((p) => p.id === k.player)?.team,
                              )
                            : undefined
                        }
                        className="kill-weapon"
                      />
                      {k.head && <ItemIcon name="В голову" />}
                      {k.opening && (
                        <abbr
                          title="Первое убийство раунда"
                          aria-label="Первое убийство раунда"
                        >
                          1K
                        </abbr>
                      )}
                      {k.trade && (
                        <ItemIcon
                          name="Размен"
                          label={"Размен за " + name(k.trade)}
                        />
                      )}
                      {!k.enemy &&
                        k.weapon !== "C4" &&
                        (k.player === k.target ? (
                          <ItemIcon name="Самоустранение" />
                        ) : (
                          <abbr
                            title="Убийство союзника"
                            aria-label="Убийство союзника"
                          >
                            TK
                          </abbr>
                        ))}
                    </span>
                    <b>{name(k.target)}</b>
                  </div>
                ))}
            </section>
          </div>
          <div className="match-legend">
            <span>● CT</span>
            <span>◆ T</span>
            <span>
              <ItemIcon name="C4" /> C4
            </span>
            <span>
              {selectedAgent
                ? selectedAgent.name + " · " + selectedAgent.status
                : "Выберите игрока на карте"}
            </span>
          </div>
        </section>
        {roster(m.clubs[1])}
      </div>
      <section className="hud-controls" aria-label="Управление просмотром">
        <button
          className="primary"
          disabled={!enabled || finished || timeout}
          onClick={() => act(frame.running ? "pause" : "start")}
        >
          {frame.running ? "Пауза просмотра" : "Запустить"}
        </button>
        <div className="speed-list">
          {[1, 2, 4, 8, 128].map((n) => (
            <button
              key={n}
              disabled={!enabled}
              aria-pressed={frame.speed === n}
              onClick={() => act("speed", n)}
            >
              {n === 128 ? "Быстро" : n + "×"}
            </button>
          ))}
        </div>
      </section>
      <div className="match-grid">
        <div className="match-main">
          <section className="panel match-data">
            <nav aria-label="Данные матча">
              {tabs.map((t) => (
                <button
                  key={t}
                  aria-pressed={tab === t}
                  onClick={() => setTab(t)}
                >
                  {t}
                </button>
              ))}
            </nav>
            {tab === "Составы" && !selectedAgent && (
              <p className="inventory">
                Выберите игрока на радаре или в пятёрке команды, чтобы открыть
                его роль и снаряжение.
              </p>
            )}
            {tab === "Составы" && selectedAgent && (
              <div className="inventory">
                <b>{selectedAgent.name}</b> · {selectedAgent.status}
                {m.roleRatings[selectedAgent.id] && (
                  <RoleRatings
                    values={m.roleRatings[selectedAgent.id]}
                    compact
                  />
                )}
                <div className="selected-loadout">
                  <WeaponSlots
                    a={selectedAgent}
                    dead={selectedAgent.alive === false}
                  />
                  <Gear
                    a={selectedAgent}
                    dead={selectedAgent.alive === false}
                    carrier={m.bomb?.carrier === selectedAgent.id}
                  />
                  {selectedAgent.alive && selectedAgent.ammo !== undefined && (
                    <span>
                      Патроны {selectedAgent.ammo}/{selectedAgent.reserve}
                    </span>
                  )}
                </div>
              </div>
            )}
            {tab === "Статистика" && (
              <div
                className="table-scroll"
                tabIndex={0}
                aria-label="Таблица статистики"
              >
                <table>
                  <thead>
                    <tr>
                      {[
                        "Игрок",
                        "K",
                        "A",
                        "D",
                        "ADR",
                        "KAST",
                        "HS",
                        "Первые",
                        "Клатчи",
                        "Расходы",
                      ].map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {m.stats.map((p) => (
                      <tr key={p.id}>
                        <th>
                          {p.visual ? (
                            <Identity name={p.name} visual={p.visual} />
                          ) : (
                            p.name
                          )}
                          <small>{clubName(p.teamId)}</small>
                        </th>
                        {[
                          p.k,
                          p.a,
                          p.d,
                          (p.damage / Math.max(1, m.round)).toFixed(1),
                          rounds
                            ? Math.round((100 * p.kast) / rounds) + "%"
                            : "—",
                          p.hs,
                          p.opening,
                          p.clutches,
                          p.spent === null ? "—" : p.spent + " $",
                        ].map((v, i) => (
                          <td key={i}>{v}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {tab === "Раунды" && played.size > 0 && (
              <section className="inventory tactic-results">
                <h3>Тактики против «{opponent.name}»</h3>
                <small>
                  {world.map.name} ·{" "}
                  {m.stats
                    .filter((p) => p.teamId === coach.id)
                    .map((p) => p.name)
                    .join(", ")}
                </small>
                {[...played.values()].map(({ plan, rounds, wins }) => (
                  <p key={plan.id + plan.revision}>
                    <b>{plan.name}</b> · в{plan.revision} · {plan.side} ·{" "}
                    {plan.buy} · выиграно {wins} из {rounds}
                  </p>
                ))}
              </section>
            )}
            {tab === "Раунды" && (
              <div className="round-list">
                {!rounds && <p>История появится после первого раунда.</p>}
                {m.history
                  .slice()
                  .reverse()
                  .map((r) => (
                    <div key={r.round}>
                      <small>R{r.round}</small>
                      <b>
                        {m.clubs.map((c) => r.scoreByTeam[c.id]).join(" : ")}
                      </b>
                      <span>
                        {clubName(r.winnerTeamId)} · {r.side}
                      </span>
                      <span>
                        {r.reason}
                        {r.tactic && (
                          <small className="round-economy">
                            {r.tactic.name} · в{r.tactic.revision} ·{" "}
                            {r.tactic.side} · {r.tactic.buy}
                          </small>
                        )}
                        <small className="round-economy">
                          {clock(r.duration)} ·{" "}
                          {Object.entries(r.economy)
                            .map(([side, total]) => side + " " + total + " $")
                            .join(" / ")}
                        </small>
                      </span>
                    </div>
                  ))}
              </div>
            )}
            {tab === "Журнал" && (
              <ol className="match-events">
                {world.events
                  .slice()
                  .reverse()
                  .map((e, i) => (
                    <li key={e.tick + "-" + i}>
                      <time>{clock(e.tick)}</time>
                      {e.kind === "kill" && e.weapon && e.target && e.player ? (
                        <span className="journal-event">
                          {e.weapon !== "C4" && name(e.player)}
                          <ItemIcon
                            name={e.weapon}
                            side={m.stats.find((p) => p.id === e.player)?.team}
                          />
                          {e.head && <ItemIcon name="В голову" />}
                          {name(e.target)}
                        </span>
                      ) : (
                        <span className="journal-event">
                          {(e.weapon || e.utility) && (
                            <ItemIcon
                              name={(e.weapon || e.utility)!}
                              side={e.team ?? undefined}
                            />
                          )}
                          {e.text}
                        </span>
                      )}
                    </li>
                  ))}
              </ol>
            )}
          </section>
        </div>
        <aside className="match-aside">
          <section className="panel coaching">
            <h2>Скамейка тренера</h2>
            <p>
              {coach.name} · осталось тайм-аутов{" "}
              <b>
                {m.remaining} / {m.timeoutLimit}
              </b>
            </p>
            {m.pregame &&
              m.prepared.map((p) => (
                <p key={p.side + p.buy}>
                  {p.side} · {p.buy} · {p.name} · в{p.revision}
                </p>
              ))}
            {(timeout || m.pregame) && (
              <button onClick={openBoard}>Выбрать тактику</button>
            )}
            {!timeout ? (
              <button
                disabled={
                  !enabled || finished || m.pending || m.remaining === 0
                }
                onClick={() => act("timeout")}
              >
                {m.pending ? "Тайм-аут запрошен" : "Запросить тайм-аут"}
              </button>
            ) : (
              <>
                <h3>Обратная связь</h3>
                {m.feedback.length ? (
                  m.feedback.map((f) => (
                    <blockquote key={f.player}>
                      <b>
                        {f.player} · R{f.round}
                      </b>
                      {f.text}
                    </blockquote>
                  ))
                ) : (
                  <p>
                    {world.view !== "full" && world.view !== coach.side
                      ? "Переключитесь на обзор своей команды."
                      : "У состава пока нет наблюдений."}
                  </p>
                )}
                <label>
                  План на ближайший раунд
                  <select
                    value={nextCall}
                    onChange={(e) => setNextCall(e.target.value)}
                  >
                    {m.calls.map((c) => (
                      <option key={c}>{c}</option>
                    ))}
                  </select>
                </label>
                <button
                  disabled={!enabled}
                  onClick={() => act("call", nextCall)}
                >
                  Передать колл
                </button>
                {m.call && <p role="status">Принято · {m.call}</p>}
                <button
                  className="primary"
                  disabled={!enabled}
                  onClick={() => act("resume")}
                >
                  Завершить тайм-аут
                </button>
              </>
            )}
            {Object.entries(m.plans).map(([side, p]) => (
              <p className="plan-line" key={side}>
                <b>{side} · IGL</b>{" "}
                {p.tactic
                  ? p.tactic.name + " · в" + p.tactic.revision
                  : p.style}{" "}
                · {p.site} · {p.buy}
              </p>
            ))}
          </section>
          <section className="panel broadcast">
            <h2>Сохранение матча</h2>
            <div className="slots">
              <button disabled={!enabled} onClick={() => act("save")}>
                Сохранить
              </button>
              <button
                disabled={!enabled || !frame.hasSave}
                onClick={() => act("load")}
              >
                Загрузить
              </button>
            </div>
            {!frame.careerId && (
              <details>
                <summary>Новый сценарий</summary>
                <label>
                  Seed
                  <input
                    value={seed}
                    inputMode="numeric"
                    onChange={(e) => setSeed(e.target.value)}
                  />
                </label>
                <div className="slots">
                  {[
                    ["match", "Новый BO1"],
                    ["reset", "Стенд R0"],
                  ].map(([kind, label]) => (
                    <button
                      key={kind}
                      disabled={
                        !enabled ||
                        !/^\d+$/.test(seed) ||
                        Number(seed) > 2147483647
                      }
                      onClick={() => act(kind, Number(seed))}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </details>
            )}
          </section>
        </aside>
      </div>
    </article>
  );
}
