# Dependency Tools

YWTA Python ModuleのImport関係と循環依存を調べます。

## Dependency Visualizer

### Reference

- **Menu:** `YWTA > Utility > Dependency Visualizer`
- **Audience:** YWTA開発者

依存関係をTreeで表示し、循環を確認できます。分析だけではSceneやSource Fileを変更しません。

`__init__.pyファイルを更新`はSource Fileを直接書き換えます。確認Dialog、Backup、Maya Undoは
ありません。Git差分を確認できる状態でのみ使用してください。

## Dependencies Analyzer CLI

### Reference

- **Menu:** `YWTA > Utility > Dependencies Analyzer CLI`

CLIの使用例をDialogに表示します。

## Known Limitations

表示例に含まれる`generate_dependency_graph(...)`は、現在の実装に存在しません。その行は
実行しないでください。`analyze_dependencies()`と`detect_cycles()`は利用できます。
