#include "navigation.hpp"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;

PYBIND11_MODULE(_match_native, module) {
    module.doc() = "Detailed match engine components";
    module.attr("NAV_API_VERSION") = 1;
    py::class_<esport::NavSurfaces>(module, "NavSurfaces")
        .def(py::init<std::vector<esport::Area>>(), py::arg("areas"),
             py::call_guard<py::gil_scoped_release>())
        .def("locate_many", &esport::NavSurfaces::locate_many,
             py::arg("points"), py::arg("max_vertical"), py::call_guard<py::gil_scoped_release>());
}
