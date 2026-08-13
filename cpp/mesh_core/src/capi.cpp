#include "ywta/mesh_core/capi.h"

#include <algorithm>
#include <exception>
#include <limits>
#include <string>
#include <vector>

#include "ywta/mesh_core/hair_tube_cage.h"
#include "ywta/mesh_core/hair_tube_topology.h"

namespace {

thread_local std::string last_error;

template <typename T>
T* copy_array(const std::vector<T>& source) {
  if (source.empty()) {
    return nullptr;
  }
  T* output = new T[source.size()];
  std::copy(source.begin(), source.end(), output);
  return output;
}

void clear_output(YwtaHairTubeOutput* output) {
  if (output != nullptr) {
    *output = {};
  }
}

int write_generated_output(const ywta::mesh_core::HairTubeCurveCage& cage,
                           std::uint64_t target_segments, YwtaHairTubeOutput* output) {
  const ywta::mesh_core::HairTubeGeneratedMeshResult generated =
      ywta::mesh_core::regenerate_hair_tube_fixed_density(cage, target_segments);
  if (!generated.ok()) {
    last_error = generated.message;
    return 300 + static_cast<int>(generated.status);
  }

  std::vector<double> flat_positions;
  flat_positions.reserve(generated.mesh.positions.size() * 3);
  for (const ywta::mesh_core::Point3d& point : generated.mesh.positions) {
    flat_positions.insert(flat_positions.end(), {point.x, point.y, point.z});
  }
  std::vector<std::uint64_t> intervals;
  std::vector<double> alphas;
  intervals.reserve(generated.mesh.source_mapping.size());
  alphas.reserve(generated.mesh.source_mapping.size());
  for (const ywta::mesh_core::HairTubeSourceSample& source : generated.mesh.source_mapping) {
    intervals.push_back(source.interval);
    alphas.push_back(source.alpha);
  }

  output->vertex_count = generated.mesh.positions.size();
  output->quad_count = generated.mesh.quad_indices.size() / 4;
  output->positions_xyz = copy_array(flat_positions);
  output->quad_indices = copy_array(generated.mesh.quad_indices);
  output->source_intervals = copy_array(intervals);
  output->source_alphas = copy_array(alphas);
  output->source_station_count = cage.source_station_count;
  output->max_fit_deviation = cage.max_fit_deviation;
  output->max_source_distance = generated.mesh.max_source_distance;
  output->cubic_active = cage.cubic_active ? 1 : 0;
  return 0;
}

}  // namespace

int ywta_hair_tube_generate(uint32_t vertex_count, const double* positions_xyz,
                            const uint64_t* face_offsets, uint64_t face_count,
                            const uint32_t* face_vertices, uint64_t face_vertex_count,
                            const uint32_t* root_vertices, uint64_t target_segments,
                            double fit_tolerance, YwtaHairTubeOutput* output) {
  last_error.clear();
  if (output == nullptr) {
    last_error = "output must not be null";
    return 1;
  }
  clear_output(output);
  if (positions_xyz == nullptr) {
    last_error = "positions_xyz must not be null";
    return 2;
  }

  try {
    const ywta::mesh_core::HairTubeTopologyResult topology =
        ywta::mesh_core::extract_hair_tube_topology(
            {vertex_count, face_offsets, face_count, face_vertices, face_vertex_count},
            {root_vertices, 4});
    if (!topology.ok()) {
      last_error = topology.message;
      return 100 + static_cast<int>(topology.status);
    }

    std::vector<ywta::mesh_core::Point3d> positions;
    positions.reserve(vertex_count);
    for (std::uint32_t vertex = 0; vertex < vertex_count; ++vertex) {
      const std::size_t offset = static_cast<std::size_t>(vertex) * 3;
      positions.push_back(
          {positions_xyz[offset], positions_xyz[offset + 1], positions_xyz[offset + 2]});
    }
    const ywta::mesh_core::HairTubeCageResult cage = ywta::mesh_core::build_hair_tube_curve_cage(
        topology.topology, {positions.data(), positions.size()}, fit_tolerance);
    if (!cage.ok()) {
      last_error = cage.message;
      return 200 + static_cast<int>(cage.status);
    }
    return write_generated_output(cage.cage, target_segments, output);
  } catch (const std::exception& error) {
    ywta_hair_tube_free(output);
    last_error = error.what();
    return 3;
  } catch (...) {
    ywta_hair_tube_free(output);
    last_error = "unknown C++ exception";
    return 4;
  }
}

int ywta_hair_tube_generate_from_rails(const double* rail_positions_xyz, uint64_t station_count,
                                       uint64_t target_segments, double fit_tolerance,
                                       YwtaHairTubeOutput* output) {
  last_error.clear();
  if (output == nullptr) {
    last_error = "output must not be null";
    return 1;
  }
  clear_output(output);
  if (rail_positions_xyz == nullptr || station_count < 2 ||
      station_count > std::numeric_limits<std::uint32_t>::max() / 4) {
    last_error = "rail positions and station_count must describe four non-empty rails";
    return 2;
  }

  try {
    ywta::mesh_core::HairTubeTopology topology;
    topology.station_count = station_count;
    topology.rails.reserve(static_cast<std::size_t>(station_count) * 4);
    topology.rings.reserve(static_cast<std::size_t>(station_count) * 4);
    std::vector<ywta::mesh_core::Point3d> positions;
    positions.reserve(static_cast<std::size_t>(station_count) * 4);
    for (std::uint64_t rail = 0; rail < 4; ++rail) {
      for (std::uint64_t station = 0; station < station_count; ++station) {
        const std::uint64_t vertex = rail * station_count + station;
        const std::size_t offset = static_cast<std::size_t>(vertex) * 3;
        topology.rails.push_back(static_cast<std::uint32_t>(vertex));
        positions.push_back({rail_positions_xyz[offset], rail_positions_xyz[offset + 1],
                             rail_positions_xyz[offset + 2]});
      }
    }
    for (std::uint64_t station = 0; station < station_count; ++station) {
      for (std::uint64_t rail = 0; rail < 4; ++rail) {
        topology.rings.push_back(static_cast<std::uint32_t>(rail * station_count + station));
      }
    }
    topology.side_faces.resize(static_cast<std::size_t>(station_count - 1) * 4);
    const ywta::mesh_core::HairTubeCageResult cage = ywta::mesh_core::build_hair_tube_curve_cage(
        topology, {positions.data(), positions.size()}, fit_tolerance);
    if (!cage.ok()) {
      last_error = cage.message;
      return 200 + static_cast<int>(cage.status);
    }
    return write_generated_output(cage.cage, target_segments, output);
  } catch (const std::exception& error) {
    ywta_hair_tube_free(output);
    last_error = error.what();
    return 3;
  } catch (...) {
    ywta_hair_tube_free(output);
    last_error = "unknown C++ exception";
    return 4;
  }
}

void ywta_hair_tube_free(YwtaHairTubeOutput* output) {
  if (output == nullptr) {
    return;
  }
  delete[] output->positions_xyz;
  delete[] output->quad_indices;
  delete[] output->source_intervals;
  delete[] output->source_alphas;
  clear_output(output);
}

const char* ywta_mesh_core_last_error(void) { return last_error.c_str(); }
