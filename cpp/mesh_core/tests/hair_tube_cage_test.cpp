#include "ywta/mesh_core/hair_tube_cage.h"

#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

using ywta::mesh_core::build_hair_tube_curve_cage;
using ywta::mesh_core::evaluate_hair_tube_curve_cage;
using ywta::mesh_core::HairTubeCageResult;
using ywta::mesh_core::HairTubeCageStatus;
using ywta::mesh_core::HairTubeCurveCage;
using ywta::mesh_core::HairTubeGeneratedMeshResult;
using ywta::mesh_core::HairTubeTopology;
using ywta::mesh_core::Point3d;
using ywta::mesh_core::Point3dView;
using ywta::mesh_core::regenerate_hair_tube_fixed_density;

constexpr double kTolerance = 1.0e-9;
int failures = 0;

void expect(bool condition, const std::string& message) {
  if (!condition) {
    std::cerr << "FAIL: " << message << '\n';
    ++failures;
  }
}

bool near(double first, double second, double tolerance = kTolerance) {
  return std::abs(first - second) <= tolerance;
}

bool near(const Point3d& first, const Point3d& second, double tolerance = kTolerance) {
  return near(first.x, second.x, tolerance) && near(first.y, second.y, tolerance) &&
         near(first.z, second.z, tolerance);
}

struct CageFixture {
  HairTubeTopology topology;
  std::vector<Point3d> positions;
};

CageFixture make_tube(const std::vector<Point3d>& centers) {
  CageFixture fixture;
  fixture.topology.station_count = centers.size();
  const std::vector<Point3d> corners{
      {-0.5, -0.5, 0.0},
      {0.5, -0.5, 0.0},
      {0.5, 0.5, 0.0},
      {-0.5, 0.5, 0.0},
  };
  for (const Point3d& center : centers) {
    for (const Point3d& corner : corners) {
      fixture.positions.push_back({center.x + corner.x, center.y + corner.y, center.z + corner.z});
      fixture.topology.rings.push_back(static_cast<std::uint32_t>(fixture.topology.rings.size()));
    }
  }
  for (std::size_t rail = 0; rail < 4; ++rail) {
    for (std::size_t station = 0; station < centers.size(); ++station) {
      fixture.topology.rails.push_back(static_cast<std::uint32_t>(station * 4 + rail));
    }
  }
  fixture.topology.side_faces.resize((centers.size() - 1) * 4);
  for (std::size_t face = 0; face < fixture.topology.side_faces.size(); ++face) {
    fixture.topology.side_faces[face] = face;
  }
  return fixture;
}

HairTubeCageResult build(CageFixture& fixture, double fit_tolerance) {
  return build_hair_tube_curve_cage(
      fixture.topology,
      Point3dView{fixture.positions.data(), static_cast<std::uint64_t>(fixture.positions.size())},
      fit_tolerance);
}

void expect_empty_cage_failure(const HairTubeCageResult& result, HairTubeCageStatus status,
                               const std::string& context) {
  expect(result.status == status,
         context + ": expected status " + std::to_string(static_cast<int>(status)) + ", got " +
             std::to_string(static_cast<int>(result.status)) + " (" + result.message + ")");
  expect(result.cage.source_station_count == 0, context + ": cage should be empty");
  expect(result.cage.shared_t.empty(), context + ": shared t should be empty");
  expect(result.cage.source_points.empty(), context + ": source points should be empty");
  expect(result.cage.cubic_segments.empty(), context + ": cubic segments should be empty");
}

void expect_empty_mesh_failure(const HairTubeGeneratedMeshResult& result, HairTubeCageStatus status,
                               const std::string& context) {
  expect(result.status == status,
         context + ": expected status " + std::to_string(static_cast<int>(status)) + ", got " +
             std::to_string(static_cast<int>(result.status)) + " (" + result.message + ")");
  expect(result.mesh.positions.empty(), context + ": positions should be empty");
  expect(result.mesh.quad_indices.empty(), context + ": indices should be empty");
  expect(result.mesh.source_mapping.empty(), context + ": mapping should be empty");
}

void test_uniform_polyline_round_trip() {
  CageFixture fixture = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 2.0}});
  const HairTubeCageResult built = build(fixture, 0.0);

  expect(built.ok(), "uniform tube should build");
  expect(!built.cage.cubic_active, "zero tolerance should force polyline mode");
  expect(built.cage.shared_t.size() == 3, "uniform tube should retain three stations");
  expect(near(built.cage.shared_t[0], 0.0) && near(built.cage.shared_t[1], 0.5) &&
             near(built.cage.shared_t[2], 1.0),
         "uniform tube should have uniform shared t");

  const HairTubeGeneratedMeshResult generated = regenerate_hair_tube_fixed_density(built.cage, 2);
  expect(generated.ok(), "source density should regenerate");
  expect(generated.mesh.positions.size() == fixture.positions.size(),
         "source density should retain the vertex count");
  for (std::size_t index = 0; index < fixture.positions.size(); ++index) {
    expect(near(generated.mesh.positions[index], fixture.positions[index]),
           "polyline source-density round trip should be exact");
  }
  expect(near(generated.mesh.max_source_distance, 0.0),
         "polyline output should remain on the Oracle");
}

