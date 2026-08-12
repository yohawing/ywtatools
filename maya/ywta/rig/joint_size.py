"""
Joint Size Tools

ジョイントのサイズを一括で設定するためのツール
"""

import math
from typing import Optional

import maya.cmds as cmds

from ywta.core import undo_utils


def _target_joints(selected_only):
    """対象jointを階層順・重複なしのロングパスで返す。"""
    if selected_only:
        selected = cmds.ls(selection=True, type="joint", long=True) or []
        if not selected:
            return []
        joints = []
        for joint in selected:
            joints.append(joint)
            joints.extend(cmds.listRelatives(joint, allDescendents=True, type="joint", fullPath=True) or [])
    else:
        joints = cmds.ls(type="joint", long=True) or []
    return list(dict.fromkeys(joints))


def _validate_targets(joints):
    """radius変更不能なjointがあれば編集前に拒否する。"""
    for joint in joints:
        plug = joint + ".radius"
        if cmds.referenceQuery(joint, isNodeReferenced=True):
            raise ValueError("参照jointのradiusは変更できません: {}".format(joint))
        if cmds.getAttr(plug, lock=True):
            raise ValueError("radiusがlockされています: {}".format(joint))
        incoming = cmds.listConnections(plug, source=True, destination=False, plugs=True) or []
        if incoming:
            raise ValueError("radiusに入力接続があります: {}".format(joint))


def set_joint_size_hierarchy(joint_size: float = 1.0, selected_only: bool = True):
    """選択されたジョイントとその階層下のジョイントサイズを一括設定

    Args:
        joint_size: 設定するジョイントサイズ
        selected_only: Trueの場合は選択されたジョイントのみ、Falseの場合は全ジョイント
    """
    if (
        not isinstance(joint_size, (int, float))
        or isinstance(joint_size, bool)
        or not math.isfinite(joint_size)
        or joint_size <= 0.0
    ):
        raise ValueError("joint sizeは0より大きい有限値にしてください。")
    if not isinstance(selected_only, bool):
        raise ValueError("selected_onlyはboolで指定してください。")
    joints_to_process = _target_joints(selected_only)
    if not joints_to_process:
        cmds.warning("ジョイントが選択されていません。" if selected_only else "処理対象のジョイントが見つかりません。")
        return []
    _validate_targets(joints_to_process)

    undo_utils.require_enabled("Set Joint Size")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Set Joint Size")
    failed = False
    try:
        for joint in joints_to_process:
            cmds.setAttr(joint + ".radius", float(joint_size))
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    print("{}個のジョイントのサイズを{}に設定しました。".format(len(joints_to_process), joint_size))
    return joints_to_process


def get_joint_size_from_selection() -> Optional[float]:
    """選択されたジョイントのサイズを取得

    Returns:
        最初に選択されたジョイントのサイズ、選択がない場合はNone
    """
    selected = cmds.ls(selection=True, type="joint")
    if not selected:
        return None

    try:
        return cmds.getAttr(f"{selected[0]}.radius")
    except (RuntimeError, ValueError):
        return None


def show_joint_size_ui():
    """Joint Size設定UIを表示"""
    window_name = "jointSizeWindow"

    # 既存のウィンドウがあれば削除
    if cmds.window(window_name, exists=True):
        cmds.deleteUI(window_name)

    # ウィンドウを作成
    window = cmds.window(
        window_name,
        title="Joint Size Tools",
        widthHeight=(300, 150),
        resizeToFitChildren=True,
    )

    # メインレイアウト
    cmds.columnLayout(adjustableColumn=True)
    # タイトル
    cmds.text(label="Joint Size Hierarchy Tool", font="boldLabelFont")
    cmds.separator(height=10)

    # サイズ設定
    cmds.rowLayout(numberOfColumns=2, columnWidth2=(100, 150))
    cmds.text(label="Joint Size:")
    size_field = cmds.floatField(value=1.0, precision=3, minValue=0.001, maxValue=100.0)
    cmds.setParent("..")

    cmds.separator(height=10)

    # 現在の選択からサイズを取得ボタン
    cmds.button(
        label="Get Size from Selected Joint",
        command=lambda x: _update_size_field_from_selection(size_field),
        annotation="選択されたジョイントのサイズを取得してフィールドに設定します",
    )

    cmds.separator(height=10)

    # 実行ボタン
    cmds.rowLayout(numberOfColumns=2, columnWidth2=(140, 140))

    cmds.button(
        label="Set Selected Hierarchy",
        command=lambda x: _execute_joint_size_command(size_field, True),
        annotation="選択されたジョイントとその階層下のジョイントサイズを設定します",
        backgroundColor=(0.6, 0.8, 0.6),
    )

    cmds.button(
        label="Set All Joints",
        command=lambda x: _execute_joint_size_command(size_field, False),
        annotation="シーン内の全ジョイントのサイズを設定します",
        backgroundColor=(0.8, 0.6, 0.6),
    )

    cmds.setParent("..")
    cmds.separator(height=10)

    # 閉じるボタン
    cmds.button(
        label="Close",
        command=lambda x: cmds.deleteUI(window),
        annotation="ウィンドウを閉じます",
    )

    # ウィンドウを表示
    cmds.showWindow(window)


def _update_size_field_from_selection(size_field):
    """選択されたジョイントのサイズをフィールドに設定"""
    size = get_joint_size_from_selection()
    if size is not None:
        cmds.floatField(size_field, edit=True, value=size)
        print(f"選択されたジョイントのサイズ {size} をフィールドに設定しました。")
    else:
        cmds.warning("ジョイントが選択されていないか、サイズを取得できませんでした。")


def _execute_joint_size_command(size_field, selected_only):
    """ジョイントサイズ設定コマンドを実行"""
    joint_size = cmds.floatField(size_field, query=True, value=True)
    set_joint_size_hierarchy(joint_size, selected_only)


# メニューから直接呼び出される関数
def set_joint_size_from_menu():
    """メニューから呼び出される関数"""
    show_joint_size_ui()


if __name__ == "__main__":
    # テスト用
    show_joint_size_ui()
