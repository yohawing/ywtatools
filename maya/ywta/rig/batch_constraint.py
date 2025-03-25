import maya.cmds as cmds
import math

# 複数のBoneと複数のControllerを取得する
# ボーンごとにPointConstraintを作成する

# 選択されているボーンを取得
bones = cmds.ls(selection=True, type="joint")
# 選択されているコントローラを取得(Joint以外)
controllers = cmds.ls(selection=True, type="transform")
controllers = [c for c in controllers if not cmds.nodeType(c) == "joint"]

# BoneごとにControllerとの距離を計算し、重みを設定
for bone in bones:
    # boneのPositionを取得
    bone_pos = cmds.xform(bone, query=True, translation=True, worldSpace=True)
    # controllersとBoneをPointConstraintで結ぶ
    
    distances = []
    for i, ctl in enumerate(controllers):
        ctl_pos = cmds.xform(ctl, query=True, translation=True, worldSpace=True)
        y_dist = abs(bone_pos[1] - ctl_pos[1])
        distances.append(y_dist)

    for i, ctl in enumerate(controllers):
        ratio = 1- distances[i] / sum(distances)
        # 距離に応じて、Controllerごとに重みを設定
        # cmds.setAttr(f"{constraint[0]}.{ctl}W{str(i)}", ratio)
        constraint = cmds.pointConstraint(ctl, bone, weight=ratio,  maintainOffset=True)