import { useEffect, useRef, type ReactNode } from "react";
export function Glyph({ name }: { name: string }) {
  return (
    <img
      className="ui-icon"
      src={"/interface/ui/" + name + ".svg"}
      alt=""
      aria-hidden="true"
    />
  );
}
export function Brand({ menu }: { menu?: () => void }) {
  const content = (
    <>
      <span className="brand-symbol">
        <Glyph name="crosshair" />
      </span>
      <span className="brand-name">
        ESPORT SIM<small>TEAM MANAGER</small>
      </span>
    </>
  );
  return menu ? (
    <button className="brand" aria-label="← Главное меню" onClick={menu}>
      {content}
    </button>
  ) : (
    <div className="brand">{content}</div>
  );
}
export function Heading({
  title,
  sub,
  children,
}: {
  title: string;
  sub?: string;
  children?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <h1>{title}</h1>
        {sub && <p className="subtitle">{sub}</p>}
      </div>
      {children && <div className="page-actions">{children}</div>}
    </div>
  );
}
export function Dialog({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const el = dialog.current!;
    el.showModal();
    return () => el.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="ui-dialog"
      aria-label={title}
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-button" aria-label="Закрыть" onClick={close}>
            <Glyph name="x" />
          </button>
        </div>
        {children}
      </div>
    </dialog>
  );
}
export function Tabs({
  items,
  value,
  change,
}: {
  items: string[];
  value: string;
  change: (s: string) => void;
}) {
  return (
    <div className="view-tabs">
      {items.map((t) => (
        <button
          key={t}
          aria-pressed={value === t}
          className={"view-tab " + (value === t ? "active" : "")}
          onClick={() => change(t)}
        >
          {t}
        </button>
      ))}
    </div>
  );
}

export function Readiness({ fatigue }: { fatigue: number | undefined }) {
  if (fatigue === undefined) return <>—</>;
  const value = 100 - fatigue;
  return (
    <span className="status-measure">
      <span className="meter">
        <span style={{ width: value + "%" }} />
      </span>
      {value}%
    </span>
  );
}
