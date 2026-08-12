# Fabricator 機能を参考にした Maya ツール拡充

Fabricator v1.4.2 の公開ドキュメントにあるワークフローを機能要件の参考にし、
YWTA の既存構成と安全方針に合わせて独自実装した Maya ツール群です。

Fabricator 本体は Business Source License 1.1、YWTA は MIT License です。
ライセンスを混在させないため、Fabricator の Python ソース、アイコン、画像、JSON、
固有リグ実装はコピーしていません。このリポジトリの実装とテストは YWTA 側で
新規作成したものです。

単一Undoと失敗時rollbackを契約にする変更操作は、Maya Undoが無効な場合はsceneを
編集せずに拒否します。

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
- 同一トポロジーJSONから選択頂点だけを1回Undoで部分復元
- file dialogなしで再利用できるユーザー単位のTemporary Skin Clipboard
- 保存した world-space source mesh を再構築する closest-point 転送
- Transfer OptionsでclosestPoint / rayCast / closestComponentを選択し、厳密なname / oneToOne influence対応を維持
- 複数skinned meshは頂点・face・influence indexをメモリ上でvirtual結合し、scene非編集で1 JSONへ保存
- Transfer時は保存元と適用先のlinear unit / up axis不一致を編集前拒否
- 頂点数だけでなく face connectivity の SHA-256 fingerprint を Direct load 時に検証
- influence の完全検証、曖昧な短名の拒否、保存外 influence のゼロ化
- Direct / Subset / Transferはtargetのlocked influenceを検出し、曖昧な部分適用をrollback
- Maya再起動後も使える永続Weight Clipboard、複数mesh/頂点への単一Undo Paste、複数頂点平均のCopyとその場Average
- Weight Paste / Averageはlocked influenceを検出して曖昧な再配分を編集前拒否
- 選択jointをウェイト0で追加、選択した未使用・unlocked influenceだけを安全に削除
- world YZ面で方向を明示する+X→-X / -X→+X Skin Weight Mirror
- Skin Weight Mirrorはlocked influenceを編集前拒否し、単一Undo / Redo
- 選択componentの隣接頂点平均による局所Smooth（複数mesh、locked influence対応）
- 全output meshを走査する未使用influence削除（locked influenceは既定で保護）
- bulk write 用の同梱 Python plugin による単一 Undo / Redo
- 元meshを残し、結合後の頂点順を全頂点検証するSkinned Mesh Combine
- Combineへ明示したnamespace付き出力名はMayaのcurrent namespaceに依存しない
- 元meshを残し、shellごとの元vertex/face index mappingで分割するSkinned Mesh Separate
- Separateは同位置頂点を位置照合せず、UV / normal / color set / material / weightをsubset転送
- Separateはsource input geometryとbindPreMatrixを継承し、animation中も同じskin変形を維持
- Separateの出力名はsource namespaceを継承し、Mayaのcurrent namespaceに依存しない
- Combine / Separateの明示名は、namespaceなしならroot namespaceの完全名として扱う
- Combine / Separateはjoint-global lockを変えないようlocked source influenceを編集前拒否
- skinCluster後段でtopologyが変わったmeshはinput/output fingerprint不一致として編集前拒否

Skin JSON は geometry と weight を含むため、大きいメッシュではファイルサイズも
大きくなります。Direct load は fingerprint が一致するメッシュだけに使用し、
リトポロジー後は Transfer を使用してください。

複数メッシュから保存したJSONは、選択順に連結した1つのvirtual mesh archiveです。
適用先も1つの結合済みmeshとし、Directでは同じ連結順が必要です。元の複数meshへ
個別に復元する用途では、それぞれを別JSONとして保存してください。

Skinned Mesh Combineは実行時のjoint・mesh評価姿勢を新しいskinClusterのbind stateに
します。animation rigでは、そのrigで正本とするrest / bind frameへ移動してから実行して
ください。特定frameを暗黙に強制する処理は、YWTA側に共通のframe 0規約がないため入れて
いません。

### Pose / Animation Clip / Selection Sets

メニュー: `YWTA > Animation`

