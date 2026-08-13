# Rigging ツール棚卸しと整理決定

## 目的とスコープ

本書は、`maya/ywta/menu/menu_rigging.py` と現行の Rigging 実装を読み取った**コードスナップショット**である。目的は、機能・配置・重複・共通 UI/Undo 要件を固定し、`JointEditTools` 統合後のメニュー構成を一つに決めることにある。

第1段階として `Skeleton > Joint Editing` と `Skeleton > Naming` を実装済みである。JET の Add / Insert / Align / Mirror は既存の canonical backend をそのまま利用し、直接メニューと同じ prevalidation / transaction を通る。`Rename Chain` は `Name Tools` と同じ UI を開く互換 alias として `Naming` 内に残す。Skeleton I/O、Clipboard、Rig Construction、Controls の階層移行は本タスクに含めず、既存の到達性を維持する。

UI の実機表示、HumanIK の依存（PyMEL/MEL）、Swing/Twist プラグインのロード可否はこの読み取りだけでは確認していない。以下で「要確認」としたものを適合済みとは扱わない。

## 現行メニュー全項目

`menu_rigging.py` の section divider、submenu、ループ生成項目を含めて、表示される label と実装 entrypoint を列挙する。「Undo/transaction」は実装上の明示状態であり、Maya 全体の標準 Undo が常に同じ粒度になることを意味しない。

