import maya.cmds as cmds
import ywta.deform.blendshape as blendshape
import maya.mel as mel

# 現在のメッシュのをBlendShapeターゲットに追加

def add_blendshape_target_with_frame(mesh, frame):

    # blendspageがなければ作成
    blendshape_name = blendshape.get_blendshape_node(mesh)

    # メッシュを複製して
    mesh_target = cmds.duplicate(mesh, name=f"deformer_{frame}")[0]

    # ブレンドシェイプターゲットに追加
    blendshape.add_target(blendshape_name, mesh_target)

    # 複製したshapeを削除
    cmds.delete(mesh_target)

    return mesh_target


def bake_deformed_to_blendshape():
    """
    デフォーマーで変形されたメッシュをBlendShapeターゲットに追加します。
    TimeSliderのStartからEndまでのフレームを1フレームずつ移動してベイクします。
    メッシュを選択して実行してください。
    """
    sel = cmds.ls(selection=True)

    # Check mesh selection
    if not sel:
        cmds.warning("メッシュが選択されていません。")
        return

    mesh = sel[0]
    blendshape_name = blendshape.get_blendshape_node(mesh)

    # 現在のTimeSliderのStartとEndを取得
    start_frame = cmds.playbackOptions(q=True, minTime=True)
    end_frame = cmds.playbackOptions(q=True, maxTime=True)

    for frame in range(int(start_frame), int(end_frame) + 1):
        # タイムスライダーを移動
        cmds.currentTime(frame)
        tareget_name = add_blendshape_target_with_frame(mesh, frame)
        #シェイプキーのキーフレームを追加

        mel.eval(f"setAttr {blendshape_name}.{tareget_name} 1")
        mel.eval(f"setKeyframe {blendshape_name}.{tareget_name}")
        if frame != end_frame:
            cmds.currentTime(frame+1)
            mel.eval(f"setAttr {blendshape_name}.{tareget_name} 0")
            mel.eval(f"setKeyframe {blendshape_name}.{tareget_name}")

        if frame != start_frame:
            cmds.currentTime(frame-1)
            mel.eval(f"setAttr {blendshape_name}.{tareget_name} 0")
            mel.eval(f"setKeyframe {blendshape_name}.{tareget_name}")


    print(f"フレーム{start_frame}から{end_frame}までのデフォームをBlendShapeターゲットに追加しました。")