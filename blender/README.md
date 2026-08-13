# YWTA Blender Tools

[← YWTA Tools のトップへ戻る](../README.md)

Blender 4.4 以降で、Shape Keyの整理、Hair Tubeの作り直し、Remesh、表面の
Smoothingなどを行うアドオンです。

## マニュアル

ツールの場所、必要な選択、基本操作、Undo、既知の制限は
[Blender Manual](docs/README.md)にまとめています。

- [Modeling](docs/modeling/README.md) — Hair Tube、AutoRemesh、Volume Smoothing
- [Shape Keys](docs/shape-keys.md) — Shape Key名の検索と置換
- [Geometry Nodes](docs/geometry-nodes.md) — 追加ノード
- [Interface](docs/interface.md) — YWTAタブと補助パネル

## インストール

1. Blenderで `Edit > Preferences > File Paths` を開きます。
2. `Script Directories` に、このリポジトリの `blender` フォルダーを追加します。
3. Blenderを再起動します。
4. `Edit > Preferences > Add-ons` で `YWTA Tools` を検索し、有効にします。

有効化すると、3D Viewportのサイドバーに `YWTA` タブが追加されます。ツールは
Object、Edit Mode、Vertex、Geometry Nodesの各メニューにも配置されます。

## まず試す

追加のDLLを必要としないShape Keyの置換で、インストールを確認できます。

1. Shape Keyを持つMeshを選択します。
2. 3D Viewportで `N` キーを押し、`YWTA` タブを開きます。
3. `ShapeKey名の検索と置換` を展開します。
4. 検索文字と置換文字を入力し、`ShapeKey名を置換` を実行します。

成功すると、変更したObject数とShape Key数がステータスに表示されます。`Basis` は
変更されません。操作は通常のUndoで戻せます。

## ネイティブ機能

次のツールは、初回利用前にWindows DLLのビルドが必要です。

| ツール | ビルド |
| --- | --- |
| Hair Tube Curve Cage | `uvx nox -s mesh_core_tests` |
| AutoRemesh | `uvx nox -s autoremesher_build` |
| Volume Preserving Smooth | `uvx nox -s mesh_smoothing_build` |

生成されたDLLは `bin/windows/` から読み込まれます。要件と環境変数による上書き方法は、
各ツールのマニュアルを参照してください。

## テスト

リポジトリのルートで実行します。

```powershell
uvx nox -s blender_tests
uvx nox -s blender_tests -- --type integration
```

テストランナーは、インストール済みの最新Blenderを探します。見つからない場合は
`BLENDER_EXECUTABLE` に `blender.exe` の絶対パスを設定してください。詳しくは
[Tests](../tests/README.md)を参照してください。

## 開発者向けの配置

```text
blender/addons/ywtatools_addon/      アドオン本体
blender/modules/ywta_remesh/         AutoRemesherのPython接続
blender/modules/ywta_mesh_smoothing/ Volume SmoothingのPython接続
blender/modules/ywta_mesh_core/      Hair TubeのPython接続
blender/startup/                     起動時スクリプト
```
