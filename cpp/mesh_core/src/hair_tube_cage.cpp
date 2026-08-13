#include "ywta/mesh_core/hair_tube_cage.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <sstream>
#include <utility>
#include <vector>

namespace ywta::mesh_core {
namespace {

constexpr std::size_t kRailCount = 4;
constexpr std::size_t kFitSamplesPerInterval = 16;
constexpr double kLengthEpsilon = 1.0e-12;
constexpr double kAreaEpsilon = 1.0e-12;
constexpr double kIntersectionEpsilon = 1.0e-10;

Point3d add(const Point3d& left, const Point3d& right) {
  return {left.x + right.x, left.y + right.y, left.z + right.z};
}

Point3d subtract(const Point3d& left, const Point3d& right) {
  return {left.x - right.x, left.y - right.y, left.z - right.z};
}

Point3d multiply(const Point3d& point, double scalar) {
  return {point.x * scalar, point.y * scalar, point.z * scalar};
}

double dot(const Point3d& left, const Point3d& right) {
  return left.x * right.x + left.y * right.y + left.z * right.z;
}

Point3d cross(const Point3d& left, const Point3d& right) {
  return {
      left.y * right.z - left.z * right.y,
      left.z * right.x - left.x * right.z,
      left.x * right.y - left.y * right.x,
  };
}

double squared_length(const Point3d& point) { return dot(point, point); }

double distance(const Point3d& first, const Point3d& second) {
  return std::sqrt(squared_length(subtract(first, second)));
}

bool finite(const Point3d& point) {
  return std::isfinite(point.x) && std::isfinite(point.y) && std::isfinite(point.z);
}

bool finite(const CubicSegment3d& segment) {
  return std::isfinite(segment.t0) && std::isfinite(segment.t1) && finite(segment.a) &&
         finite(segment.b) && finite(segment.c) && finite(segment.d);
}

Point3d lerp(const Point3d& first, const Point3d& second, double alpha) {
  return add(multiply(first, 1.0 - alpha), multiply(second, alpha));
}

HairTubeCageResult cage_error(HairTubeCageStatus status, std::string message) {
  HairTubeCageResult result;
  result.status = status;
  result.message = std::move(message);
  return result;
}

HairTubeCageSampleResult sample_error(HairTubeCageStatus status, std::string message) {
  HairTubeCageSampleResult result;
  result.status = status;
  result.message = std::move(message);
  return result;
}

HairTubeGeneratedMeshResult mesh_error(HairTubeCageStatus status, std::string message) {
  HairTubeGeneratedMeshResult result;
  result.status = status;
  result.message = std::move(message);
  return result;
}

std::size_t source_index(const HairTubeCurveCage& cage, std::size_t rail, std::uint64_t station) {
  return rail * static_cast<std::size_t>(cage.source_station_count) +
         static_cast<std::size_t>(station);
}

std::size_t cubic_index(const HairTubeCurveCage& cage, std::size_t rail, std::uint64_t interval) {
  return rail * static_cast<std::size_t>(cage.source_station_count - 1) +
         static_cast<std::size_t>(interval);
}

HairTubeSourceSample locate_source_interval(const HairTubeCurveCage& cage, double t) {
  if (t <= 0.0) {
    return {0, 0.0};
  }
  if (t >= 1.0) {
    return {cage.source_station_count - 2, 1.0};
  }
  const auto upper = std::upper_bound(cage.shared_t.begin(), cage.shared_t.end(), t);
  const std::uint64_t interval =
      static_cast<std::uint64_t>(std::distance(cage.shared_t.begin(), upper) - 1);
  const double begin = cage.shared_t[static_cast<std::size_t>(interval)];
  const double end = cage.shared_t[static_cast<std::size_t>(interval + 1)];
  return {interval, (t - begin) / (end - begin)};
}

Point3d evaluate_polyline(const HairTubeCurveCage& cage, std::size_t rail,
                          const HairTubeSourceSample& source) {
  const Point3d& first = cage.source_points[source_index(cage, rail, source.interval)];
  const Point3d& second = cage.source_points[source_index(cage, rail, source.interval + 1)];
  return lerp(first, second, source.alpha);
}

Point3d evaluate_cubic(const HairTubeCurveCage& cage, std::size_t rail,
                       const HairTubeSourceSample& source, double t) {
  const CubicSegment3d& segment = cage.cubic_segments[cubic_index(cage, rail, source.interval)];
  const double x = t - segment.t0;
  return add(segment.a, add(multiply(segment.b, x),
                            add(multiply(segment.c, x * x), multiply(segment.d, x * x * x))));
}

std::vector<double> natural_second_derivatives(const std::vector<double>& t,
                                               const std::vector<double>& values) {
  const std::size_t count = t.size();
  std::vector<double> second(count, 0.0);
  if (count <= 2) {
    return second;
  }

  const std::size_t interior_count = count - 2;
  std::vector<double> lower(interior_count, 0.0);
  std::vector<double> diagonal(interior_count, 0.0);
  std::vector<double> upper(interior_count, 0.0);
  std::vector<double> right(interior_count, 0.0);
  for (std::size_t interior = 0; interior < interior_count; ++interior) {
    const std::size_t station = interior + 1;
    const double previous_h = t[station] - t[station - 1];
    const double next_h = t[station + 1] - t[station];
    lower[interior] = previous_h;
    diagonal[interior] = 2.0 * (previous_h + next_h);
    upper[interior] = next_h;
    right[interior] = 6.0 * ((values[station + 1] - values[station]) / next_h -
                             (values[station] - values[station - 1]) / previous_h);
  }
  lower.front() = 0.0;
  upper.back() = 0.0;

  for (std::size_t index = 1; index < interior_count; ++index) {
    const double factor = lower[index] / diagonal[index - 1];
    diagonal[index] -= factor * upper[index - 1];
    right[index] -= factor * right[index - 1];
  }
  std::vector<double> solution(interior_count, 0.0);
  solution.back() = right.back() / diagonal.back();
  for (std::size_t index = interior_count - 1; index > 0; --index) {
    solution[index - 1] =
        (right[index - 1] - upper[index - 1] * solution[index]) / diagonal[index - 1];
  }
  for (std::size_t interior = 0; interior < interior_count; ++interior) {
    second[interior + 1] = solution[interior];
  }
  return second;
}

std::vector<CubicSegment3d> fit_rail(const std::vector<double>& t,
                                     const std::vector<Point3d>& points) {
  std::vector<double> x_values;
  std::vector<double> y_values;
  std::vector<double> z_values;
  x_values.reserve(points.size());
  y_values.reserve(points.size());
  z_values.reserve(points.size());
  for (const Point3d& point : points) {
    x_values.push_back(point.x);
    y_values.push_back(point.y);
    z_values.push_back(point.z);
  }
  const std::vector<double> second_x = natural_second_derivatives(t, x_values);
  const std::vector<double> second_y = natural_second_derivatives(t, y_values);
  const std::vector<double> second_z = natural_second_derivatives(t, z_values);

  std::vector<CubicSegment3d> segments;
  segments.reserve(points.size() - 1);
  for (std::size_t interval = 0; interval + 1 < points.size(); ++interval) {
    const double h = t[interval + 1] - t[interval];
    const Point3d second_first{second_x[interval], second_y[interval], second_z[interval]};
    const Point3d second_next{second_x[interval + 1], second_y[interval + 1],
                              second_z[interval + 1]};
    CubicSegment3d segment;
    segment.t0 = t[interval];
    segment.t1 = t[interval + 1];
    segment.a = points[interval];
    segment.b = subtract(multiply(subtract(points[interval + 1], points[interval]), 1.0 / h),
                         multiply(add(multiply(second_first, 2.0), second_next), h / 6.0));
    segment.c = multiply(second_first, 0.5);
    segment.d = multiply(subtract(second_next, second_first), 1.0 / (6.0 * h));
    segments.push_back(segment);
  }
  return segments;
}

double point_segment_distance(const Point3d& point, const Point3d& first, const Point3d& second) {
  const Point3d segment = subtract(second, first);
  const double length_squared = squared_length(segment);
  if (length_squared <= kLengthEpsilon * kLengthEpsilon) {
    return distance(point, first);
  }
  const double alpha = std::clamp(dot(subtract(point, first), segment) / length_squared, 0.0, 1.0);
  return distance(point, add(first, multiply(segment, alpha)));
}

double rail_polyline_distance(const HairTubeCurveCage& cage, std::size_t rail,
                              const Point3d& point) {
  double minimum = std::numeric_limits<double>::infinity();
  for (std::uint64_t interval = 0; interval + 1 < cage.source_station_count; ++interval) {
    minimum = std::min(minimum, point_segment_distance(
                                    point, cage.source_points[source_index(cage, rail, interval)],
                                    cage.source_points[source_index(cage, rail, interval + 1)]));
  }
  return minimum;
}

enum class QuadQuality {
  kValid,
  kZeroArea,
  kInverted,
};

struct Point2d {
  double x = 0.0;
  double y = 0.0;
};

struct Bounds3d {
  Point3d minimum;
  Point3d maximum;
};

QuadQuality inspect_quad(const std::array<Point3d, 4>& quad) {
  const Point3d diagonal = subtract(quad[2], quad[0]);
  const Point3d first_cross = cross(subtract(quad[1], quad[0]), diagonal);
  const Point3d second_cross = cross(diagonal, subtract(quad[3], quad[0]));
  const double first_area = std::sqrt(squared_length(first_cross));
  const double second_area = std::sqrt(squared_length(second_cross));
  double max_edge_squared = 0.0;
  for (std::size_t edge = 0; edge < quad.size(); ++edge) {
    max_edge_squared =
        std::max(max_edge_squared, squared_length(subtract(quad[(edge + 1) % 4], quad[edge])));
  }
  if (!std::isfinite(first_area) || !std::isfinite(second_area) || max_edge_squared <= 0.0 ||
      first_area <= kAreaEpsilon * max_edge_squared ||
      second_area <= kAreaEpsilon * max_edge_squared) {
    return QuadQuality::kZeroArea;
  }
  if (dot(first_cross, second_cross) <= 0.0) {
    return QuadQuality::kInverted;
  }
  return QuadQuality::kValid;
}

Bounds3d triangle_bounds(const std::array<Point3d, 3>& triangle) {
  Bounds3d bounds{triangle[0], triangle[0]};
  for (std::size_t vertex = 1; vertex < triangle.size(); ++vertex) {
    bounds.minimum.x = std::min(bounds.minimum.x, triangle[vertex].x);
    bounds.minimum.y = std::min(bounds.minimum.y, triangle[vertex].y);
    bounds.minimum.z = std::min(bounds.minimum.z, triangle[vertex].z);
    bounds.maximum.x = std::max(bounds.maximum.x, triangle[vertex].x);
    bounds.maximum.y = std::max(bounds.maximum.y, triangle[vertex].y);
    bounds.maximum.z = std::max(bounds.maximum.z, triangle[vertex].z);
  }
  return bounds;
}

bool bounds_overlap(const Bounds3d& first, const Bounds3d& second) {
  return first.minimum.x <= second.maximum.x + kIntersectionEpsilon &&
         second.minimum.x <= first.maximum.x + kIntersectionEpsilon &&
         first.minimum.y <= second.maximum.y + kIntersectionEpsilon &&
         second.minimum.y <= first.maximum.y + kIntersectionEpsilon &&
         first.minimum.z <= second.maximum.z + kIntersectionEpsilon &&
         second.minimum.z <= first.maximum.z + kIntersectionEpsilon;
}

Point2d project(const Point3d& point, std::size_t dropped_axis) {
  if (dropped_axis == 0) {
    return {point.y, point.z};
  }
  if (dropped_axis == 1) {
    return {point.x, point.z};
  }
  return {point.x, point.y};
}

double orient2d(const Point2d& first, const Point2d& second, const Point2d& third) {
  return (second.x - first.x) * (third.y - first.y) - (second.y - first.y) * (third.x - first.x);
}

bool on_segment(const Point2d& first, const Point2d& second, const Point2d& point) {
  return std::abs(orient2d(first, second, point)) <= kIntersectionEpsilon &&
         point.x >= std::min(first.x, second.x) - kIntersectionEpsilon &&
         point.x <= std::max(first.x, second.x) + kIntersectionEpsilon &&
         point.y >= std::min(first.y, second.y) - kIntersectionEpsilon &&
         point.y <= std::max(first.y, second.y) + kIntersectionEpsilon;
}

bool segments_intersect_2d(const Point2d& first_a, const Point2d& first_b, const Point2d& second_a,
                           const Point2d& second_b) {
  const double first_side_a = orient2d(first_a, first_b, second_a);
  const double first_side_b = orient2d(first_a, first_b, second_b);
  const double second_side_a = orient2d(second_a, second_b, first_a);
  const double second_side_b = orient2d(second_a, second_b, first_b);
  if (((first_side_a > kIntersectionEpsilon && first_side_b < -kIntersectionEpsilon) ||
       (first_side_a < -kIntersectionEpsilon && first_side_b > kIntersectionEpsilon)) &&
      ((second_side_a > kIntersectionEpsilon && second_side_b < -kIntersectionEpsilon) ||
       (second_side_a < -kIntersectionEpsilon && second_side_b > kIntersectionEpsilon))) {
    return true;
  }
  return on_segment(first_a, first_b, second_a) || on_segment(first_a, first_b, second_b) ||
         on_segment(second_a, second_b, first_a) || on_segment(second_a, second_b, first_b);
}

bool point_in_triangle_2d(const Point2d& point, const std::array<Point2d, 3>& triangle) {
  const double first = orient2d(triangle[0], triangle[1], point);
  const double second = orient2d(triangle[1], triangle[2], point);
  const double third = orient2d(triangle[2], triangle[0], point);
  const bool has_negative = first < -kIntersectionEpsilon || second < -kIntersectionEpsilon ||
                            third < -kIntersectionEpsilon;
  const bool has_positive =
      first > kIntersectionEpsilon || second > kIntersectionEpsilon || third > kIntersectionEpsilon;
  return !(has_negative && has_positive);
}

bool coplanar_triangles_intersect(const std::array<Point3d, 3>& first,
                                  const std::array<Point3d, 3>& second, const Point3d& normal) {
  const std::array<double, 3> magnitude{std::abs(normal.x), std::abs(normal.y), std::abs(normal.z)};
  const std::size_t dropped_axis = static_cast<std::size_t>(
      std::distance(magnitude.begin(), std::max_element(magnitude.begin(), magnitude.end())));
  std::array<Point2d, 3> first_2d{};
  std::array<Point2d, 3> second_2d{};
  for (std::size_t vertex = 0; vertex < 3; ++vertex) {
    first_2d[vertex] = project(first[vertex], dropped_axis);
    second_2d[vertex] = project(second[vertex], dropped_axis);
  }
  for (std::size_t first_edge = 0; first_edge < 3; ++first_edge) {
    for (std::size_t second_edge = 0; second_edge < 3; ++second_edge) {
      if (segments_intersect_2d(first_2d[first_edge], first_2d[(first_edge + 1) % 3],
                                second_2d[second_edge], second_2d[(second_edge + 1) % 3])) {
        return true;
      }
    }
  }
  return point_in_triangle_2d(first_2d[0], second_2d) ||
         point_in_triangle_2d(second_2d[0], first_2d);
}

bool segment_intersects_triangle(const Point3d& start, const Point3d& end,
                                 const std::array<Point3d, 3>& triangle) {
  const Point3d direction = subtract(end, start);
  const Point3d edge_first = subtract(triangle[1], triangle[0]);
  const Point3d edge_second = subtract(triangle[2], triangle[0]);
  const Point3d cross_direction = cross(direction, edge_second);
  const double determinant = dot(edge_first, cross_direction);
  if (std::abs(determinant) <= kIntersectionEpsilon) {
    return false;
  }
  const double inverse = 1.0 / determinant;
  const Point3d origin_delta = subtract(start, triangle[0]);
  const double first_barycentric = inverse * dot(origin_delta, cross_direction);
  if (first_barycentric < -kIntersectionEpsilon || first_barycentric > 1.0 + kIntersectionEpsilon) {
    return false;
  }
  const Point3d barycentric_cross = cross(origin_delta, edge_first);
  const double second_barycentric = inverse * dot(direction, barycentric_cross);
  if (second_barycentric < -kIntersectionEpsilon ||
      first_barycentric + second_barycentric > 1.0 + kIntersectionEpsilon) {
    return false;
  }
  const double segment_parameter = inverse * dot(edge_second, barycentric_cross);
  return segment_parameter >= -kIntersectionEpsilon &&
         segment_parameter <= 1.0 + kIntersectionEpsilon;
}

bool triangles_intersect(const std::array<Point3d, 3>& first_input,
                         const std::array<Point3d, 3>& second_input) {
  Point3d minimum = first_input[0];
  Point3d maximum = first_input[0];
  for (const auto& triangle : {first_input, second_input}) {
    for (const Point3d& point : triangle) {
      minimum.x = std::min(minimum.x, point.x);
      minimum.y = std::min(minimum.y, point.y);
      minimum.z = std::min(minimum.z, point.z);
      maximum.x = std::max(maximum.x, point.x);
      maximum.y = std::max(maximum.y, point.y);
      maximum.z = std::max(maximum.z, point.z);
    }
  }
  const double coordinate_scale =
      std::max({maximum.x - minimum.x, maximum.y - minimum.y, maximum.z - minimum.z});
  if (!std::isfinite(coordinate_scale) || coordinate_scale <= kLengthEpsilon) {
    return false;
  }
  std::array<Point3d, 3> first{};
  std::array<Point3d, 3> second{};
  for (std::size_t vertex = 0; vertex < 3; ++vertex) {
    first[vertex] = multiply(subtract(first_input[vertex], minimum), 1.0 / coordinate_scale);
    second[vertex] = multiply(subtract(second_input[vertex], minimum), 1.0 / coordinate_scale);
  }
  if (!bounds_overlap(triangle_bounds(first), triangle_bounds(second))) {
    return false;
  }
  const Point3d first_normal = cross(subtract(first[1], first[0]), subtract(first[2], first[0]));
  const Point3d second_normal =
      cross(subtract(second[1], second[0]), subtract(second[2], second[0]));
  const Point3d normal_cross = cross(first_normal, second_normal);
  const double normal_product = squared_length(first_normal) * squared_length(second_normal);
  const double scale = std::max({1.0, std::sqrt(squared_length(subtract(first[1], first[0]))),
                                 std::sqrt(squared_length(subtract(first[2], first[0])))});
  const bool parallel =
      squared_length(normal_cross) <= kIntersectionEpsilon * kIntersectionEpsilon * normal_product;
  const bool coplanar =
      parallel && std::abs(dot(first_normal, subtract(second[0], first[0]))) <=
                      kIntersectionEpsilon * std::sqrt(squared_length(first_normal)) * scale;
  if (coplanar) {
    return coplanar_triangles_intersect(first, second, first_normal);
  }
  for (std::size_t edge = 0; edge < 3; ++edge) {
    if (segment_intersects_triangle(first[edge], first[(edge + 1) % 3], second) ||
        segment_intersects_triangle(second[edge], second[(edge + 1) % 3], first)) {
      return true;
    }
  }
  return false;
}

bool quads_share_vertex(const std::array<std::uint32_t, 4>& first,
                        const std::array<std::uint32_t, 4>& second) {
  for (const std::uint32_t first_vertex : first) {
    if (std::find(second.begin(), second.end(), first_vertex) != second.end()) {
      return true;
    }
  }
  return false;
}

bool quads_intersect(const std::vector<Point3d>& positions,
                     const std::array<std::uint32_t, 4>& first,
                     const std::array<std::uint32_t, 4>& second) {
  const std::array<std::array<std::uint32_t, 3>, 2> first_triangles{
      std::array<std::uint32_t, 3>{first[0], first[1], first[2]},
      std::array<std::uint32_t, 3>{first[0], first[2], first[3]},
  };
  const std::array<std::array<std::uint32_t, 3>, 2> second_triangles{
      std::array<std::uint32_t, 3>{second[0], second[1], second[2]},
      std::array<std::uint32_t, 3>{second[0], second[2], second[3]},
  };
  for (const auto& first_triangle_indices : first_triangles) {
    const std::array<Point3d, 3> first_triangle{
        positions[first_triangle_indices[0]],
        positions[first_triangle_indices[1]],
        positions[first_triangle_indices[2]],
    };
    for (const auto& second_triangle_indices : second_triangles) {
      const std::array<Point3d, 3> second_triangle{
          positions[second_triangle_indices[0]],
          positions[second_triangle_indices[1]],
          positions[second_triangle_indices[2]],
      };
      if (triangles_intersect(first_triangle, second_triangle)) {
        return true;
      }
    }
  }
  return false;
}

}  // namespace

HairTubeCageResult build_hair_tube_curve_cage(const HairTubeTopology& topology,
                                              const Point3dView& positions, double fit_tolerance) {
  if (topology.station_count < 2 ||
      topology.station_count > std::numeric_limits<std::size_t>::max() / kRailCount) {
    return cage_error(HairTubeCageStatus::kInvalidTopologyLayout,
                      "topology must contain at least two four-vertex stations");
  }
  const std::size_t station_count = static_cast<std::size_t>(topology.station_count);
  const std::size_t expected_points = station_count * kRailCount;
  if (topology.rings.size() != expected_points || topology.rails.size() != expected_points ||
      topology.side_faces.size() != (station_count - 1) * kRailCount) {
    return cage_error(HairTubeCageStatus::kInvalidTopologyLayout,
                      "topology arrays do not match station_count");
  }
  for (std::size_t rail = 0; rail < kRailCount; ++rail) {
    for (std::size_t station = 0; station < station_count; ++station) {
      if (topology.rails[rail * station_count + station] !=
          topology.rings[station * kRailCount + rail]) {
        return cage_error(HairTubeCageStatus::kInvalidTopologyLayout,
                          "rail and ring layouts disagree");
      }
    }
  }
  if (positions.points == nullptr) {
    return cage_error(HairTubeCageStatus::kNullPositions, "positions is null");
  }
  if (!std::isfinite(fit_tolerance) || fit_tolerance < 0.0) {
    return cage_error(HairTubeCageStatus::kInvalidFitTolerance,
                      "fit_tolerance must be finite and non-negative");
  }

  HairTubeCurveCage cage;
  cage.source_station_count = topology.station_count;
  cage.fit_tolerance = fit_tolerance;
  cage.source_points.reserve(expected_points);
  for (std::size_t rail = 0; rail < kRailCount; ++rail) {
    for (std::size_t station = 0; station < station_count; ++station) {
      const std::uint32_t source_vertex = topology.rails[rail * station_count + station];
      if (source_vertex >= positions.count) {
        return cage_error(HairTubeCageStatus::kPositionIndexOutOfRange,
                          "topology references a position outside the input buffer");
      }
      const Point3d point = positions.points[source_vertex];
      if (!finite(point)) {
        return cage_error(HairTubeCageStatus::kNonFinitePosition,
                          "source position contains a non-finite component");
      }
      cage.source_points.push_back(point);
    }
  }

  cage.shared_t.assign(station_count, 0.0);
  for (std::size_t station = 0; station + 1 < station_count; ++station) {
    double average_length = 0.0;
    for (std::size_t rail = 0; rail < kRailCount; ++rail) {
      average_length += distance(cage.source_points[rail * station_count + station],
                                 cage.source_points[rail * station_count + station + 1]);
    }
    average_length /= static_cast<double>(kRailCount);
    if (!std::isfinite(average_length) || average_length <= kLengthEpsilon) {
      return cage_error(HairTubeCageStatus::kZeroLengthStationInterval,
                        "a shared station interval has zero average chord length");
    }
    cage.shared_t[station + 1] = cage.shared_t[station] + average_length;
  }
  const double total_length = cage.shared_t.back();
  if (!std::isfinite(total_length) || total_length <= kLengthEpsilon) {
    return cage_error(HairTubeCageStatus::kZeroLengthStationInterval,
                      "the shared station range is not finite and positive");
  }
  for (double& value : cage.shared_t) {
    value /= total_length;
  }
  cage.shared_t.front() = 0.0;
  cage.shared_t.back() = 1.0;

  cage.cubic_segments.reserve((station_count - 1) * kRailCount);
  for (std::size_t rail = 0; rail < kRailCount; ++rail) {
    const auto begin =
        cage.source_points.begin() + static_cast<std::ptrdiff_t>(rail * station_count);
    const std::vector<Point3d> rail_points(begin,
                                           begin + static_cast<std::ptrdiff_t>(station_count));
    std::vector<CubicSegment3d> rail_segments = fit_rail(cage.shared_t, rail_points);
    if (std::any_of(rail_segments.begin(), rail_segments.end(),
                    [](const CubicSegment3d& segment) { return !finite(segment); })) {
      return cage_error(HairTubeCageStatus::kNonFiniteEvaluation,
                        "cubic fitting produced a non-finite coefficient");
    }
    cage.cubic_segments.insert(cage.cubic_segments.end(), rail_segments.begin(),
                               rail_segments.end());
  }

  cage.max_fit_deviation = 0.0;
  for (std::uint64_t interval = 0; interval + 1 < cage.source_station_count; ++interval) {
    const double t0 = cage.shared_t[static_cast<std::size_t>(interval)];
    const double t1 = cage.shared_t[static_cast<std::size_t>(interval + 1)];
    for (std::size_t sample = 1; sample < kFitSamplesPerInterval; ++sample) {
      const double alpha =
          static_cast<double>(sample) / static_cast<double>(kFitSamplesPerInterval);
      const double t = t0 + (t1 - t0) * alpha;
      const HairTubeSourceSample source{interval, alpha};
      for (std::size_t rail = 0; rail < kRailCount; ++rail) {
        const double deviation =
            distance(evaluate_cubic(cage, rail, source, t), evaluate_polyline(cage, rail, source));
        if (!std::isfinite(deviation)) {
          return cage_error(HairTubeCageStatus::kNonFiniteEvaluation,
                            "cubic fitting produced a non-finite deviation");
        }
        cage.max_fit_deviation = std::max(cage.max_fit_deviation, deviation);
      }
    }
  }
  cage.cubic_active = fit_tolerance > 0.0 && cage.max_fit_deviation <= fit_tolerance;

  HairTubeCageResult result;
  result.cage = std::move(cage);
  return result;
}

HairTubeCageSampleResult evaluate_hair_tube_curve_cage(const HairTubeCurveCage& cage, double t) {
  if (cage.source_station_count < 2 || cage.shared_t.size() != cage.source_station_count ||
      cage.source_points.size() != cage.source_station_count * kRailCount ||
      cage.cubic_segments.size() != (cage.source_station_count - 1) * kRailCount) {
    return sample_error(HairTubeCageStatus::kInvalidTopologyLayout,
                        "cage arrays do not match source_station_count");
  }
  if (!std::isfinite(cage.shared_t.front()) || !std::isfinite(cage.shared_t.back()) ||
      cage.shared_t.front() != 0.0 || cage.shared_t.back() != 1.0 ||
      std::adjacent_find(cage.shared_t.begin(), cage.shared_t.end(),
                         [](double first, double second) {
                           return !std::isfinite(second) || second <= first;
                         }) != cage.shared_t.end()) {
    return sample_error(HairTubeCageStatus::kInvalidTopologyLayout,
                        "cage parameters must be finite and strictly increasing from zero to one");
  }
  if (!std::isfinite(t) || t < 0.0 || t > 1.0) {
    return sample_error(HairTubeCageStatus::kParameterOutOfRange,
                        "evaluation parameter must be within zero and one");
  }

  HairTubeCageSample sample;
  sample.source = locate_source_interval(cage, t);
  for (std::size_t rail = 0; rail < kRailCount; ++rail) {
    if (t == 0.0) {
      sample.points[rail] = cage.source_points[source_index(cage, rail, 0)];
    } else if (t == 1.0) {
      sample.points[rail] =
          cage.source_points[source_index(cage, rail, cage.source_station_count - 1)];
    } else if (cage.cubic_active) {
      sample.points[rail] = evaluate_cubic(cage, rail, sample.source, t);
    } else {
      sample.points[rail] = evaluate_polyline(cage, rail, sample.source);
    }
    if (!finite(sample.points[rail])) {
      return sample_error(HairTubeCageStatus::kNonFiniteEvaluation,
                          "cage evaluation produced a non-finite point");
    }
  }

  HairTubeCageSampleResult result;
  result.sample = sample;
  return result;
}

HairTubeGeneratedMeshResult regenerate_hair_tube_fixed_density(const HairTubeCurveCage& cage,
                                                               std::uint64_t target_segments) {
  if (target_segments == 0) {
    return mesh_error(HairTubeCageStatus::kTargetSegmentsZero,
                      "target_segments must be at least one");
  }
  constexpr std::uint64_t kMaxStation =
      static_cast<std::uint64_t>(std::numeric_limits<std::uint32_t>::max()) / kRailCount;
  if (target_segments >= kMaxStation ||
      target_segments > std::numeric_limits<std::size_t>::max() / kRailCount - 1) {
    return mesh_error(HairTubeCageStatus::kOutputOverflow,
                      "generated mesh exceeds index or container limits");
  }

  HairTubeGeneratedMesh generated;
  const std::size_t output_station_count = static_cast<std::size_t>(target_segments + 1);
  generated.positions.reserve(output_station_count * kRailCount);
  generated.source_mapping.reserve(output_station_count * kRailCount);
  generated.quad_indices.reserve(static_cast<std::size_t>(target_segments) * kRailCount * 4);
  for (std::uint64_t station = 0; station <= target_segments; ++station) {
    const double t = static_cast<double>(station) / static_cast<double>(target_segments);
    const HairTubeCageSampleResult sampled = evaluate_hair_tube_curve_cage(cage, t);
    if (!sampled.ok()) {
      return mesh_error(sampled.status, sampled.message);
    }
    for (std::size_t rail = 0; rail < kRailCount; ++rail) {
      generated.positions.push_back(sampled.sample.points[rail]);
      generated.source_mapping.push_back(sampled.sample.source);
      generated.max_source_distance =
          std::max(generated.max_source_distance,
                   rail_polyline_distance(cage, rail, sampled.sample.points[rail]));
    }
  }

  for (std::uint64_t station = 0; station < target_segments; ++station) {
    const std::uint32_t first_station = static_cast<std::uint32_t>(station * kRailCount);
    const std::uint32_t next_station = static_cast<std::uint32_t>((station + 1) * kRailCount);
    for (std::uint32_t rail = 0; rail < kRailCount; ++rail) {
      const std::uint32_t next_rail = (rail + 1) % kRailCount;
      const std::array<std::uint32_t, 4> indices{
          first_station + rail,
          first_station + next_rail,
          next_station + next_rail,
          next_station + rail,
      };
      const std::array<Point3d, 4> quad{
          generated.positions[indices[0]],
          generated.positions[indices[1]],
          generated.positions[indices[2]],
          generated.positions[indices[3]],
      };
      const QuadQuality quality = inspect_quad(quad);
      if (quality == QuadQuality::kZeroArea) {
        return mesh_error(HairTubeCageStatus::kZeroAreaQuad,
                          "generated mesh contains a zero-area quad");
      }
      if (quality == QuadQuality::kInverted) {
        return mesh_error(HairTubeCageStatus::kInvertedQuad,
                          "generated mesh contains an inverted or self-crossing quad");
      }
      generated.quad_indices.insert(generated.quad_indices.end(), indices.begin(), indices.end());
    }
  }

  const std::size_t quad_count = generated.quad_indices.size() / 4;
  for (std::size_t first_face = 0; first_face < quad_count; ++first_face) {
    const std::size_t first_offset = first_face * 4;
    const std::array<std::uint32_t, 4> first{
        generated.quad_indices[first_offset],
        generated.quad_indices[first_offset + 1],
        generated.quad_indices[first_offset + 2],
        generated.quad_indices[first_offset + 3],
    };
    for (std::size_t second_face = first_face + 1; second_face < quad_count; ++second_face) {
      const std::size_t second_offset = second_face * 4;
      const std::array<std::uint32_t, 4> second{
          generated.quad_indices[second_offset],
          generated.quad_indices[second_offset + 1],
          generated.quad_indices[second_offset + 2],
          generated.quad_indices[second_offset + 3],
      };
      if (!quads_share_vertex(first, second) &&
          quads_intersect(generated.positions, first, second)) {
        return mesh_error(HairTubeCageStatus::kSelfIntersection,
                          "generated mesh contains intersecting non-adjacent quads");
      }
    }
  }

  HairTubeGeneratedMeshResult result;
  result.mesh = std::move(generated);
  return result;
}

}  // namespace ywta::mesh_core
