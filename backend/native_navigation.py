"""Build native NAV indices from the installed Source 2 export."""
from functools import cached_property

from ._match_native import NavSurfaces, PortalGraph
from .cs2_navigation import NavigationData


class NativeStageRoutes:
    def __init__(self, plan, crossings):
        self.plan = plan
        self.crossings = crossings

    @cached_property
    def costs(self):
        return self.plan.costs()

    def route(self, start):
        result = self.plan.route(start)
        if result is not None:
            edges, waypoints = result
            return [self.crossings[i] for i in edges], waypoints
        return None


class NativeNavigation(NavigationData):
    def __init__(self, data):
        super().__init__(data)
        self._index_portals()
        self.surfaces = NavSurfaces([(area, desc["corners"]) for area, desc in self.areas.items()])

    def _index_portals(self):
        portals = []
        self.crossings = []
        for area, crossings in self.links.items():
            for crossing in crossings:
                portals.append((area, crossing.area, self._cost(area, crossing)))
                self.crossings.append(crossing)
        self.graph = PortalGraph(self.centers, portals)

    def locate(self, point, max_vertical):
        return self.surfaces.locate_many([point], max_vertical)[0]

    def route(self, start, goal, *, avoided=frozenset(), excluded=frozenset()):
        if start is None or goal is None:
            return None
        edges = self.graph.route(start, goal, avoided, excluded)
        return None if edges is None else [self.crossings[i] for i in edges]

    def routes_through(self, stages):
        return NativeStageRoutes(self.graph.routes_through([list(stage) for stage in stages]), self.crossings)
