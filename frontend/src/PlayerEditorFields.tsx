import { resolvePortrait } from "./portraits";
import PortraitEditor from "./PortraitEditor";
import { roles, mapNames, type Entity } from "./databaseModel";

export default function PlayerEditorFields({
  r,
  patch,
  asOf,
}: {
  r: Entity;
  patch: (v: Partial<Entity>) => void;
  asOf: string;
}) {
  const st = r.statistics;
  return (
    <>
      <label>
        Настоящее имя
        <input
          value={r.realName || ""}
          maxLength={240}
          onChange={(e) => patch({ realName: e.target.value || null })}
        />
      </label>
      <label>
        Дата рождения
        <input
          type="date"
          max={asOf}
          value={r.born || ""}
          onChange={(e) => patch({ born: e.target.value || null })}
        />
      </label>
      {!r.born && (
        <label>
          Игровая оценка возраста
          <input
            type="number"
            min="14"
            max="60"
            value={r.ageEstimate ?? ""}
            onChange={(e) =>
              patch({
                ageEstimate: e.target.value ? Number(e.target.value) : null,
              })
            }
          />
        </label>
      )}
      <label>
        Национальность
        <input
          value={r.nationality || ""}
          maxLength={240}
          onChange={(e) => patch({ nationality: e.target.value || null })}
        />
      </label>
      <PortraitEditor
        layer
        value={r.appearance}
        change={(v) => patch({ appearance: resolvePortrait(v) })}
      />
      <PortraitEditor
        playerSource
        value={r.photo}
        change={(photo) => patch({ photo })}
      />
      <details className="db-editor-extra">
        <summary>Знание карт и освоение ролей</summary>
        <div className="db-form">
          {Object.entries(mapNames).map(([key, name]) => (
            <label key={key}>
              {name}
              <input
                type="number"
                min="0"
                max="100"
                value={r.mapKnowledge?.[key] ?? ""}
                onChange={(e) => {
                  const maps = { ...r.mapKnowledge };
                  if (e.target.value === "") delete maps[key];
                  else maps[key] = Number(e.target.value);
                  patch({ mapKnowledge: maps });
                }}
              />
            </label>
          ))}
          {Object.entries(roles).map(([k, name]) => (
            <label key={k}>
              {name}
              <input
                type="number"
                min="0"
                max="100"
                value={r.roleMastery?.[k] ?? ""}
                onChange={(e) => {
                  const mastery = { ...r.roleMastery };
                  if (e.target.value === "") delete mastery[k];
                  else mastery[k] = Number(e.target.value);
                  patch({ roleMastery: mastery });
                }}
              />
            </label>
          ))}
        </div>
      </details>
      <details className="db-editor-extra">
        <summary>Индивидуальная статистика</summary>
        {st ? (
          <div className="db-form">
            <label>
              Событие
              <input
                value={st.event}
                onChange={(e) =>
                  patch({ statistics: { ...st, event: e.target.value } })
                }
              />
            </label>
            <label>
              Противник
              <input
                value={st.opponent}
                onChange={(e) =>
                  patch({ statistics: { ...st, opponent: e.target.value } })
                }
              />
            </label>
            <label>
              Дата встречи
              <input
                type="date"
                value={st.date}
                max={asOf}
                onChange={(e) =>
                  patch({ statistics: { ...st, date: e.target.value } })
                }
              />
            </label>
            {(["maps", "kills", "deaths", "assists", "adr"] as const).map(
              (k, i) => (
                <label key={k}>
                  {["Карт", "Убийств", "Смертей", "Ассистов", "ADR"][i]}
                  <input
                    type="number"
                    min={k === "maps" ? 1 : 0}
                    value={st[k]}
                    onChange={(e) =>
                      patch({
                        statistics: { ...st, [k]: Number(e.target.value) },
                      })
                    }
                  />
                </label>
              ),
            )}
            <button onClick={() => patch({ statistics: null })}>
              Удалить наблюдение
            </button>
          </div>
        ) : (
          <button
            onClick={() =>
              patch({
                statistics: {
                  event: "",
                  date: asOf,
                  maps: 1,
                  kills: 0,
                  deaths: 0,
                  assists: 0,
                  adr: 0,
                  opponent: "",
                },
              })
            }
          >
            Добавить наблюдение
          </button>
        )}
      </details>
    </>
  );
}
