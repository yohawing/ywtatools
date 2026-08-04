"""
Joint Size Tools

ジョイントのサイズを一括で設定するためのツール
"""

import maya.cmds as cmds
from typing import Optional


def set_joint_size_hierarchy(joint_size: float = 1.0, selected_only: bool = True) -> None:
    """選択されたジョイントとその階層下のジョイントサイズを一括設定

    Args:
        joint_size: 設定するジョイントサイズ
        selected_only: Trueの場合は選択されたジョイントのみ、Falseの場合は全ジョイント
    """
    if selected_only:
        selected = cmds.ls(selection=True, type="joint")
        if not selected:
            cmds.warning("ジョイントが選択されていません。")
            return

        # 選択されたジョイントとその階層下のジョイントを取得
        joints_to_process = []
        for joint in selected:
            joints_to_process.append(joint)
            # 階層下のジョイントを取得
            children = cmds.listRelatives(joint, allDescendents=True, type="joint") or []
            joints_to_process.extend(children)
    else:
        # シーン内の全ジョイントを取得
        joints_to_process = cmds.ls(type="joint")

    if not joints_to_process:
        cmds.warning("処理対象のジョイントが見つかりません。")
        return

    # 重複を除去
    joints_to_process = list(set(joints_to_process))

    # ジョイントサイズを設定
    for joint in joints_to_process:
        try:
            cmds.setAttr(f"{joint}.radius", joint_size)
        except Exception as e:
            cmds.warning(f"ジョイント '{joint}' のサイズ設定に失敗しました: {str(e)}")

    print(f"{len(joints_to_process)}個のジョイントのサイズを{joint_size}に設定しました。")


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
    except:
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
    # main_layout = cmds.columnLayout(adjustableColumn=True, margin=10)
    main_layout = cmds.columnLayout(adjustableColumn=True)
    # タイトル
    cmds.text(label="Joint Size Hierarchy Tool", font="boldLabelFont")
    cmds.separator(height=10)

    # サイズ設定
    size_layout = cmds.rowLayout(numberOfColumns=2, columnWidth2=(100, 150))
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
    button_layout = cmds.rowLayout(numberOfColumns=2, columnWidth2=(140, 140))

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
