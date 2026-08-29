# YWTA Tools

Maya、Blender、Photoshop での制作を少し楽にするために作っている、個人用の
テクニカルアーティストツール集です。

リギングやスキニングのように何度も繰り返す作業、メッシュの調整、テクスチャの
書き出しなどを、なるべく安全に、少ない手順で済ませることを目指しています。

## 使いたいアプリから選ぶ

### [Maya Tools](./maya/README.md)

Maya 2024 向けのメインツール群です。ジョイントやコントロールの作成、スキンウェイト、
Pose / Animation Clip、FBX 書き出し、メッシュ処理などを `YWTA` メニューから使えます。

### [Blender Tools](./blender/README.md)

Blender 4.4 以降向けのアドオンです。Shape Key 名の一括置換、Hair Tube の Curve 編集、
Geometry Nodes の補助、クアッドリメッシュ、形を保つスムージングを収録しています。

### [Photoshop Tools](./photoshop/README.md)

Photoshop 24.4 以降向けの UXP プラグインです。PSD のレイヤーグループから PBR / Toon
テクスチャをまとめて書き出せます。

## このリポジトリについて

それぞれのアプリ向けツールに加えて、Maya と Blender の両方で使う処理を C++ と Rust
で共有しています。通常の利用では内部構造を意識する必要はありません。ネイティブ機能を
自分でビルドしたい場合は、次の README を参照してください。

- [C++ Components](./cpp/README.md) — AutoRemesher
- [Rust Components](./rust/README.md) — ボリューム保持メッシュスムージング

Maya ツールの一部は [chadmv/cmt](https://github.com/chadmv/cmt) をベースに、個人制作で
使いやすいよう機能追加と変更を行っています。

### YWTA Link Developer Preview

YWTA Linkは、同じWindowsユーザーセッションのMaya、Blender、UnityをローカルBroker経由で接続する
開発中の基盤です。Raw TCP Broker、CLI Monitor、Python/C# Client、Maya/Blenderの再生同期、
Unity Timeline同期、3アプリのCamera同期を実装しています。配布用インストーラーと
Photoshop、Substance Painter Adapterは未実装です。

開発版を試す場合はBrokerをビルドし、Maya、Blender、Unity Editorを起動するシェルで実行ファイルを指定します。

```powershell
cargo build --manifest-path rust/ywta-link/Cargo.toml
$env:YWTA_LINK_EXE = (Resolve-Path .\target\debug\ywta-link.exe).Path
& $env:YWTA_LINK_EXE --help
```

`usage: ywta-link <serve|status|peers|rooms> [options]`が表示されれば準備完了です。詳しい実装境界、
Playback/Timeline/Camera Syncの開始方法、Protocol契約は[YWTA Link v1 仕様](./specs/ywta-link-v1.md)を
参照してください。

## 開発に参加する場合

開発環境は Windows 11 を前提としています。まずは対象アプリの README を読み、全体の
テスト構成は [`tests/README.md`](./tests/README.md)、開発ルールは
[`AGENTS.md`](./AGENTS.md) を参照してください。Python の依存パッケージは
[`requirements.txt`](./requirements.txt) にまとめています。

よく使う検証コマンドは次のとおりです。

```powershell
uvx nox -s lint
uvx nox -s maya_tests -- --type unit --maya 2024
uvx nox -s blender_tests
uvx nox -s photoshop_validate
```

コードの主な配置は次のとおりです。

```text
maya/        Maya ツール
blender/     Blender アドオン
photoshop/   Photoshop UXP プラグイン
cpp/         共有 C++ コア
rust/        共有 Rust コア
tests/       テスト
docs/        Git管理外のローカル設計資料
```

## ライセンス

このリポジトリのライセンスは [`LICENSE`](./LICENSE) を参照してください。外部コードと
submodule には、それぞれのライセンスが適用されます。
