#include "ywta/mesh_core/mesh_repair.h"

#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

using namespace ywta::mesh_core;
int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

MeshRepairResult run(const std::vector<Point3d>& points,
                     const std::vector<std::vector<std::uint32_t>>& faces) {
  std::vector<std::uint64_t> offsets{0};
  std::vector<std::uint32_t> corners;
  for (const auto& face : faces) {
    corners.insert(corners.end(), face.begin(), face.end());
    offsets.push_back(corners.size());
  }
  return plan_safe_mesh_repair(
      {static_cast<std::uint32_t>(points.size()), offsets.data(), faces.size(), corners.data(),
       corners.size()},
      {points.data(), points.size()});
}

void test_removes_zero_and_later_duplicate_with_mapping() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {2, 0, 0}};
  const auto result = run(points, {{0, 1, 3}, {0, 1, 2}, {2, 1, 0}});
  expect(result.ok(), "safe fixture should produce a plan");
  if (!result.ok()) {
    return;
  }
  expect(result.plan.removed_zero_area_faces == std::vector<std::uint64_t>({0}),
         "zero-area face should be removed");
  expect(result.plan.removed_duplicate_faces == std::vector<std::uint64_t>({2}),
         "later duplicate should be removed");
  expect(result.plan.old_face_to_new[0] == kRemovedFace && result.plan.old_face_to_new[1] == 0 &&
             result.plan.old_face_to_new[2] == kRemovedFace,
         "old-to-new face mapping should mark removals");
}

void test_flips_winding_and_tracks_source_corners() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {1, 1, 0}};
  const auto result = run(points, {{0, 1, 2}, {0, 1, 3}});
  expect(result.ok() && result.plan.flipped_source_faces == std::vector<std::uint64_t>({1}),
         "second face should flip deterministically");
  expect(result.plan.face_vertices == std::vector<std::uint32_t>({0, 1, 2, 0, 3, 1}),
         "flipped face should preserve corner zero and reverse the rest");
  expect(result.plan.source_corner_by_output ==
             std::vector<std::uint64_t>({0, 1, 2, 3, 5, 4}),
         "output corners should map to original corners");
}

void test_non_manifold_edge_is_refused_without_plan() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {0, -1, 0}, {1, 1, 0}};
  const auto result = run(points, {{0, 1, 2}, {1, 0, 3}, {0, 1, 4}});
  expect(result.status == MeshRepairStatus::kUnsafeNonManifoldEdge &&
             result.plan.face_offsets.empty(),
         "non-manifold edge should fail without a partial plan");
}

}  // namespace

int main() {
  test_removes_zero_and_later_duplicate_with_mapping();
  test_flips_winding_and_tracks_source_corners();
  test_non_manifold_edge_is_refused_without_plan();
  return failures == 0 ? EXIT_SUCCESS : EXIT_FAILURE;
}
