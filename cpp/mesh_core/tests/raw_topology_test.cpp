#include "ywta/mesh_core/raw_topology.h"

#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

namespace {

using ywta::mesh_core::BowTieSplitResult;
using ywta::mesh_core::kRemovedElement;
using ywta::mesh_core::plan_bow_tie_vertex_splits;
using ywta::mesh_core::plan_single_triangle_shell_removal;
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

void test_single_triangle_shell_removal_is_explicit_and_mapped() {
  const std::vector<std::uint64_t> offsets{0, 3, 6, 9, 13, 16};
  const std::vector<std::uint32_t> vertices{
      0, 1,  2,       // edgeを共有しないtriangle
      3, 4,  5,       // 次のtriangleとedgeを共有
      4, 3,  6,       // 前のtriangleとedgeを共有
      7, 8,  9,  10,  // standalone quadは削除対象外
      0, 11, 12,      // 最初のtriangleとは頂点だけを共有
  };
  const auto result = plan_single_triangle_shell_removal({
      14,  // vertex 13は入力時点から孤立
      offsets.data(),
      offsets.size() - 1,
      vertices.data(),
      vertices.size(),
  });

  expect(result.ok(), "single-triangle removal input should be accepted");
  expect(result.plan.removed_source_faces == std::vector<std::uint64_t>({0, 4}),
         "only edge-isolated triangles should be selected for removal");
  expect(result.plan.output_face_count == 3, "three non-target faces should remain");
  expect(result.plan.retained_face_offsets == std::vector<std::uint64_t>({0, 3, 6, 10}),
         "retained face offsets should be rebuilt");
  expect(result.plan.retained_face_vertices ==
             std::vector<std::uint32_t>({0, 1, 2, 1, 0, 3, 4, 5, 6, 7}),
         "retained faces should preserve corner order and use compacted vertices");
  expect(result.plan.source_face_by_output == std::vector<std::uint64_t>({1, 2, 3}),
         "output faces should map to source faces");
  expect(result.plan.output_face_by_source ==
             std::vector<std::uint64_t>({kRemovedElement, 0, 1, 2, kRemovedElement}),
         "removed source faces should use the removal sentinel");
  expect(result.plan.source_corner_by_output ==
             std::vector<std::uint64_t>({3, 4, 5, 6, 7, 8, 9, 10, 11, 12}),
         "corner attributes should map to their original corners");
  expect(result.plan.source_vertex_by_output ==
             std::vector<std::uint32_t>({3, 4, 5, 6, 7, 8, 9, 10, 13}),
         "deleted-shell vertices should be compacted while old isolated vertices remain");
  expect(result.plan.output_vertex_by_source ==
             std::vector<std::uint64_t>({kRemovedElement, kRemovedElement, kRemovedElement, 0, 1, 2,
                                         3, 4, 5, 6, 7, kRemovedElement, kRemovedElement, 8}),
         "source vertices should map to compacted output ids");
  expect(result.plan.output_vertex_count == 9,
         "five deleted-shell-only vertices should be removed");

  const auto second_pass = plan_single_triangle_shell_removal({
      static_cast<std::uint32_t>(result.plan.output_vertex_count),
      result.plan.retained_face_offsets.data(),
      result.plan.retained_face_offsets.size() - 1,
      result.plan.retained_face_vertices.data(),
      result.plan.retained_face_vertices.size(),
  });
  expect(second_pass.ok(), "retained topology should remain valid");
  expect(second_pass.plan.removed_source_faces.empty(),
         "single-triangle removal should be idempotent");
}

void test_single_triangle_removal_propagates_validation_failure() {
  const std::vector<std::uint64_t> offsets{0, 3};
  const std::vector<std::uint32_t> vertices{0, 1, 3};
  const auto result = plan_single_triangle_shell_removal({
      3,
      offsets.data(),
      offsets.size() - 1,
      vertices.data(),
      vertices.size(),
  });

  expect(result.status == TopologyStatus::kVertexIndexOutOfRange,
         "removal planning should reject invalid topology without a partial plan");
  expect(result.plan.retained_face_vertices.empty(),
         "invalid removal input should not return retained faces");
}

void test_single_triangle_removal_can_produce_an_empty_mesh() {
  const std::vector<std::uint64_t> offsets{0, 3};
  const std::vector<std::uint32_t> vertices{0, 1, 2};
  const auto result = plan_single_triangle_shell_removal({
      3,
      offsets.data(),
      offsets.size() - 1,
      vertices.data(),
      vertices.size(),
  });

  expect(result.ok(), "a standalone triangle should be removable");
  expect(result.plan.output_face_count == 0, "removing the only triangle should leave no faces");
  expect(result.plan.retained_face_offsets == std::vector<std::uint64_t>({0}),
         "an empty output should retain a valid offset sentinel");
  expect(result.plan.output_vertex_count == 0,
         "vertices used only by the removed triangle should also be removed");
}

}  // namespace

int main() {
  test_manifold_mesh_is_unchanged();
  test_two_fans_are_split_without_changing_faces();
  test_shared_edge_connects_polygon_fans();
  test_three_fans_are_deterministic();
  test_invalid_inputs_are_rejected_without_a_plan();
  test_empty_topology_is_supported();
  test_single_triangle_shell_removal_is_explicit_and_mapped();
  test_single_triangle_removal_propagates_validation_failure();
  test_single_triangle_removal_can_produce_an_empty_mesh();

  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All raw topology tests passed\n";
  return EXIT_SUCCESS;
}
