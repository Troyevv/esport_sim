import "./recent-form.css";

export type FormResult = { id: string; won: boolean; detail: string };

/** Results are supplied in chronological order, oldest at the left. */
export function RecentForm({ results }: { results: FormResult[] }) {
  if (!results.length) return null;
  return (
    <span className="recent-form" role="list" aria-label="Форма от ранних встреч к последней">
      {results.map(({id, won, detail}) => {
        const label = (won ? "Победа" : "Поражение") + " · " + detail;
        return <span key={id} role="listitem" data-won={won} title={label} aria-label={label}>{won ? "В" : "П"}</span>;
      })}
    </span>
  );
}
