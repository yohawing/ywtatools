#include "ywta/mesh_core/hair_tube_topology.h"

#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

using ywta::mesh_core::extract_hair_tube_topology;
using ywta::mesh_core::HairTubeRootLoopView;
using ywta::mesh_core::HairTubeStatus;
using ywta::mesh_core::HairTubeTopologyResult;
using ywta::mesh_core::RawTopologyView;
using ywta::mesh_core::TopologyStatus;

int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

struct Fixture {
  std::uint32_t vertex_count = 0;
  std::vector<std::vector<std::uint32_t>> faces;
  std::vector<std::uint64_t> offsets;
  std::vector<std::uint32_t> vertices;

  void rebuild() {
    offsets.clear();
    vertices.clear();
    offsets.push_back(0);
    for (const auto& face : faces) {
      vertices.insert(vertices.end(), face.begin(), face.end());
      offsets.push_back(vertices.size());
    }
  }

  RawTopologyView view() {
    rebuild();
    return {vertex_count, offsets.data(), faces.size(), vertices.data(), vertices.size()};
  }
};

Fixture open_tube(std::uint32_t stations = 3) {
  Fixture fixture;
  fixture.vertex_count = stations * 4;
  for (std::uint32_t station = 0; station + 1 < stations; ++station) {
    for (std::uint32_t rail = 0; rail < 4; ++rail) {
      const std::uint32_t next_rail = (rail + 1) % 4;
      fixture.faces.push_back({station * 4 + rail, station * 4 + next_rail,
                               (station + 1) * 4 + next_rail, (station + 1) * 4 + rail});
    }
  }
  return fixture;
}

HairTubeTopologyResult run(Fixture& fixture, const std::vector<std::uint32_t>& root) {
  const RawTopologyView topology = fixture.view();
  return extract_hair_tube_topology(
      topology, HairTubeRootLoopView{root.data(), static_cast<std::uint64_t>(root.size())});
}

void expect_empty_failure(const HairTubeTopologyResult& result, HairTubeStatus status,
                          const std::string& context) {
  expect(result.status == status,
         context + ": expected status " + std::to_string(static_cast<int>(status)) + ", got " +
             std::to_string(static_cast<int>(result.status)) + " (" + result.message + ")");
  expect(result.topology.station_count == 0, context + ": station count should be empty");
  expect(result.topology.rings.empty(), context + ": rings should be empty");
  expect(result.topology.rails.empty(), context + ": rails should be empty");
  expect(result.topology.side_faces.empty(), context + ": side faces should be empty");
}

void test_valid_tube_has_deterministic_rings_and_rails() {
  Fixture fixture = open_tube();
  const HairTubeTopologyResult result = run(fixture, {0, 1, 2, 3});

  expect(result.ok(), "open tube should be accepted");
  expect(result.topology.station_count == 3, "open tube should have three stations");
  expect(
      result.topology.rings == std::vector<std::uint32_t>({0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11}),
      "rings should preserve station and cyclic order");
  expect(
      result.topology.rails == std::vector<std::uint32_t>({0, 4, 8, 1, 5, 9, 2, 6, 10, 3, 7, 11}),
      "rails should be derived from shared stations");
  expect(result.topology.side_faces == std::vector<std::uint64_t>({0, 1, 2, 3, 4, 5, 6, 7}),
         "side face ids should follow station and root edge order");
}

void test_face_order_does_not_change_rings_or_rails() {
  Fixture original = open_tube();
  const HairTubeTopologyResult expected = run(original, {0, 1, 2, 3});
  Fixture permuted = open_tube();
  std::reverse(permuted.faces.begin(), permuted.faces.end());
  const HairTubeTopologyResult result = run(permuted, {0, 1, 2, 3});

  expect(result.ok(), "permuted faces should be accepted");
  expect(result.topology.rings == expected.topology.rings,
         "face order should not change station ids");
  expect(result.topology.rails == expected.topology.rails, "face order should not change rail ids");
}

void test_reversed_root_reverses_cyclic_rail_order_consistently() {
  Fixture fixture = open_tube();
  const HairTubeTopologyResult result = run(fixture, {0, 3, 2, 1});

  expect(result.ok(), "reversed root should be accepted");
  expect(
      result.topology.rings == std::vector<std::uint32_t>({0, 3, 2, 1, 4, 7, 6, 5, 8, 11, 10, 9}),
      "reversed root should remain the cyclic authority");
  expect(
      result.topology.rails == std::vector<std::uint32_t>({0, 4, 8, 3, 7, 11, 2, 6, 10, 1, 5, 9}),
      "reversed rails should use the same shared stations");
}

