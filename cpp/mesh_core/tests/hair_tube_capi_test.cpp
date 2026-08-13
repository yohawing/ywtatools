#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <string>
#include <vector>

#include "ywta/mesh_core/capi.h"

namespace {

int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

void test_round_trip_and_free() {
  const std::vector<double> positions{
      -0.5, -0.5, 0.0, 0.5, -0.5, 0.0, 0.5, 0.5, 0.0, -0.5, 0.5, 0.0,
      -0.5, -0.5, 1.0, 0.5, -0.5, 1.0, 0.5, 0.5, 1.0, -0.5, 0.5, 1.0,
  };
  const std::uint64_t offsets[]{0, 4, 8, 12, 16};
  const std::uint32_t faces[]{0, 1, 5, 4, 1, 2, 6, 5, 2, 3, 7, 6, 3, 0, 4, 7};
  const std::uint32_t root[]{0, 1, 2, 3};
  YwtaHairTubeOutput output{};
  const int status =
      ywta_hair_tube_generate(8, positions.data(), offsets, 4, faces, 16, root, 3, 0.0, &output);
  expect(status == 0, std::string("C ABI should succeed: ") + ywta_mesh_core_last_error());
  expect(output.vertex_count == 16 && output.quad_count == 12,
         "C ABI should return requested density");
  expect(output.positions_xyz != nullptr && output.quad_indices != nullptr &&
             output.source_intervals != nullptr && output.source_alphas != nullptr &&
             output.source_vertex_pairs != nullptr && output.source_faces != nullptr,
         "C ABI should allocate all output arrays");
  expect(output.source_vertex_pairs[0] == 0 && output.source_vertex_pairs[1] == 4 &&
             output.source_vertex_pairs[2] == 1 && output.source_vertex_pairs[3] == 5,
         "C ABI should expose source rail vertex pairs");
  expect(output.source_faces[0] == 0 && output.source_faces[3] == 3,
         "C ABI should expose source side faces");
  expect(output.positions_xyz[2] == 0.0 && output.positions_xyz[47] == 1.0,
         "C ABI should preserve root and tip");
  ywta_hair_tube_free(&output);
  expect(output.vertex_count == 0 && output.positions_xyz == nullptr &&
             output.quad_indices == nullptr && output.source_vertex_pairs == nullptr &&
             output.source_faces == nullptr,
         "free should clear output");
}

void test_invalid_input_has_no_partial_output() {
  const double positions[]{0.0, 0.0, 0.0};
  const std::uint64_t offsets[]{0};
  const std::uint32_t root[]{0, 1, 2, 3};
  YwtaHairTubeOutput output{};
  const int status =
      ywta_hair_tube_generate(1, positions, offsets, 0, nullptr, 0, root, 1, 0.0, &output);
  expect(status != 0, "invalid topology should fail");
  expect(output.vertex_count == 0 && output.positions_xyz == nullptr,
         "failure should not return partial output");
  expect(std::string(ywta_mesh_core_last_error()).size() > 0, "failure should expose a diagnostic");
}

void test_generate_from_edited_rails() {
  const std::vector<double> rails{
      -0.5, -0.5, 0.0, -0.5, -0.5, 1.0, 0.5,  -0.5, 0.0, 0.5,  -0.5, 1.0,
      0.5,  0.5,  0.0, 0.5,  0.5,  1.0, -0.5, 0.5,  0.0, -0.5, 0.5,  1.0,
  };
  YwtaHairTubeOutput output{};
  const int status = ywta_hair_tube_generate_from_rails(rails.data(), 2, 2, 0.0, &output);
  expect(status == 0,
         std::string("edited rails should regenerate: ") + ywta_mesh_core_last_error());
  expect(output.vertex_count == 12 && output.quad_count == 8,
         "edited rails should honor target density");
  expect(output.positions_xyz[0] == -0.5 && output.positions_xyz[35] == 1.0,
         "edited rail endpoints should be preserved");
  ywta_hair_tube_free(&output);
}

}  // namespace

int main() {
  test_round_trip_and_free();
  test_invalid_input_has_no_partial_output();
  test_generate_from_edited_rails();
  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All hair tube C ABI tests passed\n";
  return EXIT_SUCCESS;
}
