#include "coaching.hpp"
#include "perception.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

void bind_state(py::module_ &module);
void bind_collision(py::module_ &module);
void bind_rays(py::module_ &module);

PYBIND11_MODULE(_match_native, module) {
    bind_state(module);
    bind_rays(module);
    bind_collision(module);
    module.doc() = "Detailed match engine components";
    module.attr("NAV_API_VERSION") = 1;
    module.attr("PORTAL_API_VERSION") = 1;
    using Release = py::call_guard<py::gil_scoped_release>;
    py::class_<esport::StageRoutes>(module, "StageRoutes")
        .def("costs", &esport::StageRoutes::costs, Release())
        .def("route", &esport::StageRoutes::route, Release());
    py::class_<esport::PortalGraph, std::shared_ptr<esport::PortalGraph>>(module, "PortalGraph")
        .def(py::init(&esport::PortalGraph::create), py::arg("centers"), py::arg("portals"), Release())
        .def("route", &esport::PortalGraph::route, py::arg("start"), py::arg("goal"), py::arg("avoided"),
             py::arg("excluded"), Release())
        .def("routes_through", &esport::PortalGraph::routes_through, py::arg("choices"), Release());
    py::class_<esport::NavSurfaces, std::shared_ptr<esport::NavSurfaces>>(module, "NavSurfaces")
        .def(py::init<std::vector<esport::Area>>(), py::arg("areas"),
             py::call_guard<py::gil_scoped_release>())
        .def("locate_many", &esport::NavSurfaces::locate_many, py::arg("points"), py::arg("max_vertical"),
             py::call_guard<py::gil_scoped_release>());
    using namespace esport;
    module.def("timeout_need", &timeout_need);
    module.attr("PHYSICAL_NAV_API_VERSION") = 1;
    py::class_<Crossing>(module, "PhysicalCrossing").def(py::init<AreaId, AreaId, bool, std::vector<Lane>>());
    py::class_<MotionState>(module, "MotionState")
        .def(py::init<Point, AreaId, double, int, WalkPath, std::optional<Destination>>())
        .def_readonly("position", &MotionState::position)
        .def_readonly("area", &MotionState::area)
        .def_readonly("heading", &MotionState::heading)
        .def_readonly("blocked_ticks", &MotionState::blocked_ticks)
        .def_readonly("destination", &MotionState::destination)
        .def_readonly("path", &MotionState::path);
    py::class_<MoveResult>(module, "MoveResult")
        .def_readonly("moved", &MoveResult::moved)
        .def_readonly("waiting", &MoveResult::waiting)
        .def_readonly("replanned", &MoveResult::replanned)
        .def_readonly("consumed", &MoveResult::consumed);
    py::class_<PhysicalNavigation, std::shared_ptr<PhysicalNavigation>>(module, "PhysicalNavigation")
        .def(py::init<std::shared_ptr<const CollisionWorld>, std::shared_ptr<const PortalGraph>,
                      std::shared_ptr<const NavSurfaces>, Point, double, std::map<AreaId, Point>,
                      std::vector<Area>, std::set<Point>, std::vector<Crossing>>(),
             Release())
        .def(
            "walk",
            [](const PhysicalNavigation &planner, MotionState actor, const Point &goal, double pace,
               const std::vector<Hazard> &fire) {
                auto result = planner.walk(actor, goal, pace, fire);
                return std::pair{std::move(actor), result};
            },
            Release())
        .def("grenade", &PhysicalNavigation::grenade, Release())
        .def("path", &PhysicalNavigation::path, Release())
        .def("escape", &PhysicalNavigation::escape, Release());

    py::class_<Observer>(module, "Observer").def(py::init<Point, double, bool, bool>());
    py::class_<Listener>(module, "Listener").def(py::init<Point, double, bool>());
    py::class_<Heard>(module, "Heard")
        .def_readonly("listener", &Heard::listener)
        .def_readonly("estimate", &Heard::estimate)
        .def_readonly("confidence", &Heard::confidence);
    py::class_<MapSensors>(module, "MapSensors")
        .def(py::init<std::shared_ptr<const PhysicalNavigation>, std::vector<std::string>>(), Release())
        .def("observe", &MapSensors::observe, Release())
        .def("hear", &MapSensors::hear, Release())
        .def("shot_transmission", &MapSensors::shot_transmission, Release());
}
