# 共通メッシュ基盤ライブラリ比較スパイク

## 結論

`ywta_mesh_core` を DCC 非依存の C++ コアとして採用し、内部を次の二層に分ける。

1. 外部ライブラリに依存しない `RawTopology` が flat buffer を検査する。
2. manifold かつ orientable と確認できた入力だけを PMP Library 3.0.0 へ変換する。

PMP は編集・remesh・穴埋めの第一バックエンドとして採用する。ただし、壊れた入力の
診断や自動修復の正本にはしない。Lox、Geometry Central、CGAL Polygon Mesh Processing
は現段階では採用しない。

責務境界の確信度は「高」、PMP採用の確信度は「中」。PMP と Lox の Windowsプローブに
加え、実GLB 29件のtopologyを診断した。一方、Maya / Blender実機への組み込み、PMPへの
変換コスト、PMPの穴埋め品質はまだ検証していない。

## 目的と成功条件

本当に決めるべきことは、汎用メッシュライブラリの機能数ではなく、壊れた DCC メッシュを
クラッシュさせずに診断し、その後の安全な処理だけを共通化できる責務境界である。

成功条件は次のとおり。

- Maya / Blender の flat buffer から元の vertex / face index を失わず診断できる。
- non-manifold edge、bow-tie vertex、winding 不整合をライブラリ構築前に報告できる。
- manifold 入力では boundary、sharp edge、rail chain を安定して辿れる。
- edge split / collapse、remesh、単純な穴埋めを後から追加できる。
- Maya は静的リンク、Blender は C ABI DLL という既存の配布方式を維持できる。
- permissive license だけで製品バイナリを配布できる。

## 非目標

- このスパイクでは外部ライブラリを submodule や依存として追加しない。
- non-manifold mesh の自動修復アルゴリズムは実装しない。
- UV、color set、skin weight の転送方式は決めない。
- Maya / Blender UI、Undo / Redo、実アセット品質の承認は行わない。
- CGAL と同等の厳密幾何カーネルを自作しない。

## 前提と制約

- 開発・配布対象は Windows 11、Maya 2024、Blender である。
- 現在の `autoremesher_core` は C++14、Maya は静的リンク、Blender は C ABI DLL と
  `ctypes` を使う。
- 外部 C++ / Rust の例外、panic、コンテナ、allocator を ABI 越しに公開しない。
- 元 DCC 要素への対応を維持できない編集は、診断処理と同じAPIに混ぜない。
- 穴埋めは自動実行せず、単純な manifold boundary loop への opt-in 操作に限定する。

## 評価結果

| 項目 | PMP 3.0.0 | Lox 0.1.1 | Geometry Central 1.1.0 | CGAL PMP |
|---|---|---|---|---|
| 言語 | C++17 | Rust | C++11 | C++17 |
| ライセンス | MIT | MIT / Apache-2.0 | MIT | GPL または商用 |
| polygon mesh | 対応 | `PolyConfig` で対応 | 対応 | 対応 |
| boundary loop | boundary halfedge を走査 | adjacency から自作 | 明示的な `BoundaryLoop` | 対応 |
| non-manifold 入力 | `TopologyException` で拒否 | panic で拒否 | 一般 `SurfaceMesh` で保持可能 | polygon soup の診断・修復が豊富 |
| edge split | 対応 | triangle mesh で対応 | 主に `ManifoldSurfaceMesh` で対応 | 対応 |
| edge collapse | 対応 | 公開 `MeshMut` API になし | 主に triangle manifold mesh で対応 | 対応 |
| remesh | 対応 | なし | manifold mesh で対応 | 対応 |
| hole fill | 単純な manifold hole に対応 | なし | 標準の穴埋めAPIを確認できず | 対応 |
| sharp / rail | feature tag + 独自chain抽出 | 独自実装 | 独自実装 | feature APIあり |
| Windows統合 | CMake / VS2022で実証 | Cargo / MSVCで実証 | CMake、依存追加あり | Boost等の構成負担が大きい |
| 現構成との距離 | 小さい | Rust C ABI層が新規に必要 | 小〜中 | 大きい |
| 判断 | 採用 | 不採用 | 保留候補 | 製品依存には不採用 |

