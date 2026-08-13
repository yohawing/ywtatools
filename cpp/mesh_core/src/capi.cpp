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
                           const ywta::mesh_core::HairTubeTopology* source_topology,
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
  std::vector<std::uint32_t> source_vertex_pairs;
  intervals.reserve(generated.mesh.source_mapping.size());
  alphas.reserve(generated.mesh.source_mapping.size());
  source_vertex_pairs.reserve(generated.mesh.source_mapping.size() * 2);
  const std::size_t rail_count = static_cast<std::size_t>(cage.rail_count);
  for (std::size_t vertex = 0; vertex < generated.mesh.source_mapping.size(); ++vertex) {
    const ywta::mesh_core::HairTubeSourceSample& source = generated.mesh.source_mapping[vertex];
    intervals.push_back(source.interval);
    alphas.push_back(source.alpha);
    const std::size_t rail = vertex % rail_count;
    const std::size_t first = rail * static_cast<std::size_t>(cage.source_station_count) +
                              static_cast<std::size_t>(source.interval);
    if (source_topology != nullptr) {
      source_vertex_pairs.push_back(source_topology->rails[first]);
      source_vertex_pairs.push_back(source_topology->rails[first + 1]);
    } else {
      source_vertex_pairs.push_back(
          static_cast<std::uint32_t>(source.interval * rail_count + rail));
      source_vertex_pairs.push_back(
          static_cast<std::uint32_t>((source.interval + 1) * rail_count + rail));
    }
  }
  std::vector<std::uint64_t> source_faces(generated.mesh.quad_indices.size() / 4,
                                          std::numeric_limits<std::uint64_t>::max());
  std::vector<std::uint64_t> source_corner_faces;
  source_corner_faces.reserve(generated.mesh.quad_indices.size());
  const std::size_t output_station_count = generated.mesh.positions.size() / rail_count;
  for (std::size_t station = 0; station + 1 < output_station_count; ++station) {
    const auto parameter = [&cage](const ywta::mesh_core::HairTubeSourceSample& source) {
      const std::size_t interval = static_cast<std::size_t>(source.interval);
      return cage.shared_t[interval] * (1.0 - source.alpha) +
             cage.shared_t[interval + 1] * source.alpha;
    };
    const double midpoint = (parameter(generated.mesh.source_mapping[station * rail_count]) +
                             parameter(generated.mesh.source_mapping[(station + 1) * rail_count])) *
                            0.5;
    const auto upper = std::upper_bound(cage.shared_t.begin(), cage.shared_t.end(), midpoint);
    const std::size_t source_interval =
        std::min(static_cast<std::size_t>(std::distance(cage.shared_t.begin(), upper) - 1),
                 static_cast<std::size_t>(cage.source_station_count - 2));
    for (std::size_t rail = 0; rail < rail_count; ++rail) {
      if (source_topology != nullptr) {
        source_faces[station * rail_count + rail] =
            source_topology->side_faces[source_interval * rail_count + rail];
      } else {
        source_faces[station * rail_count + rail] = source_interval * rail_count + rail;
      }
      for (std::size_t corner = 0; corner < 4; ++corner) {
        const std::uint32_t output_vertex =
            generated.mesh.quad_indices[(station * rail_count + rail) * 4 + corner];
        const std::size_t corner_interval =
            static_cast<std::size_t>(generated.mesh.source_mapping[output_vertex].interval);
        source_corner_faces.push_back(source_topology != nullptr
                                          ? source_topology
                                                ->side_faces[corner_interval * rail_count + rail]
                                          : corner_interval * rail_count + rail);
      }
    }
  }
  const std::size_t source_side_face_count =
      static_cast<std::size_t>(cage.source_station_count - 1) * rail_count;
  std::size_t output_face = (output_station_count - 1) * rail_count;
  if (cage.root_capped) {
    const std::uint64_t source_face =
        source_topology != nullptr ? source_topology->root_cap_face : source_side_face_count;
    source_faces[output_face++] = source_face;
    source_corner_faces.insert(source_corner_faces.end(), 4, source_face);
  }
  if (cage.tip_capped) {
    const std::uint64_t source_face = source_topology != nullptr
                                          ? source_topology->tip_cap_face
                                          : source_side_face_count + cage.root_capped;
    source_faces[output_face] = source_face;
    source_corner_faces.insert(source_corner_faces.end(), 4, source_face);
  }

  output->vertex_count = generated.mesh.positions.size();
  output->quad_count = generated.mesh.quad_indices.size() / 4;
  output->positions_xyz = copy_array(flat_positions);
  output->quad_indices = copy_array(generated.mesh.quad_indices);
  output->source_intervals = copy_array(intervals);
  output->source_alphas = copy_array(alphas);
  output->source_vertex_pairs = copy_array(source_vertex_pairs);
  output->source_faces = copy_array(source_faces);
  output->source_corner_faces = copy_array(source_corner_faces);
  output->source_station_count = cage.source_station_count;
  output->max_fit_deviation = cage.max_fit_deviation;
  output->max_source_distance = generated.mesh.max_source_distance;
  output->cubic_active = cage.cubic_active ? 1 : 0;
  output->root_capped = cage.root_capped ? 1 : 0;
  output->tip_capped = cage.tip_capped ? 1 : 0;
  output->rail_count = cage.rail_count;
  return 0;
}

}  // namespace

