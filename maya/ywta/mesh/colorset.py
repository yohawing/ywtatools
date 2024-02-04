from maya import cmds
import maya.api.OpenMaya as OpenMaya2
import ywta.shortcuts as shortcuts


def create_colorset(mesh, name, colors):
    dag = shortcuts.get_dag_path2.get_dag(mesh)
    dag.extendToShape()
    mesh_fn = OpenMaya2.MFnMesh(dag)
    vertices = range(mesh_fn.numVertices)

    cmds.polyColorSet(mesh, create=True, colorSet=name, clamped=True, representation="RGB")
    mesh_fn.setVertexColors(colors, vertices)

def get_colorset(mesh_name, colorset_name):
    dag = shortcuts.get_dag_path2(mesh_name)
    dag.extendToShape()
    mesh_fn = OpenMaya2.MFnMesh(dag)
    # vertices = range(mesh_fn.numVertices)

    return mesh_fn.mesh_fn.getColors(colorset_name)

def get_colorset_list(mesh_name):
    colorsets = cmds.polyColorSet(mesh_name, q=True, allColorSets=True)
    return colorsets

def get_weights_from_colorset(mesh_name, colorset=None):
    # カラーセットの値を取得して、それをウェイトとして返す
    fnmesh = shortcuts.get_mfnmesh(mesh_name)
    points = fnmesh.getPoints(OpenMaya2.MSpace.kObject)

    if colorset is None:
        return [1] * len(points)

    colors = fnmesh.getVertexColors(colorset)
    vertices = fnmesh.getVertices()

    weights = [0] * len(points)

    for i, id in enumerate(vertices[1]):
        #average of rgb
        weights[id] = (colors[id].r + colors[id].g + colors[id].b) / 3
        # weights[id] *= weights[id]

    return weights