- 選択 control の keyable scalar 属性を保存する Pose JSON
- playback range のanimation keys、tangent type、fixed angle/weightを保存するClip JSON
- GUIではtime sliderの複数frame highlightを優先し、未選択・standaloneではplayback rangeへfallback
- enum animationは表示ラベルで別リグのindexへ再解決（旧数値Clipも読込可能）
- 保存元と適用先のtime unit不一致を検出し、retimeせず警告
- Pose/Clipのlinear/angle unit不一致も検出し、値変換せず警告
- Maya objectSet を正本とする Selection Sets と portable JSON
- namespace を除いた control 名による別キャラクターへの適用
- `ywtaPoseId` string 属性による改名に強い明示アドレス
- blend、選択 control 限定適用、開始フレーム offset、範囲内キー置換
- PoseのBlend / Selected-onlyを保存・実行できるMaya Option UI
- file dialogなしで再利用できるユーザー単位のTemporary Pose Clipboard
- Animation ClipのPlace / Replace / Insert適用モード
- file dialogなしで再利用できるユーザー単位のTemporary Animation Clip
- 実キーがないclip開始・終了へ評価値anchorを補い、Load Optionsで個別除外可能
- ModeとSelected-onlyを任意組合せで保存・実行できるClip Option UI
- Insert時は解決・適用可能なcontrolだけの後続キーをclip占有フレーム数ぶん移動
- animCurve は現在フレームへ key を設定し、非keyable、constraint、計算node駆動属性は上書きしない
- Clipと既存animCurveのweighted tangent modeが異なる場合、範囲外キーを残すchannelは副作用を避けてskip
- 同一アドレス候補が複数ある場合は推測せず拒否

現段階は JSON の保存・適用と Selection Sets 管理が中心です。カード型ライブラリ、
thumbnail capture、カテゴリ検索、mirrored pose はまだありません。

### Versioned Skeleton IO

メニュー: `YWTA > Rigging > Export Skeleton / Import Skeleton`

- joint hierarchy を親 index で保存する versioned JSON
- translate / rotate / scale / jointOrient / rotateAxis / preferredAngle などの round-trip
- joint label、rotation limit、keyable/channel box/lock状態のround-trip
- metadata / user attribute追加後のversion 3出力と、既存version 1 / 2 JSONの後方互換読込
- 数値、bool、enum、string、double3のuser-defined静的属性とchannel状態をround-trip
- 選択jointのtop jointから保存し、file dialogなしで再利用できるユーザー単位のTemporary Skeleton Clipboard
- world姿勢を維持してrotateをjointOrientへ統合する明示importモード
- world位置・回転を維持してjoint scaleを1へbakeするClean Joint TRS import
- 実 Maya namespace への import
- current namespace に影響されない絶対 namespace 解決
- linear/angle unitとup axis不一致を既定で編集前拒否（APIで明示許可可能）
- import 前の schema / parent / sibling name / 数値検証
- 既存 root と衝突する場合は scene を変更せず拒否

従来の `ywta.rig.skeleton.dump/load` API は互換性のため残していますが、メニューは
安全な versioned 経路を使用します。

### Static Joint Hierarchy Mirror

メニュー: `YWTA > Rigging > Mirror Joint Hierarchy (Static YZ)`

- `L/R`、`Left/Right`、`lf/rt` side tokenをnamespaceを保って反転
- hierarchy全体の予定名とscene衝突を編集前に拒否
- mid-chain mirrorは反対側parentを一意に解決し、欠落時は誤parentを作らず拒否
- Maya標準mirror behaviorを使ったworld YZ面の静的mirror
- 親子構造を保持し、作成・rename・選択を単一Undo / Redoに集約
- `Joint Edit Tools`内の`Mirror Joint`も同じ階層・衝突検証経路を使用

deprecatedなlive mirror networkは採用していません。既存rigのDG接続と競合せず、
明示的に独立したjoint hierarchyを作る操作に限定しています。

### Create Joint

メニュー: `YWTA > Rigging > Create Joint`

