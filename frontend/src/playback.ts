import type { Agent, RadarMap } from "./Radar";
import type { Frame } from "./session";

export type Pose = Pick<Agent, "x" | "y" | "heading">;
type Control = { x: number; y: number };
type Key = Pose & {
  at: number;
  blend: boolean;
  curve?: { c1: Control; c2: Control; lengths: number[] };
};
type Track = { keys: Key[]; pose: Pose; sampledAt: number };
// In milliseconds of playback at the selected speed. Grow on delivery stalls;
// shrink slowly so successive bursts do not repeatedly drain the same buffer.
const initialReserve = 200;
const maxReserve = 450;
const maxTurnPerMs = (Math.PI / 180) * 0.9;

// On a missing or incompatible track the marker holds, then jumps to the known
// position. A straight segment may never cross (or graze a corner of) a wall.
function clearSegment(a: Pose, b: Pose, walls: RadarMap["walls"]) {
  const dx = b.x - a.x,
    dy = b.y - a.y;
  return !walls.some(({ x, y, w, h }) => {
    if (
      Math.max(a.x, b.x) < x ||
      Math.min(a.x, b.x) > x + w ||
      Math.max(a.y, b.y) < y ||
      Math.min(a.y, b.y) > y + h
    )
      return false;
    const x1 = dx ? (x - a.x) / dx : -Infinity,
      x2 = dx ? (x + w - a.x) / dx : Infinity;
    const y1 = dy ? (y - a.y) / dy : -Infinity,
      y2 = dy ? (y + h - a.y) / dy : Infinity;
    return (
      Math.max(0, Math.min(x1, x2), Math.min(y1, y2)) <=
      Math.min(1, Math.max(x1, x2), Math.max(y1, y2))
    );
  });
}

function key(p: Pose, at: number, blend: boolean): Key {
  return { x: p.x, y: p.y, heading: p.heading, at, blend };
}

function cubic(a: number, c1: number, c2: number, b: number, t: number) {
  const u = 1 - t;
  return (
    u * u * u * a + 3 * u * u * t * c1 + 3 * u * t * t * c2 + t * t * t * b
  );
}

// Finish a segment only when the following observed point is available and
// presentation has not entered it. Cubic Bézier stays inside its control hull.
function roundCorner(keys: Key[], cursor: number, map: RadarMap) {
  const prev = keys.at(-4),
    a = keys.at(-3),
    b = keys.at(-2)!,
    next = keys.at(-1)!;
  if (!a || !b.blend || !next.blend || a.at < cursor) return;
  const dx = b.x - a.x,
    dy = b.y - a.y;
  if (!dx && !dy) return;
  const px = prev && a.blend ? a.x - prev.x : dx;
  const py = prev && a.blend ? a.y - prev.y : dy;
  const nx = next.x - b.x,
    ny = next.y - b.y;
  if (px === dx && py === dy && nx === dx && ny === dy) return;
  // Average adjacent step vectors at a turn. A stop or reversal has zero tangent.
  const inScale = (!px && !py) || px * dx + py * dy < 0 ? 0 : 1 / 6;
  const outScale = (!nx && !ny) || nx * dx + ny * dy < 0 ? 0 : 1 / 6;
  const c1 = { x: a.x + (px + dx) * inScale, y: a.y + (py + dy) * inScale };
  const c2 = { x: b.x - (dx + nx) * outScale, y: b.y - (dy + ny) * outScale };
  const left = Math.min(a.x, b.x, c1.x, c2.x),
    right = Math.max(a.x, b.x, c1.x, c2.x);
  const top = Math.min(a.y, b.y, c1.y, c2.y),
    bottom = Math.max(a.y, b.y, c1.y, c2.y);
  if (
    left < 0 ||
    right > map.width ||
    top < 0 ||
    bottom > map.height ||
    map.walls.some(
      (w) =>
        left <= w.x + w.w && right >= w.x && top <= w.y + w.h && bottom >= w.y,
    )
  )
    return;
  const lengths = [0];
  if (inScale && outScale) {
    // Retiming by distance avoids speeding up on the shoulders of a turn.
    // Deliberate stops and reversals retain their zero endpoint velocity.
    let x = a.x,
      y = a.y;
    for (let i = 1; i <= 16; i++) {
      const t = i / 16,
        nx = cubic(a.x, c1.x, c2.x, b.x, t),
        ny = cubic(a.y, c1.y, c2.y, b.y, t);
      lengths.push(lengths[i - 1] + Math.hypot(nx - x, ny - y));
      x = nx;
      y = ny;
    }
  }
  b.curve = { c1, c2, lengths };
}

export class RadarPlayback {
  private tracks = new Map<string, Track>();
  private last?: Frame;
  private online = false;
  private received = 0;
  private end = 0;
  private cursor = 0;
  private clockAt = 0;
  private rate = 1;
  private reserve = initialReserve;
  private batches = 0;

  private nextCursor(now: number) {
    let step = Math.max(0, now - this.clockAt) * this.rate;
    const room = this.end - this.cursor;
    // Once a continuous stream is established, protect its last confirmed
    // segment against late delivery. Integrate the speed curve analytically
    // so 60 Hz, 144 Hz and repeated samples at one vsync have the same clock.
    const tail = 180;
    if (this.batches < 2 || room - step >= tail)
      return Math.min(this.end, this.cursor + step);
    step -= Math.max(0, room - tail);
    const remaining = Math.min(room, tail);
    const floorRate = 0.32;
    const floorRoom = floorRate * tail;
    const taper = remaining > floorRoom ? tail * Math.log(remaining / floorRoom) : 0;
    const left = step < taper
      ? remaining * Math.exp(-step / tail)
      : Math.max(0, Math.min(remaining, floorRoom) - (step - taper) * floorRate);
    return this.end - left;
  }

