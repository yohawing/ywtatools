"""髪チューブ入力contractのread-only診断器。

GLBはglTFのprimitive modeとaccessor metadataを読み、元ファイルへ書き込まずに
診断する。glTFのtriangle primitiveからquadを推測することはしない。in-memoryの
``MeshData``には、Phase 0のcontract gateを適用できる。
"""

from __future__ import annotations

import argparse
import json
import struct
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


GLB_MAGIC = b"glTF"
JSON_CHUNK_TYPE = 0x4E4F534A
TRIANGLE_MODES = {4, 5, 6}
MODE_NAMES = {
    0: "POINTS",
    1: "LINES",
    2: "LINE_LOOP",
    3: "LINE_STRIP",
    4: "TRIANGLES",
    5: "TRIANGLE_STRIP",
    6: "TRIANGLE_FAN",
}


@dataclass(frozen=True)
class MeshData:
    """トポロジー診断へ渡すDCC非依存のflat mesh。"""

    name: str
    faces: tuple[tuple[int, ...], ...]
    vertex_count: int | None = None


@dataclass(frozen=True)
class TopologyReport:
    """quad tube contractの観測結果。"""

    name: str
    status: str
    is_quad_tube: bool
    vertex_count: int
    face_count: int
    quad_face_count: int
    non_quad_face_count: int
    boundary_edge_count: int
    boundary_loop_lengths: tuple[int, ...]
    pole_vertex_count: int
    root_loop_count: int | None
    tip_loop_count: int | None
    station_count: int | None
    cap_count: int | None
    section_count_change: bool | None
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class GlbPrimitiveSummary:
    """GLB primitiveのmetadataだけを保持した要約。"""

    mesh_index: int
    mesh_name: str
    node_names: tuple[str, ...]
    material_name: str | None
    mode: int
    mode_name: str
    source_face_arity: int | None
    vertex_count: int | None
    index_count: int | None
    face_count: int | None
    hair_semantics_found: bool


def _edge_key(first: int, second: int) -> tuple[int, int]:
    """無向edgeのcanonical keyを返す。"""

    return (first, second) if first < second else (second, first)


def _face_components(edge_faces: dict[tuple[int, int], list[int]], face_count: int) -> int:
    """shared edgeを介したface component数を返す。"""

    adjacency: list[set[int]] = [set() for _ in range(face_count)]
    for incident_faces in edge_faces.values():
        for index, first in enumerate(incident_faces):
            adjacency[first].update(incident_faces[index + 1 :])
            for second in incident_faces[index + 1 :]:
                adjacency[second].add(first)

    visited: set[int] = set()
    components = 0
    for start in range(face_count):
        if start in visited:
            continue
        components += 1
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
    return components


def _boundary_loops(
    edge_faces: dict[tuple[int, int], list[int]],
) -> tuple[tuple[tuple[int, ...], ...], bool]:
    """boundary edge graphからcycleの順序とbranch有無を返す。"""

    graph: dict[int, set[int]] = defaultdict(set)
    for (first, second), incident_faces in edge_faces.items():
        if len(incident_faces) == 1:
            graph[first].add(second)
            graph[second].add(first)

    loops: list[tuple[int, ...]] = []
    visited: set[int] = set()
    has_branch = False
    for start in sorted(graph):
        if start in visited:
            continue
        component: set[int] = set()
        queue = deque([start])
        visited.add(start)
        while queue:
            current = queue.popleft()
            component.add(current)
            for neighbor in graph[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)

        if any(len(graph[vertex]) != 2 for vertex in component):
            has_branch = True
            loops.append(tuple(sorted(component)))
            continue

        ordered: list[int] = []
        previous: int | None = None
        current = min(component)
        while True:
            ordered.append(current)
            candidates = sorted(graph[current] - ({previous} if previous is not None else set()))
            next_vertex = candidates[0]
            if next_vertex == ordered[0]:
                break
            if next_vertex in ordered or len(ordered) > len(component):
                has_branch = True
                break
            previous, current = current, next_vertex
        loops.append(tuple(ordered))
    return tuple(loops), has_branch


