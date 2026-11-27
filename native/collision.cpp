#include "collision.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace esport {
namespace {
Point sub(const Point &a, const Point &b) { return {a[0] - b[0], a[1] - b[1], a[2] - b[2]}; }
Point along(const Point &a, const Point &v, double t) {
    return {a[0] + t * v[0], a[1] + t * v[1], a[2] + t * v[2]};
}
double dot(const Point &a, const Point &b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
Point transform(const Point &p, const Matrix &m) {
    Point result{};
    for (int j = 0; j < 3; ++j)
        result[j] = p[0] * m[0][j] + p[1] * m[1][j] + p[2] * m[2][j];
    return result;
}
bool finite(const Point &p) {
    return std::ranges::all_of(p, [](double x) { return std::isfinite(x); });
}

std::optional<std::pair<double, Point>> intersect(const Primitive &shape, const Point &start,
                                                  const Point &delta) {
    const auto origin = transform(sub(start, shape.translation), shape.inverse);
    const auto ray = transform(delta, shape.inverse);
    const auto offset = sub(origin, shape.first);
    const double radius2 = shape.radius * shape.radius;
    double best = std::numeric_limits<double>::infinity();
    auto roots = [&](double a, double b, double c, auto accepts) {
        const double discriminant = b * b - a * c;
        if (a <= 1e-15 || discriminant < 0)
            return;
        const double root = std::sqrt(discriminant);
        for (double t : {(-b - root) / a, (-b + root) / a})
            if (t >= 0 && t <= 1 && t < best && accepts(t))
                best = t;
    };
    if (shape.length > 0) {
        const double height = dot(offset, shape.axis), speed = dot(ray, shape.axis);
        const auto radial = along(offset, shape.axis, -height);
        const auto velocity = along(ray, shape.axis, -speed);
        roots(dot(velocity, velocity), dot(radial, velocity), dot(radial, radial) - radius2, [&](double t) {
            const auto h = height + t * speed;
            return h >= 0 && h <= shape.length;
        });
    }
    for (int cap = 0; cap < (shape.length ? 2 : 1); ++cap) {
        const auto diff = sub(origin, cap ? shape.last : shape.first);
        roots(dot(ray, ray), dot(diff, ray), dot(diff, diff) - radius2, [&](double t) {
            if (shape.length == 0)
                return true;
            const double h = dot(sub(along(origin, ray, t), shape.first), shape.axis);
            return cap ? h >= shape.length : h <= 0;
        });
    }
    if (!std::isfinite(best))
        return std::nullopt;
    const auto position = along(origin, ray, best);
    const auto h = std::clamp(dot(sub(position, shape.first), shape.axis), 0., shape.length);
    const auto normal = sub(position, along(shape.first, shape.axis, h));
    return std::pair{best, Point{dot(normal, shape.inverse[0]), dot(normal, shape.inverse[1]),
                                 dot(normal, shape.inverse[2])}};
}

RTCRayHit segment(const Point &start, const Point &delta, unsigned channel) {
    RTCRayHit value{};
    auto &r = value.ray;
    r.org_x = float(start[0]);
    r.org_y = float(start[1]);
    r.org_z = float(start[2]);
    r.dir_x = float(delta[0]);
    r.dir_y = float(delta[1]);
    r.dir_z = float(delta[2]);
    r.mask = channel;
    r.tfar = 1;
    return value;
}
// NumPy's single-precision 3-vector norm/dot rounds each product first.
float dot3f(float p, float q, float r) { return float(double(p) + double(q) + double(r)); }
float norm(float x, float y, float z) { return std::sqrt(dot3f(x * x, y * y, z * z)); }
} // namespace

CollisionWorld::CollisionWorld(std::shared_ptr<const TriangleScene> mesh,
                               std::vector<unsigned short> materials, std::vector<Primitive> shapes)
    : mesh_(std::move(mesh)), materials_(std::move(materials)), shapes_(std::move(shapes)) {
    if (!mesh_ || mesh_->face_count() != materials_.size())
        throw std::invalid_argument("Expected one material per triangle");
    for (const auto &s : shapes_) {
        if (!(s.length >= 0 && std::isfinite(s.length) && s.radius >= 0 && std::isfinite(s.radius)) ||
            !finite(s.low) || !finite(s.high) || !finite(s.axis) || !finite(s.translation) ||
            !finite(s.first) || !finite(s.last) || !std::ranges::all_of(s.inverse, finite))
            throw std::invalid_argument("Invalid collision primitive");
    }
    if (!shapes_.empty())
        build(0, shapes_.size());
}

std::size_t CollisionWorld::build(std::size_t begin, std::size_t end) {
    Node node{shapes_[begin].low, shapes_[begin].high, 0, begin, end};
    for (auto i = begin; i < end; ++i) {
        node.mask |= shapes_[i].mask;
        for (int j = 0; j < 3; ++j) {
            node.low[j] = std::min(node.low[j], shapes_[i].low[j]);
            node.high[j] = std::max(node.high[j], shapes_[i].high[j]);
        }
    }
    auto index = nodes_.size();
    nodes_.push_back(node);
    if (end - begin > 6) {
        const auto sizes = sub(node.high, node.low);
        auto axis = std::max_element(sizes.begin(), sizes.end()) - sizes.begin();
        std::stable_sort(shapes_.begin() + begin, shapes_.begin() + end,
                         [axis](const auto &a, const auto &b) {
                             return a.low[axis] + a.high[axis] < b.low[axis] + b.high[axis];
                         });
        auto mid = begin + (end - begin) / 2;
        nodes_[index].left = build(begin, mid);
        nodes_[index].right = build(mid, end);
    }
    return index;
}

std::optional<Impact> CollisionWorld::trace(const Point &source, const Point &target, unsigned channel,
                                            bool terminal) const {
    if (!finite(source) || !finite(target))
        throw std::invalid_argument("Non-finite collision segment");
    if (source == target)
        return std::nullopt;
    Point start{}, delta{}, inverse{};
    for (int i = 0; i < 3; ++i) {
        start[i] = float(source[i]);
        delta[i] = float(target[i]) - float(source[i]);
        inverse[i] = target[i] == source[i] ? 0 : 1. / (target[i] - source[i]);
    }
    if (!finite(start) || !finite(delta))
        throw std::invalid_argument("Invalid collision segment");
    auto ray = segment(start, delta, channel);
    mesh_->intersect(std::span{&ray, 1});
    std::optional<Impact> best;
    auto triangle = [&](const RTCRayHit &hit, double distance) {
        const auto &h = hit.hit;
        std::optional<Point> n;
        if (channel == 8) {
            const double size = norm(h.Ng_x, h.Ng_y, h.Ng_z);
            n = size ? Point{h.Ng_x / size, -h.Ng_y / size, h.Ng_z / size} : Point{0, 0, 1};
        }
        best = Impact{distance, materials_.at(h.primID), n};
    };
    if (ray.hit.geomID != RTC_INVALID_GEOMETRY_ID)
        triangle(ray, ray.ray.tfar);
    if (terminal && channel == 8 && (!best || std::get<0>(*best) >= 1. - 1e-6)) {
        const float length = norm(float(delta[0]), float(delta[1]), float(delta[2]));
        if (length > 0) {
            Vertex direction{};
            Point half{}, step{};
            for (int i = 0; i < 3; ++i) {
                direction[i] = float(delta[i]) / length;
                half[i] = direction[i] * 0.002f;
                step[i] = 2 * half[i];
            }
            std::array<RTCRayHit, 27> probes;
            std::size_t i = 0;
            for (double x : {-0.002, 0., 0.002})
                for (double y : {-0.002, 0., 0.002})
                    for (double z : {-0.002, 0., 0.002})
                        probes[i++] = segment(along(sub(target, half), Point{x, y, z}, 1), step, channel);
            mesh_->intersect(probes);
            std::optional<std::tuple<bool, double, std::int64_t>> rank;
            for (const auto &probe : probes) {
                const auto &h = probe.hit;
                if (h.geomID == RTC_INVALID_GEOMETRY_ID)
                    continue;
                double size = norm(h.Ng_x, h.Ng_y, h.Ng_z);
                if (!size)
                    continue;
                double incidence =
                    -dot3f(h.Ng_x * direction[0], h.Ng_y * direction[1], h.Ng_z * direction[2]) / size;
                auto key = std::tuple{incidence >= 0, std::abs(incidence), -std::int64_t(h.primID)};
                if (!rank || key > *rank) {
                    rank = key;
                    triangle(probe, 1);
                }
            }
        }
    }
    auto visit = [&](auto &recurse, std::size_t index, double far) -> void {
        const auto &n = nodes_[index];
        if (!(n.mask & channel))
            return;
        double near = 0;
        for (int j = 0; j < 3; ++j) {
            if (source[j] == target[j]) {
                if (source[j] < n.low[j] || source[j] > n.high[j])
                    return;
            } else {
                auto a = (n.low[j] - source[j]) * inverse[j], b = (n.high[j] - source[j]) * inverse[j];
                if (a > b)
                    std::swap(a, b);
                near = std::max(near, a);
                far = std::min(far, b);
                if (near > far)
                    return;
            }
        }
        if (n.left) {
            recurse(recurse, n.left, far);
            recurse(recurse, n.right, far);
            return;
        }
        for (auto i = n.begin; i < n.end; ++i) {
            const auto &shape = shapes_[i];
            if (!(channel & shape.mask))
                continue;
            auto h = intersect(shape, start, delta);
            if (!h || (best && h->first >= std::get<0>(*best)))
                continue;
            std::optional<Point> normal;
            if (channel == 8) {
                const auto &p = h->second;
                double size = std::sqrt(dot(p, p));
                normal = size ? Point{p[0] / size, -p[1] / size, p[2] / size} : Point{0, 0, 1};
            }
            best = Impact{h->first, shape.material, normal};
        }
    };
    if (!nodes_.empty())
        visit(visit, 0, best ? std::get<0>(*best) : 1.);
    return best;
}

std::vector<bool> CollisionWorld::visible(const std::vector<std::pair<Point, Point>> &segments) const {
    std::vector<bool> result;
    result.reserve(segments.size());
    for (const auto &[a, b] : segments)
        result.push_back(!trace(std::min(a, b), std::max(a, b), 1));
    return result;
}
} // namespace esport
