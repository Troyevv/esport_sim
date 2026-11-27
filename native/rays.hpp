#pragma once

#include "rtcore_ray.h"

#include <array>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <span>
#include <vector>

namespace esport {
using Vertex = std::array<float, 3>;
using Face = std::array<std::int32_t, 3>;

// Immutable triangle scene using the same wheel and kernel as the reference.
class TriangleScene {
public:
    TriangleScene(const std::filesystem::path& library, std::vector<Vertex> vertices,
                  const std::vector<Face>& faces, const std::vector<std::uint8_t>& masks);
    ~TriangleScene();
    std::size_t face_count() const;
    void intersect(std::span<RTCRayHit> rays) const;

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
}
