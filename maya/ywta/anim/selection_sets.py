"""Pose address で namespace を跨げる Maya control selection sets。"""

from __future__ import absolute_import

import json
import os
import tempfile

import maya.cmds as cmds

from ywta.anim import pose_io
from ywta.core import undo_utils


FORMAT = "ywta.selection_sets"
VERSION = 1
MARKER_ATTRIBUTE = "ywtaSelectionSet"
LABEL_ATTRIBUTE = "ywtaSelectionSetLabel"


def _is_selection_set(node):
    """node が YWTA selection set か判定する。"""
    marker = "{}.{}".format(node, MARKER_ATTRIBUTE)
    return cmds.nodeType(node) == "objectSet" and cmds.objExists(marker) and bool(cmds.getAttr(marker))


def _label(node):
    """selection set の表示名を取得する。"""
    plug = "{}.{}".format(node, LABEL_ATTRIBUTE)
    if not cmds.objExists(plug):
        raise ValueError("selection set label がありません: {}".format(node))
    return cmds.getAttr(plug)


def list_selection_sets():
    """YWTA selection sets を label 順で返す。"""
    sets = [node for node in cmds.ls(type="objectSet") or [] if _is_selection_set(node)]
    return sorted(sets, key=lambda node: (_label(node).casefold(), node))


def _validate_label(label):
    """user-facing label を検証・正規化する。"""
    if not isinstance(label, str) or not label.strip():
        raise ValueError("selection set label が空です。")
    return label.strip()


def _resolve_members(nodes=None):
    """control members を transform/joint の一意なロング名へ解決する。"""
    members = pose_io.resolve_controls(nodes)
    invalid = [member for member in members if cmds.nodeType(member) not in {"transform", "joint"}]
    if invalid:
        raise ValueError("control 以外は登録できません: {}".format(", ".join(invalid)))
    return members


def _create_unchecked(label, members):
    """検証済み label/members から tagged objectSet を作る。"""
    node = cmds.sets(members, name="ywtaSelectionSet#")
    cmds.addAttr(node, longName=MARKER_ATTRIBUTE, attributeType="bool")
    cmds.setAttr("{}.{}".format(node, MARKER_ATTRIBUTE), True)
    cmds.addAttr(node, longName=LABEL_ATTRIBUTE, dataType="string")
    cmds.setAttr("{}.{}".format(node, LABEL_ATTRIBUTE), label, type="string")
    return node


def create_selection_set(label, nodes=None):
    """現在選択または指定 control から1つの selection set を作る。"""
    label = _validate_label(label)
    members = _resolve_members(nodes)
    if any(_label(node).casefold() == label.casefold() for node in list_selection_sets()):
        raise ValueError("同名 selection set が既にあります: {}".format(label))
    undo_utils.require_enabled("Create Selection Set")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Create Selection Set")
    failed = False
    try:
        node = _create_unchecked(label, members)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return node


def members(selection_set):
    """selection set members をロング名で返す。"""
    matches = cmds.ls(selection_set, type="objectSet") or []
    if len(matches) != 1 or not _is_selection_set(matches[0]):
        raise ValueError("YWTA selection set ではありません: {}".format(selection_set))
    return cmds.ls(cmds.sets(matches[0], query=True) or [], long=True) or []


def select_members(selection_set):
    """selection set members を Maya selection に設定する。"""
    values = members(selection_set)
    cmds.select(values, replace=True)
    return values


def delete_selection_set(selection_set):
    """tagged objectSet だけを削除する。"""
    matches = cmds.ls(selection_set, type="objectSet") or []
    if len(matches) != 1 or not _is_selection_set(matches[0]):
        raise ValueError("YWTA selection set ではありません: {}".format(selection_set))
    undo_utils.require_enabled("Delete Selection Set")
    cmds.delete(matches[0])


def capture(selection_sets=None):
    """selection sets を portable address JSON 辞書へ変換する。"""
    sets = list_selection_sets() if selection_sets is None else list(selection_sets)
    if not sets:
        raise ValueError("保存する selection set がありません。")
    entries = []
    labels = set()
    for node in sets:
        if not _is_selection_set(node):
            raise ValueError("YWTA selection set ではありません: {}".format(node))
        label = _label(node)
        folded = label.casefold()
        if folded in labels:
            raise ValueError("selection set label が重複しています: {}".format(label))
        labels.add(folded)
        addresses = []
        seen = set()
        for member in members(node):
            address = pose_io.control_address(member)
            if address in seen:
                raise ValueError("set 内の control address が重複しています: {}".format(address))
            seen.add(address)
            addresses.append(address)
        if not addresses:
            raise ValueError("空の selection set は保存できません: {}".format(label))
        entries.append({"label": label, "members": addresses})
    return {"format": FORMAT, "version": VERSION, "sets": entries}


