import { useMemo, useState } from "react";
import { Dialog, Glyph } from "./GameUI";
import { EntityName } from "./CareerIdentity";

type Directory = Record<string, string | { name: string; realName?: string | null }>;
type Choice = {
  group: "players" | "teams";
  options: Directory;
  label: string;
  value: string;
  select: (id: string) => void;
  empty?: string;
  exclude?: string;
};
const nameOf = (row: Directory[string] | undefined) => typeof row === "string" ? row : row?.name;

function PickerDialog({group, options, label, value, select, empty, exclude, close}: Choice & {close: () => void}) {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const sorted = useMemo(() => Object.entries(options)
    .filter(([id]) => id !== exclude)
    .sort(([, a], [, b]) => (nameOf(a) || "").localeCompare(nameOf(b) || "", "ru")), [options, exclude]);
  const term = query.trim().toLowerCase();
  const matches = sorted.filter(([, row]) => {
    const alias = typeof row === "object" ? row.realName || "" : "";
    return (nameOf(row) + " " + alias).toLowerCase().includes(term);
  });
  const size = 15;
  const last = Math.max(0, Math.ceil(matches.length / size) - 1);
  const current = Math.min(page,last);
  const choose = (id: string) => { select(id); close(); };
  return <Dialog title={label} close={close}>
    <div className="entity-picker">
      <label className="entity-search"><Glyph name="search"/>
        <input autoFocus type="search" value={query} aria-label="Поиск в списке" placeholder={group==="players" ? "Никнейм или имя" : "Название команды"}
          onKeyDown={e=>{
            if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); }
          }}
          onChange={e=>{setQuery(e.target.value);setPage(0)}}/></label>
      {empty && <button className="btn" aria-pressed={value===""} onClick={()=>choose("")}>{empty}</button>}
      <div key={term+"/"+current} className="entity-picker-list">
        {matches.slice(current*size,(current+1)*size).map(([id,row]) =>
          <button type="button" key={id} aria-pressed={value===id} onClick={()=>choose(id)}>
            <EntityName group={group} id={id} fallback={nameOf(row)} link={false}/>
            {id===value && <span aria-label="Выбрано">Выбрано</span>}
          </button>)}
        {!matches.length && <p role="status">Совпадений нет. Измените поисковый запрос.</p>}
      </div>
      {last>0 && <nav aria-label="Страницы списка">
        <button className="btn" disabled={current===0} onClick={()=>setPage(current-1)}>Назад</button>
        <span aria-live="polite">{current+1} / {last+1}</span>
        <button className="btn" disabled={current===last} onClick={()=>setPage(current+1)}>Далее</button>
      </nav>}
    </div>
  </Dialog>;
}

export function EntityPicker(props: Choice) {
  const [open, setOpen] = useState(false);
  const {value, options, group, label, empty} = props;
  const selected = nameOf(options[value]);
  return <div className="entity-picker-field">
    <span>{label}</span>
    <button type="button" className="entity-picker-trigger" aria-haspopup="dialog" aria-expanded={open}
      aria-label={label+" · "+(selected || empty || "Выбрать")} onClick={()=>setOpen(true)}>
      {value ? <EntityName id={value} group={group} fallback={selected} link={false}/> : empty || "Выбрать"}
      <Glyph name="chevron-down"/>
    </button>
    {open && <PickerDialog {...props} close={()=>setOpen(false)}/>}
  </div>;
}
