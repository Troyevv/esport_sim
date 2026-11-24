import { useEffect, useMemo, useRef, useState } from "react";
import { serverURL } from "./session";
import {
  emptyEntity,
  evidence,
  groups,
  groupKeys,
  refKey,
  regions,
  roles,
  skillGroups,
  skillLabels,
  statuses,
  type Entity,
  type Group,
  type Origin,
  type Pack,
  type Ref,
} from "./databaseModel";
import "./database.css";
import { KitEditor, KitPreview } from "./KitStudio";
import { Identity } from "./SceneIdentity";
import { entityVisual } from "./databaseModel";
import PortraitEditor from "./PortraitEditor";
import {
  AttributeGrid,
  PlayerOverview,
  ClubOverview,
  ProfileHeading,
} from "./SceneProfiles";
import { editorProfile } from "./editorProfile";
import PlayerEditorFields from "./PlayerEditorFields";

type Destination = { group: Group; id: string };
type Props = {
  onClose: () => void;
  start: (value: object) => Promise<boolean>;
  enabled: boolean;
};
const sorted = (items: Record<string, Entity>) =>
  Object.entries(items).sort(([, a], [, b]) =>
    a.name.localeCompare(b.name, "ru"),
  );
async function request(path: string, body?: string | Blob) {
  const res = await fetch(serverURL("/api/database" + path), {
    credentials: "include",
    cache: "no-store",
    method: body === undefined ? "GET" : "POST",
    headers:
      body === undefined
        ? {}
        : {
            "Content-Type":
              body instanceof Blob ? "application/zip" : "application/json",
          },
    body,
  });
  if (!res.ok) {
    const detail = await res.json();
    throw new Error(
      typeof detail.detail === "string"
        ? detail.detail
        : "Сервер отклонил запрос",
    );
  }
  return res.json();
}
function Source({ origin }: { origin: Origin }) {
  return (
    <span
      className={"db-proof " + origin.status}
      title={origin.date + " · " + origin.reference}
    >
      {statuses[origin.status]}
    </span>
  );
}
function SourceLine({ origin }: { origin: Origin }) {
  return (
    <span className="db-source">
      <Source origin={origin} /> {origin.date} ·{" "}
      {origin.reference.startsWith("https://") ? (
        <a href={origin.reference} target="_blank" rel="noreferrer">
          Открыть источник ↗
        </a>
      ) : (
        origin.reference
      )}
    </span>
  );
}
const firstId = (p: Pack, g: Group) =>
  (g === "players"
    ? Object.entries(p.players).find(([, r]) => r.photo)?.[0]
    : null) ||
  sorted(p[g])[0]?.[0] ||
  "";
