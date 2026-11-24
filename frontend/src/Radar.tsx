import { useEffect, useRef, useState, type ReactNode } from "react";
import { Application, Container, Graphics, Text } from "pixi.js";
import "./radar.css";

type Point = { x: number; y: number };
type Rect = Point & { w: number; h: number };
type Team = "T" | "CT";
export interface RadarMap {
  id: string;
  name: string;
  version: string | number;
  author: string;
  width: number;
  height: number;
  walls: Rect[];
  zones: (Rect & { name: string })[];
  spawns: (Point & { team: Team })[];
}
export interface Agent extends Point {
  id: string;
  name: string;
  team: Team;
  heading: number;
  visible: string[];
  knowledge: (Point & { id: string; tick: number })[];
  status: string;
}
interface Props {
  map: RadarMap;
  agents: Agent[];
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

// All structural outlines come from the authoritative collision rectangles.
function drawPlan(map: RadarMap) {
  const plan = new Container();
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
  update: (props: Props) => void;
  resize: () => void;
  reset: () => void;
  zoomBy: (ratio: number, at?: Point) => void;
  panBy: (x: number, y: number) => void;
  selectAt: (at: Point) => void;
};

function setupScene(
  app: Application,
  host: HTMLDivElement,
  props: Props,
  zoomLabel: (n: number) => void,
) {
  let current = props;
  let zoom = 1;
  let pan = { x: 0, y: 0 };
  let fit = 1;
  const world = new Container();
  let plan = drawPlan(props.map);
  const marks = new Graphics();
  const names = new Container();
  const textById = new Map<string, Text>();
  app.stage.addChild(world);
  world.addChild(plan, marks, names);
  function draw() {
    const scale = fit * zoom;
    const { width, height } = app.screen;
    const map = current.map;
    const maxX = (scale * map.width) / 2;
    const maxY = (scale * map.height) / 2;
    pan.x = limit(pan.x, -maxX, maxX);
    pan.y = limit(pan.y, -maxY, maxY);
    world.scale.set(scale);
    world.position.set(
      (width - scale * map.width) / 2 + pan.x,
      (height - scale * map.height) / 2 + pan.y,
    );
    host.dataset.zoom = zoom.toFixed(3);
    host.dataset.panX = pan.x.toFixed(2);
    host.dataset.panY = pan.y.toFixed(2);
    marks.clear();
    for (const t of textById.values()) t.visible = false;
    const radius = limit(4.5 * scale, 6.3, 13) / scale;
    for (const a of current.agents) {
      const { x, y, heading, team } = a;
      const color = colors[team];
      const directionalPoint = (offset: number, length: number) => ({
        x: x + Math.cos(heading + offset) * radius * length,
        y: y + Math.sin(heading + offset) * radius * length,
      });
      const left = directionalPoint(-0.5, 1.1),
        tip = directionalPoint(0, 2.15),
        right = directionalPoint(0.5, 1.1);
      marks.poly([left.x, left.y, tip.x, tip.y, right.x, right.y]).fill(color);
      if (current.selected === a.id) {
        marks
          .circle(x, y, radius * 1.45)
          .stroke({ color: 0xffffff, width: 1.3 / scale });
      }
      if (team === "T")
        marks.roundRect(
          x - radius,
          y - radius,
          radius * 2,
          radius * 2,
          radius * 0.34,
        );
      else marks.circle(x, y, radius);
      marks.fill(color).stroke({ color: 0x0f1a1d, width: 1.2 / scale });
      let t = textById.get(a.id);
      if (!t) {
        const index = a.id.match(/\d+$/)?.[0];
        t = label(
          index ? String(Number(index)) : a.name.slice(0, 1),
          14,
          0x142526,
          "bold",
        );
        textById.set(a.id, t);
        names.addChild(t);
      }
      t.scale.set((radius * 1.52) / 14);
      t.position.set(x, y);
      t.visible = true;
    }
    app.render();
    host.dataset.ready = "true";
  }
  function resize() {
    const w = Math.max(1, host.clientWidth),
      h = Math.max(1, host.clientHeight);
    app.renderer.resize(w, h);
    fit = Math.min(w / (current.map.width + 38), h / (current.map.height + 46));
    draw();
  }
  const api: RadarApi = {
    update(next) {
      const changed =
        current.map.id !== next.map.id ||
        current.map.version !== next.map.version;
      current = next;
      if (changed) {
        plan.destroy({ children: true });
        plan = drawPlan(next.map);
        world.addChildAt(plan, 0);
        api.reset();
        resize();
      } else draw();
    },
    resize,
    reset() {
      zoom = 1;
      pan = { x: 0, y: 0 };
      zoomLabel(1);
      draw();
    },
    zoomBy(ratio, at) {
      const next = limit(zoom * ratio, 0.8, 4);
      if (next === zoom) return;
      const originX = (at?.x ?? app.screen.width / 2) - app.screen.width / 2;
      const originY = (at?.y ?? app.screen.height / 2) - app.screen.height / 2;
      pan.x = originX - ((originX - pan.x) * next) / zoom;
      pan.y = originY - ((originY - pan.y) * next) / zoom;
      zoom = next;
      zoomLabel(zoom);
      draw();
    },
    panBy(dx, dy) {
      pan.x += dx;
      pan.y += dy;
      draw();
    },
    selectAt(at) {
      const scale = zoom * fit;
      let target: Agent | undefined;
      let nearest = Math.max(12, 5 * scale);
      for (const agent of current.agents) {
        const distance = Math.hypot(
          at.x - world.x - agent.x * scale,
          at.y - world.y - agent.y * scale,
        );
        if (distance < nearest) {
          nearest = distance;
          target = agent;
        }
      }
      if (target) current.onSelect(target.id);
    },
  };
  api.resize();
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

function CameraButton({ label, disabled, onActivate, children }: {
  label: string;
  disabled: boolean;
  onActivate: () => void;
  children: ReactNode;
}) {
  const start = useRef<Point | null>(null);
  return (
    <button type="button" disabled={disabled} aria-label={label} onClick={onActivate}
      onTouchStart={event => {
        const touch = event.touches[0];
        start.current = event.touches.length === 1 ? {x: touch.clientX, y: touch.clientY} : null;
      }}
      onTouchMove={event => {
        const point = start.current;
        const touch = event.touches[0];
        if (point && Math.hypot(point.x - touch.clientX, point.y - touch.clientY) > 8) {
          start.current = null;
        }
      }}
      onTouchCancel={() => { start.current = null; }}
      onTouchEnd={event => {
        // Some browsers suppress their compatibility click immediately after a map drag.
        // Consume the touch's click here so a single tap always activates exactly once.
        event.preventDefault();
        const touch = event.changedTouches[0];
        const target = document.elementFromPoint(touch.clientX, touch.clientY);
        const activate = start.current && !event.touches.length && event.currentTarget.contains(target);
        start.current = null;
        if (!disabled && activate) onActivate();
      }}
    >{children}</button>
  );
}

export default function Radar(props: Props) {
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
        preference: "webgl",
        antialias: true,
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
      const scene = setupScene(app, element, latest.current, setZoom);
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
          Браузеру не удалось отобразить карту. Проверьте доступность
          графического ускорения.
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
