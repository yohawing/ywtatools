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

# リント + 自動修正
ruff check --fix .

# フォーマットチェック
ruff format --check .

# フォーマット適用
ruff format .

# 特定ファイル/ディレクトリ
ruff check maya/ywta/rig/
ruff format blender/addons/ywtatools_addon/
```

ruff が未インストールの場合は `uvx ruff check .` のように `uvx` 経由で実行してください。

## プロジェクト設定

このプロジェクトの Ruff 設定（`pyproject.toml`）:

- **行の長さ**: 128文字
- **対象**: Python 3.10以上（Maya 2024）
- **select**: `E4, E7, E9, F`（既存コードへの diff 爆発を防ぐための最小構成）
- **fix = true**: `ruff check` 実行時に自動修正が適用される
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