int ywta_hair_tube_generate(uint32_t vertex_count, const double* positions_xyz,
                            const uint64_t* face_offsets, uint64_t face_count,
                            const uint32_t* face_vertices, uint64_t face_vertex_count,
                            const uint32_t* root_vertices, uint64_t target_segments,
                            double fit_tolerance, YwtaHairTubeOutput* output) {
  return ywta_hair_tube_generate_n(vertex_count, positions_xyz, face_offsets, face_count,
                                   face_vertices, face_vertex_count, root_vertices, 4,
                                   target_segments, fit_tolerance, output);
}

int ywta_hair_tube_generate_n(uint32_t vertex_count, const double* positions_xyz,
                              const uint64_t* face_offsets, uint64_t face_count,
                              const uint32_t* face_vertices, uint64_t face_vertex_count,
                              const uint32_t* root_vertices, uint64_t root_count,
                              uint64_t target_segments, double fit_tolerance,
                              YwtaHairTubeOutput* output) {
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
            {root_vertices, root_count});
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
    return write_generated_output(cage.cage, &topology.topology, target_segments, output);
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
  return ywta_hair_tube_generate_from_rails_ex(rail_positions_xyz, station_count, target_segments,
                                               fit_tolerance, 0, 0, output);
}

int ywta_hair_tube_generate_from_rails_ex(const double* rail_positions_xyz,
                                          uint64_t station_count, uint64_t target_segments,
                                          double fit_tolerance, int root_capped, int tip_capped,
                                          YwtaHairTubeOutput* output) {
  return ywta_hair_tube_generate_from_rails_n(
      rail_positions_xyz, 4, station_count, target_segments, fit_tolerance, root_capped,
      tip_capped, output);
}

int ywta_hair_tube_generate_from_rails_n(const double* rail_positions_xyz, uint64_t rail_count,
                                         uint64_t station_count, uint64_t target_segments,
                                         double fit_tolerance, int root_capped, int tip_capped,
                                         YwtaHairTubeOutput* output) {
  last_error.clear();
  if (output == nullptr) {
    last_error = "output must not be null";
    return 1;
  }
  clear_output(output);
  if (rail_positions_xyz == nullptr || rail_count < 3 || station_count < 2 ||
      rail_count > std::numeric_limits<std::uint32_t>::max() / station_count) {
    last_error = "rail positions and counts must describe at least three non-empty rails";
    return 2;
  }

  try {
    ywta::mesh_core::HairTubeTopology topology;
    topology.rail_count = rail_count;
    topology.station_count = station_count;
    topology.rails.reserve(static_cast<std::size_t>(station_count * rail_count));
    topology.rings.reserve(static_cast<std::size_t>(station_count * rail_count));
    std::vector<ywta::mesh_core::Point3d> positions;
    positions.reserve(static_cast<std::size_t>(station_count * rail_count));
    for (std::uint64_t rail = 0; rail < rail_count; ++rail) {
      for (std::uint64_t station = 0; station < station_count; ++station) {
        const std::uint64_t vertex = rail * station_count + station;
        const std::size_t offset = static_cast<std::size_t>(vertex) * 3;
        topology.rails.push_back(static_cast<std::uint32_t>(vertex));
        positions.push_back({rail_positions_xyz[offset], rail_positions_xyz[offset + 1],
                             rail_positions_xyz[offset + 2]});
      }
    }
    for (std::uint64_t station = 0; station < station_count; ++station) {
      for (std::uint64_t rail = 0; rail < rail_count; ++rail) {
        topology.rings.push_back(static_cast<std::uint32_t>(rail * station_count + station));
      }
    }
    topology.side_faces.resize(static_cast<std::size_t>(station_count - 1) * rail_count);
    topology.root_cap_face = root_capped != 0 ? 0 : ywta::mesh_core::kNoHairTubeFace;
    topology.tip_cap_face = tip_capped != 0 ? 0 : ywta::mesh_core::kNoHairTubeFace;
    const ywta::mesh_core::HairTubeCageResult cage = ywta::mesh_core::build_hair_tube_curve_cage(
        topology, {positions.data(), positions.size()}, fit_tolerance);
    if (!cage.ok()) {
      last_error = cage.message;
      return 200 + static_cast<int>(cage.status);
    }
    return write_generated_output(cage.cage, nullptr, target_segments, output);
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
  delete[] output->source_vertex_pairs;
  delete[] output->source_faces;
  delete[] output->source_corner_faces;
  clear_output(output);
}

const char* ywta_mesh_core_last_error(void) { return last_error.c_str(); }
