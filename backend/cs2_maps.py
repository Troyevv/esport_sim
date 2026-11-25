"""Installed Source 2 maps. Simulation coordinates use 1/12 Hammer units, Y down."""

import json
import os
from functools import cached_property, lru_cache
from math import atan2, dist, hypot
from pathlib import Path

from .cs2_navigation import Navigation, surface_height
from .cs2_profiles import named_stages, resolve_anchors
from .cs2_sites import BombSites
from .match_rules import BLAST_RADIUS, ROLES

BUILD = 26879581
PROFILES = json.loads(Path(__file__).with_name("data").joinpath("maps_202611_tactics.json").read_bytes())
NAMES = dict(zip(PROFILES, ("Ancient", "Anubis", "Cache", "Dust II", "Inferno", "Mirage", "Nuke", "Train", "Vertigo")))
UNIT = 12.


def root():
    override = os.environ.get("ESPORT_SIM_MAPS")
    if override:
        return Path(override)
    if os.name == "nt":
        from .paths import windows_data_dir
        return windows_data_dir() / "maps" / str(BUILD)
    return Path(__file__).resolve().parents[1] / "runtime-data" / "maps" / str(BUILD)


def installed():
    return [m for m in PROFILES if (root() / m / "provenance.json").is_file()]


@lru_cache(maxsize=2)
def _load(directory, name):
    if name not in NAMES:
        raise ValueError("Неизвестная карта CS2")
    folder = directory / name
    try:
        return Map(folder)
    except (OSError, KeyError) as exc:
        raise ValueError(f"Не удалось открыть {NAMES[name]}. Импортируйте карты версии {BUILD}: {exc}") from exc


def get(name):
    return _load(root(), name)


def for_match(w):
    return get(w["mapId"]) if w.get("mapId") else None


def xyz(a):
    return a["x"], a["y"], a["z"]


