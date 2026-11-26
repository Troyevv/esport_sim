import { date, type Decision } from "./careerData";
import { Dialog } from "./GameUI";

const actionLabel: Record<Decision["action"], string> = {
  calendar: "Выбрать турнир",
  entry: "Открыть заявку",
  play: "В матч-центр",
  match: "В матч-центр",
  repair: "Проверить и восстановить карты",
  retry: "Повторить расчёт",
  overview: "Открыть турнир",
  inbox: "Во входящие",
};
export function ManagerAttention({
  items,
  open,
  close,
  resolve,
  repair,
  quick,
  enabled,
  error,
  saves,
}: {
  items: Decision[];
  open: boolean;
  close: () => void;
  enabled: boolean;
  resolve: (item: Decision) => void;
  repair: () => void;
  quick: () => void;
  error: string;
  saves: () => void;
}) {
  if (!open) return null;
  return (
    <Dialog title="Центр решений" close={close}>
      <div className="decision-list">
        {(["required", "warning", "info"] as const).map((level) => {
          const rows = items.filter((item) => item.level === level);
          if (!rows.length) return null;
          return (
            <section key={level} data-level={level}>
              <h3>
                {
                  {
                    required: "Требуют решения",
                    warning: "Предупреждения",
                    info: "Уведомления",
                  }[level]
                }{" "}
                <span>{rows.length}</span>
              </h3>
              {rows.map((row) => (
                <article key={row.id}>
                  <div>
                    <time>{date(row.due)}</time>
                    <strong>{row.title}</strong>
                    <p>{row.detail}</p>
                  </div>
                  <button
                    className="btn"
                    disabled={!enabled}
                    onClick={() => resolve(row)}
                  >
                    {actionLabel[row.action]}
                  </button>
                  {row.action === "play" && <button className="btn" disabled={!enabled} onClick={quick}>Быстро рассчитать матч</button>}
                  {row.action === "retry" && (
                    <button
                      className="btn"
                      disabled={!enabled}
                      onClick={repair}
                    >
                      Проверить ресурсы карт
                    </button>
                  )}
                  {row.action === "retry" && (
                    <button className="btn" onClick={saves}>
                      Открыть сохранения
                    </button>
                  )}
                </article>
              ))}
            </section>
          );
        })}
        {!items.some((r) => r.level === "required") && (
          <p role="status">Можно продолжить календарь.</p>
        )}
        {error && (
          <section>
            <p role="alert">{error}</p>
            <button className="btn" disabled={!enabled} onClick={repair}>Проверить ресурсы карт</button>
            <button className="btn" onClick={saves}>
              Открыть сохранения
            </button>
          </section>
        )}
      </div>
    </Dialog>
  );
}
