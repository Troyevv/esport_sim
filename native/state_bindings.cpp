#include "economy.hpp"
#include "grid_round.hpp"
#include "match_state.hpp"
#include "objectives.hpp"
#include "opening.hpp"
#include "tick_output.hpp"
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
void bind_state(py::module_ &module) {
    using namespace esport;
    using Release = py::call_guard<py::gil_scoped_release>;
    module.attr("MATCH_STATE_API_VERSION") = 3;
    module.def(
        "project_buy",
        [](const std::string &input, const std::string &side, const std::string &call,
           const std::string &rules) {
            auto w = Json::parse(input), cfg = Json::parse(rules);
            if (w.contains("mapId"))
                return buy_decision(w, cfg, side, call, nullptr, nullptr, nullptr)
                    .at("scenario")
                    .get<std::string>();
            auto buy = grid_buy(w, cfg, side, call);
            return buy == "Полная" || buy == "Форс" ? std::string("Оружейная") : buy;
        },
        Release());
    module.def(
        "round_checkpoint",
        [](const std::string &input, const std::string &rules, const std::string &spawn_table) {
            auto state = Json::parse(input);
            start_round(state, Json::parse(rules), Json::parse(spawn_table));
            return state.dump();
        },
        Release());
    py::class_<SiteData>(module, "SiteData")
        .def(py::init<decltype(SiteData::solids), decltype(SiteData::costs), decltype(SiteData::samples),
                      Ingress>());
    py::class_<Objectives, std::shared_ptr<Objectives>>(module, "Objectives")
        .def(py::init<std::shared_ptr<const PhysicalNavigation>, SiteData>(), Release())
        .def("site_at", &Objectives::site_at, Release());
    py::class_<OrderData>(module, "OrderData")
        .def(py::init<decltype(OrderData::places), decltype(OrderData::plants), decltype(OrderData::holds),
                      decltype(OrderData::nearby), decltype(OrderData::roles), decltype(OrderData::cover),
                      decltype(OrderData::attack_spawns), decltype(OrderData::plant_corners)>());
    py::class_<OpeningMap, std::shared_ptr<OpeningMap>>(module, "OpeningMap")
        .def(py::init<std::shared_ptr<const Objectives>, const std::string &, const std::string &,
                      ContestTable, Stations, std::map<std::string, Point>, OrderData>(),
             Release())
        .def(
            "editor_orders",
            [](const OpeningMap &map, const std::string &data, const std::string &side,
               const std::string &site, int lane, const std::string &style) {
                auto w = Json::parse(data);
                return (side == "T" ? map.attack_orders(w, site, lane, style)
                                    : map.defense_orders(w, site, lane))
                    .dump();
            },
            Release());
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
        .def(
            "advance_motion",
            [](MatchState &owner, int ticks) { return owner.advance_recorded(ticks, TickOutput::Motion); },
            Release())
        .def(
            "advance_preview",
            [](MatchState &owner, int ticks) { return owner.advance_recorded(ticks, TickOutput::Preview); },
            Release())
        .def(
            "profile_ticks",
            [](MatchState &owner, int ticks) { return owner.advance_recorded(ticks, TickOutput::Profile); },
            Release())
        .def("begin_live", &MatchState::begin_live, Release())
        .def("advance", &MatchState::advance, Release())
        .def("advance_intermission", &MatchState::advance_intermission, Release())
        .def("attach_opening", &MatchState::attach_opening, Release())
        .def("defense_orders", &MatchState::defense_orders, Release())
        .def("attack_orders", &MatchState::attack_orders, Release())
        .def("opening_call", &MatchState::opening_call, Release())
        .def("select_defense", &MatchState::select_defense, Release())
        .def("defensive_read", &MatchState::defensive_read, Release())
        .def("default_probe", &MatchState::default_probe, Release())
        .def("board_step", &MatchState::board_step, Release())
        .def("assign_board", &MatchState::assign_board, Release())
        .def("buy_decision", &MatchState::buy_decision, Release())
        .def("buy_equipment", &MatchState::buy_equipment, py::arg("side"), py::arg("strategy"),
             py::arg("board") = "null", Release())
        .def("attach_objectives", &MatchState::attach_objectives, Release())
        .def("resolve_intents", &MatchState::resolve_intents, Release())
        .def("attach_physics", &MatchState::attach_physics, Release())
        .def("priority_intent", &MatchState::priority_intent, Release())
        .def("review_captain", &MatchState::review_captain, Release())
        .def("observe", &MatchState::observe, Release())
        .def("apply_effects", &MatchState::apply_effects, Release())
        .def("resolve_actions", &MatchState::resolve_actions, Release())
        .def("attach_spawns", &MatchState::attach_spawns, Release())
        .def("finish_round", &MatchState::finish_round, Release())
        .def("deliver_radio", &MatchState::deliver_radio, Release());
}