void test_nonuniform_shared_t_uses_average_chord_length() {
  CageFixture fixture = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 3.0}});
  const HairTubeCageResult built = build(fixture, 0.0);

  expect(built.ok(), "nonuniform tube should build");
  expect(near(built.cage.shared_t[1], 1.0 / 3.0),
         "shared t should use the average four-rail chord length");
}

void test_cubic_interpolates_sources_and_obeys_tolerance() {
  CageFixture fixture =
      make_tube({{0.0, 0.0, 0.0}, {1.0, 0.0, 1.0}, {-1.0, 0.0, 2.0}, {0.0, 0.0, 3.0}});
  const HairTubeCageResult tight = build(fixture, 1.0e-12);
  const HairTubeCageResult permissive = build(fixture, 100.0);

  expect(tight.ok() && permissive.ok(), "bent tube should build for both tolerances");
  expect(tight.cage.max_fit_deviation > 1.0e-12,
         "bent cubic should report a measurable polyline deviation");
  expect(!tight.cage.cubic_active, "tight tolerance should fall back to polyline");
  expect(permissive.cage.cubic_active, "permissive tolerance should activate cubic mode");

  for (std::size_t station = 0; station < permissive.cage.shared_t.size(); ++station) {
    const auto sampled =
        evaluate_hair_tube_curve_cage(permissive.cage, permissive.cage.shared_t[station]);
    expect(sampled.ok(), "cubic source station should evaluate");
    for (std::size_t rail = 0; rail < 4; ++rail) {
      expect(near(sampled.sample.points[rail], fixture.positions[station * 4 + rail]),
             "natural cubic should interpolate every source station");
    }
  }
}

void test_fixed_density_counts_mapping_and_determinism() {
  CageFixture fixture = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 2.0}});
  const HairTubeCageResult built = build(fixture, 1.0);
  const HairTubeGeneratedMeshResult low = regenerate_hair_tube_fixed_density(built.cage, 1);
  const HairTubeGeneratedMeshResult high = regenerate_hair_tube_fixed_density(built.cage, 5);
  const HairTubeGeneratedMeshResult repeated = regenerate_hair_tube_fixed_density(built.cage, 5);

  expect(low.ok() && high.ok() && repeated.ok(), "low and high density should regenerate");
  expect(low.mesh.positions.size() == 8 && low.mesh.quad_indices.size() == 16,
         "one segment should produce two rings and four quads");
  expect(high.mesh.positions.size() == 24 && high.mesh.quad_indices.size() == 80,
         "five segments should produce six rings and twenty quads");
  expect(high.mesh.source_mapping.size() == high.mesh.positions.size(),
         "every output vertex should retain source mapping");
  for (std::size_t rail = 0; rail < 4; ++rail) {
    expect(near(high.mesh.positions[rail], fixture.positions[rail]),
           "root positions should remain exact");
    expect(near(high.mesh.positions[20 + rail], fixture.positions[8 + rail]),
           "tip positions should remain exact");
  }
  expect(high.mesh.quad_indices == repeated.mesh.quad_indices,
         "repeated regeneration should keep identical indices");
  for (std::size_t index = 0; index < high.mesh.positions.size(); ++index) {
    expect(near(high.mesh.positions[index], repeated.mesh.positions[index]),
           "repeated regeneration should keep identical positions");
    expect(
        high.mesh.source_mapping[index].interval == repeated.mesh.source_mapping[index].interval &&
            near(high.mesh.source_mapping[index].alpha, repeated.mesh.source_mapping[index].alpha),
        "repeated regeneration should keep identical source mapping");
  }
  expect(high.mesh.quad_indices[0] == 0 && high.mesh.quad_indices[1] == 1 &&
             high.mesh.quad_indices[2] == 5 && high.mesh.quad_indices[3] == 4,
         "quad winding should follow the source cyclic order");
}

