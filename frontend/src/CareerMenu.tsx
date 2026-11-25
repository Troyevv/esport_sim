import { useState, type ReactNode } from "react";
import { Brand, Dialog, Glyph } from "./GameUI";
import { date, type Summary } from "./careerData";
import { Avatar } from "./SceneIdentity";
export function CareerMenu({
  current,
  careers,
  create,
  resume,
  open,
  enabled,
  database,
  lab,
  settings,
}: {
  current: Summary | null;
  careers: Summary[];
  create: () => void;
  resume: () => void;
  open: (s: Summary) => void;
  enabled: boolean;
  database: () => void;
  lab: () => void;
  settings: ReactNode;
}) {
  const [load, setLoad] = useState(false);
  return (
    <section className="main-menu" aria-label="Главное меню">
      <header className="menu-top">
        <Brand />
        <span className="eyebrow">Твоя команда. Твои решения.</span>
        {settings}
      </header>
      <div className="menu-content">
        <section className="menu-copy">
          <div className="eyebrow">Counter-Strike · менеджер команды</div>
          <h1 aria-label="Главное меню">
            КАЖДЫЙ
            <br />
            РАУНД
            <br />
            <span>
              НАЧИНАЕТСЯ
              <br />С ТЕБЯ.
            </span>
          </h1>
          <p>
            Собери свою пятёрку. Найди собственный стиль. Проведи команду до
            решающего матча.
          </p>
          <div className="menu-buttons">
            {current && (
              <>
                <button className="btn primary" onClick={resume}>
                  Продолжить карьеру <Glyph name="player-play" />
                </button>
                <div className="continue-details">
                  {current.club} · {current.character} · {date(current.date)}
                </div>
              </>
            )}
            <button
              className={"btn " + (!current ? "primary" : "")}
              onClick={create}
            >
              Новая карьера <Glyph name="plus" />
            </button>
            <button className="btn ghost" onClick={() => setLoad(true)}>
              Загрузить сохранение <Glyph name="folder" />
            </button>
          </div>
        </section>
        <div className="menu-art">
          <img className="dragon" alt="" src="/interface/menu/spirit.png" />
          {["sh1ro", "zont1x", "donk"].map((p, i) => (
            <img
              key={p}
              className={"menu-player " + ["side left", "side", ""][i]}
              src={"/interface/menu/" + p + ".png"}
              alt=""
            />
          ))}
          <div className="menu-art-label">
            <span>
              <strong>TEAM SPIRIT</strong>
              <small>Counter-Strike</small>
            </span>
          </div>
        </div>
      </div>
      <footer className="menu-footer">
        <span>ESPORT SIM</span>
        <button onClick={database}>База сцены</button>
        <button onClick={lab}>Стенд симуляции</button>
      </footer>
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