def _validate(data):
    """外部 selection set JSON を scene 編集前に完全検証する。"""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ValueError("YWTA Selection Sets ファイルではありません。")
    if data.get("version") != VERSION:
        raise ValueError("未対応の Selection Sets version です: {}".format(data.get("version")))
    entries = data.get("sets")
    if not isinstance(entries, list) or not entries:
        raise ValueError("sets がありません。")
    labels = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("selection set entry が不正です。")
        label = _validate_label(entry.get("label"))
        if label.casefold() in labels:
            raise ValueError("selection set label が重複しています: {}".format(label))
        labels.add(label.casefold())
        addresses = entry.get("members")
        if not isinstance(addresses, list) or not addresses:
            raise ValueError("selection set members がありません: {}".format(label))
        seen = set()
        for address in addresses:
            if not isinstance(address, str) or not address.startswith(("id:", "name:")) or address in seen:
                raise ValueError("control address が不正または重複しています: {}".format(address))
            seen.add(address)
    return data


def save(file_path, selection_sets=None):
    """selection sets を JSON へ原子的に保存する。"""
    data = capture(selection_sets)
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先ディレクトリがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=directory, prefix=".ywta_sets_", suffix=".tmp", delete=False
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, target)
    except Exception:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return target


def read(file_path):
    """Selection Sets JSON を読み込み、検証済み辞書を返す。"""
    with open(file_path, "r", encoding="utf-8") as handle:
        return _validate(json.load(handle))


def apply(data):
    """portable selection sets を現在 scene の control へ解決して作成する。"""
    data = _validate(data)
    existing_labels = {_label(node).casefold() for node in list_selection_sets()}
    incoming_labels = {entry["label"].casefold() for entry in data["sets"]}
    conflicts = existing_labels & incoming_labels
    if conflicts:
        raise ValueError("同名 selection set が既にあります: {}".format(", ".join(sorted(conflicts))))
    index, ambiguous = pose_io.target_index()
    plans = []
    skipped = []
    for entry in data["sets"]:
        resolved = []
        for address in entry["members"]:
            if address in ambiguous:
                raise ValueError("target control address が曖昧です: {}".format(address))
            node = index.get(address)
            if node is None:
                skipped.append({"label": entry["label"], "address": address, "reason": "target_missing"})
            else:
                resolved.append(node)
        if resolved:
            plans.append((entry["label"], resolved))
        else:
            skipped.append({"label": entry["label"], "reason": "empty_after_resolve"})

    undo_utils.require_enabled("Import Selection Sets")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Import Selection Sets")
    failed = False
    created = []
    try:
        for label, resolved in plans:
            created.append(_create_unchecked(label, resolved))
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return {"created": created, "skipped": skipped}


def export_dialog():
    """全 YWTA selection sets をダイアログで保存する。"""
    paths = cmds.fileDialog2(
        fileMode=0,
        dialogStyle=2,
        caption="Export Selection Sets",
        fileFilter="JSON (*.json)",
    )
    if not paths:
        return None
    return save(paths[0])


def import_dialog():
    """Selection Sets JSON をダイアログで読み込む。"""
    paths = cmds.fileDialog2(
        fileMode=1,
        dialogStyle=2,
        caption="Import Selection Sets",
        fileFilter="JSON (*.json)",
    )
    if not paths:
        return None
    return apply(read(paths[0]))


def show():
    """Selection Sets 管理ウィンドウを表示する。"""
    window = "ywtaSelectionSetsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Selection Sets", widthHeight=(380, 420))
    cmds.columnLayout(adjustableColumn=True, rowSpacing=6)
    list_control = cmds.textScrollList(allowMultiSelection=False)

    def refresh(*_args):
        cmds.textScrollList(list_control, edit=True, removeAll=True)
        for node in list_selection_sets():
            cmds.textScrollList(
                list_control,
                edit=True,
                append="{} | {}".format(_label(node), node),
            )

    def selected_node():
        values = cmds.textScrollList(list_control, query=True, selectItem=True) or []
        if not values:
            raise ValueError("selection set を選択してください。")
        return values[0].rsplit(" | ", 1)[-1]

    def create_from_selection(*_args):
        result = cmds.promptDialog(
            title="Create Selection Set",
            message="Label:",
            button=["Create", "Cancel"],
            defaultButton="Create",
            cancelButton="Cancel",
            dismissString="Cancel",
        )
        if result == "Create":
            create_selection_set(cmds.promptDialog(query=True, text=True))
            refresh()

    cmds.button(label="Create from Selection", command=create_from_selection)
    cmds.button(label="Select Members", command=lambda *_: select_members(selected_node()))
    cmds.button(
        label="Delete Set",
        command=lambda *_: (delete_selection_set(selected_node()), refresh()),
    )
    cmds.rowLayout(numberOfColumns=2, adjustableColumn=1)
    cmds.button(label="Export All", command=lambda *_: export_dialog())
    cmds.button(label="Import", command=lambda *_: (import_dialog(), refresh()))
    cmds.setParent("..")
    refresh()
    cmds.showWindow(window)
    return window
