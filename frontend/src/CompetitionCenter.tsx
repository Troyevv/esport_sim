import {Icon,Badge,Button,Panel,Stat,Field,Tabs as ApprovedTabs} from "./approved/Shared";
import {TeamLogo} from "./approved/Identity";
import {Mark} from "./approved/EventMark";
import {serverURL} from "./session";
import "./approved/Competition.css";
import { useState } from "react";
import { date, fixtureScore, useData, type Act, type Career, type Profile, type Scene } from "./careerData";
import { Dialog, Heading, MetricStrip, Tabs } from "./GameUI";
import { Load, MatchReport } from "./CareerForms";
import { Avatar, Flag } from "./SceneIdentity";
import "./competitions.css";
import { EntityName, FixtureTeams } from "./CareerIdentity";
import { CompetitionMark, eventMark } from "./CompetitionMark";

type Entry = {
  version: number;
  players: string[];
  reserves: string[];
  coach: string | null;
  date: string;
  reason: string | null;
};
type Game = {
  slots: (string | null | [string, number])[];
  winner?: string;
  loser?: string;
  label: string;
  round: number;
  fixture?: string;
  score?: number[];
  date?: string;
  historical?: boolean;
  administrative?: boolean;
  reason?: string;
  bye?: boolean;
};
type Draw = {
  advance:number;
  outputs?:Game["slots"];
  standings: {
    team: string;
    wins: number;
    losses: number;
    roundDiff: number;
    buchholz: number;
  }[];
  teams: string[];
  format: string;
  games: Game[];
};
type Phase = {
  name: string;
  format: string;
  start: string;
  end: string;
  bestOf: number;
  advance: number;
  secondPlaceBO?: number;
  finalBO?: number;
};
type Stats = {
  name: string;
  team: string;
  k: number;
  d: number;
  a: number;
  damage: number;
  rounds: number;
};
type Edition = {
  id: string;
  title: string;
  organizer: string;
  source: string;
  place: string;
  region: string;
  prestige: number;
  opens: string;
  lock: string;
  applyBy?: string;
  replyBy?: Record<string, string>;
  clubRewards?: number[];
  bookingFee?: string;
  poolBySize?: [number, number][];
  start: string;
  end: string;
  year: number;
  ownEligible: boolean;
  conflicts: {id:string; title:string; state:string; dates:string[]}[];
  simulated: boolean;
  admission: string;
  status: string;
  capacity: number;
  modelDates?: boolean;
  modelDeadlines?: boolean;
  modelStages?: boolean;
  rules: {
    pool: string[];
    first: string;
    pickSide: string;
    deciderSide: string;
    formats: Record<string, (string | { kind: string; actor: number })[]>;
    timeouts: number;
    core: number;
    reserves: number;
    id: string;
  };
  stages: Phase[];
  draws: Draw[][];
  prizes: number[];
  entries: Record<string, string>;
  registrations: Record<string, Entry[]>;
  stats: Record<string, Stats>;
  advanced?: string[];
  placements?: string[];
  payouts?: Record<string, number>;
  mvp?: string;
  reason?: string;
  feeds?: string;
  snapshot?: string;
  seedSnapshot?: string;
};
type Ranking = {
  rank: number;
  regional: number;
  region: string;
  name: string;
  points: number;
  nicks: string[];
  team?: string;
};
type PastEdition = {
  id: string;
  name: string;
  end: string;
  winners: string[];
  pool: number;
  lan: boolean;
};
export type Directory = {
  archive: PastEdition[];
  editions: Edition[];
  available: string[];
  snapshots: Record<string, Ranking[]>;
  live?: { date: string; rows: Ranking[]; completeWindow: boolean };
};
type Props = {
  open:(p:Profile)=>void;
  onEdition?:(id:string)=>void;
  prepare:(id:string)=>void;
  initialEdition?: string;
  initialEntry?: boolean;
  initialConflict?: boolean;
  c: Career;
  scene: Scene;
  act: Act;
  enabled: boolean;
  revision: number;
  rankings: boolean;
};
const status: Record<string, string> = {
  registration: "Регистрация",
  withdrawn: "Команда снялась",
  offered: "Ожидает подтверждения",
  confirmed: "Место подтверждено",
  waiting: "Лист ожидания",
  playing: "Идёт турнир",
  finished: "Завершён",
  cancelled: "Отменён",
  invited: "Приглашение",
  accepted: "Участие подтверждено",
  locked: "Состав зафиксирован",
  declined: "Отказ",
  qualified: "Отбор пройден",
  missed: "Пропущен дедлайн",
  notSelected: "Вне списка участников",
  qualifiedElsewhere: "Уже квалифицировались",
};
function statusTone(state: string) {
  if (["playing","qualified","confirmed","accepted","locked"].includes(state)) return "green";
  if (["offered","invited","waiting","registration"].includes(state)) return "orange";
  return "neutral";
}
const formats: Record<string, string> = {
  swiss: "Швейцарская система",
  single: "Single elimination",
  double: "Double elimination",
  gsl: "Группы GSL",
  doubleGroups: "Группы Double elimination",
  roundRobin: "Круговая система",
};
const admission: Record<string, string> = {
  firstCome: "Открытая регистрация по порядку подачи",
  open: "Открытая квалификация",
  regionalInvite: "Региональные приглашения и места ESEA",
  finalsInvite: "Победители региональных кубков",
  globalInvite: "Приглашения Global VRS",
  mixedInvite: "Прямые приглашения и закрытые квалификации",
  leagueInvite: "Приглашения VRS и победители ECL",
  closedInvite: "Закрытая квалификация",
  qualified: "Победители квалификаций",
  invitation: "Приглашения VRS",
  rankedOpen: "Открытая заявка · отбор по VRS",
};
const money = (n: number) => n.toLocaleString("ru-RU") + " $";
function purse(e: Edition) {
  const sum = (values: number[]) => values.reduce((a, b) => a + b, 0);
  const total = sum(e.prizes) + sum(e.clubRewards || []);
  return (
    (e.poolBySize && e.status === "registration" ? "до " : "") + money(total)
  );
}
const span = (a: string, b: string) =>
  a === b ? date(a) : date(a) + " — " + date(b);

