"""Joint Edit Tools

A comprehensive tool for joint orientation, manipulation, and editing operations.
Provides both UI and programmatic interfaces for common joint editing tasks.

Usage:
    from ywta.rig.joint_edit_tools import JointEditToolsWindow
    JointEditToolsWindow.show_window()

    # Or use functions directly:
    from ywta.rig.joint_edit_tools import zero_orient, align_with_child
    zero_orient(cmds.ls(sl=True, type="joint"))
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import logging
from functools import partial
from typing import List, Optional

import maya.cmds as cmds

# Import from core modules instead of deprecated shortcuts
from ywta.core.ui_utils import SingletonWindowMixin
from ywta.rig import create_joint, joint_insert, joint_mirror, joint_orient

logger = logging.getLogger(__name__)

# Constants
MESSAGE_ATTRIBUTE = "ywta_jointEditTools"
ORIENT_GROUP = "ywta_orient_grp"
DEFAULT_OFFSET_VALUE = 90.0
UI_MARGIN_WIDTH = 4
BUTTON_HEIGHT = 30
ICON_SIZE = 20


class Axis:
    """Axis enumeration for joint operations."""

    X = "X"
    Y = "Y"
    Z = "Z"


class JointEditToolsWindow(SingletonWindowMixin):
    """Main window for joint editing tools.

    Provides a comprehensive UI for joint orientation, manipulation,
    and utility operations. Uses singleton pattern to ensure only
    one instance exists at a time.
    """

    def __init__(self):
        """Initialize the joint edit tools window."""
        self._setup_window()
        self._create_ui()
        self._show_window()

    def _setup_window(self):
        """Setup the main window properties."""
        name = "ywta_joint_edit_tools"

        # Clean up existing window
        if cmds.window(name, exists=True):
            cmds.deleteUI(name, window=True)
        if cmds.windowPref(name, exists=True):
            cmds.windowPref(name, remove=True)

        self.window = cmds.window(
            name,
            title="YWTA Joint Edit Tools",
            widthHeight=(380, 420),
            sizeable=True,
            minimizeButton=True,
            maximizeButton=False,
        )

    def _create_ui(self):
        """Create the user interface."""
        cmds.columnLayout(adjustableColumn=True)

        self._create_joints_section()
        self._create_side_selection_section()
        self._create_utility_section()
        self._create_quick_actions_section()
        self._create_offset_orient_section()

    def _create_joints_section(self):
        """Jointを作成する。

        ジョイント挿入機能のUIを提供し、使用方法を明確に表示する。
        """
        cmds.frameLayout(
            borderVisible=False,
            label="ジョイント作成操作",
            collapsable=True,
            marginWidth=UI_MARGIN_WIDTH,
            collapse=False,
        )

        # jointを新規作成するUIを作成
        cmds.rowColumnLayout(numberOfColumns=1, adjustableColumn=1, columnSpacing=(2, 5))
        self.create_joint_field = cmds.textField(
            text="joint",
            annotation="新規ジョイントの名前を入力してください",
            placeholderText="ジョイント名を入力",
        )
        cmds.button(
            label="Add Joint",
            command=self._create_joint,
            annotation="選択された2つのジョイント間に均等に配置されたジョイントを挿入します",
            height=30,  # ボタンを大きくして目立たせる
        )
        cmds.setParent("..")

        # 説明テキストを追加
        cmds.columnLayout(adjustableColumn=True)
        cmds.setParent("..")

        # 入力フィールドとボタンのレイアウト
        cmds.rowColumnLayout(numberOfColumns=2, adjustableColumn=1, columnSpacing=(2, 5))

        # ラベルを追加して分かりやすくする
        cmds.text(label="挿入するジョイント数:", align="right")
        self.insert_joint_field = cmds.intField(
            minValue=1,
            maxValue=99,
            value=1,
            annotation="選択された親ジョイントと子ジョイントの間に挿入するジョイント数",
        )

        cmds.text(label="名前パターン:", align="right")
        self.insert_joint_name_field = cmds.textField(
            text="insert_##_jnt",
            annotation="連番の桁数を#で指定します",
        )

        # スペーサー
        cmds.text(label="")
        cmds.button(
            label="ジョイントを挿入",
            command=self._insert_joints,
            annotation="選択された2つのジョイント間に均等に配置されたジョイントを挿入します",
            height=30,  # ボタンを大きくして目立たせる
        )
        cmds.setParent("..")
        cmds.setParent("..")

    def _create_side_selection_section(self):
        """Create the side selection buttons."""
        cmds.frameLayout(
            borderVisible=False,
            label="Side Assignment",
            collapsable=True,
            marginWidth=UI_MARGIN_WIDTH,
            collapse=False,
        )

        cmds.gridLayout(numberOfColumns=3, cellWidthHeight=(120, BUTTON_HEIGHT))
        cmds.button(
            label="Left",
            command=self._set_left,
            annotation="Set selected joints and hierarchy to Left side",
        )
        cmds.button(
            label="Center",
            command=self._set_center,
            annotation="Set selected joints and hierarchy to Center",
        )
        cmds.button(
            label="Right",
            command=self._set_right,
            annotation="Set selected joints and hierarchy to Right side",
        )
        cmds.setParent("..")
        cmds.setParent("..")

    def _create_utility_section(self):
        """Create the utility section."""
        cmds.frameLayout(
            borderVisible=False,
            label="Utility",
            collapsable=True,
            marginWidth=UI_MARGIN_WIDTH,
            collapse=False,
        )

        self.is_recursive_hierarchy = cmds.checkBox(
            label="Recursive Hierarchy",
            value=True,
            align="left",
            annotation="Apply operations to entire hierarchy below selected joints",
        )

        cmds.gridLayout(numberOfColumns=3, cellWidthHeight=(120, BUTTON_HEIGHT))
        cmds.button(
            label="Show Axis",
            command=self._show_axis,
            annotation="Display local rotation axes for selected joints",
        )
        cmds.button(
            label="Hide Axis",
            command=self._hide_axis,
            annotation="Hide local rotation axes for selected joints",
        )
        cmds.button(
            label="Freeze Joint Rotation",
            command=self._freeze_joint_rotation,
            annotation="Freeze rotation values into joint orient for bound joints",
        )
        cmds.button(
            label="Reset Bind Pose",
            command=self._reset_bind_pose,
            annotation="Reset and recreate bind pose for selected joints/meshes",
        )
        cmds.button(
            label="Mirror Joint",
            command=self._mirror_joint,
            annotation="Mirror selected joints to opposite side",
        )
        cmds.button(
            label="Mirror Joint Attributes",
            command=self._mirror_joint_attributes,
            annotation="Mirror joint attributes (translate, jointOrient) to opposite side",
        )
        cmds.button(
            label="Toggle SSC",
            command=self._toggle_segment_scale_compensate,
            annotation="Toggle Segment Scale Compensate for selected joints",
        )
        cmds.setParent("..")
        cmds.setParent("..")

    def _create_quick_actions_section(self):
        """Create the quick actions section."""
        cmds.frameLayout(
            borderVisible=False,
            label="Quick Actions",
            collapsable=True,
            marginWidth=UI_MARGIN_WIDTH,
            collapse=False,
        )

        cmds.gridLayout(numberOfColumns=2, cellWidthHeight=(180, 65))
        cmds.button(
            label="Align Up With Child",
            command=self._align_with_child,
            annotation="Orient joint to point towards its child joint",
        )
        cmds.button(
            label="Zero Orient",
            command=self._zero_orient,
            annotation="Reset joint orientation to zero",
        )
        cmds.button(
            label="Orient to World",
            command=self._orient_to_world,
            annotation="Orient joint to match world coordinate system",
        )
        cmds.setParent("..")
        cmds.setParent("..")

    def _create_offset_orient_section(self):
        """Create the offset orientation section."""
        cmds.frameLayout(
            borderVisible=False,
            label="Offset Orientation",
            collapsable=True,
            marginWidth=UI_MARGIN_WIDTH,
            collapse=False,
        )

        cmds.rowColumnLayout(numberOfColumns=4, columnSpacing=(1, 5))

        # X Axis controls
        self._create_axis_controls("X", self._offset_orient_x)
        # Y Axis controls
        self._create_axis_controls("Y", self._offset_orient_y)
        # Z Axis controls
        self._create_axis_controls("Z", self._offset_orient_z)

        cmds.setParent("..")
        cmds.setParent("..")

    def _create_axis_controls(self, axis: str, callback):
        """Create controls for a specific axis.

        Args:
            axis: The axis name (X, Y, Z)
            callback: The callback function for this axis
        """
        label_width = 60

        cmds.text(label=f"Offset {axis}", align="right", width=label_width)

        # Decrease button
        cmds.iconTextButton(
            style="iconOnly",
            image1="nudgeLeft.png",
            height=ICON_SIZE,
            width=ICON_SIZE,
            command=partial(callback, direction=-1),
            annotation=f"Decrease {axis} orientation",
        )

        # Value field
        field_name = f"offset_{axis.lower()}"
        setattr(
            self,
            field_name,
            cmds.floatField(
                value=DEFAULT_OFFSET_VALUE,
                annotation=f"Offset amount for {axis} axis in degrees",
            ),
        )

        # Increase button
        cmds.iconTextButton(
            style="iconOnly",
            image1="nudgeRight.png",
            height=ICON_SIZE,
            width=ICON_SIZE,
            command=partial(callback, direction=1),
            annotation=f"Increase {axis} orientation",
        )

    def _show_window(self):
        """Show the window."""
        cmds.showWindow(self.window)

    def _create_joint(self, *_args):
        """入力名で選択中心へjointを安全に作成する。"""
        joint_name = ""
        try:
            joint_name = cmds.textField(self.create_joint_field, query=True, text=True)
            created = create_joint.create_joint_at_selection(name=joint_name)
            logger.info(f"Created joint: {created}")
        except Exception as e:
            logger.error(f"Failed to create joint '{joint_name}': {e}")
            cmds.warning(f"Failed to create joint '{joint_name}': {e}")

    # Event handlers
    def _insert_joints(self, *args):
        """選択した隣接親子joint間へ安全にjointを挿入する。"""
        try:
            joint_count = cmds.intField(self.insert_joint_field, query=True, value=True)
            name_pattern = cmds.textField(self.insert_joint_name_field, query=True, text=True)
            joint_insert.insert_selected(count=joint_count, name_pattern=name_pattern)
            logger.info(f"Inserted {joint_count} joints")
        except Exception as e:
            logger.error(f"Failed to insert joints: {e}")
            cmds.warning(f"Failed to insert joints: {e}")

    def _zero_orient(self, *args):
        """Zero orient selected joints."""
        joints = self._get_selected_joints()
        if joints:
            zero_orient(joints)

    def _align_with_child(self, *args):
        """選択joint階層を安全に子方向へorientする。"""
        try:
            joint_orient.orient_selected(include_descendants=self._get_recursive_setting())
        except Exception as error:
            logger.error(f"Failed to orient joints to children: {error}")
            cmds.warning(f"Failed to orient joints to children: {error}")

    def _orient_to_world(self, *args):
        """Orient selected joints to world coordinates."""
        joints = self._get_selected_joints()
        if joints:
            orient_to_world(joints)

    def _offset_orient_x(self, direction: int):
        """Offset X orientation of selected joints."""
        joints = self._get_selected_joints()
        if joints:
            amount = cmds.floatField(self.offset_x, query=True, value=True) * direction
            offset_orient(joints, amount, Axis.X)

    def _offset_orient_y(self, direction: int):
        """Offset Y orientation of selected joints."""
        joints = self._get_selected_joints()
        if joints:
            amount = cmds.floatField(self.offset_y, query=True, value=True) * direction
            offset_orient(joints, amount, Axis.Y)

    def _offset_orient_z(self, direction: int):
        """Offset Z orientation of selected joints."""
        joints = self._get_selected_joints()
        if joints:
            amount = cmds.floatField(self.offset_z, query=True, value=True) * direction
            offset_orient(joints, amount, Axis.Z)

    def _set_left(self, *args):
        """Set selected nodes to left side."""
        self._set_side(1)

    def _set_center(self, *args):
        """Set selected nodes to center."""
        self._set_side(0)

    def _set_right(self, *args):
        """Set selected nodes to right side."""
        self._set_side(2)

    def _show_axis(self, *args):
        """Show local rotation axes for selected joints."""
        joints = self._get_selected_joints()
        recursive = self._get_recursive_setting()
        for joint in joints:
            display_local_rotation_axis(joint, state=True, recursive=recursive)

    def _hide_axis(self, *args):
        """Hide local rotation axes for selected joints."""
        joints = self._get_selected_joints()
        recursive = self._get_recursive_setting()
        for joint in joints:
            display_local_rotation_axis(joint, state=False, recursive=recursive)

    def _freeze_joint_rotation(self, *args):
        """Freeze joint rotation for bound joints."""
        try:
            selected_joints = self._get_selected_joints()
            recursive = self._get_recursive_setting()

            if recursive:
                children = cmds.listRelatives(selected_joints, allDescendents=True, type="joint") or []
                selected_joints.extend(children)

            freeze_joint_rotation(selected_joints)
            logger.info(f"Froze rotation for {len(selected_joints)} joints")
        except Exception as e:
            logger.error(f"Failed to freeze joint rotation: {e}")
            cmds.warning(f"Failed to freeze joint rotation: {e}")

    def _reset_bind_pose(self, *args):
        """Reset bind pose for selected objects."""
        try:
            reset_bind_pose()
            logger.info("Reset bind pose completed")
        except Exception as e:
            logger.error(f"Failed to reset bind pose: {e}")
            cmds.warning(f"Failed to reset bind pose: {e}")

    def _mirror_joint(self, *args):
        """選択root joint以下を安全な静的階層としてmirrorする。"""
        try:
            created = joint_mirror.mirror_selected_hierarchy()
            logger.info(f"Mirrored {len(created)} joints")
        except Exception as e:
            logger.error(f"Failed to mirror joints: {e}")
            cmds.warning(f"Failed to mirror joints: {e}")

    def _mirror_joint_attributes(self, *args):
        """Mirror joint attributes."""
        try:
            selected_joints = self._get_selected_joints()
            for joint in selected_joints:
                mirror_joint_attributes(joint)
            logger.info(f"Mirrored attributes for {len(selected_joints)} joints")
        except Exception as e:
            logger.error(f"Failed to mirror joint attributes: {e}")
            cmds.warning(f"Failed to mirror joint attributes: {e}")

    def _toggle_segment_scale_compensate(self, *args):
        """Toggle segment scale compensate for selected joints."""
        try:
            joints = self._get_selected_joints()
            if not joints:
                return

            # Use the first joint's SSC state as reference
            is_ssc = cmds.getAttr(f"{joints[0]}.segmentScaleCompensate")
            recursive = self._get_recursive_setting()

            toggle_segment_scale_compensate(joints, is_ssc, recursive)
            logger.info(f"Toggled SSC for {len(joints)} joints")
        except Exception as e:
            logger.error(f"Failed to toggle segment scale compensate: {e}")
            cmds.warning(f"Failed to toggle segment scale compensate: {e}")

    def _set_side(self, side: int):
        """Set side attribute for selected nodes and their hierarchy.

        Args:
            side: Side value (0=Center, 1=Left, 2=Right)
        """
        try:
            nodes = cmds.ls(selection=True)
            if not nodes:
                cmds.warning("No objects selected")
                return

            count = 0
            for node in nodes:
                hierarchy = cmds.listRelatives(node, allDescendents=True) or []
                hierarchy.append(node)

                for child_node in hierarchy:
                    attr = f"{child_node}.side"
                    if cmds.objExists(attr):
                        cmds.setAttr(attr, side)
                        count += 1

            side_names = {0: "Center", 1: "Left", 2: "Right"}
            logger.info(f"Set {count} nodes to {side_names.get(side, 'Unknown')} side")
        except Exception as e:
            logger.error(f"Failed to set side: {e}")
            cmds.warning(f"Failed to set side: {e}")

    def _get_selected_joints(self) -> List[str]:
        """Get currently selected joints.

        Returns:
            List of selected joint names
        """
        joints = cmds.ls(selection=True, type="joint") or []
        if not joints:
            cmds.warning("No joints selected")
        return joints

    def _get_recursive_setting(self) -> bool:
        """Get the recursive hierarchy setting.

        Returns:
            True if recursive operations should be performed
        """
        return cmds.checkBox(self.is_recursive_hierarchy, query=True, value=True)


# Utility Functions
def display_local_rotation_axis(obj: str, state: bool = True, recursive: bool = True):
    """Display or hide local rotation axis for an object.

    Args:
        obj: Object name
        state: True to show, False to hide
        recursive: Apply to children recursively
    """
    if not cmds.objExists(f"{obj}.displayLocalAxis"):
        return

    try:
        cmds.setAttr(f"{obj}.displayLocalAxis", state)

        if recursive:
            children = cmds.listRelatives(obj, children=True, type="transform") or []
            for child in children:
                child_path = f"{obj}|{child}"
                display_local_rotation_axis(child_path, state, recursive)
    except Exception as e:
        logger.warning(f"Failed to set display local axis for {obj}: {e}")


def toggle_segment_scale_compensate(joints: List[str], status: bool, recursive: bool = True):
    """Toggle segment scale compensate for joints.

    Args:
        joints: List of joint names
        status: Current SSC status to toggle from
        recursive: Apply recursively to children
    """
    for joint in joints:
        if cmds.nodeType(joint) != "joint":
            continue

        try:
            cmds.setAttr(f"{joint}.segmentScaleCompensate", not status)

            if recursive:
                children = cmds.listRelatives(joint, children=True, type="joint") or []
                toggle_segment_scale_compensate(children, status, recursive)
        except Exception as e:
            logger.warning(f"Failed to toggle SSC for {joint}: {e}")


def get_mirrored_joint_name(joint: str, word1: str = "Left", word2: str = "Right") -> Optional[str]:
    """Get the mirrored joint name by replacing side indicators.

    Args:
        joint: Original joint name
        word1: First side indicator (default: "Left")
        word2: Second side indicator (default: "Right")

    Returns:
        Mirrored joint name or None if no side indicator found
    """
    if word1 in joint:
        return joint.replace(word1, word2)
    elif word2 in joint:
        return joint.replace(word2, word1)
    return None


def freeze_joint_rotation(joints: List[str]):
    """Freeze joint rotation values into joint orient for bound joints.

    Args:
        joints: List of joint names to freeze
    """
    for joint in joints:
        try:
            # Get current world rotation
            rotation = cmds.xform(joint, query=True, worldSpace=True, rotation=True)

            # Reset joint orient
            cmds.setAttr(f"{joint}.jointOrient", 0, 0, 0, type="double3")

            # Apply world rotation
            cmds.xform(joint, worldSpace=True, rotation=rotation)

            # Get new object space rotation
            new_rotation = cmds.xform(joint, query=True, objectSpace=True, rotation=True)

            # Set joint orient to new rotation
            cmds.setAttr(f"{joint}.jointOrient", *new_rotation, type="double3")

            # Zero out rotation
            cmds.setAttr(f"{joint}.rotate", 0, 0, 0, type="double3")

        except Exception as e:
            logger.warning(f"Failed to freeze rotation for joint {joint}: {e}")


def reset_bind_pose():
    """Reset bind pose for selected objects."""
    selected = cmds.ls(selection=True, dagObjects=True)
    if not selected:
        cmds.warning("No objects selected")
        return

    # Handle meshes
    meshes = cmds.ls(selected, type="mesh")
    if meshes:
        skin_clusters = cmds.ls(cmds.listHistory(meshes), type="skinCluster")
        for skin_cluster in skin_clusters:
            try:
                joints = cmds.skinCluster(skin_cluster, query=True, influence=True)
                if joints:
                    # Delete existing bind poses
                    bind_poses = cmds.dagPose(joints, query=True, bindPose=True) or []
                    if bind_poses:
                        cmds.delete(bind_poses)

                    # Create new bind pose
                    cmds.dagPose(joints, save=True, bindPose=True)
            except Exception as e:
                logger.warning(f"Failed to reset bind pose for skin cluster {skin_cluster}: {e}")

    # Handle joints directly
    joints = cmds.ls(selected, type="joint")
    if joints:
        try:
            bind_poses = cmds.dagPose(joints, query=True, bindPose=True) or []
            if bind_poses:
                cmds.delete(bind_poses)

            cmds.dagPose(joints, save=True, bindPose=True)
        except Exception as e:
            logger.warning(f"Failed to reset bind pose for joints: {e}")


def mirror_joint(joint: str, word1: str = "Left", word2: str = "Right"):
    """Mirror a joint to the opposite side.

    Args:
        joint: Joint to mirror
        word1: First side indicator
        word2: Second side indicator
    """
    try:
        parent = cmds.listRelatives(joint, parent=True)
        if not parent:
            logger.warning(f"Joint {joint} has no parent, cannot mirror")
            return

        mirrored_parent = get_mirrored_joint_name(parent[0], word1, word2)
        if not mirrored_parent or not cmds.objExists(mirrored_parent):
            logger.warning(f"Mirrored parent {mirrored_parent} does not exist")
            return

        # Create mirrored joint
        position = cmds.xform(joint, query=True, worldSpace=True, translation=True)
        mirrored_position = [-position[0], position[1], position[2]]  # Mirror X

        cmds.select(mirrored_parent)
        new_joint = cmds.joint(position=mirrored_position)

        # Rename to mirrored name
        mirrored_name = get_mirrored_joint_name(joint, word1, word2)
        if mirrored_name:
            cmds.rename(new_joint, mirrored_name.split("|")[-1])

    except Exception as e:
        logger.error(f"Failed to mirror joint {joint}: {e}")


def mirror_joint_attributes(joint: str, word1: str = "Left", word2: str = "Right"):
    """Mirror joint attributes to the opposite side joint.

    Args:
        joint: Source joint
        word1: First side indicator
        word2: Second side indicator
    """
    try:
        mirrored_joint = get_mirrored_joint_name(joint, word1, word2)
        if not mirrored_joint or not cmds.objExists(mirrored_joint):
            logger.warning(f"Mirrored joint {mirrored_joint} does not exist")
            return

        # Mirror translate
        translate = cmds.getAttr(f"{joint}.translate")[0]
        cmds.setAttr(
            f"{mirrored_joint}.translate",
            -translate[0],
            translate[1],
            translate[2],
            type="double3",
        )

        # Mirror joint orient
        joint_orient = cmds.getAttr(f"{joint}.jointOrient")[0]
        cmds.setAttr(
            f"{mirrored_joint}.jointOrient",
            joint_orient[0],
            -joint_orient[1],
            -joint_orient[2],
            type="double3",
        )

    except Exception as e:
        logger.error(f"Failed to mirror attributes for joint {joint}: {e}")


def align_with_child(joints: List[str]):
    """従来APIから安全な静的joint orientを実行する。

    Args:
        joints: orientするjoint列。

    Returns:
        orientしたjointのロングパス。
    """
    return joint_orient.orient_to_children(joints)


def zero_orient(joints: List[str]):
    """Zero the joint orientation for given joints.

    Args:
        joints: List of joints to zero orient
    """
    for joint in joints:
        try:
            children = _unparent_children(joint)
            cmds.setAttr(f"{joint}.jointOrient", 0, 0, 0)
            _reparent_children(joint, children)
        except Exception as e:
            logger.warning(f"Failed to zero orient joint {joint}: {e}")

    if joints:
        cmds.select(joints)


def orient_to_world(joints: List[str]):
    """Orient joints to world coordinate system.

    Args:
        joints: List of joints to orient to world
    """
    for joint in joints:
        try:
            children = _unparent_children(joint)
            parent = cmds.listRelatives(joint, parent=True, path=True)
            original_name = joint.split("|")[-1]

            # Temporarily unparent to world
            if parent:
                joint = cmds.parent(joint, world=True)[0]

            # Orient to world
            cmds.joint(joint, edit=True, orientJoint="none", zeroScaleOrient=True)

            # Reparent if needed
            if parent:
                joint = cmds.parent(joint, parent)[0]
                joint = cmds.rename(joint, original_name)

            _reparent_children(joint, children)
        except Exception as e:
            logger.warning(f"Failed to orient joint {joint} to world: {e}")

    if joints:
        cmds.select(joints)


def offset_orient(joints: List[str], amount: float, axis: str):
    """Offset joint orientation by given amount on specified axis.

    Args:
        joints: List of joints to offset
        amount: Amount to offset in degrees
        axis: Axis to offset (X, Y, or Z)
    """
    for joint in joints:
        try:
            children = _unparent_children(joint)
            attribute = f"{joint}.jointOrient{axis}"

            current_orient = cmds.getAttr(attribute)
            new_orient = current_orient + amount
            cmds.setAttr(attribute, new_orient)

            _reparent_children(joint, children)
        except Exception as e:
            logger.warning(f"Failed to offset orient for joint {joint}: {e}")

    if joints:
        cmds.select(joints)


def _unparent_children(joint: str) -> List[str]:
    """Temporarily unparent children of a joint.

    Args:
        joint: Joint whose children to unparent

    Returns:
        List of unparented children
    """
    children = cmds.listRelatives(joint, children=True, path=True) or []
    unparented = []

    for child in children:
        try:
            unparented_child = cmds.parent(child, world=True)[0]
            unparented.append(unparented_child)
        except Exception as e:
            logger.warning(f"Failed to unparent child {child}: {e}")

    return unparented


def _reparent_children(joint: str, children: List[str]):
    """Reparent children back to a joint.

    Args:
        joint: Joint to reparent children to
        children: List of children to reparent
    """
    for child in children:
        try:
            cmds.parent(child, joint)
        except Exception as e:
            logger.warning(f"Failed to reparent child {child} to {joint}: {e}")


# Convenience function for showing the window
def show_window():
    """Show the Joint Edit Tools window."""
    JointEditToolsWindow.show_window()


# Maintain backward compatibility
OrientJointsWindow = JointEditToolsWindow
