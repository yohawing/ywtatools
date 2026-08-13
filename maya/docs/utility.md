# Utility ツール

[← ツールガイドへ戻る](README.md)

メニュー: `YWTA > Utility`

## シーンの問題を探す

### Scene Audit

次の問題を、シーンを修正せずに検査します。

- Transform / Jointの重複したShort Name
- Non-manifold Vertex / Edge
- Lamina Face
- 面積0または非有限のFace

Scene全体、または選択Meshだけを検査できます。結果から `Select Issues` を押すと該当箇所が
選択されます。自動修復は行いません。**シーン変更なし**です。

## Maya内でテストを実行する

### Unit Test Runner

Unit / Integration / Performance Testを一覧から実行します。

> [!CAUTION]
> `New Scene Between Test` は既定でオンです。テストごとに新規Sceneを作るため、未保存の
> 制作Sceneを失う可能性があります。必ず専用のMaya Sessionで使用してください。

実行後はTest件数が0でないことと、Pass / Fail / Error / Skippedを確認します。

## Python Moduleの依存関係を調べる

### Dependency Visualizer

YWTA ModuleのImport関係と循環依存を表示します。分析だけならシーンを変更しません。

> [!WARNING]
> `__init__.pyファイルを更新` はSource Fileを直接書き換えます。確認Dialog、Backup、Maya Undoは
> ありません。Git差分を確認できる開発者だけが使用してください。

### Dependencies Analyzer CLI

CLIの使用例をDialogに表示します。

> [!WARNING]
> 表示例にある `generate_dependency_graph(...)` は現在の実装に存在しません。その行は実行
> しないでください。`analyze_dependencies()` と `detect_cycles()` は利用できます。

## Moduleを再読み込みする

### Reload All Modules

名前に反して、すでに読み込まれた全Moduleを再読み込みする機能ではありません。初期Snapshot
より後に読み込まれたModuleだけを対象とし、Reload中の例外も表示しません。状態が不整合に
なった場合はMayaを再起動してください。**開発者向け**です。

## MayaのIconを探す

### Resource Browser

Maya標準のResource Browserを開きます。YWTA固有の管理ツールではありません。
表示するだけなら **シーン変更なし**です。
