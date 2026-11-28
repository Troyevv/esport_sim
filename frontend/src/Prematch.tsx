import { useCareerViewTab } from "./CareerViewTab";
import { FixtureTeams, EntityName } from "./CareerIdentity";
import { RecentForm } from "./RecentForm";
import { useState } from "react";
import { Avatar, LineupPortrait } from "./SceneIdentity";
import { Icon, Badge, Button, Panel, Tabs, Meter } from "./approved/Shared";
import { serverURL } from "./session";
import { Portrait, TeamLogo } from "./approved/Identity";
import "./approved/Competition.css";
import { ForecastLine, type Quote } from "./ForecastLine";
import {
  date,
  fixtureMap,
  useData,
  type Career,
  type Fixture,
  type Profile,
  type Scene,
} from "./careerData";
import "./prematch.css";

type Past = {
  id: string;
  date: string;
  teams: string[];
  score: number[];
  winnerTeamId: string;
};
type Club = {
  players: string[];
  version: number | null;
  rank: number | null;
  points: number | null;
  recent: Past[];
  publicRatings: {
    player: string;
    rating: number;
    maps: number;
    source: string;
  }[];
};
type Prep = {
  day: string;
  clubs: Record<string, Club>;
  publication: string | null;
  h2h: Past[];
  evidence: Record<
    string,
    Record<string, { games: number; wins: number; picks: number; bans: number }>
  >;
  mapProbabilities: Record<string, number>;
  advice: {
    author: string;
    minimum: number;
    strongest: string | null;
    weakest: string | null;
  } | null;
  staff: { duty: string; name: string; due: string }[];
  forecasts: Quote[];
  calibration: { count: number; brier: number | null };
};
const tabs = [
  "План на серию",
  "Состав и готовность",
  "Соперник",
  "Маппул",
  "Сравнение",
  "Прогнозы",
];
export default function Prematch({
  c,
  scene,
  event,
  revision,
  open,
  calendar,
  tournament,
  prepareBoard,
  play,
}: {
  c: Career;
  scene: Scene;
  event: Fixture;
  revision: number;
  open: (p: Profile) => void;
  calendar: (d: string) => void;
  tournament: (id: string) => void;
  prepareBoard: (map: string, side: "CT" | "T") => void;
  play?: () => void;
}) {
  const [tab, setTab] = useCareerViewTab(tabs[0]);
  const [chosenMap, setChosenMap] = useState("");
  const [planSide, setPlanSide] = useState<"CT" | "T">("T");
  const request = useData<Prep>(
    "/api/career/" + c.id + "/prematch/" + event.id,
    revision,
  );
  if (request.error)
    return (
      <p role="alert">
        {request.error} <button onClick={request.reload}>Повторить</button>
      </p>
    );
  if (!request.data)
    return <p role="status">Загружаем предматчевую подготовку…</p>;
  const data = request.data;
  const teams = event.teams.includes(c.team)
    ? [c.team, event.teams.find((t) => t !== c.team)!]
    : event.teams;
  const name = (id: string) => scene.teams[id]?.name || c.teams[id] || id;
  const mapName = (key: string) =>
    fixtureMap({ ...event, mapId: key, bestOf: undefined });
  const results = (rows: Past[]) =>
    rows.length ? (
      rows.map((r) => (
        <div key={r.id} className="prep-result"><time>{date(r.date)}</time>
          <FixtureTeams teams={r.teams} names={c.teams}/><b>{r.score?.join(" : ") ?? "—"}</b></div>
      ))
    ) : (
      <p>Завершённых встреч в доступной истории нет.</p>
    );
  const lineup = (tid: string) => (
    <section key={tid} className="surface panel-body">
      <h2><EntityName group="teams" id={tid} fallback={name(tid)}/></h2>
      <small>
        {data.clubs[tid].version
          ? "Турнирная заявка · версия " + data.clubs[tid].version
          : "Пятёрка редакции карьеры"}
      </small>
      {data.clubs[tid].players.map((pid) => {
        const p = scene.players[pid],
          own = c.roster.find((r) => r.id === pid);
        const rating = data.clubs[tid].publicRatings.find(
          (r) => r.player === pid,
        );
        return (
          <button
            className="entity-button"
            key={pid}
            onClick={() => open({ group: "players", id: pid })}
          >
            {p && <LineupPortrait id={pid} name={p.name} visual={p.visual} />}
            <span>
              <strong>{p?.name || pid}</strong>
              <small>
                {own
                  ? "Форма " +
                    own.form +
                    " · готовность " +
                    (100 - own.fatigue) +
                    "%"
                  : rating
                    ? "Публичный рейтинг " +
                      rating.rating.toFixed(2) +
                      " · карт " +
                      rating.maps
                    : "Публичной оценки нет"}
              </small>
            </span>
          </button>
        );
      })}
    </section>
  );
  const rival = teams[1],
    maps = Object.keys(data.mapProbabilities);
  const ranked = maps
    .map((m) => ({ m, ...data.evidence[rival][m] }))
    .filter((r) => r.games > 0)
    .sort(
      (a, b) => (b.wins + 2) / (b.games + 4) - (a.wins + 2) / (a.games + 4),
    );
  const quote = data.forecasts.at(-1);
  const planMap = maps.includes(chosenMap)
    ? chosenMap
    : data.advice?.weakest || maps[0];
  const teamHero = (t: string, opposing = false) => {
    const logo = (
      <TeamLogo name={name(t)} size={90} visual={scene.teams[t]?.visual} />
    );
    return (
      <div className={"cp-prematch-team" + (opposing ? " cp-opponent" : "")}>
        {!opposing && logo}
        <div>
          <span>
            {t === c.team
              ? "ВАША КОМАНДА"
              : teams.includes(c.team)
                ? "СОПЕРНИК"
                : "УЧАСТНИК"}
          </span>
          <h1><button className="hero-profile-action" onClick={()=>open({group:"teams",id:t})}>{name(t)}</button></h1>
          <p>
            VRS {data.clubs[t].rank ? "#" + data.clubs[t].rank : "—"} ·{" "}
            {data.clubs[t].recent.length ? <RecentForm results={data.clubs[t].recent.slice(0,5).reverse().map(r=>({
              id:r.id, won:r.winnerTeamId===t, detail:date(r.date)+" · "+r.teams.map(name).join(" — ")+" · "+r.score.join(" : ")
            }))}/> : "Истории пока нет"}
          </p>
        </div>
        {opposing && logo}
      </div>
    );
  };
  const first = teams[0],
    ownLineup = data.clubs[first];
  const coach = Object.values(scene.staff).find(
    (s) =>
      s.team === c.team &&
      (s.name === data.advice?.author || s.role === "coach"),
  );
  const tired =
    first === c.team
      ? [...c.roster].sort((a, b) => b.fatigue - a.fatigue)[0]
      : undefined;
  return (
    <div className="cp-module">
      <button
        className="cp-back"
        onClick={() =>
          event.edition ? tournament(event.edition) : calendar(event.date)
        }
      >
        <Icon name="back" />
        {event.title || "Календарь"}
      </button>
      <div className="cp-prematch-hero">
        {teamHero(first)}
        <div className="cp-versus">
          <Badge>BO{event.bestOf || 1} · MR12</Badge>
          <b>VS</b>
          <span>{date(event.date)}</span>
        </div>
        {teamHero(rival, true)}
      </div>
      <div className="cp-prematch-toolbar">
        <div>
          <Badge>{event.edition ? "Турнирная серия" : "Матч календаря"}</Badge>
          <span>
            Указания тренера доступны в собственный разрешённый перерыв
          </span>
        </div>
        {play ? (
          <Button variant="primary" onClick={play}>
            {event.bestOf ? "Подтвердить и перейти к veto" : "В матч-центр"}
          </Button>
        ) : (
          <Button onClick={() => calendar(event.date)}>
            Открыть календарь
          </Button>
        )}
      </div>
      <Tabs items={tabs} value={tab} onChange={setTab} />
      {tab === tabs[0] && (
        <>
          <div className="cp-two-col">
            <Panel
              title="Рекомендация штаба"
              action={
                coach ? (
                  <Button
                    onClick={() => open({ group: "staff", id: coach.id })}
                  >
                    {coach.name}
                  </Button>
                ) : (
                  data.advice && <Badge>{data.advice.author}</Badge>
                )
              }
            >
              <Badge tone={ranked.length ? "green" : "neutral"}>
                {ranked.length ? "Наблюдаемая статистика" : "Сбор данных"}
              </Badge>
              <h2>
                {data.advice?.strongest
                  ? "Подготовить ответ на " + mapName(data.advice.strongest)
                  : "Разбор маппула " + name(rival)}
              </h2>
              <p>
                {ranked.length
                  ? name(rival) +
                    " выиграли " +
                    ranked[0].wins +
                    " из " +
                    ranked[0].games +
                    " на " +
                    mapName(ranked[0].m) +
                    "."
                  : "В доступных протоколах пока нет сыгранных карт соперника."}
              </p>
              <p className="cp-sample">
                Данные на {date(data.day)} ·{" "}
                {ranked.reduce((n, r) => n + r.games, 0)} карт
              </p>
              <div className="cp-actions">
                <Button onClick={() => setTab(tabs[3])}>Сравнить карты</Button>
                <Button onClick={() => setTab(tabs[2])}>
                  Отчёт о сопернике
                </Button>
              </div>
              <div className="cp-observation">
                <h3>Подготовка veto</h3>
                <p>
                  {data.advice?.weakest
                    ? "Кандидат для своего пика · " +
                      mapName(data.advice.weakest)
                    : "Для рекомендации по пику пока недостаточно наблюдений."}
                </p>
              </div>
            </Panel>
            <Panel title="Перед выходом на сервер">
              <div className="cp-task-row">
                <Badge
                  tone={tired && tired.fatigue > 70 ? "orange" : "neutral"}
                >
                  {tired && tired.fatigue > 70 ? "Внимание" : "Состав"}
                </Badge>
                <div>
                  <strong>
                    {tired && tired.fatigue > 70
                      ? "Проверить готовность " + tired.name
                      : "Стартовая пятёрка"}
                  </strong>
                  <p>
                    {tired && tired.fatigue > 70
                      ? "Готовность " +
                        Math.round(100 - tired.fatigue) +
                        "%. Штабу доступны показатели нагрузки своего состава."
                      : ownLineup.players
                          .map((id) => scene.players[id]?.name || id)
                          .join(" · ")}
                  </p>
                  <Button onClick={() => setTab(tabs[1])}>
                    Проверить состав
                  </Button>
                </div>
              </div>
              <div className="cp-task-row">
                <Badge tone={ownLineup.version ? "green" : "orange"}>
                  Допуск
                </Badge>
                <div>
                  <strong>
                    {ownLineup.version
                      ? "Пятёрка зарегистрирована"
                      : "Состав редакции карьеры"}
                  </strong>
                  <p>
                    {ownLineup.version
                      ? "Версия заявки " + ownLineup.version
                      : event.title}
                  </p>
                  {event.edition && (
                    <Button onClick={() => tournament(event.edition!)}>
                      Проверить турнир
                    </Button>
                  )}
                </div>
              </div>
            </Panel>
          </div>
          <div className="cp-two-col">
            <Panel title="Стартовый план">
              <label className="field">
                <span>Карта для подготовки тактики</span>
                <select
                  value={planMap || ""}
                  onChange={(e) => setChosenMap(e.target.value)}
                >
                  {maps.map((m) => (
                    <option value={m} key={m}>
                      {mapName(m)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Сторона для разбора</span>
                <select
                  value={planSide}
                  onChange={(e) => setPlanSide(e.target.value as "CT" | "T")}
                >
                  <option value="T">Атака · T</option>
                  <option value="CT">Защита · CT</option>
                </select>
              </label>
              {data.staff.map((s) => (
                <p key={s.duty}>
                  {s.name} · {date(s.due)}
                </p>
              ))}
              {first === c.team && (
                <Button
                  disabled={!planMap}
                  onClick={() => prepareBoard(planMap, planSide)}
                >
                  Открыть тактическую доску
                </Button>
              )}
            </Panel>
            <Panel
              title="Виртуальная линия"
              className="cp-odds"
              action={<Button onClick={() => setTab(tabs[5])}>Методика</Button>}
            >
              {quote ? (
                <>
                  <div className="cp-odds-top">
                    <div>
                      <Badge>
                        {quote.stage === "opening"
                          ? "До veto"
                          : "После хода veto"}
                      </Badge>
                      <p>
                        {date(quote.date)} · BO{quote.bestOf} · {quote.version}
                      </p>
                    </div>
                  </div>
                  <div className="cp-odds-main">
                    {quote.teams.map((t, i) => (
                      <div key={t}>
                        <TeamLogo
                          name={name(t)}
                          visual={scene.teams[t]?.visual}
                        />
                        <b>{Math.round(quote.probability[i] * 100)}%</b>
                        <span>
                          {name(t)} · <em>{quote.odds[i].toFixed(2)}</em>
                        </span>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <p>Датированная линия отсутствует.</p>
              )}
            </Panel>
          </div>
        </>
      )}
      {tab === tabs[1] && (
        <>
          <div className="cp-split">
            <h2>Пятёрка на серию</h2>
            <Badge>
              {ownLineup.version
                ? "Заявка · версия " + ownLineup.version
                : "Состав редакции"}
            </Badge>
          </div>
          <div className="cp-lineup">
            {ownLineup.players.map((pid) => {
              const p = scene.players[pid],
                own = c.roster.find((r) => r.id === pid);
              return (
                <article key={pid}>
                  <button className="lineup-profile-action" aria-label={"Профиль · "+(p?.name || pid)} onClick={()=>open({group:"players",id:pid})}><Portrait
                    id={pid}
                    name={p?.name || pid}
                    visual={p?.visual}
                    size="large"
                  />
                  </button><h3>{p?.name || pid}</h3>
                  <Meter
                    value={own ? Math.round(100 - own.fatigue) : null}
                    label="Готовность"
                  />
                  <dl className="cp-definition">
                    <div>
                      <dt>Форма</dt>
                      <dd>{own?.form ?? "—"}</dd>
                    </div>
                    <div>
                      <dt>Состояние</dt>
                      <dd>{own ? own.morale + "/100" : "Недоступно"}</dd>
                    </div>
                    <div>
                      <dt>Допуск</dt>
                      <dd>
                        {ownLineup.version
                          ? "Зарегистрирован"
                          : "Состав редакции"}
                      </dd>
                    </div>
                  </dl>
                  <Button onClick={() => open({ group: "players", id: pid })}>
                    Профиль
                  </Button>
                </article>
              );
            })}
          </div>
        </>
      )}
      {tab === tabs[2] && (
        <div className="cp-two-col">
          {lineup(rival)}
          <section className="surface panel-body">
            <h2>Последние результаты соперника</h2>
            {results(data.clubs[rival].recent)}
          </section>
        </div>
      )}
      {tab === tabs[3] && (
        <>
          <div className="cp-filters">
            <Badge>Публичные результаты · по {date(data.day)}</Badge>
          </div>
          <div className="cp-map-comparison">
            {maps.map((m) => (
              <article key={m}>
                <img
                  src={serverURL("/api/maps/" + m + "/radar.png").href}
                  alt={"Радар " + mapName(m)}
                />
                <div>
                  <h3>{mapName(m)}</h3>
                </div>
                {teams.map((t, i) => {
                  const v = data.evidence[t][m],
                    rate = v.games
                      ? Math.round((100 * v.wins) / v.games)
                      : null;
                  return (
                    <div className="cp-map-rate" key={t}>
                      <span>
                        {name(t)} <b>{rate == null ? "—" : rate + "%"}</b>
                      </span>
                      <Meter value={rate} tone={i ? "orange" : "green"} />
                      <small>
                        {v.games} карт · пики {v.picks} / баны {v.bans}
                      </small>
                    </div>
                  );
                })}
              </article>
            ))}
          </div>
        </>
      )}
      {tab === tabs[4] && (
        <div className="cp-two-col">
          {teams.map((t) => (
            <section key={t} className="surface panel-body">
              <h2><EntityName group="teams" id={t} fallback={name(t)}/></h2>
              <p>
                Очки VRS · {data.clubs[t].points ?? "—"}
                {data.publication && " · " + date(data.publication)}
              </p>
              {results(data.clubs[t].recent)}
            </section>
          ))}
        </div>
      )}
      {tab === tabs[5] && (
        <ForecastLine
          quotes={data.forecasts}
          names={c.teams}
          teamLabel={id=><EntityName group="teams" id={id} fallback={name(id)}/>}
          calibration={data.calibration}
        />
      )}
    </div>
  );
}