| 現行 section / label | 実装 entrypoint | 機能分類 | 選択・前提 | UI 種別 | Undo / transaction 状態 |
|---|---|---|---|---|---|
| （section なし）`Freeze to offsetParentMatrix` | `ywta.rig.common.freeze_to_parent_offset` | Transform / OPM | Transform 選択（未選択時は関数既定の `cmds.ls(sl=True)`）; Maya 2020+ | direct | 明示 chunk なし。既存接続・lock を一括復元する rollback は保証されない |
| `Skeleton` / `Joint Edit Tools` | `ywta.rig.joint_edit_tools.JointEditToolsWindow` | Joint workbench | Joint を選択してウィンドウ内操作 | window | ウィンドウ内で混在。新しい create/insert/orient/mirror は各 backend の 1 chunk、legacy 操作は chunk なし・例外を warning にするものがある |
| `Skeleton` / `Mirror Joint Hierarchy (Static YZ)` | `ywta.rig.joint_mirror.mirror_selected_hierarchy` | Joint hierarchy mirror | root joint 1つ; side token (`L/R` 等) と衝突を事前検証 | direct | `mirror_hierarchy` が 1 chunk、失敗時 `cmds.undo()` |
| `Skeleton` / `Create Joint` | `ywta.rig.create_joint.create_joint_at_selection` | Joint creation | 選択中心（空なら原点）; 最後の選択が joint なら子にする（参照親は拒否） | direct | 1 chunk、失敗 rollback |
| `Skeleton` / `Insert Joints Between Selected...` | `ywta.rig.joint_insert.show_options` → `insert_selected` | Joint topology edit | 直接の親子 joint 2つ; 未 skin/constraint/IK、非参照、count 1--99、`#` を含む名前 | options window | `insert_joints` が 1 chunk、失敗 rollback |
| `Skeleton` / `Orient Selected Joints to Children` | `ywta.rig.joint_orient.orient_selected` | Joint orient | joint 選択（既定は descendants 含む）; 子が1つ、未リグ、編集可能 channel | direct | `orient_to_children` が 1 chunk、失敗 rollback |
| `Skeleton` / `Duplicate Joint Hierarchy...` | `ywta.rig.joint_duplicate.show_options` → `duplicate_selected` | Joint hierarchy duplicate | root joint 1つ; 子 DAG が全て joint、参照なし、Find/Replace 後の名前を検証 | options window | `duplicate_hierarchy` が 1 chunk、失敗 rollback |
| `Skeleton` / `Create at Selection Center`（submenu） | `ywta.rig.create_object` | Basic object creation | 選択全体の中心、空選択は原点 | submenu | 子項目ごと 1 chunk、失敗 rollback |
| `Create at Selection Center` / `Null` | `create_object.create_null` | Transform creation | 上記共通 | direct | `create_at_selection` の 1 chunk、失敗 rollback |
| `Create at Selection Center` / `Locator` | `create_object.create_locator` | Locator creation | 上記共通 | direct | 同上 |
| `Create at Selection Center` / `Poly Cube` | `create_object.create_cube` | Primitive creation | 上記共通 | direct | 同上 |
| `Create at Selection Center` / `Poly Sphere` | `create_object.create_sphere` | Primitive creation | 上記共通 | direct | 同上 |
| `Create at Selection Center` / `Poly Cylinder` | `create_object.create_cylinder` | Primitive creation | 上記共通 | direct | 同上 |
| `Create at Selection Center` / `Poly Plane` | `create_object.create_plane` | Primitive creation | 上記共通 | direct | 同上 |
| `Skeleton` / `Constraints`（submenu） | `ywta.rig.constraint_tools` | Constraint construction | driver を先、driven を最後に transform 2つ以上 | submenu | create/delete は各 1 chunk、失敗 rollback |
| `Constraints` / `Create Constraint...` | `constraint_tools.show_options` → `create_selected` | Configurable constraint | Type、Maintain Offset、Aim/Up 軸; driven channel が settable、参照 node は不可 | options window | `create_constraint` の 1 chunk、失敗 rollback |
| `Constraints` / `Parent Constraint` | `constraint_tools.create_selected("parent")` | Constraint preset | 選択順は上記共通 | direct | 1 chunk、失敗 rollback |
| `Constraints` / `Point Constraint` | `constraint_tools.create_selected("point")` | Constraint preset | 選択順は上記共通 | direct | 同上 |
| `Constraints` / `Orient Constraint` | `constraint_tools.create_selected("orient")` | Constraint preset | 選択順は上記共通 | direct | 同上 |
| `Constraints` / `Scale Constraint` | `constraint_tools.create_selected("scale")` | Constraint preset | 選択順は上記共通 | direct | 同上 |
| `Constraints` / `Aim Constraint` | `constraint_tools.create_selected("aim")` | Constraint preset | Aim/Up は非ゼロかつ非平行、その他は共通 | direct | 同上 |
| `Constraints` / `Delete Constraints` | `constraint_tools.delete_constraints` | Constraint removal | 選択 transform を駆動する constraint; 参照 constraint は不可 | direct | 1 chunk、失敗 rollback |
| `Skeleton` / `Name Tools` | `ywta.name.show` | Naming / selection workbench | rename 対象 node を選択; collision、曖昧名、参照 node を拒否 | window | rename 操作は `rename_nodes` の 1 chunk、失敗 rollback。Select by Name は選択のみ |
| `Skeleton` / `Rename Chain` | `ywta.name.rename_chain_ui` → `name.show` | Naming compatibility alias | Name Tools と同じ | window | Name Tools と同じ。別実装ではない |
| `Skeleton` / `Joint Size Tools` | `ywta.rig.joint_size.set_joint_size_from_menu` → `show_joint_size_ui` | Joint display utility | ウィンドウで選択階層または全 joint、radius > 0; lock/入力接続/参照を拒否 | window | 設定ボタンが `set_joint_size_hierarchy` の 1 chunk、失敗 rollback |
| `Skeleton` / `Export Skeleton` | `ywta.rig.skeleton_io.save_selected` | Skeleton file export | root joint 1つ; 保存先を選ぶ | file dialog | ファイル書き出しのみ、Maya Undo 対象外（cancel は no-op） |
| `Skeleton` / `Import Skeleton` | `skeleton_io.load_dialog`（flags 既定） | Skeleton file import | file と任意 namespace; scene unit/angle/up-axis mismatch は既定拒否 | file dialog + prompt | `skeleton_io.create` の 1 chunk、失敗 rollback |
| `Skeleton` / `Import Skeleton (Bake Rotate to Joint Orient)` | `skeleton_io.load_dialog(bake_to_joint_orient=True)` | Skeleton import preset | 上記共通; rotate を jointOrient に bake | file dialog + prompt | 同上 |
| `Skeleton` / `Import Skeleton (Clean Joint TRS)` | `skeleton_io.load_dialog(bake_to_joint_orient=True, zero_joint_scales=True)` | Skeleton import preset | 上記共通; rotate を bake、scale を 1 にする | file dialog + prompt | 同上 |
| `Temporary Skeleton Clipboard` / `Save Temporary Skeleton` | `skeleton_io.save_temp_selected` | Temporary skeleton export | joint 1つ; joint parent を辿った root を固定 user JSON に保存 | direct | ファイル書き出しのみ、Maya Undo 対象外 |
| `Temporary Skeleton Clipboard` / `Load Temporary Skeleton` | `skeleton_io.load_temp_dialog` | Temporary skeleton import | 固定 JSON、namespace prompt; Cancel は no-op | prompt dialog | `skeleton_io.create` の 1 chunk、失敗 rollback |
| `Temporary Skeleton Clipboard` / `Load Temporary Skeleton (Clean Joint TRS)` | `skeleton_io.load_temp_dialog(bake_to_joint_orient=True, zero_joint_scales=True)` | Temporary skeleton import preset | 上記共通; rotate bake + scale 1 | prompt dialog | 同上 |
| `Selection Navigation` / `Select Child Joints` | `selection_tools.select_child_joints` | Selection navigation | root node を選択; 子孫 joint を親→子順に選択 | direct | Scene 編集なし（selection change のみ） |
| `Selection Navigation` / `Select Child Meshes` | `selection_tools.select_child_meshes` | Selection navigation | root node; intermediate mesh を除外 | direct | Scene 編集なし |
| `Selection Navigation` / `Select Influencing Joints` | `selection_tools.select_influencing_joints` | Skin navigation | skinCluster 付き mesh を選択 | direct | Scene 編集なし |
| `Selection Navigation` / `Select Influenced Meshes` | `selection_tools.select_influenced_meshes` | Skin navigation | influence joint を選択 | direct | Scene 編集なし |
| `Selection Navigation` / `Snap A to B (Position)` | `selection_tools.snap_to_last` | Transform placement | 2つ以上の transform; 最後が target、先行が source; lock/参照/ancestor を検証 | direct | 1 chunk、失敗 rollback |
| `Skeleton` / `Connect Twist Joint` | `ywta.rig.swingtwist.create_from_menu` | Swing/Twist DG network | driver → driven の transform 2つ; plugin または vanilla node | direct | 明示 chunk/事前 rollback なし。既存接続を含む一括復元は未保証 |
| （`Connect Twist Joint` の optionBox） | `swingtwist.display_menu_options` → `Options` | Swing/Twist options | Twist axis、Twist/Swing weight を設定・保存 | option box | 設定保存は optionVar。Apply が上記 network を作成するが明示 chunk なし |
| `Animation Rig` / `Control Creator` | `ywta.rig.control_ui.show` | Control workbench | library shape と viewport selection をウィンドウで操作 | window | shape 作成・swap/combine は各 backend の 1 chunk。library file 操作は Maya Undo 外 |
| `Animation Rig` / `Export Selected Control Curves` | `ywta.rig.control.export_curves` | Control file export | Curve transform を選択; 保存先を選ぶ | file dialog | ファイル書き出しのみ、Maya Undo 対象外 |
| `Animation Rig` / `Import Control Curves` | `ywta.rig.control.import_curves` | Control file import | JSON を選ぶ; 保存名で新規 transform/shape 作成 | file dialog | `_run_curve_creation` の 1 chunk、失敗 rollback |
| `Animation Rig` / `Swap Selected Control Shapes` | `ywta.rig.control.swap_selected_curves` | Control shape edit | control transform と JSON; shape/visibility state を検証 | file dialog | `swap_curve_shapes` の 1 chunk、失敗 rollback |
| `Animation Rig` / `Mirror Selected Control Shape` | `ywta.rig.control.mirror_selected_control_shapes` | Control shape mirror | control 1つ; 命名規則で反対側 transform が存在 | direct | `swap_curve_shapes` の 1 chunk、失敗 rollback |
| `Animation Rig` / `Edit Selected Control CVs` | `ywta.rig.control.select_control_cvs` | Component selection | NURBS curve を持つ control transform | direct | Scene 編集なし（CV 選択のみ） |
| `Animation Rig` / `Combine Selected Control Shapes` | `ywta.rig.control.combine_control_shapes` | Control shape merge | control 2つ以上; 最後が destination、参照/子 transform を拒否 | direct | 1 chunk、失敗 rollback |
| `HumanIK` / `HumanIK Auto Setup` | `ywta.rig.humanik.setup_hik_character` | HumanIK setup | root joint 1つ、Hip/Pelvis 検出、HumanIK MEL/PyMEL 依存 | direct | 明示 chunk/rollback なし。選択不足や依存不足の実機挙動は要確認 |

