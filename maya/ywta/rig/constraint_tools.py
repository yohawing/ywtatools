"""選択順に基づくconstraint作成・削除ツール。"""

import math

import maya.cmds as cmds

from ywta.core import undo_utils


CONSTRAINT_COMMANDS = {
    "parent": cmds.parentConstraint,
    "point": cmds.pointConstraint,
    "orient": cmds.orientConstraint,
    "scale": cmds.scaleConstraint,
    "aim": cmds.aimConstraint,
}
DRIVEN_CHANNELS = {
    "parent": ("translate", "rotate"),
    "point": ("translate",),
    "orient": ("rotate",),
    "scale": ("scale",),
    "aim": ("rotate",),
}


def _resolve_transform(node):
    """transform派生nodeを一意なロングパスへ解決する。"""
    matches = cmds.ls(node, long=True) or []
    matches = [match for match in matches if cmds.objectType(match, isAType="transform")]
    if len(matches) != 1:
        raise ValueError("transformを一意に解決できません: {}".format(node))
    return matches[0]


def _validate_vector(value, label):
    """3要素の有限vectorをfloat tupleへ変換する。"""
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 3
        or any(
            not isinstance(component, (int, float)) or isinstance(component, bool) or not math.isfinite(float(component))
            for component in value
        )
    ):
        raise ValueError("{}が不正です。".format(label))
    return tuple(float(component) for component in value)


def _validate_aim_axes(aim_vector, up_vector):
    """Aim/Upが非ゼロかつ非平行であることを検証する。"""
    aim = _validate_vector(aim_vector, "aim_vector")
    up = _validate_vector(up_vector, "up_vector")
    if sum(value * value for value in aim) <= 1.0e-12:
        raise ValueError("aim_vectorは非ゼロにしてください。")
    if sum(value * value for value in up) <= 1.0e-12:
        raise ValueError("up_vectorは非ゼロにしてください。")
    cross = (
        aim[1] * up[2] - aim[2] * up[1],
        aim[2] * up[0] - aim[0] * up[2],
        aim[0] * up[1] - aim[1] * up[0],
    )
    if sum(value * value for value in cross) <= 1.0e-12:
        raise ValueError("aim_vectorとup_vectorは非平行にしてください。")
    return aim, up


