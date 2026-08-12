"""multi-shell skinned meshを元vertex mappingで非破壊分割する。"""

import maya.api.OpenMaya as om
import maya.api.OpenMayaAnim as oma
import maya.cmds as cmds

from ywta.core import undo_utils
from ywta.deform import skin_io
from ywta.deform import skin_weight_command


def _absolute_name(name):
    """namespace付き名をcurrent namespace非依存にする。"""
    return ":" + name.lstrip(":") if ":" in name else name


def _shell_plans(function):
    """mesh topologyからshellごとのface/vertex mappingを作る。"""
    face_counts, face_connects = function.getVertices()
    face_counts = list(face_counts)
    face_connects = list(face_connects)
    parents = list(range(function.numPolygons))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    vertex_face = {}
    offset = 0
    face_vertices = []
    for face_index, count in enumerate(face_counts):
        vertices = face_connects[offset : offset + count]
        offset += count
        face_vertices.append(vertices)
        for vertex in vertices:
            if vertex in vertex_face:
                union(face_index, vertex_face[vertex])
            else:
                vertex_face[vertex] = face_index

    groups = {}
    for face_index in range(function.numPolygons):
        groups.setdefault(find(face_index), []).append(face_index)

    plans = []
    for faces in sorted(groups.values(), key=lambda value: value[0]):
        vertex_map = {}
        original_vertices = []
        counts = []
        connects = []
        for face_index in faces:
            vertices = face_vertices[face_index]
            counts.append(len(vertices))
            for vertex in vertices:
                if vertex not in vertex_map:
                    vertex_map[vertex] = len(original_vertices)
                    original_vertices.append(vertex)
                connects.append(vertex_map[vertex])
        plans.append(
            {
                "faces": faces,
                "face_vertices": [face_vertices[index] for index in faces],
                "face_counts": counts,
                "face_connects": connects,
                "original_vertices": original_vertices,
                "vertex_map": vertex_map,
            }
        )
    return plans, face_counts


def _flat_offsets(counts):
    """faceごとのflat配列開始位置を返す。"""
    offsets = []
    total = 0
    for count in counts:
        offsets.append(total)
        total += count
    return offsets


def _copy_uv_sets(source, target, plan):
    """全UV setのface-vertex割当をshellへsubset転送する。"""
    target_sets = set(target.getUVSetNames())
    for uv_set in source.getUVSetNames():
        if uv_set not in target_sets:
            target.createUVSet(uv_set)
            target_sets.add(uv_set)
        u_values, v_values = source.getUVs(uv_set)
        counts, uv_ids = source.getAssignedUVs(uv_set)
        counts = list(counts)
        uv_ids = list(uv_ids)
        offsets = _flat_offsets(counts)
        piece_counts = []
        piece_ids = []
        used = []
        remap = {}
        for face_index in plan["faces"]:
            count = counts[face_index]
            piece_counts.append(count)
            for source_id in uv_ids[offsets[face_index] : offsets[face_index] + count]:
                if source_id not in remap:
                    remap[source_id] = len(used)
                    used.append(source_id)
                piece_ids.append(remap[source_id])
        target.clearUVs(uv_set)
        if used:
            target.setUVs([u_values[index] for index in used], [v_values[index] for index in used], uv_set)
            target.assignUVs(piece_counts, piece_ids, uv_set)


def _copy_normals(source, target, plan, normal_matrix):
    """world-space face-vertex normalをidentity transformのshellへ転送する。"""
    normals = []
    face_ids = []
    vertex_ids = []
    for new_face, (source_face, source_vertices) in enumerate(zip(plan["faces"], plan["face_vertices"])):
        source_normals = source.getFaceVertexNormals(source_face, om.MSpace.kObject)
        for normal, source_vertex in zip(source_normals, source_vertices):
            transformed = om.MVector(normal) * normal_matrix
            transformed.normalize()
            normals.append(transformed)
            face_ids.append(new_face)
            vertex_ids.append(plan["vertex_map"][source_vertex])
    if normals:
        target.setFaceVertexNormals(normals, face_ids, vertex_ids, om.MSpace.kObject)


