import {Badge,Button,Icon,Tabs as ApprovedTabs} from "./approved/Shared";
import {Portrait,TeamLogo} from "./approved/Identity";
import "./approved/Match.css";
import TimeoutRoom, {type Room} from "./TimeoutRoom";
import { SeriesScore } from "./SeriesCenter";
import { useState } from "react";
import type { PlanRef } from "./tactics";
import Radar from "./Radar";
import type { Frame, View } from "./session";
import type { RadarPlayback } from "./playback";
import "./match.css";
import "./arena.css";
import { LineupPortrait, Identity, type Visual } from "./SceneIdentity";
import { itemLabel } from "./scorebotIcons";
import { Gear, ItemIcon, WeaponSlots } from "./MatchEquipment";
import { RoleRatings } from "./SceneProfiles";

type Side = "CT" | "T";
type Point = { x: number; y: number; z?: number };
export interface MatchView {
  award?: { name: string } | null;
  radio?: {player:string;channel:string;state:string;tick:number}[];
  impressions?:Record<string,string>;
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
    flashesThrown?: number; enemiesFlashed?: number; alliesFlashed?: number; selfFlashes?: number;
    enemyBlindTicks?: number; flashAssists?: number; heDamage?: number; fireDamage?: number;
    smokeScreenTicks?: number; firesQuenched?: number; decoyHearings?: number;
  }[];
  bomb: (Point & { carrier: string | null; site: string | null }) | null;
  action: { player: string; kind: string; start: number; end: number } | null;
  effects: (Point & {
    team?: Side;
    kind: string;
    spatial?: boolean;
    burstTick?: number;
    volume?: [number, number, number, number][];
    trajectory?: [number, number, number][];
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
  room?: Room | null;
  breakOwner?: string | null;
  rivalRemaining?: number;
  pending: boolean;
  call: string | null;
  calls: string[];
  feedback: { player: string; id: number; round: number; text: string }[];
}

const radioStates:Record<string,string> = {ack:"Задание принято",help:"Запрашивает поддержку",check:"Проверяет контакт",
  refused:"Не может выполнить задачу",completed:"Задача выполнена",progress:"Выполняет задачу",holding:"Удерживает позицию",moving:"Перемещается"};
const phases: Record<string, string> = {
  freeze: "Подготовка",
  live: "В игре",
  planted: "C4 установлена",
  result: "Раунд завершён",
  timeout: "Тактический тайм-аут",
  finished: "Матч завершён",
};
const tabs = ["Радар","Составы", "Статистика", "Раунды", "Журнал"] as const;
const clock = (ticks: number) => {
  const seconds = Math.ceil(ticks / 10);
  return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
};
type Props = {
  frame: Frame;
  playback: RadarPlayback;
  connected: boolean;
  enabled: boolean;
  act: (name: string, value?: number | string | object) => Promise<boolean>;
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
    <div
      className={
        "mx-live-roster " + (club.id === m!.coachTeamId ? "own" : "rival")
      }
      data-team={club.id}
      data-side={club.side}
      aria-label={"Пятёрка · " + club.name}
    >
      <div
        className="mx-roster-title"
        title={
          club.id === m!.coachTeamId && m!.teamRating != null
            ? "OVR " + m!.teamRating
            : undefined
        }
      >
        <TeamLogo name={club.name} visual={club.visual} size={25} />
        <strong>{club.name}</strong>
        <small>{club.side}</small>
      </div>
      {players.map((row) => {
        const a = agents.find((p) => p.id === row.id),
          dead =
            a?.alive === false || m!.kills.some((k) => k.target === row.id);
        const hp = dead ? 0 : a?.hp,
          known = a?.equipmentValue !== undefined;
        return (
          <button
            key={row.id}
            className={
              "mx-live-player" +
              (dead ? " dead" : "") +
              (selected === row.id ? " selected" : "") +
              (!known ? " mx-limited-player" : "")
            }
            data-player={row.id}
            aria-pressed={selected === row.id}
            onClick={() => select(row.id)}
          >
            <LineupPortrait
              id={a?.playerId || row.id}
              name={row.name}
              visual={row.visual || {}}
            />
            <div className="mx-live-player-data">
              <strong>{row.name}</strong>
              <div className="mx-live-weapon">
                {a?.weapon ? (
                  <ItemIcon name={a.weapon} side={a.team} />
                ) : (
                  <span className="mx-unknown-weapon">Оружие ?</span>
                )}
                <span>{dead ? "Выбыл" : hp != null ? hp + " HP" : "HP ?"}</span>
              </div>
              <div
                className={"mx-hp" + (hp == null ? " unknown" : "")}
                role={hp == null ? "img" : "meter"}
                aria-valuenow={hp}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-label={"Здоровье · " + row.name}
              >
                {hp != null && <i style={{ width: hp + "%" }} />}
              </div>
              {known ? (
                <div className="mx-live-utility">
                  <Gear
                    a={a}
                    dead={dead}
                    carrier={m!.bomb?.carrier === row.id}
                  />
                </div>
              ) : (
                <div className="mx-knowledge-hint">
                  {dead ? "Устранение подтверждено" : "Экипировка неизвестна"}
                </div>
              )}
              <small>
                {a?.cash != null ? money(a.cash) : "Экономика неизвестна"}
              </small>
            </div>
            <b className="mx-kd">
              <span>{row.k}</span>
              <small>{row.d}</small>
            </b>
          </button>
        );
      })}
    </div>
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
  const [tab, setTab] = useState<(typeof tabs)[number]>("Радар");
  const [preparation, setPreparation] = useState("План на карту");
  const [focus, setFocus] = useState(false);
  const [showNames, setShowNames] = useState(true),
    [showGrenades, setShowGrenades] = useState(true);
  const [cameraControls, setCameraControls] = useState<HTMLDivElement | null>(
    null,
  );
  const [display, setDisplay] = useState<"Трансляция" | "Тренерский обзор">(
    "Трансляция",
  );
  const [selected, select] = useState<string | null>(
    () => m.stats.find((row) => row.teamId === m.coachTeamId)?.id ?? null,
  );
  const [seed, setSeed] = useState(String(world.seed));
  const [nextCall, setNextCall] = useState(m.calls[0]);
  const utilityStats = m.stats.find((row) => row.id === selected);
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
      select={select}
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
  if (m.room)
    return (
      <article className="match-center">
        <TimeoutRoom
          key={m.round}
          match={m}
          map={world.map.name}
          enabled={enabled}
          saved={frame.hasSave}
          act={act}
          openBoard={openBoard}
        />
      </article>
    );
  const awayBreak = !!m.breakOwner && !timeout;
  const ser = world.series;
  const scoreTeam = (club: MatchView["clubs"][number], rival = false) => {
    const badge = <TeamLogo name={club.name} visual={club.visual} size={48} />;
    return (
      <div
        data-team={club.id}
        data-side={club.side}
        className={"mx-score-team " + (rival ? "rival" : "own")}
      >
        {rival ? <b>{club.score}</b> : badge}
        <div>
          <strong>{club.name}</strong>
          <small>
            {club.side} · {rival ? "Соперник" : "Команда тренера"}
          </small>
        </div>
        {rival ? badge : <b>{club.score}</b>}
      </div>
    );
  };
  const tabItems =
    display === "Трансляция"
      ? ["Радар", "Статистика", "Раунды"]
      : Array.from(tabs);
  return (
    <article
      className={
        "mx-root mx-match-screen " +
        (display === "Трансляция" ? "mx-broadcast" : "mx-coach-view") +
        (focus ? " mx-focus" : "") +
        (tab === "Радар" ? " mx-radar-active" : "") +
        (m.pregame ? " mx-preparing" : "")
      }
    >
      {ser?.stage !== "finished" && (
        <>
          <header className="mx-stage-header">
            <div className="mx-stage-title">
              <span>МАТЧ-ЦЕНТР</span>
              <h1>
                {finished
                  ? "Итоги карты"
                  : m.pregame
                    ? "Подготовка карты"
                    : "Прямой эфир"}
              </h1>
            </div>
            <div className="mx-view-switch">
              <div>
                {(["Трансляция", "Тренерский обзор"] as const).map((v) => (
                  <button
                    key={v}
                    aria-pressed={display === v}
                    className={display === v ? "active" : ""}
                    onClick={() => {
                      setDisplay(v);
                      if (
                        v === "Трансляция" &&
                        (tab === "Журнал" || tab === "Составы")
                      )
                        setTab("Радар");
                    }}
                  >
                    <Icon
                      name={v === "Трансляция" ? "eye" : "tactic"}
                      size={17}
                    />
                    {v}
                  </button>
                ))}
              </div>
            </div>
            <div className="mx-stage-actions">
              <button
                className="mx-arena-toggle"
                aria-pressed={focus}
                onClick={() => {
                  setTab("Радар");
                  setFocus(!focus);
                }}
              >
                <Icon name={focus ? "close" : "tactic"} size={19} />
                <span>{focus ? "Выйти" : "Арена"}</span>
              </button>
              <details className="mx-match-options">
                <summary aria-label="Действия с эпизодом"><Icon name="save" size={16}/><span>Эпизод</span></summary>
                <div>
                  <Button disabled={!enabled} onClick={() => act("save")}>
                    Сохранить эпизод
                  </Button>
                  <Button
                    disabled={!enabled || !frame.hasSave}
                    onClick={() => act("load")}
                  >
                    Загрузить эпизод
                  </Button>
                  <Button onClick={openBoard}>Редактор тактик</Button>
                </div>
              </details>
            </div>
          </header>
          <section className="mx-broadcast-score" aria-label="Счёт матча">
            <div className="mx-score-event">
              <span>
                {ser?.tournament ||
                  (frame.careerId ? "Встреча календаря" : "Выставочная серия")}
              </span>
              <span>
                BO{ser?.bestOf || 1}
                {ser && (
                  <b> · СЕРИЯ {ser.teams.map((t) => ser.score[t]).join(":")}</b>
                )}
              </span>
              <span>
                {world.view === "full"
                  ? "Режим наблюдателя"
                  : "Командная проекция"}
              </span>
              {m.source && <small className="mx-score-source">Составы из базы · {m.source.id} / {m.source.revision}</small>}
            </div>
            {scoreTeam(coach)}
            <div className="mx-round-clock">
              <small>
                {world.map.name} · R{m.round}
              </small>
              <strong>
                {finished
                  ? "ФИНАЛ"
                  : timeout
                    ? "ПАУЗА"
                    : m.phase === "result"
                      ? "ИТОГ"
                      : clock(m.clock)}
              </strong>
              <span>
                {!frame.running && m.phase === "live"
                  ? "Пауза просмотра"
                  : phases[m.phase]}
              </span>
            </div>
            {scoreTeam(opponent, true)}
          </section>
          <div className="mx-series-strip">
            {ser ? (
              ser.order.map((v, i) => (
                <span
                  key={v.map}
                  className={ser.results.length === i ? "active" : ""}
                >
                  <b>{ser.names[v.map]}</b>
                  {ser.results[i] && (
                    <strong>
                      {ser.teams.map((t) => ser.results[i].score[t]).join(":")}
                    </strong>
                  )}
                </span>
              ))
            ) : (
              <span className="active">
                <b>{world.map.name}</b>
              </span>
            )}
            <b>Лимит перерывов · {m.timeoutLimit}</b>
          </div>
        </>
      )}
      {ser && (finished || ser.stage === "finished") && (
        <SeriesScore frame={frame} enabled={enabled} act={act} />
      )}
      {m.phase === "planted" && (
        <div className="arena-event">
          C4 установлена{m.bomb?.site && " · " + m.bomb.site}
        </div>
      )}
      {m.phase === "result" && m.history.length > 0 && (
        <div className="arena-event">
          {clubName(m.history.at(-1)!.winnerTeamId)} ·{" "}
          {m.history.at(-1)!.reason}
        </div>
      )}
      {m.phase === "freeze" &&
        m.round > 1 &&
        m.history.at(-1)?.side &&
        (() => {
          const previous = m.history.at(-1)!;
          const winner = m.clubs.find((c) => c.id === previous.winnerTeamId);
          return winner && winner.side !== previous.side ? (
            <div className="arena-event">
              Смена сторон · {coach.name} начинает за {coach.side}
            </div>
          ) : null;
        })()}
      {world.view === "full" &&
        ["live", "planted"].includes(m.phase) &&
        m.clubs.map((club) => {
          const alive = world.agents.filter(
            (a) => a.team === club.side && a.alive,
          );
          const opponents = world.agents.filter(
            (a) => a.team !== club.side && a.alive,
          ).length;
          return alive.length === 1 && opponents > 1 ? (
            <div className="arena-event" key={club.id}>
              Клатч · {name(alive[0].id)} · 1 против {opponents}
            </div>
          ) : null;
        })}
      {awayBreak && (
        <p className="match-result">
          {clubName(m.breakOwner!)} · Тактический перерыв · {clock(m.clock)}
        </p>
      )}
      {finished && (
        <p className="match-result">
          Победитель {world.series ? "карты" : "матча"} —{" "}
          <strong>{clubName(m.winnerTeamId!)}</strong>
          {m.award && (
            <>
              {" "}
              · MVP карты <strong>{m.award.name}</strong>
            </>
          )}
        </p>
      )}
      {m.pregame && !finished && (
        <section className="mx-pregame">
          <div>
            <Badge tone="orange">
              До начала карты · {m.clubs.map((c) => c.score).join(":")}
            </Badge>
            <h2>
              {world.map.name.toUpperCase()} · СТАРТ ЗА {coach.side}
            </h2>
            <p>Проверьте пятёрку и выберите план до первого раунда.</p>
            <div className="mx-button-row">
              <Button
                variant="primary"
                disabled={!enabled || frame.running}
                onClick={() => act("start")}
              >
                <Icon name="play" />
                Начать первый раунд
              </Button>
            </div>
          </div>
          <div>
            <ApprovedTabs
              items={["План на карту", "Пятёрка", "Закупка"]}
              value={preparation}
              onChange={setPreparation}
            />
            {preparation === "План на карту" ? (
              <>
                {m.prepared.length ? (
                  m.prepared.map((p) => (
                    <p key={p.side + p.buy}>
                      {p.side} · {p.name} · в{p.revision}
                    </p>
                  ))
                ) : (
                  <p>Готовый план на эту карту пока не назначен.</p>
                )}
                {!ser?.spectator && (
                  <Button onClick={openBoard}>Выбрать тактику</Button>
                )}
              </>
            ) : preparation === "Пятёрка" ? (
              <p>
                {m.stats
                  .filter((p) => p.teamId === coach.id)
                  .map((p) => p.name)
                  .join(" · ")}
              </p>
            ) : (
              <p>
                {m.nextBuy || "Закупку определяет капитан"} · {coach.side}
              </p>
            )}
          </div>
        </section>
      )}
      <div className="mx-playback">
        <div className="mx-button-row">
          <Button
            variant="primary"
            aria-label={frame.running ? "Пауза просмотра" : "Запустить"}
            disabled={!enabled || finished || timeout}
            onClick={() => act(frame.running ? "pause" : "start")}
          >
            <Icon name={frame.running ? "pause" : "play"} size={17} />
            {frame.running ? "Пауза" : "Смотреть"}
          </Button>
          <div className="mx-speed" aria-label="Скорость просмотра">
            {[1, 2, 4, 8, 128].map((n) => (
              <button
                key={n}
                disabled={!enabled}
                className={frame.speed === n ? "active" : ""}
                aria-pressed={frame.speed === n}
                onClick={() => act("speed", n)}
              >
                {n === 128 ? "Быстро" : n + "×"}
              </button>
            ))}
          </div>
        </div>
        <span className="mx-permission-note">
          {awayBreak
            ? "Перерыв соперника"
            : m.pending
              ? "Запрос ожидает границы раунда"
              : m.pregame
                ? "Решения доступны до старта карты"
                : "Управление планом — в свой перерыв"}
        </span>
        <Button
          className="mx-timeout-request"
          disabled={
            !enabled ||
            finished ||
            awayBreak ||
            timeout ||
            m.pending ||
            m.remaining === 0 ||
            ser?.spectator
          }
          onClick={() => act("timeout")}
        >
          {m.pending ? "Тайм-аут запрошен" : "Тайм-аут"} · {m.remaining}/
          {m.timeoutLimit}
        </Button>
      </div>
      <div className="mx-match-tabs">
        <ApprovedTabs
          items={tabItems}
          value={tab}
          onChange={(v) => setTab(v as typeof tab)}
        />
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
      <div className="mx-arena" hidden={tab !== "Радар"}>
        {roster(coach)}
        <div className="mx-center-radar">
          <section className="mx-radar">
            <div className="mx-radar-top">
              <strong>{world.map.name.toUpperCase()}</strong>
              <div className="mx-button-row" ref={setCameraControls} />
            </div>
            {m.phase === "planted" && (
              <div className="hud-bomb">
                <strong>
                  <ItemIcon name="C4" /> · {m.bomb?.site || "Установлена"}
                </strong>
                <span>
                  {m.action?.kind === "defuse" ? "Обезвреживание" : "До взрыва"}{" "}
                  · {clock(m.clock)}
                </span>
                <progress
                  aria-label="Время до взрыва"
                  value={m.clock}
                  max={400}
                />
              </div>
            )}
            <div className="radar-broadcast mx-radar-viewport">
              <Radar
                controlsHost={cameraControls}
                showNames={showNames}
                showGrenades={showGrenades}
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
            <div className="mx-radar-bottom">
              <label>
                <input
                  type="checkbox"
                  checked={showNames}
                  onChange={(e) => setShowNames(e.target.checked)}
                />{" "}
                Имена
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={showGrenades}
                  onChange={(e) => setShowGrenades(e.target.checked)}
                />{" "}
                Гранаты
              </label>
              <span>Перетаскивание — обзор · два пальца — масштаб</span>
            </div>
          </section>
        </div>
        {roster(opponent)}
      </div>
      {rounds > 0 && (
        <div className="mx-round-timeline" aria-label="Последние раунды">
          {m.history.slice(-12).map((r) => (
            <button
              className={r.winnerTeamId === coach.id ? "won" : "lost"}
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

      {tab === "Радар" && (
        <>
          <div className="mx-below-radar">
            <div className="mx-radio-card">
              <span className="mx-eyebrow">КОМАНДНОЕ РАДИО · {coach.name}</span>
              <h3>
                {m.radio?.length
                  ? name(m.radio[0].player) +
                    " · " +
                    (radioStates[m.radio[0].state] || "Обновил статус задачи")
                  : "Передач пока нет"}
              </h3>
              <span>Подтверждённые сообщения пятёрки</span>
              <Button
                onClick={() => {
                  setDisplay("Тренерский обзор");
                  setTab("Журнал");
                }}
              >
                Журнал матча
              </Button>
            </div>
            <div className="mx-current-order">
              <span className="mx-eyebrow">УСТАНОВКА ТРЕНЕРА</span>
              <h3>
                {m.call ||
                  m.plans[coach.side]?.tactic?.name ||
                  "Решение капитана"}
              </h3>
              <p>
                {m.pending
                  ? "Запрос перерыва передан"
                  : m.pregame
                    ? "До начала карты доступен выбор тактики"
                    : "Указания доступны в собственный перерыв"}
              </p>
            </div>
          </div>
        </>
      )}
      {display === "Тренерский обзор" && (
        <div className="arena-bench">
          <section className="surface panel-body">
            <h2>Состояние пятёрки</h2>
            {Object.entries(m.impressions || {}).map(([id, state]) => (
              <p key={id}>
                <strong>{name(id)}</strong> · {state}
              </p>
            ))}
            {!Object.keys(m.impressions || {}).length && (
              <p>В этой проекции наблюдения своего штаба недоступны.</p>
            )}
          </section>
          <section className="surface panel-body">
            <h2>Командное радио</h2>
            {m.radio?.map((r) => (
              <p key={r.player + r.channel}>
                <strong>{name(r.player)}</strong> ·{" "}
                {radioStates[r.state] || "Обновил статус задачи"} ·{" "}
                {clock(r.tick)}
              </p>
            ))}
            {!m.radio?.length && <p>Подтверждённых передач пока нет.</p>}
          </section>
        </div>
      )}
      {(tab === "Радар" || tab === "Составы") && utilityStats && (
        <div className="mx-player-detail">
          <Portrait
            size="large"
            id={selectedAgent?.playerId || utilityStats.id}
            name={utilityStats.name}
            visual={utilityStats.visual}
          />
          <div>
            <Badge
              tone={utilityStats.teamId === coach.id ? "green" : "neutral"}
            >
              {utilityStats.teamId === coach.id
                ? "Своя команда"
                : "Публичные наблюдения"}
            </Badge>
            <h3>{utilityStats.name}</h3>
            <p>
              {utilityStats.role} · {clubName(utilityStats.teamId)}
            </p>
            {selectedAgent ? (
              <div className="inventory">
                <b>{selectedAgent.name}</b> · {selectedAgent.status}
                {m.roleRatings[selectedAgent.id] && (
                  <RoleRatings
                    values={m.roleRatings[selectedAgent.id]}
                    compact
                  />
                )}
                {utilityStats?.flashesThrown !== undefined && (
                  <small>
                    Флешки {utilityStats.flashesThrown} · ослеплено противников{" "}
                    {utilityStats.enemiesFlashed}, союзников{" "}
                    {utilityStats.alliesFlashed}, себя{" "}
                    {utilityStats.selfFlashes} · зрение противников снижено{" "}
                    {((utilityStats.enemyBlindTicks ?? 0) / 10).toFixed(1)} с ·
                    флеш-ассисты {utilityStats.flashAssists}
                    <br />
                    Урон HE {utilityStats.heDamage} · огонь{" "}
                    {utilityStats.fireDamage} · потушено очагов{" "}
                    {utilityStats.firesQuenched} · услышано ложных выстрелов{" "}
                    {utilityStats.decoyHearings}
                  </small>
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
            ) : (
              <p>Инвентарь и состояние игрока в этой проекции неизвестны.</p>
            )}
          </div>
        </div>
      )}
      <div className="match-grid">
        <div className="match-main">
          <section className="panel match-data" hidden={tab === "Радар"}>
            {tab === "Статистика" && ser && !finished && (
              <SeriesScore frame={frame} enabled={enabled} act={act} />
            )}
            {tab === "Составы" && !utilityStats && (
              <p className="inventory">
                Выберите игрока на радаре или в пятёрке команды, чтобы открыть
                его роль и снаряжение.
              </p>
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
            {timeout && <button onClick={openBoard}>Выбрать тактику</button>}
            {!timeout ? (
              <button
                disabled={
                  !enabled ||
                  finished ||
                  awayBreak ||
                  m.pending ||
                  m.remaining === 0
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
