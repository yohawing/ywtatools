"""RBF Mesh Retarget Workbench UIの状態とbackend境界を検証する。"""

from unittest import mock

import maya.cmds as cmds

from ywta.rig import meshretarget_ui
from ywta.test import TestCase


class _FakeItem:
    """Qtを起動せずにQListWidgetItemの最小契約を再現する。"""

    def __init__(self, text):
        self._text = text
        self._selected = False

    def text(self):
        return self._text

    def setSelected(self, selected):
        self._selected = selected


class _FakeFollowers:
    """Qtを起動せずにfollower一覧のcallback契約を検証する。"""

    def __init__(self):
        self.items = []

    def count(self):
        return len(self.items)

    def item(self, index):
        return self.items[index]

    def addItem(self, item):
        self.items.append(item)

    def addItems(self, values):
        self.items.extend(_FakeItem(value) for value in values)

    def selectedItems(self):
        return [item for item in self.items if item._selected]

    def row(self, item):
        return self.items.index(item)

    def takeItem(self, row):
        return self.items.pop(row)

    def clear(self):
        self.items = []


class _FakeNode:
    """MayaNodeWidgetのnode propertyだけを再現する。"""

    def __init__(self, node):
        self.node = node


class _FakeSpinBox:
    """QSpinBoxのvalue APIだけを再現する。"""

    def __init__(self, value):
        self._value = value

    def value(self):
        return self._value

    def setValue(self, value):
        self._value = value


class MeshRetargetUiTests(TestCase):
    """UI callbackとpreview duplicateのライフサイクルを検証する。"""

    def setUp(self):
        # Maya mayapyのテストプロセスではQtウィンドウを生成せずcallbackを検証する。
        self.window = meshretarget_ui.MeshRetargetWindow.__new__(meshretarget_ui.MeshRetargetWindow)
        self.window.source_body = _FakeNode("source_body")
        self.window.modified_body = _FakeNode("modified_body")
        self.window.followers = _FakeFollowers()
        self.window.max_control_points = _FakeSpinBox(meshretarget_ui.DEFAULT_MAX_CONTROL_POINTS)
        self.window.preview_duplicates = []
        self.window._preview_records = []
        self.item_patch = mock.patch.object(meshretarget_ui, "QListWidgetItem", _FakeItem)
        self.item_patch.start()
        self.window.followers.addItems(["follower_a", "follower_b"])

    def tearDown(self):
        self.item_patch.stop()

    def test_validate_max_control_points_is_bounded_integer(self):
        self.assertEqual(64, meshretarget_ui.validate_max_control_points(64))
        for invalid in (True, 3, meshretarget_ui.MAX_CONTROL_POINTS + 1, "64"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    meshretarget_ui.validate_max_control_points(invalid)

    def test_add_remove_clear_followers_preserves_unique_state(self):
        self.window.clear_followers()
        with mock.patch.object(cmds, "ls", return_value=["follower_a", "follower_c"]):
            self.window.add_selected_followers()
            self.window.add_selected_followers()
        self.assertEqual(["follower_a", "follower_c"], self.window._follower_names())

        self.window.followers.item(0).setSelected(True)
        self.window.remove_selected_followers()
        self.assertEqual(["follower_c"], self.window._follower_names())
        self.window.clear_followers()
        self.assertEqual([], self.window._follower_names())

    def test_preview_uses_low_density_and_replaces_previous_duplicates(self):
        self.window.preview_duplicates = ["preview_old"]
        self.window._preview_records = [("preview_old", "uuid-old")]
        with (
            mock.patch.object(
                cmds,
                "ls",
                side_effect=lambda value, **_: ["|renamed_preview"] if value == "uuid-old" else [],
            ),
            mock.patch.object(cmds, "delete") as delete,
            mock.patch.object(
                meshretarget_ui, "meshretarget", mock.Mock(retarget=mock.Mock(return_value=["preview_new"]))
            ) as backend,
        ):
            self.window.preview()

        retarget = backend.retarget
        delete.assert_called_once_with("|renamed_preview")
        self.assertEqual(["preview_new"], self.window.preview_duplicates)
        self.assertEqual(
            ("source_body", "modified_body", ["follower_a", "follower_b"]),
            retarget.call_args.args[:3],
        )
        self.assertEqual(meshretarget_ui.PREVIEW_MAX_CONTROL_POINTS, retarget.call_args.kwargs["max_control_points"])

    def test_apply_cleans_preview_and_passes_ui_value(self):
        self.window.preview_duplicates = ["preview_old"]
        self.window._preview_records = [("preview_old", "uuid-old")]
        self.window.max_control_points.setValue(128)
        with (
            mock.patch.object(cmds, "ls", return_value=["|preview_old"]),
            mock.patch.object(cmds, "delete") as delete,
            mock.patch.object(
                meshretarget_ui, "meshretarget", mock.Mock(retarget=mock.Mock(return_value=["applied"]))
            ) as backend,
        ):
            self.window.apply()

        retarget = backend.retarget
        delete.assert_called_once_with("|preview_old")
        self.assertEqual(128, retarget.call_args.kwargs["max_control_points"])
        self.assertEqual([], self.window.preview_duplicates)

    def test_preview_cleanup_skips_missing_uuid(self):
        self.window.preview_duplicates = ["preview_old"]
        self.window._preview_records = [("preview_old", "uuid-old")]
        with (
            mock.patch.object(cmds, "ls", return_value=[]),
            mock.patch.object(cmds, "delete") as delete,
        ):
            self.window._cleanup_preview()

        delete.assert_not_called()
        self.assertEqual([], self.window.preview_duplicates)

    def test_backend_exception_is_reported_as_warning(self):
        with (
            mock.patch.object(
                meshretarget_ui, "meshretarget", mock.Mock(retarget=mock.Mock(side_effect=RuntimeError("fixture")))
            ),
            mock.patch.object(meshretarget_ui.QMessageBox, "warning") as warning,
        ):
            self.window.preview()

        warning.assert_called_once()
        self.assertIn("fixture", warning.call_args.args[2])
