# YWTA Blender Tools

[リポジトリ全体のインデックスへ戻る](../README.md)

Blender 4.4 以降向けのアドオンです。Geometry Nodes の補助ノード、Shape Key の
一括リネーム、クアッドリメッシュ、ボリューム保持スムージングを提供します。

## インストール

1. Blender の `Edit > Preferences > File Paths` を開く
2. `Script Directories` に、このリポジトリの `blender` ディレクトリを追加する
3. Blender を再起動する
4. `Edit > Preferences > Add-ons` で `YWTA Tools` を検索して有効化する

有効化後、主な UI は 3D Viewport のサイドバーにある `YWTA` タブ、Object メニュー、
Edit Mode の Vertex メニュー、Geometry Nodes の Add メニューへ追加されます。

## 機能

### Geometry Nodes

- **Angle From Vector**: 2つのベクトルの内積から角度を計算
- **Group Wrapper**: Geometry Node Group をラップして追加

Geometry Nodes エディターの `Add > Extra` から利用できます。

### Shape Key Rename

3D Viewport の `YWTA > ShapeKey名の検索と置換` から、Shape Key 名を検索・置換します。
大文字小文字の区別と、選択オブジェクトだけを対象にするかを指定できます。`Basis` は
変更しません。

### AutoRemesher

Object Mode でメッシュを選択し、`Object > AutoRemesh` を実行します。実行後は Redo
パネル（F9）で目標ポリゴン数、適応度、Organic / Hard Surface などを調整できます。

利用前に C++ DLL をビルドしてください。

```powershell
git submodule update --init external/autoremesher
uvx nox -s autoremesher_build
```

DLL は `bin/windows/ywta_autoremesher.dll` に生成されます。別の場所へ配置する場合は、
Blender の起動前に `YWTA_AUTOREMESHER_DLL` へ絶対パスを設定します。ビルドの詳細は
[C++ Components](../cpp/README.md) を参照してください。

### Volume Preserving Smoothing

Edit Mode の `Vertex > Volume Preserving Smooth` から、選択メッシュを体積保持しながら
平滑化します。Vertex Group を連続マスクとして指定でき、hard edge、seam、crease、
選択エッジを輪郭 rail として保持できます。

ブラシ版は 3D Viewport 左側の Toolbar（T キー）にある `Volume Smooth Brush` です。
Tool Settings から Smooth / Volume / Remove Bumps、半径、強度を調整できます。

利用前に Rust DLL をビルドして FFI smoke test を実行します。

```powershell
uvx nox -s mesh_smoothing_build
uvx nox -s mesh_smoothing_ffi_smoke
```

DLL は `bin/windows/ywta_mesh_smoothing.dll` に生成されます。別の場所へ配置する場合は、
Blender の起動前に `YWTA_MESH_SMOOTHING_DLL` へ絶対パスを設定します。詳細は
[Rust Components](../rust/README.md) を参照してください。

## テスト

```powershell
uvx nox -s blender_tests
uvx nox -s blender_tests -- --type integration
```

テストランナーはインストール済みの最新 Blender を自動検出します。検出できない場合は
`BLENDER_EXECUTABLE` に `blender.exe` の絶対パスを設定してください。詳細は
[`tests/README.md`](../tests/README.md) を参照してください。

## 実装場所

```text
blender/addons/ywtatools_addon/     アドオン本体
blender/modules/ywta_remesh/        AutoRemesher DLL バインディング
blender/modules/ywta_mesh_smoothing/ スムージング DLL バインディング
blender/startup/                     Blender startup スクリプト
```