def _build_topology(
    mesh: MeshData,
) -> tuple[
    int,
    dict[tuple[int, int], list[int]],
    list[set[int]],
    tuple[tuple[int, ...], ...],
    bool,
    int,
    tuple[str, ...],
]:
    """edge table、boundary、pole、validation issueを構築する。"""

    inferred_vertex_count = max((vertex for face in mesh.faces for vertex in face), default=-1) + 1
    vertex_count = mesh.vertex_count if mesh.vertex_count is not None else inferred_vertex_count
    issues: list[str] = []
    edge_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
    neighbors: list[set[int]] = [set() for _ in range(max(vertex_count, 0))]

    if vertex_count < 0:
        issues.append("INVALID_VERTEX_COUNT")
        vertex_count = 0

    for face_index, face in enumerate(mesh.faces):
        if len(face) < 3 or len(set(face)) != len(face):
            issues.append("INVALID_FACE")
            continue
        if any(vertex < 0 or vertex >= vertex_count for vertex in face):
            issues.append("VERTEX_INDEX_OUT_OF_RANGE")
            continue
        for offset, first in enumerate(face):
            second = face[(offset + 1) % len(face)]
            key = _edge_key(first, second)
            edge_faces[key].append(face_index)
            neighbors[first].add(second)
            neighbors[second].add(first)

    boundary_loops, has_boundary_branch = _boundary_loops(edge_faces)
    if has_boundary_branch:
        issues.append("BOUNDARY_BRANCH")
    boundary_edge_count = sum(len(faces) == 1 for faces in edge_faces.values())
    pole_vertex_count = sum(degree not in (3, 4) for degree in (len(neighbor_set) for neighbor_set in neighbors) if degree > 0)
    if pole_vertex_count:
        issues.append("POLE_VERTEX")
    return (
        vertex_count,
        edge_faces,
        neighbors,
        boundary_loops,
        has_boundary_branch,
        boundary_edge_count,
        tuple(dict.fromkeys(issues)),
    )


def _ring_sequence(
    root: tuple[int, ...],
    tip: tuple[int, ...],
    neighbors: list[set[int]],
    used_vertices: set[int],
) -> tuple[tuple[int, ...], ...] | None:
    """root boundary loopから4頂点ring列を保守的に辿る。"""

    if len(root) != 4 or len(tip) != 4:
        return None
    rings: list[tuple[int, ...]] = [root]
    previous: set[int] = set()
    current = root
    while set(current) != set(tip):
        current_set = set(current)
        next_ring = tuple(
            next(iter(neighbors[vertex] - current_set - previous), -1)
            if len(neighbors[vertex] - current_set - previous) == 1
            else -1
            for vertex in current
        )
        if -1 in next_ring or len(set(next_ring)) != 4:
            return None
        if set(next_ring) in (set(ring) for ring in rings):
            return None
        next_edges = all(next_ring[offset] in neighbors[next_ring[(offset + 1) % 4]] for offset in range(4))
        reverse_edges = all(next_ring[offset] in neighbors[next_ring[(offset - 1) % 4]] for offset in range(4))
        if not next_edges and not reverse_edges:
            return None
        rings.append(next_ring)
        previous = current_set
        current = next_ring
        if len(rings) > len(used_vertices) // 2 + 1:
            return None
    if set(vertex for ring in rings for vertex in ring) != used_vertices:
        return None
    return tuple(rings)


