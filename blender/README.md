# YWTA Blender Tools

[← YWTA Tools のトップへ戻る](../README.md)

Blender 4.4 以降向けの小さなツール集です。Shape Key の整理、Geometry Nodes の補助、
リメッシュ、表面のスムージングなど、モデリング中に繰り返しやすい作業をまとめています。

## インストール

1. Blender の `Edit > Preferences > File Paths` を開きます。
2. `Script Directories` に、このリポジトリの `blender` フォルダーを追加します。
3. Blender を再起動します。
4. `Edit > Preferences > Add-ons` で `YWTA Tools` を検索し、有効にします。

有効化すると、3D Viewport のサイドバーに `YWTA` タブが追加されます。機能によっては
Object メニュー、Edit Mode の Vertex メニュー、Geometry Nodes の Add メニューにも
項目が追加されます。

## できること

### Shape Key の名前をまとめて直す

3D Viewport の `YWTA > ShapeKey名の検索と置換` を開きます。検索する文字と置換後の
文字を入力するだけで、複数の Shape Key 名をまとめて変更できます。大文字小文字を
区別するか、選択中のオブジェクトだけを対象にするかも選べます。`Basis` は変更しません。

### Geometry Nodes を組みやすくする

Geometry Nodes エディターの `Add > Extra` に、次のノードを追加します。

- **Angle From Vector** — 2つのベクトルが作る角度を計算します。
- **Group Wrapper** — Geometry Node Group をラップして追加します。

### メッシュをクアッドへリメッシュする

Object Mode でメッシュを選び、`Object > AutoRemesh` を実行します。処理後も Redo
パネル（F9）から、目標ポリゴン数、形状への追従度、Organic / Hard Surface などを
調整できます。

この機能は初回だけ C++ DLL のビルドが必要です。

```powershell
git submodule update --init external/autoremesher
uvx nox -s autoremesher_build
```

通常は生成された `bin/windows/ywta_autoremesher.dll` をそのまま使います。別の場所へ
置く場合だけ、Blender を起動する前に `YWTA_AUTOREMESHER_DLL` へ絶対パスを設定して
ください。詳しいビルド条件は [C++ Components](../cpp/README.md) にあります。

### 形を保ちながら表面を滑らかにする

Edit Mode で頂点を選び、`Vertex > Volume Preserving Smooth` を実行します。通常の
スムージングよりもボリュームを保ちながら、表面の凹凸を整えられます。

Vertex Group を処理の強さとして使うこともできます。hard edge、seam、crease、選択
エッジは輪郭として残せます。ブラシで調整したい場合は、3D Viewport 左側の Toolbar
（T キー）から `Volume Smooth Brush` を選びます。

この機能は初回だけ Rust DLL のビルドが必要です。

```powershell
uvx nox -s mesh_smoothing_build
uvx nox -s mesh_smoothing_ffi_smoke
```

通常は `bin/windows/ywta_mesh_smoothing.dll` が使われます。別の場所へ置く場合は、
Blender を起動する前に `YWTA_MESH_SMOOTHING_DLL` へ絶対パスを設定してください。
詳しくは [Rust Components](../rust/README.md) を参照してください。

## テスト

リポジトリのルートから次を実行します。

```powershell
uvx nox -s blender_tests
uvx nox -s blender_tests -- --type integration
```

テストランナーは、インストール済みの最新 Blender を探して使用します。見つからない
場合は `BLENDER_EXECUTABLE` に `blender.exe` の絶対パスを設定してください。その他の
実行方法は [`tests/README.md`](../tests/README.md) にまとめています。

## 開発者向けの配置案内

```text
blender/addons/ywtatools_addon/      アドオン本体
blender/modules/ywta_remesh/         AutoRemesher の接続部分
blender/modules/ywta_mesh_smoothing/ スムージングの接続部分
blender/startup/                     起動時スクリプト
```
