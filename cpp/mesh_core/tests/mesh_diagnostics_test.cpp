#include "ywta/mesh_core/mesh_diagnostics.h"

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

MeshDiagnosticResult run(std::uint32_t vertex_count, const std::vector<Point3d>& points,
                         const std::vector<std::vector<std::uint32_t>>& faces) {
  std::vector<std::uint64_t> offsets{0};
  std::vector<std::uint32_t> corners;
  for (const auto& face : faces) {
    corners.insert(corners.end(), face.begin(), face.end());
    offsets.push_back(corners.size());
  }
  return diagnose_mesh({vertex_count, offsets.data(), faces.size(), corners.data(), corners.size()},
                       {points.data(), points.size()});
}

void test_clean_quad_reports_one_boundary_loop() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {1, 1, 0}, {0, 1, 0}};
  const auto result = run(4, points, {{0, 1, 2, 3}});
  expect(result.ok(), "valid quad should diagnose");
  expect(result.report.boundary_loop_offsets == std::vector<std::uint64_t>({0, 4}),
         "quad should expose one four-vertex boundary loop");
  expect(result.report.boundary_loop_vertices == std::vector<std::uint32_t>({0, 1, 2, 3}),
         "boundary loop should be deterministic");
}

void test_all_issue_classes_are_reported() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {2, 0, 0}, {0, 1, 0},
                                    {1, 1, 0}, {2, 1, 0}, {0, -1, 0}};
  const auto result = run(7, points,
                          {{0, 1, 2}, {2, 1, 0}, {0, 1, 4}, {0, 1, 5}, {0, 3, 4},
                           {0, 6, 5}});
  expect(result.ok(), "issue fixture should diagnose without mutation");
  expect(result.report.zero_area_faces == std::vector<std::uint64_t>({0, 1}),
         "collinear faces should be zero-area");
  expect(result.report.duplicate_faces == std::vector<std::uint64_t>({0, 1}),
         "same vertex set should be duplicate faces");
  expect(result.report.non_manifold_edges.size() >= 2 && result.report.non_manifold_edges[0] == 0 &&
             result.report.non_manifold_edges[1] == 1,
         "edge shared by four faces should be non-manifold");
}

void test_bow_tie_vertex_is_reported() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0},
                                    {-1, 0, 0}, {0, -1, 0}};
  const auto result = run(5, points, {{0, 1, 2}, {0, 3, 4}});
  expect(result.ok() && result.report.bow_tie_vertices == std::vector<std::uint32_t>({0}),
         "disconnected face fans should report their shared bow-tie vertex");
}

void test_duplicate_face_ids_are_unique_and_sorted() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}};
  const auto result = run(3, points, {{0, 1, 2}, {2, 1, 0}, {1, 0, 2}});
  expect(result.report.duplicate_faces == std::vector<std::uint64_t>({0, 1, 2}),
         "three duplicate faces should each appear once in sorted order");
}

void test_winding_conflict_is_separate_from_non_manifold() {
  const std::vector<Point3d> points{{0, 0, 0}, {1, 0, 0}, {0, 1, 0}, {1, 1, 0}};
  const auto result = run(4, points, {{0, 1, 2}, {0, 1, 3}});
  expect(result.ok(), "winding fixture should diagnose");
  expect(result.report.winding_conflict_edges == std::vector<std::uint32_t>({0, 1}),
         "same directed shared edge should be a winding conflict");
  expect(result.report.non_manifold_edges.empty(), "two-face winding conflict is not non-manifold");
}

void test_invalid_positions_fail_without_partial_report() {
  const std::uint64_t offsets[]{0, 3};
  const std::uint32_t corners[]{0, 1, 2};
  const auto result = diagnose_mesh({3, offsets, 1, corners, 3}, {}, 1.0e-12);
  expect(result.status == MeshDiagnosticStatus::kNullPositions &&
             result.report.zero_area_faces.empty(),
         "missing positions should fail without a partial report");
}

}  // namespace

int main() {
  test_clean_quad_reports_one_boundary_loop();
  test_all_issue_classes_are_reported();
  test_bow_tie_vertex_is_reported();
  test_duplicate_face_ids_are_unique_and_sorted();
  test_winding_conflict_is_separate_from_non_manifold();
  test_invalid_positions_fail_without_partial_report();
  if (failures != 0) {
    return EXIT_FAILURE;
  }
  std::cout << "All mesh diagnostic tests passed\n";
  return EXIT_SUCCESS;
}
