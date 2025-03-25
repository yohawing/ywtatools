import maya.cmds as cmds


def create_joint_hierarchy_from_transform(transform):
    # 現在の選択を保存し、選択を解除
    current_selection = cmds.ls(selection=True)
    cmds.select(clear=True)

    # Transform 階層をコピーした Joint 階層を作成する関数
    joint = cmds.joint(name=transform + "_jnt")

    # 子の Transform を再帰的に処理
    children = cmds.listRelatives(transform, children=True, type="transform")
    if children:
        for child in children:
            create_joint_hierarchy_from_transform(child)
            cmds.parent(child + "_jnt", joint)

    # Joint の位置を Transform に合わせる
    cmds.delete(cmds.parentConstraint(transform, joint))

    return joint


def merge_meshes(transform):
    # Transform 階層内のすべてのメッシュを取得
    meshes = cmds.listRelatives(transform, allDescendents=True, type="mesh")

    # メッシュをマージ
    if meshes:
        merged_mesh = cmds.polyUnite(meshes, constructionHistory=False)[0]
        cmds.rename(merged_mesh, transform + "_mesh")
        return transform + "_mesh"
    else:
        return None


def merge_and_skin():
    # 選択した Transform を取得
    selection = cmds.ls(selection=True, type="transform")

    if selection:
        transform = selection[0]

        # Transform 階層をコピーした Joint 階層を作成
        root_joint = create_joint_hierarchy_from_transform(transform)

        # Transform 内のメッシュをマージ
        merged_mesh = merge_meshes(transform)

        if merged_mesh:
            # メッシュを Joint にバインド
            cmds.select(root_joint, replace=True)
            cmds.select(merged_mesh, add=True)
            cmds.skinCluster(
                root_joint,
                merged_mesh,
                toSelectedBones=False,
                bindMethod=0,
                skinMethod=0,
                maximumInfluences=3,
            )
            # bindMethod=0 は Closest Distance でバインドすることを意味します。

        print("Joint hierarchy created and mesh bound successfully.")
    else:
        print("Please select a transform node.")