def _copy_color_sets(source, target, plan, source_face_counts):
    """全color setのface-vertex値をshellへsubset転送する。"""
    source_offsets = _flat_offsets(source_face_counts)
    for color_set in source.getColorSetNames():
        representation = source.getColorRepresentation(color_set)
        created = target.createColorSet(
            color_set,
            source.isColorClamped(color_set),
            representation,
        )
        target.setCurrentColorSetName(created)
        source_colors = source.getFaceVertexColors(color_set)
        colors = []
        face_ids = []
        vertex_ids = []
        for new_face, (source_face, source_vertices) in enumerate(zip(plan["faces"], plan["face_vertices"])):
            start = source_offsets[source_face]
            for local_index, source_vertex in enumerate(source_vertices):
                colors.append(source_colors[start + local_index])
                face_ids.append(new_face)
                vertex_ids.append(plan["vertex_map"][source_vertex])
        if colors:
            target.setFaceVertexColors(colors, face_ids, vertex_ids, rep=representation)
    target.displayColors = source.displayColors


def _copy_shaders(source, target_transform, plan):
    """source faceのshadingEngine割当を新しいface番号へ転送する。"""
    shaders, assignments = source.getConnectedShaders(0)
    groups = {}
    for new_face, source_face in enumerate(plan["faces"]):
        shader_index = assignments[source_face]
        if shader_index >= 0:
            groups.setdefault(shader_index, []).append(new_face)
    for shader_index, faces in groups.items():
        shading_engine = om.MFnDependencyNode(shaders[shader_index]).name()
        components = ["{}.f[{}]".format(target_transform, face) for face in faces]
        cmds.sets(components, edit=True, forceElement=shading_engine)


def _piece_weights(data, resolved_influences, physical_influences, original_vertices):
    """source sparse rowをpieceのphysical influence順へ展開する。"""
    physical_index = {path: index for index, path in enumerate(physical_influences)}
    weights = []
    for vertex in original_vertices:
        row = [0.0] * len(physical_influences)
        for source_index, value in data["weights"][vertex]:
            row[physical_index[resolved_influences[source_index]]] = float(value)
        weights.extend(row)
    return weights


def _copy_bind_pre_matrices(source_cluster, target_cluster, influences):
    """source skinClusterのbindPreMatrixを同じinfluenceへ転送する。"""
    source_function = oma.MFnSkinCluster(skin_io._depend_node(source_cluster))
    target_function = oma.MFnSkinCluster(skin_io._depend_node(target_cluster))
    for influence in influences:
        influence_path = skin_io._dag_path(influence)
        source_index = source_function.indexForInfluenceObject(influence_path)
        target_index = target_function.indexForInfluenceObject(influence_path)
        matrix = cmds.getAttr("{}.bindPreMatrix[{}]".format(source_cluster, source_index))
        cmds.setAttr(
            "{}.bindPreMatrix[{}]".format(target_cluster, target_index),
            matrix,
            type="matrix",
        )


