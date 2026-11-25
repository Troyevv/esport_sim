import { useEffect, useRef, useState, type ReactNode } from "react";
import { Application, Assets, Container, Graphics, Sprite, Text, Texture } from "pixi.js";
import type { RadarPlayback } from "./playback";
import { serverURL, type Frame } from "./session";
import "./radar.css";
import { drawEvents, RadarEquipment } from "./matchRadar";

type Point = { x: number; y: number; z?: number };
type Rect = Point & { w: number; h: number };
type Team = "T" | "CT";
export interface RadarMap {
  id: string;
  name: string;
  version: string | number;
  author: string;
  width: number;
  height: number;
  radar?: string;
  layers?: Record<string, {AltitudeMin: string; AltitudeMax: string}>;
  walls: Rect[];
  zones: (Rect & { name: string })[];
  spawns: (Point & { team: Team })[];
}
export interface Agent extends Point {
  id: string;
  name: string;
  team: Team;
  heading: number;
  hp?: number; armor?: number; cash?: number; ammo?: number; reserve?: number; weapon?: string;
  primary?: string | null; secondary?: string | null;
  utility?: string[]; kit?: boolean; helmet?: boolean; equipmentValue?: number; alive?: boolean;
  visible: string[];
  knowledge: (Point & { id: string; tick: number })[];
  status: string;
}
interface Props {
  layer?: string;
  frame: Frame;
  playback: RadarPlayback;
  connected: boolean;
  selected: string | null;
  onSelect: (id: string) => void;
}

const colors = { CT: 0x55d9c9, T: 0xffb56d };
const mono = "Consolas, Menlo, monospace";
const limit = (n: number, min: number, max: number) =>
  Math.max(min, Math.min(max, n));

function label(
  text: string,
  size: number,
  fill: number,
  weight: "bold" | "normal" = "normal",
) {
  const item = new Text({
    text,
    style: { fontFamily: mono, fontSize: size, fill, fontWeight: weight },
    resolution: 3,
  });
  item.anchor.set(0.5);
  return item;
}

export function onLayer(map: RadarMap, layer: string, z?: number) {
  const limits = map.layers?.[layer];
  if (!limits || z === undefined) return true;
  return z * 12 >= Number(limits.AltitudeMin) && z * 12 < Number(limits.AltitudeMax);
}