function Archive({ editions }: { editions: PastEdition[] }) {
  const [query, setQuery] = useState(""),
    [limit, setLimit] = useState(30);
  const filtered = editions.filter((e) =>
    [e.name, ...e.winners]
      .join(" ")
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  return (
    <section className="surface panel-body">
      <h2>До начала карьеры</h2>
      <label>
        Турнир или победитель{" "}
        <input
          type="search"
          value={query}
          onChange={(ev) => {
            setQuery(ev.target.value);
            setLimit(30);
          }}
        />
      </label>
      {filtered.slice(0, limit).map((e) => (
        <div className="tc-result" key={e.id}>
          <span className="tc-fixture-day">
            <CompetitionMark
              mark="archive"
              cycle={e.id}
              name={e.name}
              size={32}
            />
            <small>
              {date(e.end)} · {e.lan ? "LAN" : "Онлайн"}
            </small>
          </span>
          <a
            href={
              "https://liquipedia.net/counterstrike/" +
              e.id.split("/").map(encodeURIComponent).join("/")
            }
            target="_blank"
            rel="noreferrer"
          >
            {e.name}
          </a>
          <span>
            {e.winners.join(", ") || "Победитель не указан"} · {money(e.pool)}
          </span>
        </div>
      ))}
      {filtered.length > limit && (
        <button className="btn" onClick={() => setLimit(limit + 30)}>
          Показать ещё
        </button>
      )}
      <p>Источник — участники Liquipedia, CC BY-SA 3.0.</p>
    </section>
  );
}

function Rankings({ data, c, scene }: { data: Directory; c:Career; scene:Scene }) {
  const dates = Object.keys(data.snapshots).sort().reverse();
  const [publication, pick] = useState(dates[0]),
    [region, setRegion] = useState("Global"),
    [query, search] = useState("");
  const [selected,setSelected] = useState(c.team);
  const rows =
    publication === "live"
      ? data.live?.rows || []
      : data.snapshots[publication];
  const identity = (r:Ranking) => r.team || Object.keys(c.teams).find(t=>c.teams[t]===r.name) || r.name;
  const selectedRow = rows?.find(r=>identity(r)===selected);
  const past = dates.filter(d=>publication==="live" || d<=publication).flatMap(d=>{
    const row=data.snapshots[d].find(r=>identity(r)===selected);
    return row?[{date:d,points:row.points,rank:row.rank}]:[];
  });
  const maxPoints = past.reduce((max, row) => Math.max(max, row.points), 0);
  return (
    <>
      <Heading
        title="Рейтинг VRS" eyebrow="Соревновательная сцена"
        sub="Составы, очки и даты приглашений"
      />
      <div className="filter-bar">
        <label>
          Снимок{" "}
          <select value={publication} onChange={(e) => pick(e.target.value)}>
            {data.live && (
              <option value="live">
                Расчёт карьеры · {date(data.live.date)}
              </option>
            )}
            {dates.map((d) => (
              <option key={d} value={d}>
                {date(d)} · {d <= "2026-11-02" ? "Valve" : "Карьера"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Регион{" "}
          <select value={region} onChange={(e) => setRegion(e.target.value)}>
            {["Global", "Europe", "Americas", "Asia"].map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
        </label>
        <label>
          Команда{" "}
          <input
            type="search"
            value={query}
            onChange={(e) => search(e.target.value)}
          />
        </label>
      </div>
      {publication === "live" && (
        <p className="panel-body">
          Расчёт по методологии Valve с учётом матчей карьеры. Стартовая история
          — Liquipedia, CC BY-SA 3.0.
        </p>
      )}
      {publication === "live" && !data.live?.completeWindow && (
        <p className="panel-body">
          Расчёт охватывает только сыгранные в карьере соревнования. Предыстория
          за 180 дней неполна.
        </p>
      )}
      <div className="vrs-layout"><section className="surface table-wrap">
        <table className="simple-table">
          <thead>
            <tr>
              <th>Место</th>
              <th>Команда / состав</th>
              <th>Регион</th>
              <th>Очки</th>
            </tr>
          </thead>
          <tbody>
            {(rows || [])
              .filter(
                (r) =>
                  (region === "Global" || r.region === region) &&
                  r.name.toLowerCase().includes(query.toLowerCase()),
              )
              .map((r) => (
                <tr key={r.rank} data-selected={identity(r)===selected}>
                  <td>{region === "Global" ? r.rank : r.regional}</td>
                  <td>
                    <button className="vrs-team" onClick={()=>setSelected(identity(r))}><Avatar club name={r.name} {...scene.teams[identity(r)]?.visual}/>{r.name}</button>
                    <small className="tc-sub">{r.nicks.join(" · ")}</small>
                  </td>
                  <td><span className="vrs-region"><Flag value={r.region}/>{r.region}</span></td>
                  <td className="mono accent">{r.points}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section><aside className="surface vrs-trend"><h2>Динамика публикаций</h2>
        <h3><EntityName group="teams" id={selected} recordedName={selectedRow?.name} fallback={c.teams[selected]}/></h3>
        {selectedRow && <><p>Место #{selectedRow.rank} · {selectedRow.points} очков</p><small>Пятёрка на дату публикации</small><p>{selectedRow.nicks.join(" · ")}</p></>}
        {past.length ? <ol>{past.map(p=><li key={p.date}><time>{date(p.date)}</time><strong>#{p.rank}</strong><span>{p.points}</span>
          {past.length>1 && maxPoints>0 && <meter min={0} max={maxPoints} value={p.points} aria-label={"Очки VRS на "+date(p.date)}/>}</li>)}</ol>
          : <p>В доступных публикациях нет истории этой команды.</p>}
      </aside></div>
    </>
  );
}

function Registration({
  event,
  c,
  scene,
  available,
  initialConflict,
  act,
  enabled,
}: Omit<Props, "rankings" | "revision"> & {
  event: Edition;
  available: string[];
}) {
  const versions = event.registrations[c.team] || [],
    old = versions.at(-1);
  const [five, setFive] = useState(old?.players || c.roster.map((p) => p.id)),
    [res, setRes] = useState(old?.reserves || []),
    [coach, setCoach] = useState(old?.coach || ""),
    [reason, setReason] = useState(""),
    [alert, setAlert] = useState(""),
    [decision, setDecision] = useState<"calendar"|"leave"|null>(initialConflict && event.conflicts.length ? "calendar" : null);
  const state = event.entries[c.team],
    before = c.date >= event.opens && c.date < event.lock,
    locked = state === "locked" && event.status === "playing",
    allowed = event.ownEligible;
  const send = async (action: string) => {
    setAlert("");
    const ok = await act(
      "career-entry",
      {
        edition: event.id,
        action,
        players: five,
        reserves: res,
        coach: coach || null,
        reason,
        release: event.conflicts.map(r=>r.id).sort(),
      },
      setAlert,
    );
    if (ok) {setDecision(null);setAlert("Изменения сохранены.");}
  };
  const candidates =
    locked && old ? [...old.players, ...old.reserves] : available;
  const toggle = (id: string, target: "main" | "reserve") => {
    const main = five.filter((p) => p !== id),
      bench = res.filter((p) => p !== id);
    setFive(target === "main" && !five.includes(id) ? [...main, id] : main);
    setRes(target === "reserve" && !res.includes(id) ? [...bench, id] : bench);
  };
  return (
    <section className="surface panel-body tc-entry">
      <h2>Заявка · {c.club}</h2>
      <p>
        {status[state] || admission[event.admission]} · Регистрация с{" "}
        {date(event.opens)} · Приём заявок до{" "}
        {date(event.applyBy || event.lock)}
        {" · "}Фиксация {date(event.lock)}
      </p>
      {!allowed && <p>Ограничение по региону: {event.region}.</p>}
      {before && state === "offered" && (
        <button
          className="btn primary"
          disabled={!enabled}
          onClick={() => event.conflicts.length ? setDecision("calendar") : send("confirm")}
        >
          Подтвердить место до {date(event.replyBy![c.team])}
        </button>
      )}
      {before &&
        (!event.applyBy || c.date < event.applyBy) &&
        allowed &&
        (state === "invited" ||
          ((!state || state === "declined") &&
            ["open", "rankedOpen", "firstCome"].includes(event.admission))) && (
          <button
            className="btn primary"
            disabled={!enabled}
            onClick={() => event.conflicts.length ? setDecision("calendar") : send("accept")}
          >
            {state === "invited"
              ? "Принять приглашение"
              : "Заявиться на участие"}
          </button>
        )}
      {["registration","playing"].includes(event.status) && ["accepted","invited","confirmed","offered","waiting","qualified","locked"].includes(state) && (
        <button className="btn" disabled={!enabled} onClick={()=>setDecision("leave")}>
          {state==="invited" || state==="offered" ? "Отклонить приглашение" : locked ? "Снять команду с турнира" : "Отменить участие"}
        </button>
      )}
      {!!event.conflicts.length && (before || ["accepted","confirmed","qualified","locked"].includes(state)) && <button className="btn" disabled={!enabled}
        onClick={()=>setDecision("calendar")}>Разрешить конфликт календаря</button>}
      {decision && <Dialog title={decision==="calendar" ? "Конфликт календаря" : "Отказ от участия"} close={()=>setDecision(null)}>
        <div className="panel-body tc-decision">
          <h3>{event.title}</h3><p>{status[state] || "Заявка ещё не подана"} · {span(event.start,event.end)}</p>
          {decision==="calendar" ? <>
            {event.conflicts.map(row=><article key={row.id}><h3>{row.title}</h3><p>{status[row.state]} · {row.dates.map(date).join(", ")}</p>
              <small>{row.state==="locked" ? "Снятие после фиксации. Назначенные встречи завершатся техническим поражением." : "Место будет освобождено."}</small></article>)}
            <button className="btn primary" disabled={!enabled || !event.conflicts.length} onClick={()=>send("prioritise")}>
              Выбрать {event.title} и отказаться от конфликтующих турниров</button>
            <button className="btn" disabled={!enabled} onClick={()=>state && !["declined","withdrawn"].includes(state) ? send("leave") : setDecision(null)}>
              Сохранить другие обязательства</button>
          </> : <>
            <p>{locked ? "Сыгранные матчи и версии заявки сохранятся. Соперники пройдут дальше по регламенту." :
                "Место освободится для другого участника. Предыдущие версии заявки останутся в истории."}</p>
            <button className="btn primary" disabled={!enabled} onClick={()=>send("leave")}>Подтвердить отказ</button>
          </>}
          {alert && <p role="status">{alert}</p>}
        </div></Dialog>}
      {((before &&
        ["accepted", "qualified", "offered", "confirmed"].includes(state)) ||
        (locked && !!old?.reserves.length)) && (
        <>
          <div className="tc-entry-players">
            {candidates.map((p) => (
              <div key={p}>
                <strong>{scene.players[p]?.name || p}</strong>
                <button
                  className="btn sm"
                  aria-pressed={five.includes(p)}
                  onClick={() => toggle(p, "main")}
                >
                  Основа
                </button>
                <button
                  className="btn sm"
                  aria-pressed={res.includes(p)}
                  onClick={() => toggle(p, "reserve")}
                >
                  Запас
                </button>
              </div>
            ))}
          </div>
          <label>
            Тренер{" "}
            <select
              disabled={locked}
              value={coach}
              onChange={(e) => setCoach(e.target.value)}
            >
              <option value="">Без тренера</option>
              {Object.values(scene.staff)
                .filter((s) => s.team === c.team)
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </label>
          {locked && (
            <label>
              Основание экстренной замены{" "}
              <input
                value={reason}
                maxLength={240}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          )}
          <p>
            Основа {five.length}/5 · Запас {res.length}/{event.rules.reserves}
          </p>
          <button
            className="btn primary"
            disabled={
              !enabled ||
              five.length !== 5 ||
              res.length > event.rules.reserves ||
              (locked && !reason.trim())
            }
            onClick={() => send(locked ? "replace" : "submit")}
          >
            {locked ? "Подать экстренную замену" : "Сохранить заявку"}
          </button>
        </>
      )}
      {locked &&
        old?.players.some((p) => !available.includes(p)) &&
        c.queue[0]?.edition === event.id &&
        c.queue[0]?.date === c.date && (
          <button
            className="btn"
            disabled={!enabled}
            onClick={() => send("withdraw")}
          >
            Сняться с матча из-за недоступного состава
          </button>
        )}
      {versions.map((v) => (
        <p key={v.version}>
          <b>Версия {v.version}</b> · {date(v.date)} ·{" "}
          {v.players.map((p) => scene.players[p]?.name).join(", ")}{" "}
          {v.reason && " · " + v.reason}
        </p>
      ))}
      {alert && <p role="status">{alert}</p>}
    </section>
  );
}

type DrawProps = Pick<Props, "c" | "scene"> & { onFixture: (id: string) => void };

function resolveSlot(draw: Draw, slot: Game["slots"][number]) {
  if (!Array.isArray(slot)) return slot;
  const parent = draw.games[slot[1]];
  return slot[0] === "winner" ? parent?.winner : parent?.loser;
}

function GameDraw({ draw, c, scene, onFixture }: DrawProps & { draw: Draw }) {
  const [focusTeam, setFocusTeam] = useState(draw.teams.includes(c.team) ? c.team : "");
  const [branch, setBranch] = useState("Верхняя сетка");
  const [filter, setFilter] = useState("all");
  function slotName(slot: Game["slots"][number]) {
    const id = resolveSlot(draw,slot);
    if (id) return c.teams[id] || scene.teams[id]?.name || id;
    if (!Array.isArray(slot)) return "Свободный слот";
    return (slot[0] === "winner" ? "Победитель" : "Проигравший") + " № " + (slot[1] + 1);
  }
  const indexed = draw.games.map((game, index) => ({ game, index }));
  const branches = draw.format === "double" ? [...new Set(draw.games.map(g => g.label))] : [];
  const activeBranch = branches.includes(branch) ? branch : branches[0];
  const games = indexed.filter(({game}) => !activeBranch || game.label === activeBranch);
  const rounds = [...new Set(games.map(({game}) => game.round))].sort((a,b) => a-b);
  const next = new Map<number,string[]>();
  for (const { game, index } of indexed) {
    for (const slot of game.slots) {
      if (!Array.isArray(slot)) continue;
      const destinations = next.get(slot[1]) || [];
      destinations.push((slot[0] === "winner" ? "Победа" : "Поражение") + " → № " + (index+1));
      next.set(slot[1], destinations);
    }
  }
  const fixtures = new Set([...c.history, ...c.queue].map(f => f.id));
  return <section className="tournament-draw">
    <div className="draw-toolbar">
      <label>Выделить путь<select value={focusTeam} onChange={e => setFocusTeam(e.target.value)}>
        <option value="">Все команды</option>
        {draw.teams.map(id => <option key={id} value={id}>{c.teams[id] || id}</option>)}
      </select></label>
      <label>Раунды<select value={filter} onChange={e => setFilter(e.target.value)}>
        <option value="all">Вся сетка</option>
        {rounds.map(r => <option key={r} value={r}>Раунд {r + 1}</option>)}
      </select></label>
    </div>
    <div className="draw-context"><b>{draw.teams.length} команд</b><span>Проходят дальше · {draw.advance}</span>
      {draw.teams.includes(c.team) && <span>Ваша команда · {c.club}</span>}</div>
    {!!branches.length && <Tabs items={branches} value={activeBranch} change={value => {setBranch(value); setFilter("all");}}/>}
    {(draw.format === "swiss" || draw.format === "roundRobin") && <div className="tc-standings" tabIndex={0} role="region" aria-label="Таблица группы">
      <table className="simple-table"><thead><tr><th>Место</th><th>Команда</th><th>В</th><th>П</th>
        <th>{draw.format === "swiss" ? "Бухгольц" : "± раундов"}</th></tr></thead>
        <tbody>{draw.standings.map((row,index) => <tr key={row.team} data-focused={row.team === focusTeam}>
          <td>{index + 1}</td><td><EntityName group="teams" id={row.team} fallback={c.teams[row.team]}/></td>
          <td>{row.wins}</td><td>{row.losses}</td><td>{draw.format === "swiss" ? row.buchholz : row.roundDiff}</td>
        </tr>)}</tbody></table>
    </div>}
    <div className="tc-bracket" role="region" aria-label="Сетка по раундам" tabIndex={0}>
      {rounds.filter(r => filter === "all" || String(r) === filter).map(r => <section key={r} className="tc-round">
        <h3>Раунд {r + 1}</h3>
        {games.filter(({game}) => game.round === r).map(({ game, index }) =>
          <article className="tc-pair" key={index} data-focused={!!focusTeam && game.slots.some(s => resolveSlot(draw,s) === focusTeam)}>
            <small>{game.label} · № {index + 1}{game.date && " · " + date(game.date)}</small>
            {game.slots.map((slot,i) => {
              const id = resolveSlot(draw,slot);
              return <div key={i} className={id && id === game.winner ? "tc-winner" : ""}>
                {id ? <EntityName group="teams" id={id} fallback={slotName(slot)}/> : <b>{slotName(slot)}</b>}<span>{game.score?.[i] ?? "—"}</span>
              </div>;
            })}
            {game.bye && <small>Проход без игры</small>}
            {game.administrative && <small>{game.reason || "Технический результат"}</small>}
            {game.historical && <small>До начала карьеры</small>}
            {next.has(index) && <small className="draw-path">{next.get(index)!.join(" · ")}</small>}
            {game.fixture && fixtures.has(game.fixture) && <button className="link-button" onClick={() => onFixture(game.fixture!)}>
              {game.score ? "Протокол встречи" : "Подготовка и линия"}
            </button>}
          </article>)}
      </section>)}
    </div>
    {draw.outputs && <p>Выход из стадии · {draw.outputs.map(slotName).join(" · ")}</p>}
  </section>;
}

function TournamentStage({ phase, draws, ...props }: DrawProps & { phase: Phase; draws: Draw[] }) {
  const [group, setGroup] = useState(Math.max(0, draws.findIndex(draw => draw.teams.includes(props.c.team))));
  const active = draws[group] || draws[0];
  if (!active) return null;
  return <section className="surface panel-body tc-stage">
    <h2>{phase.name}</h2>
    <p>{formats[phase.format]} · BO{phase.bestOf} · {date(phase.start)} — {date(phase.end)}</p>
    {draws.length > 1 && <label className="draw-group">Группа<select value={draws.indexOf(active)} onChange={e => setGroup(Number(e.target.value))}>
      {draws.map((draw,index) => <option key={index} value={index}>Группа {index + 1} · {draw.teams.length} команд</option>)}
    </select></label>}
    <GameDraw key={group} draw={active} {...props}/>
  </section>;
}

export function CompetitionCenter(props: Props) {
  const { c, scene, enabled, revision, rankings } = props;
  const res = useData<Directory>(
    "/api/career/" + c.id + "/competitions",
    revision,
  );
  const [picked, select] = useState(props.initialEdition || ""),
    [tab, show] = useState(props.initialEntry ? "Моя заявка" : "Обзор"),
    [archive, setArchive] = useState(false);
  const [report, openReport] = useState("");
  const [rulesOpen, setRulesOpen] = useState(false);
  const [mapDetail, setMapDetail] = useState("");
  const [participantQuery, setParticipantQuery] = useState("");
  const [region, filterRegion] = useState("Все регионы"),
    [search, filterName] = useState(""),
    [period, setPeriod] = useState(""),
    [own, onlyOwn] = useState(false);
  if (res.error || !res.data) return <Load {...res} />;
  const data = res.data,
    event = data.editions.find((e) => e.id === picked);
  if (rankings) return <Rankings {...{ data, c, scene }} />;
  if (!event)
    return (
      <>
        <Heading
          title="Соревнования"
          eyebrow={"Сезон " + c.date.slice(0, 4)}
          sub="Календарь, турнирные этапы и участие команды"
        />
        <MetricStrip
          items={[
            ["Соревнования", data.editions.length, "В календаре карьеры"],
            [
              "Участие команды",
              data.editions.filter((e) =>
                [
                  "confirmed",
                  "locked",
                  "accepted",
                  "playing",
                  "qualified",
                ].includes(e.entries[c.team]),
              ).length,
              c.club,
            ],
            [
              "Регистрация",
              data.editions.filter((e) => e.status === "registration").length,
              "Открытые соревнования",
            ],
            [
              "Форматы",
              new Set(
                data.editions.flatMap((e) => e.stages.map((s) => s.format)),
              ).size,
              "Включены в календарь",
            ],
          ]}
        />
        <Tabs
          items={["Календарь турниров", "Архив"]}
          value={archive ? "Архив" : "Календарь турниров"}
          change={(s) => setArchive(s === "Архив")}
        />
        {!archive && (
          <div className="filter-bar">
            <label>
              Поиск турнира{" "}
              <input
                value={search}
                type="search"
                onChange={(e) => filterName(e.target.value)}
              />
            </label>
            <label>
              Регион соревнования{" "}
              <select
                value={region}
                onChange={(e) => filterRegion(e.target.value)}
              >
                {["Все регионы", "Global", "Europe", "Americas", "Asia"].map(
                  (item) => (
                    <option key={item}>{item}</option>
                  ),
                )}
              </select>
            </label>
          </div>
        )}
        {!archive && (
          <div className="filter-bar">
            <label>
              Месяц{" "}
              <select
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
              >
                <option value="">Весь календарь</option>
                {Array.from(
                  new Set(data.editions.map((e) => e.start.slice(0, 7))),
                )
                  .sort()
                  .map((m) => (
                    <option key={m} value={m}>
                      {new Date(m + "-15T12:00:00Z").toLocaleDateString(
                        "ru-RU",
                        { month: "long", year: "numeric" },
                      )}
                    </option>
                  ))}
              </select>
            </label>
            <label>
              <input
                type="checkbox"
                checked={own}
                onChange={(e) => onlyOwn(e.target.checked)}
              />{" "}
              Моя команда
            </label>
          </div>
        )}
        <div className="tc-list">
          {data.editions
            .filter(
              (e) =>
                archive ||
                ((!period || e.start.slice(0, 7) === period) &&
                  (!own || !!e.entries[c.team]) &&
                  (region === "Все регионы" || e.region === region) &&
                  e.title.toLowerCase().includes(search.toLowerCase())),
            )
            .filter((e) =>
              archive ? e.status === "finished" : e.status !== "finished",
            )
            .sort((a, b) => a.start.localeCompare(b.start))
            .map((e) => (
              <button
                className="surface tc-card"
                key={e.id}
                onClick={() => {
                  (props.onEdition || select)(e.id);
                  show("Обзор");
                }}
              >
                <span className="tc-card-line">
                  <CompetitionMark
                    mark={eventMark(e.id, e.organizer)}
                    name={e.title}
                    cycle={e.id}
                    year={e.year}
                    size={50}
                  />
                  <small>
                    {e.organizer} · {e.region}
                    <span className="tc-state" data-tone={statusTone(e.status)}>{status[e.status] || e.status}</span>
                  </small>
                </span>
                <strong>{e.title}</strong>
                <span>{span(e.start, e.end)}</span>
                <footer>
                  {e.prizes.length ? purse(e) : "Отбор"} · {e.capacity} команд
                  {e.simulated ? " · Игровой сезон" : ""}
                </footer>
                {e.feeds && !!e.advanced?.length && (
                  <b>
                    Прошли отбор ·{" "}
                    {e.advanced.map((t) => c.teams[t]).join(", ")}
                  </b>
                )}
                {!e.feeds && e.placements?.[0] && (
                  <b>Победитель · {c.teams[e.placements[0]]}</b>
                )}
              </button>
            ))}
        </div>
        {archive && <Archive editions={data.archive} />}
      </>
    );
  const rows = Object.entries(event.stats).sort(
    ([, a], [, b]) => b.damage / b.rounds - a.damage / a.rounds,
  );
  const teamStats: Record<string, { k: number; d: number; damage: number }> =
    {};
  for (const [, r] of rows) {
    const t = (teamStats[r.team] ||= { k: 0, d: 0, damage: 0 });
    t.k += r.k;
    t.d += r.d;
    t.damage += r.damage;
  }
  const fixture = c.history.find((e) => e.id === report);
  const stage =
    event.stages[Math.max(0, event.draws.length - 1)] || event.stages[0];
  const upcoming = c.queue.find(
    (e) => e.edition === picked && e.teams.includes(c.team),
  );
  const record = event.draws
    .at(-1)
    ?.flatMap((draw) => draw.standings)
    .find((row) => row.team === c.team);
  const matchDay =
    upcoming &&
    new Date(upcoming.date + "T12:00:00Z").toLocaleDateString("ru", {
      day: "numeric",
      month: "short",
      timeZone: "UTC",
    });
  const mark = eventMark(event.id, event.organizer);
  const groupStage = (format: string) =>
    ["roundRobin", "swiss", "gsl", "doubleGroups"].includes(format);
  return (
    <div className="cp-module">
      <button
        className="cp-back"
        onClick={() => (props.onEdition || select)("")}
      >
        <Icon name="back" />
        Все соревнования
      </button>
      <div className="cp-tournament-hero">
        {["major", "contenders", "eu14", "blast"].includes(mark) ? (
          <Mark mark={mark as "major"} size={112} />
        ) : (
          <CompetitionMark
            mark={mark}
            name={event.title}
            cycle={event.id}
            year={event.year}
            size={112}
          />
        )}
        <div>
          <p className="cp-eyebrow">
            СЕЗОН {event.year} · {event.organizer}
          </p>
          <h1>{event.title}</h1>
          <p>
            {span(event.start, event.end)} · {event.place}
          </p>
          <div className="cp-inline">
            <Badge tone={statusTone(event.status)}>{status[event.status] || event.status}</Badge>
            <Badge>
              {event.stages
                .map((s) => formats[s.format] || s.format)
                .filter((f, i, a) => a.indexOf(f) === i)
                .join(" / ")}
            </Badge>
          </div>
        </div>
        <div className="cp-prize">
          <span>Призовой фонд</span>
          <b>{purse(event)}</b>
          <span>{event.capacity} команд</span>
        </div>
      </div>
      <ApprovedTabs
        items={[
          "Обзор",
          "Участники",
          "Группы",
          "Сетка",
          "Расписание",
          "Результаты",
          "Статистика",
          "История",
          "Моя заявка",
        ]}
        value={tab}
        onChange={show}
      />
      {tab === "Обзор" && (
        <>
          <div className="cp-two-col">
            <Panel title="На повестке тренера">
              <div className="cp-callout">
                <Icon name="calendar" />
                <div>
                  <strong>
                    {upcoming
                      ? "Встреча с " +
                        c.teams[upcoming.teams.find((t) => t !== c.team)!]
                      : "Положение команды"}
                  </strong>
                  <p>
                    {upcoming
                      ? "Подготовка к серии: состав, маппул и анализ соперника."
                      : status[event.entries[c.team]] || "Команда не заявлена."}
                  </p>
                  <Button
                    variant="primary"
                    onClick={() =>
                      upcoming ? props.prepare(upcoming.id) : show("Моя заявка")
                    }
                  >
                    {upcoming ? "Подготовить команду" : "Открыть заявку"}
                  </Button>
                </div>
              </div>
              <div className="cp-metrics">
                <Stat
                  label={record ? "Счёт этапа" : "Стадия"}
                  value={
                    record
                      ? record.wins + "–" + record.losses
                      : stage?.name || status[event.status]
                  }
                />
                <Stat label="Встреча" value={matchDay || "—"} />
                <Stat label="Проходят" value={stage?.advance || "—"} />
              </div>
            </Panel>
            <Panel title="Регламент издания">
              <dl className="cp-definition">
                {[
                  ["Формат встречи", "BO" + (stage?.bestOf || 1) + " · MR12"],
                  ["Тайм-ауты", event.rules.timeouts + " на карту"],
                  ["Команды тренера", "Только в разрешённое окно"],
                  ["Резерв", event.rules.reserves + " игроков"],
                  ["Фиксация состава", date(event.lock)],
                ].map(([k, v]) => (
                  <div key={k}>
                    <dt>{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
              <Button onClick={() => setRulesOpen(true)}>
                Развернуть правила
              </Button>
            </Panel>
          </div>
          <Panel title="Пул карт">
            <div className="cp-map-chips">
              {event.rules.pool.map((m) => (
                <button key={m} onClick={() => setMapDetail(m)}>
                  <img
                    src={serverURL("/api/maps/" + m + "/radar.png").href}
                    alt=""
                  />
                  <span>{m.replace(/^de_/, "")}</span>
                </button>
              ))}
            </div>
          </Panel>
          {mapDetail && (
            <Dialog title={mapDetail} close={() => setMapDetail("")}>
              <img
                src={serverURL("/api/maps/" + mapDetail + "/radar.png").href}
                alt={"Радар " + mapDetail}
              />
            </Dialog>
          )}
          {rulesOpen && (
            <Dialog title="Правила издания" close={() => setRulesOpen(false)}>
              <p>
                {status[event.status]} · {admission[event.admission]} ·{" "}
                {event.simulated ? "Игровой сезон" : "Календарь организатора"}.
              </p>
              <p>
                Фиксация состава {date(event.lock)}. Запасных до{" "}
                {event.rules.reserves}. Тактических тайм-аутов на карту:{" "}
                {event.rules.timeouts}.
              </p>
              <details>
                <summary>Пул карт, veto и стартовые стороны</summary>
                <p>{event.rules.pool.map((m) => m.slice(3)).join(" · ")}</p>
                <p>
                  Первый ход получает{" "}
                  {event.rules.first === "draw"
                    ? "победитель жеребьёвки"
                    : event.rules.first === "home"
                      ? "команда A"
                      : "команда B"}
                  . На выбранной карте стартовую сторону определяет{" "}
                  {event.rules.pickSide === "opponent"
                    ? "соперник"
                    : "автор пика"}
                  . На решающей карте выбирает{" "}
                  {event.rules.deciderSide === "first" ? "первая" : "вторая"}{" "}
                  сторона veto.
                </p>
                {Object.entries(event.rules.formats).map(([bo, steps]) => (
                  <p key={bo}>
                    <b>BO{bo}</b> ·{" "}
                    {steps
                      .map((s, i) => {
                        const actor = typeof s === "string" ? i % 2 : s.actor;
                        const kind = typeof s === "string" ? s : s.kind;
                        return (
                          (actor ? "B" : "A") +
                          " " +
                          (kind === "pick" ? "пик" : "бан")
                        );
                      })
                      .join(" → ")}
                  </p>
                ))}
              </details>
              {event.snapshot && (
                <p>Снимок для приглашений · {date(event.snapshot)}</p>
              )}
              {event.seedSnapshot && (
                <p>Снимок для посева · {date(event.seedSnapshot)}</p>
              )}
              {event.stages.map((s) => (
                <p key={s.name}>
                  <b>{s.name}</b> · {formats[s.format]} · BO{s.bestOf}
                  {s.format === "swiss" && s.bestOf === 1 ? " / BO3" : ""}
                  {s.finalBO ? " · финал BO" + s.finalBO : ""}
                  {s.secondPlaceBO
                    ? " · решающий BO" + s.secondPlaceBO
                    : ""} · {span(s.start, s.end)}
                </p>
              ))}
              <p>
                <a href={event.source} target="_blank" rel="noreferrer">
                  Источник регламента ↗
                </a>
              </p>
              {event.bookingFee && (
                <p>
                  Взнос по регламенту {event.bookingFee}. Одна команда от
                  организации. Фонд зависит от числа допущенных составов.
                </p>
              )}
              {event.modelStages && (
                <p>
                  Окна стадий, регламент матчей и распределение выплат следуют
                  игровой проекции Major.
                </p>
              )}
              {event.modelDeadlines && (
                <p>Дедлайн регистрации задан календарём карьеры.</p>
              )}
              {event.modelDates && (
                <p>
                  Окно отбора, размер сетки и дедлайн заданы календарём карьеры.
                </p>
              )}
              {event.reason && <p>{event.reason}</p>}
              {!!event.prizes.length && (
                <details>
                  <summary>Распределение призовых</summary>
                  {event.prizes.map((n, i) => (
                    <p key={i}>
                      {i + 1} место · {money(n)}
                      {event.clubRewards &&
                        " + " + money(event.clubRewards[i]) + " клубу"}{" "}
                      {event.placements?.[i] &&
                        " · " + c.teams[event.placements[i]]}
                    </p>
                  ))}
                </details>
              )}
            </Dialog>
          )}
        </>
      )}
      {tab === "История" && (
        <Panel title="История издания">
          <p>
            {span(event.start, event.end)} · {event.title}
          </p>
          {event.placements?.length ? (
            event.placements.map((t, i) => (
              <p key={t}>
                {i + 1}. <EntityName group="teams" id={t} fallback={c.teams[t]}/>
              </p>
            ))
          ) : (
            <p>Итоговые места ещё не определены.</p>
          )}
        </Panel>
      )}
      {tab === "Моя заявка" && (
        <Registration
          key={
            picked +
            ":" +
            event.entries[c.team] +
            ":" +
            event.registrations[c.team]?.length
          }
          {...props}
          enabled={enabled && res.revision === revision}
          event={event}
          available={data.available}
        />
      )}
      {tab === "Участники" && (
        <>
          <div className="cp-filters">
            <Field label="Команда или игрок">
              <input
                type="search"
                placeholder="Поиск по заявкам"
                value={participantQuery}
                onChange={(e) => setParticipantQuery(e.target.value)}
              />
            </Field>
            <Badge>
              {Object.keys(event.entries).length} команд в списке заявок
            </Badge>
          </div>
          <div className="cp-participants">
            {Object.entries(event.entries)
              .filter(([t]) => {
                const entry = event.registrations[t]?.at(-1);
                return [
                  c.teams[t] || t,
                  ...(entry?.players || []).map(
                    (id) => scene.players[id]?.name || id,
                  ),
                ]
                  .join(" ")
                  .toLowerCase()
                  .includes(participantQuery.toLowerCase().trim());
              })
              .map(([t, state]) => {
                const entry = event.registrations[t]?.at(-1);
                const view = () => props.open({ group: "teams", id: t });
                return (
                  <article key={t}>
                    <div className="cp-split">
                      <button className="cp-team-link" onClick={view}>
                        <TeamLogo
                          name={c.teams[t] || t}
                          visual={scene.teams[t]?.visual}
                          size={44}
                        />
                        {c.teams[t] || t}
                      </button>
                      <Badge
                        tone={
                          ["locked", "confirmed", "playing"].includes(state)
                            ? "green"
                            : "neutral"
                        }
                      >
                        {status[state] || state}
                      </Badge>
                    </div>
                    <div className="cp-roster-links">
                      {entry ? (
                        entry.players.map((id) => (
                          <button
                            className="cp-person-link"
                            key={id}
                            onClick={() => props.open({ group: "players", id })}
                          >
                            {scene.players[id]?.name || id}
                          </button>
                        ))
                      ) : (
                        <span className="cp-muted">
                          Пятёрка ещё не зарегистрирована
                        </span>
                      )}
                    </div>
                    {entry && (
                      <details>
                        <summary>
                          Версия {entry.version} · {date(entry.date)}
                        </summary>
                        <p>
                          Запасные ·{" "}
                          {entry.reserves
                            .map((id) => scene.players[id]?.name || id)
                            .join(", ") || "нет"}
                        </p>
                        <p>
                          Тренер ·{" "}
                          {entry.coach
                            ? scene.staff[entry.coach]?.name
                            : "не заявлен"}
                        </p>
                      </details>
                    )}
                    <div className="cp-split">
                      <span className="cp-muted">
                        {t === c.team ? "Ваша команда" : scene.teams[t]?.region}
                      </span>
                      <Button onClick={view}>Полная карточка</Button>
                    </div>
                  </article>
                );
              })}
          </div>
          {!Object.keys(event.entries).length && <p>Заявок пока нет.</p>}
        </>
      )}
      {["Группы", "Сетка"].includes(tab) && (
        <>
          {!event.draws.some(
            (d, i) =>
              d.length &&
              groupStage(event.stages[i].format) === (tab === "Группы"),
          ) && <p>Для выбранного раздела сетка ещё не сформирована.</p>}
          {event.draws.map(
            (draws, i) =>
              groupStage(event.stages[i].format) === (tab === "Группы") && (
                <TournamentStage
                  key={event.id + "-" + i}
                  phase={event.stages[i]}
                  draws={draws}
                  c={c}
                  scene={scene}
                  onFixture={(id) => {
                    if (c.history.some((f) => f.id === id)) {
                      openReport(id);
                      show("Результаты");
                    } else props.prepare(id);
                  }}
                />
              ),
          )}
        </>
      )}
      {["Расписание", "Результаты"].includes(tab) && (
        <section className="surface panel-body">
          {tab === "Результаты" &&
            event.draws
              .flat()
              .flatMap((draw) => draw.games.filter((g) => g.historical).map(game=>({draw,game})))
              .map(({draw,game:g}, i) => (
                <div className="tc-result" key={"history" + i}>
                  <small>{date(g.date!)} · до начала карьеры</small>
                  <b>{g.slots.map((slot,index)=>{
                    const id = resolveSlot(draw,slot);
                    return <span key={index}>{index>0 && " — "}{id ? <EntityName group="teams" id={id} fallback={c.teams[id]}/> : "Участник не определён"}</span>;
                  })}</b>
                  <span>{g.score?.join(" : ")}</span>
                </div>
              ))}
          {(tab === "Результаты" ? c.history : c.queue)
            .filter((e) => e.edition === picked)
            .map((e) => (
              <div key={e.id} className="tc-result">
                <span className="tc-fixture-day">
                  <CompetitionMark
                    mark={eventMark(event.id, event.organizer)}
                    name={event.title}
                    year={event.year}
                    cycle={event.id}
                    size={22}
                  />
                  <small>
                    {date(e.date)} · BO{e.bestOf}
                  </small>
                </span>
                <b><FixtureTeams teams={e.teams} names={c.teams}/></b>
                {!e.score && (
                  <button
                    className="btn sm"
                    onClick={() => props.prepare(e.id)}
                  >
                    Подготовка и линия
                  </button>
                )}
                {!e.score && !e.teams.includes(c.team) && (
                  <button
                    className="btn sm"
                    disabled={!enabled || !!c.progress}
                    onClick={() =>
                      props.act("career-watch", {
                        fixture: c.watchFixture === e.id ? null : e.id,
                      })
                    }
                  >
                    {c.watchFixture === e.id
                      ? "Отменить наблюдение"
                      : "Остановиться перед матчем"}
                  </button>
                )}
                {e.score && (
                  <button className="btn sm" onClick={() => openReport(e.id)}>
                    {fixtureScore(e)} · Протокол
                  </button>
                )}
              </div>
            ))}
          {!event.draws.length && <p>Расписание появится после жеребьёвки.</p>}
          {fixture && (
            <MatchReport
              careerId={c.id}
              event={fixture}
              teams={c.teams}
              close={() => openReport("")}
            />
          )}
        </section>
      )}
      {tab === "Статистика" && (
        <section className="surface panel-body">
          {!rows.length ? (
            <p>
              После первой завершённой в карьере серии здесь появится статистика
              по протоколам карт.
            </p>
          ) : (
            <>
              {event.mvp && (
                <p>
                  MVP турнира · <b>{event.stats[event.mvp].name}</b> ·
                  максимальный ADR
                </p>
              )}
              <div className="table-wrap">
                <table className="simple-table">
                  <thead>
                    <tr>
                      <th>Игрок</th>
                      <th>Команда</th>
                      <th>K</th>
                      <th>D</th>
                      <th>A</th>
                      <th>ADR</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(([p, r]) => (
                      <tr key={p}>
                        <td><EntityName group="players" id={p} recordedName={r.name} historicalTeam={r.team}/></td>
                        <td><EntityName group="teams" id={r.team} fallback={c.teams[r.team]}/></td>
                        <td>{r.k}</td>
                        <td>{r.d}</td>
                        <td>{r.a}</td>
                        <td>{(r.damage / r.rounds).toFixed(1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <h2>Команды</h2>
              {Object.entries(teamStats).map(([t, r]) => (
                <p key={t}>
                  <EntityName group="teams" id={t} fallback={c.teams[t]}/> · {r.k} убийств · {r.d} смертей · {r.damage}{" "}
                  урона
                </p>
              ))}
            </>
          )}
        </section>
      )}
    </div>
  );
}
