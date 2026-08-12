# YWTA Tools

個人制作で使う DCC 向けテクニカルアーティストツール集です。Maya、Blender、
Photoshop の各ツールと、複数の DCC から利用するネイティブコアを同じリポジトリで
管理しています。

この README はリポジトリ全体のインデックスです。導入方法と機能の詳細は、対象の
ツールに対応する README を参照してください。

## ツール一覧

| 対象 | 内容 | ドキュメント |
| --- | --- | --- |
| Maya 2024 | リギング、スキニング、アニメーション、メッシュ、入出力、パイプライン支援 | [Maya Tools](./maya/README.md) |
| Blender 4.4 以降 | Geometry Nodes、Shape Key、AutoRemesher、ボリューム保持スムージング | [Blender Tools](./blender/README.md) |
| Photoshop 24.4 以降 | PBR / Toon テクスチャ生成・書き出し用 UXP プラグイン | [Photoshop Tools](./photoshop/README.md) |
| 共有 C++ コア | AutoRemesher と DCC 向け C ABI | [C++ Components](./cpp/README.md) |
| 共有 Rust コア | ボリューム保持メッシュスムージングと C ABI | [Rust Components](./rust/README.md) |

Maya ツールは [chadmv/cmt](https://github.com/chadmv/cmt) をベースに、個人制作向けの
機能追加と変更を行っています。

## リポジトリ構成

```text
maya/                 Maya Python モジュール、C++ プラグイン、アイコン
blender/              Blender アドオンとネイティブ DLL バインディング
photoshop/            Photoshop UXP プラグイン
cpp/                  共有 C++ コアと C ABI
rust/                 共有 Rust クレートと C ABI
external/             外部ソースの submodule
tests/                DCC 別・共有コアのテスト
docs/                 横断的な設計・採用方針
```

各ツール固有の利用方法は、その実装に最も近い README に置きます。ルート README
には個別機能の操作手順を重複させず、追加・移動されたツールを見つけるための索引だけを
保ちます。

## 開発

Windows 11 上での開発を前提としています。Python 依存は
[`requirements.txt`](./requirements.txt)、テスト構成は
[`tests/README.md`](./tests/README.md) を参照してください。

代表的な検証コマンドは次のとおりです。

```powershell
uvx nox -s lint
uvx nox -s maya_tests -- --type unit --maya 2024
uvx nox -s blender_tests
uvx nox -s photoshop_validate
```

開発ルール、対応環境、コミット規律は [`AGENTS.md`](./AGENTS.md) を参照してください。

## ライセンス

このリポジトリのライセンスは [`LICENSE`](./LICENSE) を参照してください。外部コードや
submodule には、それぞれのライセンスが適用されます。
