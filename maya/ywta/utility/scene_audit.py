"""Maya scene の名前衝突と危険な mesh topology を読み取り専用で監査する。"""

from __future__ import absolute_import

import json
import math

import maya.api.OpenMaya as om
import maya.cmds as cmds


ISSUE_CATEGORIES = (
    "non_manifold_vertices",
    "non_manifold_edges",
    "lamina_faces",
    "zero_area_faces",
)
_LAST_REPORT = None


def find_duplicate_short_names():
    """同じ短名を持つtransform/joint群を返す。"""
    by_name = {}
    for node in cmds.ls(type="transform", long=True) or []:
        short_name = node.rsplit("|", 1)[-1]
        by_name.setdefault(short_name, []).append(node)
    return [{"name": name, "nodes": sorted(nodes)} for name, nodes in sorted(by_name.items()) if len(nodes) > 1]


def _poly_components(shape, **query):
    """polyInfo の component range を展開したロング名へ正規化する。"""
    values = cmds.polyInfo(shape, **query) or []
    if not values:
        return []
    return sorted(set(cmds.ls(values, flatten=True, long=True) or values))


def _zero_area_faces(shape, tolerance=1.0e-12):
    """world-space面積が有限でないか閾値以下のfaceを返す。"""
    if not isinstance(tolerance, (int, float)) or isinstance(tolerance, bool) or not math.isfinite(tolerance):
        raise ValueError("zero-area toleranceは有限数にしてください。")
    if tolerance < 0.0:
        raise ValueError("zero-area toleranceは0以上にしてください。")
    selection = om.MSelectionList()
    selection.add(shape)
    iterator = om.MItMeshPolygon(selection.getDagPath(0))
    faces = []
    while not iterator.isDone():
        area = float(iterator.getArea(om.MSpace.kWorld))
        if not math.isfinite(area) or area <= tolerance:
            faces.append("{}.f[{}]".format(shape, iterator.index()))
        iterator.next()
    return faces


def audit_mesh(shape):
    """1つの mesh shape を変更せずに診断する。"""
    matches = cmds.ls(shape, type="mesh", long=True) or []
    if len(matches) != 1:
        raise ValueError("mesh shape を一意に解決できません: {}".format(shape))
    shape = matches[0]
    if cmds.getAttr(shape + ".intermediateObject"):
        raise ValueError("intermediate shape は監査対象にできません: {}".format(shape))
    return {
        "shape": shape,
        "non_manifold_vertices": _poly_components(shape, nonManifoldVertices=True),
        "non_manifold_edges": _poly_components(shape, nonManifoldEdges=True),
        "lamina_faces": _poly_components(shape, laminaFaces=True),
        "zero_area_faces": _zero_area_faces(shape),
    }


def _audit_shapes(shapes, duplicates):
    """shape列を監査し、選択可能なreportを作る。"""
    global _LAST_REPORT
    meshes = []
    errors = []
    for shape in shapes:
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        try:
            item = audit_mesh(shape)
        except (RuntimeError, ValueError) as error:
            errors.append({"shape": shape, "error": str(error)})
            continue
        if any(item[category] for category in ISSUE_CATEGORIES):
            meshes.append(item)
    issue_counts = {category: sum(len(item[category]) for item in meshes) for category in ISSUE_CATEGORIES}
    report = {
        "duplicate_short_names": duplicates,
        "errors": errors,
        "meshes": meshes,
        "summary": {
            "duplicate_name_groups": len(duplicates),
            "mesh_issue_components": sum(issue_counts.values()),
            "affected_meshes": len(meshes),
            "scan_errors": len(errors),
            **issue_counts,
        },
    }
    _LAST_REPORT = report
    return report


def audit_scene():
    """scene 全体を監査し、選択可能な report を返す。"""
    shapes = cmds.ls(type="mesh", long=True) or []
    return _audit_shapes(shapes, find_duplicate_short_names())


def _selected_mesh_shapes():
    """現在選択のtransform / shape / componentからmesh shapeを取得する。"""
    objects = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    shapes = []
    for node in objects:
        if cmds.nodeType(node) == "mesh":
            candidates = [node]
        else:
            candidates = (
                cmds.listRelatives(
                    node,
                    shapes=True,
                    fullPath=True,
                    noIntermediate=True,
                    type="mesh",
                )
                or []
            )
        shapes.extend(candidates)
    return list(dict.fromkeys(shapes))


def audit_selected_meshes():
    """選択meshだけを監査し、scene-wide名前衝突は含めない。"""
    shapes = _selected_mesh_shapes()
    if not shapes:
        raise ValueError("監査するmesh transform / shape / componentを選択してください。")
    return _audit_shapes(shapes, [])


def issue_nodes(report, categories=None, include_duplicate_names=True):
    """report から選択対象の node/component を順序保持して取り出す。"""
    if not isinstance(report, dict):
        raise ValueError("Scene Audit reportが不正です。")
    categories = ISSUE_CATEGORIES if categories is None else tuple(categories)
    unknown = set(categories) - set(ISSUE_CATEGORIES)
    if unknown:
        raise ValueError("未対応の issue category です: {}".format(", ".join(sorted(unknown))))
    values = []
    if include_duplicate_names:
        for duplicate in report.get("duplicate_short_names", []):
            values.extend(duplicate.get("nodes", []))
    for mesh in report.get("meshes", []):
        for category in categories:
            values.extend(mesh.get(category, []))
    result = []
    seen = set()
    for value in values:
        if value not in seen and cmds.objExists(value):
            seen.add(value)
            result.append(value)
    return result


def select_issues(report=None, categories=None, include_duplicate_names=True):
    """最新または明示した監査結果の問題箇所をMaya selectionに設定する。"""
    if report is None:
        report = audit_scene()
    nodes = issue_nodes(report, categories, include_duplicate_names)
    cmds.select(nodes, replace=True)
    return nodes


def format_report(report):
    """UI と Script Editor 用に安定した JSON 文字列へ整形する。"""
    return json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)


def show():
    """Scene Audit の小さな結果ウィンドウを表示する。"""
    window = "ywtaSceneAuditWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Scene Audit", widthHeight=(620, 420))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    output = cmds.scrollField(editable=False, wordWrap=False, text="Audit を実行してください。")

    def run_audit(*_args):
        report = audit_scene()
        cmds.scrollField(output, edit=True, text=format_report(report))

    def run_audit_and_select(*_args):
        report = audit_scene()
        cmds.scrollField(output, edit=True, text=format_report(report))
        return select_issues(report)

    def run_selected_audit(*_args):
        report = audit_selected_meshes()
        cmds.scrollField(output, edit=True, text=format_report(report))

    def run_selected_audit_and_select(*_args):
        report = audit_selected_meshes()
        cmds.scrollField(output, edit=True, text=format_report(report))
        return select_issues(report, include_duplicate_names=False)

    cmds.gridLayout(numberOfColumns=2, cellWidthHeight=(300, 28))
    cmds.button(label="Audit Scene", command=run_audit)
    cmds.button(label="Audit Scene + Select Issues", command=run_audit_and_select)
    cmds.button(label="Audit Selected Meshes", command=run_selected_audit)
    cmds.button(label="Audit Selected + Select Issues", command=run_selected_audit_and_select)
    cmds.setParent("..")
    cmds.showWindow(window)
    return window
