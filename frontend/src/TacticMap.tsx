import { useEffect, useMemo, useRef, useState } from "react";
import { Application, Container } from "pixi.js";
import { drawPlan, type RadarMap } from "./Radar";
import {
  colors,
  floor,
  gridRouter,
  same,
  snap,
  spawn,
  symbols,
  walks,
  type Plan,
  type Point,
  type Preview,
  type Tool,
} from "./tactics";

type Props = {
  map: RadarMap;
  plan: Plan;
  slot: number;
  tool: Tool;
  selected: number | null;
  preview: Preview | null;
  tick: number;
  onDraw: (points: Point[]) => void;
  onPick: (slot: number, step: number | null) => void;
  onError: (text: string) => void;
};
type Camera = { zoom: number; x: number; y: number };
const home: Camera = { zoom: 1, x: 0, y: 0 };
const gap = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);

export default function TacticMap(props: Props) {
  const { map, plan, slot, tool, preview, tick, selected } = props;
  const host = useRef<HTMLDivElement>(null),
    ink = useRef<HTMLCanvasElement>(null);
  const scene = useRef<{ app: Application; ground: Container } | null>(null);
  const [size, resize] = useState({ w: 1, h: 1 }),
    [camera, setCamera] = useState(home);
  const [ready, setReady] = useState(false),
    [renderError, setRenderError] = useState(false);
  const [cursor, setCursor] = useState<Point | null>(null),
    [stroke, setStroke] = useState<Point[]>([]);
  const pointers = useRef(new Map<number, Point>()),
    nav = useRef(false),
    trail = useRef<Point[]>([]);
  const router = useMemo(() => gridRouter(map), [map]);
  const scale =
    Math.min(size.w / (map.width + 24), size.h / (map.height + 24)) *
    camera.zoom;
  const offset = {
    x: (size.w - map.width * scale) / 2 + camera.x,
    y: (size.h - map.height * scale) / 2 + camera.y,
  };
  const local = (p: Point) => ({
    x: (p.x - offset.x) / scale,
    y: (p.y - offset.y) / scale,
  });
  const pos = (e: { clientX: number; clientY: number }) => {
    const r = host.current!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  };
  function zoomAt(factor: number, before: Point, after = before) {
    setCamera((c) => {
      const zoom = Math.max(0.85, Math.min(4, c.zoom * factor)),
        ratio = zoom / c.zoom;
      return {
        zoom,
        x: after.x - size.w / 2 - (before.x - size.w / 2 - c.x) * ratio,
        y: after.y - size.h / 2 - (before.y - size.h / 2 - c.y) * ratio,
      };
    });
  }
  useEffect(() => {
    const el = host.current!;
    const observer = new ResizeObserver(() =>
      resize({ w: el.clientWidth, h: el.clientHeight }),
    );
    observer.observe(el);
    const app = new Application();
    let stopped = false;
    app
      .init({
        preference: "canvas",
        autoStart: false,
        autoDensity: true,
        antialias: true,
        backgroundAlpha: 0,
        resolution: Math.min(devicePixelRatio, 2),
      })
      .then(() => {
        if (stopped) {
          app.destroy(true, { children: true });
          return;
        }
        const ground = drawPlan(map);
        app.stage.addChild(ground);
        el.prepend(app.canvas);
        scene.current = { app, ground };
        setReady(true);
      })
      .catch(() => {
        if (!stopped) setRenderError(true);
      });
    return () => {
      stopped = true;
      observer.disconnect();
      if (scene.current) {
        app.destroy(true, { children: true });
        scene.current = null;
      }
    };
  }, [map.id, map.version]);
  useEffect(() => {
    const sc = scene.current;
    if (!sc) return;
    sc.app.renderer.resize(size.w, size.h);
    sc.ground.scale.set(scale);
    sc.ground.position.set(offset.x, offset.y);
    sc.app.render();
  }, [ready, size, scale, offset.x, offset.y]);

  useEffect(() => {
    const canvas = ink.current!,
      dpr = Math.min(devicePixelRatio, 2);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    if (
      canvas.width !== Math.round(size.w * dpr) ||
      canvas.height !== Math.round(size.h * dpr)
    ) {
      canvas.width = Math.round(size.w * dpr);
      canvas.height = Math.round(size.h * dpr);
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size.w, size.h);
    ctx.translate(offset.x, offset.y);
    ctx.scale(scale, scale);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    function line(
      points: Point[],
      color: string,
      width: number,
      dashed = false,
    ) {
      if (!ctx || !points.length) return;
      ctx.beginPath();
      ctx.setLineDash(dashed ? [2, 1.8] : []);
      ctx.moveTo(points[0].x, points[0].y);
      points.slice(1).forEach((p) => ctx.lineTo(p.x, p.y));
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.stroke();
      ctx.setLineDash([]);
    }
    function disc(
      p: Point,
      r: number,
      fill: string,
      edge: string,
      text: string,
    ) {
      if (!ctx) return;
      ctx.beginPath();
      ctx.arc(p.x, p.y, r, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();
      ctx.strokeStyle = edge;
      ctx.lineWidth = 0.7;
      ctx.stroke();
      ctx.font = "bold " + r * 1.5 + "px system-ui";
      ctx.fillStyle = edge;
      ctx.fillText(text, p.x, p.y + 0.15);
    }
    for (const i of [0, 1, 2, 3, 4].filter((i) => i !== slot).concat(slot)) {
      const start = spawn(map, plan.side, i);
      let prev: Point = start;
      ctx.globalAlpha = preview ? 0.28 : i === slot ? 1 : 0.48;
      plan.slots[i].forEach((s, j) => {
        const moving = walks(s.kind);
        line(
          [prev, ...(moving ? router(prev, s) : [s])],
          colors[i],
          i === slot ? 1.3 : 0.7,
          !moving,
        );
        if (moving) prev = s;
        if (i === slot || s.kind !== "move")
          disc(
            s,
            i === slot && selected === j ? 4.4 : 2.5,
            "#132025",
            colors[i],
            s.kind === "move" ? String(j + 1) : symbols[s.kind],
          );
      });
      if (!preview) {
        ctx.globalAlpha = 1;
        disc(
          start,
          i === slot ? 4.9 : 3.5,
          colors[i],
          "#142225",
          String(i + 1),
        );
      }
    }
    ctx.globalAlpha = 1;
    if (preview) {
      const n = Math.max(
          0,
          Math.min(Math.floor(tick), preview.frames.length - 1),
        ),
        fraction = tick - n;
      const frame = preview.frames[n],
        next = preview.frames[n + 1] || frame;
      for (const f of preview.effects.filter(
        (f) => f.land <= tick && f.end > tick,
      )) {
        ctx.beginPath();
        ctx.arc(f.x, f.y, f.radius, 0, Math.PI * 2);
        ctx.fillStyle = f.utility === "Огонь" ? "#fc98536b" : "#cedddb66";
        ctx.fill();
      }
      frame.forEach(([x, y, h, hp], i) => {
        const target = next[i],
          p = {
            x: x + (target[0] - x) * fraction,
            y: y + (target[1] - y) * fraction,
          };
        ctx.globalAlpha = hp ? 1 : 0.4;
        if (hp)
          line(
            [p, { x: p.x + Math.cos(h) * 7, y: p.y + Math.sin(h) * 7 }],
            "#f4eed8",
            1,
          );
        disc(
          p,
          3.5,
          i < 5 ? colors[i] : "#ee9e88",
          "#141f24",
          hp ? String((i % 5) + 1) : "×",
        );
      });
      ctx.globalAlpha = 1;
    }
    if (stroke.length) line(stroke, colors[slot], 1.6, true);
    if (cursor) disc(cursor, 3.4, "#142024", "#fff", "+");
  }, [
    size,
    offset.x,
    offset.y,
    scale,
    map,
    plan,
    slot,
    router,
    preview,
    tick,
    stroke,
    cursor,
    selected,
  ]);

  function commit(points: Point[]) {
    if (!points.length || preview) return;
    const p = points[points.length - 1];
    if (tool === "select") {
      const candidates = plan.slots.flatMap((steps, i) => [
        ...steps.map((s, j) => ({ p: s, slot: i, index: j as number | null })),
        { p: spawn(map, plan.side, i), slot: i, index: null },
      ]);
      const hit = candidates.sort((a, b) => gap(a.p, p) - gap(b.p, p))[0];
      if (hit && gap(hit.p, p) <= 10) props.onPick(hit.slot, hit.index);
      return;
    }
    if (tool === "pan") return;
    if (points.some((p) => !floor(map, p))) {
      props.onError(
        "Маршрут попал в стену. Проведите его по свободным клеткам.",
      );
      return;
    }
    props.onDraw(tool === "move" ? points : [p]);
  }
  function cancel() {
    pointers.current.clear();
    nav.current = false;
    trail.current = [];
    setStroke([]);
  }
  const centre = { x: size.w / 2, y: size.h / 2 };
  return (
    <div className="board-stage">
      <div
        ref={host}
        className="board-viewport"
        data-testid="tactic-map"
        data-ready={ready}
        role="application"
        tabIndex={0}
        aria-label="Доска тактики. Стрелки перемещают курсор, Enter ставит точку, плюс и минус меняют масштаб."
        onKeyDown={(e) => {
          const deltas: Record<string, Point> = {
            ArrowLeft: { x: -10, y: 0 },
            ArrowRight: { x: 10, y: 0 },
            ArrowUp: { x: 0, y: -10 },
            ArrowDown: { x: 0, y: 10 },
          };
          const c = cursor || spawn(map, plan.side, slot),
            d = deltas[e.key];
          if (d) {
            e.preventDefault();
            if (tool === "pan")
              setCamera((v) => ({ ...v, x: v.x - d.x * 3, y: v.y - d.y * 3 }));
            else
              setCursor({
                x: Math.min(map.width - 5, Math.max(5, c.x + d.x)),
                y: Math.min(map.height - 5, Math.max(5, c.y + d.y)),
              });
          }
          if (e.key === "Enter") {
            e.preventDefault();
            commit([c]);
          }
          if (e.key === "+" || e.key === "=") zoomAt(1.25, centre);
          if (e.key === "-") zoomAt(0.8, centre);
          if (e.key === "Home") setCamera(home);
        }}
        onPointerDown={(e) => {
          if (e.button !== 0 && e.button !== 1) return;
          e.currentTarget.setPointerCapture(e.pointerId);
          setCursor(null);
          const p = pos(e);
          pointers.current.set(e.pointerId, p);
          if (
            pointers.current.size > 1 ||
            tool === "pan" ||
            preview ||
            e.button === 1
          ) {
            nav.current = true;
            trail.current = [];
            setStroke([]);
            return;
          }
          trail.current = [snap(local(p))];
          setStroke(trail.current);
        }}
        onPointerMove={(e) => {
          const held = pointers.current,
            old = held.get(e.pointerId);
          if (!old) return;
          const p = pos(e),
            other = [...held].find(([id]) => id !== e.pointerId)?.[1];
          held.set(e.pointerId, p);
          if (other) {
            const mid = (a: Point) => ({
              x: (a.x + other.x) / 2,
              y: (a.y + other.y) / 2,
            });
            zoomAt(
              gap(p, other) / Math.max(1, gap(old, other)),
              mid(old),
              mid(p),
            );
          } else if (nav.current)
            setCamera((c) => ({
              ...c,
              x: c.x + p.x - old.x,
              y: c.y + p.y - old.y,
            }));
          else if (tool === "move") {
            const from = local(old),
              to = local(p),
              count = Math.ceil(gap(from, to) / 4);
            for (let i = 1; i <= count; i++) {
              const v = snap({
                x: from.x + ((to.x - from.x) * i) / count,
                y: from.y + ((to.y - from.y) * i) / count,
              });
              if (!same(v, trail.current[trail.current.length - 1]))
                trail.current.push(v);
            }
            setStroke([...trail.current]);
          }
        }}
        onPointerCancel={cancel}
        onLostPointerCapture={(e) => {
          if (pointers.current.has(e.pointerId)) cancel();
        }}
        onPointerUp={(e) => {
          if (!pointers.current.delete(e.pointerId)) return;
          if (!nav.current) {
            const last = snap(local(pos(e)));
            if (!same(last, trail.current[trail.current.length - 1]))
              trail.current.push(last);
            commit(trail.current);
          }
          if (!pointers.current.size) cancel();
        }}
      >
        <canvas ref={ink} className="board-ink" aria-hidden="true" />
        {renderError && (
          <p role="alert">Браузеру не удалось отобразить карту.</p>
        )}
      </div>
      <div className="board-camera">
        <button
          aria-label="Уменьшить доску"
          onClick={() => zoomAt(0.8, centre)}
        >
          −
        </button>
        <button aria-label="Центрировать доску" onClick={() => setCamera(home)}>
          {Math.round(camera.zoom * 100)}%
        </button>
        <button
          aria-label="Увеличить доску"
          onClick={() => zoomAt(1.25, centre)}
        >
          +
        </button>
      </div>
    </div>
  );
}
