from maya import cmds
import maya.api.OpenMaya as OpenMaya2
import ywta.shortcuts as shortcuts


def create_colorset(mesh, name, colors):
    """
    :param str mesh:
    :param str name:
    :param list colors:
    """
    dag = shortcuts.get_dag_path2.get_dag(mesh)
    dag.extendToShape()
    mesh_fn = OpenMaya2.MFnMesh(dag)
    vertices = range(mesh_fn.numVertices)

    cmds.polyColorSet(mesh, create=True, colorSet=name, clamped=True, representation="RGB")
    mesh_fn.setVertexColors(colors, vertices)

def get_colorset(mesh_name, colorset_name):
    """
    :param str mesh_name:
    :param str colorset_name:
    :return: list
    """
    dag = shortcuts.get_dag_path2(mesh_name)
    dag.extendToShape()
    mesh_fn = OpenMaya2.MFnMesh(dag)
    vertices = range(mesh_fn.numVertices)

    return mesh_fn.mesh_fn.getColors(colorset_name)