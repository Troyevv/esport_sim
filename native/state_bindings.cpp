#include "match_state.hpp"
#include "physical_navigation.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
void bind_state(py::module_ &module) {
    using namespace esport;
    using Release = py::call_guard<py::gil_scoped_release>;
    module.attr("MATCH_STATE_API_VERSION") = 1;
    py::class_<MatchState>(module, "MatchState")
        .def(py::init<const std::string &, std::string, std::set<std::string>, std::set<std::string>, int,
                      int, const std::string &>(),
             Release())
        .def("snapshot",
             [](const MatchState &match) {
                 std::string json;
                 {
                     py::gil_scoped_release release;
                     json = match.snapshot();
                 }
                 return py::bytes(json);
             })
        .def("command", &MatchState::command, py::arg("kind"), py::arg("value") = "", Release())
        .def("advance_intermission", &MatchState::advance_intermission, Release())
        .def("attach_physics", &MatchState::attach_physics, Release())
        .def("apply_effects", &MatchState::apply_effects, Release())
        .def("resolve_actions", &MatchState::resolve_actions, Release())
        .def("attach_spawns", &MatchState::attach_spawns, Release())
        .def("finish_round", &MatchState::finish_round, Release())
        .def("deliver_radio", &MatchState::deliver_radio, Release());
}
