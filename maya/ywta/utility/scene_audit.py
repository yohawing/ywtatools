"""Maya scene の名前衝突と危険な mesh topology を読み取り専用で監査する。"""

from __future__ import absolute_import

import json

import maya.cmds as cmds


ISSUE_CATEGORIES = (
    "non_manifold_vertices",
    "non_manifold_edges",
    "lamina_faces",
)
_LAST_REPORT = None


def find_duplicate_short_names():
    """同じ短名を持つ DAG node 群を返す。"""
    by_name = {}
    for node in cmds.ls(dagObjects=True, long=True) or []:
        short_name = node.rsplit("|", 1)[-1]
        by_name.setdefault(short_name, []).append(node)
    return [{"name": name, "nodes": sorted(nodes)} for name, nodes in sorted(by_name.items()) if len(nodes) > 1]


def _poly_components(shape, **query):
    """polyInfo の component range を展開したロング名へ正規化する。"""
    values = cmds.polyInfo(shape, **query) or []
    if not values:
        return []
    return sorted(set(cmds.ls(values, flatten=True, long=True) or values))


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
    }


def audit_scene():
    """scene 全体を監査し、選択可能な report を返す。"""
    global _LAST_REPORT
    meshes = []
    errors = []
    for shape in cmds.ls(type="mesh", long=True) or []:
        if cmds.getAttr(shape + ".intermediateObject"):
            continue
        try:
            item = audit_mesh(shape)
        except (RuntimeError, ValueError) as error:
            errors.append({"shape": shape, "error": str(error)})
            continue
        if any(item[category] for category in ISSUE_CATEGORIES):
            meshes.append(item)
    duplicates = find_duplicate_short_names()
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


def issue_nodes(report, categories=None, include_duplicate_names=True):
    """report から選択対象の node/component を順序保持して取り出す。"""
    categories = tuple(categories or ISSUE_CATEGORIES)
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
    """監査結果に含まれる問題箇所を Maya selection に設定する。"""
    report = report or _LAST_REPORT
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

    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1)
    cmds.button(label="Audit", command=run_audit)
    cmds.button(label="Select Issues", command=lambda *_: select_issues())
    cmds.setParent("..")
    cmds.showWindow(window)
    return window
