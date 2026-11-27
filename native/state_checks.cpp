#include "match_state.hpp"

#include <fstream>
#include <iterator>
#include <stdexcept>

int main(int argc, char **argv) {
    if (argc != 2)
        return 2;
    std::ifstream source(argv[1], std::ios::binary);
    std::string saved((std::istreambuf_iterator<char>(source)), {});
    for (int i = 0; i < 10; ++i) {
        esport::MatchState original(saved, "cs2-bo1.20", {}, {}, 45, 26879581, "{}");
        original.deliver_radio();
        original.command("timeout", "");
        auto snapshot = original.snapshot();
        esport::MatchState restored(snapshot, "cs2-bo1.20", {}, {}, 45, 26879581, "{}");
        if (restored.snapshot() != snapshot)
            throw std::runtime_error("Native checkpoint changed during restore");
    }
}
