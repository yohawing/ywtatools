# Utility

メニューは `YWTA > Utility`。Scene Audit と Resource Browser は読み取り／表示中心ですが、
開発用のテスト・依存関係・reload は scene 外のファイルや Python runtime に影響します。

## Scene Audit

### `YWTA > Utility > Scene Audit`

重複 transform/joint short name、non-manifold vertex/edge、lamina face、world-space 面積 0 または
非有限 face を監査します。

- **準備**: Scene 全体、または mesh transform/shape/component を選択。
- **最小手順**: Audit → report のカテゴリを選択 → 必要なら Select Issues。
- **確認**: report の node/component と viewport の選択が一致すること。選択操作は古い report を
  再利用せず再監査します。
- **安全**: **シーン変更なし / 選択のみ**。自動修復はありません。dry-run、mapping、Undo の
  共通 contract が TODO であるため、修復目的で別コマンドを組み合わせないでください。

## Unit Test Runner

### `YWTA > Utility > Unit Test Runner`

Maya 内の unittest を一覧化し、Run All/Selected/Failed と Refresh を提供します。`tests/maya`
の unit/integration/performance を対象にします。

- **重要な既定値**: Settings の `New Scene Between Test` は **オン**。各 test case 後に新規 scene
  を作るため、未保存の production scene を破棄する可能性があります。専用の保存済み test scene
  または専用 Maya session で実行し、必要ならオプションをオフにします。
- `Buffer Output` は成功時の出力を隠し、失敗時だけ表示。テスト runner の rollback importer は
  import 時のコード更新を拾います。
- **確認**: 件数が0でないこと、pass/fail/error/skipped と output を確認。CLI の単体テストは
  `python tests/run_maya_tests.py --type unit --maya 2024` でも実行できます。
- **安全**: テストは scene、plugin、temp file を操作する可能性があり、通常の Maya Undo と
  独立です。専用 session を推奨します。

## Dependency Visualizer

### `YWTA > Utility > Dependency Visualizer`

YWTA module の import 依存と循環を分析し、tree と cycle を表示します。filter（例 `ywta.rig`）
で絞り込めます。

- **最小手順**: Analyze → tree/cycle を確認。必要なら選択 module の更新対象を指定。
- **危険な操作**: `__init__.pyファイルを更新` は依存コメントを各 `__init__.py` へ直接書き戻し、
  Maya Undo、バックアップ、transaction を持ちません。**開発者専用 / 破壊的**として git/ファイル
  バックアップを取り、差分を確認してから実行します。
- **確認**: 更新後に対象ファイルの diff と Python import を確認。分析だけならシーン変更なし。

## Dependencies Analyzer CLI

### `YWTA > Utility > Dependencies Analyzer CLI`

コマンドライン利用例を confirm dialog に表示します。`analyze_dependencies()` と
`detect_cycles()` は現在の実装に存在しますが、表示 snippet にある
`generate_dependency_graph(...)` は現行 module に存在しない stale line です。

**既知の制限**: その `generate_dependency_graph` 行は実行しないでください。必要なら `main()` の
`--output` / `--detect-cycles` をソースで確認した上で、開発者が別環境へ出力します。dialog の
表示自体は **シーン変更なし** です。

## Reload All Modules

### `YWTA > Utility > Reload All Modules`

初回 importer snapshot に存在しなかった module を `importlib.reload` します。**「すでに読み込まれた
すべての module」を文字どおり再読み込みする機能ではなく**、reload 例外を隠します。依存 module の
古い参照や部分的な状態が残る可能性があるため、**開発者専用**。未保存 scene/UI を保存し、問題が
出た場合は Maya を再起動して import を検証します。scene/file の Undo はありません。

## Resource Browser

### `YWTA > Utility > Resource Browser`

Maya 標準 `resourceBrowser` を開きます。Maya のアイコン・resource を検索／閲覧するだけで、
YWTA scene data は変更しません（**シーン変更なし**）。標準 UI の保存機能を使う場合は、
その file 操作が Maya Undo 外であることを覚えておいてください。
