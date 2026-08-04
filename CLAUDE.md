# ywtatools

## プロジェクト概要

Maya / Blender 用のテクニカルアーティストツール集です。個人プロジェクトで使う、リギング・デフォーメーション・アニメーション・メッシュ処理系のツールとユーティリティをまとめています。
Maya 側は [chadmv/cmt](https://github.com/chadmv/cmt) をベースにしています。

### 対応プラットフォーム

- Autodesk Maya 2024 (Python 3.10)
- Blender（アドオンとして実装）
- Windows 11 での開発を前提

## ディレクトリ構成

```
maya/ywta/          Mayaモジュール本体（Python）。rig/, deform/, mesh/, anim/, io/, ui/, utility/ など機能別に分類
maya/cpp/           Maya C++プラグインソース（CMakeビルド）
maya/icons/         UIアイコン
maya/plug-ins/      コンパイル済みプラグイン
blender/addons/     Blenderアドオン
tests/              Maya/Blender共通のテストフレームワーク（tests/README.md 参照）
```

新機能を追加するときは、適切なサブモジュール（rig/, deform/, mesh/ 等）に配置し、`menu.py` にメニューエントリを追加、必要ならアイコンを作成し、対応するテストコードを `tests/maya/unit/` または `tests/blender/unit/` に作成してください。

## コーディング規約

### 一般

- コードは読みやすく保守性を重視し、シンプルかつ必要最低限な実装にする。長いコードや複雑なロジックは避ける
- コメント・docstring は日本語で記述する
- 既存コードパターンを踏襲する

### Python

- PEP 8 準拠、インデントは4スペース
- Maya Python API 2.0 を優先使用（高速化が期待できる箇所は必須）
- docstring は必須（Google スタイル推奨）
- 型ヒントの使用を推奨
- UI は PySide2/PySide6 の両対応で記述する:
  ```python
  try:
      from PySide6.QtCore import QObject, Qt
  except ImportError:
      from PySide2.QtCore import QObject, Qt
  ```
- 命名規則: クラスは PascalCase、関数/変数は snake_case、定数は UPPER_SNAKE_CASE、プライベートは先頭に `_`

### C++

- `.clang-format` ファイルに従う
- Maya C++ API を使用、CMake でビルド（`maya/cpp/build.bat`）

### 依存関係

- 外部依存の無断追加は禁止。Python の依存は numpy, scipy, pyparsing のみ（`requirements.txt` 参照）
- Maya/Blender の安定性を損なう可能性のあるコードは禁止

## タスクランナー（Nox）

新しいビルド・検証タスクを追加するときは、設定ファイルを増やさないため、原則としてルートの `noxfile.py` に Nox セッションとして追加してください。Nox は追加の venv を作らず（`venv_backend="none"`）、既存の Python 環境・mayapy・blender を呼び出す薄いランナーとして使います。

よく使うコマンド:

```bash
# lint
uvx nox -s lint

# Mayaテスト（tests/run_maya_tests.py をラップ）
uvx nox -s maya_tests
uvx nox -s maya_tests -- --type integration
uvx nox -s maya_tests -- --type unit --maya 2024

# Blenderテスト（tests/run_blender_tests.py をラップ）
uvx nox -s blender_tests
uvx nox -s blender_tests -- --type integration

# AutoRemesher コアDLLのビルド（要 VS2022 + CMake、Qt不要）
uvx nox -s autoremesher_build
```

既存の `tests/run_maya_tests.py` / `tests/run_blender_tests.py` を直接実行することも可能です（詳細は `tests/README.md`）。

## テスト

- Maya: `python tests/run_maya_tests.py --pattern "test_*.py" --maya 2024`（または `uvx nox -s maya_tests`）
- Blender: `python tests/run_blender_tests.py`（または `uvx nox -s blender_tests`）
- `--type unit|integration|performance` でテスト種別を指定
- Maya 内から実行する場合は YWTA > Utility > Unit Test Runner を使用
- 新機能には対応するテストを作成する

## Lint

```bash
ruff check .
# または
uvx nox -s lint
```

既存コードは safe fix + format 適用済みだが、自動修正できないlintエラーが約270件残っている（大半はワイルドカードimport由来の F403/F405、ほか E722/F841/F821 など）。未コミットのWIP差分がある間は、**リポジトリ全体への `ruff check --fix .` / `ruff format .` を実行しない**（WIP差分と整形差分が混ざる事故が過去に発生）。修正・整形は `ruff format <file>` のようにパスを明示して実行すること。`maya/ywta/shortcuts.py` は再エクスポートハブのため F401/E402 を除外している（import を削除しない）。

## AutoRemesher 統合

自動クアッドリメッシャー [huxingyi/autoremesher](https://github.com/huxingyi/autoremesher)（MIT）を `external/autoremesher` に submodule（1.0.0 pin）として取り込み、コア（Qt非依存）を利用している。**submodule 内のファイルは改変禁止**（回避が必要な場合は `cpp/autoremesher_core/qtshim/` のようにヘッダ差し込みで対応する）。

- `cpp/autoremesher_core/` — コア静的 lib + Blender 用 C ABI DLL（`uvx nox -s autoremesher_build` → `bin/windows/ywta_autoremesher.dll`）
- Maya: `maya/cpp/src/autoRemesherNode.cpp`（MPxNode、コアを静的リンク）+ `maya/ywta/mesh/autoremesher.py`（ノード作成ヘルパー）。ビルドは `maya/cpp/build.bat`
- Blender: `blender/modules/ywta_remesh/binding.py`（ctypes）+ `ywtatools_addon/autoremesher.py`（オペレータ）。DLL は `YWTA_AUTOREMESHER_DLL` 環境変数で上書き可

## コミット規律

- 1タスク = 1コミット。複数タスクを連続して進める場合も、タスク単位で実装・検証・コミットを分ける
- コミット前に lint と関連テストを実行する
- 完了記録はコミットメッセージが正本。`TODO.md` に完了履歴を溜めない（下記参照）
- コミットメッセージのプレフィックス:
  - `rig:` リギング関連
  - `anim:` アニメーション関連
  - `deform:` デフォーメーション関連
  - `blender:` Blenderアドオン関連
  - `cpp:` C++プラグイン関連
  - `test:` テスト関連
  - `docs:` ドキュメント関連

## TODO.md 運用ルール

`TODO.md` はリポジトリにコミットしない、ローカル専用の実行キューです（`.gitignore` 対象）。

- 次に着手するタスクを列挙する場所であり、完了したタスクの履歴を残す場所ではない
- タスクが完了したらエントリを削除し、完了記録はコミットメッセージに書く
- 恒久的な設計方針や仕様は `TODO.md` ではなく `AGENTS.md` やコード自体のコメントに反映する

## 禁止事項

- ライセンス違反となるコードの使用
- Maya/Blender の安定性を損なう可能性のあるコード
- 外部依存関係の無断追加
