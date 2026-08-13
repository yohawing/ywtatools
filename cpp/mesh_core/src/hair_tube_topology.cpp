#include "ywta/mesh_core/hair_tube_topology.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <sstream>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace ywta::mesh_core {
namespace {

struct EdgeKey {
  std::uint32_t first = 0;
  std::uint32_t second = 0;

  [[nodiscard]] bool operator==(const EdgeKey& other) const noexcept {
    return first == other.first && second == other.second;
  }
};

struct EdgeKeyHash {
  [[nodiscard]] std::size_t operator()(const EdgeKey& edge) const noexcept {
    const std::size_t first = std::hash<std::uint32_t>{}(edge.first);
    const std::size_t second = std::hash<std::uint32_t>{}(edge.second);
    return first ^ (second + 0x9e3779b9U + (first << 6U) + (first >> 2U));
  }
};

struct EdgeUse {
  std::uint64_t face = 0;
  bool canonical_direction = false;
};

using EdgeTable = std::unordered_map<EdgeKey, std::vector<EdgeUse>, EdgeKeyHash>;

EdgeKey edge_key(std::uint32_t first, std::uint32_t second) {
  return first < second ? EdgeKey{first, second} : EdgeKey{second, first};
}

HairTubeTopologyResult error_result(HairTubeStatus status, std::string message,
                                    TopologyStatus topology_status = TopologyStatus::kOk) {
  HairTubeTopologyResult result;
  result.status = status;
  result.topology_status = topology_status;
  result.message = std::move(message);
  return result;
}

std::vector<std::uint32_t> face_vertices(const RawTopologyView& topology, std::uint64_t face) {
  const std::uint64_t begin = topology.face_offsets[face];
  const std::uint64_t end = topology.face_offsets[face + 1];
  return {topology.face_vertices + begin, topology.face_vertices + end};
}

bool assign_next(std::vector<std::uint64_t>& next_ring, std::size_t rail, std::uint32_t vertex) {
  constexpr std::uint64_t kUnset = std::numeric_limits<std::uint64_t>::max();
  if (next_ring[rail] == kUnset) {
    next_ring[rail] = vertex;
    return true;
  }
  return next_ring[rail] == vertex;
}

bool opposite_vertices(const std::vector<std::uint32_t>& face, std::uint32_t first,
                       std::uint32_t second, std::uint32_t& next_first,
                       std::uint32_t& next_second) {
  for (std::size_t index = 0; index < face.size(); ++index) {
    if (face[index] != first) {
      continue;
    }
    const std::size_t previous = (index + face.size() - 1) % face.size();
    const std::size_t next = (index + 1) % face.size();
    if (face[next] == second) {
      next_first = face[previous];
      next_second = face[(next + 1) % face.size()];
      return true;
    }
    if (face[previous] == second) {
      next_first = face[next];
      next_second = face[(previous + face.size() - 1) % face.size()];
      return true;
    }
  }
  return false;
}

bool face_matches_ring(const RawTopologyView& topology, std::uint64_t face,
                       const std::vector<std::uint32_t>& ring) {
  const auto vertices = face_vertices(topology, face);
  return vertices.size() == ring.size() &&
         std::all_of(vertices.begin(), vertices.end(), [&ring](std::uint32_t vertex) {
           return std::find(ring.begin(), ring.end(), vertex) != ring.end();
         });
}

}  // namespace

