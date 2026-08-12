"""Control curve shape差し替えのMaya単体テスト。"""

import maya.cmds as cmds

from ywta.rig import control
from ywta.test import TestCase


class ControlSwapTests(TestCase):
    """接続、表示状態、複数shape、Undoを検証する。"""

    @staticmethod
    def _line(points):
        """テスト用のlinear CurveShapeを作成する。"""
        return control.CurveShape(cvs=points, degree=1, form=0, knots=list(range(len(points))))

    def _target(self):
        """表示状態と接続を持つcontrolを作成する。"""
        target = cmds.circle(name="hand_ctrl", degree=1, sections=4)[0]
        shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        cmds.setAttr(shape + ".overrideEnabled", True)
        cmds.setAttr(shape + ".overrideRGBColors", True)
        cmds.setAttr(shape + ".overrideColorRGB", 0.1, 0.2, 0.3, type="double3")
        cmds.setAttr(shape + ".overrideDisplayType", 2)
        driver = cmds.createNode("transform", name="visibility_driver")
        cmds.addAttr(driver, longName="showControl", attributeType="bool")
        cmds.connectAttr(driver + ".showControl", shape + ".visibility")
        cmds.setKeyframe(target, attribute="translateX", time=1, value=2.0)
        return target, shape, driver

    def test_swap_preserves_transform_and_shape_display_contract(self):
        target, old_shape, driver = self._target()
        original_uuid = cmds.ls(target, uuid=True)[0]
        curve = self._line([(0, 0, 0), (2, 0, 0), (2, 1, 0)])

        result = control.swap_curve_shapes([target], [curve])

        new_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertEqual(["|" + target], result)
        self.assertFalse(cmds.objExists(old_shape))
        self.assertEqual(original_uuid, cmds.ls(target, uuid=True)[0])
        self.assertEqual(3, cmds.getAttr(new_shape + ".controlPoints", size=True))
        for actual, expected in zip(cmds.getAttr(new_shape + ".overrideColorRGB")[0], (0.1, 0.2, 0.3)):
            self.assertAlmostEqual(expected, actual)
        self.assertEqual(2, cmds.getAttr(new_shape + ".overrideDisplayType"))
        self.assertEqual(
            driver + ".showControl",
            cmds.listConnections(new_shape + ".visibility", source=True, plugs=True)[0],
        )
        self.assertEqual([1.0], cmds.keyframe(target, attribute="translateX", query=True, timeChange=True))

    def test_multi_shape_swap_is_single_undoable_action(self):
        target, old_shape, _driver = self._target()
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)
        curves = [
            self._line([(0, 0, 0), (1, 0, 0)]),
            self._line([(0, 0, 0), (0, 1, 0)]),
        ]

        control.swap_curve_shapes([target], curves)

        self.assertEqual(2, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        self.assertEqual([sentinel], cmds.ls(selection=True))
        cmds.undo()
        self.assertTrue(cmds.objExists(old_shape))
        self.assertEqual(1, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        cmds.redo()
        self.assertEqual(2, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))

    def test_swap_preserves_unconnected_hidden_visibility(self):
        """静的に非表示のshapeを差し替えても表示状態を変えない。"""
        target = cmds.circle(name="hidden_ctrl", degree=1, sections=4)[0]
        old_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        cmds.setAttr(old_shape + ".visibility", False)
        curve = self._line([(0, 0, 0), (1, 0, 0)])

        control.swap_curve_shapes([target], [curve])

        new_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        self.assertFalse(cmds.getAttr(new_shape + ".visibility"))

    def test_select_control_cvs_uses_direct_multi_shapes_only(self):
        """対象直下の全shape CVを選択し、子controlは含めない。"""
        parent = cmds.circle(name="parent_ctrl", sections=4)[0]
        extra = cmds.circle(name="extra_ctrl", sections=6)[0]
        child = cmds.circle(name="child_ctrl", sections=8)[0]
        extra_shapes = cmds.listRelatives(extra, shapes=True, fullPath=True)
        cmds.parent(extra_shapes, parent, shape=True, relative=True)
        cmds.delete(extra)
        cmds.parent(child, parent)

        result = control.select_control_cvs([parent])

        expected = []
        for shape in cmds.listRelatives(parent, shapes=True, fullPath=True) or []:
            expected.extend(cmds.ls(shape + ".cv[*]", flatten=True, long=True) or [])
        self.assertEqual(set(result), set(expected))
        self.assertEqual(set(cmds.ls(selection=True, flatten=True, long=True) or []), set(expected))
        self.assertFalse(any("child_ctrl" in component for component in result))

    def test_select_control_cvs_preflights_before_selection_change(self):
        """curveを持たない対象が混じる場合は現在選択を維持する。"""
        curve = cmds.circle(name="valid_ctrl")[0]
        invalid = cmds.createNode("transform", name="invalid_ctrl")
        cmds.select(curve, replace=True)

        with self.assertRaises(ValueError):
            control.select_control_cvs([curve, invalid])

        self.assertEqual(cmds.ls(selection=True, long=True), ["|valid_ctrl"])

    def test_combine_control_shapes_preserves_world_shape_and_undo(self):
        """source形状をworld位置のままtargetへ移し、1回でUndoする。"""
        source = cmds.curve(name="source_ctrl", degree=1, point=[(0, 0, 0), (1, 2, 0), (2, 0, 1)])
        target = cmds.circle(name="target_ctrl", degree=1, sections=4)[0]
        cmds.setAttr(source + ".translate", 3.0, 1.0, -2.0)
        cmds.setAttr(source + ".rotate", 10.0, 20.0, -15.0)
        cmds.setAttr(target + ".translate", -4.0, 2.0, 1.0)
        cmds.setAttr(target + ".rotate", -5.0, 30.0, 8.0)
        source_shape = cmds.listRelatives(source, shapes=True, fullPath=True)[0]
        expected = [
            cmds.pointPosition("{}.cv[{}]".format(source_shape, index), world=True)
            for index in range(cmds.getAttr(source_shape + ".controlPoints", size=True))
        ]
        target_uuid = cmds.ls(target, uuid=True)[0]

        result = control.combine_control_shapes([source, target])

        self.assertEqual("|target_ctrl", result)
        self.assertFalse(cmds.objExists(source))
        self.assertEqual(target_uuid, cmds.ls(target, uuid=True)[0])
        shapes = cmds.listRelatives(target, shapes=True, fullPath=True, type="nurbsCurve")
        self.assertEqual(2, len(shapes))
        combined_shape = next(shape for shape in shapes if cmds.getAttr(shape + ".controlPoints", size=True) == 3)
        actual = [cmds.pointPosition("{}.cv[{}]".format(combined_shape, index), world=True) for index in range(3)]
        for expected_point, actual_point in zip(expected, actual):
            for expected_value, actual_value in zip(expected_point, actual_point):
                self.assertAlmostEqual(expected_value, actual_value)

        cmds.undo()
        self.assertTrue(cmds.objExists(source))
        self.assertEqual(1, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        cmds.redo()
        self.assertFalse(cmds.objExists(source))
        self.assertEqual(2, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))

    def test_combine_control_shapes_rejects_source_with_child(self):
        """source削除で子階層も消える選択を編集前に拒否する。"""
        parent = cmds.circle(name="parent_ctrl")[0]
        child = cmds.circle(name="child_ctrl")[0]
        cmds.parent(child, parent)
        target = cmds.circle(name="target_ctrl")[0]
        cmds.select(parent, target, replace=True)

        with self.assertRaises(ValueError):
            control.combine_control_shapes([parent, target])

        self.assertTrue(cmds.objExists(parent))
        self.assertTrue(cmds.objExists(child))
        self.assertTrue(cmds.objExists(target))
        self.assertEqual(cmds.ls(selection=True, long=True), ["|parent_ctrl", "|target_ctrl"])

    def test_invalid_target_fails_before_other_control_is_changed(self):
        target, old_shape, _driver = self._target()
        curve = self._line([(0, 0, 0), (1, 0, 0)])

        with self.assertRaises(ValueError):
            control.swap_curve_shapes([target, "missing_ctrl"], [curve])

        self.assertTrue(cmds.objExists(old_shape))
        self.assertEqual(1, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))

    def test_smart_mirror_resolves_namespace_and_world_space_shape(self):
        cmds.namespace(add="char")
        source = cmds.curve(
            name="char:L_hand_ctrl",
            degree=1,
            point=[(0, 0, 0), (1, 2, 0), (2, 1, 1)],
        )
        target = cmds.circle(name="char:R_hand_ctrl", degree=1, sections=4)[0]
        cmds.setAttr(source + ".translate", 3.0, 1.0, -2.0)
        cmds.setAttr(source + ".rotate", 15.0, 25.0, -10.0)
        cmds.setAttr(target + ".translate", -4.0, 2.0, 1.0)
        cmds.setAttr(target + ".rotate", -12.0, 30.0, 8.0)
        source_shape = cmds.listRelatives(source, shapes=True, fullPath=True)[0]
        expected = []
        for index in range(cmds.getAttr(source_shape + ".controlPoints", size=True)):
            point = cmds.pointPosition("{}.cv[{}]".format(source_shape, index), world=True)
            expected.append((-point[0], point[1], point[2]))
        target_uuid = cmds.ls(target, uuid=True)[0]

        result = control.mirror_control_shapes(source)

        self.assertEqual("|char:R_hand_ctrl", result)
        self.assertEqual(target_uuid, cmds.ls(target, uuid=True)[0])
        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]
        actual = [
            cmds.pointPosition("{}.cv[{}]".format(target_shape, index), world=True)
            for index in range(cmds.getAttr(target_shape + ".controlPoints", size=True))
        ]
        for expected_point, actual_point in zip(expected, actual):
            for expected_value, actual_value in zip(expected_point, actual_point):
                self.assertAlmostEqual(expected_value, actual_value)

    def test_smart_mirror_rejects_missing_side_token_before_edit(self):
        source = cmds.circle(name="center_ctrl")[0]
        target = cmds.circle(name="target_ctrl")[0]
        target_shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]

        with self.assertRaises(ValueError):
            control.mirror_control_shapes(source)

        self.assertTrue(cmds.objExists(target_shape))
