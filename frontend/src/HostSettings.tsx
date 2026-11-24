import { useEffect, useRef, useState } from "react";
import { serverURL } from "./session";
import "./host-settings.css";

type Device = { id: string; name: string; pairedAt: number | null; connected: boolean };
type Host = {
  enabled: boolean; addresses: string[]; address: string | null; url: string | null;
  fingerprint: string | null; error: string | null; shutdownAvailable: boolean; devices: Device[];
};

async function hostRequest<T>(path: string, method = "GET", data?: unknown): Promise<T> {
  const response = await fetch(serverURL(path), {
    method, credentials: "include", cache: "no-store", signal: AbortSignal.timeout(15000),
    headers: data === undefined ? undefined : {"Content-Type": "application/json"},
    body: data === undefined ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(typeof error?.detail === "string" ? error.detail : "Не удалось выполнить запрос к домашнему серверу.");
  }
  return response.status === 204 ? undefined as T : response.json();
}

function NetworkGlyph() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" aria-hidden="true">
    <rect x="3" y="3" width="18" height="11" rx="2"/><path d="M12 14v5M4 20h16M6 8h4"/><circle cx="17" cy="9" r="1"/>
  </svg>;
}

function TrustInstructions({ fingerprint }: { fingerprint: string }) {
  return <details className="host-trust"><summary>Доверие к сертификату</summary>
    <p>Скачайте открытый сертификат этого ПК и передайте его на телефон через USB, AirDrop или другой доверенный канал. Перед установкой сравните отпечаток SHA-256 сертификата с отпечатком на экране ПК.</p>
    <div className="host-fingerprint"><span>SHA-256</span><code>{fingerprint}</code></div>
    <a className="host-download" href={serverURL("/api/host/authority.cer").href} download="esport-sim-ca.cer">Скачать сертификат (.cer)</a>
    <h4>iPhone и iPad</h4>
    <p>Откройте файл. В «Настройки» → «Основные» → «VPN и управление устройством» выберите загруженный профиль и установите его. Затем в «Основные» → «Об этом устройстве» → «Доверие сертификатам» включите полное доверие для этого УЦ.</p>
    <h4>Android</h4>
    <p>В настройках найдите «Установка сертификата» → «Сертификат ЦС», подтвердите выбор и откройте файл. Название раздела зависит от производителя. После установки откройте адрес сервера в браузере.</p>
  </details>;
}

