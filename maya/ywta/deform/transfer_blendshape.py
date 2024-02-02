import numpy as np
import ywta.deform.blendshape as blendshape
import ywta.shortcuts as shortcuts
import maya.cmds as cmds
import maya.OpenMaya as OpenMaya
import maya.OpenMayaAnim as OpenMayaAnim
import maya.api.OpenMaya as OpenMaya2
import importlib
importlib.reload(shortcuts)
importlib.reload(blendshape)

print("start transfer blendshapes")

#PointやPointArrayを処理するサンプルコード
#https://gist.github.com/minoue/dd5d554441b253fce0bb77919e2685e0

# pointsをnumpyに変換
def points_to_np(points):
    points_np = np.zeros((len(points), 3))
    for i, p in enumerate(points):
        points_np[i] = [p.x, p.y, p.z]
    return points_np

def get_colorsets(mesh):
    colorsets = cmds.polyColorSet(mesh, q=True, allColorSets=True)
    return colorsets

def get_weights_from_colorset(mesh_name, colorset):

    fnmesh = shortcuts.get_mfnmesh(mesh_name)
    points = fnmesh.getPoints(OpenMaya2.MSpace.kObject)
    #colors = fnmesh.getColors(colorset)
    colors = fnmesh.getVertexColors(colorset)
    vertices = fnmesh.getVertices()

    if colorset is None:
        return [1] * len(points)

    weights = [0] * len(points)

    for i, id in enumerate(vertices[1]):
        #average of rgb
        weights[id] = (colors[id].r + colors[id].g + colors[id].b) / 3
        weights[id] *= weights[id]

    return weights

def blend_points_width_weights(source, target, weights):

    source_points = shortcuts.get_points(source)
    target_points = shortcuts.get_points(target)

    if len(source_points) != len(target_points):
        raise RuntimeError("Source and target points must be the same length")
    if len(weights) != len(target_points):
        raise RuntimeError("Weights must be the same length as target points")

    new_points = OpenMaya2.MPointArray()
    for i,w in enumerate(weights):
        p = OpenMaya2.MPoint()
        p.x = source_points[i].x * w + target_points[i].x * (1 - w)
        p.y = source_points[i].y * w + target_points[i].y * (1 - w)
        p.z = source_points[i].z * w + target_points[i].z * (1 - w)
        new_points.append(p)
    return new_points

def new_target_with_points(blendshape_name, target_mesh, points, target_name=None):
    # メッシュを複製して
    target_dup = cmds.duplicate(target_mesh, name=f"{target_mesh}_dup")[0]

    # 頂点をセットして
    target_dup_fnmesh = shortcuts.get_mfnmesh(target_dup)
    target_dup_fnmesh.setPoints(points)

    # ブレンドシェイプターゲットに追加
    target_index = blendshape.add_target(bs_name, target_dup, target_name)

    cmds.delete(target_dup)

sel = cmds.ls(selection=True, flatten=True)
source_mesh = sel[0]
target_mesh = sel[1]

bs_name = blendshape.get_blendshape_node(target_mesh)

# transfer shapes
weights = get_weights_from_colorset(target_mesh, "all")
new_points = blend_points_width_weights(source_mesh, target_mesh, weights)
target_fnmesh = shortcuts.get_mfnmesh(target_mesh)
target_fnmesh.setPoints(new_points)


def transfer_shape_with_colorset(source_mesh, target_mesh, colorset):
    # get all colorsets
    colorsets = get_colorsets(target_mesh)
    print(colorsets)

    for colorset in colorsets:
        weights = get_weights_from_colorset(target_mesh, colorset)
        new_points = blend_points_width_weights(source_mesh, target_mesh, weights)
        target_name = f"sakia_{colorset}"
        new_target_with_points(bs_name, target_mesh, new_points, target_name)


