#include "grenades.hpp"
#include "group_tasks.hpp"

namespace esport {
Json AgentTurn::coordinated_peek(const Point &goal, const Json &step, bool arrived, const Json &partner) {
    const auto pos = actor_point(a);
    auto it = a.find("groupLead");
    if (it == a.end() || it->at("step") != step) {
        if (!arrived || !can_support(*this) || active(a, "groupDuty"))
            return nullptr;
        const Tick until = offer_deadline(false);
        const int delay = radio_delay(*this);
        if (until <= now + 2 * delay)
            return nullptr;
        Point aim = pos;
        const double fraction = std::min(1., 14 / std::max(1., distance(pos, goal)));
        for (size_t i = 0; i < 3; ++i)
            aim[i] += (goal[i] - pos[i]) * fraction;
        Json members = partner.is_null() ? nominate_group(pos, aim, until) : Json::array({partner});
        if (members.empty())
            return nullptr;
        const Json ticket = Json::array({a.at("id"), "stage", now});
        a["groupLead"] = {
            {"step", step}, {"ticket", ticket}, {"until", until}, {"closed", false}, {"worked", now}};
        signal_group("stage", "stage", aim, step,
                     {{"members", members}, {"until", until}, {"phase", w.at("phase")}});
    }
    auto &lead = a.at("groupLead");
    if (lead.at("closed") == true)
        return nullptr;
    lead["worked"] = now;
    const Json ticket = lead.at("ticket"), request = a.at("sentFeedback").at("stage");
    auto stop = [&](const char *state) {
        a.at("groupLead")["closed"] = true;
        signal_group("launch", state, pos, ticket, {{"until", now}});
        return Json(nullptr);
    };
    if (!can_support(*this) || now >= lead.at("until") || active(a, "groupDuty"))
        return stop("cancel");
    auto wait = [&]() {
        heading_to(a, request.at("point"));
        a["status"] = "Ждёт прикрытия на рубеже";
        return Json::array({"hold", nullptr});
    };
    if (lead.contains("at")) {
        const Json &id = lead.at("mate");
        auto partner_reply = recent_call(id, reply_channel(ticket), 45);
        if (!living_mate(*this, id) || (partner_reply && partner_reply->at("order") == ticket &&
                                        terminal_reply(partner_reply->at("state"))))
            return stop("cancel");
        if (now <= lead.at("at") &&
            (!partner_reply || partner_reply->at("order") != ticket ||
             distance(actor_point(*living_mate(*this, id)), partner_reply->at("origin").get<Point>()) > 5))
            return stop("cancel");
        if (now < lead.at("at"))
            return wait();
        if (now > lead.at("at").get<Tick>() + 3)
            return stop("complete");
        if (waiting_for_ticket_flash(*this, ticket))
            return wait();
        auto intent = movement(goal, 2);
        if (intent.at(0) != "move")
            return stop("cancel");
        heading_to(a, request.at("point"));
        a["status"] = "Выходит под прикрытие напарника";
        return intent;
    }
    if (distance(pos, request.at("origin").get<Point>()) > 5)
        return stop("cancel");
    const Json *chosen = nullptr;
    bool pending = false, primary_casting = false;
    for (const auto &id : request.at("members")) {
        const auto mate = living_mate(*this, id);
        if (!mate)
            continue;
        auto reply = recent_call(id, reply_channel(ticket), 32);
        if (reply && reply->at("order") == ticket) {
            if (terminal_reply(reply->at("state")))
                continue;
            if (coordinated_utility(w) && id == request.at("members").front() &&
                reply->at("state") == "casting")
                primary_casting = true;
            if (reply->at("state") == "set" &&
                distance(actor_point(*mate), reply->at("origin").get<Point>()) < 5 &&
                (!chosen || (!chosen->value("wing", false) && reply->value("wing", false))))
                chosen = reply;
        }
        pending = true;
    }
    if (!pending)
        return stop("cancel");
    if (chosen && !primary_casting) {
        Tick launch = std::max(now + radio_delay(*this), chosen->value("coverAt", now));
        if (a.contains("crossingCalls"))
            for (const auto &cast : a.at("crossingCalls"))
                if (cast.at("item") == "Свет" && (cast.value("ticket", Json(nullptr)) == ticket ||
                                                  cast.value("forPlayer", Json(nullptr)) == a.at("id")))
                    launch = std::max(launch, cast.value("land", launch));
        if (launch >= lead.at("until"))
            return stop("cancel");
        const Json mate = chosen->at("sender");
        lead["at"] = launch;
        lead["mate"] = mate;
        signal_group("launch", "go", goal, ticket,
                     {{"at", launch}, {"mate", mate}, {"until", lead.at("until")}});
    }
    return wait();
}
} // namespace esport
