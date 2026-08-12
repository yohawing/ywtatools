# Fabricator 機能を参考にした Maya ツール拡充

Fabricator v1.4.2 の公開ドキュメントにあるワークフローを機能要件の参考にし、
YWTA の既存構成と安全方針に合わせて独自実装した Maya ツール群です。

Fabricator 本体は Business Source License 1.1、YWTA は MIT License です。
ライセンスを混在させないため、Fabricator の Python ソース、アイコン、画像、JSON、
固有リグ実装はコピーしていません。このリポジトリの実装とテストは YWTA 側で
新規作成したものです。

## 利用できる機能

### Name Tools

メニュー: `YWTA > Rigging > Name Tools`

- `#` の桁数を使う連番 rename
- 大文字小文字を選べる検索置換
- prefix / suffix の追加と除去
- 末尾番号の振り直し
- 複数 wildcard による選択
- 親子同時 rename、namespace 保持、名前交換、競合時 rollback

### Skin IO と Vertex Weight Tools

メニュー: `YWTA > Deform`

- 同一トポロジーへの JSON 保存・復元
- 保存した world-space source mesh を再構築する closest-point 転送
- Transfer時は保存元と適用先のlinear unit / up axis不一致を編集前拒否
- 頂点数だけでなく face connectivity の SHA-256 fingerprint を Direct load 時に検証
- influence の完全検証、曖昧な短名の拒否、保存外 influence のゼロ化
- 1頂点の Weight Clipboard、複数頂点への Paste、選択頂点の Average
- 選択componentの隣接頂点平均による局所Smooth（複数mesh、locked influence対応）
- 全output meshを走査する未使用influence削除（locked influenceは既定で保護）
- bulk write 用の同梱 Python plugin による単一 Undo / Redo
- 元meshを残し、結合後の頂点順を全頂点検証するSkinned Mesh Combine

Skin JSON は geometry と weight を含むため、大きいメッシュではファイルサイズも
大きくなります。Direct load は fingerprint が一致するメッシュだけに使用し、
リトポロジー後は Transfer を使用してください。

### Pose / Animation Clip / Selection Sets

メニュー: `YWTA > Animation`

- 選択 control の keyable scalar 属性を保存する Pose JSON
- playback range のanimation keys、tangent type、fixed angle/weightを保存するClip JSON
- enum animationは表示ラベルで別リグのindexへ再解決（旧数値Clipも読込可能）
- 保存元と適用先のtime unit不一致を検出し、retimeせず警告
- Pose/Clipのlinear/angle unit不一致も検出し、値変換せず警告
- Maya objectSet を正本とする Selection Sets と portable JSON
- namespace を除いた control 名による別キャラクターへの適用
- `ywtaPoseId` string 属性による改名に強い明示アドレス
- blend、選択 control 限定適用、開始フレーム offset、範囲内キー置換
- PoseのBlend / Selected-onlyを保存・実行できるMaya Option UI
- Animation ClipのPlace / Replace / Insert適用モード
- Insert時は解決・適用可能なcontrolだけの後続キーをclip占有フレーム数ぶん移動
- animCurve は現在フレームへ key を設定し、constraint や計算node駆動属性は上書きしない
- 同一アドレス候補が複数ある場合は推測せず拒否

現段階は JSON の保存・適用と Selection Sets 管理が中心です。カード型ライブラリ、
thumbnail capture、カテゴリ検索、mirrored pose はまだありません。

### Versioned Skeleton IO

メニュー: `YWTA > Rigging > Export Skeleton / Import Skeleton`

- joint hierarchy を親 index で保存する versioned JSON
- translate / rotate / scale / jointOrient / rotateAxis / preferredAngle などの round-trip
- world姿勢を維持してrotateをjointOrientへ統合する明示importモード
- 実 Maya namespace への import
- current namespace に影響されない絶対 namespace 解決
- linear/angle unitとup axis不一致を既定で編集前拒否（APIで明示許可可能）
- import 前の schema / parent / sibling name / 数値検証
- 既存 root と衝突する場合は scene を変更せず拒否

従来の `ywta.rig.skeleton.dump/load` API は互換性のため残していますが、メニューは
安全な versioned 経路を使用します。

### Control Shape Swap

メニュー: `YWTA > Rigging > Swap Selected Control Shapes`

- 選択controlのtransform、key、constraintなどを維持してNURBS shapeだけを差し替え
- shapeのoverride color、display type、visibility入力接続を新shapeへ継承
- 複数shape controlに対応
- 事前検証と単一Undo / Redo

### Scene Audit

メニュー: `YWTA > Utility > Scene Audit`

- 重複する DAG short name の一覧
- non-manifold vertex / edge の一覧
- lamina face の一覧
- 問題 node / component の一括選択
- 壊れた個別 mesh の scan error を記録し、残りの scene 監査を継続

この機能は読み取り専用です。自動修復は既存 `TODO.md` にある dry-run、要素 mapping、
Undo の共通 contract が完成するまで追加しません。

### Batch Runner

メニュー: `YWTA > Batch Runner`

- scene ごとに新しい `mayapy` subprocess を起動
- headless Maya で任意 Python script を実行
- 明示 checkbox を有効にした場合だけ scene を上書き保存
- child stdout のライブ表示、scene 単位の結果、失敗後の継続
- Cancel 後は処理中 scene を完了し、次 scene を起動しない
- scene list、script、Save 設定を versioned `QSettings` state に保存

汎用 `Export` checkbox は追加していません。FBX / USD、対象 root、出力先、命名規則が
未定義のままでは安全な動作を決められないためです。FBX は次の専用 Exporter を使用します。

### Atomic FBX Exporter

メニュー: `YWTA > Export Selected FBX / Export Animation FBX`

- 静的 mesh、skinned mesh、joint animation の selected export
- Autodesk FBX settings の push / pop と Maya selection の復元
- 同じディレクトリの一時 FBX に出力し、成功時だけ出力先を置換
- animation range の bake export
- source skeleton の rename、duplicate、namespace 移動を行わない

## 意図的に未採用の範囲

- Fabricator 固有の modular rig / component binding / Armature blueprint
- ML AutoSkin と追加依存の自動インストール
- AI bridge / assistant
- Project Setup の engine template
- Joint Aimer の viewport preview と mirror workflow
- skinned mesh の separate
- Scene Audit の自動修復
- thumbnail 付き Pose / Animation library UI

これらは既存 YWTA の rig、HumanIK、mesh-core、依存制約との設計統合が必要で、
単純移植の対象にはしません。