### PMP Library

採用理由は、現リポジトリの CMake / C++ と同じ技術境界で、必要な編集操作と標準的な
アルゴリズムが揃うためである。MITであり、viewerを無効化すればOpenGL系依存は不要である。

安定タグ 3.0.0 は C++17 でビルドできる。公式サイトが示す現行mainの要件はC++20で、
2026-08-03時点のmainも `cxx_std_20` だったため、追従ではなく 3.0.0 pin を前提とする。

注意点は次のとおり。

- `SurfaceMesh::add_face()` は complex edge / vertex を例外で拒否するため、診断器ではない。
- `flip()` は呼び出し側にもmanifold性の確認を要求する。
- hole fill は単純なmanifold holeが前提である。
- 3.0.0のCMakeは `PMP_INSTALL=OFF` で利用側への公開include pathも外れる。
  組み込み時は `PMP_INSTALL=ON` のままinstall targetを実行しないか、上位側でincludeを補う。
- 同梱Eigenを日本語コードページのMSVCでビルドするとC4819警告が出るが、今回のRelease
  ビルドと実行結果には影響しなかった。

### Lox

型付きhandle、connectivityとproperty mapの分離、triangle / polygon構造の切替はよい。
一方、現在の目的に対しては採用コストに見合わない。

- crateは0.1.1で、公式説明も組み込みアルゴリズムが少ないこととIO未実装を明記している。
- splitはあるがcollapse、remesh、hole fillがない。
- 不正なface追加は `Result` ではなくpanicで拒否される。
- 未接続頂点も `is_boundary()` がtrueになり、DCC診断で必要な「孤立」と「boundary loop」の
  分類をそのまま表現しない。
- 現リポジトリにCargo、Rust DLL、panic捕捉、C ABIの保守面を新しく追加する。

将来、共通コア全体をRustへ移す別の理由が生じた場合だけ再評価する。Lox単体の機能は
その移行理由にならない。

### Geometry Central

一般 `SurfaceMesh` がnon-manifoldを保持でき、manifold型ではboundary loopとmutation時の
data追従が強い。ただし一般mesh対応は比較的新しく、split / collapse / remeshなど必要な
編集操作の多くは `ManifoldSurfaceMesh` 側に残る。結局、壊れた入力から編集可能meshへの
昇格判定は自前で必要になる。

研究系アルゴリズムやmutation追従propertyが将来必要になった場合の第二候補とする。
現用途ではPMPより大きな利点がなく、同時採用もしない。

### CGAL Polygon Mesh Processing

polygon soup修復、self-intersection、degenerate要素、feature検出など機能は最も豊富である。
しかしPolygon Mesh Processing packageはGPLで、非GPL配布には商用ライセンスが必要になる。
WindowsではBoostが必須で、選択するカーネルによりGMP / MPFRまたはBoost.Multiprecisionも
関わる。個人DCCツールの常設バックエンドとしては重すぎる。

難しい入力に対する開発時の比較Oracleとしては有用だが、製品バイナリには組み込まない。

## Windowsプローブ

2026-08-10に、依存をリポジトリへ追加せず一時ディレクトリで実行した。

### PMP 3.0.0

- compiler: MSVC 19.44.35227、Visual Studio 2022 Build Tools
- generator: Ninja、Release、static library、viewer / examples / tests / docsなし
- 結果: `pmp.lib` とプローブをビルド・実行できた
- 2枚のtriangleが共有するedgeへ3枚目を追加すると `TopologyException` になった
- 共有edgeのsplit後は6頂点4面になった
- 最初の2面から数えたboundary halfedgeは4だった

### Lox 0.1.1

- compiler: rustc 1.94.0、MSVC target、Release
- fresh build: 依存28 package、約6.4秒（このマシンでの診断値）
- 結果: プローブをビルド・実行できた
- 3枚目のface追加は `new face would add a non-manifold edge` でpanicした
- `catch_unwind` 後のedge splitは成功し、6頂点4面になった
- 4つの接続済みboundary頂点に孤立頂点を加えるとboundary頂点数は5になった

これらはライブラリの全面的な品質比較ではない。今回必要な入力拒否、boundary意味論、
基本mutation、Windows toolchainだけを確認した。

