"""
メッシュメニュー定義

メッシュ操作関連のメニュー項目を定義します。
"""

import maya.cmds as cmds


def create_mesh_menu(parent_menu):
    """メッシュメニューを作成する

    Args:
        parent_menu: 親メニュー

    Returns:
        作成されたメニュー項目
    """
    mesh_menu = cmds.menuItem(subMenu=True, tearOff=True, parent=parent_menu, label="Mesh")

    # 頂点ロック関連
    cmds.menuItem(
        parent=mesh_menu,
        label="Lock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.lock()",
        annotation="選択された頂点をロックします",
        image="componentTag_vertex.png",
    )
    cmds.menuItem(
        parent=mesh_menu,
        label="Unlock Selected Vertices",
        command="import ywta.mesh.lock_selected_vertices as lsv; lsv.unlock()",
        annotation="選択された頂点のロックを解除します",
        image="componentTag_vertex.png",
    )

    # マージと自動スキニング
    cmds.menuItem(
        parent=mesh_menu,
        label="Merge Objects and Skinning",
        command="import ywta.mesh.merge_and_skin as mas; mas.merge_and_skin()",
        annotation="複数のオブジェクトをマージして階層をJoint化しBindSkinします",
        image="menuIconSkinning.png",
    )

    # AutoRemesher
    cmds.menuItem(
        parent=mesh_menu,
        label="AutoRemesher Node",
        command="import ywta.mesh.autoremesher as ar; ar.show_options()",
        annotation="パラメータを指定してAutoRemesherノードを作成します（別オブジェクトに出力）",
        image="out_mesh.png",
    )

    cmds.menuItem(
        parent=mesh_menu,
        label="Hair Tube Curve Cage...",
        command="import ywta.mesh.hair_tube as ht; ht.show_options()",
        annotation="選択した3辺以上のroot loopから編集可能なCurve Cageと別meshを生成します",
        image="menuIconCurves.png",
    )
    cmds.menuItem(
        parent=mesh_menu,
        label="Mesh Diagnostics...",
        command="import ywta.mesh.mesh_diagnostics as md; md.show_options()",
        annotation="zero-area、重複、non-manifold、winding、bow-tie、boundaryを分類して選択します",
        image="out_mesh.png",
    )

    # Rust Volume Preserving Smoothing（ブラシは別実装）
    cmds.menuItem(
        parent=mesh_menu,
        label="Volume Preserving Smoothing",
        command="import ywta.mesh.volume_smoothing as vs; vs.smooth_selected_mesh()",
        annotation="選択メッシュをHC方式でスムージングし、閉メッシュの体積を補正します",
        image="modifySmooth.png",
    )
    cmds.menuItem(
        parent=mesh_menu,
        label="Volume Smooth Brush",
        command="import ywta.mesh.volume_smoothing as vs; vs.activate_volume_smooth_brush()",
        annotation="ビューポート上をドラッグして局所スムージングします（半径はobject-space）",
        image="brushSmooth.png",
    )

    return mesh_menu