void test_invalid_cage_inputs_fail_without_partial_output() {
  CageFixture fixture = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 2.0}});

  HairTubeTopology short_topology = fixture.topology;
  short_topology.station_count = 1;
  expect_empty_cage_failure(
      build_hair_tube_curve_cage(
          short_topology, Point3dView{fixture.positions.data(), fixture.positions.size()}, 0.0),
      HairTubeCageStatus::kInvalidTopologyLayout, "short topology");
  expect_empty_cage_failure(build_hair_tube_curve_cage(fixture.topology, {}, 0.0),
                            HairTubeCageStatus::kNullPositions, "null positions");

  CageFixture out_of_range = fixture;
  out_of_range.topology.rails[0] = 99;
  out_of_range.topology.rings[0] = 99;
  expect_empty_cage_failure(build(out_of_range, 0.0), HairTubeCageStatus::kPositionIndexOutOfRange,
                            "out-of-range position");

  CageFixture non_finite = fixture;
  non_finite.positions[0].x = std::numeric_limits<double>::infinity();
  expect_empty_cage_failure(build(non_finite, 0.0), HairTubeCageStatus::kNonFinitePosition,
                            "non-finite position");
  expect_empty_cage_failure(build(fixture, -1.0), HairTubeCageStatus::kInvalidFitTolerance,
                            "negative tolerance");

  CageFixture zero_interval = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}});
  expect_empty_cage_failure(build(zero_interval, 0.0),
                            HairTubeCageStatus::kZeroLengthStationInterval,
                            "zero station interval");

  HairTubeCurveCage invalid_parameters = build(fixture, 0.0).cage;
  invalid_parameters.shared_t[1] = invalid_parameters.shared_t[0];
  const auto invalid_sample = evaluate_hair_tube_curve_cage(invalid_parameters, 0.5);
  expect(invalid_sample.status == HairTubeCageStatus::kInvalidTopologyLayout,
         "non-increasing cage parameters should fail evaluation");
  expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(invalid_parameters, 2),
                            HairTubeCageStatus::kInvalidTopologyLayout,
                            "non-increasing cage parameters");
}

void test_invalid_regeneration_and_zero_area_fail_without_partial_output() {
  CageFixture fixture = make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 1.0}});
  const HairTubeCageResult built = build(fixture, 0.0);
  expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(built.cage, 0),
                            HairTubeCageStatus::kTargetSegmentsZero, "zero segments");
  expect_empty_mesh_failure(
      regenerate_hair_tube_fixed_density(built.cage, std::numeric_limits<std::uint64_t>::max()),
      HairTubeCageStatus::kOutputOverflow, "segment overflow");

  CageFixture collapsed;
  collapsed.topology = fixture.topology;
  collapsed.positions = {
      {0.0, 0.0, 0.0}, {0.0, 0.0, 0.0}, {0.0, 0.0, 0.0}, {0.0, 0.0, 0.0},
      {0.0, 0.0, 1.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 1.0}, {0.0, 0.0, 1.0},
  };
  const HairTubeCageResult collapsed_cage = build(collapsed, 0.0);
  expect(collapsed_cage.ok(), "collapsed cross section should build for diagnostic regeneration");
  expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(collapsed_cage.cage, 1),
                            HairTubeCageStatus::kZeroAreaQuad, "zero-area quad");

  CageFixture inverted = fixture;
  inverted.positions[4] = {-0.5, -0.5, 1.0};
  inverted.positions[5] = {-0.5, 0.5, 1.0};
  inverted.positions[6] = {0.5, 0.5, 1.0};
  inverted.positions[7] = {0.5, -0.5, 1.0};
  const HairTubeCageResult inverted_cage = build(inverted, 0.0);
  expect(inverted_cage.ok(), "inverted rail order should build for diagnostic regeneration");
  expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(inverted_cage.cage, 1),
                            HairTubeCageStatus::kInvertedQuad, "inverted quad");

  CageFixture intersecting =
      make_tube({{0.0, 0.0, 0.0}, {0.0, 0.0, 2.0}, {0.0, 0.0, 4.0}, {0.0, 0.0, 1.0}});
  const HairTubeCageResult intersecting_cage = build(intersecting, 0.0);
  expect(intersecting_cage.ok(), "overlapping rail path should build for regeneration checks");
  expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(intersecting_cage.cage, 3),
                            HairTubeCageStatus::kSelfIntersection,
                            "non-adjacent quad intersection");
  for (const double scale : {1.0e-6, 1.0e6}) {
    CageFixture scaled = intersecting;
    for (Point3d& point : scaled.positions) {
      point.x *= scale;
      point.y *= scale;
      point.z *= scale;
    }
    const HairTubeCageResult scaled_cage = build(scaled, 0.0);
    expect(scaled_cage.ok(), "scaled intersecting path should build");
    expect_empty_mesh_failure(regenerate_hair_tube_fixed_density(scaled_cage.cage, 3),
                              HairTubeCageStatus::kSelfIntersection,
                              "scale-independent intersection");
  }
}

}  // namespace

int main() {
  test_uniform_polyline_round_trip();
  test_nonuniform_shared_t_uses_average_chord_length();
  test_cubic_interpolates_sources_and_obeys_tolerance();
  test_fixed_density_counts_mapping_and_determinism();
  test_invalid_cage_inputs_fail_without_partial_output();
  test_invalid_regeneration_and_zero_area_fail_without_partial_output();

  if (failures != 0) {
    std::cerr << failures << " test(s) failed\n";
    return EXIT_FAILURE;
  }
  std::cout << "All hair tube cage tests passed\n";
  return EXIT_SUCCESS;
}
