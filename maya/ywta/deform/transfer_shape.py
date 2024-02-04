from math import e
import maya.cmds as cmds
import maya.api.OpenMaya as OpenMaya2
import ywta.deform.blendshape as blendshape
import ywta.mesh.colorset as colorset
import ywta.shortcuts as shortcuts
from ywta.ui.optionbox import OptionBox

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

def new_target_with_points(target_mesh, points, target_name=None):

    # blendspageがなければ作成
    blendshape_name = blendshape.get_blendshape_node(target_mesh)
    if blendshape_name is None:
        blendshape_name = cmds.blendShape(target_mesh, foc=True)[0]

    # メッシュを複製して
    target_dup = cmds.duplicate(target_mesh, name=f"{target_mesh}_dup")[0]

    # 頂点をセットして
    target_dup_fnmesh = shortcuts.get_mfnmesh(target_dup)
    target_dup_fnmesh.setPoints(points)

    # ブレンドシェイプターゲットに追加
    target_index = blendshape.add_target(blendshape_name, target_dup, target_name)

    # 複製したshapeを削除
    cmds.delete(target_dup)

def transfer_shape_with_colorset(source_mesh, target_mesh, is_use_colorset=None, is_add_blendshape_target=False):
    """ターゲットのカラーセットのリストを取得して、それぞれのカラーセットに対してシェイプを転送する"""
    if is_use_colorset:
        for colorset_name in colorset.get_colorset_list(target_mesh):
            weights = colorset.get_weights_from_colorset(target_mesh, colorset_name)
            new_points = blend_points_width_weights(source_mesh, target_mesh, weights)
            if is_add_blendshape_target:
                target_name = f"{source_mesh.split('|')[-1]}_{colorset_name}"
                new_target_with_points(target_mesh, new_points, target_name)
            else:
                raise RuntimeError("enable Add Blendshape Target")
    else:
        weights = colorset.get_weights_from_colorset(target_mesh)
        new_points = blend_points_width_weights(source_mesh, target_mesh, weights)
        target_fnmesh = shortcuts.get_mfnmesh(target_mesh)
        if is_add_blendshape_target:
            target_name = f"new_target_{source_mesh.split('|')[-1]}"
            new_target_with_points( target_mesh, new_points, target_name)
        else:
            target_fnmesh.setPoints(new_points)

def exec_from_menu(*args, **kwargs):
    sel = cmds.ls(sl=True)
    if len(sel) != 2:
        raise RuntimeError("Select source and target mesh.")
    source_mesh, target_mesh = sel
    kwargs = Options.get_kwargs()
    transfer_shape_with_colorset(source_mesh, target_mesh,
                                is_use_colorset=kwargs[Options.IS_USE_COLORSET],
                                is_add_blendshape_target=kwargs[Options.IS_ADD_BLENDSHAPE_TARGET])


def display_menu_options(*args, **kwargs):
    options = Options("Transfer Shape Options")
    options.show()

class Options(OptionBox):
    IS_USE_COLORSET = "is_use_colorset"
    IS_ADD_BLENDSHAPE_TARGET = "is_add_blendshape_target"

    @classmethod
    def get_kwargs(cls):
        """Gets the function arguments either from the option box widgets or the saved
        option vars.  If the widgets exist, their values will be saved to the option
        vars.

        :return: A dictionary of the arguments to the create_twist_decomposition
        function."""
        kwargs = {}

        if cmds.checkBox(Options.IS_USE_COLORSET, exists=True):
            kwargs[Options.IS_USE_COLORSET] = cmds.checkBox(Options.IS_USE_COLORSET, q=True, v=False)
            cmds.optionVar(iv=(Options.IS_USE_COLORSET, kwargs[Options.IS_USE_COLORSET]))
        else:
            kwargs[Options.IS_USE_COLORSET] = cmds.optionVar(q=Options.IS_USE_COLORSET)

        if cmds.checkBox(Options.IS_ADD_BLENDSHAPE_TARGET, exists=True):
            kwargs[Options.IS_ADD_BLENDSHAPE_TARGET] = cmds.checkBox(Options.IS_ADD_BLENDSHAPE_TARGET, q=True, v=False)
            cmds.optionVar(iv=(Options.IS_ADD_BLENDSHAPE_TARGET, kwargs[Options.IS_ADD_BLENDSHAPE_TARGET]))
        else:
            kwargs[Options.IS_ADD_BLENDSHAPE_TARGET] = cmds.optionVar(q=Options.IS_ADD_BLENDSHAPE_TARGET)

        return kwargs

    def create_ui(self):
        cmds.columnLayout(adj=True)

        is_use_colorset = cmds.optionVar(q=Options.IS_USE_COLORSET)
        cmds.checkBox(Options.IS_USE_COLORSET, label="Use ColorSet", value=is_use_colorset)

        is_add_blendshape_target = cmds.optionVar(q=Options.IS_ADD_BLENDSHAPE_TARGET)
        cmds.checkBox(Options.IS_ADD_BLENDSHAPE_TARGET, label="Add Blendshape Target", value=is_add_blendshape_target)

    def on_apply(self):
        exec_from_menu()

    def on_reset(self):
        cmds.checkBox(Options.IS_USE_COLORSET, e=True, v=False)
        cmds.checkBox(Options.IS_ADD_BLENDSHAPE_TARGET, e=True, v=False)

    def on_save(self):
        Options.get_kwargs()