export function drawPlan(map: RadarMap, layer = "default", redraw = () => {}, failed = () => {}) {
  const plan = new Container();
  if (map.radar) {
    const url = serverURL(map.radar);
    url.searchParams.set("layer", layer);
    void Assets.load<Texture>(url.href)
      .then(texture => {
        if (plan.destroyed) return;
        const background = plan.addChild(new Sprite(texture));
        background.width = map.width;
        background.height = map.height;
        redraw();
      }).catch(() => { if (!plan.destroyed) failed(); });
    return plan;
  }
  const lines = new Graphics();
  plan.addChild(lines);
  const { width, height } = map;
  lines.rect(0, 0, width, height).fill(0x1d3033);
  for (let x = 0; x < width; x += 10) lines.moveTo(x, 0).lineTo(x, height);
  for (let y = 0; y < height; y += 10) lines.moveTo(0, y).lineTo(width, y);
  lines.stroke({ color: 0x7ba6a6, alpha: 0.12, width: 0.3 });
  for (let x = 0; x < width; x += 50) {
    lines.moveTo(x, -2).lineTo(x, -3.8);
    const tick = label(String(x), 6.2, 0x99aeae);
    tick.position.set(x, -7);
    plan.addChild(tick);
  }
  for (let y = 0; y < height; y += 50) {
    lines.moveTo(-2, y).lineTo(-3.8, y);
    const tick = label(String(y), 6.2, 0x99aeae);
    tick.position.set(-10, y);
    plan.addChild(tick);
  }
  lines.stroke({ color: 0x789497, width: 0.5 });
  for (const zone of map.zones) {
    const { x, y, w, h } = zone;
    lines.rect(x, y, w, h).fill({ color: 0xedc578, alpha: 0.16 });
    for (let start = -h; start < w; start += 3.2) {
      const first = Math.max(0, -start);
      const last = Math.min(h, w - start);
      lines
        .moveTo(x + start + first, y + first)
        .lineTo(x + start + last, y + last);
    }
    lines.stroke({ color: 0xf2cb84, alpha: 0.35, width: 0.45 });
    lines.rect(x, y, w, h).stroke({ color: 0xdfbb7d, width: 0.8 });
    const letter = label(zone.name, Math.min(w, h) * 0.72, 0xffdc99, "bold");
    letter.position.set(x + w / 2, y + h / 2);
    plan.addChild(letter);
  }
  for (const { x, y, w, h } of map.walls) {
    lines.rect(x, y, w, h).fill(0x34494e);
    // Roof seams run along the short axis, inset inside the solid footprint.
    const alongX = w > h;
    const span = alongX ? w : h;
    if (Math.min(w, h) >= 4) {
      for (let offset = 2; offset < span - 1; offset += 3) {
        if (alongX)
          lines.moveTo(x + offset, y + 1).lineTo(x + offset, y + h - 1);
        else lines.moveTo(x + 1, y + offset).lineTo(x + w - 1, y + offset);
      }
      lines.stroke({ color: 0x91aaaa, alpha: 0.2, width: 0.35 });
    }
    lines
      .rect(x, y, w, h)
      .stroke({ color: 0x96abad, alpha: 0.85, width: 0.6, alignment: 0 });
    lines
      .moveTo(x + w, y)
      .lineTo(x + w, y + h)
      .lineTo(x, y + h)
      .stroke({ color: 0x142428, width: 0.7, alignment: 0 });
  }
  for (const spawn of map.spawns) {
    lines
      .circle(spawn.x, spawn.y, 2.1)
      .stroke({ color: colors[spawn.team], alpha: 0.5, width: 0.55 });
    lines
      .moveTo(spawn.x - 3.2, spawn.y)
      .lineTo(spawn.x - 1.1, spawn.y)
      .moveTo(spawn.x + 1.1, spawn.y)
      .lineTo(spawn.x + 3.2, spawn.y)
      .stroke({ color: colors[spawn.team], alpha: 0.52, width: 0.55 });
  }
  lines
    .rect(0, 0, width, height)
    .stroke({ color: 0x9db6b4, alpha: 0.6, width: 0.6 });
  return plan;
}

type RadarApi = {
  destroy: () => void;
  update: (props: Props) => void;
  resize: () => void;
  reset: () => void;
  zoomBy: (ratio: number, at?: Point) => void;
  panBy: (x: number, y: number) => void;
  selectAt: (at: Point) => void;
};

function marker(agent: Agent, match: boolean) {
  const group = new Container({ label: agent.id });
  const color = colors[agent.team];
  const ring = new Graphics()
    .circle(0, 0, 1.45)
    .stroke({ color: 0xffffff, width: 0.22 });
  const tip = new Graphics()
    .poly([0.95, -0.53, 2.15, 0, 0.95, 0.53])
    .fill(color);
  const body = new Graphics();
  if (agent.team === "T") body.roundRect(-1, -1, 2, 2, 0.34);
  else body.circle(0, 0, 1);
  body.fill(color).stroke({ color: 0x0f1a1d, width: 0.22 });
  const text = label(
    agent.id.match(/\d+$/)?.[0] ?? agent.name.slice(0, 1),
    14,
    0x142526,
    "bold",
  );
  text.scale.set(1.52 / 14);
  group.addChild(tip, ring, body, text);
  if (match) {
    const nick = label(agent.name, 12, color, "bold");
    nick.scale.set(0.075);
    nick.position.y = 1.9;
    group.addChild(nick);
  }
  return { group, tip, ring, team:agent.team };
}