function SettingsDialog({ close }: { close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [state, setState] = useState<Host | null>(null);
  const [address, setAddress] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [invite, setInvite] = useState<{code: string; qrDataUrl: string; until: number} | null>(null);
  const [confirm, setConfirm] = useState<string | null>(null);
  const [stopping, setStopping] = useState(false);
  const serial = useRef(0);
  const locked = useRef(false);
  const known = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (!invite) return;
    const id = window.setTimeout(() => setInvite(null), Math.max(0, invite.until - Date.now()));
    return () => window.clearTimeout(id);
  }, [invite]);

  function receive(next: Host) {
    setState(next);
    setAddress(old => next.enabled && next.address ? next.address : next.addresses.includes(old) ? old : next.addresses[0] || "");
    const previous = known.current;
    if (!next.enabled || next.devices.some(d => previous && !previous.has(d.id))) setInvite(null);
    known.current = new Set(next.devices.map(d => d.id));
  }
  async function refresh() {
    if (locked.current) return;
    const n = ++serial.current;
    try {
      const next = await hostRequest<Host>("/api/host");
      if (n === serial.current) { receive(next); setError(""); }
    } catch (e) {
      if (n === serial.current) setError(e instanceof Error ? e.message : "Сервер недоступен");
    }
  }
  useEffect(() => {
    dialog.current?.showModal();
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    void refresh();
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => {
      ++serial.current;
      window.clearInterval(timer);
      document.body.style.overflow = old;
    };
  }, []);
  async function action(op: () => Promise<void>) {
    if (locked.current) return;
    ++serial.current;
    locked.current = true;
    setBusy(true); setError("");
    try {
      await op();
      setConfirm(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Сервер недоступен"); }
    finally { locked.current = false; setBusy(false); }
  }
  const toggle = (enabled: boolean) => action(async () => {
    receive(await hostRequest<Host>("/api/host/lan", "POST", enabled ? {enabled, address} : {enabled}));
  });
  const revoke = (id: string) => action(async () => {
    await hostRequest("/api/host/devices/" + encodeURIComponent(id), "DELETE");
    receive(await hostRequest<Host>("/api/host"));
  });
  const issue = () => action(async () => {
    const next = await hostRequest<{code: string; qrDataUrl: string; expiresIn: number}>("/api/host/invite", "POST");
    setInvite({code: next.code, qrDataUrl: next.qrDataUrl, until: Date.now() + next.expiresIn * 1000});
  });
  const shutdown = () => action(async () => {
    await hostRequest("/api/host/shutdown", "POST");
    setStopping(true);
  });
  return <dialog ref={dialog} className="host-dialog" aria-labelledby="host-title" onClose={close}>
    <header className="host-titlebar">
      <div className="host-heading"><div className="host-emblem"><NetworkGlyph/></div><div><span>ESPORT_SIM</span><h2 id="host-title">Домашний сервер</h2></div></div>
      <button className="host-x" aria-label="Закрыть настройки" onClick={() => dialog.current?.close()} autoFocus>×</button>
    </header>
    <div className="host-sections">
    {stopping ? <p role="status">Завершается работа сервера. Это окно можно закрыть.</p> : <>
      {error && <p className="host-error" role="alert">{error}</p>}
      {!state && <p role="status">Загружаем настройки…</p>}
      {state && <>
        <section className="host-block">
          <div className="host-sectionhead"><h3>Локальная сеть</h3><span className={state.enabled ? "host-tag active" : "host-tag"}>{state.enabled ? "Доступ открыт" : "Только этот ПК"}</span></div>
          <p>Подключите телефон или планшет к той же домашней сети, что и этот ПК.</p>
          <div className="host-address-row"><label>Сетевой интерфейс<select value={address} disabled={busy || state.enabled || !state.addresses.length} onChange={e => setAddress(e.target.value)}>
            {!state.addresses.length && <option value="">Нет доступного IPv4-адреса</option>}
            {state.addresses.map(ip => <option key={ip}>{ip}</option>)}
          </select></label>
          <button className={state.enabled ? "" : "host-action"} disabled={busy || (!state.enabled && !address)} onClick={() => void toggle(!state.enabled)}>{state.enabled ? "Отключить LAN" : "Включить LAN"}</button></div>
          {state.error && <p className="host-error" role="alert">{state.error}</p>}
        </section>
        {state.enabled && state.url && <section className="host-block">
          <h3>Подключение телефона</h3>
          {state.fingerprint && <TrustInstructions fingerprint={state.fingerprint}/>}
          <div className="host-pairing"><img src={invite?.qrDataUrl || serverURL("/api/host/qr.svg?address=" + encodeURIComponent(state.url)).href} alt={invite ? "QR-код одноразового приглашения" : "QR-код адреса сервера"} width="128" height="128"/>
          <div><h4>Адрес сервера</h4><code className="host-url">https://<wbr/><span>{new URL(state.url).host}</span></code>
            <p>{invite ? "Отсканируйте приглашение на телефоне. Код заполнится автоматически. Проверьте название устройства и нажмите «Подключить»." : "После установки сертификата выдайте код, чтобы показать QR-приглашение. Также можно открыть этот адрес и ввести код вручную."}</p></div></div>
          <div className="host-invite"><div><h4>Одноразовый код</h4><p>Введите его на телефоне в течение 10 минут. Новый код заменяет предыдущий.</p></div>
          <button className="host-action" disabled={busy} onClick={() => void issue()}>Выдать код</button></div>
          {invite && <output aria-label="Одноразовый код" className="host-code">{invite.code}</output>}
        </section>}
        <section className="host-block"><div className="host-sectionhead"><h3>Разрешённые устройства</h3><span className="host-total">{state.devices.length}</span></div>
          {!state.devices.length && <p>Список появится после первого подключения по коду.</p>}
          <ul className="host-devices">{state.devices.map(device => <li key={device.id}>
            <div><strong>{device.name}</strong><small>{device.connected ? "На связи" : "Вне сети"}{device.pairedAt ? " · С " + new Date(device.pairedAt * 1000).toLocaleDateString("ru-RU") : ""}</small></div>
            {confirm === device.id
              ? <div className="host-confirm"><button disabled={busy} onClick={() => setConfirm(null)}>Отмена</button><button className="host-danger" disabled={busy} onClick={() => void revoke(device.id)}>Подтвердить отзыв</button></div>
              : <button disabled={busy} onClick={() => setConfirm(device.id)}>Отозвать доступ</button>}
          </li>)}</ul>
        </section>
        {state.shutdownAvailable && <section className="host-block host-stop"><h3>Завершение работы</h3>
          {confirm === "shutdown" ? <><p>Сервер закроется, все устройства будут отключены. Для продолжения запустите приложение снова.</p><div className="host-confirm"><button disabled={busy} onClick={() => setConfirm(null)}>Отмена</button><button disabled={busy} className="host-danger" onClick={() => void shutdown()}>Подтвердить остановку</button></div></>
            : <button disabled={busy} onClick={() => setConfirm("shutdown")}>Остановить приложение</button>}
        </section>}
      </>}
    </>}</div>
  </dialog>;
}

export default function HostSettings({ connected }: { connected: boolean }) {
  const [available, setAvailable] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let mounted = true;
    const check = () => hostRequest<{hostSettings: boolean}>("/api/capabilities")
      .then(data => { if (mounted) setAvailable(data.hostSettings); }).catch(() => {});
    void check();
    window.addEventListener("online", check);
    return () => { mounted = false; window.removeEventListener("online", check); };
  }, [connected]);
  if (!available) return null;
  return <><button className="host-trigger" aria-label="Настройки сервера" onClick={() => setOpen(true)}><NetworkGlyph/><span>Настройки сервера</span></button>
    {open && <SettingsDialog close={() => setOpen(false)}/>}</>;
}
