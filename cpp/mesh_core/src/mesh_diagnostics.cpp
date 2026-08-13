#include "ywta/mesh_core/mesh_diagnostics.h"

#include <algorithm>
#include <cmath>
#include <map>
#include <set>
#include <sstream>
#include <unordered_map>
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

double squared_length(const Point3d& point) {
  return point.x * point.x + point.y * point.y + point.z * point.z;
}

Point3d cross(const Point3d& first, const Point3d& second) {
  return {first.y * second.z - first.z * second.y,
          first.z * second.x - first.x * second.z,
          first.x * second.y - first.y * second.x};
}

Point3d subtract(const Point3d& first, const Point3d& second) {
  return {first.x - second.x, first.y - second.y, first.z - second.z};
}

void append_edge(std::vector<std::uint32_t>& output, const Edge& edge) {
  output.push_back(edge.first);
  output.push_back(edge.second);
}

}  // namespace

MeshDiagnosticResult diagnose_mesh(const RawTopologyView& topology, const Point3dView& positions,
                                   double area_epsilon) {
  const BowTieSplitResult validation = plan_bow_tie_vertex_splits(topology);
  if (!validation.ok()) {
    return {MeshDiagnosticStatus::kInvalidTopology, validation.status, validation.message, {}};
  }
  if (positions.points == nullptr) {
    return {MeshDiagnosticStatus::kNullPositions, TopologyStatus::kOk,
            "positions must not be null", {}};
  }
  if (positions.count < topology.vertex_count) {
    return {MeshDiagnosticStatus::kPositionCountMismatch, TopologyStatus::kOk,
            "positions must contain every topology vertex", {}};
  }
  for (std::uint32_t vertex = 0; vertex < topology.vertex_count; ++vertex) {
    const Point3d point = positions.points[vertex];
    if (!std::isfinite(point.x) || !std::isfinite(point.y) || !std::isfinite(point.z)) {
      std::ostringstream message;
      message << "position " << vertex << " contains a non-finite component";
      return {MeshDiagnosticStatus::kNonFinitePosition, TopologyStatus::kOk, message.str(), {}};
    }
  }
  if (!std::isfinite(area_epsilon) || area_epsilon < 0.0) {
    return {MeshDiagnosticStatus::kInvalidAreaEpsilon, TopologyStatus::kOk,
            "area_epsilon must be finite and non-negative", {}};
  }

  MeshDiagnosticResult result;
  auto& report = result.report;
  for (const BowTieVertexSplit& split : validation.plan.splits) {
    report.bow_tie_vertices.push_back(split.source_vertex);
  }

  std::map<Edge, std::vector<EdgeUse>> edges;
  std::map<std::vector<std::uint32_t>, std::uint64_t> first_face_by_vertices;
  std::set<std::uint64_t> duplicate_faces;
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    std::vector<std::uint32_t> canonical(topology.face_vertices + begin,
                                         topology.face_vertices + end);
    std::sort(canonical.begin(), canonical.end());
    const auto [found, inserted] = first_face_by_vertices.emplace(canonical, face);
    if (!inserted) {
      duplicate_faces.insert(found->second);
      duplicate_faces.insert(face);
    }

    const Point3d origin = positions.points[topology.face_vertices[begin]];
    double doubled_area = 0.0;
    for (std::uint64_t corner = begin + 1; corner + 1 < end; ++corner) {
      const Point3d triangle =
          cross(subtract(positions.points[topology.face_vertices[corner]], origin),
                subtract(positions.points[topology.face_vertices[corner + 1]], origin));
      doubled_area += std::sqrt(squared_length(triangle));
    }
    if (doubled_area * 0.5 <= area_epsilon) {
      report.zero_area_faces.push_back(face);
    }

    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint32_t first = topology.face_vertices[corner];
      const std::uint32_t second = topology.face_vertices[corner + 1 == end ? begin : corner + 1];
      const Edge key = edge_key(first, second);
      edges[key].push_back({face, first == key.first});
    }
  }
  report.duplicate_faces.assign(duplicate_faces.begin(), duplicate_faces.end());

  std::map<std::uint32_t, std::vector<std::uint32_t>> boundary_adjacency;
  for (const auto& [edge, uses] : edges) {
    if (uses.size() > 2) {
      append_edge(report.non_manifold_edges, edge);
    } else if (uses.size() == 2 && uses[0].forward == uses[1].forward) {
      append_edge(report.winding_conflict_edges, edge);
    } else if (uses.size() == 1) {
      boundary_adjacency[edge.first].push_back(edge.second);
      boundary_adjacency[edge.second].push_back(edge.first);
    }
  }

  report.boundary_loop_offsets.push_back(0);
  std::set<Edge> visited;
  for (auto& [vertex, neighbours] : boundary_adjacency) {
    std::sort(neighbours.begin(), neighbours.end());
    if (neighbours.size() != 2) {
      continue;
    }
    for (const std::uint32_t neighbour : neighbours) {
      const Edge start_edge = edge_key(vertex, neighbour);
      if (visited.count(start_edge) != 0) {
        continue;
      }
      std::vector<std::uint32_t> loop{vertex};
      std::uint32_t previous = vertex;
      std::uint32_t current = neighbour;
      while (current != vertex) {
        loop.push_back(current);
        const auto found = boundary_adjacency.find(current);
        if (found == boundary_adjacency.end() || found->second.size() != 2) {
          loop.clear();
          break;
        }
        visited.insert(edge_key(previous, current));
        const std::uint32_t next = found->second[0] == previous ? found->second[1] : found->second[0];
        previous = current;
        current = next;
        if (loop.size() > boundary_adjacency.size()) {
          loop.clear();
          break;
        }
      }
      if (!loop.empty()) {
        visited.insert(edge_key(previous, current));
        report.boundary_loop_vertices.insert(report.boundary_loop_vertices.end(), loop.begin(),
                                             loop.end());
        report.boundary_loop_offsets.push_back(report.boundary_loop_vertices.size());
      }
    }
  }
  return result;
}

}  // namespace ywta::mesh_core