function setupScene(
  app: Application,
  host: HTMLDivElement,
  props: Props,
  zoomLabel: (n: number) => void,
  failed: () => void,
) {
  let current = props,
    zoom = 1,
    fit = 1;
  const pan = { x: 0, y: 0 };
  const world = new Container({ label: "map" });
  let plan = drawPlan(props.frame.world.map, props.layer, redraw, failed);
  if (!props.frame.world.map.radar) plan.cacheAsTexture({ resolution: 3, antialias: true });
  const players = new Container({ label: "players" });
  const markers = new Map<string, ReturnType<typeof marker>>();
  const playback = props.playback;
  app.stage.addChild(world);
  const effects = new Graphics();
  const items = new RadarEquipment(schedule);
  world.addChild(plan, effects, items, players);
  let dirty = true;
  let request = 0;
  function present(now: number) {
    request = 0;
    let changed = dirty;
    for (const a of current.frame.world.agents) {
      const m = markers.get(a.id)!;
      const visible = playback.has(a.id) && onLayer(current.frame.world.map, current.layer || 'default', a.z);
      if (m.group.visible !== visible) { m.group.visible = visible; changed = true; }
      if (!visible) continue;
      const p = playback.sample(a.id, now);
      if (
        m.group.x !== p.x ||
        m.group.y !== p.y ||
        m.tip.rotation !== p.heading
      ) {
        m.group.position.set(p.x, p.y);
        m.tip.rotation = p.heading;
        changed = true;
      }
    }
    const match = current.frame.world.match;
    if (match) {
      const tick = playback.displayTick(now);
      const id = match.bomb?.carrier;
      const carrier = id && playback.has(id) ? playback.sample(id, now) : undefined;
      items.begin();
      drawEvents(effects, match, tick, items, carrier, z => onLayer(current.frame.world.map, current.layer || "default", z));
      items.end();
      changed = true;
    }
    if (changed) app.render();
    dirty = false;
    host.dataset.ready ||= "true";
    if (current.connected && current.frame.running) schedule();
  }
  function redraw() { dirty = true; schedule(); }
  function schedule() {
    if (!request) request = requestAnimationFrame(present);
  }
  function camera() {
    const scale = fit * zoom;
    const map = current.frame.world.map;
    const { width, height } = app.screen;
    pan.x = limit(pan.x, (-scale * map.width) / 2, (scale * map.width) / 2);
    pan.y = limit(pan.y, (-scale * map.height) / 2, (scale * map.height) / 2);
    world.scale.set(scale);
    world.position.set(
      (width - scale * map.width) / 2 + pan.x,
      (height - scale * map.height) / 2 + pan.y,
    );
    const radius = limit(4.5 * scale, 6.3, 13) / scale;
    for (const m of markers.values()) m.group.scale.set(radius);
    host.dataset.zoom = zoom.toFixed(3);
    host.dataset.panX = pan.x.toFixed(2);
    host.dataset.panY = pan.y.toFixed(2);
    dirty = true;
    schedule();
  }
  function resize() {
    const w = Math.max(1, host.clientWidth),
      h = Math.max(1, host.clientHeight);
    app.renderer.resize(w, h);
    const map = current.frame.world.map;
    fit = Math.min(w / (map.width + 38), h / (map.height + 46));
    camera();
  }
  const api: RadarApi = {
    update(next) {
      const oldMap = current.frame.world.map,
        map = next.frame.world.map;
      const changed = oldMap.id !== map.id || oldMap.version !== map.version || current.layer !== next.layer;
      current = next;

      for (const [id, m] of markers) {
        if (changed || !next.frame.world.agents.some((a) => a.id === id && a.team === m.team)) {
          m.group.destroy({ children: true });
          markers.delete(id);
          dirty = true;
        }
      }
      for (const a of next.frame.world.agents) {
        let m = markers.get(a.id);
        if (!m) {
          m = marker(a, !!next.frame.world.match);
          markers.set(a.id, m);
          players.addChild(m.group);
          const scale = fit * zoom;
          m.group.scale.set(limit(4.5 * scale, 6.3, 13) / scale);
          dirty = true;
        }
        m.group.alpha = a.alive === false ? 0.32 : 1;
        if (m.ring.visible !== (a.id === next.selected)) {
          m.ring.visible = a.id === next.selected;
          dirty = true;
        }
      }
      if (changed) {
        plan.destroy({ children: true });
        plan = drawPlan(map, next.layer, redraw, failed);
        if (!map.radar) plan.cacheAsTexture({ resolution: 3, antialias: true });
        world.addChildAt(plan, 0);
        api.reset();
        resize();
      }
      schedule();
    },
    resize,
    destroy() {
      cancelAnimationFrame(request);
    },
    reset() {
      zoom = 1;
      pan.x = pan.y = 0;
      zoomLabel(zoom);
      camera();
    },
    zoomBy(ratio, at) {
      const next = limit(zoom * ratio, 0.8, 4);
      if (next === zoom) return;
      const x = (at?.x ?? app.screen.width / 2) - app.screen.width / 2;
      const y = (at?.y ?? app.screen.height / 2) - app.screen.height / 2;
      pan.x = x - ((x - pan.x) * next) / zoom;
      pan.y = y - ((y - pan.y) * next) / zoom;
      zoom = next;
      zoomLabel(zoom);
      camera();
    },
    panBy(dx, dy) {
      pan.x += dx;
      pan.y += dy;
      camera();
    },
    selectAt(at) {
      let nearest = Math.max(12, 5 * world.scale.x),
        target: string | undefined;
      for (const [id, { group }] of markers) {
        if (!group.visible) continue;
        const d = Math.hypot(
          at.x - world.x - group.x * world.scale.x,
          at.y - world.y - group.y * world.scale.y,
        );
        if (d < nearest) {
          nearest = d;
          target = id;
        }
      }
      if (target) current.onSelect(target);
    },
  };
  api.update(props);
  resize();
  return api;
}

