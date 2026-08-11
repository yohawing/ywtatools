# Hair Tube Curve Retopology 計画

## 目的と成功条件

本当に解くべき問題は、低ポリゴンの髪チューブを一度だけ減面することではなく、
輪郭を編集可能なカーブ表現へ戻し、必要な密度のquad meshを何度でも生成できる
非破壊の中間表現を作ることである。

最小の成功条件は次のとおり。

- ユーザーが単一のroot edge loopを指定すると、分岐のない四角形断面tubeから4本の縦railを抽出できる
- 元のedge ring対応を共有パラメータ `t` として保持し、4本のcurveを同じ断面位置で評価できる
- 長さ方向の分割数を指定し、元のroot/tip、断面の非対称性、railの巡回順を保つquad meshを再生成できる
- 元mesh、curve cage、再生成meshを残し、失敗時に元meshを変更しない
- Rust coreのfixture testに加え、Maya 2024とBlenderの実DCC smokeで同じ再生成結果を確認できる

確信度は中〜高。規則的な四角形tubeでは成立しやすいが、入力トポロジーの許容範囲と
spline fitの誤差上限は実アセットで調整が必要である。

## 非目標 (Non-goals)

- 初期版では分岐した髪、穴、自己交差、non-manifold、途中で断面頂点数が変わるmeshを自動修復しない
- 任意の有機meshを単一NURBS Surfaceへ変換しない
- 初期版では自動root/tip推定を必須にせず、root loopをユーザー指定とする
- 初期版では元meshと完全に同一のUV、skin weight、custom normalを保証しない
- Maya/Blender固有のcurve nodeをRust coreの正本にしない
- 既存AutoRemesherや汎用decimatorを置き換えない

## 前提と制約

- MVP入力は、各断面が4頂点で、隣接断面間がquad stripになっている単一tubeとする
- root loopの巡回順をrail ID 0〜3の正本とし、途中でrailの入れ替えを許さない
- 4本を別々のarc lengthで評価せず、元ring列から作る共通 `t` を使用する
- Rust coreはDCC非依存のflat bufferを受け取り、Maya/Blenderは選択取得、Undo、node生成、属性転送を担当する
- topology traversalへLoxを使うかは既存のLox採用スパイクで決める。採用しない場合もcore contractは変えない
- 外部依存は追加前に明示判断し、Maya/Blenderの安定性を優先する

## 検討した選択肢

### A. 4本の独立NURBS curveを共有 `t` で束ねる

採用案。元の4本のcorner chainを直接保持でき、平たい断面、偏った断面、テーパーを
centerlineへ潰さず再現できる。独立curveのねじれを防ぐため、rail IDと共有stationを
Curve Cage contractに含める。

### B. centerline + width / thickness / rollによるsweep

編集性と圧縮率は高いが、非対称な断面や4隅が別々にうねる髪束を近似しすぎる。
初期復元形式には採用しない。整形済みtubeを作るオプションとして後から追加できる。

### C. 任意NURBS Surfaceを直接fitする

patch seam、UV方向、制御点数、ねじれ、DCC間差の管理が重く、四角形tubeという強い
事前条件を活かせないため却下する。

### D. constrained decimationだけを行う

一度の減面には有効だが、密度変更をやり直せる編集可能な正本が残らない。将来、
Curve Cage生成前の整理や比較Oracleとして利用するが、本機能の中心にはしない。

## 採用アプローチ

中間表現をDCC非依存の `HairTubeCurveCage` とする。

```text
HairTubeCurveCage
├─ rail_count: 4
├─ source_stations[]       # 元edge ring由来の共有t
├─ rails[4][]              # 各railのsource points / fitted curve
├─ cyclic_order[4]         # root loopの巡回順
├─ root_cap / tip_cap      # 初期版は保持または未生成
├─ fit_tolerance
└─ source_mapping[]        # 再生成頂点から元rail区間への対応
```

抽出ではroot loopの各頂点から、root loopに含まれないquad対向edgeを辿る。全railが同じ
station数でtipへ到達し、各stationが1つの4頂点ringを構成することを検証する。曖昧、分岐、
再訪、rail交差、ring反転を検出したらfail-closedにする。

curve fitは最初に元polylineをOracleとして保持し、その後に端点補間付きcubic B-splineを
fitする。共有 `t` は4本の各区間長を平均したchord lengthから作り、全railを同じ `t` で
評価する。再生成時は、固定segment数または曲率・元polyline距離に基づくadaptive samplingを
選び、同じstationの4点を巡回順にquad接続する。

## フェーズ分割

### Phase 0: Contractとfixture

- 四角形tube、テーパー、曲がり、ねじれ、平たい断面、閉じたcap付きtubeの最小fixtureを作る
- `HairTubeInput`、`CurveCage`、診断コード、source mappingを定義する
- 元meshを変更しないread-only probeをRust/Pythonから実行可能にする

完了条件:

- 正常fixtureを分類し、不正入力を理由付きで拒否するcontract testが通る
- flat buffer、index、上限値、非有限値をfail-closedで拒否する

### Phase 1: Tube topology抽出