## 実GLB corpusの診断

`F:\3dcg\idea\glb` の29ファイルを、元ファイルへ書き込まずread-onlyで走査した。このcorpusは
製品fixtureやGoldenではなく、異常入力の分布を知るためのローカル診断資料として扱う。
アセット自体や派生meshはリポジトリへ追加しない。

全ファイルは1 mesh / 1 triangle primitiveで、sparse accessorとDraco圧縮はなかった。
合計は約2.08GB、22,309,561頂点、37,592,162 triangleだった。主要な大規模ファイルは
約150万triangleである。

| 診断 | 29件合計 |
|---|---:|
| invalid index | 0 |
| face内の重複index | 0 |
| 重複triangle | 0 |
| non-finite position | 0 |
| exact / near-zero area triangle | 0 / 0 |
| 3面以上が共有するedge | 0 |
| 2面共有edgeのwinding衝突 | 0 |
| boundary edge | 6,795,306 |
| bow-tie vertex | 50,922 |
| 余分なvertex fan | 52,551 |
| 1頂点の最大fan数 | 4 |
| edge-connected shell | 204,125 |
| 1 triangleだけのshell | 27,496 |

bow-tieが最も多かったのは `Lumi_noHair.glb` の4,519頂点、次いで
`Lumi部屋着.glb` の3,947頂点、`バニーガール女性.glb` の3,603頂点だった。
boundary edgeが最も多かったのは `少女顔アップ.glb` の421,656本だった。

このcorpusでは、edge incidenceだけを見れば全edgeが1面または2面で、windingも整合している。
それでも複数のface fanが一点のvertexだけを共有するため、surface manifoldではない。
したがって「各edgeの使用数が2以下」をPMP変換条件にしてはならず、vertexごとのface fanを
edge adjacencyで分割し、1成分であることを明示的に証明する必要がある。

PMPの `add_face()` とLoxのface追加は、この種のcomplex vertexを構築途中で拒否すると推定
される。このcorpusを両ライブラリへ直接投入する試験はまだ行っていないため、拒否位置や
部分構築後の状態については未検証として残す。

## 採用アーキテクチャ

```text
Maya mesh / Blender mesh
          |
          v
flat positions + face offsets + face indices
          |
          v
RawTopology（外部依存なし、read-only、元indexを保持）
    |                    |
    | issues             | ValidatedSurface
    v                    v
DCC要素選択・表示      PMP adapter
                         |
                         v
                 split / collapse / remesh / hole fill
                         |
                         v
              新mesh + old-to-new mapping
```

### `RawTopology` の責務

入力bufferをコピーする前に、NULL、長さ、overflow、face offset単調性、index範囲を確認する。
その後、元のvertex / face indexを正本として次を分類する。

- 3頂点未満のface、face内の重複vertex、重複face
- 非有限position、zero-length edge、zero-area face
- undirected edgeごとのface使用数
- 同じedgeを共有する2面のwinding一致・不一致
- 3面以上が共有するnon-manifold edge
- vertexごとのface fan連結成分とbow-tie vertex
- boundary edge graphのclosed loop、open chain、branch

診断は入力を変更せず、issue kind、要素種別、元index、関連index、数値証拠を返す。
boundary loopは、boundary graphの各頂点次数が2で閉じている成分だけに与える名称とする。
孤立頂点やbranchをboundary loopへ混ぜない。

### PMPへ渡す条件

次をすべて満たす入力だけを `ValidatedSurface` としてPMPへ変換する。

- 全faceが構造的に有効
- 各edgeの使用数が1または2
- 2面共有edgeの向きが反対
- 各vertexのface fanが1成分
- boundary成分がclosed loop

zero-areaなど幾何的異常は操作ごとに扱いを変える。topology traversalだけなら警告付きで
許可できるが、remesh / hole fillへは渡さない。

### sharp edgeとrail chain

sharp edge判定は角度、DCCのhard-edge属性、またはユーザー選択を `RawTopology` 上のedge tagへ
統合する。rail chainはライブラリ固有機能にせず、tagged edge graphから次数1の端点または
closed cycleを辿る自前アルゴリズムにする。これによりPMPを交換してもHair Tubeのcontractを
維持できる。