def separate(mesh, base_name=None):
    """skinned multi-shell meshを元mesh非破壊でshellごとに分割する。

    Args:
        mesh: 単一のskinned mesh transformまたはshape。
        base_name: 出力名prefix。省略時は ``<source>_shell``。

    Returns:
        sourceとpiece情報を含む辞書。
    """
    shape = skin_io._mesh_shape(mesh)
    source = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
    data = skin_io.capture(source)
    source_cluster = skin_io._skin_cluster(shape)
    skin_function = oma.MFnSkinCluster(skin_io._depend_node(source_cluster))
    output_index = skin_function.indexForOutputShape(skin_io._depend_node(shape))
    input_function = om.MFnMesh(skin_function.inputShapeAtIndex(output_index))
    output_function = om.MFnMesh(skin_io._dag_path(shape))
    if skin_io._topology(input_function) != skin_io._topology(output_function):
        raise ValueError("skinCluster inputとoutputのtopologyが一致しないため分割できません。")
    plans, source_face_counts = _shell_plans(input_function)
    if len(plans) < 2:
        raise ValueError("meshは1 shellだけのため分割できません: {}".format(source))
    if base_name is None:
        base_name = source.rsplit("|", 1)[-1] + "_shell"
    if not isinstance(base_name, str) or not base_name.strip() or "|" in base_name:
        raise ValueError("base_nameは空でないDAG short nameにしてください。")
    names = ["{}{:02d}".format(base_name.strip(), index + 1) for index in range(len(plans))]
    occupied = [name for name in names if cmds.objExists(_absolute_name(name))]
    if occupied:
        raise ValueError("出力名が既に存在します: {}".format(", ".join(occupied)))

    resolved_influences = skin_io._resolve_influences(data["influences"])
    source_matrix = skin_io._dag_path(shape).inclusiveMatrix()
    normal_matrix = source_matrix.inverse().transpose()
    source_points = [point * source_matrix for point in input_function.getPoints(om.MSpace.kObject)]
    original_selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Separate Skinned Mesh")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Separate Skinned Mesh")
    failed = False
    pieces = []
    try:
        for name, plan in zip(names, plans):
            transform = cmds.createNode("transform", name=_absolute_name(name))
            points = [source_points[index] for index in plan["original_vertices"]]
            om.MFnMesh().create(
                points,
                plan["face_counts"],
                plan["face_connects"],
                parent=skin_io._depend_node(transform),
            )
            transform = (cmds.ls(transform, long=True, type="transform") or [transform])[0]
            if transform.rsplit("|", 1)[-1] != name:
                raise RuntimeError("shell mesh名がMayaに変更されました: {}".format(transform))
            target_shape = skin_io._mesh_shape(transform)
            target_function = om.MFnMesh(skin_io._dag_path(target_shape))
            _copy_uv_sets(output_function, target_function, plan)
            _copy_normals(input_function, target_function, plan, normal_matrix)
            _copy_color_sets(output_function, target_function, plan, source_face_counts)
            _copy_shaders(output_function, transform, plan)

            cluster = cmds.skinCluster(
                resolved_influences,
                transform,
                toSelectedBones=True,
                normalizeWeights=1,
            )[0]
            skin_function = oma.MFnSkinCluster(skin_io._depend_node(cluster))
            physical_influences = [path.fullPathName() for path in skin_function.influenceObjects()]
            _copy_bind_pre_matrices(source_cluster, cluster, resolved_influences)
            weights = _piece_weights(
                data,
                resolved_influences,
                physical_influences,
                plan["original_vertices"],
            )
            skin_weight_command.execute(
                cluster,
                target_shape,
                range(len(plan["original_vertices"])),
                range(len(physical_influences)),
                weights,
                normalize=False,
            )
            pieces.append(
                {
                    "mesh": transform,
                    "skin_cluster": cluster,
                    "original_vertices": list(plan["original_vertices"]),
                    "original_faces": list(plan["faces"]),
                }
            )
        cmds.select([piece["mesh"] for piece in pieces], replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
            valid_selection = [item for item in original_selection if cmds.objExists(item)]
            if valid_selection:
                cmds.select(valid_selection, replace=True)
            else:
                cmds.select(clear=True)
    return {"source": source, "pieces": pieces}


def separate_selected():
    """選択された単一skinned meshを分割するメニュー入口。"""
    selected = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    meshes = []
    for item in selected:
        try:
            shape = skin_io._mesh_shape(item)
        except ValueError:
            continue
        transform = (cmds.listRelatives(shape, parent=True, fullPath=True) or [shape])[0]
        if transform not in meshes:
            meshes.append(transform)
    if len(meshes) != 1:
        raise ValueError("分割するskinned meshを1つ選択してください。")
    return separate(meshes[0])
