"""Visibility helpers for viewer-filtered match snapshots."""
from math import cos, hypot, sin
from . import engine
from .cs2_maps import xyz


def point(a):
    return xyz(a) if "z" in a else (a["x"], a["y"])

def in_view(a,b):
    dx,dy=b["x"]-a["x"],b["y"]-a["y"]
    d2=dx*dx+dy*dy
    dot=dx*cos(a["heading"])+dy*sin(a["heading"])
    return dot>=0 and 4*dot*dot >= d2

def sees(space,a,b):
    return in_view(a,b) and space.clear(a,b) if space else engine.sees(a,b)

def at(xy):
    return dict(zip(("x","y","z"),xy))

def near_line(a, b, p, radius):
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    dz = b.get("z",0)-a.get("z",0)
    length = dx * dx + dy * dy + dz*dz
    ratio = (
        max(0, min(1, ((p["x"] - a["x"]) * dx + (p["y"] - a["y"]) * dy + (p.get("z",0)-a.get("z",0))*dz) / length))
        if length
        else 0
    )
    return hypot(a["x"] + ratio * dx - p["x"], a["y"] + ratio * dy - p["y"], a.get("z",0)+ratio*dz-p.get("z",0)) <= radius
