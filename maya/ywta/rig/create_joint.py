import maya.cmds as cmds


def create_joint_from_selected_verts():
    """
    選択した頂点の平均位置にジョイントを作成する関数
    """
    # 選択された頂点を取得
    selected_verts = cmds.ls(selection=True, flatten=True)

    if len([vert for vert in selected_verts if "vtx" in vert]) == 0:
        cmds.warning("頂点が選択されていません。")
        return

    # 頂点の位置を取得し、平均位置を計算
    total_pos = [0.0, 0.0, 0.0]
    for vert in selected_verts:
        vert_pos = cmds.pointPosition(vert, w=True)
        total_pos[0] += vert_pos[0]
        total_pos[1] += vert_pos[1]
        total_pos[2] += vert_pos[2]

    center_pos = [
        total_pos[0] / len(selected_verts),
        total_pos[1] / len(selected_verts),
        total_pos[2] / len(selected_verts),
    ]

    # ジョイントを作成
    bone_name = "joint"
    bone = cmds.joint(name=bone_name, p=center_pos)
    print("create joint in {0}".format(center_pos))
    cmds.select(clear=True)
    cmds.select(bone)


def create_joint_from_selected_faces():
    """
    選択した面の平均位置にジョイントを作成する関数
    """
    # 選択された面を取得
    selected_faces = cmds.ls(selection=True, flatten=True)

    if len([face for face in selected_faces if "f" in face]) == 0:
        cmds.warning("面が選択されていません。")
        return

    # 面の中心位置を計算
    # total_pos = [0.0, 0.0, 0.0]
    for face in selected_faces:
        cmds.select(face, r=True)
        cmds.ConvertSelectionToVertices()
        create_joint_from_selected_verts()


def create_joint_from_selected_component():
    # 選択されたコンポーネントの条件分岐
    selected_component = cmds.ls(selection=True, flatten=True)

    if len([comp for comp in selected_component if ".vtx[" in comp]) > 0:
        create_joint_from_selected_verts()

    elif len([comp for comp in selected_component if ".f[" in comp]) > 0:
        create_joint_from_selected_faces()


# selected_verts = cmds.ls(selection=True, flatten=True)

# if len([vert for vert in selected_verts if "vtx" in vert]) is 0:
#     cmds.warning("頂点が選択されていません。")
# else:
#     total_pos = [0.0, 0.0, 0.0]
#     for vert in selected_verts:
#         vert_pos = cmds.pointPosition(vert, w=True)
#         total_pos[0] += vert_pos[0]
#         total_pos[1] += vert_pos[1]
#         total_pos[2] += vert_pos[2]
#     center_pos = [
#         total_pos[0] / len(selected_verts),
#         total_pos[1] / len(selected_verts),
#         total_pos[2] / len(selected_verts),
#     ]

#     bone_name = "joint"
#     bone = cmds.joint(name=bone_name, p=center_pos)
#     print("create joint in {0}".format(center_pos))
#     cmds.select(clear=True)
#     cmds.select(bone)
