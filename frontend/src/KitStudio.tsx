import { useState } from "react";
import { resolvePortrait } from "./portraits";
import { GamePortrait, kitDesign } from "./GamePortrait";
import {
  playerAppearance,
  teamKit,
  type Entity,
  type Pack,
} from "./databaseModel";

export function KitPreview({
  pack,
  id,
  selected,
}: {
  pack: Pack;
  id: string;
  selected?: string | null;
}) {
  const [override, choose] = useState<string | null>(null);
  const [comparison, setComparison] = useState<string[] | null>(null);
  const player = pack.players[id];
  const head = playerAppearance(pack, id)?.image;
  const current = override ?? selected ?? "";
  const options = Object.entries(pack.teams).sort(([, a], [, b]) =>
    a.name.localeCompare(b.name),
  );
  return (
    <details className="kit-studio">
      <summary>Примерочная формы</summary>
      <div className="kit-tools">
        <button
          type="button"
          aria-pressed={comparison !== null}
          onClick={() => {
            if (comparison) setComparison(null);
            else
              setComparison(
                [
                  current,
                  ...options
                    .map(([key]) => key)
                    .filter((key) => key !== current),
                ].slice(0, 3),
              );
          }}
        >
          {comparison ? "Один комплект" : "Сравнить комплекты"}
        </button>
      </div>
      {comparison ? (
        <section
          className="kit-comparison"
          aria-label={"Сравнение формы · " + player.name}
        >
          <header>
            <h3>{player.name}</h3>
            <p>
              {player.realName || player.name} ·{" "}
              {head ? "Студийный портрет" : "Нейтральная внешность"}
            </p>
          </header>
          <div className="kit-cards">
            {comparison.map((value, i) => {
              const kit = teamKit(pack, value);
              const design = kitDesign(kit);
              return (
                <article
                  key={i}
                  className="kit-card"
                  style={{ borderColor: design.accent }}
                >
                  <GamePortrait name={player.name} head={head} kit={kit} />
                  <label>
                    Комплект {i + 1}
                    <select
                      aria-label={"Команда комплекта " + (i + 1)}
                      value={value}
                      onChange={(e) =>
                        setComparison(
                          comparison.map((old, j) =>
                            j === i ? e.target.value : old,
                          ),
                        )
                      }
                    >
                      <option value="">Свободный агент</option>
                      {options.map(([key, t]) => (
                        <option value={key} key={key}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </article>
              );
            })}
          </div>
        </section>
      ) : (
        <div className="kit-preview">
          <GamePortrait
            name={player.name}
            head={head}
            kit={teamKit(pack, current)}
          />
          <div>
            <label>
              Комплект формы
              <select value={current} onChange={(e) => choose(e.target.value)}>
                <option value="">Свободный агент</option>
                {options.map(([k, t]) => (
                  <option key={k} value={k}>
                    {t.name}
                  </option>
                ))}
              </select>
            </label>
            <p>
              Игровой дизайн. Примерка сохраняет внешность игрока и действует
              только в этом окне.
            </p>
          </div>
        </div>
      )}
    </details>
  );
}

export function KitEditor({
  team,
  id,
  patch,
}: {
  team: Entity;
  id: string;
  patch: (values: Partial<Entity>) => void;
}) {
  const badge = resolvePortrait(team.logo);
  const kit = {
    id,
    name: team.name,
    design: team.kit,
    badge: badge?.image,
    badgeLicense: badge?.license,
  };
  const design = kitDesign(kit);
  return (
    <details className="db-editor-extra">
      <summary>Форма команды</summary>
      <div className="kit-preview">
        <GamePortrait name={team.name} kit={kit} />
        <div>
          {(["primary", "accent"] as const).map((k) => (
            <label key={k}>
              {k === "primary" ? "Основной цвет" : "Отделка"}
              <input
                type="color"
                value={design[k]}
                onChange={(e) =>
                  patch({ kit: { ...design, [k]: e.target.value } })
                }
              />
            </label>
          ))}
          <label>
            Рисунок
            <select
              value={design.pattern}
              onChange={(e) =>
                patch({
                  kit: {
                    ...design,
                    pattern: e.target.value as typeof design.pattern,
                  },
                })
              }
            >
              <option value="plain">Однотонная</option>
              <option value="sash">Диагональ</option>
              <option value="panels">Боковые вставки</option>
              <option value="chevron">Шеврон</option>
            </select>
          </label>
        </div>
      </div>
    </details>
  );
}
