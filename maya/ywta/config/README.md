# YWTA Tools 設定システム

このディレクトリには、YWTA Toolsの設定システムが含まれています。設定システムは、デフォルト設定とユーザー設定を統合し、アプリケーション全体で一貫した設定管理を提供します。

## 設計概要

設定システムは以下のコンポーネントで構成されています：

1. **BaseConfig**: 設定クラスの基底クラス。設定の読み込み、保存、取得、設定などの基本機能を提供します。
2. **ConfigValue**: 設定値を表すクラス。型安全性と検証機能を提供します。
3. **ConfigSchema**: 設定値のスキーマ定義と検証ルールを提供します。
4. **SettingsManager**: 設定管理クラス。デフォルト設定とユーザー設定を統合し、設定値へのアクセスを提供します。

## 設定ファイル

設定システムは以下の設定ファイルを使用します：

1. **default_config.json**: デフォルト設定ファイル。アプリケーションに組み込まれており、すべての設定のデフォルト値を定義します。
2. **user_config.json**: ユーザー設定ファイル。ユーザーが変更した設定のみを含みます。このファイルは、ユーザーのMayaアプリケーションディレクトリ（`{maya_app_dir}/ywta_tools/user_config.json`）に保存されます。

## 設定値の優先順位

設定値は以下の優先順位で取得されます：

1. 環境変数（`YWTA_[設定キー]`）
2. ユーザー設定（`user_config.json`）
3. デフォルト設定（`default_config.json`）
4. 指定されたデフォルト値（`get_setting(key, default)`の`default`引数）

## 設定構造

設定は階層構造になっており、ドット表記でアクセスできます。例えば、`rig.default_control_color`は、`rig`セクションの`default_control_color`設定を表します。

主な設定セクション：

- **documentation**: ドキュメント関連の設定
- **plugins**: プラグイン関連の設定
- **ui**: UI関連の設定
- **logging**: ログ関連の設定
- **rig**: リギング関連の設定
- **deform**: デフォーメーション関連の設定
- **mesh**: メッシュ関連の設定
- **anim**: アニメーション関連の設定
- **io**: 入出力関連の設定
- **system**: システム関連の設定
- **user**: ユーザー関連の設定

## 使用方法

### 設定値の取得

```python
from maya.ywta.config.settings_manager import get_setting

# 設定値を取得
control_color = get_setting("rig.default_control_color")
icon_size = get_setting("ui.icon_size")

# デフォルト値を指定して設定値を取得
log_dir = get_setting("logging.log_directory", "C:/Temp")
```

### 設定値の設定

```python
from maya.ywta.config.settings_manager import set_setting

# 設定値を設定
set_setting("rig.default_control_color", 13)
set_setting("ui.language", "ja")
```

### 設定値のリセット

```python
from maya.ywta.config.settings_manager import reset_setting

# 特定の設定値をデフォルトにリセット
reset_setting("rig.default_control_color")

# すべての設定値をデフォルトにリセット
reset_setting()
```

### 設定のエクスポート/インポート

```python
from maya.ywta.config.settings_manager import export_settings, import_settings

# 現在の設定をエクスポート
export_settings("C:/Temp/my_settings.json")

# 設定をインポート
import_settings("C:/Temp/my_settings.json")
```

### 設定の保存

```python
from maya.ywta.config.settings_manager import save_settings

# 現在の設定をユーザー設定ファイルに保存
save_settings()
```

### 設定変更時のコールバック

```python
from maya.ywta.config.settings_manager import add_callback, remove_callback, set_setting

# コールバック関数を定義
def on_theme_changed(key, value):
    print(f"テーマが変更されました: {key} = {value}")
    # UIの更新など必要な処理を実行

# コールバックを登録
add_callback("ui.theme.primary_color", on_theme_changed)

# 設定を変更（コールバックが呼び出される）
set_setting("ui.theme.primary_color", "#FF0000")
# 出力: テーマが変更されました: ui.theme.primary_color = #FF0000

# コールバックを削除
remove_callback("ui.theme.primary_color", on_theme_changed)

# 設定を変更（コールバックは呼び出されない）
set_setting("ui.theme.primary_color", "#00FF00")
```

### 設定マネージャーの直接使用

```python
from maya.ywta.config.settings_manager import get_settings_manager

# 設定マネージャーのインスタンスを取得
settings = get_settings_manager()

# すべての設定値を取得
all_settings = settings.get_all_settings()

# 変更された設定値を取得
modified_settings = settings.get_modified_settings()
```

## 新しい設定の追加

新しい設定を追加するには、`default_config.json`ファイルに設定を追加します。設定は自動的に読み込まれ、アプリケーション全体で利用可能になります。

例えば、新しいリギング設定を追加する場合：

```json
{
  "rig": {
    "new_setting": "value"
  }
}
```

この設定は、`get_setting("rig.new_setting")`で取得できます。

## 設定値の検証

設定値の検証が必要な場合は、`ConfigSchema`クラスを使用して検証ルールを定義できます。

```python
from maya.ywta.config.config_schema import ConfigSchema
from maya.ywta.config.settings_manager import get_settings_manager

# スキーマを作成
schema = ConfigSchema()

# 検証ルールを追加
schema.add_range_constraint("rig.control_scale", min_value=0.1, max_value=10.0)
schema.add_choice_constraint("logging.level", ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])

# 設定値を検証
settings = get_settings_manager()
schema.validate("rig.control_scale", settings.get("rig.control_scale"))
```

## 環境変数

設定値は環境変数でオーバーライドできます。環境変数の名前は`YWTA_`プレフィックスの後に、設定キーを大文字にしてドットをアンダースコアに置き換えたものになります。

例：
- `rig.default_control_color` → `YWTA_RIG_DEFAULT_CONTROL_COLOR`
- `ui.icon_size` → `YWTA_UI_ICON_SIZE`

## 後方互換性

既存の設定システムとの後方互換性のために、以下のプロパティが提供されています：

- `DOCUMENTATION_ROOT`: `documentation.root_url`の別名
- `ENABLE_PLUGINS`: `plugins.enable_cpp_plugins`の別名

これらのプロパティは、`settings.py`モジュールからアクセスできます：

```python
from maya.ywta.settings import DOCUMENTATION_ROOT, ENABLE_PLUGINS

print(DOCUMENTATION_ROOT)
print(ENABLE_PLUGINS)
