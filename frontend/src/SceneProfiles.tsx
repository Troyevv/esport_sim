import { useEffect, useState } from "react";
import {
  roles,
  skillGroups,
  skillLabels,
  statuses,
  type Entity,
  type Group,
} from "./databaseModel";
import "./profiles.css";

// Read-only projections. Callers supply disclosed values or observation ranges.
// No component in this module fetches an editor record or accepts a world/package.
type Observation = number | { low: number; high: number };
export type VisibleAttributes = Partial<Record<string, Observation>>;
export type ProfileLink = {
  group: Group;
  id: string;
  name: string;
  detail?: string;
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
const photoPage =
  "https://commons.wikimedia.org/wiki/File:IEM_Chicago_Final_Edits-9731_ZywOo_(48353577846)_(cropped).jpg";
const photoUrl =
  "https://upload.wikimedia.org/wikipedia/commons/thumb/d/dd/IEM_Chicago_Final_Edits-9731_ZywOo_%2848353577846%29_%28cropped%29.jpg/250px-IEM_Chicago_Final_Edits-9731_ZywOo_%2848353577846%29_%28cropped%29.jpg";
function Portrait({ name, photo }: { name: string; photo?: string | null }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    setFailed(false);
  }, [photo]);
  return (
    <div className="pf-portrait">
      {photo && !failed ? (
        <img
          alt={name + " · IEM Chicago, 2019"}
          src={photoUrl}
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span aria-hidden>{name.slice(0, 2).toUpperCase()}</span>
      )}
    </div>
  );
}
export function ProfileHeading({
  name,
  subtitle,
  photo,
  type,
  context,
  rating,
}: {
  name: string;
  subtitle?: string | null;
  photo?: string | null;
  type: string;
  context: string;
  rating?: number;
}) {
  return (
    <header className="pf-heading">
      <Portrait name={name} photo={photo} />
      <div className="pf-identity">
        <small>{type}</small>
        <h2>{name}</h2>
        {subtitle && <strong>{subtitle}</strong>}
        <span>{context}</span>
      </div>
      {rating !== undefined && (
        <div className="pf-overall" aria-label={"Общий рейтинг " + rating}>
          <strong>{rating}</strong>
          <small>OVR</small>
        </div>
      )}
      {photo && (
        <small className="pf-credit">
          <a href={photoPage} target="_blank" rel="noreferrer">
            Фото · Esports Kingdom
          </a>{" "}
          ·{" "}
          <a
            href="https://creativecommons.org/licenses/by/2.0/"
            target="_blank"
            rel="noreferrer"
          >
            CC BY 2.0
          </a>{" "}
          · кадрирование
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
              <strong>{e.name}</strong>
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
            {r.name === "Сайт" && r.value.startsWith("https://") ? (
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
  maps,
  mastery,
  connections,
  go,
  ratingError,
}: {
  facts: ProfileFact[];
  ratings: Ratings | null;
  statistics?: Entity["statistics"];
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
          <p className="pf-empty">В срезе нет индивидуальной статистики.</p>
        )}
      </section>
      <div className="pf-split">
        <Familiarity
          title="Знание карт"
          values={maps}
          names={{ depo: "Депо" }}
        />
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
