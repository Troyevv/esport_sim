import { useState } from "react";
import { GamePortrait, kitDesign } from "./GamePortrait";
import { teamKit, type Entity, type Pack } from "./databaseModel";

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
  const player = pack.players[id];
  const current = override ?? selected ?? "";
  const options = Object.entries(pack.teams).sort(([, a], [, b]) =>
    a.name.localeCompare(b.name),
  );
  return (
    <details className="kit-studio">
      <summary>Примерочная формы</summary>
      <div className="kit-preview">
        <GamePortrait
          name={player.name}
          head={player.appearance?.image}
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
  const kit = { id, name: team.name, design: team.kit };
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