### バイナリ境界

- `ywta_mesh_core_core`: C++17 static library。`RawTopology` とPMP adapterを含む。
- `ywta_mesh_core`: Blender向けC ABI DLL。allocatorを跨がず、必ず専用free関数を持つ。
- Maya plugin: `ywta_mesh_core_core` を静的リンクする。
- C ABIからC++例外を出さず、すべてstatus codeと診断reportへ変換する。
- C ABIからRust panic、STL container、PMP handleを公開しない。

AutoRemesherとは目的と入力contractが異なるため、当初は同じDLLへ統合しない。将来まとめる
場合も、C API prefixとallocator ownershipを維持する。

## フェーズ分割

### 1. `RAW-TOPOLOGY-1`

flat topology buffer、診断issue、boundary graph、bow-tie判定を外部依存なしで実装する。

完了条件:

- hand-authored fixtureで全issueが元index付きで返る。
- invalid offset / index / overflowをbuffer参照前に拒否する。
- ローカルGLB corpus 29件で50,922 bow-tie vertexを再検出できる。
- Maya / Blenderを起動しない純C++ testが通る。

### 2. `PMP-ADAPTER-1`

PMP 3.0.0をpinし、`ValidatedSurface` との往復とold-to-new mappingを実装する。

完了条件:

- VS2022でstatic coreとC ABI DLLをRelease buildできる。
- triangle / quad / ngon、複数boundary loopの往復が一致する。
- invalid入力がPMPへ到達しないことをspyまたはtest seamで証明する。

### 3. `MESH-OPS-1`

sharp / rail chain、split / collapseを追加する。remeshとhole fillは後続の独立タスクにする。

完了条件:

- chainのopen / closed / branchを理由付きで分類する。
- 各編集がold-to-new mappingを返す。
- 操作失敗時に入力meshを変更しない。

## リスクと対策

- PMP 3.0.0が古い: pinして必要箇所だけadapterで隠し、main追従を必須にしない。
- C++17がMaya pluginへ波及する: core targetだけでcompile featureを宣言し、ホストABIはCに閉じる。
- 外部ライブラリが壊れた入力で落ちる: `RawTopology` gateを唯一の入口にする。
- 診断と修復が混ざる: read-only reportとmutation APIを別にする。
- 属性mappingが後付けできない: 最初の編集APIからold-to-new mappingを必須にする。
- flat buffer変換が重い: 全候補とも最低O(V + face-index数)なので、実アセットでcopy回数とpeak
  memoryを計測し、ライブラリ名だけで最適化判断しない。

## 前提を見直すトリガー

- PMP 3.0.0がMaya 2024 toolchainでリンクできない。
- 代表実アセットでadapter変換が総処理時間の20%以上、またはpeak memoryを2倍超にする。
- 必須操作がPMPのmanifold前提では実装不能になる。
- GPLではないCGAL package、または同等のpermissive libraryで診断層を置換できる。
- Rust共通コアを別理由で導入し、Cargo / C ABIの保守コストが既に支払われる。

## 未解決の問い

- PMPをsubmoduleとしてpinするか、必要ターゲットだけvendorするか。
- Maya 2024 pluginとPMP static libraryのruntime / exception設定をどこまで揃えるか。
- Blenderからf32を渡すか、既存AutoRemesher同様f64へ変換するか。
- 大規模実髪アセットでのcopy時間、peak memory、rail chain抽出時間。
- ローカルGLB corpusから再配布可能な最小synthetic fixtureをどう抽出・再構成するか。
- simple hole fillの品質をどのfixtureと数値で承認するか。

## 参照

- [PMP Library](https://www.pmp-library.org/)
- [PMP installation](https://www.pmp-library.org/installation.html)
- [Lox crate](https://docs.rs/lox/0.1.1/lox/)
- [Geometry Central surface mesh](https://geometry-central.net/surface/surface_mesh/basics/)
- [Geometry Central mutation](https://geometry-central.net/surface/surface_mesh/mutation/)
- [CGAL Polygon Mesh Processing](https://doc.cgal.org/latest/Polygon_mesh_processing/)
- [CGAL license](https://www.cgal.org/license.html)