## 重複・責務衝突候補

| 対象 | コード根拠 | 判定 | 整理方針 |
|---|---|---|---|
| `Joint Edit Tools` と `Create Joint` / `Insert Joints...` / `Orient...` / `Mirror Joint Hierarchy` | `joint_edit_tools.py` が `create_joint`、`joint_insert`、`joint_orient`、`joint_mirror` を import し、`_create_joint` 等から呼ぶ。Mirror は `_mirror_joint` → `mirror_selected_hierarchy` | **統合候補（同一 backend）** | 次タスクで JET のボタンを backend 呼び出しへ寄せ、メニューの canonical action は `Skeleton > Joint Editing` に1つずつ残す |
| JET の `Mirror Joint` と flat `Mirror Joint Hierarchy (Static YZ)` | 上記 `_mirror_joint` が同じ `joint_mirror.mirror_selected_hierarchy` を呼ぶ | **統合候補（完全重複）** | UI を一方へ寄せる。旧 label/entrypoint は移行期間の alias として保持 |
| `Name Tools` と `Rename Chain` | `menu_rigging.py` はそれぞれ `name.show` / `name.rename_chain_ui`、後者は `return show()` | **統合済み相当／入口だけ重複** | 最終メニューでは `Naming > Name Tools` を正規入口、`Rename Chain` は `Legacy` alias として1リリース残す |
| Skeleton JSON 3 import variants と Temporary 2 variants | 全て `skeleton_io.load`/`create` の flags 違い。同一 serializer/validator | **併存（preset の差）** | `Skeleton I/O > Import` に配置し、通常/ Bake / Clean を明示 preset。Temporary は `Clipboard` に分離し、内部実装は共通化 |
| `Create Constraint...` と Parent/Point/Orient/Scale/Aim | `constraint_tools.show_options` と `create_selected(kind)` が同じ `create_constraint` を呼ぶ | **併存（options と quick preset）** | `Constraints > Create...` を主入口、5 preset は `Quick Presets` に残す。選択順と defaults を label/tooltip に固定 |
| `Control Creator` と Export/Import/Swap/Mirror/Edit/Combine | `control_ui.py` に library、mirror、CV、combine、create があり、flat 項目も `control.py` の同じ関数群を直接呼ぶ | **統合候補だが併存** | `Controls > Control Creator` を canonical workbench、`Controls > Shape I/O` と `Shape Operations` は高速入口として残す。library file 操作と scene shape 操作を混ぜない |
| Control Creator の `Smart Mirror` と `Mirror Selected Control Shape` | Creator は `mirror_selected_control_shapes`、flat も同じ function。Creator の `Mirror Curve` は source/destination 2選択の別 API | **統合候補（Smart Mirror）／併存（明示2選択）** | Smart Mirror は1つにし、2選択の旧 `Mirror Curve` は Advanced に説明付きで残す |
| `Freeze to offsetParentMatrix`、JET の `Freeze Joint Rotation`、`common.freeze_to_joint_orient` | OPM/jointOrient に姿勢を移すが、対象属性と意味が異なる。JET legacy 関数は transaction を持たない | **要調査（同一視しない）** | `Advanced / Transform Safety` に隔離し、姿勢保持・既存接続・skin影響を fixture で比較してから統合判断 |
| JET の Zero/World/Offset orient、Side、Axis、SSC、Bind Pose と flat menu | flat menu に完全一致する action はない。`joint_orient.orient_to_children` とは目的が異なる | **併存（JET 専用）** | `Joint Editing > Advanced` に残す。各操作の prevalidation、単一 Undo、エラー表示を別受入条件にする |