function Select({
  label,
  value,
  options,
  onChange,
  blank = "Неизвестно",
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
  blank?: string;
}) {
  return (
    <label>
      {label}
      <select
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{blank}</option>
        {options.map(([k, n]) => (
          <option key={k} value={k}>
            {n}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function DatabaseEditor({ onClose, start, enabled }: Props) {
  const [catalog, setCatalog] = useState<(Ref & { title: string })[]>([]);
  const [pack, setPack] = useState<Pack | null>(null);
  const [at, setAt] = useState<Destination>({ group: "players", id: "" });
  const [draft, setDraft] = useState<Entity | null>(null);
  const [create, setCreate] = useState(false);
  const [query, setQuery] = useState(""),
    [filter, setFilter] = useState(""),
    [order, setOrder] = useState("asc");
  const [page, setPage] = useState(0),
    [section, setSection] = useState("Профиль"),
    [skillGroup, setSkillGroup] = useState("Механика");
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [matchSetup, setMatchSetup] = useState(false),
    [home, setHome] = useState(""),
    [away, setAway] = useState(""),
    [seed, setSeed] = useState("42");
  const input = useRef<HTMLInputElement>(null);
  const card = useRef<HTMLElement>(null);
  const selected = draft || pack?.[at.group][at.id];
  const options = useMemo(
    () =>
      pack
        ? (Object.fromEntries(
            groupKeys.map((g) => [
              g,
              sorted(pack[g]).map(([k, v]) => [k, v.name]),
            ]),
          ) as Record<Group, [string, string][]>)
        : null,
    [pack],
  );
  const rosterList = useMemo(
    () =>
      pack
        ? sorted(pack.rosters).filter(([, r]) => r.players?.length === 5)
        : [],
    [pack],
  );
  const rows = useMemo(() => {
    if (!pack || !options) return [];
    const found = options[at.group].filter(([id, name]) => {
      const r = pack[at.group][id];
      const linked = r.team
        ? pack.teams[r.team]?.name
        : r.organization
          ? pack.organizations[r.organization]?.name
          : "";
      return (
        (!filter ||
          [
            r.role,
            r.region,
            r.team,
            r.contract,
            r.organization,
            String(r.tier),
          ].includes(filter)) &&
        (name + " " + (r.realName || "") + " " + id + " " + (linked || ""))
          .toLocaleLowerCase()
          .includes(query.trim().toLocaleLowerCase())
      );
    });
    return order === "asc" ? found : found.reverse();
  }, [pack, options, at.group, filter, query, order]);
  const profile = useMemo(
    () => (pack ? editorProfile(pack, at.group, at.id) : null),
    [pack, at],
  );
  const history = useMemo(
    () =>
      profile?.results
        .slice()
        .sort(([, a], [, b]) => b.date.localeCompare(a.date)) || [],
    [profile],
  );
  const [ratings, setRatings] = useState<{
    roles: Record<string, number>;
    overall: number;
  } | null>(null);
  const [ratingError, setRatingError] = useState("");
  useEffect(() => {
    let current = true;
    setRatings(null);
    setRatingError("");
    if (pack && at.group === "players" && pack.players[at.id]) {
      request("/" + refKey(pack) + "/ratings/" + at.id)
        .then((v) => {
          if (current) setRatings(v);
        })
        .catch((e) => {
          if (current) setRatingError(String(e));
        });
    }
    return () => {
      current = false;
    };
  }, [pack, at]);
  function guard() {
    return (
      !draft ||
      (!create &&
        JSON.stringify(draft) === JSON.stringify(pack?.[at.group][at.id])) ||
      window.confirm("Закрыть карточку без сохранения изменений?")
    );
  }
  function move(g: Group, id: string, scroll = false) {
    if (!guard()) return;
    setDraft(null);
    setCreate(false);
    setSection("Профиль");
    setAt({ group: g, id });
    setNotice("");
    setError("");
    if (g !== at.group) {
      setQuery("");
      setFilter("");
      setPage(0);
    }
    if (scroll && window.innerWidth < 740)
      requestAnimationFrame(() =>
        card.current?.scrollIntoView({ block: "start" }),
      );
  }
  async function load(ref?: Ref, select?: Destination) {
    const list = (await request("")) as (Ref & { title: string })[];
    const target = ref || list[0];
    const { package: p } = (await request("/" + refKey(target))) as {
      package: Pack;
    };
    setCatalog(list);
    setPack(p);
    setDraft(null);
    setCreate(false);
    setPage(0);
    setFilter("");
    setQuery("");
    setAt(
      select && p[select.group][select.id]
        ? select
        : {
            group: select?.group || "players",
            id: firstId(p, select?.group || "players"),
          },
    );
    if (!select || !p[select.group][select.id]) setSection("Профиль");
    const rs = sorted(p.rosters).filter(([, r]) => r.players?.length === 5);
    setHome(rs[0]?.[0] || "");
    setAway(rs.find(([, r]) => r.team !== rs[0]?.[1].team)?.[0] || "");
  }
  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await fn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void run(() => load());
  }, []);
  function patch(update: Partial<Entity>) {
    setDraft((prev) => (prev ? { ...prev, ...update } : prev));
  }
  function begin(copy = false) {
    if (!pack || !guard()) return;
    const r =
      copy && selected
        ? { ...structuredClone(selected), name: selected.name + " · копия" }
        : emptyEntity(at.group, pack);
    setDraft(r);
    setCreate(true);
    setAt({ group: at.group, id: crypto.randomUUID() });
    setSection("Профиль");
    setNotice("");
    setError("");
    requestAnimationFrame(() =>
      card.current?.scrollIntoView({ block: "nearest" }),
    );
  }
  async function save(record: Entity | null) {
    if (!pack) return;
    await run(async () => {
      const ref = await request(
        "/" + refKey(pack) + "/" + at.group + "/" + at.id,
        JSON.stringify({ create, record }),
      );
      await load(ref, at);
      setNotice(
        record
          ? "Редакция " + ref.revision + " сохранена"
          : "Запись удалена · редакция " + ref.revision,
      );
    });
  }
  async function download() {
    if (!pack) return;
    await run(async () => {
      const obj = await request("/" + refKey(pack));
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(obj)], { type: "application/json" }),
      );
      const a = document.createElement("a");
      a.href = url;
      a.download = pack.id + "-r" + pack.revision + ".json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
  }
  function entityLink(g: Group, k: string) {
    return (
      <button className="db-link" key={g + k} onClick={() => move(g, k, true)}>
        {pack?.[g][k]?.name} ↗
      </button>
    );
  }
  const head = (
    <header className="db-heading">
      <div>
        <span className="eyebrow">Предматчевая подготовка</span>
        <h1>База сцены</h1>
      </div>
      <button
        onClick={() => {
          if (guard()) onClose();
        }}
      >
        Вернуться
      </button>
    </header>
  );
  if (!pack || !options)
    return (
      <article className="db">
        {head}
        <p role="status">{error || "Загружаем пакеты…"}</p>
        {error && <button onClick={() => run(() => load())}>Повторить</button>}
      </article>
    );
  const g = at.group;
  const editing = !!draft;
  const latest =
    catalog.find((c) => c.id === pack.id)?.revision === pack.revision;
  const teams = options.teams,
    players = options.players,
    orgs = options.organizations;
  const filterOptions: [string, string][] =
    g === "players"
      ? [...Object.entries(roles), ["free", "Свободный агент"]]
      : g === "teams"
        ? [
            ...Object.entries(regions),
            ...["1", "2", "3"].map((n) => [n, "Тир " + n] as [string, string]),
          ]
        : g === "rosters" || g === "staff"
          ? teams
          : [];
  const r = selected;
  const activeFieldNames: Record<string, string> = {
    founded: "Год основания",
    website: "Сайт",
    preparation: "Подготовка штаба",
    realName: "Настоящее имя",
    born: "Дата рождения",
    ageEstimate: "Игровой возраст",
    sample: "Выборка карт и серий",
    performance: "Рейтинг выступлений",
    logo: "Эмблема",
    nationality: "Национальность",
    photo: "Исходная фотография",
    appearance: "Слой внешности",
    kit: "Дизайн формы",
    roleMastery: "Освоение ролей",
    mapKnowledge: "Знание карт",
    statistics: "Индивидуальная статистика",
    name: "Название",
    role: "Роль",
    contract: "Контракт",
    potential: "Потенциал",
    tier: "Тир",
    region: "Регион",
    organization: "Организация",
    team: "Команда",
    players: "Пятёрка",
    captain: "Капитан",
    date: "Дата состава",
    skills: "Базовый профиль",
  };
  const fieldKeys = r
    ? Object.keys(r).filter((k) => !["fields", "origin"].includes(k))
    : [];
  return (
    <article className="db" aria-busy={busy}>
      {head}
      <section className="db-pack">
        <div>
          <label>
            Пакет и редакция
            <select
              value={refKey(pack)}
              disabled={busy}
              onChange={(e) => {
                if (guard())
                  void run(() =>
                    load(catalog.find((c) => refKey(c) === e.target.value)),
                  );
              }}
            >
              {catalog.map((c) => (
                <option key={refKey(c)} value={refKey(c)}>
                  {c.title} · ред. {c.revision}
                </option>
              ))}
            </select>
          </label>
          <small>Срез {pack.asOf}</small>
        </div>
        <div className="db-actions">
          <button
            disabled={busy}
            onClick={() => {
              if (!guard()) return;
              const title = window
                .prompt("Название нового пакета", pack.title + " · копия")
                ?.trim();
              if (title)
                void run(async () => {
                  const ref = await request(
                    "/" + refKey(pack) + "/copy",
                    JSON.stringify({ title }),
                  );
                  await load(ref);
                  setNotice("Создан отдельный пакет");
                });
            }}
          >
            Свой пакет
          </button>
          <button disabled={busy} onClick={() => input.current?.click()}>
            Импорт
          </button>
          <button disabled={busy} onClick={download}>
            Экспорт
          </button>
          <button
            className="primary"
            aria-expanded={matchSetup}
            onClick={() => setMatchSetup((v) => !v)}
          >
            Подбор BO1
          </button>
        </div>
        <input
          ref={input}
          type="file"
          accept=".json,.zip,application/json,application/zip"
          hidden
          aria-label="Файл пакета"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file || !guard()) return;
            await run(async () => {
              if (file.size > 24 * 1024 * 1024)
                throw Error("Пакет больше 24 МиБ");
              const ref = await request(
                "/import",
                file.name.toLowerCase().endsWith(".zip")
                  ? file
                  : await file.text(),
              );
              await load(ref);
              setNotice("Пакет проверен и открыт");
            });
          }}
        />
      </section>
      {matchSetup && (
        <section className="db-match">
          <h2>Выставочный матч</h2>
          <p>
            Депо · пять на пять. Для неизвестных ролей и капитана движок
            использует игровые назначения.
          </p>
          <div className="db-match-fields">
            <Select
              label="Ваша пятёрка"
              value={home}
              options={rosterList.map(([k, v]) => [k, v.name])}
              onChange={setHome}
            />
            <Select
              label="Соперник"
              value={away}
              options={rosterList.map(([k, v]) => [k, v.name])}
              onChange={setAway}
            />
            <label>
              Seed
              <input
                value={seed}
                inputMode="numeric"
                onChange={(e) => setSeed(e.target.value)}
              />
            </label>
            <button
              className="primary"
              disabled={
                !enabled ||
                busy ||
                !home ||
                !away ||
                pack.rosters[home]?.team === pack.rosters[away]?.team ||
                !/^\d+$/.test(seed) ||
                Number(seed) > 2147483647
              }
              onClick={() => {
                if (guard())
                  void run(async () => {
                    if (
                      await start({
                        id: pack.id,
                        revision: pack.revision,
                        rosters: [home, away],
                        seed: Number(seed),
                      })
                    )
                      onClose();
                  });
              }}
            >
              Начать BO1
            </button>
          </div>
        </section>
      )}
      {error && (
        <div className="db-error" role="alert">
          {error}{" "}
          <button
            onClick={() => {
              if (guard())
                void run(async () => {
                  const list = (await request("")) as Ref[];
                  await load(list.find((c) => c.id === pack.id));
                });
            }}
          >
            Обновить пакет
          </button>
        </div>
      )}
      {notice && (
        <p className="db-success" role="status">
          {notice}
        </p>
      )}
      <nav className="db-tabs" aria-label="Раздел базы">
        {groupKeys.map((k) => (
          <button
            key={k}
            aria-pressed={k === g}
            onClick={() => move(k, firstId(pack, k))}
          >
            {groups[k]} <b>{Object.keys(pack[k]).length}</b>
          </button>
        ))}
      </nav>
      <div className="db-layout">
        <section className="db-index">
          <div className="db-bar">
            <h2>{groups[g]}</h2>
            <button disabled={!latest || busy} onClick={() => begin()}>
              Создать
            </button>
          </div>
          <label>
            Поиск
            <input
              type="search"
              placeholder="Имя или ID"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
            />
          </label>
          <div className="db-filters">
            {filterOptions.length > 0 && (
              <Select
                label="Фильтр"
                value={filter}
                blank="Все"
                options={filterOptions}
                onChange={(v) => {
                  setFilter(v);
                  setPage(0);
                }}
              />
            )}
            <label>
              Сортировка
              <select
                value={order}
                onChange={(e) => {
                  setOrder(e.target.value);
                  setPage(0);
                }}
              >
                <option value="asc">А → Я</option>
                <option value="desc">Я → А</option>
              </select>
            </label>
          </div>
          <div className="db-list">
            {rows.slice(page * 10, page * 10 + 10).map(([id, name]) => {
              const e = pack[g][id];
              const subtitle = e.team
                ? pack.teams[e.team]?.name
                : e.region
                  ? regions[e.region]
                  : e.role
                    ? roles[e.role] || e.role
                    : null;
              return (
                <button
                  key={id}
                  aria-pressed={id === at.id}
                  onClick={() => move(g, id, true)}
                >
                  <strong>
                    <Identity name={name} visual={entityVisual(pack, g, id)} />
                  </strong>
                  <small>{subtitle || "↗"}</small>
                </button>
              );
            })}
            {!rows.length && <p>Записей по запросу нет.</p>}
          </div>
          <div className="db-pages">
            <small>
              {rows.length ? page * 10 + 1 : 0}–
              {Math.min(rows.length, page * 10 + 10)} из {rows.length}
            </small>
            <button
              aria-label="Предыдущие записи"
              disabled={!page}
              onClick={() => setPage((v) => v - 1)}
            >
              ←
            </button>
            <button
              aria-label="Следующие записи"
              disabled={(page + 1) * 10 >= rows.length}
              onClick={() => setPage((v) => v + 1)}
            >
              →
            </button>
          </div>
        </section>
        <section ref={card} className="db-card">
          {!r ? (
            <p>Выберите запись или создайте новую.</p>
          ) : (
            <>
              {editing ? (
                <header className="db-person">
                  <div>
                    <small>Редактирование · {groups[g]}</small>
                    <h2>{r.name || "Новая запись"}</h2>
                    <small>{at.id}</small>
                  </div>
                </header>
              ) : (
                <ProfileHeading
                  name={r.name}
                  subtitle={r.realName}
                  photo={
                    g === "players"
                      ? r.appearance
                      : entityVisual(pack, g, at.id).photo
                  }
                  visual={entityVisual(pack, g, at.id)}
                  type={
                    {
                      players: "Профиль игрока",
                      teams: "Профиль команды",
                      organizations: "Профиль организации",
                      staff: "Профиль сотрудника",
                      rosters: "Заявка состава",
                    }[g]
                  }
                  context={profile?.context || ""}
                  rating={g === "players" ? ratings?.overall : undefined}
                />
              )}
              {!editing && g === "players" && (
                <KitPreview
                  key={refKey(pack) + at.id}
                  pack={pack}
                  id={at.id}
                  selected={entityVisual(pack, g, at.id).kit?.id}
                />
              )}
              <div className="db-actions">
                {editing ? (
                  <>
                    <button
                      className="primary"
                      disabled={busy || !r.name.trim()}
                      onClick={() => save(r)}
                    >
                      Сохранить
                    </button>
                    <button
                      onClick={() => {
                        setDraft(null);
                        if (create) setAt({ group: g, id: firstId(pack, g) });
                        setCreate(false);
                      }}
                    >
                      Отмена
                    </button>
                    {!create && (
                      <button disabled={busy} onClick={() => begin(true)}>
                        Копировать
                      </button>
                    )}
                    {!create && (
                      <button
                        className="db-danger"
                        disabled={busy}
                        onClick={() => {
                          if (
                            window.confirm(
                              "Удалить запись «" +
                                r.name +
                                "» из новой редакции?",
                            )
                          )
                            void save(null);
                        }}
                      >
                        Удалить
                      </button>
                    )}
                  </>
                ) : (
                  <button
                    disabled={!latest || busy}
                    onClick={() => setDraft(structuredClone(r))}
                  >
                    Редактировать
                  </button>
                )}
              </div>
              <nav className="db-subtabs" aria-label="Вкладки карточки">
                {[
                  "Профиль",
                  ...(g === "players" ? ["Навыки · 58"] : []),
                  "Источники",
                  ...(history.length ? ["История"] : []),
                ].map((n) => (
                  <button
                    aria-pressed={section === n}
                    key={n}
                    onClick={() => setSection(n)}
                  >
                    {n}
                  </button>
                ))}
              </nav>
              {section === "Профиль" && (
                <div className="db-details">
                  {editing ? (
                    <div className="db-form">
                      <label>
                        Название
                        <input
                          value={r.name}
                          maxLength={240}
                          onChange={(e) => patch({ name: e.target.value })}
                        />
                      </label>
                      {g === "players" && (
                        <>
                          <PlayerEditorFields
                            r={r}
                            patch={patch}
                            asOf={pack.asOf}
                          />
                          <Select
                            label="Игровая роль"
                            value={r.role || ""}
                            options={Object.entries(roles)}
                            onChange={(v) => patch({ role: v || null })}
                          />
                          <Select
                            label="Статус контракта"
                            value={r.contract || ""}
                            options={[["free", "Свободный агент"]]}
                            onChange={(v) => patch({ contract: v || null })}
                          />
                          <label>
                            Потенциал
                            <input
                              type="number"
                              min="0"
                              max="100"
                              placeholder="Неизвестно"
                              value={r.potential ?? ""}
                              onChange={(e) =>
                                patch({
                                  potential:
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                })
                              }
                            />
                          </label>
                        </>
                      )}
                      {(g === "teams" ||
                        g === "organizations" ||
                        g === "staff") && (
                        <>
                          <label>
                            {g === "staff"
                              ? "Национальность"
                              : "Страна или регион"}
                            <input
                              value={r.nationality || ""}
                              onChange={(e) =>
                                patch({ nationality: e.target.value || null })
                              }
                            />
                          </label>
                          <PortraitEditor
                            value={g === "staff" ? r.photo : r.logo}
                            change={(v) =>
                              patch(g === "staff" ? { photo: v } : { logo: v })
                            }
                          />
                        </>
                      )}
                      {g === "teams" && (
                        <>
                          <KitEditor team={r} id={at.id} patch={patch} />
                          <Select
                            label="Регион"
                            value={r.region || ""}
                            options={Object.entries(regions)}
                            onChange={(v) => patch({ region: v || null })}
                          />
                          <Select
                            label="Тир"
                            value={String(r.tier || "")}
                            options={["1", "2", "3"].map((n) => [n, n])}
                            onChange={(v) =>
                              patch({ tier: v ? Number(v) : null })
                            }
                          />
                          <Select
                            label="Организация"
                            value={r.organization || ""}
                            options={orgs}
                            onChange={(v) => patch({ organization: v || null })}
                          />
                        </>
                      )}
                      {(g === "rosters" || g === "staff") && (
                        <Select
                          label="Команда"
                          value={r.team || ""}
                          options={teams}
                          onChange={(v) => patch({ team: v || null })}
                        />
                      )}
                      {g === "organizations" && (
                        <>
                          <label>
                            Год основания
                            <input
                              type="number"
                              min="1800"
                              max={pack.asOf.slice(0, 4)}
                              value={r.founded ?? ""}
                              onChange={(e) =>
                                patch({
                                  founded: e.target.value
                                    ? Number(e.target.value)
                                    : null,
                                })
                              }
                            />
                          </label>
                          <label>
                            Официальный сайт
                            <input
                              type="url"
                              value={r.website || ""}
                              onChange={(e) =>
                                patch({ website: e.target.value || null })
                              }
                            />
                          </label>
                        </>
                      )}
                      {g === "staff" && (
                        <>
                          <label>
                            Настоящее имя
                            <input
                              value={r.realName || ""}
                              onChange={(e) =>
                                patch({ realName: e.target.value || null })
                              }
                            />
                          </label>
                          <label>
                            Подготовка штаба
                            <input
                              type="number"
                              min="0"
                              max="100"
                              value={r.preparation}
                              onChange={(e) =>
                                patch({ preparation: Number(e.target.value) })
                              }
                            />
                          </label>
                        </>
                      )}
                      {g === "staff" && (
                        <label>
                          Должность
                          <input
                            value={r.role || ""}
                            onChange={(e) => patch({ role: e.target.value })}
                          />
                        </label>
                      )}
                      {g === "rosters" && (
                        <>
                          <label>
                            Дата заявки
                            <input
                              type="date"
                              max={pack.asOf}
                              value={r.date}
                              onChange={(e) => patch({ date: e.target.value })}
                            />
                          </label>
                          {[0, 1, 2, 3, 4].map((i) => (
                            <Select
                              key={i}
                              label={"Игрок " + (i + 1)}
                              value={r.players?.[i] || ""}
                              options={players}
                              blank="Свободный слот"
                              onChange={(v) => {
                                const slots = [...(r.players || [])];
                                slots[i] = v;
                                const lineup = slots.filter(Boolean);
                                patch({
                                  players: lineup,
                                  captain: lineup.includes(r.captain || "")
                                    ? r.captain
                                    : null,
                                });
                              }}
                            />
                          ))}
                          <Select
                            label="Капитан"
                            value={r.captain || ""}
                            options={(r.players || []).map((k) => [
                              k,
                              pack.players[k].name,
                            ])}
                            onChange={(v) => patch({ captain: v || null })}
                          />
                        </>
                      )}
                    </div>
                  ) : (
                    profile &&
                    (g === "players" ? (
                      <PlayerOverview
                        facts={profile.facts}
                        ratings={ratings}
                        ratingError={ratingError}
                        statistics={r.statistics}
                        performance={r.performance}
                        sample={r.sample}
                        maps={r.mapKnowledge || {}}
                        mastery={r.roleMastery || {}}
                        connections={profile.sections}
                        go={(group, id) => move(group, id, true)}
                      />
                    ) : (
                      <ClubOverview
                        facts={profile.facts}
                        sections={profile.sections}
                        go={(group, id) => move(group, id, true)}
                      />
                    ))
                  )}
                </div>
              )}
              {section === "Навыки · 58" && r.skills && !editing && (
                <AttributeGrid
                  values={r.skills}
                  provenance={Object.fromEntries(
                    Object.entries(r.skills).map(([k, v]) => [
                      k,
                      evidence(pack, r, "skills." + k, v).status,
                    ]),
                  )}
                />
              )}
              {section === "Навыки · 58" && r.skills && editing && (
                <div className="db-details">
                  <Select
                    label="Группа характеристик"
                    value={skillGroup}
                    options={Object.keys(skillGroups).map((k) => [k, k])}
                    onChange={(v) => v && setSkillGroup(v)}
                  />
                  {skillGroups[skillGroup].map((k) => (
                    <div className="db-skill" key={k}>
                      <label htmlFor={"skill-" + k}>{skillLabels[k]}</label>
                      <Source
                        origin={evidence(pack, r, "skills." + k, r.skills![k])}
                      />
                      {editing ? (
                        <input
                          id={"skill-" + k}
                          type="number"
                          min="0"
                          max="100"
                          value={r.skills![k]}
                          onChange={(e) =>
                            patch({
                              skills: {
                                ...r.skills,
                                [k]: Number(e.target.value),
                              },
                            })
                          }
                        />
                      ) : (
                        <strong>{r.skills![k]}</strong>
                      )}
                      <meter
                        min="0"
                        max="100"
                        value={r.skills![k]}
                        aria-label={skillLabels[k]}
                      />
                    </div>
                  ))}
                </div>
              )}
              {section === "Источники" && (
                <div className="db-details">
                  {[
                    ...fieldKeys,
                    ...Object.keys(r.fields).filter((k) =>
                      k.startsWith("skills."),
                    ),
                  ].map((k) => (
                    <div className="db-origin" key={k}>
                      <b>
                        {activeFieldNames[k] || skillLabels[k.split(".")[1]]}
                      </b>
                      <SourceLine
                        origin={evidence(
                          pack,
                          r,
                          k,
                          k.startsWith("skills.")
                            ? r.skills?.[k.split(".")[1]]
                            : r[k as keyof Entity],
                        )}
                      />
                    </div>
                  ))}
                </div>
              )}
              {section === "История" && (
                <div className="db-details">
                  {history.map(([k, h]) => (
                    <div className="db-origin" key={k}>
                      <small>
                        {h.date} · {h.event || "Встреча"}
                      </small>
                      <b>
                        {pack.teams[h.team].name} — {h.opponent} ·{" "}
                        {h.outcome === "W" ? "Победа" : "Поражение"}
                      </b>
                      <div className="db-links">
                        {h.players.map((pid) => entityLink("players", pid))}
                      </div>
                      <SourceLine origin={pack.origins[h.origin]} />
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>
      </div>
    </article>
  );
}
