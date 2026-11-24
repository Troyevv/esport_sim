import type { Agent, RadarMap } from "./Radar";
import type { Frame } from "./session";

export type Pose = Pick<Agent, "x" | "y" | "heading">;
type Key = Pose & { at: number; blend: boolean };
type Track = { keys: Key[]; pose: Pose };
const bufferMs = 125;

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

export class RadarPlayback {
  private tracks = new Map<string, Track>();
  private last?: Frame;
  private online = false;
  private received = 0;
  private end = 0;

  push(next: Frame, online: boolean, now: number) {
    const old = this.last;
    const world = next.world;
    const continuous =
      old &&
      this.online &&
      online &&
      old.context === next.context &&
      old.world.view === world.view &&
      old.world.map.id === world.map.id &&
      old.world.map.version === world.map.version &&
      next.running &&
      old.running &&
      old.speed === next.speed;
    if (continuous && world.tick === old.world.tick) return;
    const ticks = old ? world.tick - old.world.tick : 0;
    const bridge =
      continuous &&
      ticks === next.speed &&
      now - this.received < 450 &&
      this.end < now + 350;
    const start = bridge ? Math.max(now, this.end) : now;
    const duration = bridge
      ? ((world.time - old.world.time) * 1000) / next.speed
      : 0;
    const correction = Math.max(
      -8,
      Math.min(8, (now + bufferMs - start - duration) * 0.2),
    );
    const end = bridge ? start + duration + correction : now + bufferMs;
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
        });
        continue;
      }
      // If delivery stalled, extend the final confirmed pose up to the new start.
      while (track.keys.length > 1 && track.keys[1].at <= now)
        track.keys.shift();
      const tail = track.keys[track.keys.length - 1];
      if (start > tail.at) track.keys.push(key(tail, start, false));
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
      }
    }
    this.received = now;
    this.end = end;
    this.online = online;
    this.last = next;
  }

  sample(id: string, now: number): Pose {
    const { keys, pose } = this.tracks.get(id)!;
    while (keys.length > 1 && keys[1].at <= now) keys.shift();
    const [a, b] = keys;
    const t = b?.blend ? Math.max(0, (now - a.at) / (b.at - a.at)) : 0;
    pose.x = t ? a.x + (b.x - a.x) * t : a.x;
    pose.y = t ? a.y + (b.y - a.y) * t : a.y;
    const turn = t
      ? Math.atan2(
          Math.sin(b.heading - a.heading),
          Math.cos(b.heading - a.heading),
        )
      : 0;
    pose.heading = a.heading + turn * t;
    return pose;
  }
}
