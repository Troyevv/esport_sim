import { useData, type Report, type Decision } from "./careerData";
import type { Quote } from "./ForecastLine";
import type { Directory } from "./CompetitionCenter";
import { regions, roles } from "./databaseModel";
import "./home.css";
import { useState } from "react";
import { Glyph, Heading } from "./GameUI";
import {
  date,
  dayAt,
  isoDay,
  monday,
  fixtureName,
  fixtureScore,
  weekdays,
  position,
  type Career,
  type Scene,
  type Fixture,
  type Profile,
} from "./careerData";
import { Badge, Button, Meter, Panel, PageHeading } from "./approved/Shared";
import { TeamLogo, Portrait } from "./approved/Identity";
export type Letter = {
  id: string;
  date: string;
  title: string;
  from: string;
  body: string;
  event?: Fixture;
  edition?:string;
};
export function letters(c: Career): Letter[] {
  const box: Letter[] = c.milestones.map((m) => ({
    edition:m.edition,
    id: m.id || "club/" + m.date + "/" + m.title,
    date: m.date,
    title: m.title,
    from: m.sender || c.organization || c.club,
    body:m.body || (
      m.matches === null
        ? c.character + " · " + position(c.mode) + " · " + c.club
        : "Сыграно матчей за неделю: " + m.matches + "."),
  }));
  for (const e of c.history.filter((e) => e.teams.includes(c.team)))
    box.push({
      id: "result/" + e.id,
      date: e.date,
      title: "Результат встречи",
      from: "Матч-центр",
      body: fixtureName(c, e) + " · " + fixtureScore(e),
      event: e,
    });
  const next = c.queue.find((e) => e.teams.includes(c.team));
  if (next)
    box.push({
      id: "fixture/" + next.id,
      date: c.date,
      title: "Ближайший соперник",
      from: "Календарь",
      body:
        fixtureName(c, next) + " · " + date(next.date) + " · "+(next.title||"Выставочный")+" BO" + (next.bestOf ?? 1) + ".",
      event: next,
    });
  return box.reverse().sort((a, b) => b.date.localeCompare(a.date));
}
function letterIcon(m: Letter) {
  if (m.event?.score) return "report-analytics";
  if (m.event) return "calendar";
  return m.edition ? "trophy" : "mail";
}
export function Inbox({
  box,
  read,
  selected,
  select,
  calendar,
  tournament,
}: {
  box: Letter[];
  read: string[];
  selected: Letter | null;
  select: (id: string | null) => void;
  calendar: (d: string) => void;
  tournament:(id:string)=>void;
}) {
  const [filter, setFilter] = useState(false);
  const filtered = box.filter(
    (m) => !filter || !read.includes(m.id) || selected?.id === m.id,
  );
  return (
    <>
      <Heading title="Входящие" sub="Сообщения клуба и протоколы встреч" />
      <section
        className={"surface inbox-layout " + (selected ? "message-open" : "")}
      >
        <div className="inbox-list">
          <div className="inbox-controls">
            <button
              className="btn sm"
              aria-pressed={filter}
              onClick={() => setFilter(!filter)}
            >
              {filter ? "Непрочитанные" : "Все сообщения"}
            </button>
          </div>
          {filtered.map((m) => (
            <button
              key={m.id}
              className={
                "inbox-item " + (selected?.id === m.id ? "active" : "")
              }
              onClick={() => select(m.id)}
            >
              <span className="sender letter-source"><Glyph name={letterIcon(m)}/>{m.from}</span>
              <strong>{m.title}</strong>
              <small>{date(m.date)}</small>
              {!read.includes(m.id) && (
                <span className="unread-dot" aria-label="Не прочитано" />
              )}
            </button>
          ))}
          {!filtered.length && (
            <p className="panel-body muted">Новых сообщений нет.</p>
          )}
        </div>
        <article className="message-content">
          {selected ? (
            <>
              <button className="btn mobile-back" onClick={() => select(null)}>
                Все сообщения
              </button>
              <span className="pill info">Уведомление</span>
              <h2>{selected.title}</h2>
              <div className="message-author">
                <span className="manager-avatar">
                  <Glyph name={letterIcon(selected)} />
                </span>
                <span>
                  <strong>{selected.from}</strong>
                  <small>{date(selected.date)}</small>
                </span>
              </div>
              <p className="message-body">{selected.body}</p>
              <div className="message-actions">
                {(selected.edition || selected.event?.edition) && <button className="btn primary" onClick={()=>tournament((selected.edition || selected.event?.edition)!)}>Открыть турнир</button>}
                <button
                  className="btn"
                  onClick={() =>
                    calendar(selected.event?.date || selected.date)
                  }
                >
                  Открыть календарь
                </button>
              </div>
            </>
          ) : (
            <div className="inbox-prompt"><Glyph name="inbox"/><h2>Выберите сообщение</h2>
              {filtered.some(m=>!read.includes(m.id)) && <button className="btn" onClick={()=>select(filtered.find(m=>!read.includes(m.id))!.id)}>Открыть первое непрочитанное</button>}
            </div>
          )}
        </article>
      </section>
    </>
  );
}

