"""
Configuration System Test

新しい設定システムの基本的なテストを行います。
"""

import os
import tempfile
from pathlib import Path

from .settings_manager import SettingsManager, get_settings_manager
from .base_config import ConfigValue, ValidationError


def test_basic_functionality():
    """基本機能のテスト"""
    print("=== 基本機能テスト ===")

    # 一時ファイルで設定マネージャーを作成
    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        temp_config = Path(f.name)

    try:
        settings = SettingsManager(temp_config)

        # デフォルト値の確認
        print(f"Documentation URL: {settings.DOCUMENTATION_ROOT}")
        print(f"Enable Plugins: {settings.ENABLE_PLUGINS}")

        # 設定値の変更
        settings.DOCUMENTATION_ROOT = "https://example.com/docs"
        settings.ENABLE_PLUGINS = False

        print(f"Changed Documentation URL: {settings.DOCUMENTATION_ROOT}")
        print(f"Changed Enable Plugins: {settings.ENABLE_PLUGINS}")

        # 新しい設定値の追加
        settings.set("test.value", "test_data")
        print(f"Test value: {settings.get('test.value')}")

        # 設定ファイルに保存
        settings.save_config()
        print(f"設定ファイルに保存: {temp_config}")

        # 新しいインスタンスで読み込み確認
        settings2 = SettingsManager(temp_config)
        print(f"再読み込み後 Documentation URL: {settings2.DOCUMENTATION_ROOT}")
        print(f"再読み込み後 Enable Plugins: {settings2.ENABLE_PLUGINS}")
        print(f"再読み込み後 Test value: {settings2.get('test.value')}")

        print("✓ 基本機能テスト完了")

    finally:
        # 一時ファイルを削除
        if temp_config.exists():
            temp_config.unlink()


def test_environment_variables():
    """環境変数テスト"""
    print("\n=== 環境変数テスト ===")

    # 環境変数を設定
    os.environ["YWTA_DOCUMENTATION_ROOT"] = "https://env.example.com"
    os.environ["YWTA_ENABLE_PLUGINS"] = "false"

    try:
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            temp_config = Path(f.name)

        settings = SettingsManager(temp_config)

        # 環境変数が優先されることを確認
        print(f"環境変数からの Documentation URL: {settings.DOCUMENTATION_ROOT}")
        print(f"環境変数からの Enable Plugins: {settings.ENABLE_PLUGINS}")

        print("✓ 環境変数テスト完了")

        if temp_config.exists():
            temp_config.unlink()

    finally:
        # 環境変数をクリア
        os.environ.pop("YWTA_DOCUMENTATION_ROOT", None)
        os.environ.pop("YWTA_ENABLE_PLUGINS", None)


def test_validation():
    """検証機能のテスト"""
    print("\n=== 検証機能テスト ===")

    with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
        temp_config = Path(f.name)

    try:
        settings = SettingsManager(temp_config)

        # カスタム検証付きの設定値を追加
        settings.add_config_value(
            ConfigValue(
                key="test.positive_number",
                default=10,
                description="正の数値のテスト",
                validator=lambda v: isinstance(v, (int, float)) and v > 0,
            )
        )

        # 正常な値
        settings.set("test.positive_number", 5)
        print(f"正常な値: {settings.get('test.positive_number')}")

        # 異常な値（エラーが発生するはず）
        try:
            settings.set("test.positive_number", -1)
            print("❌ 検証エラーが発生しませんでした")
        except ValidationError as e:
            print(f"✓ 期待通り検証エラーが発生: {e}")

        print("✓ 検証機能テスト完了")

    finally:
        if temp_config.exists():
            temp_config.unlink()


def test_qsettings_compatibility():
    """QSettings互換性テスト"""
    print("\n=== QSettings互換性テスト ===")

    try:
        settings = get_settings_manager()

        # QSettings互換メソッドのテスト
        settings.setValue("test.qsettings", "test_value")
        value = settings.value("test.qsettings", "default")

        print(f"QSettings互換メソッドでの値: {value}")
        print("✓ QSettings互換性テスト完了")

    except Exception as e:
        print(f"QSettings互換性テストでエラー: {e}")


def run_all_tests():
    """すべてのテストを実行"""
    print("YWTA Tools 設定システム テスト開始\n")

    try:
        test_basic_functionality()
        test_environment_variables()
        test_validation()
        test_qsettings_compatibility()

        print("\n🎉 すべてのテストが完了しました！")

    except Exception as e:
        print(f"\n❌ テスト中にエラーが発生しました: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    run_all_tests()