## 整理後メニュー構成（決定）

最終形は次の順序とする。階層を追加しても現行 label と Python entrypoint は変更せず、既存 script/テストの到達性を保つ。

1. **Rigging**
   1. **Skeleton**
      1. **Joint Editing** — `Joint Edit Tools`、`Create Joint`、`Insert Joints Between Selected...`、`Orient Selected Joints to Children`、`Duplicate Joint Hierarchy...`、`Mirror Joint Hierarchy (Static YZ)`、`Joint Size Tools`
      2. **Naming** — `Name Tools`（正規）、`Rename Chain`（Legacy alias）
      3. **Skeleton I/O** — `Export Skeleton`、`Import Skeleton`（通常/Bake/Clean の3 preset）
      4. **Temporary Skeleton Clipboard** — Save/Load（通常/Clean）
      5. **Selection Navigation** — Child Joints/Meshes、Influencing/Influenced、Snap A to B
   2. **Rig Construction**
      1. **Create at Selection Center** — Null、Locator、Poly Cube/Sphere/Cylinder/Plane
      2. **Constraints** — `Create Constraint...`、`Quick Presets`（5種）、`Delete Constraints`
      3. **Swing/Twist** — `Connect Twist Joint` と option box
   3. **Controls**
      1. `Control Creator`
      2. **Shape I/O** — Export/Import
      3. **Shape Operations** — Swap、Mirror、Edit CVs、Combine
   4. **Animation Rig**（既存 divider label は移行中も保持。最終的には Controls の旧 alias をここに残す）
   5. **HumanIK** — `HumanIK Auto Setup`
   6. **Advanced / Legacy** — `Freeze to offsetParentMatrix`、JET の legacy-only 操作、`Rename Chain` の alias、明示的な2選択 Control Mirror

