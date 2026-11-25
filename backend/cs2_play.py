"""Map-dependent choices for the shared BO1 agents, using squad observations."""

from math import atan2, dist, pi, sin
from .cs2_maps import UNIT, xyz
from . import match_performance as perf
from .match_rules import RULES, equipment_value


def exit_goal(space,w,a,allies,bomb):
    site = (bomb and bomb["site"]) or a["heardSite"] or w["plan"]["reinforce"]
    if not site:
        return
    pos = xyz(bomb) if bomb else space.site_points[site]
    area = a["navArea"]
    routes = space.escape(pos)
    if area not in routes.costs:
        return
    remaining = w["deadline"]-w["tick"]
    speed = 2 * perf.move_speed(w["player"])
    threats = sum(p["source"]!="Слух" and w["tick"]-p["tick"]<32 and dist(xyz(p),pos)<60
                  for p in a["knowledge"].values())
    if a["team"]=="T":
        if remaining > routes.costs[area]/UNIT/speed + 12 + equipment_value(a)/450 - threats*3:
            return
    else:
        if w["action"]:
            return
        to = space.locate(pos)
        path = space.route(area,to)
        length=0.
        prev=xyz(a)
        if path is not None:
            for cross in path:
                exit,entry=space.to_sim(cross.leave),space.to_sim(cross.enter)
                length+=dist(prev,exit)+dist(exit,entry)
                prev=entry
            length+=dist(prev,pos)
        if path is not None and remaining > max(0,length-6)/speed + (RULES["kitDefuse"] if a["kit"] else RULES["defuse"]) + max(0,threats-len(allies)+1)*8:
            return
    _, goals = routes.route(area)
    return space.centers[goals[-1]]


def spatial_intent(space,w,a,allies,bomb,fire,travel):
    now,plan=w["tick"],w["plan"]
    side,slot=a["team"],a["slot"]
    order=plan["orders"]["slots"][slot]
    site=plan["site"]
    pos=xyz(a)
    recent=[p for p in a["knowledge"].values() if now-p["tick"]<35]
    latest=max(recent,key=lambda p:p["tick"],default=None)
    goal=order["hold"]
    if w["phase"]=="planted":
        if side=="CT":
            site=a["heardSite"] or plan["reinforce"] or order["site"]
            goal=xyz(bomb) if bomb else space.site_points[site]
            other=w["action"] and w["action"]["player"]!=a["id"]
            if bomb and dist(pos,goal)<=6 and not other and space.clear(a,bomb):
                return "defuse",None
            if other:
                goal=space.holds[site][slot][1] if len(space.holds[site])>slot else space.site_points[site]
            a["status"]="Прикрывает разминирование" if other else "Идёт на ретейк"
        else:
            site=bomb["site"]
            if order["site"]!=site:
                goal=space.site_points[site]
            a["status"]="Прикрывает C4"
    elif side=="T":
        if bomb and not bomb["carrier"] and min(allies,key=lambda p:(dist(xyz(p),xyz(bomb)),p["slot"])) is a:
            goal=xyz(bomb)
            a["status"]="Подбирает C4"
        else:
            carrier=bomb and bomb["carrier"]==a["id"]
            if carrier:
                at=space.site_at(pos)
                if at and (at==site or w["deadline"]-now<90):
                    return "plant",at
            route=order["via"]
            index=a["waypoint"]
            if index<len(route) and dist(pos,route[index])<2.6:
                index+=1
                a["waypoint"]=index
            if index<len(route) and w["deadline"]-now>145:
                goal=route[index]
            elif carrier:
                goal=order["plant"]
            a["status"]=f"Выход на {site}"
            if index and index<len(route) and plan["style"]=="Сбор":
                partners=[p for p in allies if p is not a and plan["orders"]["slots"][p["slot"]]["via"]==route]
                if partners and now-plan["start"]<230 and min(dist(pos,xyz(p)) for p in partners)>35:
                    goal=pos
                    a["status"]="Ждёт партнёра для выхода"
    else:
        site=order["site"]
        if plan["reinforce"] and slot in (1,4):
            site=plan["reinforce"]
            goal=space.site_points[site]
        a["status"]=f"Занимает {site}"
    if latest and (side=="CT" or not bomb or bomb["carrier"]!=a["id"]) and not w["action"]:
        if dist(goal,xyz(latest))<40 and dist(pos,xyz(latest))>6:
            goal=xyz(latest)
            a["status"]="Проверяет сообщение о контакте"
    moved=travel(a,goal,2 if plan["style"]=="Быстро" or w["phase"]=="planted" else 1.65,fire,allow_detour=True)
    if moved:
        return "move",None
    # Watch an approach known to this team or turn toward the last reported contact.
    watch=xyz(latest) if latest else order["watch"]
    a["heading"]=atan2(watch[1]-a["y"],watch[0]-a["x"])+0.65*sin((now+13*slot)/26)
    return "hold",None