- object / component選択全体のworld bounding-box中心へjointを1つ作成
- 空選択ではworld原点へ作成
- 最後の選択objectがjointなら、そのjointを明示parentにする
- 参照jointへのparentを編集前拒否し、作成・parent・選択を単一Undo / Redo
- `Joint Edit Tools`内の`Add Joint`も入力名を使って同じ選択中心・Undo経路を使用
- `Create at Selection Center` submenuからNull / Locator / Cube / Sphere / Cylinder / Planeを作成
- 基本objectも選択全体のworld bounding-box中心、空選択ではworld原点へ単一Undoで作成

### Insert Joints

メニュー: `YWTA > Rigging > Insert Joints Between Selected...`

- 選択順に依存せず、隣接する親子joint間へ1～99個をworld位置で均等挿入
- namespaceを親から継承し、`#`桁数による連番名を作成前検証
- 子jointのworld matrixを維持し、挿入・再parent・選択を単一Undo / Redo
- 分岐joint、参照joint、skinCluster / constraint / IK接続済みjointは編集前拒否
- `Joint Edit Tools`内の従来の挿入buttonも同じ安全な検証経路を使用

### Static Joint Orientation

メニュー: `YWTA > Rigging > Orient Selected Joints to Children`

- 選択joint階層の非leaf jointをMaya標準joint orientで直接の子方向へ静的整列
- +Xを子方向、+Yをsecondary axisとし、rotateを0のままjointOrientに保持
- 子・孫jointのworld matrixと元のselectionを保持し、階層全体を1回のUndo / Redo
- 分岐、同一位置の親子、参照、skinCluster / constraint / IK、接続・lock channelを編集前拒否
- `Joint Edit Tools`内の`Align with Child`も同じ原子的な階層orient経路を使用

### Joint Display Size

メニュー: `YWTA > Rigging > Joint Size Tools`

- 選択joint階層またはscene全jointのdisplay radiusを一括設定
- 非正・非有限サイズ、参照joint、lock / 入力接続済みradiusを編集前拒否
- 対象全体を単一Undo / Redoとし、途中失敗時は部分適用を残さない

### Duplicate Joint Hierarchy

メニュー: `YWTA > Rigging > Duplicate Joint Hierarchy...`

- 選択root以下のjoint hierarchy全体をFind / Replace後の名前で複製
- 全jointへの置換成功、namespace維持、階層内重複、scene衝突を複製前検証
- joint以外の子DAG nodeや参照階層は部分複製せず拒否
- 元階層を変更せず、複製・一時rename・最終rename・選択を単一Undo / Redo

### Constraints

メニュー: `YWTA > Rigging > Constraints`

- driversを先、drivenを最後に選ぶParent / Point / Orient / Scale / Aim constraint
- maintain offset対応のPython APIと、明示したlocal aim/up軸によるAim
- `Create Constraint...`から種別、Maintain Offset、local Aim / Upベクトルを指定
- Aim / Upのゼロ長・平行ベクトルはconstraint作成前に拒否
- 参照node、重複driver、locked・接続済みdriven channelを編集前拒否
- 選択transformへ入るconstraintだけを削除するDelete Constraints
- 作成・削除とも選択を維持し、単一Undo / 失敗rollback

### Selection Navigation

メニュー: `YWTA > Rigging > Selection Navigation`

- 選択階層の子孫jointまたは表示mesh transformを選択
- 選択meshからskinClusterへ登録されたinfluence jointを選択
- 選択jointから、そのjointがinfluenceとして登録されたmeshを選択
- 複数skinCluster・複数output geometryを重複なしで処理
- 最後に選択したtargetのworld pivotへ複数transformを位置だけ単一UndoでSnap

### Control Shape Swap

メニュー: `YWTA > Rigging > Swap Selected Control Shapes`

