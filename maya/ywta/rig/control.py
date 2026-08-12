"""The control module provides functions and a graphical interface to create,
manipulate, import and export curve controls.

.. image:: control.png

The APIs provided allow curve shapes to be abstracted from transforms.  This allows the
creation of rigging constructs independent of actual curve shapes which can vary
greatly from asset to asset.  The general workflow would be to create rig controls
with transforms only without shapes.  After the rigs are created, add shapes to the
transforms with this tool/API.  The shapes can then be serialized to disk to load back
in an automated build.

Example Usage
=============

The Control Creator tool can be accessed in the cmt menu::

    CMT > Rigging > Control Creator

API
---
::

    import ywta.rig.control as control
    curve = cmds.circle()[0]

    # Save the curve to disk
    file_path = "{}/control.json".format(cmds.workspace(q=True, rd=True))
    control.export_curves([curve], file_path)

    # Load the curve back in
    cmds.file(n=True, f=True)
    control.import_curves(file_path)

    # Create another copy of the curve
    control.import_new_curves(file_path)

    # Create the curve on the selected transform
    node = cmds.createNode('transform', name='newNode')
    control.import_curves_on_selected(file_path)

    # Manipulate the curve before creating
    curve = control.load_curves(file_path)[0]
    curve.scale_by(2, 2, 2)
    curve.set_rotation(0, 60, 0)
    curve.set_translation(10, 5, 0)
    new_node = curve.create("anotherNode")

    # Mirror the curve
    mirrored = cmds.createNode("transform", name="mirroredNode")
    cmds.setAttr("{}.t".format(mirrored), -10, -5, 2)
    cmds.setAttr("{}.r".format(mirrored), -55, 10, 63)
    control.mirror_curve(new_node, mirrored)

"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import json
import math
import os
import logging
import re
import webbrowser
import tempfile

import maya.cmds as cmds
import maya.api.OpenMaya as OpenMaya

from ywta.settings import DOCUMENTATION_ROOT
from ywta.core import undo_utils
import ywta.shortcuts as shortcuts

logger = logging.getLogger(__name__)
CONTROLS_DIRECTORY = os.path.join(os.path.dirname(__file__), "controls")
HELP_URL = "{}/rig/control.html".format(DOCUMENTATION_ROOT)


def export_curves(controls=None, file_path=None):
    """Serializes the given curves into the control library.

    :param controls: Optional list of controls to export. If no controls are specified,
        the selected curves will be exported.
    :param file_path: File path to export to
    :return: The exported list of ControlShapes.
    """
    if file_path is None:
        file_path = shortcuts.get_save_file_name("*.json", "ywta.control")
        if not file_path:
            return
    if controls is None:
        controls = cmds.ls(sl=True)
    data = get_curve_data(controls)
    _write_curve_data(data, file_path)
    return data


def _write_curve_data(data, file_path):
    """CurveShape列を原子的JSONとして書き出す。"""
    target = os.path.abspath(file_path)
    directory = os.path.dirname(target)
    if not os.path.isdir(directory):
        raise ValueError("保存先directoryがありません: {}".format(directory))
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix=".ywta_control_",
        suffix=".json",
        dir=directory,
        delete=False,
    )
    temporary = handle.name
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=4, cls=CurveShapeEncoder)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)
    logger.info("Exported controls to {}".format(target))
    return target


def export_shape_to_library(controls, name, overwrite=False, directory=CONTROLS_DIRECTORY):
    """複数controlのworld形状を1つのlibrary entryとして保存する。

    Args:
        controls: 保存対象control transform。
        name: library上のshape名。
        overwrite: 既存entryの置換を明示許可するか。
        directory: 保存先library directory。

    Returns:
        保存したJSONの絶対path。
    """
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name.strip()):
        raise ValueError("library名は英数字、underscore、hyphenだけにしてください。")
    if not isinstance(overwrite, bool):
        raise ValueError("overwriteはboolで指定してください。")
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        raise ValueError("control library directoryがありません: {}".format(directory))
    target = os.path.join(directory, name.strip() + ".json")
    if os.path.exists(target) and not overwrite:
        raise ValueError("Control library entryが既に存在します: {}".format(name.strip()))

    data = []
    seen = set()
    for control in controls or []:
        matches = cmds.ls(control, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("controlを一意に解決できません: {}".format(control))
        transform = matches[0]
        node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
        if node_uuid in seen:
            continue
        seen.add(node_uuid)
        shapes = _curve_shapes(transform)
        if not shapes:
            raise ValueError("NURBS curve shapeがありません: {}".format(transform))
        matrix = _dag_path(transform).inclusiveMatrix()
        for shape in shapes:
            curve = _curve_data_from_shape(shape)
            world_points = [OpenMaya.MPoint(*point) * matrix for point in curve.cvs]
            curve.cvs = [(point.x, point.y, point.z) for point in world_points]
            curve.transform = name.strip()
            data.append(curve)
    if not data:
        raise ValueError("保存するcontrolを1つ以上指定してください。")
    return _write_curve_data(data, target)


def rename_library_shape(old_name, new_name, directory=CONTROLS_DIRECTORY):
    """Control library entryを検証して原子的に改名する。

    Args:
        old_name: 現在のlibrary名。
        new_name: 新しいlibrary名。
        directory: Control library directory。

    Returns:
        改名後JSONの絶対path。
    """
    name_pattern = r"[A-Za-z0-9_-]+"
    if not isinstance(old_name, str) or not re.fullmatch(name_pattern, old_name.strip()):
        raise ValueError("現在のlibrary名が不正です。")
    if not isinstance(new_name, str) or not re.fullmatch(name_pattern, new_name.strip()):
        raise ValueError("library名は英数字、underscore、hyphenだけにしてください。")
    old_name = old_name.strip()
    new_name = new_name.strip()
    if old_name == new_name:
        raise ValueError("新しいlibrary名を指定してください。")
    directory = os.path.abspath(directory)
    if not os.path.isdir(directory):
        raise ValueError("control library directoryがありません: {}".format(directory))
    source = os.path.join(directory, old_name + ".json")
    target = os.path.join(directory, new_name + ".json")
    if not os.path.isfile(source):
        raise ValueError("Control library entryがありません: {}".format(old_name))
    if os.path.exists(target):
        raise ValueError("Control library entryが既に存在します: {}".format(new_name))

    curves = load_curves(source)
    for curve in curves:
        curve.transform = new_name
    _write_curve_data(curves, target)
    try:
        os.remove(source)
    except Exception:
        if os.path.exists(target):
            os.remove(target)
        raise
    return target


def get_curve_data(controls=None):
    """Get the serializable data of the given controls.

    :param controls: Controls to serialize
    :return: List of ControlShape objects
    """
    if controls is None:
        controls = cmds.ls(sl=True)
    data = []
    seen = set()
    for control in controls or []:
        matches = cmds.ls(control, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("controlを一意に解決できません: {}".format(control))
        transform = matches[0]
        node_uuid = (cmds.ls(transform, uuid=True) or [None])[0]
        if node_uuid in seen:
            continue
        seen.add(node_uuid)
        shapes = _curve_shapes(transform)
        if not shapes:
            raise ValueError("NURBS curve shapeがありません: {}".format(transform))
        for shape in shapes:
            curve = _curve_data_from_shape(shape)
            curve.transform = transform.rsplit("|", 1)[-1]
            data.append(curve)
    return data


def import_new_curves(file_path=None, tag_as_controller=False):
    """Imports control shapes from disk onto new transforms.

    :param file_path: Path to the control file.
    :param tag_as_controller: True to tag the curve transform as a controller
    :return: The new curve transforms
    """
    controls = load_curves(file_path)
    mapping = {}
    reserved = set()
    for curve in controls:
        if curve.transform not in mapping:
            name = curve.transform
            suffix = 1
            while cmds.objExists(name) or name in reserved:
                name = "{}{}".format(curve.transform, suffix)
                suffix += 1
            mapping[curve.transform] = name
            reserved.add(name)

    def create():
        transforms = []
        for curve in controls:
            transform = mapping[curve.transform]
            curve.create(transform, tag_as_controller)
            if transform not in transforms:
                transforms.append(transform)
        return transforms

    return _run_curve_creation("Import New Control Curves", create)


def import_curves(file_path=None, tag_as_controller=False):
    """Imports control shapes from disk onto their saved named transforms.

    :param file_path: Path to the control file.
    :param tag_as_controller: True to tag the curve transform as a controller
    :return: The new curve transforms
    """
    controls = load_curves(file_path)

    def create():
        transforms = []
        for curve in controls:
            transform = curve.create(curve.transform, tag_as_controller)
            if transform not in transforms:
                transforms.append(transform)
        return transforms

    return _run_curve_creation("Import Control Curves", create)


def import_curves_on_selected(file_path=None, tag_as_controller=False):
    """Imports a control shape from disk onto the selected transform.

    :param file_path: Path to the control file.
    :param tag_as_controller: True to tag the curve transform as a controller
    :return: The new curve transform
    """
    controls = load_curves(file_path)
    selected_transforms = cmds.ls(selection=True, long=True, type="transform") or []
    if not selected_transforms:
        return

    def create():
        for transform in selected_transforms:
            for curve in controls:
                curve.create(transform, tag_as_controller)
        return selected_transforms

    return _run_curve_creation("Import Curves on Selected", create)


def load_curves(file_path=None):
    """Load the CurveShape objects from disk.

    :param file_path:
    :return:
    """
    if file_path is None:
        file_path = shortcuts.get_open_file_name("*.json", "ywta.control")
        if not file_path:
            return

    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    _validate_curve_payload(data)
    logger.info("Loaded controls {}".format(file_path))
    curves = [CurveShape(**control) for control in data]
    return curves


def _validate_curve_payload(data):
    """Control JSON全体をscene編集前に検証する。"""
    if not isinstance(data, list) or not data:
        raise ValueError("Control JSONは1件以上のcurve配列にしてください。")
    required = {"transform", "cvs", "degree", "form", "knots", "color"}
    for record_index, record in enumerate(data):
        if not isinstance(record, dict) or set(record) != required:
            raise ValueError("curve recordの項目が不正です: {}".format(record_index))
        transform = record["transform"]
        if not isinstance(transform, str) or not transform.strip() or "|" in transform:
            raise ValueError("curve transform名が不正です: {}".format(record_index))
        degree = record["degree"]
        form = record["form"]
        if not isinstance(degree, int) or isinstance(degree, bool) or degree < 1:
            raise ValueError("curve degreeが不正です: {}".format(record_index))
        if not isinstance(form, int) or isinstance(form, bool) or form not in {0, 1, 2}:
            raise ValueError("curve formが不正です: {}".format(record_index))
        cvs = record["cvs"]
        if not isinstance(cvs, list) or len(cvs) < degree + 1:
            raise ValueError("curve CV数が不足しています: {}".format(record_index))
        for point in cvs:
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 3
                or any(
                    not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
                    for value in point
                )
            ):
                raise ValueError("curve CVが不正です: {}".format(record_index))
        knots = record["knots"]
        expected_knots = len(cvs) + degree - 1
        if form == 2:
            expected_knots += degree
        if (
            not isinstance(knots, list)
            or len(knots) != expected_knots
            or any(
                not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value))
                for value in knots
            )
            or any(float(left) > float(right) for left, right in zip(knots, knots[1:]))
        ):
            raise ValueError("curve knot列が不正です: {}".format(record_index))
        color = record["color"]
        if color is None:
            continue
        if isinstance(color, int) and not isinstance(color, bool) and 0 <= color <= 31:
            continue
        if (
            isinstance(color, (list, tuple))
            and len(color) == 3
            and all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                and 0.0 <= float(value) <= 1.0
                for value in color
            )
        ):
            continue
        raise ValueError("curve colorが不正です: {}".format(record_index))


def _run_curve_creation(chunk_name, callback):
    """Control curve作成を選択復元付きの単一Undoで実行する。"""
    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled(chunk_name)
    cmds.undoInfo(openChunk=True, chunkName="YWTA {}".format(chunk_name))
    failed = False
    try:
        result = callback()
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
    return result


def _get_new_transform_name(base):
    """Get a new unique transform name

    :param base: Base name
    :return: A unique name of a non-existing transform
    """
    name = base
    i = 1
    while cmds.objExists(name):
        name = "{}{}".format(base, i)
        i += 1
    return name


class CurveShape(object):
    """Represents the data required to build a nurbs curve shape"""

    def __init__(self, transform=None, cvs=None, degree=3, form=0, knots=None, color=None):
        self.cvs = cvs
        self.degree = degree
        self.form = form
        self.knots = knots
        self.color = color
        self.transform_matrix = OpenMaya.MTransformationMatrix()
        self.transform = transform
        if transform and cmds.objExists(transform) and not cvs:
            self._set_from_curve(transform)

    def _set_from_curve(self, transform):
        """Store the parameters from an existing curve in the CurveShape object.

        :param transform: Transform
        """
        shape = shortcuts.get_shape(transform)
        if shape and cmds.nodeType(shape) == "nurbsCurve":
            curve = _curve_data_from_shape(shape)
            self.transform = transform
            self.cvs = curve.cvs
            self.degree = curve.degree
            self.form = curve.form
            self.knots = curve.knots
            self.color = curve.color

    def create(self, transform=None, as_controller=True):
        """Create a curve.

        :param transform: Name of the transform to create the curve shape under.
            If the transform does not exist, it will be created.
        :param as_controller: True to mark the curve transform as a controller.
        :return: The transform of the new curve shapes.
        """
        transform = transform or self.transform
        if not cmds.objExists(transform):
            transform = cmds.createNode("transform", name=transform)
        periodic = self.form == 2
        points = self._get_transformed_points()
        points = points + points[: self.degree] if periodic else points
        curve = cmds.curve(degree=self.degree, p=points, per=periodic, k=self.knots)
        shape = shortcuts.get_shape(curve)
        if self.color is not None:
            cmds.setAttr("{}.overrideEnabled".format(shape), True)
            if isinstance(self.color, int):
                cmds.setAttr("{}.overrideColor".format(shape), self.color)
            else:
                cmds.setAttr("{}.overrideRGBColors".format(shape), True)
                cmds.setAttr("{}.overrideColorRGB".format(shape), *self.color)
        cmds.parent(shape, transform, r=True, s=True)
        short_name = transform.rsplit("|", 1)[-1]
        shape = cmds.rename(shape, "{}Shape".format(short_name))
        cmds.delete(curve)
        if as_controller:
            cmds.controller(transform)
        logger.info("Created curve {} for transform {}".format(shape, transform))
        return transform

    def _get_transformed_points(self):
        matrix = self.transform_matrix.asMatrix()
        points = [OpenMaya.MPoint(*x) * matrix for x in self.cvs]
        points = [(p.x, p.y, p.z) for p in points]
        return points

    def translate_by(self, x, y, z, local=True):
        """Translate the curve cvs by the given values

        :param x: Translate X
        :param y: Translate Y
        :param z: Translate Z
        :param local: True for local space, False for world
        """
        space = OpenMaya.MSpace.kObject if local else OpenMaya.MSpace.kWorld
        self.transform_matrix.translateBy(OpenMaya.MVector(x, y, z), space)

    def set_translation(self, x, y, z, local=True):
        """Set the absolute translation of the curve shape.

        :param x: Translate X
        :param y: Translate Y
        :param z: Translate Z
        :param local: True for local space, False for world
        """
        space = OpenMaya.MSpace.kObject if local else OpenMaya.MSpace.kWorld
        self.transform_matrix.setTranslation(OpenMaya.MVector(x, y, z), space)

    def rotate_by(self, x, y, z, local=True):
        """Rotate the curve cvs by the given euler rotation values

        :param x: Rotate X
        :param y: Rotate Y
        :param z: Rotate Z
        :param local: True for local space, False for world
        """
        x, y, z = [v * 0.0174533 for v in [x, y, z]]
        space = OpenMaya.MSpace.kObject if local else OpenMaya.MSpace.kWorld
        self.transform_matrix.rotateBy(OpenMaya.MEulerRotation(x, y, z), space)

    def set_rotation(self, x, y, z):
        """Set the absolute rotation of the curve shape in euler rotations.

        :param x: Rotate X
        :param y: Rotate Y
        :param z: Rotate Z
        """
        x, y, z = [v * 0.0174533 for v in [x, y, z]]
        self.transform_matrix.setRotation(OpenMaya.MEulerRotation(x, y, z))

    def scale_by(self, x, y, z, local=True):
        """Scale the curve cvs by the given amount.

        :param x: Scale X
        :param y: Scale Y
        :param z: Scale Z
        :param local: True for local space, False for world
        """
        space = OpenMaya.MSpace.kObject if local else OpenMaya.MSpace.kWorld
        self.transform_matrix.scaleBy([x, y, z], space)

    def set_scale(self, x, y, z, local=True):
        """Set the absolute scale of the curve shape.

        :param x: Scale X
        :param y: Scale Y
        :param z: Scale Z
        :param local: True for local space, False for world
        """
        space = OpenMaya.MSpace.kObject if local else OpenMaya.MSpace.kWorld
        self.transform_matrix.setScale([x, y, z], space)


class CurveShapeEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, CurveShape):
            return {
                "cvs": obj.cvs,
                "degree": obj.degree,
                "form": obj.form,
                "knots": obj.knots,
                "color": obj.color,
                "transform": obj.transform,
            }
        return json.JSONEncoder.default(self, obj)


def rotate_components(rx, ry, rz, nodes=None):
    """Rotate the given nodes' components the given number of degrees about each axis.

    :param rx: Degrees around x.
    :param ry: Degrees around y.
    :param rz: Degrees around z.
    :param nodes: Optional list of curves.
    """
    if nodes is None:
        nodes = cmds.ls(sl=True) or []
    for node in nodes:
        pivot = cmds.xform(node, q=True, rp=True, ws=True)
        cmds.rotate(rx, ry, rz, "{0}.cv[*]".format(node), r=True, p=pivot, os=True, fo=True)


def _dag_path(node):
    """DAG nodeのAPI 2.0 MDagPathを返す。"""
    selection = OpenMaya.MSelectionList()
    selection.add(node)
    return selection.getDagPath(0)


def mirror_curve(source, destination):
    """Mirrors the curve on source across the YZ plane to destination.

    The cvs will be mirrored in world space no matter the transform of destination.

    :param source: Source transform
    :param destination: Destination transform
    :return: The mirrored CurveShape object
    """
    source_curve = CurveShape(source)

    path_source = _dag_path(source)
    matrix = path_source.inclusiveMatrix()

    path_destination = _dag_path(destination)
    inverse_matrix = path_destination.inclusiveMatrixInverse()

    world_cvs = [OpenMaya.MPoint(*x) * matrix for x in source_curve.cvs]
    for cv in world_cvs:
        cv.x *= -1
    local_cvs = [p * inverse_matrix for p in world_cvs]
    source_curve.cvs = [(p.x, p.y, p.z) for p in local_cvs]
    is_controller = cmds.controller(source, q=True, isController=True)
    source_curve.transform = destination
    source_curve.create(destination, as_controller=is_controller)
    return source_curve


_SIDE_TOKENS = {
    "l": "R",
    "r": "L",
    "lf": "rt",
    "rt": "lf",
    "left": "right",
    "right": "left",
}


def _mirrored_control_name(source):
    """namespaceを保持して最初のside tokenを反転したcontrol名を返す。"""
    leaf = source.rsplit("|", 1)[-1]
    namespace, separator, base = leaf.rpartition(":")
    if not separator:
        namespace = ""
        base = leaf
    parts = base.split("_")
    for index, part in enumerate(parts):
        opposite = _SIDE_TOKENS.get(part.casefold())
        if opposite is None:
            continue
        if part.isupper():
            opposite = opposite.upper()
        elif part.islower():
            opposite = opposite.lower()
        elif part[:1].isupper():
            opposite = opposite.capitalize()
        parts[index] = opposite
        mirrored = "_".join(parts)
        return "{}:{}".format(namespace, mirrored) if namespace else mirrored
    raise ValueError("side tokenがありません: {}".format(leaf))


def _curve_data_from_shape(shape):
    """1つのNURBS curve shapeをCurveShapeデータへ変換する。"""
    function = OpenMaya.MFnNurbsCurve(_dag_path(shape))
    degree = function.degree
    form = cmds.getAttr(shape + ".form")
    points = function.cvPositions(OpenMaya.MSpace.kObject)
    cvs = [(point.x, point.y, point.z) for point in points]
    if form == 2:
        cvs = cvs[:-degree]
    color = None
    if cmds.getAttr(shape + ".overrideEnabled"):
        if cmds.getAttr(shape + ".overrideRGBColors"):
            color = cmds.getAttr(shape + ".overrideColorRGB")[0]
        else:
            color = cmds.getAttr(shape + ".overrideColor")
    return CurveShape(
        cvs=cvs,
        degree=degree,
        form=form,
        knots=list(function.knots()),
        color=color,
    )


def mirror_control_shapes(source, destination=None):
    """sourceの全curve shapeをworld YZ反転して反対側controlへ差し替える。

    destination transform自体とその接続、表示設定は維持する。destination省略時は
    L/R、lf/rt、left/rightのunderscore区切りtokenから同namespace内で解決する。
    """
    source_matches = cmds.ls(source, long=True, type="transform") or []
    if len(source_matches) != 1:
        raise ValueError("source controlを一意に解決できません: {}".format(source))
    source = source_matches[0]
    if destination is None:
        destination = _mirrored_control_name(source)
    destination_matches = cmds.ls(destination, long=True, type="transform") or []
    if len(destination_matches) != 1:
        raise ValueError("mirror先controlを一意に解決できません: {}".format(destination))
    destination = destination_matches[0]
    if (cmds.ls(source, uuid=True) or [None])[0] == (cmds.ls(destination, uuid=True) or [None])[0]:
        raise ValueError("sourceとdestinationは別controlにしてください。")
    source_shapes = _curve_shapes(source)
    if not source_shapes:
        raise ValueError("sourceにNURBS curve shapeがありません: {}".format(source))
    if not _curve_shapes(destination):
        raise ValueError("destinationにNURBS curve shapeがありません: {}".format(destination))

    source_matrix = _dag_path(source).inclusiveMatrix()
    destination_inverse = _dag_path(destination).inclusiveMatrixInverse()
    curves = []
    for shape in source_shapes:
        curve = _curve_data_from_shape(shape)
        world_points = [OpenMaya.MPoint(*point) * source_matrix for point in curve.cvs]
        for point in world_points:
            point.x *= -1.0
        local_points = [point * destination_inverse for point in world_points]
        curve.cvs = [(point.x, point.y, point.z) for point in local_points]
        curves.append(curve)
    swap_curve_shapes([destination], curves)
    return destination


def mirror_selected_control_shapes():
    """選択した1つのcontrol shapeを名前解決した反対側へmirrorする。"""
    selected = cmds.ls(selection=True, long=True, type="transform") or []
    if len(selected) != 1:
        raise ValueError("mirror元controlを1つ選択してください。")
    return mirror_control_shapes(selected[0])


def _curve_shapes(transform):
    """transform直下の表示用NURBS curve shapeをロングパスで返す。"""
    return (
        cmds.listRelatives(
            transform,
            shapes=True,
            noIntermediate=True,
            fullPath=True,
            type="nurbsCurve",
        )
        or []
    )


def select_control_cvs(transforms=None):
    """選択control直下にある全NURBS curve CVを選択する。

    Args:
        transforms: 対象transform名。省略時は現在選択を使用する。

    Returns:
        選択したCV componentの一覧。
    """
    if transforms is None:
        transforms = cmds.ls(selection=True, long=True, type="transform") or []

    components = []
    seen = set()
    for transform in transforms or []:
        matches = cmds.ls(transform, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("controlを一意に解決できません: {}".format(transform))
        target = matches[0]
        node_uuid = (cmds.ls(target, uuid=True) or [None])[0]
        if node_uuid in seen:
            continue
        seen.add(node_uuid)
        shapes = _curve_shapes(target)
        if not shapes:
            raise ValueError("NURBS curve shapeがありません: {}".format(target))
        for shape in shapes:
            components.extend(cmds.ls(shape + ".cv[*]", flatten=True, long=True) or [])

    if not components:
        raise ValueError("編集するcontrolを1つ以上選択してください。")
    cmds.select(components, replace=True)
    return components


def set_control_color(rgb, transforms=None):
    """control shapeへRGB override colorを単一Undoで設定する。

    Args:
        rgb: 0から1の範囲にあるRGB値。
        transforms: 対象control。省略時は現在選択を使用する。

    Returns:
        色を変更したcurve shapeのロングパス一覧。
    """
    if not isinstance(rgb, (list, tuple)) or len(rgb) != 3:
        raise ValueError("RGBは3要素のlistまたはtupleで指定してください。")
    if any(
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or not 0.0 <= float(value) <= 1.0
        for value in rgb
    ):
        raise ValueError("RGB値は0から1の有限数で指定してください。")
    color = tuple(float(value) for value in rgb)

    if transforms is None:
        transforms = cmds.ls(selection=True, long=True, type="transform") or []
    shapes = []
    seen = set()
    for transform in transforms or []:
        matches = cmds.ls(transform, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("controlを一意に解決できません: {}".format(transform))
        target = matches[0]
        node_uuid = (cmds.ls(target, uuid=True) or [None])[0]
        if node_uuid in seen:
            continue
        seen.add(node_uuid)
        target_shapes = _curve_shapes(target)
        if not target_shapes:
            raise ValueError("NURBS curve shapeがありません: {}".format(target))
        for shape in target_shapes:
            blocked = [
                attribute
                for attribute in ("overrideEnabled", "overrideRGBColors", "overrideColorRGB")
                if not cmds.getAttr("{}.{}".format(shape, attribute), settable=True)
            ]
            if blocked:
                raise ValueError("表示色が編集できません: {} ({})".format(shape, ", ".join(blocked)))
        shapes.extend(target_shapes)
    if not shapes:
        raise ValueError("色を変更するcontrolを1つ以上選択してください。")

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Set Control Color")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Set Control Color")
    failed = False
    try:
        for shape in shapes:
            cmds.setAttr(shape + ".overrideEnabled", True)
            cmds.setAttr(shape + ".overrideRGBColors", True)
            cmds.setAttr(shape + ".overrideColorRGB", *color, type="double3")
        cmds.select(selection, replace=True) if selection else cmds.select(clear=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return shapes


def combine_control_shapes(transforms=None):
    """複数controlを最後のtransformへworld形状を維持して結合する。

    最後以外のsource transformは削除する。親子関係にある選択や参照nodeは、
    targetや未選択の子階層を誤って削除しないよう編集前に拒否する。

    Args:
        transforms: 選択順のcontrol transform名。省略時は現在選択を使用する。

    Returns:
        結合先controlのロングパス。
    """
    if transforms is None:
        transforms = cmds.ls(selection=True, long=True, type="transform") or []

    resolved = []
    seen = set()
    for transform in transforms or []:
        matches = cmds.ls(transform, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("controlを一意に解決できません: {}".format(transform))
        target = matches[0]
        node_uuid = (cmds.ls(target, uuid=True) or [None])[0]
        if node_uuid in seen:
            raise ValueError("同じcontrolを複数回指定できません: {}".format(target))
        seen.add(node_uuid)
        resolved.append(target)
    if len(resolved) < 2:
        raise ValueError("結合するcontrolを2つ以上選択してください。")

    for index, transform in enumerate(resolved):
        if cmds.referenceQuery(transform, isNodeReferenced=True):
            raise ValueError("参照controlは結合できません: {}".format(transform))
        if not _curve_shapes(transform):
            raise ValueError("NURBS curve shapeがありません: {}".format(transform))
        descendants = set(cmds.listRelatives(transform, allDescendents=True, fullPath=True, type="transform") or [])
        if index < len(resolved) - 1 and descendants:
            raise ValueError("子transformを持つsource controlは結合できません: {}".format(transform))

    destination = resolved[-1]
    destination_inverse = _dag_path(destination).inclusiveMatrixInverse()
    plans = []
    for source in resolved[:-1]:
        source_matrix = _dag_path(source).inclusiveMatrix()
        for shape in _curve_shapes(source):
            curve = _curve_data_from_shape(shape)
            world_points = [OpenMaya.MPoint(*point) * source_matrix for point in curve.cvs]
            local_points = [point * destination_inverse for point in world_points]
            curve.cvs = [(point.x, point.y, point.z) for point in local_points]
            plans.append((curve, _shape_display_state(shape)))

    undo_utils.require_enabled("Combine Control Shapes")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Combine Control Shapes")
    failed = False
    try:
        for curve, state in plans:
            before = set(_curve_shapes(destination))
            curve.create(destination, as_controller=False)
            created = [shape for shape in _curve_shapes(destination) if shape not in before]
            if len(created) != 1:
                raise RuntimeError("curve shapeを一意に作成できません: {}".format(destination))
            _apply_shape_display_state(created[0], state)
        cmds.delete(resolved[:-1])
        destination = (cmds.ls(destination, long=True, type="transform") or [destination])[0]
        cmds.select(destination, replace=True)
    except Exception:
        failed = True
        raise
    finally:
        cmds.undoInfo(closeChunk=True)
        if failed:
            cmds.undo()
    return destination


def _shape_display_state(shape):
    """shape差し替え時に保持する表示状態を取得する。"""
    visibility_sources = cmds.listConnections(shape + ".visibility", source=True, destination=False, plugs=True) or []
    if len(visibility_sources) > 1:
        raise RuntimeError("visibility入力を一意に解決できません: {}".format(shape))
    return {
        "visibility": cmds.getAttr(shape + ".visibility"),
        "override_enabled": cmds.getAttr(shape + ".overrideEnabled"),
        "override_rgb": cmds.getAttr(shape + ".overrideRGBColors"),
        "override_color": cmds.getAttr(shape + ".overrideColor"),
        "override_color_rgb": cmds.getAttr(shape + ".overrideColorRGB")[0],
        "override_display_type": cmds.getAttr(shape + ".overrideDisplayType"),
        "visibility_source": visibility_sources[0] if visibility_sources else None,
    }


def _apply_shape_display_state(shape, state):
    """保存済み表示状態を新しいcurve shapeへ適用する。"""
    cmds.setAttr(shape + ".visibility", state["visibility"])
    cmds.setAttr(shape + ".overrideEnabled", state["override_enabled"])
    cmds.setAttr(shape + ".overrideRGBColors", state["override_rgb"])
    cmds.setAttr(shape + ".overrideColor", state["override_color"])
    cmds.setAttr(shape + ".overrideColorRGB", *state["override_color_rgb"], type="double3")
    cmds.setAttr(shape + ".overrideDisplayType", state["override_display_type"])
    if state["visibility_source"]:
        cmds.connectAttr(state["visibility_source"], shape + ".visibility", force=True)


def swap_curve_shapes(transforms, curves):
    """transform接続を維持してcontrol curve shapeだけを差し替える。

    Args:
        transforms: 差し替え対象のtransform名。
        curves: 新規作成に使う :class:`CurveShape` の列。

    Returns:
        差し替えたtransformのロングパス一覧。
    """
    if not curves or not all(isinstance(curve, CurveShape) and curve.cvs for curve in curves):
        raise ValueError("有効なCurveShapeを1つ以上指定してください。")
    resolved = []
    plans = []
    seen = set()
    for transform in transforms or []:
        matches = cmds.ls(transform, long=True, type="transform") or []
        if len(matches) != 1:
            raise ValueError("transformを一意に解決できません: {}".format(transform))
        target = matches[0]
        node_uuid = (cmds.ls(target, uuid=True) or [None])[0]
        if node_uuid in seen:
            continue
        seen.add(node_uuid)
        old_shapes = _curve_shapes(target)
        if not old_shapes:
            raise ValueError("NURBS curve shapeがありません: {}".format(target))
        plans.append((target, old_shapes, [_shape_display_state(shape) for shape in old_shapes]))
        resolved.append(target)
    if not plans:
        raise ValueError("差し替え対象のcontrolを1つ以上指定してください。")

    selection = cmds.ls(selection=True, long=True) or []
    undo_utils.require_enabled("Swap Control Shapes")
    cmds.undoInfo(openChunk=True, chunkName="YWTA Swap Control Shapes")
    failed = False
    try:
        for target, old_shapes, states in plans:
            before = set(old_shapes)
            for curve in curves:
                curve.create(target, as_controller=False)
            new_shapes = [shape for shape in _curve_shapes(target) if shape not in before]
            if len(new_shapes) != len(curves):
                raise RuntimeError("作成したcurve shape数が一致しません: {}".format(target))
            for index, shape in enumerate(new_shapes):
                state = states[index] if len(states) == len(new_shapes) else states[0]
                _apply_shape_display_state(shape, state)
            cmds.delete(old_shapes)
        valid_selection = [item for item in selection if cmds.objExists(item)]
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
    return resolved


def swap_selected_curves(file_path=None):
    """選択controlのshapeをJSON内のcurveへ差し替える。"""
    transforms = cmds.ls(selection=True, long=True, type="transform") or []
    if not transforms:
        raise ValueError("差し替えるcontrolを1つ以上選択してください。")
    curves = load_curves(file_path)
    if curves is None:
        return None
    return swap_curve_shapes(transforms, curves)


def get_knots(curve):
    """Gets the list of knots of a curve so it can be recreated.

    :param curve: Curve to query.
    :return: A list of knot values that can be passed into the curve creation command.
    """
    shape = shortcuts.get_shape(curve)
    return list(OpenMaya.MFnNurbsCurve(_dag_path(shape)).knots())


def documentation():
    webbrowser.open(HELP_URL)


def get_control_paths_in_library():
    """Get the file paths of all controls in the library.

    :return: List of file paths
    """
    controls = [os.path.splitext(x)[0] for x in os.listdir(CONTROLS_DIRECTORY) if x.endswith(".json")]
    controls.sort()
    return controls