def _has_expected_side_faces(
    faces: Sequence[tuple[int, ...]],
    rings: Sequence[tuple[int, ...]],
) -> bool:
    """隣接ringごとに4つのquad side faceだけがあることを確認する。"""

    expected_faces: set[int] = set()
    for first_ring, second_ring in zip(rings, rings[1:]):
        first_set = set(first_ring)
        second_set = set(second_ring)
        side_faces = [
            index
            for index, face in enumerate(faces)
            if len(face) == 4
            and len(set(face) & first_set) == 2
            and len(set(face) & second_set) == 2
            and set(face) <= first_set | second_set
        ]
        if len(side_faces) != 4:
            return False
        expected_faces.update(side_faces)
    return len(expected_faces) == len(faces)


def probe_mesh(mesh: MeshData) -> TopologyReport:
    """単一meshへ4-sided quad tubeのcontract gateを適用する。

    root loopを自動修復せず、boundary graphから一意に証明できる場合だけ採用する。
    """

    faces = mesh.faces
    vertex_count, edge_faces, neighbors, boundary_loops, boundary_branch, boundary_edge_count, issues = _build_topology(mesh)
    quad_face_count = sum(len(face) == 4 for face in faces)
    non_quad_face_count = len(faces) - quad_face_count
    mutable_issues = list(issues)
    if non_quad_face_count:
        mutable_issues.append("NON_QUAD_FACE")
    if _face_components(edge_faces, len(faces)) > 1 and faces:
        mutable_issues.append("DISCONNECTED_FACE_COMPONENTS")

    used_vertices = {vertex for face in faces for vertex in face}
    section_count_change: bool | None = None
    if boundary_loops and any(len(loop) != 4 for loop in boundary_loops):
        section_count_change = True
        mutable_issues.append("SECTION_COUNT_CHANGE_OR_AMBIGUOUS")

    root_loop_count: int | None = None
    tip_loop_count: int | None = None
    station_count: int | None = None
    cap_count: int | None = None
    is_quad_tube = False

    if not faces:
        mutable_issues.append("EMPTY_MESH")
    elif not non_quad_face_count and not boundary_branch and _face_components(edge_faces, len(faces)) == 1:
        if len(boundary_loops) == 2 and all(len(loop) == 4 for loop in boundary_loops):
            rings = _ring_sequence(boundary_loops[0], boundary_loops[1], neighbors, used_vertices)
            if rings is not None and _has_expected_side_faces(faces, rings):
                is_quad_tube = True
                root_loop_count = 1
                tip_loop_count = 1
                station_count = len(rings)
                cap_count = 0
            else:
                mutable_issues.append("ROOT_TIP_NOT_PROVABLE")
                section_count_change = True if section_count_change is None else section_count_change
                mutable_issues.append("SECTION_COUNT_CHANGE_OR_AMBIGUOUS")
        elif not boundary_loops:
            edge_count = len(edge_faces)
            euler_characteristic = len(used_vertices) - edge_count + len(faces)
            all_regular = all(len(neighbor_set) in (3, 4) for neighbor_set in neighbors if neighbor_set)
            if (
                len(used_vertices) >= 8
                and len(used_vertices) % 4 == 0
                and len(faces) == 4 * (len(used_vertices) // 4 - 1) + 2
                and euler_characteristic == 2
                and all_regular
            ):
                is_quad_tube = True
                root_loop_count = 1
                tip_loop_count = 1
                station_count = len(used_vertices) // 4
                cap_count = 2
            else:
                mutable_issues.append("CAP_OR_ROOT_TIP_NOT_PROVABLE")
        else:
            mutable_issues.append("BOUNDARY_LOOP_NOT_TWO")

    if non_quad_face_count:
        root_loop_count = tip_loop_count = station_count = cap_count = None
    if not is_quad_tube and section_count_change is None and quad_face_count == len(faces) and faces:
        section_count_change = False

    if is_quad_tube:
        status = "accepted"
        reason_codes = tuple(dict.fromkeys(mutable_issues))
    else:
        status = "gated"
        reason_codes = tuple(dict.fromkeys(mutable_issues)) or ("CONTRACT_NOT_PROVABLE",)
    return TopologyReport(
        name=mesh.name,
        status=status,
        is_quad_tube=is_quad_tube,
        vertex_count=vertex_count,
        face_count=len(faces),
        quad_face_count=quad_face_count,
        non_quad_face_count=non_quad_face_count,
        boundary_edge_count=boundary_edge_count,
        boundary_loop_lengths=tuple(len(loop) for loop in boundary_loops),
        pole_vertex_count=sum(
            degree not in (3, 4) for degree in (len(neighbor_set) for neighbor_set in neighbors) if degree > 0
        ),
        root_loop_count=root_loop_count,
        tip_loop_count=tip_loop_count,
        station_count=station_count,
        cap_count=cap_count,
        section_count_change=section_count_change,
        reason_codes=reason_codes,
    )


def _load_glb_json(path: Path) -> dict[str, Any]:
    """GLBのJSON chunkだけを解釈し、BIN chunkは解釈しない。"""

    raw = path.read_bytes()
    if len(raw) < 12:
        raise ValueError("GLB header is truncated")
    magic, version, total_length = struct.unpack_from("<4sII", raw, 0)
    if magic != GLB_MAGIC or version != 2:
        raise ValueError("unsupported GLB header")
    if total_length > len(raw):
        raise ValueError("GLB declares a length beyond the file")
    offset = 12
    while offset + 8 <= total_length:
        chunk_length, chunk_type = struct.unpack_from("<II", raw, offset)
        chunk_start = offset + 8
        chunk_end = chunk_start + chunk_length
        if chunk_end > total_length:
            raise ValueError("GLB chunk exceeds declared length")
        if chunk_type == JSON_CHUNK_TYPE:
            return json.loads(raw[chunk_start:chunk_end].decode("utf-8").rstrip(" \t\r\n\x00"))
        offset = chunk_end
    raise ValueError("GLB JSON chunk is missing")


def _accessor_count(doc: dict[str, Any], accessor_index: int | None) -> int | None:
    """accessor countを安全に取得する。"""

    if accessor_index is None:
        return None
    accessors = doc.get("accessors", [])
    if accessor_index < 0 or accessor_index >= len(accessors):
        return None
    count = accessors[accessor_index].get("count")
    return count if isinstance(count, int) else None


def _hair_semantics(text: Iterable[str | None]) -> bool:
    """名前だけから髪関連semanticが明示されているかを判定する。"""

    tokens = ("hair", "髪", "fringe", "bang", "ponytail", "kami")
    return any(any(token in (value or "").casefold() for token in tokens) for value in text)


def inspect_glb(path: str | Path, *, hair_asset_selected: bool = True) -> dict[str, Any]:
    """GLBをread-onlyで走査し、髪tube contractの証拠を返す。"""

    source = Path(path)
    doc = _load_glb_json(source)
    materials = doc.get("materials", [])
    meshes = doc.get("meshes", [])
    nodes = doc.get("nodes", [])
    node_names_by_mesh: dict[int, list[str]] = defaultdict(list)
    for node in nodes:
        mesh_index = node.get("mesh")
        if isinstance(mesh_index, int):
            node_names_by_mesh[mesh_index].append(str(node.get("name") or ""))

    primitive_summaries: list[GlbPrimitiveSummary] = []
    for mesh_index, mesh in enumerate(meshes):
        mesh_name = str(mesh.get("name") or f"mesh_{mesh_index}")
        for primitive in mesh.get("primitives", []):
            mode = primitive.get("mode", 4)
            if not isinstance(mode, int):
                mode = 4
            attributes = primitive.get("attributes", {})
            position_index = attributes.get("POSITION") if isinstance(attributes, dict) else None
            indices_index = primitive.get("indices")
            vertex_count = _accessor_count(doc, position_index if isinstance(position_index, int) else None)
            index_count = _accessor_count(doc, indices_index if isinstance(indices_index, int) else None)
            if index_count is None:
                index_count = vertex_count
            if mode == 4:
                face_count = index_count // 3 if index_count is not None else None
                face_arity = 3
            elif mode in (5, 6):
                face_count = max(0, index_count - 2) if index_count is not None else None
                face_arity = 3
            else:
                face_count = 0
                face_arity = None
            material_index = primitive.get("material")
            material_name = None
            if isinstance(material_index, int) and 0 <= material_index < len(materials):
                material_name = str(materials[material_index].get("name") or "") or None
            node_names = tuple(node_names_by_mesh.get(mesh_index, []))
            semantics = (mesh_name, material_name, *node_names)
            primitive_summaries.append(
                GlbPrimitiveSummary(
                    mesh_index=mesh_index,
                    mesh_name=mesh_name,
                    node_names=node_names,
                    material_name=material_name,
                    mode=mode,
                    mode_name=MODE_NAMES.get(mode, f"UNKNOWN_{mode}"),
                    source_face_arity=face_arity,
                    vertex_count=vertex_count,
                    index_count=index_count,
                    face_count=face_count,
                    hair_semantics_found=_hair_semantics(semantics),
                )
            )

    named_hair_primitives = sum(summary.hair_semantics_found for summary in primitive_summaries)
    selected_candidates = 1 if hair_asset_selected else 0
    proven_candidates = sum(summary.hair_semantics_found and summary.source_face_arity == 4 for summary in primitive_summaries)
    reason_codes: list[str] = []
    if hair_asset_selected and not named_hair_primitives:
        reason_codes.append("HAIR_COMPONENT_NOT_SEPARABLE")
    if any(summary.source_face_arity == 3 for summary in primitive_summaries):
        reason_codes.extend(("TRIANGULATED_INPUT", "NON_QUAD_FACE"))
    if selected_candidates and not proven_candidates:
        reason_codes.extend(
            (
                "ROOT_TIP_NOT_EVALUATED",
                "CAP_NOT_EVALUATED",
                "POLE_NOT_EVALUATED",
                "SECTION_COUNT_NOT_EVALUATED",
            )
        )
    return {
        "asset": source.name,
        "source": str(source),
        "bytes": source.stat().st_size,
        "mesh_count": len(meshes),
        "node_count": len(nodes),
        "material_count": len(materials),
        "hair_asset_selected": hair_asset_selected,
        "hair_semantics_found": bool(named_hair_primitives),
        "selected_hair_candidate_count": selected_candidates,
        "proven_quad_tube_candidate_count": proven_candidates,
        "primitive_count": len(primitive_summaries),
        "primitives": [asdict(summary) for summary in primitive_summaries],
        "contract": {
            "four_sided_quad_tube": proven_candidates > 0,
            "root_tip": "not_evaluated",
            "cap": "not_evaluated",
            "pole": "not_evaluated",
            "section_count_change": "not_evaluated",
        },
        "reason_codes": tuple(dict.fromkeys(reason_codes)),
    }


def inspect_assets(paths: Sequence[str | Path]) -> dict[str, Any]:
    """複数GLBを順序を保って走査し、aggregate比率を返す。"""

    assets = [inspect_glb(path) for path in paths]
    selected_count = sum(asset["selected_hair_candidate_count"] for asset in assets)
    proven_count = sum(asset["proven_quad_tube_candidate_count"] for asset in assets)
    return {
        "probe": "HAIR-TUBE-PROBE-1",
        "read_only": True,
        "asset_count": len(assets),
        "selected_hair_candidate_count": selected_count,
        "proven_quad_tube_candidate_count": proven_count,
        "proven_quad_tube_ratio": (proven_count / selected_count) if selected_count else None,
        "assets": assets,
    }


def _parse_args() -> argparse.Namespace:
    """CLI引数を解釈する。"""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="read-onlyで走査するGLB")
    return parser.parse_args()


def main() -> int:
    """GLB診断JSONをstdoutへ出力する。"""

    args = _parse_args()
    try:
        result = inspect_assets(args.paths)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"probe failed: {error}")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