void test_invalid_roots_are_rejected() {
  Fixture fixture = open_tube();
  expect_empty_failure(run(fixture, {0, 1, 2}), HairTubeStatus::kRootLoopCountNotFour,
                       "short root");
  expect_empty_failure(run(fixture, {0, 1, 1, 3}), HairTubeStatus::kRepeatedRootVertex,
                       "repeated root");
  expect_empty_failure(run(fixture, {0, 1, 2, 99}), HairTubeStatus::kRootVertexOutOfRange,
                       "out-of-range root");
  expect_empty_failure(run(fixture, {0, 1, 2, 8}), HairTubeStatus::kRootEdgeMissing,
                       "missing root edge");

  const RawTopologyView topology = fixture.view();
  expect_empty_failure(extract_hair_tube_topology(topology, HairTubeRootLoopView{nullptr, 4}),
                       HairTubeStatus::kNullRootVertices, "null root buffer");
}

void test_non_quad_and_capped_root_are_rejected() {
  Fixture triangle = open_tube();
  triangle.faces[0].pop_back();
  expect_empty_failure(run(triangle, {0, 1, 2, 3}), HairTubeStatus::kNonQuadFace, "triangle input");

  Fixture capped = open_tube();
  capped.faces.push_back({0, 3, 2, 1});
  expect_empty_failure(run(capped, {0, 1, 2, 3}), HairTubeStatus::kRootNotBoundary, "capped root");

  Fixture internal_root = open_tube();
  expect_empty_failure(run(internal_root, {4, 5, 6, 7}), HairTubeStatus::kRootNotBoundary,
                       "internal root ring");
}

void test_non_manifold_and_winding_conflict_are_rejected() {
  Fixture non_manifold = open_tube();
  non_manifold.faces.push_back(non_manifold.faces[0]);
  non_manifold.faces.push_back(non_manifold.faces[0]);
  expect_empty_failure(run(non_manifold, {0, 1, 2, 3}), HairTubeStatus::kNonManifoldEdge,
                       "non-manifold edge");

  Fixture winding = open_tube();
  std::reverse(winding.faces[0].begin(), winding.faces[0].end());
  expect_empty_failure(run(winding, {0, 1, 2, 3}), HairTubeStatus::kWindingConflict,
                       "winding conflict");
}

void test_incomplete_section_and_tip_cap_are_rejected() {
  Fixture incomplete = open_tube();
  incomplete.vertex_count = 14;
  incomplete.faces.push_back({8, 9, 13, 12});
  expect_empty_failure(run(incomplete, {0, 1, 2, 3}), HairTubeStatus::kSectionCountChanged,
                       "incomplete station");

  Fixture tip_cap = open_tube();
  tip_cap.faces.push_back({8, 9, 10, 11});
  expect_empty_failure(run(tip_cap, {0, 1, 2, 3}), HairTubeStatus::kAmbiguousContinuation,
                       "tip cap");
}

void test_bow_tie_vertex_is_rejected_as_ambiguous() {
  Fixture fixture;
  fixture.vertex_count = 7;
  fixture.faces = {{0, 1, 2, 3}, {0, 4, 5, 6}};

  expect_empty_failure(run(fixture, {0, 1, 2, 3}), HairTubeStatus::kAmbiguousContinuation,
                       "bow-tie vertex");
}

void test_extra_component_is_rejected() {
  Fixture fixture = open_tube();
  fixture.vertex_count = 16;
  fixture.faces.push_back({12, 13, 14, 15});
  expect_empty_failure(run(fixture, {0, 1, 2, 3}), HairTubeStatus::kDisconnectedTopology,
                       "extra component");
}

void test_malformed_buffer_is_rejected_without_partial_output() {
  const std::array<std::uint32_t, 4> root{0, 1, 2, 3};
  const HairTubeTopologyResult result = extract_hair_tube_topology(
      {}, HairTubeRootLoopView{root.data(), static_cast<std::uint64_t>(root.size())});

  expect_empty_failure(result, HairTubeStatus::kInvalidTopology, "malformed topology");
  expect(result.topology_status == TopologyStatus::kNullFaceOffsets,
         "malformed topology should retain the RawTopology status");
}

}  // namespace

int main() {
  test_valid_tube_has_deterministic_rings_and_rails();
  test_face_order_does_not_change_rings_or_rails();
  test_reversed_root_reverses_cyclic_rail_order_consistently();
  test_invalid_roots_are_rejected();
  test_non_quad_and_capped_root_are_rejected();
  test_non_manifold_and_winding_conflict_are_rejected();
  test_incomplete_section_and_tip_cap_are_rejected();
  test_bow_tie_vertex_is_rejected_as_ambiguous();
  test_extra_component_is_rejected();
  test_malformed_buffer_is_rejected_without_partial_output();

  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All hair tube topology tests passed\n";
  return EXIT_SUCCESS;
}
