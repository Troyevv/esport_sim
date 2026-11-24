import { Graphics } from "pixi.js";
import type { MatchView } from "./MatchCenter";

const colors:Record<string,number> = {"Дым":0xafbbc1,"Свет":0xfff5c7,"Огонь":0xfe8547,"HE":0xff5b51};
export function drawEvents(g:Graphics,m:MatchView,tick:number,carrier?:{x:number;y:number}) {
  g.clear();
  for (const f of m.effects) {
    if(tick<f.start || tick>=f.end+3) continue;
    const color=colors[f.kind];
    if(tick<f.land) {
      const t=Math.min(1,(tick-f.start)/(f.land-f.start)), x=f.sx+(f.x-f.sx)*t, y=f.sy+(f.y-f.sy)*t;
      g.moveTo(f.sx,f.sy).lineTo(x,y).stroke({color,width:.7,alpha:.7});
      g.circle(x,y,1.6).fill(color);
    } else {
      const fade=Math.min(1,(f.end+3-tick)/4);
      const radius=f.radius*Math.min(1,.35+(tick-f.land)*.25);
      g.circle(f.x,f.y,radius).fill({color,alpha:fade*.34}).stroke({color,width:.8,alpha:fade*.8});
    }
  }
  for(const s of m.shots) {
    const age=tick-s.tick;
    if(age<0 || age>=4) continue;
    g.moveTo(s.x,s.y).lineTo(s.tx,s.ty).stroke({color:0xfce7ae,width:.85,alpha:1-age/4});
  }
  if(m.bomb) {
    const p=carrier??m.bomb;
    g.roundRect(p.x-2,p.y-6,4,4,0.7).fill(0xffd66d).stroke({color:0x342714,width:.7});
    if(m.phase==="planted") g.circle(p.x,p.y,4+(tick%10)*.4).stroke({color:0xffd66d,width:.8});
  }
  if(m.action && m.bomb) {
    const t=Math.max(0,Math.min(1,(tick-m.action.start)/(m.action.end-m.action.start)));
    g.arc(m.bomb.x,m.bomb.y,8,-Math.PI/2,-Math.PI/2+2*Math.PI*t).stroke({color:0xf2ffef,width:1.5});
  }
}
