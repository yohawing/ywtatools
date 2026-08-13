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
             output.source_intervals != nullptr && output.source_alphas != nullptr,
         "C ABI should allocate all output arrays");
  expect(output.positions_xyz[2] == 0.0 && output.positions_xyz[47] == 1.0,
         "C ABI should preserve root and tip");
  ywta_hair_tube_free(&output);
  expect(
      output.vertex_count == 0 && output.positions_xyz == nullptr && output.quad_indices == nullptr,
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

}  // namespace

int main() {
  test_round_trip_and_free();
  test_invalid_input_has_no_partial_output();
  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All hair tube C ABI tests passed\n";
  return EXIT_SUCCESS;
}