`Animation Rig` は既存 menu label を壊さないため移行期間に残すが、新規説明と実装の正規階層は `Controls` とする。直接実行は selection だけで安全に決まる作成・選択・preset に限定し、名前・数・軸・namespace・file を指定するものは options/window/file dialog とする。既存 flat label は一度に削除せず、1リリースは `Legacy` alias（同じ entrypoint、同じ annotation）を置き、menu 到達性テストを更新してから alias の削除を別変更として行う。

## 全 Rigging action 共通の UI / Undo 要件

これは現状が全て適合しているという宣言ではなく、整理後に適用する契約と検証方法である。

| 要件 | 適用対象・実装指針 | 検証方法 |
|---|---|---|
| 日本語 tooltip/annotation | menu の全 actionable item（divider/submenu を除く）。目的、選択順、重要な前提、cancel/no-op を短く記載。JET 内部の英語 annotation も新規変更箇所から日本語化 | `tests/maya/unit/test_maya_menu.py::test_all_actionable_menu_items_have_japanese_annotations`、menu capture の label/annotation 表 |
| Prevalidation | selection count/type/order、direct parent-child、name/namespace collision、reference/lock/incoming connection、scene convention、plugin/file schema を**編集前**に検証 | 各 `plan`/`_validate_*` の unit test と、失敗時に scene snapshot/hash が不変であるテスト |
| 単一 Undo | scene を変更する1 actionを `undo_utils.require_enabled` + `undoInfo(openChunk/closeChunk)` で包む。window の各 Apply は独立 action | 成功後に Maya Undo 1回で全変更が戻り、2回目が無関係 actionを戻さないことを mayapy/実 Maya で確認 |
| Failure rollback | transaction 内の例外を再送出し、close 後に失敗 chunk を undo。部分作成、node/shape 数、name を検証してから success | 強制失敗 fixture（collision、locked plug、接続切断、plugin error）で scene/selection を比較 |
| Selection order | driver→driven、Snap の source→最後の target、Combine の source→最後の destination を tooltip と docs に明記。成功時は元選択を保持するか、作成結果を選択するかを action ごとに固定 | `cmds.ls(selection=True, long=True)` の順序を記録する unit test と実 Maya smoke |
| Reference / lock handling | 参照 node、locked/non-settable plug、incoming animation/constraint を編集前に拒否。例外（OPM freeze の一時 unlock 等）は専用警告と復元を必須にする | 参照・lock・入力接続 fixture、rollback 後の lock/connection 状態比較 |
| Cancel は no-op | fileDialog2、promptDialog、option box の Cancel/閉じるは scene、selection、optionVar（Apply 前）を変更しない | dialog callback の cancel テスト、実 Maya で Cancel 前後の scene/selection diff が空であること |
| Success check | 作成数、UUID/name、namespace、world pose、connection、shape display state、Skeleton JSON の readback を確認。HumanIK/Swing/Twist は依存と接続先を確認してから完了表示 | unit test の readback + Maya 2024 GUI smoke。offscreen Qt や menu label だけを実機成功の根拠にしない |

