#include "grenades.hpp"
#include "group_tasks.hpp"

namespace esport {
namespace {
void reply(AgentTurn &t, const Json &ticket, const char *state, const Point &aim, Tick until, bool wing) {
    t.signal_group(reply_channel(ticket), state, aim, ticket,
                   {{"duty", true}, {"until", until}, {"wing", wing}});
}

void close_duty(AgentTurn &t, const char *state) {
    auto duty = t.a.find("groupDuty");
    if (duty == t.a.end())
        return;
    Json record = std::move(*duty);
    t.a.erase(duty);
    reply(t, record.at("ticket"), state, record.at("aim"), record.at("until"), record.at("wing"));
}

Point wing_angle(const Point &from, const Point &forward, const Point &origin, int seat) {
    const double dx = forward[0] - origin[0], dy = forward[1] - origin[1];
    const double norm = std::max(1., std::hypot(dx, dy));
    double offset = (from[1] - origin[1]) * dx - (from[0] - origin[0]) * dy;
    double side = offset == 0 ? (seat % 2 ? -1. : 1.) : std::copysign(1., offset);
    return {forward[0] - side * dy * 6 / norm, forward[1] + side * dx * 6 / norm, forward[2]};
}

Json support_flash(AgentTurn &t, const Json &offer, const Point &pos) {
    if (t.grid || !member_of(t.a.at("utility"), "Свет") || t.a.at("throwAt") > t.now ||
        t.now + t.cfg.at("throwRecovery").get<int>() + 2 * radio_delay(t) >= offer.at("until").get<Tick>())
        return nullptr;
    const auto &nav = t.arena.objectives().map();
    const auto aim = offer.at("point").get<Point>(), origin = offer.at("origin").get<Point>();
    const double reach = distance(origin, aim);
    if (reach < 5)
        return nullptr;
    const double radius = t.cfg.at("utility").at("Свет")[0];
    Point target = aim;
    for (size_t i = 0; i < 3; ++i)
        target[i] += (aim[i] - origin[i]) * radius * (spatial_grenades(t.w) ? .45 : 1.) / reach;
    const int flight = std::max(3, int(std::nearbyint(distance(pos, target) / 7)));
    const auto land = nav.grenade(pos, target, flight).back();
    if (distance(land, target) > 5 || std::ranges::any_of(t.squad, [&](auto m) {
            if (spatial_grenades(t.w))
                return t.flash_risk(*m, land, flight);
            return distance(actor_point(*m), land) < radius + 3 && !nav.hit(land, actor_point(*m), 1, 5, 64);
        }))
        return nullptr;
    auto cmd = grenade_intent(target, "Свет", "Прикрывает согласованный выход");
    cmd[1]["groupTicket"] = group_ticket(offer);
    return cmd;
}
} // namespace

Json AgentTurn::execute_group_task(const Json &offer) {
    const auto ticket = group_ticket(offer);
    const auto origin = offer.at("origin").get<Point>(), point = offer.at("point").get<Point>();
    const Tick until = offer.value("until", ticket.at(2).get<Tick>() + 25);
    const bool staged = offer.at("state") == "stage";
    const auto &primary = offer.at("members").front();
    const auto prior = recent_call(primary, reply_channel(ticket), 50);
    const bool transferred = !living_mate(*this, primary) ||
                             (prior && prior->at("order") == ticket && terminal_reply(prior->at("state")));
    const bool mobile = (primary == a.at("id") || transferred) && !protects_sector(a);
    const bool sender_alive = living_mate(*this, ticket.at(0));
    const auto pos = actor_point(a);
    if (active(a, "groupLead") && !a.at("groupLead").at("closed").get<bool>()) {
        const Json previous = a.at("groupLead").at("ticket");
        a.at("groupLead")["closed"] = true;
        signal_group("launch", "cancel", pos, previous, {{"until", now}});
    }
    if (active(a, "groupDuty") && a.at("groupDuty").at("ticket") != ticket)
        close_duty(*this, "cancel");
    if (!active(a, "groupDuty")) {
        a["groupDuty"] = {{"ticket", ticket}, {"aim", point},  {"until", until},   {"wing", mobile},
                          {"accepted", now},  {"worked", now}, {"state", "accept"}};
        reply(*this, ticket, "accept", point, until, mobile);
    }
    auto &initial = a.at("groupDuty");
    initial["worked"] = now;
    initial["wing"] = mobile;
    auto announce = [&](const char *state, const Point &aim) {
        a.at("groupDuty")["state"] = state;
        reply(*this, ticket, state, aim, until, mobile);
    };
    auto release = recent_call(ticket.at(0), "launch", 50);
    if (staged && release && release->at("order") == ticket && release->at("state") == "go") {
        const Json launch = *release;
        if (!sender_alive || !can_support(*this) || now > launch.at("at").get<Tick>() + 3) {
            close_duty(*this, sender_alive ? "complete" : "cancel");
            return nullptr;
        }
        if (now >= launch.at("at") && launch.at("mate") == a.at("id") && initial.contains("step") && mobile) {
            const Point step = initial.at("step"), angle = initial.at("angle");
            if (distance(pos, step) > 1 && move(step, 2)) {
                heading_to(a, angle);
                announce("executing", angle);
                a["status"] = "Выходит вторым номером";
                return Json::array({"move", nullptr});
            }
            close_duty(*this, "complete");
            return nullptr;
        }
    }
    if (!staged && mobile && sender_alive && !grid && offer.at("state") == "help" && now >= a.at("throwAt") &&
        !a.at("utility").empty()) {
        auto r = a.at("knowledge").find(offer.at("order").get<std::string>());
        if (r != a.at("knowledge").end()) {
            auto cast = assist_contact({living_mate(*this, ticket.at(0))}, *r);
            if (!cast.empty()) {
                cast[1]["purpose"] = "Поддержка по запросу напарника";
                close_duty(*this, "complete");
                return cast;
            }
        }
    }
    const bool approach = mobile && sender_alive && (staged || offer.at("state") == "help");
    if (approach && distance(pos, origin) > (staged ? 12 : 14) && !cover_from_place(a, origin, point)) {
        bool moved =
            grid ? grid->walk(a, Json::array({origin[0], origin[1]}), 2 * move_speed(player), grid_fire, true)
                 : move(origin, 2);
        if (!moved) {
            close_duty(*this, "decline");
            return nullptr;
        }
        announce("preparing", point);
        a["status"] = "Идёт на запрос помощи";
        return Json::array({"move", nullptr});
    }
    auto &duty = a.at("groupDuty");
    if (staged && sender_alive && mobile && !duty.contains("flashTried")) {
        duty["flashTried"] = true;
        auto cast = support_flash(*this, offer, pos);
        if (!cast.empty()) {
            announce("casting", point);
            return cast;
        }
    }
    if (staged && duty.contains("land") &&
        now < std::max(duty.at("land").get<Tick>(), a.at("ready").get<Tick>())) {
        heading_to(a, point);
        a["status"] = "Ждёт срабатывания своей гранаты";
        return Json::array({"hold", nullptr});
    }
    const double heading = a.at("heading");
    Point angle = staged ? wing_angle(pos, point, origin, slot) : point;
    heading_to(a, angle);
    if (!group_lane(angle)) {
        angle = point;
        heading_to(a, angle);
    }
    if (!group_lane(angle)) {
        a["heading"] = heading;
        close_duty(*this, "decline");
        return nullptr;
    }
    if (staged && !grid && !duty.contains("step") && mobile) {
        Point step = pos;
        const double span = std::max(1., distance(pos, angle));
        for (size_t i = 0; i < 3; ++i)
            step[i] += (angle[i] - pos[i]) * std::min(1., 6 / span);
        auto &nav = arena.objectives().map();
        auto area = nav.locate(step);
        if (area && !nav.hit(pos, step, 1, 64, 64) && nav.path(a.at("navArea"), pos, *area, step, {}))
            duty["step"] = step;
    }
    duty["angle"] = angle;
    announce(staged ? "set" : "executing", angle);
    a["status"] = !sender_alive ? "Принимает сектор напарника"
                  : mobile      ? "Прикрывает направление по радио"
                                : "Страхует группу со своей позиции";
    return Json::array({"hold", nullptr});
}

void AgentTurn::finish_group_tasks() {
    auto duty = a.find("groupDuty");
    if (duty != a.end() && (now >= duty->at("until") || duty->at("worked") != now)) {
        const bool fulfilled = duty->at("state") == "executing" && a.at("visible").empty();
        close_duty(*this, fulfilled ? "complete" : "cancel");
    }
    if (active(a, "groupLead") && !a.at("groupLead").at("closed").get<bool>() &&
        a.at("groupLead").at("worked") != now) {
        const Json lead = a.at("groupLead");
        a.at("groupLead")["closed"] = true;
        signal_group("launch", "cancel", actor_point(a), lead.at("ticket"), {{"until", now}});
    }
    if (a.value("groupInboxTick", Tick{-1}) != now)
        return;
    if (!a.contains("sentFeedback"))
        a["sentFeedback"] = Json::object();
    for (const auto &offer : a.at("peerCalls")) {
        if (!offer.contains("members") || !member_of(offer.at("members"), a.at("id")) ||
            now >= offer.value("until", Tick{0}))
            continue;
        const Json ticket = group_ticket(offer);
        if (active(a, "groupDuty") && a.at("groupDuty").at("ticket") == ticket)
            continue;
        const auto channel = reply_channel(ticket);
        auto sent = a.find("sentFeedback");
        if (sent != a.end() && sent->contains(channel) && sent->at(channel).at("order") == ticket)
            continue;
        reply(*this, ticket, "decline", offer.at("point"), offer.at("until"), false);
    }
}
} // namespace esport
