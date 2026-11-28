import { Assets, Container, Graphics, Sprite, Texture } from "pixi.js";
import { iconURL } from "./scorebotIcons";
import type { MatchView } from "./MatchCenter";

const colors: Record<string, number> = {
  Дым: 0xafbbc1,
  Свет: 0xfff5c7,
  Огонь: 0xfe8547,
  Ложная: 0xc8aaff,
  HE: 0xff5b51,
};
// Reuse sprites and textures across animation frames. Coordinates come only from the current view.
export class RadarEquipment extends Container {
  private used = 0;
  private textures = new Map<string, Texture | null>();
  constructor(private redraw: () => void) {
    super();
  }
  begin() {
    this.used = 0;
  }
  show(
    item: string,
    x: number,
    y: number,
    width: number,
    height: number,
    tint: number,
    side?: string,
  ) {
    const url = iconURL(item, side);
    if (!url) return;
    if (!this.textures.has(url)) {
      this.textures.set(url, null);
      void Assets.load<Texture>(url)
        .then((texture) => {
          if (this.destroyed) return;
          this.textures.set(url, texture);
          this.redraw();
        })
        .catch((error) => console.error("Загрузка значка радара", url, error));
    }
    const texture = this.textures.get(url);
    if (!texture) return;
    const sprite =
      (this.children[this.used] as Sprite | undefined) ??
      this.addChild(new Sprite());
    ++this.used;
    sprite.texture = texture;
    sprite.anchor.set(0.5);
    sprite.position.set(x, y);
    sprite.scale.set(Math.min(width / texture.width, height / texture.height));
    sprite.tint = tint;
    sprite.visible = true;
  }
  airborne(
    g: Graphics, kind: string, x: number, y: number, color: number, team?: string,
  ) {
    const before = this.used;
    this.show(kind, x, y, 5, 6, color, team);
    // The first flight can finish before its SVG texture has decoded.
    if (this.used === before) g.circle(x, y, 1.8).fill(color);
  }
  end() {
    for (let i = this.used; i < this.children.length; i++)
      this.children[i].visible = false;
  }
}
export function drawEvents(
  g: Graphics,
  m: MatchView,
  tick: number,
  items: RadarEquipment,
  carrier?: { x: number; y: number },
  visible: (z?: number) => boolean = () => true,
  scale = 1,
  grenades = true,
) {
  g.clear();
  for (const gun of m.groundWeapons)
    if (visible(gun.z)) items.show(gun.weapon, gun.x, gun.y, 8, 4, 0xacbfc3);
  if (grenades) for (const f of m.effects) {
    if (tick < f.start || tick >= f.end + 3) continue;
    const color = colors[f.kind];
    if (tick < f.land) {
      const path = f.trajectory;
      if (path) {
        const span = Math.max(0,tick-f.start);
        const from = path[Math.min(path.length-1,Math.floor(span))];
        const to = path[Math.min(path.length-1,Math.floor(span)+1)];
        const t = span%1;
        if (visible(from[2] + (to[2] - from[2]) * t))
          items.airborne(
            g, f.kind, from[0] + (to[0] - from[0]) * t,
            from[1] + (to[1] - from[1]) * t, color, f.team,
          );
        continue;
      }
      const t = Math.min(1, (tick - f.start) / (f.land - f.start)),
        x = f.sx + (f.x - f.sx) * t,
        y = f.sy + (f.y - f.sy) * t;
      g.moveTo(f.sx, f.sy)
        .lineTo(x, y)
        .stroke({ color, width: 0.7, alpha: 0.7 });
      items.airborne(g, f.kind, x, y, color, f.team);
    } else {
      if (!visible(f.z) && !(f.spatial && f.volume)) continue;
      if (f.spatial) {
        if (f.burstTick === undefined || tick < f.burstTick) continue;
        if (f.kind === "Дым" || f.kind === "Огонь") {
          if (tick >= f.end || !f.volume) continue;
          for (const [x, y, z, r] of f.volume) {
            if (visible(z)) g.circle(x, y, r);
          }
          g.fill({ color, alpha: f.kind === "Дым" ? 0.48 : 0.62 });
          continue;
        }
        const age = tick - f.burstTick;
        if (f.kind === "Ложная" && tick < f.end) items.show(f.kind,f.x,f.y,5,5,color,f.team);
        if (age >= 4) continue;
        const alpha = 1 - age / 4;
        const burstColor = f.kind === "Свет" ? 0xffffff : color;
        const unit = Math.max(1, 1.8 / scale);
        g.circle(f.x, f.y, (2 + age * 2) * unit)
          .stroke({color: burstColor, width: 1.15 * unit, alpha});
        for (let i=0; i<8; i++) {
          const dx=Math.cos(i*Math.PI/4), dy=Math.sin(i*Math.PI/4);
          g.moveTo(f.x+dx*2*unit,f.y+dy*2*unit).lineTo(f.x+dx*(8+age)*unit,f.y+dy*(8+age)*unit);
        }
        g.stroke({color:burstColor,width:unit,alpha});
        continue;
      }
      const fade = Math.min(1, (f.end + 3 - tick) / 4);
      items.show(f.kind, f.x, f.y, 4.5, 5.5, color, f.team);
      const radius = f.radius * Math.min(1, 0.35 + (tick - f.land) * 0.25);
      g.circle(f.x, f.y, radius)
        .fill({ color, alpha: fade * 0.34 })
        .stroke({ color, width: 0.8, alpha: fade * 0.8 });
    }
  }
  for (const s of m.shots) {
    const age = tick - s.tick;
    if (!visible(s.z) || age < 0 || age >= 4) continue;
    g.moveTo(s.x, s.y)
      .lineTo(s.tx, s.ty)
      .stroke({ color: 0xfce7ae, width: 0.85, alpha: 1 - age / 4 });
  }
  if (m.bomb && visible(m.bomb.z)) {
    const p = carrier ?? m.bomb;
    if (m.resolution && tick >= m.resolution.tick) {
      const progress = Math.min(1, (tick - m.resolution.tick + 1) / 13);
      const explosion = m.resolution.kind === "explode";
      g.circle(
        p.x,
        p.y,
        explosion ? 4 + 66 * progress : 5 + 5 * progress,
      ).stroke({
        color: explosion ? 0xff914a : 0x87f5d6,
        width: 1.6,
        alpha: 1 - progress,
      });
      return;
    }
    items.show(
      "C4",
      p.x + (carrier ? 4 : 0),
      p.y - (carrier ? 6 : 0),
      7,
      7,
      0xffdc7b,
    );
    if (m.phase === "planted")
      g.circle(p.x, p.y, 4 + (tick % 10) * 0.4).stroke({
        color: 0xffd66d,
        width: 0.8,
      });
  }
  if (m.action && m.bomb && visible(m.bomb.z)) {
    const t = Math.max(
      0,
      Math.min(1, (tick - m.action.start) / (m.action.end - m.action.start)),
    );
    g.moveTo(m.bomb.x, m.bomb.y - 8)
      .arc(m.bomb.x, m.bomb.y, 8, -Math.PI / 2, -Math.PI / 2 + 2 * Math.PI * t)
      .stroke({ color: 0xf2ffef, width: 1.5 });
  }
}