class Map:
    def __init__(self, folder):
        self.folder = folder
        self.name = name = folder.name
        src = json.loads((folder / "provenance.json").read_bytes())
        data = json.loads((folder / "gameplay.json").read_bytes())
        if src["map"] != name or data["map"] != name or int(src["steamBuild"]) != BUILD or src["unresolvedModels"]:
            raise ValueError(f"{name}: неверная версия карты или неполные ресурсы")
        self.overview = src["overview"]
        self.nav = Navigation(data)
        self.sites = BombSites(data["targets"])
        self.spawns = {s: [p for p in data["spawns"] if p["enabled"] and p["side"] == s] for s in ("T","CT")}
        self.profile = PROFILES[name]
        self.places = resolve_anchors(self.profile, named_stages(data,self.nav,self.profile), self.nav,src["navSha256"])
        self.centers = {}
        self.plants = {"A": [], "B": []}
        self.cover = []
        for i, center in self.nav.centers.items():
            x,y,z = center
            height = surface_height(self.nav.areas[i]["corners"], x, y)
            pos = (x,y,height if height is not None else z)
            self.centers[i] = self.to_sim(pos)
            site = self.sites.at((x,y,pos[2]+1))
            if site:
                self.plants[site].append(i)
            for spot in self.nav.areas[i]["cover"]:
                point = spot["position"]
                if self.nav.locate(point,64) == i:
                    self.cover.append((i,self.to_sim(point)))
        self.site_points = {}
        self.holds = {}
        for site, areas in self.plants.items():
            if not areas or min(map(len,self.spawns.values())) < 5:
                raise ValueError(f"{name}: неполные спавны или плент {site}")
            mean = tuple(sum(self.centers[i][axis] for i in areas)/len(areas) for axis in range(3))
            center = min(areas,key=lambda i: dist(self.centers[i],mean))
            self.site_points[site] = self.centers[center]
            self.holds[site] = sorted(self.cover,key=lambda item: dist(item[1], mean))[:16]
        self.route = lru_cache(maxsize=8192)(self.nav.route)
        self.approach = lru_cache(maxsize=32)(self._approach)
        self.escape = lru_cache(maxsize=16)(self._escape)
        self.locate = lru_cache(maxsize=8192)(self._locate)

    @cached_property
    def collision(self):
        from .cs2_collision import Collision
        return Collision(self.folder)

    def to_sim(self, p):
        return ((p[0]-self.overview["pos_x"])/UNIT,(self.overview["pos_y"]-p[1])/UNIT,p[2]/UNIT)

    def world(self, p):
        return (self.overview["pos_x"]+p[0]*UNIT,self.overview["pos_y"]-p[1]*UNIT,p[2]*UNIT)

    def _locate(self, point):
        return self.nav.locate(self.world(point),96)

    def site_at(self, pos):
        x,y,z = self.world(pos)
        return self.sites.at((x,y,z+1))

    def spawn(self, side, slot, selection=0):
        choices = self.spawns[side]
        spawn = choices[(selection+slot)%len(choices)]
        p = spawn["position"]
        ident = self.nav.locate(p,96)
        height = surface_height(self.nav.areas[ident]["corners"],*p[:2])
        return self.to_sim((*p[:2],height)), -spawn["heading"], ident

    def _approach(self, site, variant):
        labels = self.profile[site][variant]
        return self.nav.routes_through([self.places[n] for n in labels]+[self.plants[site]])

    def _escape(self, bomb):
        goals = [i for i,p in self.centers.items() if dist(p,bomb) >= BLAST_RADIUS+4]
        return self.nav.routes_through([goals])

    def orders(self, side, site, squad, lane):
        slots = []
        for player in sorted(squad,key=lambda a:a["slot"]):
            i = player["slot"]
            defended = ("A" if i in (0,2) else "B") if side=="CT" and i!=4 else site
            variant = lane if i in (0,2,4) else 1-lane
            start = player["navArea"]
            if side=="T":
                options = self._approach(site,variant)
                selected = options.route(start)
                if selected is None:
                    # A mid-round call can originate beyond a one-way transition.
                    selected = self._approach(site,1-variant).route(start)
                waypoints = [self.centers[j] for j in selected[1][:-1]] if selected else []
                plant = self.centers[selected[1][-1]] if selected else self.site_points[site]
            else:
                guards = self.profile["guards"][defended]
                choices = self.places[guards[i%len(guards)]]
                usable = [j for j in sorted(choices) if self.route(start,j) is not None]
                waypoints = [self.centers[min(usable,key=lambda j:dist(xyz(player),self.centers[j]))]] if usable else []
                plant = self.site_points[defended]
            hold = waypoints[-1] if side=="CT" and waypoints else plant
            if side=="T" or i==4:
                covers = [p for j,p in self.holds[defended] if self.route(start,j) is not None and dist(p,plant)<55]
                if covers:
                    hold = covers[(i+lane*3)%len(covers)]
            slots.append(dict(role=ROLES[i], approach=list(waypoints[0] if waypoints else hold),
                              via=[list(p) for p in waypoints], stage=list(waypoints[-1] if waypoints else plant),
                              hold=list(hold),plant=list(plant),site=defended,
                              watch=list(self._watch(defended, hold, variant))))
        return dict(version=1,map=self.name,geometry=BUILD,slots=slots)

    def _watch(self, site, pos, variant):
        label = self.profile[site][variant][-1]
        options = [self.centers[i] for i in self.places[label]]
        return min(options,key=lambda p:dist(p,pos))

    def hit(self, p, q, channel, up=0, target_up=None):
        a,b = self.world(p),self.world(q)
        return self.collision.trace((*a[:2],a[2]+up),(*b[:2],b[2]+(up if target_up is None else target_up)),channel)

    def clear(self, a, b):
        return self.hit(xyz(a),xyz(b),1,64) is None

    def walk(self,a,goal,pace,hazards):
        here = a["navArea"]
        goal = tuple(goal)
        zone = self.locate(goal)
        if zone is None:
            return False
        pos = xyz(a)
        if goal == pos:
            return False
        dest = [zone,*goal]
        if a["dest"]!=dest or not a["path"]:
            path = self.route(here,zone)
            if path is None:
                return False
            points=[]
            for crossing in path:
                points.append([*self.to_sim(crossing.leave),here])
                here=crossing.area
                points.append([*self.to_sim(crossing.enter),here])
            points.append([*goal,zone])
            a["path"],a["dest"]=points,dest
        moved=False
        while a["path"] and pace>0:
            node=a["path"][0]
            endpoint=tuple(node[:3])
            length=dist(pos,endpoint)
            if any(dist(endpoint,xyz(f))<f["radius"]<=dist(pos,xyz(f)) for f in hazards):
                a["status"]="Пережидает огонь за укрытием"
                return moved
            if length>0:
                fraction=min(1,pace/length)
                nxt=tuple(p+(q-p)*fraction for p,q in zip(pos,endpoint)) if fraction<1 else endpoint
                if hypot(nxt[0]-pos[0],nxt[1]-pos[1])>1e-6:
                    a["heading"]=atan2(nxt[1]-pos[1],nxt[0]-pos[0])
                a["x"],a["y"],a["z"]=nxt
                pos=nxt
                moved=True
            pace-=length
            if pace>=0:
                a["navArea"]=node[3]
                a["path"].pop(0)
        return moved

    @cached_property
    def descriptor(self):
        scale=self.overview["scale"]/UNIT
        spawns=[]
        for side in ("T","CT"):
            for i in range(len(self.spawns[side])):
                (x,y,z),_,_=self.spawn(side,i)
                spawns.append(dict(team=side,x=x,y=y,z=z))
        zones=[]
        for site,p in self.site_points.items():
            zones.append(dict(name=site,x=p[0]-4,y=p[1]-4,z=p[2],w=8,h=8))
        return dict(id=self.name,version=BUILD,name=NAMES[self.name],author=f"Valve · Steam {BUILD}",
                    width=1024*scale,height=1024*scale,walls=[],zones=zones,spawns=spawns,
                    radar=f"/api/maps/{self.name}/radar",layers=self.overview.get("verticalsections",{}))
