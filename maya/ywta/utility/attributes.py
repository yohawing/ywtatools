import maya.cmds as cmds


def unlockAttributes():
    # 選択されたトランスフォームノードを取得
    selectedTransforms = cmds.ls(selection=True, type="transform")

    if not selectedTransforms:
        cmds.warning("トランスフォームノードが選択されていません。")
        return

    # トランスレーション、ローテーション、スケールの属性リスト
    attributes = [
        "translateX",
        "translateY",
        "translateZ",
        "rotateX",
        "rotateY",
        "rotateZ",
        "scaleX",
        "scaleY",
        "scaleZ",
    ]

    # 選択された各トランスフォームノードに対して処理
    for transform in selectedTransforms:
        for attr in attributes:
            # 属性をアンロック
            cmds.setAttr("{}.{}".format(transform, attr), lock=False)

    print("選択したトランスフォームノードの属性をアンロックしました。")


def lockAttributes():
    # 選択されたトランスフォームノードを取得
    selectedTransforms = cmds.ls(selection=True, type="transform")

    if not selectedTransforms:
        cmds.warning("トランスフォームノードが選択されていません。")
        return

    # トランスレーション、ローテーション、スケールの属性リスト
    attributes = [
        "translateX",
        "translateY",
        "translateZ",
        "rotateX",
        "rotateY",
        "rotateZ",
        "scaleX",
        "scaleY",
        "scaleZ",
    ]

    # 選択された各トランスフォームノードに対して処理
    for transform in selectedTransforms:
        for attr in attributes:
            # 属性をアンロック
            cmds.setAttr("{}.{}".format(transform, attr), lock=True)

    print("選択したトランスフォームノードの属性をロックしました。")