function bindNavigation(host: HTMLDivElement, api: RadarApi) {
  const pointers = new Map<number, Point>();
  let tapped: Point | null = null;
  function local(e: PointerEvent | WheelEvent) {
    const rect = host.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }
  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    const point = local(e);
    pointers.set(e.pointerId, point);
    tapped = pointers.size === 1 ? point : null;
    host.setPointerCapture(e.pointerId);
  }
  function move(e: PointerEvent) {
    if (!pointers.has(e.pointerId)) return;
    const previous = [...pointers.values()];
    const point = local(e);
    pointers.set(e.pointerId, point);
    if (tapped && Math.hypot(point.x - tapped.x, point.y - tapped.y) > 4)
      tapped = null;
    const next = [...pointers.values()];
    if (next.length === 1) {
      api.panBy(point.x - previous[0].x, point.y - previous[0].y);
    } else if (next.length === 2) {
      const midpoint = (pts: Point[]) => ({
        x: (pts[0].x + pts[1].x) / 2,
        y: (pts[0].y + pts[1].y) / 2,
      });
      const distance = (pts: Point[]) =>
        Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const from = midpoint(previous),
        to = midpoint(next);
      if (distance(previous) > 1)
        api.zoomBy(distance(next) / distance(previous), from);
      api.panBy(to.x - from.x, to.y - from.y);
    }
  }
  function end(e: PointerEvent) {
    if (!pointers.delete(e.pointerId)) return;
    if (tapped && e.type === "pointerup") api.selectAt(local(e));
    tapped = null;
    if (host.hasPointerCapture(e.pointerId))
      host.releasePointerCapture(e.pointerId);
  }
  function wheel(e: WheelEvent) {
    e.preventDefault();
    api.zoomBy(Math.exp(-Math.sign(e.deltaY) * 0.15), local(e));
  }
  function key(e: KeyboardEvent) {
    const shift = 30;
    switch (e.key) {
      case "+":
      case "=":
        api.zoomBy(1.25);
        break;
      case "-":
        api.zoomBy(0.8);
        break;
      case "Home":
        api.reset();
        break;
      case "ArrowLeft":
        api.panBy(shift, 0);
        break;
      case "ArrowRight":
        api.panBy(-shift, 0);
        break;
      case "ArrowUp":
        api.panBy(0, shift);
        break;
      case "ArrowDown":
        api.panBy(0, -shift);
        break;
      default:
        return;
    }
    e.preventDefault();
  }
  host.addEventListener("pointerdown", down);
  host.addEventListener("pointermove", move);
  host.addEventListener("pointerup", end);
  host.addEventListener("pointercancel", end);
  host.addEventListener("lostpointercapture", end);
  host.addEventListener("wheel", wheel, { passive: false });
  host.addEventListener("keydown", key);
  return () => {
    host.removeEventListener("pointerdown", down);
    host.removeEventListener("pointermove", move);
    host.removeEventListener("pointerup", end);
    host.removeEventListener("pointercancel", end);
    host.removeEventListener("lostpointercapture", end);
    host.removeEventListener("wheel", wheel);
    host.removeEventListener("keydown", key);
  };
}