export function Dashboard({
  c,
  scene,
  box,
  go,
  calendar,
  open,
  letter,
  prepare,
  tournament,
  resolve,
  revision,
  quick,
}: {
  c: Career;
  scene: Scene;
  box: Letter[];
  go: (page: string) => void;
  calendar: (day: string) => void;
  open: (p: Profile) => void;
  letter: (id: string) => void;
  prepare: (id: string) => void;
  tournament: (id: string) => void;
  resolve: (row: Decision) => void;
  revision: number;
  quick?: () => void;
}) {
  const next = c.queue.find(
    (e) => e.kind === "match" && !e.pcw && e.teams.includes(c.team),
  );
  const recent = c.history
    .filter((e) => e.kind === "match" && e.teams.includes(c.team))
    .slice(-3)
    .reverse();
  const plan = useData<{ forecasts: Quote[] }>(
    next ? "/api/career/" + c.id + "/prematch/" + next.id : null,
    revision,
  );
  const directory = useData<Directory>(
    !next && c.competitions ? "/api/career/" + c.id + "/competitions" : null,
    revision,
  );
  const upcoming = directory.data?.editions
    .filter(
      (e) =>
        ["accepted", "confirmed", "qualified", "locked", "playing"].includes(
          e.entries[c.team],
        ) && e.status !== "finished",
    )
    .sort((a, b) => a.start.localeCompare(b.start))[0];
  const last = useData<Report>(
    recent.length ? "/api/career/" + c.id + "/report/" + recent[0].id : null,
  );
  const mvp = last.data?.performance.players.find(
    (p) => p.player === last.data?.performance.mvp,
  );
  const start = monday(c.date);
  const training = useData<Record<string, string[]>>(
    "/api/career/" + c.id + "/training-calendar?since=" + start + "&count=7",
    revision,
  );
  const quote = plan.data?.forecasts.at(-1);
  const team = (id: string) => scene.teams[id]?.name || c.teams[id] || id;
  const opponent = next?.teams.find((t) => t !== c.team);
  const dayLabel = new Date(c.date + "T12:00:00Z").toLocaleDateString("ru", {
    weekday: "long",
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  });
  const isToday = next?.date === c.date;
  const teamButton = (tid?: string) => (
    <button
      className="hero-team"
      disabled={!tid}
      onClick={() => tid && open({ group: "teams", id: tid })}
    >
      {tid && (
        <TeamLogo
          size={88}
          name={team(tid)}
          visual={scene.teams[tid]?.visual}
        />
      )}
      <h2>{tid ? team(tid) : "Жеребьёвка"}</h2>
      <small>
        {tid
          ? regions[scene.teams[tid]?.region || ""] ||
            scene.teams[tid]?.visual.flag
          : "Соперник ещё не определён"}
      </small>
    </button>
  );
  const price = (id?: string) => {
    const i = quote?.teams.indexOf(id || "") ?? -1;
    return quote && i >= 0 ? (
      <>
        <em>{Math.round(quote.probability[i] * 100)}%</em> {team(id!)}{" "}
        <b>{quote.odds[i].toFixed(2)}</b>
      </>
    ) : (
      "—"
    );
  };
  const destination = () =>
    next
      ? prepare(next.id)
      : upcoming
        ? tournament(upcoming.id)
        : calendar(c.date);
  const decisions = c.attention.slice(0, 3);
  const eventName = next?.title || upcoming?.title || "Календарь команды";
  const brand = eventName.match(/^([A-ZА-Я0-9]{2,}) (.+)$/);

  return (
    <>
      <PageHeading
        eyebrow={dayLabel.toUpperCase() + " · СЕЗОН " + c.date.slice(0, 4)}
        title={isToday ? "День матча" : "Кабинет команды"}
        subtitle={
          opponent
            ? "Всё решается на сервере. Подготовьте команду к встрече с " +
              team(opponent) +
              "."
            : "Расписание, состав и решения штаба " + c.club + "."
        }
        actions={
          <Badge tone="orange">
            {isToday
              ? "МАТЧ СЕГОДНЯ"
              : next
                ? date(next.date)
                : "КАЛЕНДАРЬ КОМАНДЫ"}
          </Badge>
        }
      />
      <div className="home-layout">
        <div className="home-main">
          <section className="match-hero">
            <div className="hero-topline">
              <button
                className="event-wordmark"
                style={{ border: 0, background: "none", padding: 0 }}
                onClick={() =>
                  next?.edition
                    ? tournament(next.edition)
                    : upcoming
                      ? tournament(upcoming.id)
                      : calendar(c.date)
                }
              >
                {brand ? (
                  <>
                    <span>{brand[1]}</span> {brand[2]}
                  </>
                ) : (
                  eventName
                )}
              </button>
              <span>
                {next ? "BO" + (next.bestOf || 1) + " · MR12" : "Расписание"}
              </span>
            </div>
            <div className="hero-versus">
              {teamButton(c.team)}
              <div className="versus-time">
                <strong>VS</strong>
                <small>
                  {isToday
                    ? "Сегодня"
                    : date(next?.date || upcoming?.start || c.date)}
                </small>
                {next && <small>BO{next.bestOf || 1}</small>}
              </div>
              {teamButton(opponent)}
            </div>
            <div className="probability-line">
              {quote && (
                <i
                  style={{
                    width:
                      100 * quote.probability[quote.teams.indexOf(c.team)] +
                      "%",
                  }}
                />
              )}
            </div>
            <div className="hero-odds">
              <span>{price(c.team)}</span>
              <span>
                {quote
                  ? "Виртуальные коэффициенты"
                  : "Линия появится после жеребьёвки"}
              </span>
              <span>{price(opponent)}</span>
            </div>
            <div className="hero-action">
              <p>
                <strong>
                  {next
                    ? "Подготовка к серии"
                    : upcoming?.title || "Календарь команды"}
                </strong>
                {c.roster.length} игроков · {c.club}
              </p>
              <Button variant="primary" onClick={destination}>
                {next
                  ? "Подготовка к матчу"
                  : upcoming
                    ? "Открыть турнир"
                    : "Открыть календарь"}
              </Button>
            </div>
          </section>
          <section>
            <div className="section-heading">
              <h2>Ваш стартовый состав</h2>
              <button className="text-button" onClick={() => go("Состав")}>
                Управление составом
              </button>
            </div>
            <div className="lineup-five">
              {c.roster.map((p) => (
                <button
                  className="home-player"
                  key={p.id}
                  onClick={() => open({ group: "players", id: p.id })}
                >
                  <Portrait {...p} />
                  <div className="home-player-info">
                    <strong>{p.name}</strong>
                    <small>{roles[p.role] || p.role}</small>
                    <div className="readiness-label">Готовность</div>
                    <Meter
                      value={Math.round(100 - p.fatigue)}
                      tone={p.fatigue > 10 ? "orange" : "green"}
                    />
                    {p.fatigue > 70 && (
                      <span className="player-alert">Высокая усталость</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </section>
          <section>
            <div className="section-heading">
              <h2>Неделя команды</h2>
              <button className="text-button" onClick={() => calendar(c.date)}>
                Весь календарь
              </button>
            </div>
            <div className="week-strip">
              {weekdays.map((d, i) => {
                const day = isoDay(dayAt(start, i));
                const e = [...recent, ...c.queue].find(
                  (g) =>
                    g.date === day &&
                    g.kind === "match" &&
                    g.teams.includes(c.team),
                );
                return (
                  <button
                    className={
                      "week-day" +
                      (day === c.date ? " active" : "") +
                      (e ? " match-day" : "")
                    }
                    onClick={() => calendar(day)}
                    key={day}
                  >
                    <small>{d}</small>
                    <b>{Number(day.slice(-2))}</b>
                    <span>
                      {e
                        ? fixtureName(c, e)
                        : training.data?.[day]?.join(" · ") || "Свободно"}
                    </span>
                  </button>
                );
              })}
            </div>
          </section>
        </div>
        <aside className="home-aside">
          <Panel
            title="Решения тренера"
            action={<Badge tone="orange">{c.attention.length}</Badge>}
          >
            {decisions.map((a) => (
              <div key={a.id} className="decision-item">
                <Badge tone={a.level === "required" ? "orange" : "blue"}>
                  {date(a.due)}
                </Badge>
                <h3>{a.title}</h3>
                <p>{a.detail}</p>
                {a.action === "play" && quick ? (
                  <Button aria-label="Быстро рассчитать матч" onClick={quick}>
                    Рассчитать матч
                  </Button>
                ) : (
                  <Button onClick={() => resolve(a)}>Открыть решение</Button>
                )}
              </div>
            ))}
            {decisions.length === 0 && (
              <div className="decision-item">
                <Badge tone="green">Календарь</Badge>
                <h3>Обязательных решений нет</h3>
                <Button onClick={() => calendar(c.date)}>
                  Открыть календарь
                </Button>
              </div>
            )}
            {decisions.length < 3 && box[0] && (
              <div className="decision-item">
                <Badge>ВХОДЯЩИЕ</Badge>
                <h3>{box[0].title}</h3>
                <p>{box[0].from}</p>
                <Button onClick={() => letter(box[0].id)}>
                  Открыть письмо
                </Button>
              </div>
            )}
            {decisions.length < 2 && opponent && (
              <div className="decision-item">
                <Badge tone="blue">АНАЛИЗ СОПЕРНИКА</Badge>
                <h3>{team(opponent)}</h3>
                <p>
                  {date(next!.date)} · BO{next!.bestOf || 1}
                </p>
                <Button onClick={destination}>Отчёт штаба</Button>
              </div>
            )}
          </Panel>
          <Panel
            title="Последние встречи"
            action={
              <button
                className="text-button"
                onClick={() => go("Архив матчей")}
              >
                Все
              </button>
            }
          >
            {recent.map((e) => {
              const tid = e.teams.find((t) => t !== c.team)!;
              return (
                <div className="result-mini" key={e.id}>
                  <button onClick={() => open({ group: "teams", id: tid })}>
                    <TeamLogo
                      name={team(tid)}
                      visual={scene.teams[tid]?.visual}
                      size={28}
                    />
                    <span>
                      {team(tid)}
                      <small>{date(e.date)}</small>
                    </span>
                  </button>
                  <button
                    className={
                      "score " +
                      (e.score &&
                      e.score[e.teams.indexOf(c.team)] >
                        e.score[e.teams.indexOf(tid)]
                        ? "green"
                        : "red")
                    }
                    onClick={() => calendar(e.date)}
                  >
                    {fixtureScore(e)}
                  </button>
                </div>
              );
            })}
            {!recent.length && (
              <p>В этой карьере команда ещё не сыграла официальный матч.</p>
            )}
          </Panel>
          <Panel title="MVP последней серии">
            {mvp ? (
              <button
                className="focus-player"
                style={{
                  background: "none",
                  border: 0,
                  padding: 0,
                  textAlign: "left",
                }}
                onClick={() => open({ group: "players", id: mvp.player })}
              >
                <Portrait
                  id={mvp.player}
                  name={mvp.name}
                  visual={{
                    ...scene.players[mvp.player]?.visual,
                    kit:
                      scene.players[mvp.player]?.visual.kit?.id === mvp.teamId
                        ? scene.players[mvp.player].visual.kit
                        : null,
                  }}
                />
                <div>
                  <Badge tone="orange">MVP</Badge>
                  <h3>{mvp.name}</h3>
                  <p>
                    Impact {mvp.impact?.toFixed(2)} · {mvp.rounds} раундов
                  </p>
                </div>
              </button>
            ) : (
              <p>
                {last.error ||
                  (recent.length && !last.data
                    ? "Загружаем протокол…"
                    : "Для определения MVP пока недостаточно данных.")}
              </p>
            )}
          </Panel>
        </aside>
      </div>
    </>
  );
}