  private advance(now: number) {
    if (now > this.clockAt) {
      this.cursor = this.nextCursor(now);
      this.clockAt = now;
    }
  }

  push(next: Frame, online: boolean, now: number) {
    const old = this.last;
    const world = next.world;
    const continuous =
      old &&
      this.online &&
      online &&
      old.context === next.context &&
      old.world.view === world.view &&
      old.world.match?.round === world.match?.round &&
      old.world.map.id === world.map.id &&
      old.world.map.version === world.map.version &&
      next.running &&
      old.running;
    this.online = online;
    this.last = next;
    // A speed command can have the same tick as the preceding snapshot. Keep
    // queued movement at its original speed; the new speed applies to future ticks.
    if (continuous && world.tick === old.world.tick) return;
    const ticks = old ? world.tick - old.world.tick : 0;
    const gap = now - this.received;
    const estimatedCursor = this.nextCursor(now);
    const covered =
      ticks === next.speed ||
      (ticks > 0 &&
        world.motion !== undefined &&
        world.motion.startTick === old?.world.tick);
    const bridge =
      continuous &&
      covered &&
      gap < 1000 &&
      now - this.clockAt < 1000 &&
      this.end - estimatedCursor < maxReserve + 250;
    if (bridge) this.advance(now);
    this.batches = bridge ? this.batches + 1 : 0;
    const start = bridge ? this.end : 0;
    const duration = bridge
      ? ((world.time - old.world.time) * 1000) / next.speed
      : 0;
    const end = start + duration;
    if (bridge) {
      // Packet arrival determines how much to buffer, never the duration of a
      // model segment. A bounded clock servo compensates for sustained drift.
      this.reserve = Math.min(
        maxReserve,
        Math.max(initialReserve, gap + 55, this.reserve - gap / 1000),
      );
      const error = end - estimatedCursor - this.reserve;
      const target = 1 + Math.max(-0.07, Math.min(0.035, error / 1100));
      this.rate += (target - this.rate) * Math.min(0.4, gap / 500);
    } else {
      this.cursor = -this.reserve;
      this.clockAt = now;
      this.rate = 1;
    }
    const visible = new Set(world.agents.map((a) => a.id));
    for (const id of this.tracks.keys())
      if (!visible.has(id)) this.tracks.delete(id);
    for (const agent of world.agents) {
      const track = this.tracks.get(agent.id);
      const batch = world.motion;
      const samples = batch?.tracks[agent.id];
      if (
        !track ||
        !bridge ||
        (ticks > 1 &&
          (batch?.startTick !== old.world.tick || samples?.length !== ticks))
      ) {
        this.tracks.set(agent.id, {
          keys: [key(agent, end, false)],
          pose: key(agent, end, false),
          sampledAt: now,
        });
        continue;
      }
      while (track.keys.length > 1 && track.keys[1].at <= this.cursor)
        track.keys.shift();
      for (let i = 1; i <= ticks; i++) {
        const s = i < ticks ? samples![i] : null;
        const pose = s ? { x: s[0], y: s[1], heading: s[2] } : agent;
        const previous = track.keys[track.keys.length - 1];
        track.keys.push(
          key(
            pose,
            start + ((end - start) * i) / ticks,
            clearSegment(previous, pose, world.map.walls),
          ),
        );
        roundCorner(track.keys, this.cursor, world.map);
      }
    }
    this.received = now;
    this.end = end;
  }

  displayTick(now: number) {
    this.advance(now);
    if (!this.last) return 0;
    if (!this.last.running || !this.online || this.last.speed > 8) return this.last.world.tick;
    return this.last.world.tick - Math.max(0, this.end - this.cursor) * this.last.speed / 100;
  }

  has(id: string) {
    return this.tracks.has(id);
  }

  sample(id: string, now: number): Pose {
    this.advance(now);
    const track = this.tracks.get(id)!;
    const { keys, pose } = track;
    while (keys.length > 1 && keys[1].at <= this.cursor) keys.shift();
    const [a, b] = keys;
    const t = b?.blend ? Math.max(0, (this.cursor - a.at) / (b.at - a.at)) : 0;
    pose.x = t ? a.x + (b.x - a.x) * t : a.x;
    pose.y = t ? a.y + (b.y - a.y) * t : a.y;
    if (t && b.curve) {
      const { c1, c2, lengths } = b.curve;
      let parameter = t;
      if (lengths.length > 1) {
        const distance = t * lengths[lengths.length - 1];
        let i = 1;
        while (i < lengths.length - 1 && lengths[i] < distance) i++;
        parameter =
          (i -
            1 +
            (distance - lengths[i - 1]) / (lengths[i] - lengths[i - 1])) /
          (lengths.length - 1);
      }
      pose.x = cubic(a.x, c1.x, c2.x, b.x, parameter);
      pose.y = cubic(a.y, c1.y, c2.y, b.y, parameter);
    }
    const turn = t
      ? Math.atan2(
          Math.sin(b.heading - a.heading),
          Math.cos(b.heading - a.heading),
        )
      : 0;
    // At 8× a genuine 90° change can span just 12.5 ms. Slew only the
    // indicator toward the confirmed heading, also across the ±π boundary.
    const diff = a.heading + turn * t - pose.heading;
    const shortest = Math.atan2(Math.sin(diff), Math.cos(diff));
    const limit = Math.max(0, now - track.sampledAt) * maxTurnPerMs;
    pose.heading += Math.max(-limit, Math.min(limit, shortest));
    track.sampledAt = Math.max(track.sampledAt, now);
    return pose;
  }
}
