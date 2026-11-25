import { Avatar, Flag, Identity, type Visual } from "./SceneIdentity";
import {
  roles,
  mapNames,
  skillGroups,
  skillLabels,
  statuses,
  type Entity,
  type Group,
} from "./databaseModel";
import "./profiles.css";
import { resolvePortrait, photoLicenses, type PhotoRef } from "./portraits";

// Read-only projections. Callers supply disclosed values or observation ranges.
// No component in this module fetches an editor record or accepts a world/package.
type Observation = number | { low: number; high: number };
export type VisibleAttributes = Partial<Record<string, Observation>>;
export type ProfileLink = {
  group: Group;
  id: string;
  name: string;
  detail?: string;
  visual?: Visual;
};
export type Navigate = (group: Group, id: string) => void;
export type ProfileSection = {
  title: string;
  items: ProfileLink[];
  empty: string;
};
export type ProfileFact = { name: string; value: string; status?: string };
type Ratings = { overall: number; roles: Record<string, number> };
export function level(value: number) {
  return value >= 80
    ? "high"
    : value >= 60
      ? "good"
      : value >= 40
        ? "mid"
        : "low";
}
function Score({ value }: { value: Observation }) {
  return typeof value === "number" ? (
    <b className={"pf-score " + level(value)}>{value}</b>
  ) : (
    <b className="pf-score range">
      {value.low}–{value.high}
    </b>
  );
}
export function RoleRatings({
  values,
  compact = false,
}: {
  values: Record<string, number>;
  compact?: boolean;
}) {
  return (
    <span className={compact ? "role-ratings" : "pf-ratings"}>
      {compact && "Рейтинги ролей · "}
      {Object.entries(values).map(([role, v]) => (
        <span key={role}>
          {roles[role]} <Score value={v} />{" "}
        </span>
      ))}
    </span>
  );
}
export function AttributeGrid({
  values,
  provenance,
}: {
  values: VisibleAttributes;
  provenance?: Record<string, string>;
}) {
  return (
    <div className="pf-attributes">
      {Object.entries(skillGroups).map(([group, keys]) => {
        const visible = keys.filter((k) => values[k] !== undefined);
        if (!visible.length) return null;
        return (
          <section key={group}>
            <h3>
              {group}
              <small>{visible.length}</small>
            </h3>
            {visible.map((k) => (
              <div className="pf-attribute" key={k}>
                <span>{skillLabels[k]}</span>
                {provenance?.[k] && <small>{statuses[provenance[k]]}</small>}
                <Score value={values[k]!} />
              </div>
            ))}
          </section>
        );
      })}
    </div>
  );
}
export function ProfileHeading({
  name,
  subtitle,
  photo,
  visual,
  type,
  context,
  rating,
}: {
  name: string;
  subtitle?: string | null;
  photo?: PhotoRef;
  visual?: Visual;
  type: string;
  context: string;
  rating?: number;
}) {
  const asset = visual?.player && !visual.head ? null : resolvePortrait(photo);
  return (
    <header className="pf-heading">
      <div className="pf-portrait">
        <Avatar name={name} photo={photo} {...visual} />
      </div>
      <div className="pf-identity">
        <small>{type}</small>
        <div className="pf-title">
          <h2>{name}</h2>
          <Flag value={visual?.flag} />
        </div>
        {subtitle && <strong>{subtitle}</strong>}
        <span>{context}</span>
      </div>
      {rating !== undefined && (
        <div className="pf-overall" aria-label={"Общий рейтинг " + rating}>
          <strong>{rating}</strong>
          <small>OVR</small>
        </div>
      )}
      {asset && (
        <small className="pf-credit">
          <a href={asset.source} target="_blank" rel="noreferrer">
            {visual?.club
              ? "Эмблема"
              : visual?.player
                ? "Слой внешности"
                : "Фото"}{" "}
            · {asset.author}
          </a>{" "}
          ·{" "}
          <a
            href={photoLicenses[asset.license] || asset.source}
            target="_blank"
            rel="noreferrer"
          >
            {asset.license}
          </a>{" "}
          {asset.changes && " · " + asset.changes}
        </small>
      )}
    </header>
  );
}
export function ProfileLinks({
  section,
  go,
}: {
  section: ProfileSection;
  go: Navigate;
}) {
  return (
    <section className="pf-section">
      <h3>
        {section.title}
        <small>{section.items.length}</small>
      </h3>
      {section.items.length ? (
        <div className="pf-roster">
          {section.items.map((e) => (
            <button key={e.group + e.id} onClick={() => go(e.group, e.id)}>
              <strong>
                <Identity name={e.name} visual={e.visual} />
              </strong>
              <small>{e.detail || "Открыть"} ↗</small>
            </button>
          ))}
        </div>
      ) : (
        <p className="pf-empty">{section.empty}</p>
      )}
    </section>
  );
}
export function Facts({ rows }: { rows: ProfileFact[] }) {
  return (
    <dl className="pf-facts">
      {rows.map((r) => (
        <div key={r.name}>
          <dt>{r.name}</dt>
          <dd>
            {r.name === "Национальность" || r.name === "Принадлежность" ? (
              <Flag value={r.value === "Нет сведений" ? null : r.value} />
            ) : r.name === "Сайт" && r.value.startsWith("https://") ? (
              <a href={r.value} rel="noreferrer" target="_blank">
                {r.value.replace(/^https:\/\//, "")} ↗
              </a>
            ) : (
              r.value
            )}
          </dd>
          {r.status && <small>{statuses[r.status]}</small>}
        </div>
      ))}
    </dl>
  );
}
function Familiarity({
  title,
  values,
  names,
}: {
  title: string;
  values: Record<string, number>;
  names: Record<string, string>;
}) {
  return (
    <section className="pf-section">
      <h3>{title}</h3>
      {Object.entries(values).map(([k, v]) => (
        <div className="pf-bar" key={k}>
          <span>{names[k] || k}</span>
          <i aria-hidden>
            <i className={level(v)} style={{ width: v + "%" }} />
          </i>
          <Score value={v} />
        </div>
      ))}
    </section>
  );
}
export function PlayerOverview({
  facts,
  ratings,
  statistics,
  performance,
  sample,
  maps,
  mastery,
  connections,
  go,
  ratingError,
}: {
  facts: ProfileFact[];
  ratings: Ratings | null;
  statistics?: Entity["statistics"];
  performance?: Entity["performance"];
  sample?: Entity["sample"];
  maps: Record<string, number>;
  mastery: Record<string, number>;
  connections: ProfileSection[];
  go: Navigate;
  ratingError: string;
}) {
  const st = statistics;
  return (
    <div className="pf-body">
      <Facts rows={facts} />
      <section className="pf-section">
        <h3>
          Рейтинги по ролям <small>OVR / 100</small>
        </h3>
        {ratings ? (
          <RoleRatings values={ratings.roles} />
        ) : (
          <p className="pf-empty">{ratingError || "Рассчитываем рейтинги…"}</p>
        )}
      </section>
      <section className="pf-section">
        <h3>Статистика выступлений</h3>
        {performance && (
          <p>
            {performance.version} ·{" "}
            <strong>{performance.rating.toFixed(2)}</strong> ·{" "}
            {performance.maps} карт (
            {performance.window === "last 12 months"
              ? "за 12 месяцев"
              : performance.window}
            )
          </p>
        )}
        {sample && (
          <p>
            {sample.from} — {sample.until} · {sample.maps} карт · победы в
            сериях {sample.wins}/{sample.series}
          </p>
        )}
        {st ? (
          <>
            <p className="pf-caption">
              {st.event} · {st.date} · против {st.opponent} · карт {st.maps}
            </p>
            <Facts
              rows={[
                ["Убийства", st.kills],
                ["Смерти", st.deaths],
                ["Ассисты", st.assists],
                ["ADR", st.adr],
              ].map(([name, v]) => ({ name: String(name), value: String(v) }))}
            />
          </>
        ) : (
          !performance &&
          !sample && (
            <p className="pf-empty">В срезе нет индивидуальной статистики.</p>
          )
        )}
      </section>
      <div className="pf-split">
        <Familiarity title="Знание карт" values={maps} names={mapNames} />
        <Familiarity title="Освоение ролей" values={mastery} names={roles} />
      </div>
      {connections.map((s) => (
        <ProfileLinks key={s.title} section={s} go={go} />
      ))}
    </div>
  );
}
export function ClubOverview({
  facts,
  sections,
  go,
}: {
  facts: ProfileFact[];
  sections: ProfileSection[];
  go: Navigate;
}) {
  return (
    <div className="pf-body">
      <Facts rows={facts} />
      {sections.map((s) => (
        <ProfileLinks key={s.title} section={s} go={go} />
      ))}
    </div>
  );
}
