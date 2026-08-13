# Maya ツールガイド

`YWTA` メニューにあるツールを、やりたい作業から探すためのガイドです。
インストールがまだの場合は、先に [Maya README](../README.md) を参照してください。

## やりたいことから探す

- [ジョイントやコントローラーを作る](rigging.md)
  — Joint、Constraint、Control、Skeleton、HumanIK
- [スキンウェイトや BlendShape を編集する](deform.md)
  — Skin Weight、Skinned Mesh、Shape、Deformer
- [ポーズやアニメーションを保存・再利用する](animation.md)
  — Selection Set、Pose、Animation Clip
- [メッシュを結合・整形する](mesh.md)
  — 頂点ロック、Merge、AutoRemesher、Smoothing
- [スクリプト実行や FBX 書き出しを行う](pipeline-export.md)
  — Run Script、Batch Runner、FBX Export
- [シーンの検査や開発作業を行う](utility.md)
  — Scene Audit、Test Runner、Dependency、Reload

## 各ページの読み方

ツール名の横に、操作の性質を短く記載しています。

- **Undo 1回** — 実装上、操作全体を1回の Undo で戻せます。
- **シーン変更なし** — ノードや属性を変更しません。選択が変わることはあります。
- **ファイル保存** — JSON や FBX の変更は Maya の Undo では戻りません。
- **要バックアップ** — 一括 Undo や失敗時の復元が保証されていない機能です。
- **開発者向け** — 任意コード実行やソースファイル変更など、制作作業以外の機能です。

> [!IMPORTANT]
> 初めて使う編集ツールは、保存済みシーンのコピーで試してください。特に
> **要バックアップ** と書かれた機能は、Maya の Undo だけに頼らないでください。

## メニュー構成

```text
YWTA
├─ Animation
├─ Mesh
├─ Rigging
├─ Deform
├─ Utility
├─ Run Script
├─ Batch Runner
├─ Export Selected FBX
├─ Export Animation FBX
└─ Documentation
```

このガイドは、現在のメニュー定義と実装、関連テストを基にしています。今回、Maya GUI
上で全ツールを操作する実機確認は行っていません。既知の制限は各ページに明記しています。
