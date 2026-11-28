import { useState, type ReactNode } from "react";
import { Brand, Dialog, Glyph } from "./GameUI";
import { date, type Summary } from "./careerData";
import "./menu.css";
import { Avatar } from "./SceneIdentity";
export function CareerMenu({
  current,
  careers,
  create,
  resume,
  open,
  enabled,
  database,
  board,
  lab,
  settings,
}: {
  current: Summary | null;
  careers: Summary[];
  create: () => void;
  resume: () => void;
  open: (s: Summary) => void;
  enabled: boolean;
  database: (page?:"editor"|"exhibition"|"appearance") => void;
  board:()=>void;
  lab: () => void;
  settings: ReactNode;
}) {
  const [load, setLoad] = useState(false);
  return (
    <section className="root-menu" aria-label="Главное меню">
      <header className="menu-top"><Brand/>{settings}</header>
      <div className="root-menu-body">
        <div className="intro-hero"><div><div className="eyebrow">ESPORT SIM · TEAM MANAGER</div>
          <h1 className="intro-title" aria-label="Главное меню">ПЯТЬ ИГРОКОВ.<br/>ОДНА <em>АМБИЦИЯ.</em></h1>
          <p>Постройте команду, которая выдержит давление. Каждое решение ведёт к следующему раунду.</p>
          <div className="intro-actions">{current && <button className="btn primary" onClick={resume}>Продолжить карьеру</button>}
            <button className={"btn "+(!current?"primary":"")} onClick={create}>Новая карьера</button></div>
          {current && <small>{current.club} · {current.character} · {date(current.date)}</small>}</div>
          <div className="intro-players"><img src="/interface/menu/donk.png" alt="donk в форме Team Spirit"/><img src="/interface/menu/sh1ro.png" alt="sh1ro в форме Team Spirit"/></div>
        </div>
        <div className="intro-menu">{[
          {title:"Загрузить карьеру",label:"Загрузить сохранение",detail:"Слоты и резервные копии",glyph:"save",run:()=>setLoad(true)},
          {title:"Выставочный матч",detail:"Составы, подготовка, veto и трансляция",glyph:"player-play",run:()=>database("exhibition")},
          {title:"Редактор базы",label:"База сцены",detail:"Редакции команд, игроков и организаций",glyph:"book",run:()=>database("editor")},
          {title:"Тактическая доска",detail:"Карта, исполнители и цепочки действий",glyph:"crosshair",run:board},
          {title:"Лаборатория матчей",label:"Стенд симуляции",detail:"Настройка серии и воспроизводимый разбор",glyph:"report-analytics",run:lab},
          {title:"Студия образа",detail:"Портреты, форма и личные пакеты",glyph:"users",run:()=>database("appearance")}
        ].map(item=><button key={item.title} aria-label={item.label || item.title} onClick={item.run}><Glyph name={item.glyph}/><span>
          <strong>{item.title}</strong><small>{item.detail}</small></span></button>)}</div>
      </div>
      {load && (
        <Dialog title="Мои карьеры" close={() => setLoad(false)}>
          <div className="panel-body">
            {careers.length ? (
              careers.map((s) => (
                <div className="cr-save" key={s.id}>
                  <Avatar club name={s.club} />
                  <span>
                    <strong>{s.club}</strong>
                    <small>
                      {s.character} · {date(s.date)}
                    </small>
                  </span>
                  <button
                    className="btn"
                    disabled={!enabled}
                    onClick={() => open(s)}
                  >
                    Открыть
                  </button>
                </div>
              ))
            ) : (
              <p className="muted">Сохранённых карьер пока нет.</p>
            )}
          </div>
        </Dialog>
      )}
    </section>
  );
}
