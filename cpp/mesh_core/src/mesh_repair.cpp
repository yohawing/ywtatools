#include "ywta/mesh_core/mesh_repair.h"

#include <algorithm>
#include <map>
#include <queue>
#include <set>
#include <utility>

namespace ywta::mesh_core {
namespace {

using Edge = std::pair<std::uint32_t, std::uint32_t>;

struct EdgeUse {
  std::uint64_t face = 0;
  bool forward = false;
};

Edge edge_key(std::uint32_t first, std::uint32_t second) {
  return first < second ? Edge{first, second} : Edge{second, first};
}

MeshRepairResult repair_error(MeshRepairStatus status, std::string message) {
  MeshRepairResult result;
  result.status = status;
  result.message = std::move(message);
  return result;
}

}  // namespace

MeshRepairResult plan_safe_mesh_repair(const RawTopologyView& topology,
                                       const Point3dView& positions, double area_epsilon) {
  const MeshDiagnosticResult diagnostic = diagnose_mesh(topology, positions, area_epsilon);
  if (!diagnostic.ok()) {
    MeshRepairResult result = repair_error(MeshRepairStatus::kInvalidInput, diagnostic.message);
    result.diagnostic_status = diagnostic.status;
    result.topology_status = diagnostic.topology_status;
    return result;
  }
  MeshRepairResult result;
  MeshRepairPlan& plan = result.plan;
  std::vector<bool> removed(static_cast<std::size_t>(topology.face_count), false);
  for (const std::uint64_t face : diagnostic.report.zero_area_faces) {
    removed[static_cast<std::size_t>(face)] = true;
    plan.removed_zero_area_faces.push_back(face);
  }

  std::map<std::vector<std::uint32_t>, std::uint64_t> first_face;
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    if (removed[static_cast<std::size_t>(face)]) {
      continue;
    }
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    std::vector<std::uint32_t> canonical(topology.face_vertices + begin,
                                         topology.face_vertices + end);
    std::sort(canonical.begin(), canonical.end());
    if (!first_face.emplace(std::move(canonical), face).second) {
      removed[static_cast<std::size_t>(face)] = true;
      plan.removed_duplicate_faces.push_back(face);
    }
  }

  std::map<Edge, std::vector<EdgeUse>> edges;
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    if (removed[static_cast<std::size_t>(face)]) {
      continue;
    }
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint32_t first = topology.face_vertices[corner];
      const std::uint32_t second = topology.face_vertices[corner + 1 == end ? begin : corner + 1];
      const Edge key = edge_key(first, second);
      edges[key].push_back({face, first == key.first});
    }
  }

  std::vector<std::vector<std::pair<std::uint64_t, bool>>> adjacency(
      static_cast<std::size_t>(topology.face_count));
  for (const auto& [edge, uses] : edges) {
    if (uses.size() > 2) {
      return repair_error(MeshRepairStatus::kUnsafeNonManifoldEdge,
                          "safe repair refuses edges shared by three or more retained faces");
    }
    if (uses.size() != 2) {
      continue;
    }
    const bool relative_flip = uses[0].forward == uses[1].forward;
    adjacency[static_cast<std::size_t>(uses[0].face)].push_back({uses[1].face, relative_flip});
    adjacency[static_cast<std::size_t>(uses[1].face)].push_back({uses[0].face, relative_flip});
  }
  std::vector<int> flip(static_cast<std::size_t>(topology.face_count), -1);
  for (std::uint64_t seed = 0; seed < topology.face_count; ++seed) {
    if (removed[static_cast<std::size_t>(seed)] || flip[static_cast<std::size_t>(seed)] != -1) {
      continue;
    }
    flip[static_cast<std::size_t>(seed)] = 0;
    std::queue<std::uint64_t> pending;
    pending.push(seed);
    while (!pending.empty()) {
      const std::uint64_t face = pending.front();
      pending.pop();
      for (const auto& [neighbour, relative_flip] : adjacency[static_cast<std::size_t>(face)]) {
        const int expected = flip[static_cast<std::size_t>(face)] ^ static_cast<int>(relative_flip);
        int& assigned = flip[static_cast<std::size_t>(neighbour)];
        if (assigned == -1) {
          assigned = expected;
          pending.push(neighbour);
        } else if (assigned != expected) {
          return repair_error(MeshRepairStatus::kNonOrientableSurface,
                              "face winding constraints are non-orientable");
        }
      }
    }
  }

  plan.old_face_to_new.assign(static_cast<std::size_t>(topology.face_count), kRemovedFace);
  plan.face_offsets.push_back(0);
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    if (removed[static_cast<std::size_t>(face)]) {
      continue;
    }
    const std::uint64_t output_face = plan.source_face_by_output.size();
    plan.old_face_to_new[static_cast<std::size_t>(face)] = output_face;
    plan.source_face_by_output.push_back(face);
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    if (flip[static_cast<std::size_t>(face)] == 0) {
      for (std::uint64_t corner = begin; corner < end; ++corner) {
        plan.face_vertices.push_back(topology.face_vertices[corner]);
        plan.source_corner_by_output.push_back(corner);
      }
    } else {
      plan.flipped_source_faces.push_back(face);
      plan.face_vertices.push_back(topology.face_vertices[begin]);
      plan.source_corner_by_output.push_back(begin);
      for (std::uint64_t corner = end - 1; corner > begin; --corner) {
        plan.face_vertices.push_back(topology.face_vertices[corner]);
        plan.source_corner_by_output.push_back(corner);
      }
    }
    plan.face_offsets.push_back(plan.face_vertices.size());
  }
  return result;
}

}  // namespace ywta::mesh_core
