import { fixtureMap } from "./careerData";
import { useEffect, useRef, useState } from "react";
import { regions } from "./databaseModel";
import {
  useData,
  date,
  scopes,
  slotName,
  fixtureScore,
  type Act,
  type Career,
  type Catalog,
  type Options,
  type Fixture,
  type Report,
} from "./careerData";
export function Load({ error, reload }: { error: string; reload: () => void }) {
  return error ? (
    <div role="alert">
      {error} <button onClick={reload}>Повторить</button>
    </div>
  ) : (
    <p role="status">Загружаем данные…</p>
  );
}

export function NewCareer({
  act,
  enabled,
  back,
  opened,
}: {
  act: Act;
  enabled: boolean;
  back: () => void;
  opened: () => void;
}) {
  const catalog = useData<Catalog>("/api/database");
  const [edition, setEdition] = useState("");
  const source =
    edition ||
    (catalog.data?.[0]
      ? catalog.data[0].id + "/" + catalog.data[0].revision
      : "");
  const options = useData<Options>(
    source ? "/api/career/options/" + source : null,
  );
  const [team, setTeam] = useState("");
  const [name, setName] = useState("");
  const [mode, setMode] = useState("manager");
  const [scope, setScope] = useState("standard");
  const [areas, setAreas] = useState(["Europe"]);
  const teams = (options.data?.teams || [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const club = teams.find((t) => t.id === team) || teams[0];
  const submit = async () => {
    const [id, rev] = source.split("/");
    if (
      club &&
      (await act("career-create", {
        id,
        revision: Number(rev),
        team: club.id,
        name,
        mode,
        scope: options.data?.circuit?"full":scope,
        regions: !options.data?.circuit && scope === "fast" ? areas : [],
      }))
    )
      opened();
  };
  return (
    <section className="career">
      <button onClick={back}>← Главное меню</button>
      <header className="cr-title">
        <small>Карьера</small>
        <h1>Новая карьера</h1>
      </header>
      <form
        className="cr-grid"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="cr-card cr-form">
          <h2>Стартовый мир</h2>
          {(!catalog.data || catalog.error) && <Load {...catalog} />}
          <label>
            Редакция базы
            <select
              value={source}
              onChange={(e) => {
                setEdition(e.target.value);
                setTeam("");
              }}
            >
              {catalog.data?.map((p) => (
                <option key={p.id + p.revision} value={p.id + "/" + p.revision}>
                  {p.title} · ред. {p.revision}
                </option>
              ))}
            </select>
          </label>
          {(!options.data || options.error) && <Load {...options} />}
          <label>
            Команда
            <select
              aria-label="Команда"
              required
              value={club?.id || ""}
              onChange={(e) => setTeam(e.target.value)}
            >
              {teams.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
          {options.data && (
            <p>
              {date(options.data.date)} · {teams.length} команд с полной
              пятёркой
            </p>
          )}
          {options.data?.circuit ? <p>Полная турнирная сцена · соревнования и VRS всех регионов</p> : <>
          <label>
            Охват симуляции
            <select value={scope} onChange={(e) => setScope(e.target.value)}>
              {Object.entries(scopes).map(([k, v]) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          {scope === "fast" ? (
            <fieldset>
              <legend>Регионы фоновых встреч</legend>
              {Object.entries(regions).map(([k, v]) => (
                <label key={k}>
                  <input
                    type="checkbox"
                    checked={areas.includes(k)}
                    onChange={(e) =>
                      setAreas(
                        e.target.checked
                          ? [...areas, k]
                          : areas.filter((a) => a !== k),
                      )
                    }
                  />
                  {v}
                </label>
              ))}
            </fieldset>
          ) : (
            <p>
              {scope === "full"
                ? "Все доступные составы, включая тир-3."
                : "Основная сцена (тир-1 и тир-2) и ваша команда. В базах без тиров участвуют все доступные составы."}
            </p>
          )}</>}
        </div>
        <div className="cr-card cr-form">
          <h2>Игровой персонаж</h2>
          <label>
            Имя персонажа
            <input
              required
              maxLength={64}
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoComplete="off"
            />
          </label>
          <label>
            Должность
            <select value={mode} onChange={(e) => setMode(e.target.value)}>
              <option value="manager">Наёмный менеджер</option>
              <option value="owner">Владелец организации</option>
            </select>
          </label>
          {club && (
            <div className="cr-selection">
              <small>Стартовая команда</small>
              <strong>{club.name}</strong>
              <span>
                {regions[club.region || ""] || "Регион неизвестен"}
                {club.tier && " · Тир " + club.tier}
              </span>
            </div>
          )}
          <button
            className="primary"
            disabled={
              !enabled ||
              !name.trim() ||
              !club ||
              !!options.error ||
              (!options.data?.circuit && scope === "fast" && !areas.length)
            }
          >
            Создать карьеру
          </button>
        </div>
      </form>
    </section>
  );
}

const buyName: Record<string,string> = {pistol:"пистолетный", full:"полная закупка", force:"форс", eco:"эко"};

export function MatchReport({
  event,
  teams,
  close,
}: {
  event: Fixture;
  teams: Record<string, string>;
  close: () => void;
}) {
  const data = useData<Report>("/api/career/report/" + event.id);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    title.current?.focus();
  }, [event.id]);
  const rounds = data.data?.rounds.length || 0;
  return (
    <section className="cr-card cr-report">
      <div className="cr-line">
        <h2 ref={title} tabIndex={-1}>
          Протокол матча
        </h2>
        <button onClick={close}>Закрыть протокол</button>
      </div>
      <h3 className="cr-result-title">
        {teams[event.teams[0]]} <strong>{fixtureScore(event)}</strong>{" "}
        {teams[event.teams[1]]}
      </h3>
      {!data.data || data.error ? (
        <Load {...data} />
      ) : (
        <>
          <p>
            {date(event.date)} · {fixtureMap(event)} · Раунды: {rounds} · {data.data.simulation?.mode === "round" ? "Быстрый расчёт по раундам" : "Подробная симуляция"}
          </p>
          {data.data.maps && <ol className="series-order" aria-label="Итоги карт">
            {data.data.maps.map((m,i) => <li key={m.mapId}><small>Карта {i+1}</small>
              <strong>{fixtureMap({...event,bestOf:undefined,mapId:m.mapId})}</strong>
              <span>{event.teams.map(t => m.scoreByTeam[t]).join(" : ")}</span></li>)}
          </ol>}
          {data.data.simulation?.mode === "round" && (data.data.maps || [{mapId:event.mapId || "depo", rounds:data.data.rounds}]).map(m=>(
            <details className="cr-rounds" key={m.mapId}>
              <summary>Раунды · {fixtureMap({...event,bestOf:undefined,mapId:m.mapId})}</summary>
              <ol>{m.rounds.map(r=><li key={r.round}>
                <strong>{r.score.join(" : ")}</strong> {teams[r.winnerTeamId]} · {r.side}
                <small>{r.buys?.map((b,i)=>teams[event.teams[i]]+" · "+(buyName[b] || b)).join(" / ")}</small>
              </li>)}</ol>
            </details>
          ))}
          {event.teams.map((tid, club) => (
            <table key={tid}>
              <caption>{teams[tid]}</caption>
              <thead>
                <tr>
                  <th scope="col">Игрок</th>
                  <th scope="col">K</th>
                  <th scope="col">D</th>
                  <th scope="col">A</th>
                  <th scope="col">ADR</th>
                  <th scope="col">KAST</th>
                  <th scope="col" title="Первые убийства / первые смерти">FK / FD</th>
                </tr>
              </thead>
              <tbody>
                {data
                  .data!.stats.filter((p) =>
                    p.teamId ? p.teamId === tid : p.club === club,
                  )
                  .map((p) => (
                    <tr key={p.player}>
                      <th scope="row">{p.name}</th>
                      <td>{p.k}</td>
                      <td>{p.d}</td>
                      <td>{p.a}</td>
                      <td>{(p.damage / rounds).toFixed(1)}</td>
                      <td>{Number.isFinite(p.kast) ? Math.round(100*p.kast/rounds)+"%" : "—"}</td>
                      <td>{p.opening ?? "—"} / {p.openingDeaths ?? "—"}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          ))}
        </>
      )}
    </section>
  );
}

export function Saves({
  c,
  act,
  enabled,
}: {
  c: Career;
  act: Act;
  enabled: boolean;
}) {
  const [slot, setSlot] = useState("1");
  return (
    <section className="cr-card cr-form">
      <h2>Сохранения</h2>
      <div className="cr-line">
        <label>
          Ручной слот
          <select value={slot} onChange={(e) => setSlot(e.target.value)}>
            {["1", "2", "3"].map((s) => (
              <option key={s} value={s}>
                {slotName(s)}
              </option>
            ))}
          </select>
        </label>
        <button
          disabled={!enabled}
          onClick={() => act("career-save", { slot })}
        >
          Сохранить карьеру
        </button>
      </div>
      {c.slots.map((s) => (
        <div className="cr-save" key={s.slot}>
          <span>
            <strong>{slotName(s.slot)}</strong>
            <small>
              {date(s.date)} · {s.club}
            </small>
          </span>
          <button
            disabled={!enabled}
            onClick={() => act("career-load", { slot: s.slot })}
          >
            Загрузить
          </button>
        </div>
      ))}
    </section>
  );
}
