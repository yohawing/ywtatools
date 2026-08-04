---
name: test
description: YWTA Toolsのテストを実行します。Maya/Blenderのユニットテスト、統合テストに対応。「テスト」「test」「検証」などのキーワードで呼び出されます。
allowed-tools: Bash, Read, Glob, Grep
---

# テスト実行

## 概要

YWTA Tools のテストスイート（Maya / Blender）を実行します。

## 使用方法

```
/test [target] [type] [options]
```

### 引数

- `target`: `maya` または `blender`。省略時は両方の案内を出す
- `type`: テストタイプ（unit, integration, performance）。省略時は unit
- `--maya <version>`: Mayaバージョン指定（Mayaテスト用、既定 2024）

## テストコマンド

### Nox 経由（推奨）

```bash
uvx nox -s maya_tests
uvx nox -s maya_tests -- --type integration
uvx nox -s maya_tests -- --type unit --maya 2024

uvx nox -s blender_tests
uvx nox -s blender_tests -- --type integration
```

### 直接実行（Nox が使えない場合）

```bash
python tests/run_maya_tests.py --pattern "test_*.py" --maya 2024
python tests/run_maya_tests.py --type unit --maya 2024
python tests/run_maya_tests.py --type integration --maya 2024

blender -b -P tests/run_blender_tests.py
blender -b -P tests/run_blender_tests.py -- --type integration
```

Maya 内から実行する場合は YWTA > Utility > Unit Test Runner を使用してください。

## テストディレクトリ構成

```
tests/
├── common/           # 共通のテストユーティリティとベースクラス
├── maya/
│   ├── unit/
│   ├── integration/
│   └── performance/
├── blender/
│   ├── unit/
│   ├── integration/
│   └── performance/
└── utils/
```

詳細は `tests/README.md` を参照してください。

## 注意事項

- Maya/Blenderのテストは実機（mayapy / blender）が必要
- 失敗時は詳細なエラーログを確認する
- 新機能には対応するテストを作成する