## 次タスク（JointEditTools 統合）decision matrix

| JET 操作 | canonical backend / menu | 決定 | 受入条件（短縮） |
|---|---|---|---|
| Add Joint | `create_joint.create_joint_at_selection` / `Skeleton > Joint Editing > Create Joint` | 統合 | 名前、中心/原点、最後の joint parent、reference 拒否、Undo 1回 |
| ジョイントを挿入 | `joint_insert.insert_selected` / `Insert Joints...` | 統合 | 直接親子、未リグ依存、count/name 検証、world pose 維持、Undo 1回 |
| Align Up With Child | `joint_orient.orient_selected` / `Orient Selected Joints...` | 統合 | descendants 設定、child 数、rotate/channel 検証、失敗 rollback、selection 復元 |
| Mirror Joint | `joint_mirror.mirror_selected_hierarchy` / `Mirror Joint Hierarchy (Static YZ)` | 統合 | side token、全名衝突、target parent、作成数、Undo 1回 |
| Side Assignment (Left/Center/Right) | JET 内 `_set_side` / `Joint Editing > Advanced` | 併存 | joint `side` 属性のみ変更、対象数と lock/reference 方針、Undo 1回 |
| Show/Hide Axis、Toggle SSC | `display_local_rotation_axis` / `toggle_segment_scale_compensate` | 併存 | recursive 範囲、変更可能属性、Undo 1回、部分失敗 rollback |
| Freeze Joint Rotation | JET `freeze_joint_rotation` | 要調査 | skin/bind pose と jointOrient の姿勢保持を fixture で確認。OPM Freeze と統合しない |
| Zero Orient、Orient to World、Offset Orientation | JET legacy functions | 併存（Advanced） | 子の一時 unparent/reparent、lock/reference、姿勢保持、単一 Undo、例外を握り潰さない |
| Mirror Joint Attributes | JET `mirror_joint_attributes` | 併存（Advanced） | 左右名解決、translate/jointOrient の定義、既存 target の検証、Undo 1回 |
| Reset Bind Pose | JET `reset_bind_pose` | 併存（Advanced） | skinCluster/mesh/joint の bindPose fixture、既存 pose の復元、Undo 方針を明記 |

統合完了の最低条件は、上表の canonical backend が menu と JET の両方から同じ prevalidation/transaction を通り、既存 label の到達性テストと Maya 2024 実 GUI smoke が通ることである。条件を満たさない legacy 操作は削除せず `Advanced / Legacy` に隔離する。
