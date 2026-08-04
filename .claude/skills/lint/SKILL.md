---
name: lint
description: Ruffを使用してPythonコードのリント・フォーマットを実行します。コード品質チェック、自動修正に対応。「lint」「リント」「フォーマット」「整形」などのキーワードで呼び出されます。
allowed-tools: Bash, Read, Glob
---

# コードリント・フォーマット

## 概要

Ruff を使用して Python コードのリント（静的解析）とフォーマット（整形）を実行します。

## 使用方法

```
/lint [path] [options]
```

### 引数

- `path`: チェック対象のパス（省略時はプロジェクト全体）
- `--fix`: 自動修正を適用
- `--format`: フォーマットのみ実行

## コマンド

### Nox 経由（推奨）

```bash
uvx nox -s lint
uvx nox -s lint -- maya/ywta/rig/
```

### 直接実行

```bash
# リントチェック
ruff check .

# フォーマットチェック（書き換えなし）
ruff format --check .

# 特定ファイル/ディレクトリ（修正・整形はパス明示で）
ruff check --fix maya/ywta/rig/joint_size.py
ruff format blender/addons/ywtatools_addon/shape_key_rename.py
```

**警告**: 未コミットのWIP差分がある間は、リポジトリ全体への `ruff check --fix .` / `ruff format .` を実行しない（WIP差分と整形差分が混ざる）。修正・整形は必ず対象パスを明示すること。自動修正できないエラーが約280件残っている（F403/F405 のワイルドカードimport等）。`maya/ywta/shortcuts.py` は再エクスポートハブのため F401/E402 除外（import を削除しない）。

ruff が未インストールの場合は `uvx ruff check .` のように `uvx` 経由で実行してください。

## プロジェクト設定

このプロジェクトの Ruff 設定（`pyproject.toml`）:

- **行の長さ**: 128文字
- **対象**: Python 3.10以上（Maya 2024）
- **select**: `E4, E7, E9, F`（既存コードへの diff 爆発を防ぐための最小構成）
- **fix は無効**（`ruff check` は報告のみ。修正は `--fix` をパス付きで明示）
- **tests/** は `E402` を許容

既存コードは一括整形していません。lint は自分が触ったファイルに限定して実行してください。

## よくあるエラー

| コード | 説明 | 対処 |
|--------|------|------|
| F401 | 未使用のインポート | 削除または `# noqa: F401` |
| F841 | 未使用の変数 | 削除または `_` プレフィックス |
| E9xx | 構文エラー | コードを修正 |

## 注意事項

- コミット前にリントを実行することを推奨
- 危険な修正は `--unsafe-fixes` オプションが必要
