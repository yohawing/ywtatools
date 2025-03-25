"""A tool used to orient joints with common orientations.

The tool mostly assumes the X axis is the primary axis and joints always rotate forward on the Z axis.

Usage:
import cmt.rig.orientjoints
cmt.rig.orientjoints.OrientJointsWindow()
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from functools import partial
import logging
import maya.cmds as cmds
import maya.api.OpenMaya as OpenMaya

import ywta.rig.skeleton as skeleton

# reload(skeleton)

log = logging.getLogger(__name__)
MESSAGE_ATTRIBUTE = "ywta_jointEditTools"
ORIENT_GROUP = "ywta_orient_grp"


class OrientJointsWindow(object):
    def __init__(self):
        name = "ywta_orient_edit_tools"
        if cmds.window(name, exists=True):
            cmds.deleteUI(name, window=True)
        if cmds.windowPref(name, exists=True):
            cmds.windowPref(name, remove=True)
        self.window = cmds.window(
            name, title="YWTA Joint Edit Tools", widthHeight=(358, 380)
        )
        cmds.columnLayout(adjustableColumn=True)
        margin_width = 4
        cmds.frameLayout(
            bv=False, label="Operations", collapsable=True, mw=margin_width
        )
        cmds.rowColumnLayout(numberOfColumns=2, adj=1)

        self.insert_joint_field = cmds.intField(minValue=1, value=1)
        cmds.button(label="Insert Joints", c=self.insert_joints)

        cmds.setParent("..")

        cmds.gridLayout(numberOfColumns=3, cellWidthHeight=(116, 30))
        cmds.button(label="Left", c=self.set_left)
        cmds.button(label="Center", c=self.set_center)
        cmds.button(label="Right", c=self.set_right)

        cmds.setParent("..")

        # region Utility
        cmds.frameLayout(bv=False, label="Utility", collapsable=True, mw=margin_width)
        self.isRecursiveHierarchy = cmds.checkBox(
            label="Recursive Hierarchy", value=True, align="left"
        )
        cmds.gridLayout(numberOfColumns=3, cellWidthHeight=(116, 30))
        cmds.button(label="Show Axis", c=self.show_axis)
        cmds.button(label="Hide Axis", c=self.hide_axis)
        cmds.button(label="Freeze Binded Joint", c=self.freezeJntRot)
        cmds.button(label="Reset Bind Pose", c=self.resetBindPose)
        cmds.button(label="Mirror Joint", c=self.mirrorJoint)
        cmds.button(label="Mirror Joint Attr", c=self.mirrorJointAttr)
        cmds.button(label="Toggle SSC", c=self.toggleSegmentScaleCompensate)

        cmds.setParent("..")
        cmds.setParent("..")
        # endregion

        # region Quick Actions
        cmds.frameLayout(
            bv=False, label="Quick Actions", collapsable=True, mw=margin_width
        )
        cmds.gridLayout(numberOfColumns=2, cellWidthHeight=(175, 65))
        cmds.button(label="Align Up With Child", command=self.align_with_child)
        cmds.button(label="Zero Orient", command=self.zero_orient)
        cmds.button(label="Orient to World", command=self.orient_to_world)
        cmds.rowColumnLayout(numberOfColumns=4)
        # endregion

        # region Offset Orient
        height = 20
        label_width = 60
        icon_left = "nudgeLeft.png"
        icon_right = "nudgeRight.png"
        cmds.text(label="Offset X", align="right", width=label_width)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_left,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_x, direction=-1),
        )
        self.offset_x = cmds.floatField(value=90.0)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_right,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_x, direction=1),
        )
        cmds.text(label="Offset Y", align="right", width=label_width)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_left,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_y, direction=-1),
        )
        self.offset_y = cmds.floatField(value=90.0)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_right,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_y, direction=1),
        )
        cmds.text(label="Offset Z", align="right", width=label_width)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_left,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_z, direction=-1),
        )
        self.offset_z = cmds.floatField(value=90.0)
        cmds.iconTextButton(
            style="iconOnly",
            image1=icon_right,
            label="spotlight",
            h=height,
            w=height,
            c=partial(self.offset_orient_z, direction=1),
        )
        # endregion

        # endregion

        cmds.showWindow(self.window)

    def insert_joints(self, *args):
        joint_count = cmds.intField(self.insert_joint_field, q=True, v=True)
        skeleton.insert_joints(joint_count=joint_count)

    def zero_orient(self, *args):
        joints = cmds.ls(sl=True, type="joint") or []
        zero_orient(joints)

    def align_with_child(self, *args):
        joints = cmds.ls(sl=True, type="joint") or []
        align_with_child(joints)

    def orient_to_world(self, *args):
        joints = cmds.ls(sl=True, type="joint") or []
        orient_to_world(joints)

    def offset_orient_x(self, direction):
        joints = cmds.ls(sl=True, type="joint") or []
        amount = cmds.floatField(self.offset_x, q=True, value=True) * direction
        offset_orient(joints, amount, Axis.x)

    def offset_orient_y(self, direction):
        joints = cmds.ls(sl=True, type="joint") or []
        amount = cmds.floatField(self.offset_y, q=True, value=True) * direction
        offset_orient(joints, amount, Axis.y)

    def offset_orient_z(self, direction):
        joints = cmds.ls(sl=True, type="joint") or []
        amount = cmds.floatField(self.offset_z, q=True, value=True) * direction
        offset_orient(joints, amount, Axis.z)

    def set_left(self, *args):
        self.set_side(1)

    def set_center(self, *args):
        self.set_side(0)

    def set_right(self, *args):
        self.set_side(2)

    def show_axis(self, *args):
        joints = cmds.ls(sl=True, type="joint") or []
        recursive = cmds.checkBox(self.isRecursiveHierarchy, query=True, value=True)
        for joint in joints:
            displayLRA(joint, state=True, recursive=recursive)

    def hide_axis(self, *args):
        joints = cmds.ls(sl=True, type="joint") or []
        recursive = cmds.checkBox(self.isRecursiveHierarchy, query=True, value=True)
        for joint in joints:
            displayLRA(joint, state=False, recursive=recursive)

    def set_side(self, side):
        nodes = cmds.ls(sl=True)
        for n in nodes:
            hierarchy = cmds.listRelatives(n, ad=True)
            hierarchy.append(n)
            for node in hierarchy:
                attr = "{}.side".format(node)
                if cmds.objExists(attr):
                    cmds.setAttr(attr, side)

        pass

    def freezeJntRot(self, *args):
        selected_joints = cmds.ls(sl=1, type="joint")
        recursive = cmds.checkBox(self.isRecursiveHierarchy, query=True, value=True)
        if recursive:
            children = cmds.listRelatives(selected_joints, ad=True, type="joint")
            if children:
                selected_joints.extend(children)
        freezeJntRot(selected_joints)

    def resetBindPose(self, *args):
        resetBindPose()

    def mirrorJoint(self, *args):
        selected_joints = cmds.ls(sl=1, type="joint")
        for jnt in selected_joints:
            # get parent
            parent = cmds.listRelatives(jnt, parent=True)
            mirroredParent = getMirroredJoint(parent)
            # add joint
            new_jnt = getMirroredJoint(parent)
            cmds.joint(
                new_jnt,
                position=cmds.xform(mirroredParent, q=1, worldSpace=1, translation=1),
            )

    def mirrorJointAttr(self, *args):
        selected_joints = cmds.ls(sl=1, type="joint")
        for jnt in selected_joints:
            mirroredJnt = getMirroredJoint(jnt)
            tr = cmds.getAttr(jnt + ".translate")[0]
            cmds.setAttr(
                mirroredJnt + ".translate", -tr[0], tr[1], tr[2], type="double3"
            )
            jo = cmds.getAttr(jnt + ".jointOrient")[0]
            cmds.setAttr(
                mirroredJnt + ".jointOrient", jo[0], -jo[1], -jo[2], type="double3"
            )

    def toggleSegmentScaleCompensate(self, *args):
        """選択したジョンイとのSeasonScaleCompensateを切り替える。
        フラグで子階層も再帰的に処理する。選択したJointの値を反転したものを全てに適応する。"""
        joints = cmds.ls(sl=True, type="joint")
        isSSC = cmds.getAttr(joints[0] + ".segmentScaleCompensate")
        recursive = cmds.checkBox(self.isRecursiveHierarchy, query=True, value=True)
        toggleSegmentScaleCompensate(joints, isSSC, recursive)


def toggleSegmentScaleCompensate(joints, status, recursive=True):
    for jnt in joints:
        # check type is joint
        if not cmds.nodeType(jnt) == "joint":
            continue
        cmds.setAttr(jnt + ".segmentScaleCompensate", not status)
        if recursive:
            children = cmds.listRelatives(jnt, children=True, type="joint") or []
            toggleSegmentScaleCompensate(children, status, recursive)


def getMirroredJoint(joint, word1="Left", word2="Right"):
    # Jointの名前から反対側のJoint名を取得
    if word1 in joint:
        return joint.replace(word1, word2)
    if word2 in joint:
        return joint.replace(word2, word1)
    return None


class Axis:
    x = "X"
    y = "Y"
    z = "Z"


def displayLRA(obj, state=True, recursive=True):
    # check if the object has a displayLocalAxis attribute
    if not cmds.objExists(obj + ".displayLocalAxis"):
        return

    cmds.setAttr(obj + ".displayLocalAxis", state)

    if not recursive:
        return
    # 子オブジェクトを取得して再帰的に処理
    children = cmds.listRelatives(obj, children=True, type="transform") or []
    print(children)
    for child in children:
        displayLRA(obj + "|" + child, state)


def segment_joints(joints, segments):
    """Segments the given joints into the specified number of segments.

    @param joints: Joints to segment.
    @param segments: Number of segments to create.
    """
    for joint in joints:
        children = _unparent_children(joint)
        cmds.select(joint)
        cmds.joint(e=True, segmentScaleCompensate=False)
        cmds.joint(e=True, segmentScaleCompensate=True)
        cmds.joint(joint, e=True, segmentScaleCompensate=True)
        cmds.joint(joint, e=True, segmentScaleCompensate=False)
        cmds.joint(joint, e=True, segmentScaleCompensate=True)
        cmds.joint(joint, e=True, segmentScaleCompensate=False)
        _reparent_children(joint, children)

    if joints:
        cmds.select(joints)


# Bind済のジョイントの回転をフリーズする
def freezeJntRot(joints):
    for jnt in joints:
        rot = cmds.xform(jnt, q=1, worldSpace=1, rotation=1)
        cmds.setAttr(jnt + ".jointOrient", 0, 0, 0, type="double3")
        cmds.xform(jnt, worldSpace=1, rotation=rot)
        newRot = cmds.xform(jnt, q=1, objectSpace=1, rotation=1)
        cmds.setAttr(
            jnt + ".jointOrient", newRot[0], newRot[1], newRot[2], type="double3"
        )
        cmds.setAttr(jnt + ".rotate", 0, 0, 0, type="double3")


# バインドポーズをリセット
def resetBindPose():
    selected = cmds.ls(selection=True, dag=True)
    # type check if mesh
    if cmds.ls(selected, type="mesh"):
        skinClusters = cmds.ls(cmds.listHistory(selected), type="skinCluster")
        for sc in skinClusters:
            joints = cmds.skinCluster(sc, query=True, influence=True)

            # get bind pose
            # bindPoses = cmds.listConnections(sc, type="dagPose")
            bindPoses = cmds.dagPose(joints, q=True, bp=True)

            if bindPoses:
                cmds.delete(bindPoses)

            cmds.dagPose(joints, save=True, bindPose=True)
    if cmds.ls(selected, type="joint"):
        bindPoses = cmds.dagPose(selected, q=True, bp=True)
        if bindPoses:
            cmds.delete(bindPoses)

        cmds.dagPose(selected, save=True, bindPose=True)


def get_skinCluster_list(allJnt):
    skinClusterList = []
    for jnt in allJnt:
        scTmp = cmds.listConnections(jnt, type="skinCluster")
        if scTmp is not None:
            scTmp = list(set(scTmp))
            for i in scTmp:
                skinClusterList.append(i)
    return list(set(skinClusterList))


def align_with_child(joints):
    """Aligns the up axis of the given joints with their respective child joint.
    #指定されたジョイントの上軸をそれぞれの子ジョイントに合わせます。
    @param joints: List of joints to orient.
    """
    for joint in joints:
        children = _unparent_children(joint)
        if children:
            cmds.delete(
                cmds.aimConstraint(
                    children[0],
                    joint,
                    aim=(1, 0, 0),
                    upVector=(0, 1, 0),
                    worldUpType="objectrotation",
                    worldUpVector=(0, 1, 0),
                    worldUpObject=children[0],
                )
            )
            cmds.makeIdentity(joint, apply=True)
        _reparent_children(joint, children)

    if joints:
        cmds.select(joints)


def zero_orient(joints):
    for joint in joints:
        children = _unparent_children(joint)
        cmds.setAttr("{0}.jointOrient".format(joint), 0, 0, 0)
        _reparent_children(joint, children)

    if joints:
        cmds.select(joints)


def orient_to_world(joints):
    """Orients the given joints with the world.

    @param joints: Joints to orient.
    """
    for joint in joints:
        children = _unparent_children(joint)
        parent = cmds.listRelatives(joint, parent=True, path=True)
        orig_joint = joint.split("|")[-1]
        if parent:
            joint = cmds.parent(joint, world=True)[0]
        cmds.joint(joint, e=True, oj="none", zso=True)
        if parent:
            joint = cmds.parent(joint, parent)[0]
            joint = cmds.rename(joint, orig_joint)
        _reparent_children(joint, children)

    if joints:
        cmds.select(joints)


def offset_orient(joints, amount, axis):
    """Offsets the orient by the given amount

    @param joints: Joints to orient.
    @param amount: Amount to offset by.
    @param axis: Which axis X, Y or Z
    """
    for joint in joints:
        children = _unparent_children(joint)
        attribute = "{0}.jointOrient{1}".format(joint, axis)
        orient = cmds.getAttr(attribute)
        orient += amount
        cmds.setAttr(attribute, orient)
        _reparent_children(joint, children)

    if joints:
        cmds.select(joints)


def _unparent_children(joint):
    """Helper function to unparent any children of the given joint.

    @param joint: Joint whose children to unparent.
    @return: A list of the unparented children.
    """
    children = cmds.listRelatives(joint, children=True, path=True) or []
    return [cmds.parent(child, world=True)[0] for child in children]


def _reparent_children(joint, children):
    """Helper function to reparent any children of the given joint.
    @param joint: Joint whose children to reparent.
    @param children: List of transforms to reparent
    """
    for child in children:
        cmds.parent(child, joint)