def create_constraint(
    kind,
    drivers,
    driven,
    maintain_offset=True,
    aim_vector=(1.0, 0.0, 0.0),
    up_vector=(0.0, 1.0, 0.0),
):
    """driverからdrivenへconstraintを単一Undoで作成する。

    Args:
        kind: parent / point / orient / scale / aim。
        drivers: 1つ以上のdriver transform。
        driven: constraint対象transform。
        maintain_offset: 現在の相対姿勢を維持するか。
        aim_vector: Aim constraintのlocal aim軸。
        up_vector: Aim constraintのlocal up軸。

    Returns:
        作成したconstraint nodeのロング名。
    """
    if kind not in CONSTRAINT_COMMANDS:
        raise ValueError("未対応のconstraint種別です: {}".format(kind))
    if not isinstance(maintain_offset, bool):
        raise ValueError("maintain_offsetはboolで指定してください。")
    if not isinstance(drivers, (list, tuple)) or not drivers:
        raise ValueError("driverを1つ以上指定してください。")
    resolved_driven = _resolve_transform(driven)
    resolved_drivers = []
    seen = set()
    for driver in drivers:
        resolved = _resolve_transform(driver)
        node_uuid = (cmds.ls(resolved, uuid=True) or [None])[0]
        if node_uuid in seen:
            raise ValueError("同じdriverを複数回指定できません: {}".format(resolved))
        seen.add(node_uuid)
        resolved_drivers.append(resolved)
    driven_uuid = (cmds.ls(resolved_driven, uuid=True) or [None])[0]
    if driven_uuid in seen:
        raise ValueError("driverとdrivenは別nodeにしてください。")
    referenced = [node for node in resolved_drivers + [resolved_driven] if cmds.referenceQuery(node, isNodeReferenced=True)]
    if referenced:
        raise ValueError("参照nodeにはconstraintを作成できません: {}".format(", ".join(referenced)))

    blocked = []
    for channel in DRIVEN_CHANNELS[kind]:
        for axis in "XYZ":
            attribute = "{}.{}{}".format(resolved_driven, channel, axis)
            if not cmds.getAttr(attribute, settable=True):
                blocked.append(channel + axis)
    if blocked:
        raise ValueError("driven channelが編集できません: {} ({})".format(resolved_driven, ", ".join(blocked)))

    options = {"maintainOffset": maintain_offset}
    if kind == "aim":
        aim_vector, up_vector = _validate_aim_axes(aim_vector, up_vector)
        options.update(
            aimVector=aim_vector,
            upVector=up_vector,
            worldUpType="vector",
            worldUpVector=up_vector,
        )

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Create {} Constraint".format(kind.title()))
    cmds.undoInfo(openChunk=True, chunkName="YWTA Create {} Constraint".format(kind.title()))
    failed = False
    try:
        constraint = CONSTRAINT_COMMANDS[kind](resolved_drivers, resolved_driven, **options)[0]
        constraint = (cmds.ls(constraint, long=True) or [constraint])[0]
        if selection:
            cmds.select(selection, replace=True)
        else:
            cmds.select(clear=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return constraint


def create_selected(
    kind,
    maintain_offset=True,
    aim_vector=(1.0, 0.0, 0.0),
    up_vector=(0.0, 1.0, 0.0),
):
    """選択順の最後をdriven、それ以前をdriversとして作成する。"""
    selected = []
    seen = set()
    for node in cmds.ls(selection=True, objectsOnly=True, long=True) or []:
        if not cmds.objectType(node, isAType="transform"):
            continue
        node_uuid = (cmds.ls(node, uuid=True) or [None])[0]
        if node_uuid not in seen:
            seen.add(node_uuid)
            selected.append(node)
    if len(selected) < 2:
        raise ValueError("driverを先、drivenを最後に2つ以上選択してください。")
    return create_constraint(
        kind,
        selected[:-1],
        selected[-1],
        maintain_offset=maintain_offset,
        aim_vector=aim_vector,
        up_vector=up_vector,
    )


def show_options():
    """constraint種別、offset、Aim/Up軸を指定するMaya UIを表示する。"""
    window = "ywtaConstraintOptionsWindow"
    if cmds.window(window, exists=True):
        cmds.deleteUI(window)
    cmds.window(window, title="YWTA Constraint Options", sizeable=False)
    cmds.columnLayout(adjustableColumn=True, rowSpacing=8, width=340)
    kind_field = cmds.optionMenuGrp(label="Type")
    for label in ("Parent", "Point", "Orient", "Scale", "Aim"):
        cmds.menuItem(label=label)
    offset_field = cmds.checkBox(label="Maintain Offset", value=True)
    aim_field = cmds.floatFieldGrp(
        label="Local Aim",
        numberOfFields=3,
        value1=1.0,
        value2=0.0,
        value3=0.0,
    )
    up_field = cmds.floatFieldGrp(
        label="Local Up",
        numberOfFields=3,
        value1=0.0,
        value2=1.0,
        value3=0.0,
    )

    def vector(field):
        return tuple(cmds.floatFieldGrp(field, query=True, **{"value{}".format(index): True}) for index in range(1, 4))

    def run(*_args):
        return create_selected(
            cmds.optionMenuGrp(kind_field, query=True, value=True).lower(),
            maintain_offset=cmds.checkBox(offset_field, query=True, value=True),
            aim_vector=vector(aim_field),
            up_vector=vector(up_field),
        )

    cmds.button(label="Create from Selection", command=run)
    cmds.showWindow(window)
    return window


def delete_constraints(nodes=None):
    """指定transformを駆動するconstraintを単一Undoで削除する。"""
    if nodes is None:
        nodes = cmds.ls(selection=True, objectsOnly=True, long=True) or []
    elif isinstance(nodes, str):
        nodes = [nodes]
    else:
        try:
            nodes = list(nodes)
        except TypeError as error:
            raise ValueError("constraint削除対象はtransform列にしてください。") from error
    transforms = []
    for node in nodes or []:
        resolved = _resolve_transform(node)
        if resolved not in transforms:
            transforms.append(resolved)
    if not transforms:
        raise ValueError("constraintを削除するtransformを1つ以上選択してください。")
    constraints = []
    for transform in transforms:
        for constraint in cmds.listConnections(transform, source=True, destination=False, type="constraint") or []:
            if constraint not in constraints:
                constraints.append(constraint)
    if not constraints:
        raise ValueError("選択nodeを駆動するconstraintがありません。")
    referenced = [constraint for constraint in constraints if cmds.referenceQuery(constraint, isNodeReferenced=True)]
    if referenced:
        raise ValueError("参照constraintは削除できません: {}".format(", ".join(referenced)))

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Delete Constraints")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Delete Constraints")
    failed = False
    try:
        cmds.delete(constraints)
        valid_selection = [node for node in selection if cmds.objExists(node)]
        if valid_selection:
            cmds.select(valid_selection, replace=True)
        else:
            cmds.select(clear=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return constraints
