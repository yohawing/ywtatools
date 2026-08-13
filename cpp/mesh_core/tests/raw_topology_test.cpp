#include "ywta/mesh_core/raw_topology.h"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

using ywta::mesh_core::BowTieSplitResult;
using ywta::mesh_core::plan_bow_tie_vertex_splits;
using ywta::mesh_core::plan_manifold_splits;
using ywta::mesh_core::RawTopologyView;
using ywta::mesh_core::TopologyStatus;

int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

BowTieSplitResult run(std::uint32_t vertex_count, const std::vector<std::uint64_t>& offsets,
                      const std::vector<std::uint32_t>& vertices) {
  return plan_bow_tie_vertex_splits(RawTopologyView{
      vertex_count,
      offsets.data(),
      offsets.size() - 1,
      vertices.data(),
      vertices.size(),
  });
}

void expect_repaired_result_is_idempotent(const BowTieSplitResult& repaired,
                                          const std::vector<std::uint64_t>& offsets,
                                          const std::string& context) {
  const BowTieSplitResult second_pass =
      run(static_cast<std::uint32_t>(repaired.plan.output_vertex_count), offsets,
          repaired.plan.rewritten_face_vertices);
  expect(second_pass.ok(), context + ": repaired topology should remain valid");
  expect(second_pass.plan.splits.empty(),
         context + ": repaired topology should have one fan per vertex");
  expect(second_pass.plan.output_vertex_count == repaired.plan.output_vertex_count,
         context + ": a second pass should not add vertices");
}

void test_manifold_mesh_is_unchanged() {
  const std::vector<std::uint64_t> offsets{0, 3, 6};
  const std::vector<std::uint32_t> vertices{0, 1, 2, 0, 2, 3};
  const BowTieSplitResult result = run(5, offsets, vertices);

  expect(result.ok(), "manifold mesh should be accepted");
  expect(result.plan.output_vertex_count == 5, "manifold mesh should not add vertices");
  expect(result.plan.rewritten_face_vertices == vertices, "manifold indices should stay unchanged");
  expect(result.plan.splits.empty(), "manifold mesh should not report a split");
  expect(result.plan.source_to_output_offsets == std::vector<std::uint64_t>({0, 1, 2, 3, 4, 5}),
         "isolated vertices should remain in the source mapping");
}

void test_two_fans_are_split_without_changing_faces() {
  const std::vector<std::uint64_t> offsets{0, 3, 6};
  const std::vector<std::uint32_t> vertices{0, 1, 2, 0, 3, 4};
  const BowTieSplitResult result = run(5, offsets, vertices);

  expect(result.ok(), "bow-tie mesh should be repairable");
  expect(result.plan.output_vertex_count == 6, "one extra fan should add one vertex");
  expect(result.plan.rewritten_face_vertices == std::vector<std::uint32_t>({0, 1, 2, 5, 3, 4}),
         "the second fan should use the duplicated vertex");
  expect(result.plan.splits.size() == 1, "one bow-tie vertex should be reported");
  expect(result.plan.splits[0].source_vertex == 0, "split should retain the source vertex id");
  expect(result.plan.splits[0].output_vertices == std::vector<std::uint32_t>({0, 5}),
         "split should expose all output vertex ids");
  expect(result.plan.source_vertex_by_output == std::vector<std::uint32_t>({0, 1, 2, 3, 4, 0}),
         "new vertex attributes should map back to the source vertex");
  expect_repaired_result_is_idempotent(result, offsets, "two-fan split");
}

void test_shared_edge_connects_polygon_fans() {
  const std::vector<std::uint64_t> offsets{0, 4, 7, 10};
  const std::vector<std::uint32_t> vertices{
      0, 1, 2, 3, 0, 4, 1, 0, 5, 6,
  };
  const BowTieSplitResult result = run(7, offsets, vertices);

  expect(result.ok(), "polygon mesh should be accepted");
  expect(result.plan.output_vertex_count == 8, "only the disconnected third face should split");
  expect(result.plan.rewritten_face_vertices[4] == 0, "shared edge should keep the original fan");
  expect(result.plan.rewritten_face_vertices[7] == 7, "disconnected fan should use a duplicate");
}

void test_three_fans_are_deterministic() {
  const std::vector<std::uint64_t> offsets{0, 3, 6, 9};
  const std::vector<std::uint32_t> vertices{0, 1, 2, 0, 3, 4, 0, 5, 6};
  const BowTieSplitResult result = run(7, offsets, vertices);

  expect(result.ok(), "three-fan bow-tie should be repairable");
  expect(result.plan.output_vertex_count == 9, "three fans should add two vertices");
  expect(result.plan.rewritten_face_vertices ==
             std::vector<std::uint32_t>({0, 1, 2, 7, 3, 4, 8, 5, 6}),
         "new ids should follow face order deterministically");
  expect_repaired_result_is_idempotent(result, offsets, "three-fan split");
}

