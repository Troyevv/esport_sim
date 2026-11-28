import { lazy, Suspense, useState } from "react";
import { Avatar } from "./SceneIdentity";
import { Glyph, Heading, Tabs } from "./GameUI";
import { regions } from "./databaseModel";
import {
  useData,
  date,
  scopes,
  slotName,
  type Act,
  type Career,
  type Catalog,
  type Options,
  type Fixture,
} from "./careerData";
export function Load({ error, reload }: { error: string; reload: () => void }) {
  return error ? (
    <div className="game-request" role="alert">
      <Glyph name="report-analytics"/><span>{error}</span><button className="btn" onClick={reload}>Повторить</button>
    </div>
  ) : (
    <p className="game-request" role="status"><span className="request-spinner" aria-hidden="true"/>Загружаем данные…</p>
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
  const [step,setStep] = useState("Клуб");
  const [query,setQuery] = useState("");
  const [region,setRegion] = useState("");
  const [limit,setLimit] = useState(16);
  const [name, setName] = useState("");
  const [mode, setMode] = useState("manager");
  const [scope, setScope] = useState("standard");
  const [areas, setAreas] = useState(["Europe"]);
  const teams = (options.data?.teams || [])
    .slice()
    .sort((a, b) => a.name.localeCompare(b.name, "ru"));
  const club = teams.find((t) => t.id === team) || teams[0];
  const visible = teams.filter(t=>(!region || t.region===region) && t.name.toLowerCase().includes(query.toLowerCase().trim()));
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
    <section className="career career-create">
      <Heading title={step==="Клуб"?"Клуб и стартовый сценарий":"Ваш первый сезон"} eyebrow="Новая карьера" sub="Выберите редакцию сцены и клуб для старта карьеры">
        <button onClick={back}>← Главное меню</button></Heading>
      <Tabs items={["Клуб","Менеджер"]} value={step} change={setStep}/>
      {step==="Клуб" ? <>
        <div className="filter-bar">          {(!catalog.data || catalog.error) && <Load {...catalog} />}
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

        <label>Найти клуб<input type="search" value={query} onChange={e=>{setQuery(e.target.value);setLimit(16)}}/></label>
        <label>Регион клуба<select value={region} onChange={e=>{setRegion(e.target.value);setLimit(16)}}><option value="">Все регионы</option>
          {Object.entries(regions).map(([id,title])=><option key={id} value={id}>{title}</option>)}</select></label></div>
        {options.data && <div className="club-filter-result"><span role="status">Клубов · {visible.length} из {teams.length}</span>
          {(query || region) && <button type="button" onClick={()=>{setQuery("");setRegion("");setLimit(16)}}>Сбросить фильтры</button>}</div>}
        <div className="create-club-grid">{visible.slice(0,limit).map(t=><button key={t.id} className="create-club-card" aria-pressed={club?.id===t.id} onClick={()=>setTeam(t.id)}>
          <Avatar name={t.name} club {...t.visual}/><strong>{t.name}</strong><small>{regions[t.region||""] || "Регион неизвестен"}{t.tier?" · Тир "+t.tier:""}</small>
          {club?.id===t.id && <b>Выбрано</b>}</button>)}</div>
        {visible.length>limit && <button onClick={()=>setLimit(limit+16)}>Показать ещё клубы</button>}
        {!visible.length && options.data && <p>Клубов по этим условиям нет.</p>}
        <div className="create-next">{club && <span className="create-selected"><Avatar name={club.name} club {...club.visual}/><strong>{club.name}</strong></span>}<button className="btn primary" disabled={!club || !options.data || !!options.error} onClick={()=>setStep("Менеджер")}>Настроить карьеру</button></div>
      </> : <form className="cr-grid" onSubmit={e=>{e.preventDefault();void submit()}}>
        <div className="cr-card cr-form"><h2>Стартовый мир</h2>
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
              <div className="create-selected"><Avatar name={club.name} club {...club.visual}/><strong>{club.name}</strong></div>
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
      </form>}
    </section>
  );
}

const ReportScreen = lazy(() => import("./MatchReport"));
export function MatchReport(props: { event: Fixture; teams: Career["teams"]; careerId: string; close: () => void }) {
  return <Suspense fallback={<p role="status">Загружаем протокол…</p>}>
    <ReportScreen key={props.careerId + "/" + props.event.id} {...props} />
  </Suspense>;
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
