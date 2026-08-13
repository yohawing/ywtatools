"""Retarget meshes fit on a source mesh to a modified version of the source mesh.

The RBF formulation is adapted from PyGeM's MIT-licensed RBF implementation:
https://github.com/mathLab/PyGeM/blob/1daf6f0ec47eff05f66b6c10cba046c2c6a8deee/pygem/rbf.py
See ``PyGeM-LICENSE.rst`` in this directory.

Example Usage
=============

    retarget("source_body", "new_body", ["shirt", "pants"], rbf=RBF.linear)

"""

import time
import numpy as np

import maya.api.OpenMaya as OpenMaya
import maya.cmds as cmds
import ywta.shortcuts as shortcuts
from ywta.rig.rbf_solver import (  # noqa: F401
    RBF,
    RbfSolver,
    get_distance_matrix,
    get_weight_matrix,
)


def retarget(
    source,
    target,
    shapes,
    rbf=None,
    radius=0.5,
    stride=1,
    max_control_points=None,
    progress=None,
    cancelled=None,
):
    """Run the mesh retarget.

    :param source: Source mesh
    :param target: Modified source mesh
    :param shapes: List of meshes to retarget
    :param rbf: One of the RBF functions. See class RBF
    :param radius: Smoothing parameter for the rbf
    :param stride: Vertex stride to sample on the source mesh.  Increase to speed up
    the calculation but less accurate.
    """
    start_time = time.time()
    source_points = points_to_np_array(source, stride if max_control_points is None else 1)
    target_points = points_to_np_array(target, stride if max_control_points is None else 1)

    solver = RbfSolver.fit(
        source_points,
        target_points,
        rbf=rbf,
        radius=radius,
        max_control_points=max_control_points,
        progress=progress,
        cancelled=cancelled,
    )

    shapes = list(shapes)
    point_sets = [points_to_np_array(shape) for shape in shapes]
    deformed_sets = solver.transform_many(point_sets, progress, cancelled)
    for shape, deformed in zip(shapes, deformed_sets):
        points = [OpenMaya.MPoint(*p) for p in deformed]
        dupe = cmds.duplicate(shape, name="{}_{}_{}".format(shape, radius, solver.rbf.__name__))[0]
        set_points(dupe, points)

    end_time = time.time()
    print("Transferred in {} seconds".format(end_time - start_time))


def points_to_np_array(mesh, stride=1):
    points = get_points(mesh)
    sparse_points = [OpenMaya.MPoint(p) for p in points][::stride]
    np_points = np.array([[p.x, p.y, p.z] for p in sparse_points])
    return np_points


def get_points(mesh):
    path = shortcuts.get_dag_path2(shortcuts.get_shape(mesh))
    mesh_fn = OpenMaya.MFnMesh(path)
    return mesh_fn.getPoints()


def set_points(mesh, points):
    path = shortcuts.get_dag_path2(shortcuts.get_shape(mesh))
    mesh_fn = OpenMaya.MFnMesh(path)
    mesh_fn.setPoints(points)