void test_invalid_inputs_are_rejected_without_a_plan() {
  BowTieSplitResult result = plan_bow_tie_vertex_splits({});
  expect(result.status == TopologyStatus::kNullFaceOffsets, "null offsets should fail");

  const std::vector<std::uint64_t> bad_offsets{0, 3};
  const std::vector<std::uint32_t> repeated{0, 1, 0};
  result = run(3, bad_offsets, repeated);
  expect(result.status == TopologyStatus::kRepeatedFaceVertex, "repeated face vertex should fail");
  expect(result.plan.rewritten_face_vertices.empty(),
         "invalid input should not return a partial plan");

  const std::vector<std::uint32_t> out_of_range{0, 1, 3};
  result = run(3, bad_offsets, out_of_range);
  expect(result.status == TopologyStatus::kVertexIndexOutOfRange, "out-of-range index should fail");

  const std::vector<std::uint64_t> short_face_offsets{0, 2};
  const std::vector<std::uint32_t> short_face{0, 1};
  result = run(2, short_face_offsets, short_face);
  expect(result.status == TopologyStatus::kFaceTooSmall, "short face should fail");

  result = plan_bow_tie_vertex_splits({3, bad_offsets.data(), 1, nullptr, 3});
  expect(result.status == TopologyStatus::kNullFaceVertices, "null indices should fail");

  const std::vector<std::uint64_t> wrong_end_offsets{0, 4};
  result = plan_bow_tie_vertex_splits(
      {3, wrong_end_offsets.data(), 1, repeated.data(), repeated.size()});
  expect(result.status == TopologyStatus::kInvalidFaceOffsets,
         "offsets ending beyond the index buffer should fail");
}

void test_empty_topology_is_supported() {
  const std::vector<std::uint64_t> offsets{0};
  const std::vector<std::uint32_t> vertices;
  const BowTieSplitResult result = run(2, offsets, vertices);

  expect(result.ok(), "empty face set should be accepted");
  expect(result.plan.output_vertex_count == 2, "isolated vertices should be preserved");
  expect(result.plan.source_vertex_by_output == std::vector<std::uint32_t>({0, 1}),
         "isolated vertex attributes should retain identity mapping");
}

void test_non_manifold_edge_uses_are_split() {
  const std::vector<std::uint64_t> offsets{0, 3, 6, 9};
  const std::vector<std::uint32_t> vertices{0, 1, 2, 1, 0, 3, 0, 1, 4};
  const auto result = plan_manifold_splits({5, offsets.data(), 3, vertices.data(), 9});

  expect(result.ok(), "non-manifold edge should be splittable");
  expect(result.plan.split_non_manifold_edges == std::vector<std::uint32_t>({0, 1}),
         "split plan should report the source non-manifold edge");
  expect(result.plan.output_vertex_count == 7, "third edge use should duplicate both endpoints");
  expect(result.plan.rewritten_face_vertices ==
             std::vector<std::uint32_t>({0, 1, 2, 1, 0, 3, 5, 6, 4}),
         "first two edge uses should stay together and later uses should split");
  expect(result.plan.source_vertex_by_output ==
             std::vector<std::uint32_t>({0, 1, 2, 3, 4, 0, 1}),
         "duplicated point attributes should map to source endpoints");
  const auto second = plan_manifold_splits(
      {7, offsets.data(), 3, result.plan.rewritten_face_vertices.data(), 9});
  expect(second.ok() && second.plan.output_vertex_count == 7,
         "split topology should be idempotent");
}

void test_edge_and_vertex_fans_are_split_together() {
  const std::vector<std::uint64_t> offsets{0, 3, 6, 9, 12};
  const std::vector<std::uint32_t> vertices{0, 1, 2, 1, 0, 3, 0, 1, 4, 0, 5, 6};
  const auto result = plan_manifold_splits({7, offsets.data(), 4, vertices.data(), 12});

  expect(result.ok(), "combined edge and vertex fans should be splittable");
  expect(result.plan.output_vertex_count == 10,
         "edge endpoints and disconnected vertex fan should each duplicate");
  expect(result.plan.split_source_vertices == std::vector<std::uint32_t>({0}),
         "plan should report the source vertex fan split");
  for (const std::uint32_t source : result.plan.source_vertex_by_output) {
    expect(source < 7, "every output vertex should retain an original source mapping");
  }
}

}  // namespace

int main() {
  test_manifold_mesh_is_unchanged();
  test_two_fans_are_split_without_changing_faces();
  test_shared_edge_connects_polygon_fans();
  test_three_fans_are_deterministic();
  test_invalid_inputs_are_rejected_without_a_plan();
  test_empty_topology_is_supported();
  test_non_manifold_edge_uses_are_split();
  test_edge_and_vertex_fans_are_split_together();

  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All raw topology tests passed\n";
  return EXIT_SUCCESS;
}
