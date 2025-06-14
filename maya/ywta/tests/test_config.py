"""
Configuration System Test

新しい設定システムの基本的なテストを行います。
"""

import os
import json
import maya.cmds as cmds
from pathlib import Path

from ywta.test import TestCase
from ywta.config.settings_manager import (
    SettingsManager,
    get_settings_manager,
    get_setting,
    set_setting,
    reset_setting,
    export_settings,
    import_settings,
    save_settings,
    add_callback,
    remove_callback,
)
from ywta.config.base_config import ConfigValue, ValidationError


class ConfigTests(TestCase):
    """設定システムのテストケース"""

    def setUp(self):
        """各テスト前の準備"""
        # 一時ファイルでデフォルト設定とユーザー設定を作成
        self.temp_default_config = self.get_temp_filename("default_config.json")
        self.temp_user_config = self.get_temp_filename("user_config.json")
        self.temp_export_config = self.get_temp_filename("export_config.json")

        # デフォルト設定を作成
        default_config = {
            "documentation": {"root_url": "https://example.com"},
            "plugins": {"enable_cpp_plugins": True},
            "ui": {"icon_size": 24, "theme": {"primary_color": "#3498db"}},
            "rig": {"default_control_color": 13},
        }
        with open(self.temp_default_config, "w", encoding="utf-8") as f:
            json.dump(default_config, f)

        # グローバルインスタンスをリセット
        SettingsManager._instance = None

    def tearDown(self):
        """各テスト後のクリーンアップ"""
        # グローバルインスタンスをリセット
        SettingsManager._instance = None

    def test_basic_functionality(self):
        """基本機能のテスト"""
        # 設定マネージャーを作成
        settings = SettingsManager(self.temp_user_config, self.temp_default_config)

        # デフォルト値の確認
        self.assertEqual("", settings.DOCUMENTATION_ROOT)
        self.assertEqual(True, settings.ENABLE_PLUGINS)
        self.assertEqual(24, settings.get("ui.icon_size"))
        self.assertEqual(13, settings.get("rig.default_control_color"))

        # 設定値の変更
        settings.DOCUMENTATION_ROOT = "https://example.com/docs"
        settings.ENABLE_PLUGINS = False
        settings.set("ui.icon_size", 32)
        settings.set("rig.default_control_color", 17)

        # 変更後の値を確認
        self.assertEqual("https://example.com/docs", settings.DOCUMENTATION_ROOT)
        self.assertEqual(False, settings.ENABLE_PLUGINS)
        self.assertEqual(32, settings.get("ui.icon_size"))
        self.assertEqual(17, settings.get("rig.default_control_color"))

        # 新しい設定値の追加
        settings.set("test.value", "test_data")
        self.assertEqual("test_data", settings.get("test.value"))

        # 設定ファイルに保存
        settings.save_config()

        # 新しいインスタンスで読み込み確認
        settings2 = SettingsManager(self.temp_user_config, self.temp_default_config)
        self.assertEqual("https://example.com/docs", settings2.DOCUMENTATION_ROOT)
        self.assertEqual(False, settings2.ENABLE_PLUGINS)
        self.assertEqual(32, settings2.get("ui.icon_size"))
        self.assertEqual(17, settings2.get("rig.default_control_color"))
        self.assertEqual("test_data", settings2.get("test.value"))

        # 変更された設定値の取得
        modified_settings = settings2.get_modified_settings()
        self.assertIn("documentation.root_url", modified_settings)
        self.assertIn("plugins.enable_cpp_plugins", modified_settings)
        self.assertIn("ui.icon_size", modified_settings)
        self.assertIn("rig.default_control_color", modified_settings)

    def test_environment_variables(self):
        """環境変数テスト"""
        # 環境変数を設定
        os.environ["YWTA_DOCUMENTATION_ROOT"] = "https://env.example.com"
        os.environ["YWTA_PLUGINS_ENABLE_CPP_PLUGINS"] = "false"
        os.environ["YWTA_UI_ICON_SIZE"] = "48"

        try:
            # ユーザー設定を作成
            user_config = {
                "documentation": {"root_url": "https://user.example.com"},
                "ui": {"icon_size": 32},
            }
            with open(self.temp_user_config, "w", encoding="utf-8") as f:
                json.dump(user_config, f)

            settings = SettingsManager(self.temp_user_config, self.temp_default_config)

            # 環境変数が優先されることを確認
            self.assertEqual("https://env.example.com", settings.DOCUMENTATION_ROOT)
            self.assertEqual(False, settings.ENABLE_PLUGINS)
            self.assertEqual(48, settings.get("ui.icon_size"))

        finally:
            # 環境変数をクリア
            os.environ.pop("YWTA_DOCUMENTATION_ROOT", None)
            os.environ.pop("YWTA_PLUGINS_ENABLE_CPP_PLUGINS", None)
            os.environ.pop("YWTA_UI_ICON_SIZE", None)

    def test_reset_settings(self):
        """設定リセットのテスト"""
        settings = SettingsManager(self.temp_user_config, self.temp_default_config)

        # 設定値を変更
        settings.set("documentation.root_url", "https://user.example.com")
        settings.set("ui.icon_size", 32)
        settings.set("ui.theme.primary_color", "#ff5733")
        settings.set("test.value", "test_data")

        # 変更後の値を確認
        self.assertEqual(
            "https://user.example.com", settings.get("documentation.root_url")
        )
        self.assertEqual(32, settings.get("ui.icon_size"))
        self.assertEqual("#ff5733", settings.get("ui.theme.primary_color"))
        self.assertEqual("test_data", settings.get("test.value"))

        # 特定の設定値をリセット
        settings.reset_to_default("ui.icon_size")
        self.assertEqual(24, settings.get("ui.icon_size"))

        # ネストされた設定値をリセット
        settings.reset_to_default("ui.theme.primary_color")
        self.assertEqual("#3498db", settings.get("ui.theme.primary_color"))

        # すべての設定値をリセット
        settings.reset_to_default()
        self.assertEqual(
            "https://default.example.com", settings.get("documentation.root_url")
        )
        self.assertEqual(24, settings.get("ui.icon_size"))
        self.assertIsNone(settings.get("test.value"))

    def test_export_import_settings(self):
        """設定のエクスポート/インポートテスト"""
        settings = SettingsManager(self.temp_user_config, self.temp_default_config)

        # 設定値を変更
        settings.set("documentation.root_url", "https://user.example.com")
        settings.set("ui.icon_size", 32)
        settings.set("test.value", "test_data")

        # 設定をエクスポート
        settings.export_settings(self.temp_export_config)
        self.assertTrue(os.path.exists(self.temp_export_config))

        # 設定値をリセット
        settings.reset_to_default()

        # エクスポートした設定をインポート
        settings.import_settings(self.temp_export_config)
        self.assertEqual(
            "https://user.example.com", settings.get("documentation.root_url")
        )
        self.assertEqual(32, settings.get("ui.icon_size"))
        self.assertEqual("test_data", settings.get("test.value"))

    def test_qsettings_compatibility(self):
        """QSettings互換性テスト"""
        settings = get_settings_manager()

        # QSettings互換メソッドのテスト
        settings.setValue("test.qsettings", "test_value")
        value = settings.value("test.qsettings", "default")

        self.assertEqual("test_value", value)

    def test_convenience_functions(self):
        """便利関数のテスト"""
        # グローバルインスタンスを設定
        global_settings = SettingsManager(
            self.temp_user_config, self.temp_default_config
        )
        SettingsManager._instance = global_settings

        # get_setting関数のテスト
        self.assertEqual("https://example.com", get_setting("documentation.root_url"))
        self.assertEqual(24, get_setting("ui.icon_size"))
        self.assertEqual("default_value", get_setting("not.exists", "default_value"))

        # set_setting関数のテスト
        set_setting("documentation.root_url", "https://new.example.com")
        set_setting("ui.icon_size", 48)
        self.assertEqual(
            "https://new.example.com", get_setting("documentation.root_url")
        )
        self.assertEqual(48, get_setting("ui.icon_size"))

        # reset_setting関数のテスト
        reset_setting("ui.icon_size")
        self.assertEqual(24, get_setting("ui.icon_size"))

        # export_settings関数のテスト
        export_settings(self.temp_export_config)
        self.assertTrue(os.path.exists(self.temp_export_config))

        # 設定値を変更
        set_setting("documentation.root_url", "https://changed.example.com")

        # import_settings関数のテスト
        import_settings(self.temp_export_config)
        self.assertEqual(
            "https://new.example.com", get_setting("documentation.root_url")
        )

    def test_callbacks(self):
        """コールバック機能のテスト"""
        # グローバルインスタンスを設定
        global_settings = SettingsManager(
            self.temp_user_config, self.temp_default_config
        )
        SettingsManager._instance = global_settings

        # コールバック関数
        callback_results = []

        def on_setting_changed(key, value):
            callback_results.append((key, value))

        # コールバックを登録
        add_callback("ui.theme.primary_color", on_setting_changed)
        add_callback("ui.icon_size", on_setting_changed)

        # 設定値を変更
        set_setting("ui.theme.primary_color", "#ff5733")
        set_setting("ui.icon_size", 48)
        set_setting("documentation.root_url", "https://example.com")  # コールバックなし

        # コールバックが呼び出されたことを確認
        self.assertEqual(2, len(callback_results))
        self.assertEqual("ui.theme.primary_color", callback_results[0][0])
        self.assertEqual("#ff5733", callback_results[0][1])
        self.assertEqual("ui.icon_size", callback_results[1][0])
        self.assertEqual(48, callback_results[1][1])

        # コールバックを削除
        remove_callback("ui.theme.primary_color", on_setting_changed)

        # 設定値を再度変更
        set_setting("ui.theme.primary_color", "#3498db")
        set_setting("ui.icon_size", 24)

        # 削除したコールバックは呼び出されないことを確認
        self.assertEqual(3, len(callback_results))
        self.assertEqual("ui.icon_size", callback_results[2][0])
        self.assertEqual(24, callback_results[2][1])

    def test_save_settings(self):
        """設定の永続化機能のテスト"""
        # グローバルインスタンスを設定
        global_settings = SettingsManager(
            self.temp_user_config, self.temp_default_config
        )
        SettingsManager._instance = global_settings

        # 設定値を変更
        set_setting("ui.theme.primary_color", "#ff5733")
        set_setting("ui.icon_size", 48)

        # 設定を保存
        save_settings()

        # 新しいインスタンスで読み込み確認
        SettingsManager._instance = None
        new_settings = get_settings_manager()
        new_settings.load_config(self.temp_user_config)

        # 保存された設定値を確認
        self.assertEqual("#3498db", get_setting("ui.theme.primary_color"))
        self.assertEqual(48, get_setting("ui.icon_size"))