- 選択controlのtransform、key、constraintなどを維持してNURBS shapeだけを差し替え
- shapeのoverride color、display type、静的visibility値、visibility入力接続を新shapeへ継承
- 複数shape controlに対応
- side tokenとnamespaceから反対側controlを解決するworld YZ Shape Mirror
- Control CreatorのSmart Mirrorから同じmulti-shape mirrorを直接実行可能
- 選択control直下の全shape CVを、子controlを巻き込まず編集選択
- 最後の選択へworld形状を維持してcurveを結合（他のsource transformは削除）
- Control Combineは子transformを持つsource・参照nodeを編集前拒否し、単一Undo / 失敗rollback
- Control CreatorのRGB色変更を複数shapeへ適用し、単一Undo / 失敗rollback
- Edit CVs / Combine / Set ColorはControl Creatorウィンドウから直接実行可能
- 複数shape controlを1つのtransformとして原子的JSON保存・再作成
- 外部Control JSONの全curve schema / CV / knot / colorを作成前検証
- Control JSON Importはmulti-shapeを単一Undoで作成し、途中失敗時rollback
- Library Saveは複数controlのworld形状を1 entryへbakeし、既存名の上書きを明示確認
- Library RenameはJSON schemaを再検証して内部名も更新し、既存entryへの上書きを拒否
- Library Deleteは確認後も名前・保存先・JSON schemaを再検証し、library外のfileを削除しない
- Build at Originはviewport選択を無視して選択library shapeをworld原点へ新規作成
- Build at Selectionは選択object / component全体のworld bounds中心へlibrary shapeを新規作成
- 事前検証と単一Undo / Redo

### Scene Audit

メニュー: `YWTA > Utility > Scene Audit`

- 重複するtransform / joint short nameの一覧（shape名の重複は除外）
- non-manifold vertex / edge の一覧
- lamina face の一覧
- world-space面積が0または非有限のface一覧
- 問題 node / component の一括選択
- 選択transform / shape / componentから所属meshだけを読み取り局所監査
- UIの選択操作は古いscene reportを再利用せず、その場で再監査してから選択
- 壊れた個別 mesh の scan error を記録し、残りの scene 監査を継続

この機能は読み取り専用です。自動修復は既存 `TODO.md` にある dry-run、要素 mapping、
Undo の共通 contract が完成するまで追加しません。

### Batch Runner

メニュー: `YWTA > Batch Runner`

- scene ごとに新しい `mayapy` subprocess を起動
- headless Maya で任意 Python script を実行
- 明示 checkbox を有効にした場合だけ scene を上書き保存
- child stdout のライブ表示、scene 単位の結果、失敗後の継続
- 全scene起動前のPython script構文検証
- Cancel 後は処理中 scene を完了し、次 scene を起動しない
- scene list、script、Save 設定を versioned `QSettings` state に保存

汎用 `Export` checkbox は追加していません。FBX / USD、対象 root、出力先、命名規則が
未定義のままでは安全な動作を決められないためです。FBX は次の専用 Exporter を使用します。

### Atomic FBX Exporter

メニュー: `YWTA > Export Selected FBX / Export Animation FBX`

- 静的 mesh、skinned mesh、joint animation の selected export
- skinned mesh単独選択時はskinClusterのtop influence joint rootを自動でexport対象へ追加
- Autodesk FBX settings の push / pop と Maya selection の復元
- 同じディレクトリの一時 FBX に出力し、成功時だけ出力先を置換
- animation range の bake export
- Animation FBXはjoint chain途中の選択を拒否し、最上位jointだけをrootとして許可
- source skeleton の rename、duplicate、namespace 移動を行わない

## 意図的に未採用の範囲

- Fabricator 固有の modular rig / component binding / Armature blueprint
- ML AutoSkin と追加依存の自動インストール
- AI bridge / assistant
- Project Setup の engine template
- Joint Aimer の viewport preview と mirror workflow
- deprecated Smart Joint Mirror のlive DG network
- skinCluster接続を切断するDisconnect/Reconnect All Skins
- Scene Audit の自動修復
- thumbnail 付き Pose / Animation library UI
- Fabricator component address / `FAB_RigBinding` / `world_ctrl` roleに依存するroot motion自動除外とIK→FK比率差fallback
- UE5固定名のEngine IK reference joint自動生成
- Fabricator component / Limb / Moduleの複製（汎用joint hierarchy複製のみ採用）
- Joint Offset / Spread のlive slider（axisのlocal/world契約と分岐hierarchyの評価順が未定義）
- Paint on Select の常駐selection callback（scene-wide scriptJobとtool context状態の設計が必要）

これらは既存 YWTA の rig、HumanIK、mesh-core、依存制約との設計統合が必要で、
単純移植の対象にはしません。
