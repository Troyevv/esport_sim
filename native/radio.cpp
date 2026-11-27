#include "radio.hpp"
#include <algorithm>
#include <cmath>
#include <tuple>

namespace esport {
bool peer_radio(const Json &world) {
    return world.value("agentPolicy", 0) == 3;
}

int reception_quality(const Json &world, const Json &sender, const Json &recipient) {
    const auto &speaker = player_profile(world, sender).at("skills");
    const auto &listener = player_profile(world, recipient).at("skills");
    return (speaker.at("communication").get<int>() + listener.at("coordination").get<int>() +
            chemistry(world, sender, recipient)) / 3;
}

void report_contact(Json &world, Json &actor, const Json &sight) {
    const Tick now = world.at("tick");
    const int skill = player_profile(world, actor).at("skills").at("communication");
    Json packet = sight;
    if (peer_radio(world)) {
        const auto id = sight.at("id").get<std::string>();
        auto &last = actor["sentContacts"][id];
        Json details = Json::array({sight.value("weapon", ""), sight.value("carryingC4", false),
                                    sight.value("interaction", ""), sight.value("groupSize", 1)});
        if (!last.is_null()) {
            auto age = now - last.at("tick").get<Tick>();
            if (age < 4 || (age < 24 && last.at("details") == details &&
                            distance(last.at("point").get<Point>(), actor_point(sight)) < 8))
                return;
        }
        last = {{"tick", now}, {"point", actor_point(sight)}, {"details", std::move(details)}};
        packet.erase("motionHistory");
    }
    world.at("messages").push_back({{"team", actor.at("team")}, {"sender", actor.at("id")},
                                    {"sight", std::move(packet)}, {"due", plus_ticks(now, 1 + (100 - skill) / 12)}});
}

namespace {
double strength(const Json &report) {
    return report.value("signalStrength", report.value("confidence", report.at("source") == "Зрение" ? 1. : .65));
}
}

bool accept_report(Json &incoming, Json *prior, const std::string &sender, int quality, Tick now) {
    const Tick observed = incoming.at("tick");
    if (observed > now || now - observed >= 75)
        return false;
    const double intrinsic = strength(incoming);
    const double signal = intrinsic * (.55 + .004 * quality);
    incoming["signalStrength"] = signal;
    incoming["confidence"] = signal;
    incoming["reporter"] = sender;
    if (!prior)
        return true;
    const Tick previous = prior->at("tick");
    // Within the freshness window, prefer the better witness. A direct view
    // wins at equal time. The sender ID resolves equally credible peer reports.
    const bool conflict = std::abs(observed - previous) <= 5 &&
                          distance(actor_point(incoming), actor_point(*prior)) > 18;
    auto rank = [now](const Json &r) {
        auto tick = r.at("tick").get<Tick>();
        return std::tuple{strength(r) - .06 * double(now - tick), tick, r.value("reporter", std::string{})};
    };
    bool wins = observed > previous;
    if (observed == previous || conflict)
        wins = rank(incoming) > rank(*prior);
    Json &winner = wins ? incoming : *prior;
    if (conflict && winner.contains("reporter")) {
        winner["disputed"] = true;
        winner["confidence"] = strength(winner) * .65;
    }
    return wins;
}
}
