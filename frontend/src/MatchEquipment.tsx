import type { Agent } from "./Radar";
import { iconURL, itemLabel } from "./scorebotIcons";

export function ItemIcon({
  name,
  side,
  label,
  className = "",
}: {
  name: string;
  side?: string;
  label?: string;
  className?: string;
}) {
  const description = label || itemLabel(name, side);
  const src = iconURL(name, side);
  return src ? (
    <img
      data-item={name}
      className={"sb-icon " + className}
      src={src}
      alt={description}
      title={description}
      draggable={false}
    />
  ) : (
    <span>{description}</span>
  );
}

export function WeaponSlots({ a, dead }: { a?: Agent; dead: boolean }) {
  if (dead || !a) return <strong>{dead ? "Выбыл" : "Вне обзора"}</strong>;
  if (a.primary === undefined || a.secondary === undefined)
    return (
      <span className="gun-slots">
        {a.weapon && <ItemIcon name={a.weapon} className="visible-gun" />}
      </span>
    );
  return (
    <span className="gun-slots">
      {(
        [
          ["Основное", a.primary],
          ["Дополнительное", a.secondary],
        ] as const
      ).map(([slot, gun], i) => (
        <span
          key={slot}
          className={"gun-slot " + (i ? "secondary" : "primary-gun")}
          data-equipped={!!gun && gun === a.weapon}
        >
          {gun ? (
            <ItemIcon
              name={gun}
              label={
                slot +
                " · " +
                itemLabel(gun) +
                (gun === a.weapon ? " · в руках" : "")
              }
            />
          ) : (
            <span title={slot + " · пусто"} aria-label={slot + " · пусто"}>
              —
            </span>
          )}
        </span>
      ))}
    </span>
  );
}

export function Gear({
  a,
  dead,
  carrier,
}: {
  a?: Agent;
  dead: boolean;
  carrier: boolean;
}) {
  if (dead || !a || a.equipmentValue === undefined)
    return <span className="hud-kit">Снаряжение —</span>;
  const counts = new Map<string, number>();
  for (const g of a.utility || []) counts.set(g, (counts.get(g) || 0) + 1);
  return (
    <span className="hud-kit">
      {a.armor ? (
        <span className="gear-item">
          <ItemIcon name="Броня" label={"Броня · " + a.armor} />
          <b>{a.armor}</b>
        </span>
      ) : null}
      {a.helmet && <ItemIcon name="Шлем" />}
      {a.kit && <ItemIcon name="Набор" />}
      {Array.from(counts, ([g, n]) => (
        <span className="gear-item" key={g}>
          <ItemIcon
            name={g}
            side={a.team}
            label={itemLabel(g, a.team) + " ×" + n}
          />
          {n > 1 && <b>×{n}</b>}
        </span>
      ))}
      {carrier && <ItemIcon name="C4" className="carried-c4" />}
      {!a.armor && !a.kit && !counts.size && !carrier && (
        <span aria-label="Нет снаряжения">—</span>
      )}
    </span>
  );
}