- root loopから4本の縦chainとring列を決定する
- cyclic order、同一station数、quad strip、tip到達、manifold性を検証する
- Lox採用時と自前adjacency時でcontract結果が一致するcharacterization testを用意する

完了条件:

- fixtureのrail/ring IDが決定的で、入力順を変えても同じcanonical結果になる
- 分岐、三角形、途中のpole、断面数変化、bow-tieを誤生成せず拒否する

### Phase 2: Curve Cageと固定密度再生成

- 4 railのsource polylineと共有 `t` を構築する
- polyline評価で任意segment数のquad tubeを生成する
- cubic fitを追加し、fit tolerance 0ではpolyline Oracleへ戻せるようにする
- rail IDの入れ替わり、断面反転、zero-area quadを検査する

完了条件:

- 元station数でのround-tripが許容誤差内
- 低密度・高密度の双方で全quad、同一winding、non-zero area、非交差の検査が通る
- 再生成meshと元rail polylineの最大距離をレポートできる

### Phase 3: Adaptive samplingと品質ゲート

- rail曲率、断面変化、元polylineとの距離からstationを追加・削除する
- target segments、最大形状誤差、最小/最大segment長を相互排他的な設定に整理する
- polyline Oracleとcubic結果のHausdorff近似、接線変化、quad aspect ratioを計測する

完了条件:

- 指定誤差を超えるfixtureでは自動的にstationが増える
- 固定密度より少ない頂点で同じ誤差を満たすケースを実証する
- 品質閾値を満たせない場合は結果を確定せず診断を返す

### Phase 4: Maya / Blender workbench

- root loop選択、Preview、segment/tolerance変更、curve cage表示、Generate、Cancelを提供する
- MayaはNURBS Curve、BlenderはCurve objectをadapter表示に使うが、Rust contractを正本にする
- 元meshを保持し、生成物を別objectへ出力する
- Undo/Redoと、curve編集後の再生成を実装する

完了条件:

- Maya 2024とBlenderで同一fixtureのrail数、station数、生成頂点数、index hashが一致する
- 実髪tubeでPreview、編集、再生成、Undo/Redoを再現できる
- 不正選択時にsceneを変更しない

### Phase 5: 属性転送とLOD

- source mappingを使い、UV、skin weight、vertex colorをbilinear補間する
- root/tip capの保持または再生成を選べるようにする
- 複数のtarget segmentsからLOD群を一括生成する
- 断面頂点数Nへの一般化を検討する

完了条件:

- UV seam、skin weight正規化、material assignmentを実アセットで検証する
- 同じCurve Cageから複数LODを決定的に再生成できる

## 依存関係とクリティカルパス

```text
Lox採否スパイク
  └─ Tube topology抽出
       └─ 共有t付きCurve Cage
            └─ 固定密度quad再生成
                 ├─ DCC Preview / 編集
                 ├─ Adaptive sampling
                 └─ 属性転送 / LOD
```

クリティカルパスは、curve fittingではなくroot loopから正しい4 railとring対応を決定する部分である。
ここが不安定なままNURBSやUIへ進まない。

## リスクと対策

- **railの入れ替わり・tubeのねじれ**: rootのcyclic orderを固定し、各stationのquad normalと面積を検査する
- **spline overshoot**: polyline Oracleを常に保持し、最大距離を超えた区間はknot追加またはpolylineへfallbackする
- **4本のparameterずれ**: railごとのarc lengthではなく共有station `t` を唯一の評価軸にする
- **不規則入力の誤受理**: 自動修復せず、問題のedge/vertex IDと診断コードを返す
- **DCC差**: NURBS nodeそのものではなくcoreが生成するsample positionsとindicesを比較する
- **属性破損**: geometry MVPと属性転送を分離し、source mappingが安定してから属性を有効化する
- **大規模mesh性能**: traversalをO(V+E)、fitをrail点数に比例させ、Previewは低密度で実行する

## 前提が崩れたことを検知する方法

- root loopからtipまでの4 chainが同じstation数にならない
- quadの対向edgeが一意に決まらない、または途中で訪問済み要素へ戻る
- ringの巡回順が反転する、面積が閾値以下になる、rail同士が交差する
- cubic fitとsource polylineの距離がfit toleranceを超える
- 実アセットの多数が4-sided tubeではなく、poleや断面数変化を常用している

最後の条件が頻発する場合は、4 rail MVPを拡張する前に、ユーザー指定seamによるtube展開、
N-sided generalized cage、またはcenterline + profile方式へ計画を見直す。

## 未解決の問い

- capは元faceを保持するか、再生成するか、初期版では開口のままにするか
- curve編集後の断面反転を自動補正するか、fail-closedにするか
- cubic fitのdegreeと既定toleranceをworld-space、bounding-box比、edge length比のどれで指定するか
- Maya/Blenderのcurve object編集をどこまで永続化し、Curve Cageへどうread-backするか
- UVをrail方向の共有 `t` から再生成するか、元UVをsource mappingで転送するか
- 4 rail MVPの次をN-sided tubeにするか、centerline + profile編集にするか

自己レビュー上の最も弱い前提は「実際の髪tubeが規則的な4-sided quad stripである」こと。
Phase 0で複数の実アセットをread-only probeし、この比率が低ければ実装前に入力contractを見直す。