HairTubeTopologyResult extract_hair_tube_topology(const RawTopologyView& topology,
                                                  const HairTubeRootLoopView& root_loop) {
  const BowTieSplitResult validation = plan_bow_tie_vertex_splits(topology);
  if (!validation.ok()) {
    return error_result(HairTubeStatus::kInvalidTopology, validation.message, validation.status);
  }
  if (root_loop.count < 3 || root_loop.count > std::numeric_limits<std::uint32_t>::max()) {
    return error_result(HairTubeStatus::kInvalidRootLoopCount,
                        "root loop must contain at least three vertices");
  }
  if (root_loop.vertices == nullptr) {
    return error_result(HairTubeStatus::kNullRootVertices, "root loop vertices is null");
  }

  std::vector<std::uint32_t> root(static_cast<std::size_t>(root_loop.count));
  std::unordered_set<std::uint32_t> root_vertices;
  std::uint64_t root_cap_face = kNoHairTubeFace;
  bool root_has_boundary_edge = false;
  for (std::size_t rail = 0; rail < root.size(); ++rail) {
    const std::uint32_t vertex = root_loop.vertices[rail];
    if (vertex >= topology.vertex_count) {
      return error_result(HairTubeStatus::kRootVertexOutOfRange,
                          "root loop contains an out-of-range vertex");
    }
    if (!root_vertices.insert(vertex).second) {
      return error_result(HairTubeStatus::kRepeatedRootVertex,
                          "root loop contains a repeated vertex");
    }
    root[rail] = vertex;
  }

  EdgeTable edges;
  edges.reserve(static_cast<std::size_t>(topology.face_vertex_count));
  std::vector<bool> vertex_used(topology.vertex_count, false);
  for (std::uint64_t face = 0; face < topology.face_count; ++face) {
    const std::uint64_t begin = topology.face_offsets[face];
    const std::uint64_t end = topology.face_offsets[face + 1];
    if (end - begin != 4) {
      std::ostringstream message;
      message << "face " << face << " is not a quad";
      return error_result(HairTubeStatus::kNonQuadFace, message.str());
    }
    for (std::uint64_t corner = begin; corner < end; ++corner) {
      const std::uint32_t first = topology.face_vertices[corner];
      const std::uint32_t second = topology.face_vertices[corner + 1 == end ? begin : corner + 1];
      vertex_used[first] = true;
      const EdgeKey key = edge_key(first, second);
      std::vector<EdgeUse>& uses = edges[key];
      uses.push_back(EdgeUse{face, first == key.first});
      if (uses.size() > 2) {
        std::ostringstream message;
        message << "edge " << key.first << '-' << key.second << " has more than two incident faces";
        return error_result(HairTubeStatus::kNonManifoldEdge, message.str());
      }
    }
  }
  if (!validation.plan.splits.empty()) {
    return error_result(HairTubeStatus::kAmbiguousContinuation,
                        "topology contains a bow-tie vertex");
  }
  for (const auto& [key, uses] : edges) {
    if (uses.size() == 2 && uses[0].canonical_direction == uses[1].canonical_direction) {
      std::ostringstream message;
      message << "edge " << key.first << '-' << key.second << " has inconsistent face winding";
      return error_result(HairTubeStatus::kWindingConflict, message.str());
    }
  }
  if (std::find(vertex_used.begin(), vertex_used.end(), false) != vertex_used.end()) {
    return error_result(HairTubeStatus::kDisconnectedTopology,
                        "topology contains an unused vertex");
  }

  for (std::size_t rail = 0; rail < root.size(); ++rail) {
    const EdgeKey key = edge_key(root[rail], root[(rail + 1) % root.size()]);
    const auto found = edges.find(key);
    if (found == edges.end()) {
      return error_result(HairTubeStatus::kRootEdgeMissing,
                          "root loop contains an edge absent from the topology");
    }
    if (found->second.size() == 1) {
      root_has_boundary_edge = true;
      continue;
    }
    const auto cap = std::find_if(found->second.begin(), found->second.end(),
                                  [&topology, &root](const EdgeUse& use) {
                                    return face_matches_ring(topology, use.face, root);
                                  });
    if (cap == found->second.end() ||
        (root_cap_face != kNoHairTubeFace && root_cap_face != cap->face)) {
      return error_result(HairTubeStatus::kRootNotBoundary,
                          "root loop must be a boundary loop or share one quad cap");
    }
    root_cap_face = cap->face;
  }
  if (root_cap_face != kNoHairTubeFace && root_has_boundary_edge) {
    return error_result(HairTubeStatus::kRootNotBoundary, "root loop is only partially capped");
  }

  HairTubeTopology extracted;
  extracted.rail_count = root.size();
  extracted.rings.insert(extracted.rings.end(), root.begin(), root.end());
  std::vector<std::uint32_t> current = root;
  std::vector<bool> visited_faces(static_cast<std::size_t>(topology.face_count), false);
  if (root_cap_face != kNoHairTubeFace) {
    visited_faces[static_cast<std::size_t>(root_cap_face)] = true;
    extracted.root_cap_face = root_cap_face;
  }
  std::unordered_set<std::uint32_t> visited_vertices(root.begin(), root.end());

  while (true) {
    std::vector<std::uint64_t> next_faces(current.size());
    std::vector<std::size_t> continuation_counts(current.size());
    for (std::size_t rail = 0; rail < current.size(); ++rail) {
      const EdgeKey key = edge_key(current[rail], current[(rail + 1) % current.size()]);
      const auto found = edges.find(key);
      if (found == edges.end()) {
        return error_result(HairTubeStatus::kSectionCountChanged,
                            "a station edge is missing from the topology");
      }
      for (const EdgeUse& use : found->second) {
        if (!visited_faces[static_cast<std::size_t>(use.face)]) {
          next_faces[rail] = use.face;
          ++continuation_counts[rail];
        }
      }
    }

    const bool all_finished = std::all_of(continuation_counts.begin(), continuation_counts.end(),
                                          [](std::size_t count) { return count == 0; });
    if (all_finished) {
      for (std::size_t rail = 0; rail < current.size(); ++rail) {
        const EdgeKey key = edge_key(current[rail], current[(rail + 1) % current.size()]);
        if (edges.at(key).size() != 1) {
          return error_result(HairTubeStatus::kAmbiguousContinuation,
                              "tip loop is not an open boundary loop");
        }
      }
      break;
    }
    const bool one_continuation = std::all_of(
        continuation_counts.begin(), continuation_counts.end(),
        [](std::size_t count) { return count == 1; });
    if (one_continuation &&
        std::all_of(next_faces.begin() + 1, next_faces.end(),
                    [&next_faces](std::uint64_t face) { return face == next_faces[0]; }) &&
        face_matches_ring(topology, next_faces[0], current)) {
      extracted.tip_cap_face = next_faces[0];
      visited_faces[static_cast<std::size_t>(next_faces[0])] = true;
      break;
    }
    if (std::any_of(continuation_counts.begin(), continuation_counts.end(),
                    [](std::size_t count) { return count != 1; })) {
      return error_result(HairTubeStatus::kSectionCountChanged,
                          "station edges do not share one continuation each");
    }
    std::unordered_set<std::uint64_t> unique_faces(next_faces.begin(), next_faces.end());
    if (unique_faces.size() != current.size()) {
      return error_result(HairTubeStatus::kAmbiguousContinuation,
                          "a station does not continue through one unique side face per edge");
    }

    constexpr std::uint64_t kUnset = std::numeric_limits<std::uint64_t>::max();
    std::vector<std::uint64_t> next_ring(current.size(), kUnset);
    for (std::size_t rail = 0; rail < current.size(); ++rail) {
      const std::uint64_t face_id = next_faces[rail];
      const auto face = face_vertices(topology, face_id);
      if (face.size() != 4) {
        std::ostringstream message;
        message << "side face " << face_id << " is not a quad";
        return error_result(HairTubeStatus::kNonQuadFace, message.str());
      }
      std::uint32_t next_first = 0;
      std::uint32_t next_second = 0;
      if (!opposite_vertices(face, current[rail], current[(rail + 1) % current.size()], next_first,
                             next_second) ||
          !assign_next(next_ring, rail, next_first) ||
          !assign_next(next_ring, (rail + 1) % current.size(), next_second)) {
        return error_result(HairTubeStatus::kAmbiguousContinuation,
                            "quad side faces disagree about the next station");
      }
    }

    std::unordered_set<std::uint32_t> unique_next;
    std::vector<std::uint32_t> next(current.size());
    for (std::size_t rail = 0; rail < next.size(); ++rail) {
      if (next_ring[rail] == kUnset ||
          next_ring[rail] > std::numeric_limits<std::uint32_t>::max()) {
        return error_result(HairTubeStatus::kSectionCountChanged,
                            "next station does not preserve the root vertex count");
      }
      next[rail] = static_cast<std::uint32_t>(next_ring[rail]);
      if (!unique_next.insert(next[rail]).second) {
        return error_result(HairTubeStatus::kSectionCountChanged,
                            "next station changes its vertex count");
      }
      if (visited_vertices.find(next[rail]) != visited_vertices.end()) {
        return error_result(HairTubeStatus::kRingRevisited,
                            "tube traversal revisits an earlier station vertex");
      }
    }

    for (std::size_t rail = 0; rail < current.size(); ++rail) {
      visited_faces[static_cast<std::size_t>(next_faces[rail])] = true;
      extracted.side_faces.push_back(next_faces[rail]);
    }
    extracted.rings.insert(extracted.rings.end(), next.begin(), next.end());
    visited_vertices.insert(next.begin(), next.end());
    current = next;
  }

  if (std::find(visited_faces.begin(), visited_faces.end(), false) != visited_faces.end() ||
      visited_vertices.size() != topology.vertex_count) {
    return error_result(HairTubeStatus::kDisconnectedTopology,
                        "topology contains faces or vertices outside the extracted tube");
  }

  extracted.station_count = extracted.rings.size() / extracted.rail_count;
  extracted.rails.reserve(extracted.rings.size());
  for (std::size_t rail = 0; rail < extracted.rail_count; ++rail) {
    for (std::uint64_t station = 0; station < extracted.station_count; ++station) {
      extracted.rails.push_back(
          extracted.rings[static_cast<std::size_t>(station) * extracted.rail_count + rail]);
    }
  }

  HairTubeTopologyResult result;
  result.topology = std::move(extracted);
  return result;
}

}  // namespace ywta::mesh_core
