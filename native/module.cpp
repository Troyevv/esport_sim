#include "routes.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(_match_native, module) {
    module.doc() = "Detailed match engine components";
    module.attr("NAV_API_VERSION") = 1;
    module.attr("PORTAL_API_VERSION") = 1;
    using Release = py::call_guard<py::gil_scoped_release>;
    py::class_<esport::StageRoutes>(module, "StageRoutes")
        .def("costs", &esport::StageRoutes::costs, Release())
        .def("route", &esport::StageRoutes::route, Release());
    py::class_<esport::PortalGraph, std::shared_ptr<esport::PortalGraph>>(module, "PortalGraph")
        .def(py::init(&esport::PortalGraph::create),
             py::arg("centers"), py::arg("portals"), Release())
        .def("route", &esport::PortalGraph::route, py::arg("start"), py::arg("goal"),
             py::arg("avoided"), py::arg("excluded"), Release())
        .def("routes_through", &esport::PortalGraph::routes_through, py::arg("choices"), Release());
    py::class_<esport::NavSurfaces>(module, "NavSurfaces")
        .def(py::init<std::vector<esport::Area>>(), py::arg("areas"),
             py::call_guard<py::gil_scoped_release>())
        .def("locate_many", &esport::NavSurfaces::locate_many,
             py::arg("points"), py::arg("max_vertical"), py::call_guard<py::gil_scoped_release>());
}
