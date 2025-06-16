"""
メッシュメニュー定義

メッシュ操作関連のメニュー項目を定義します。
"""

import maya.cmds as cmds
import maya.mel as mel


def create_mesh_menu(parent_menu):
    """メッシュメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    mesh_menu = cmds.menuItem(
        subMenu=True, tearOff=True, parent=parent_menu, label="Mesh"
    )

    # 頂点ロック関連
    cmds.menuItem(
        parent=mesh_menu,
        label="Lock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.lock()",
        annotation="選択された頂点をロックします",
    )
    cmds.menuItem(
        parent=mesh_menu,
        label="Unlock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.unlock()",
        annotation="選択された頂点のロックを解除します",
    )

    # マージと自動スキニング
    cmds.menuItem(
        parent=mesh_menu,
        label="Merge Objects and Skinning",
        command="import ywta.mesh.merge_and_skin as mas; mas.merge_and_skin()",
        annotation="複数のオブジェクトをマージして階層をJoint化しBindSkinします",
    )

    return mesh_menu
