import functools
import maya.cmds as cmds
import maya.mel as mel
import math as math
import ywta.deform.skinio as skinio


def reset_bindpose():
    nodeList = cmds.ls(typ='joint')
    nodeList = cmds.ls(typ='dagPose')
    for node in nodeList:
        cmds.delete(node)
    bindpose = cmds.dagPose(bp=True, save=True)
    print("reset bindpose: ", bindpose)

def duplicate_skinned_mesh():
    # 選択されたメッシュを取得
    selected_meshes = cmds.ls(selection=True, type="transform")
    if not selected_meshes:
        cmds.warning("メッシュが選択されていません。")
        return

    # 選択されたメッシュに対して処理
    mesh = selected_meshes[0]
    # スキンクラスタを取得
    skin_clusters = skinio.get_skin_clusters(mesh)
    if not skin_clusters:
        cmds.warning("スキンクラスタが見つかりません。")
        return
    skin_cluster = skin_clusters[0]
    maxInfluence = cmds.skinCluster(mesh,q=True,mi=True)
    obayMI = cmds.skinCluster(mesh,q=True,omi=True)
    # スキンクラスタの影響ボーンを取得
    influences = cmds.skinCluster(skin_cluster, query=True, influence=True)

    # メッシュを複製
    dup_mesh = cmds.duplicate(mesh, name=f"{mesh}_dup")[0]
    # Historyを削除
    cmds.delete(dup_mesh, constructionHistory=True)
    cmds.select(cl=True)
    if cmds.objExists((dup_mesh + 'ShapeOrig')):
        cmds.delete((dup_mesh + 'ShapeOrig'))

    # bindposeを取得、設定
    bindpose=cmds.dagPose(influences,dup_mesh,q=True,bp=True)
    cmds.delete(bindpose)

    # スキンクラスタを作成
    skincluster_dup = cmds.skinCluster(influences,dup_mesh,toSelectedBones=True,nw=1,mi=maxInfluence,omi=obayMI)
    print(skincluster_dup)
    cmds.select(mesh)
    cmds.select(dup_mesh,add=True)

    mel.eval('CopySkinWeights')
    #cmds.copySkinWeights(ss=skin_cluster, ds=skincluster_dup, noMirror=True, surfaceAssociation='closestPoint', influenceAssociation=['name','closestJoint', 'label'])
    # ウェイトをコピー
    # for i, influence in enumerate(influences):
    #     weights = cmds.skinPercent(skin_cluster, mesh, query=True, transform=influence)
    #     cmds.skinPercent(skin_cluster, dup_mesh, transform=influence, transformValue=weights)

    cmds.select(influences)
    reset_bindpose()
    cmds.select(clear=True)

    cmds.delete(mesh)
    cmds.rename(dup_mesh, mesh)

    print(f"{mesh}を複製しました。")