export function CameraButton({
  label,
  disabled,
  onActivate,
  children,
}: {
  label: string;
  disabled: boolean;
  onActivate: () => void;
  children: ReactNode;
}) {
  const start = useRef<Point | null>(null);
  return (
    <button
      type="button"
      disabled={disabled}
      aria-label={label}
      onClick={onActivate}
      onTouchStart={(event) => {
        const touch = event.touches[0];
        start.current =
          event.touches.length === 1
            ? { x: touch.clientX, y: touch.clientY }
            : null;
      }}
      onTouchMove={(event) => {
        const point = start.current;
        const touch = event.touches[0];
        if (
          point &&
          Math.hypot(point.x - touch.clientX, point.y - touch.clientY) > 8
        ) {
          start.current = null;
        }
      }}
      onTouchCancel={() => {
        start.current = null;
      }}
      onTouchEnd={(event) => {
        // Some browsers suppress their compatibility click immediately after a map drag.
        // Consume the touch's click here so a single tap always activates exactly once.
        event.preventDefault();
        const touch = event.changedTouches[0];
        const target = document.elementFromPoint(touch.clientX, touch.clientY);
        const activate =
          start.current &&
          !event.touches.length &&
          event.currentTarget.contains(target);
        start.current = null;
        if (!disabled && activate) onActivate();
      }}
    >
      {children}
    </button>
  );
}

export default function Radar(input: Props) {
  const [floor, setFloor] = useState('default');
  const props = { ...input, layer: input.frame.world.map.layers?.[floor] ? floor : 'default' };
  const hostRef = useRef<HTMLDivElement>(null);
  const api = useRef<RadarApi | null>(null);
  const latest = useRef(props);
  const [zoom, setZoom] = useState(1);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  useEffect(() => {
    latest.current = props;
    api.current?.update(props);
  }, [props]);
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const app = new Application();
    let stopped = false;
    let initialized = false;
    let observer: ResizeObserver | undefined;
    let remove: (() => void) | undefined;
    async function mount(element: HTMLDivElement) {
      await app.init({
        preference: "canvas",
        antialias: false,
        autoStart: false,
        backgroundAlpha: 0,
        autoDensity: true,
        resolution: Math.min(window.devicePixelRatio || 1, 2),
      });
      initialized = true;
      if (stopped) {
        app.destroy(true, { children: true });
        return;
      }
      element.appendChild(app.canvas);
      const scene = setupScene(app, element, latest.current, setZoom, () => setError(true));
      api.current = scene;
      observer = new ResizeObserver(scene.resize);
      observer.observe(element);
      remove = bindNavigation(element, scene);
      setReady(true);
    }
    mount(host).catch((reason: unknown) => {
      if (!stopped) {
        console.error("Не удалось отобразить радар", reason);
        setError(true);
      }
    });
    return () => {
      stopped = true;
      observer?.disconnect();
      remove?.();
      api.current?.destroy();
      api.current = null;
      if (initialized) app.destroy(true, { children: true });
    };
  }, []);
  return (
    <div className="sim-radar">
      <div
        className="sim-radar-viewport"
        ref={hostRef}
        data-testid="radar"
        tabIndex={0}
        role="region"
        aria-label="Тактическая карта. Перемещение стрелками, масштаб клавишами плюс и минус, центрирование клавишей Home."
      />
      {error && (
        <div className="sim-radar-error" role="alert">
          Браузеру не удалось отобразить карту. Обновите страницу или откройте
          её в современном браузере.
        </div>
      )}
      <div
        className="sim-radar-tools"
        role="group"
        aria-label="Управление картой"
      >
        <CameraButton
          disabled={!ready || zoom <= 0.8}
          label="Уменьшить карту"
          onActivate={() => api.current?.zoomBy(0.8)}
        >
          −
        </CameraButton>
        {props.frame.world.map.layers?.lower && <button onClick={() => setFloor(props.layer === "lower" ? "default" : "lower")} aria-label="Сменить этаж">{props.layer === "lower" ? "Нижний" : "Верхний"}</button>}
        <output aria-label="Масштаб карты">{Math.round(zoom * 100)}%</output>
        <CameraButton
          disabled={!ready || zoom >= 4}
          label="Увеличить карту"
          onActivate={() => api.current?.zoomBy(1.25)}
        >
          +
        </CameraButton>
        <CameraButton
          disabled={!ready}
          label="Центрировать карту"
          onActivate={() => api.current?.reset()}
        >
          <svg
            viewBox="0 0 24 24"
            width="19"
            height="19"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.6"
            aria-hidden="true"
          >
            <circle cx="12" cy="12" r="6" />
            <path d="M12 2v5m0 10v5M2 12h5m10 0h5" />
            <circle cx="12" cy="12" r="1" />
          </svg>
        </CameraButton>
      </div>
    </div>
  );
}
