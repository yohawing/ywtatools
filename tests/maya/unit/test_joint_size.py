"""
Joint Size Tools のテスト

ジョイントサイズ設定機能のテストケース
"""

import unittest
import maya.cmds as cmds
from ywta.rig import joint_size


class TestJointSizeTools(unittest.TestCase):
    """Joint Size Tools のテストクラス"""

    def setUp(self):
        """テスト前の準備"""
        # 新しいシーンを作成
        cmds.file(new=True, force=True)

        # テスト用のジョイント階層を作成
        self.root_joint = cmds.joint(name="test_root")
        cmds.select(clear=True)

        # 子ジョイントを作成
        cmds.select(self.root_joint)
        self.child1 = cmds.joint(name="test_child1", position=(1, 0, 0))
        self.child2 = cmds.joint(name="test_child2", position=(2, 0, 0))

        # 別の階層を作成
        cmds.select(clear=True)
        self.other_root = cmds.joint(name="test_other_root", position=(0, 1, 0))

        # 初期サイズを設定
        for joint in [self.root_joint, self.child1, self.child2, self.other_root]:
            cmds.setAttr(f"{joint}.radius", 0.5)

    def tearDown(self):
        """テスト後のクリーンアップ"""
        # 新しいシーンを作成してクリーンアップ
        cmds.file(new=True, force=True)

    def test_set_joint_size_hierarchy_selected(self):
        """選択されたジョイント階層のサイズ設定テスト"""
        # ルートジョイントを選択
        cmds.select(self.root_joint)

        # 階層のサイズを設定
        joint_size.set_joint_size_hierarchy(2.0, selected_only=True)

        # ルートジョイントとその子のサイズが変更されているかチェック
        self.assertAlmostEqual(cmds.getAttr(f"{self.root_joint}.radius"), 2.0, places=3)
        self.assertAlmostEqual(cmds.getAttr(f"{self.child1}.radius"), 2.0, places=3)
        self.assertAlmostEqual(cmds.getAttr(f"{self.child2}.radius"), 2.0, places=3)

        # 他のジョイントは変更されていないかチェック
        self.assertAlmostEqual(cmds.getAttr(f"{self.other_root}.radius"), 0.5, places=3)

    def test_set_joint_size_is_single_undoable_action(self):
        """階層全体のradius変更を1回でUndo/Redoする。"""
        cmds.select(self.root_joint)

        joint_size.set_joint_size_hierarchy(2.0, selected_only=True)
        cmds.undo()

        for joint in [self.root_joint, self.child1, self.child2]:
            self.assertAlmostEqual(0.5, cmds.getAttr(joint + ".radius"), places=3)
        cmds.redo()
        for joint in [self.root_joint, self.child1, self.child2]:
            self.assertAlmostEqual(2.0, cmds.getAttr(joint + ".radius"), places=3)

    def test_locked_descendant_rejects_before_edit(self):
        """変更不能な子が混じる場合はrootも変更しない。"""
        cmds.setAttr(self.child2 + ".radius", lock=True)
        cmds.select(self.root_joint)

        with self.assertRaises(ValueError):
            joint_size.set_joint_size_hierarchy(2.0, selected_only=True)

        self.assertAlmostEqual(0.5, cmds.getAttr(self.root_joint + ".radius"), places=3)
        self.assertAlmostEqual(0.5, cmds.getAttr(self.child1 + ".radius"), places=3)

    def test_invalid_size_rejects_before_edit(self):
        """非正値・非有限値をradiusへ渡さない。"""
        cmds.select(self.root_joint)

        for value in (0.0, -1.0, float("nan"), True):
            with self.assertRaises(ValueError):
                joint_size.set_joint_size_hierarchy(value, selected_only=True)

        self.assertAlmostEqual(0.5, cmds.getAttr(self.root_joint + ".radius"), places=3)

    def test_set_joint_size_hierarchy_all(self):
        """全ジョイントのサイズ設定テスト"""
        # 全ジョイントのサイズを設定
        joint_size.set_joint_size_hierarchy(3.0, selected_only=False)

        # 全ジョイントのサイズが変更されているかチェック
        for joint in [self.root_joint, self.child1, self.child2, self.other_root]:
            self.assertAlmostEqual(cmds.getAttr(f"{joint}.radius"), 3.0, places=3)

    def test_get_joint_size_from_selection(self):
        """選択されたジョイントのサイズ取得テスト"""
        # ジョイントのサイズを設定
        cmds.setAttr(f"{self.root_joint}.radius", 1.5)

        # ジョイントを選択
        cmds.select(self.root_joint)

        # サイズを取得
        size = joint_size.get_joint_size_from_selection()
        self.assertAlmostEqual(size, 1.5, places=3)

    def test_get_joint_size_from_selection_no_selection(self):
        """何も選択されていない場合のサイズ取得テスト"""
        # 選択をクリア
        cmds.select(clear=True)

        # サイズを取得（Noneが返されるはず）
        size = joint_size.get_joint_size_from_selection()
        self.assertIsNone(size)

    def test_set_joint_size_hierarchy_no_selection(self):
        """何も選択されていない場合のテスト"""
        # 選択をクリア
        cmds.select(clear=True)

        # 元のサイズを記録
        original_sizes = {}
        for joint in [self.root_joint, self.child1, self.child2, self.other_root]:
            original_sizes[joint] = cmds.getAttr(f"{joint}.radius")

        # 選択なしで実行（警告が出るはず）
        joint_size.set_joint_size_hierarchy(4.0, selected_only=True)

        # サイズが変更されていないかチェック
        for joint in [self.root_joint, self.child1, self.child2, self.other_root]:
            current_size = cmds.getAttr(f"{joint}.radius")
            self.assertAlmostEqual(current_size, original_sizes[joint], places=3)


def run_tests():
    """テストを実行する関数"""
    # テストスイートを作成
    suite = unittest.TestLoader().loadTestsFromTestCase(TestJointSizeTools)

    # テストを実行
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result


if __name__ == "__main__":
    # Maya環境でテストを実行
    run_tests()
