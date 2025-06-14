# YWTA Tools テストフレームワーク

このディレクトリには、YWTA Toolsのテストフレームワークが含まれています。
Maya、Blenderなど異なるプラットフォーム向けのテストを実行するための共通基盤を提供します。

## ディレクトリ構造

```
tests/
├── common/           # 共通のテストユーティリティとベースクラス
├── maya/             # Maya用のテスト
│   ├── unit/         # Mayaの単体テスト
│   ├── integration/  # Mayaの統合テスト
│   └── performance/  # Mayaのパフォーマンステスト
├── blender/          # Blender用のテスト
│   ├── unit/         # Blenderの単体テスト
│   ├── integration/  # Blenderの統合テスト
│   └── performance/  # Blenderのパフォーマンステスト
└── utils/            # テスト実行用のユーティリティ
```

## テストの実行方法

### 共通のテスト実行

すべてのテストを実行するには、以下のコマンドを使用します：

```bash
python tests/run_tests.py
```

特定の環境やテストタイプを指定することもできます：

```bash
# Maya環境の単体テストを実行
python tests/run_tests.py --env maya --type unit

# Blender環境の統合テストを実行
python tests/run_tests.py --env blender --type integration
```

### Maya用テストの実行

Maya環境でテストを実行するには、以下のいずれかの方法を使用します：

1. Mayaの内部から実行：
   ```python
   # Mayaのスクリプトエディタで実行
   import sys
   sys.path.append('/path/to/ywtatools')  # プロジェクトルートへのパスを指定
   import tests.run_maya_tests
   ```

2. mayapy.exeを使用して実行：
   ```bash
   mayapy.exe tests/run_maya_tests.py
   ```

オプションを指定することもできます：

```bash
mayapy.exe tests/run_maya_tests.py --type integration
```

### Blender用テストの実行

Blender環境でテストを実行するには、以下のいずれかの方法を使用します：

1. Blenderの内部から実行：
   ```python
   # Blenderのテキストエディタで実行
   import sys
   sys.path.append('/path/to/ywtatools')  # プロジェクトルートへのパスを指定
   import tests.run_blender_tests
   ```

2. blenderコマンドラインから実行：
   ```bash
   blender -b -P tests/run_blender_tests.py
   ```

オプションを指定することもできます：

```bash
blender -b -P tests/run_blender_tests.py -- --type integration
```

## 新しいテストの作成方法

### Maya用テストの作成

1. `tests/maya/unit/` ディレクトリに新しいテストファイルを作成します（例：`test_my_feature.py`）
2. `MayaTestCase` クラスを継承したテストクラスを作成します：

```python
from tests.maya.maya_test_case import MayaTestCase

class MyFeatureTests(MayaTestCase):
    """Mayaの機能テスト"""
    
    def test_something(self):
        """テスト関数"""
        # テストコードをここに記述
        self.assertEqual(1 + 1, 2)
    
    def test_maya_specific(self):
        """Maya固有のテスト"""
        # Mayaコマンドを使用したテスト
        if self.MAYA_AVAILABLE:
            sphere = self.create_test_node('polySphere')
            self.assertIsNotNone(sphere)
```

### Blender用テストの作成

1. `tests/blender/unit/` ディレクトリに新しいテストファイルを作成します（例：`test_my_addon.py`）
2. `BlenderTestCase` クラスを継承したテストクラスを作成します：

```python
from tests.blender.blender_test_case import BlenderTestCase

class MyAddonTests(BlenderTestCase):
    """Blenderアドオンのテスト"""
    
    @classmethod
    def setUpClass(cls):
        """テストクラスの初期化"""
        super().setUpClass()
        # アドオンを有効化
        cls.enable_addon('ywtatools_addon')
    
    def test_something(self):
        """テスト関数"""
        # テストコードをここに記述
        self.assertEqual(1 + 1, 2)
    
    def test_blender_specific(self):
        """Blender固有のテスト"""
        # Blender APIを使用したテスト
        if self.BLENDER_AVAILABLE:
            cube = self.create_test_object('MESH', 'TestCube')
            self.assertIsNotNone(cube)
            self.assertEqual(cube.name, 'TestCube')
```

## テスト設定のカスタマイズ

テスト実行の設定は `tests/common/test_settings.py` で定義されています。
以下のような設定をカスタマイズできます：

```python
from tests.common.test_settings import TestSettings

# 一時ファイルを削除しない
TestSettings.delete_files = False

# 出力バッファリングを無効化
TestSettings.buffer_output = False

# テスト間で新しいシーンを作成しない
TestSettings.new_scene_between_tests = False
```

## 高度なテスト機能

### 一時ファイルの作成

テスト中に一時ファイルを作成する必要がある場合は、`get_temp_filename` メソッドを使用します：

```python
def test_with_temp_file(self):
    # 一時ファイルパスを取得
    temp_file = self.get_temp_filename('test_data.json')
    
    # ファイルに書き込み
    with open(temp_file, 'w') as f:
        f.write('{"test": "data"}')
    
    # テスト終了時に自動的に削除されます
```

### 浮動小数点値の比較

浮動小数点値を含むリストや辞書を比較するための特殊なアサートメソッドが用意されています：

```python
def test_float_comparisons(self):
    list1 = [1.0001, 2.0002, 3.0003]
    list2 = [1.0002, 2.0003, 3.0004]
    
    # 小数点以下3桁まで一致していればOK
    self.assertListAlmostEqual(list1, list2, places=3)
    
    dict1 = {'a': 1.0001, 'b': 2.0002}
    dict2 = {'a': 1.0002, 'b': 2.0003}
    
    # 小数点以下3桁まで一致していればOK
    self.assertDictAlmostEqual(dict1, dict2, places=3)
