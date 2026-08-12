"""Control curve shape差し替えのMaya単体テスト。"""

import json
import os
from unittest import mock

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

    def test_set_control_color_updates_multi_shapes_and_undoes(self):
        """全shapeを同色にし、選択を維持して1回でUndoする。"""
        target = cmds.circle(name="color_ctrl", sections=4)[0]
        extra = cmds.circle(name="extra_color_ctrl", sections=6)[0]
        extra_shapes = cmds.listRelatives(extra, shapes=True, fullPath=True)
        cmds.parent(extra_shapes, target, shape=True, relative=True)
        cmds.delete(extra)
        sentinel = cmds.spaceLocator(name="selection_sentinel")[0]
        cmds.select(sentinel, replace=True)

        shapes = control.set_control_color((0.2, 0.4, 0.8), [target])

        self.assertEqual(2, len(shapes))
        self.assertEqual([sentinel], cmds.ls(selection=True))
        for shape in shapes:
            self.assertTrue(cmds.getAttr(shape + ".overrideEnabled"))
            self.assertTrue(cmds.getAttr(shape + ".overrideRGBColors"))
            for actual, expected in zip(cmds.getAttr(shape + ".overrideColorRGB")[0], (0.2, 0.4, 0.8)):
                self.assertAlmostEqual(expected, actual)

        cmds.undo()
        for shape in shapes:
            self.assertFalse(cmds.getAttr(shape + ".overrideEnabled"))
        cmds.redo()
        for shape in shapes:
            self.assertTrue(cmds.getAttr(shape + ".overrideEnabled"))

    def test_set_control_color_rejects_invalid_rgb_before_edit(self):
        """範囲外や非有限RGBで既存表示状態を変更しない。"""
        target = cmds.circle(name="color_ctrl")[0]
        shape = cmds.listRelatives(target, shapes=True, fullPath=True)[0]

        for invalid in ((1.1, 0.0, 0.0), (float("nan"), 0.0, 0.0), (True, 0.0, 0.0)):
            with self.assertRaises(ValueError):
                control.set_control_color(invalid, [target])

        self.assertFalse(cmds.getAttr(shape + ".overrideEnabled"))

    def test_multi_shape_control_library_round_trip(self):
        """複数shapeを1つのtransformとしてJSON保存・新規作成する。"""
        target = cmds.circle(name="multi_ctrl", sections=4)[0]
        extra = cmds.circle(name="extra_ctrl", sections=6)[0]
        extra_shapes = cmds.listRelatives(extra, shapes=True, fullPath=True)
        cmds.parent(extra_shapes, target, shape=True, relative=True)
        cmds.delete(extra)
        path = self.get_temp_filename("multi_control.json")

        data = control.export_curves([target], path)
        cmds.delete(target)
        created = control.import_new_curves(path)

        self.assertEqual(2, len(data))
        self.assertEqual(["multi_ctrl"], created)
        self.assertEqual(2, len(cmds.listRelatives(created[0], shapes=True, type="nurbsCurve")))

        cmds.undo()
        self.assertFalse(cmds.objExists("multi_ctrl"))
        cmds.redo()
        self.assertEqual(2, len(cmds.listRelatives("multi_ctrl", shapes=True, type="nurbsCurve")))

    def test_control_export_rejects_invalid_target_without_replacing_file(self):
        """不正controlの保存失敗で既存library JSONを置換しない。"""
        path = self.get_temp_filename("existing_control.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("sentinel")

        with self.assertRaises(ValueError):
            control.export_curves(["missing_ctrl"], path)

        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual("sentinel", handle.read())

    def test_invalid_control_record_is_rejected_before_import(self):
        """後半recordが壊れたJSONからtransformを部分作成しない。"""
        path = self.get_temp_filename("invalid_control.json")
        valid = {
            "transform": "safe_ctrl",
            "cvs": [[0, 0, 0], [1, 0, 0]],
            "degree": 1,
            "form": 0,
            "knots": [0, 1],
            "color": None,
        }
        invalid = dict(valid, transform="broken_ctrl", knots=[1, 0])
        with open(path, "w", encoding="utf-8") as handle:
            json.dump([valid, invalid], handle)

        with self.assertRaises(ValueError):
            control.import_new_curves(path)

        self.assertFalse(cmds.objExists("safe_ctrl"))
        self.assertFalse(cmds.objExists("broken_ctrl"))

    def test_control_import_rolls_back_partial_creation(self):
        """後半shape作成の失敗で先に作ったtransformも残さない。"""
        target = cmds.circle(name="multi_ctrl", sections=4)[0]
        extra = cmds.circle(name="extra_ctrl", sections=6)[0]
        extra_shapes = cmds.listRelatives(extra, shapes=True, fullPath=True)
        cmds.parent(extra_shapes, target, shape=True, relative=True)
        cmds.delete(extra)
        path = self.get_temp_filename("rollback_control.json")
        control.export_curves([target], path)
        cmds.delete(target)
        original_create = control.CurveShape.create
        call_count = [0]

        def fail_second(curve, *args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise RuntimeError("forced create failure")
            return original_create(curve, *args, **kwargs)

        with mock.patch.object(control.CurveShape, "create", new=fail_second):
            with self.assertRaises(RuntimeError):
                control.import_new_curves(path)

        self.assertFalse(cmds.objExists("multi_ctrl"))

    def test_library_save_combines_world_shapes_under_one_name(self):
        """複数transformのworld形状を1つのlibrary controlへ保存する。"""
        first = cmds.curve(name="first_ctrl", degree=1, point=[(0, 0, 0), (1, 0, 0)])
        second = cmds.curve(name="second_ctrl", degree=1, point=[(0, 0, 0), (0, 2, 0)])
        cmds.setAttr(first + ".translate", 3.0, 0.0, 0.0)
        cmds.setAttr(second + ".translate", 0.0, 4.0, 0.0)
        expected = []
        for transform in (first, second):
            shape = cmds.listRelatives(transform, shapes=True, fullPath=True)[0]
            expected.append(
                [
                    cmds.pointPosition("{}.cv[{}]".format(shape, index), world=True)
                    for index in range(cmds.getAttr(shape + ".controlPoints", size=True))
                ]
            )
        directory = os.path.dirname(self.get_temp_filename("library_marker.tmp"))

        path = control.export_shape_to_library([first, second], "combined", directory=directory)
        cmds.delete(first, second)
        created = control.import_new_curves(path)

        self.assertEqual(["combined"], created)
        shapes = cmds.listRelatives(created[0], shapes=True, fullPath=True, type="nurbsCurve")
        self.assertEqual(2, len(shapes))
        for shape, expected_points in zip(shapes, expected):
            actual = [
                cmds.pointPosition("{}.cv[{}]".format(shape, index), world=True)
                for index in range(cmds.getAttr(shape + ".controlPoints", size=True))
            ]
            for actual_point, expected_point in zip(actual, expected_points):
                for actual_value, expected_value in zip(actual_point, expected_point):
                    self.assertAlmostEqual(expected_value, actual_value)

    def test_library_save_requires_explicit_overwrite(self):
        """既存entryを明示許可なしに置換しない。"""
        target = cmds.circle(name="control")[0]
        directory = os.path.dirname(self.get_temp_filename("library_marker.tmp"))
        path = os.path.join(directory, "existing.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("sentinel")

        with self.assertRaises(ValueError):
            control.export_shape_to_library([target], "existing", directory=directory)

        with open(path, "r", encoding="utf-8") as handle:
            self.assertEqual("sentinel", handle.read())

    def test_library_rename_updates_file_and_internal_transform(self):
        """Entry改名時にJSON内部の作成名も新しい名前へ揃える。"""
        target = cmds.circle(name="control")[0]
        directory = os.path.dirname(self.get_temp_filename("library_marker.tmp"))
        source = control.export_shape_to_library([target], "old_shape", directory=directory)

        result = control.rename_library_shape("old_shape", "new_shape", directory=directory)

        self.assertFalse(os.path.exists(source))
        self.assertEqual(os.path.join(directory, "new_shape.json"), result)
        curves = control.load_curves(result)
        self.assertTrue(curves)
        self.assertEqual({"new_shape"}, {curve.transform for curve in curves})

    def test_library_rename_does_not_overwrite_existing_entry(self):
        """改名先が存在する場合は両entryを変更しない。"""
        first = cmds.circle(name="first")[0]
        second = cmds.circle(name="second")[0]
        directory = os.path.dirname(self.get_temp_filename("library_marker.tmp"))
        source = control.export_shape_to_library([first], "source", directory=directory)
        target = control.export_shape_to_library([second], "target", directory=directory)
        with open(source, "rb") as handle:
            source_before = handle.read()
        with open(target, "rb") as handle:
            target_before = handle.read()

        with self.assertRaises(ValueError):
            control.rename_library_shape("source", "target", directory=directory)

        with open(source, "rb") as handle:
            self.assertEqual(source_before, handle.read())
        with open(target, "rb") as handle:
            self.assertEqual(target_before, handle.read())

    def test_multiple_library_files_build_as_distinct_controls(self):
        """同じ内部名を持つ複数entryも別transformとして1回で作成する。"""
        first = self._line([(0, 0, 0), (1, 0, 0)])
        second = self._line([(0, 0, 0), (0, 1, 0)])
        first.transform = "shape"
        second.transform = "shape"
        first_path = self.get_temp_filename("first_control.json")
        second_path = self.get_temp_filename("second_control.json")
        control._write_curve_data([first], first_path)
        control._write_curve_data([second], second_path)

        created = control.import_new_curve_files([first_path, second_path])

        self.assertEqual(["shape", "shape1"], created)
        self.assertTrue(all(cmds.objExists(node) for node in created))
        cmds.undo()
        self.assertFalse(any(cmds.objExists(node) for node in created))

    def test_multiple_library_files_validate_before_creating(self):
        """後続JSONが壊れていれば先行entryも作成しない。"""
        curve = self._line([(0, 0, 0), (1, 0, 0)])
        curve.transform = "would_create"
        valid_path = self.get_temp_filename("valid_control.json")
        invalid_path = self.get_temp_filename("invalid_control.json")
        control._write_curve_data([curve], valid_path)
        with open(invalid_path, "w", encoding="utf-8") as handle:
            json.dump([{"transform": "broken"}], handle)

        with self.assertRaises(ValueError):
            control.import_new_curve_files([valid_path, invalid_path])

        self.assertFalse(cmds.objExists("would_create"))

    def test_multiple_library_files_validate_before_applying_to_selection(self):
        """後続JSONが壊れていれば選択controlへ前半shapeも追加しない。"""
        target = cmds.circle(name="target")[0]
        curve = self._line([(0, 0, 0), (1, 0, 0)])
        curve.transform = "valid"
        valid_path = self.get_temp_filename("valid_apply.json")
        invalid_path = self.get_temp_filename("invalid_apply.json")
        control._write_curve_data([curve], valid_path)
        with open(invalid_path, "w", encoding="utf-8") as handle:
            json.dump([{"transform": "broken"}], handle)
        cmds.select(target, replace=True)

        with self.assertRaises(ValueError):
            control.import_curve_files_on_selected([valid_path, invalid_path])

        self.assertEqual(1, len(cmds.listRelatives(target, shapes=True, type="nurbsCurve")))
        self.assertEqual(["|target"], cmds.ls(selection=True, long=True))

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
