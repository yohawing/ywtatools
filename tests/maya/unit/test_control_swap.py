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
        curves = [
            self._line([(0, 0, 0), (1, 0, 0)]),
            self._line([(0, 0, 0), (0, 1, 0)]),
        ]

        control.swap_curve_shapes([target], curves)

        self.assertEqual(2, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        cmds.undo()
        self.assertTrue(cmds.objExists(old_shape))
        self.assertEqual(1, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        cmds.redo()
        self.assertEqual(2, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))

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
