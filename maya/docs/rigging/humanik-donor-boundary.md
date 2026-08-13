# HumanIK donor 移植境界

この文書は、`maya_mmd_tools` のHumanIK実装を参照するときに、ywtatoolsへ持ち込む
**概念**と持ち込まない製品固有機能を固定します。donorのファイルを丸ごとコピーする計画では
ありません。ywtatoolsのstrictなassignment契約を中心に、必要な安全性だけを小さなAPIへ
再実装します。

## 採用する概念

- assignmentの検証、merge、差分previewはMaya非依存のpure functionに保つ
- scene変更前にslot ID、target Joint、対象階層をすべて解決し、曖昧さをfail-closedにする
- assignment適用後は各slotをMELでreadbackし、期待するlong DAG pathと照合する
- 作成処理が失敗した場合は、その呼び出しが作成したCharacterだけを削除する
- current Character、current Source、input typeなど、処理中に触るHumanIK状態は事前snapshotから復元する
- 既存接続や属性を変更する後続処理では、対象を明示したsnapshotを取り、失敗時に復元する
- MEL procedureは必要なprocedureだけを確認・sourceし、利用不能ならscene変更前に停止する

## 移植しないもの

以下はMMD製品のデータモデルまたはUIライフサイクルへ強く結合するため、ywtatoolsへは
移植しません。

- MMD固有bone名、bone index、metadata、profile、finger分類
- MMD writer、constraint、Control Rig、Bake、root locomotion検証
- `SceneModelService`やMMD model rootを前提とする探索
- ownership IDやUUID payloadを保存するscene内network node
- frontend session、presenter、action state、import lock UIを含む画面全体
- donorの「MMD rigをmuteして後で復元する」一連のworkflow

必要になった場合も、ywtatoolsの汎用Joint/Character契約から独立して設計し、この境界を
暗黙に拡張しません。

## 現在のywtatools

| 責務 | 現状 |
| --- | --- |
| versioned JSONのstrict検証、旧形式正規化 | `maya/ywta/rig/humanik_assignment.py` の `validate()` / `normalize()` で実装済み |
| layer mergeと差分preview | `merge()` / `preview_merge()` で実装済み。入力非破壊、slot順、削除semanticsなし |
| 選択root階層へのrebind | `humanik.rebind_assignment_targets()` で実装済み。namespaceを除いたleaf名のcase-sensitive完全一致のみ |
| 既存current CharacterへのJSON適用 | `load_character_definition()` で実装済み。全slot/targetを事前解決するが、適用後readbackと途中失敗rollbackは未実装 |
| 新規Character builder | `create_character_definition()` で実装済み。事前解決、slot順適用、readback、所有Character cleanupを行う |
| bind/rest pose証明後のLock | 未実装 |
| current Character/Sourceのsnapshotと復元 | 未実装 |
| HumanIK MEL procedure loader | `ensure_humanik_mel_loaded()`で実装済み。入口ごとの必須procedureを確認し、不足時だけMaya標準plugin/scriptを準備する |

既存の`setup_hik_character()`はHip/Pelvisを限定的に割り当ててLockする旧来の入口です。
選択は復元しますが、汎用builderの完成形やtransactionの根拠にはしません。

## donorファイルとの対応

| donorのfile / function | 採用する考え方 | ywtatools側の責務 |
| --- | --- | --- |
| `humanik_builder.py`: `ensure_humanik_mel_loaded()` | procedure準備 | `humanik.py`の必要最小loader。HumanIK UI初期化は含めない |
| `humanik_builder.py`: `create_humanik_definition()` / `_verify_humanik_assignment_readback()` / `delete_humanik_character()` | assignment事前解決、readback、作成所有Character cleanup | 現行`create_character_definition()`を正本とし、MMD metadata候補解決やControl Rig作成は含めない |
| `humanik_retarget.py`: `connect_humanik_source()` / `snapshot_humanik_connections()` | current Source設定の前後確認、接続前の状態観測 | 将来の`humanik.py` source adapter。Bake、writer census、locomotion proofは含めない |
| `humanik_transaction.py`: `capture_humanik_restore_state()` / `apply_humanik_restore_state()` / `humanik_transaction()` | 触る状態だけをsnapshotし、失敗時に逆順で復元する思想 | process内の一時snapshot/transaction。scene永続network nodeやMMD ownership schemaは作らない |
| `humanik_frontend.py`: `setup_and_characterize()` / `enter_source_mode()` / `enter_target_mode()` / `restore_mmd_rig()` | source/target操作の順序、preview前のguard | 将来の薄いWorkbench/controller。session/presenterを丸ごと移植せず、pure APIの結果だけを表示する |

## MELとUndoの境界

HumanIKのCharacter、Definition、Source操作はMEL procedureへ依存します。`undoInfo`のchunkだけで
完全復元できるとは仮定しません。

1. 必須procedureと入力を読み取り専用でpreflightする
2. current Character、current Source、input type、Definition lock状態のうち変更対象をsnapshotする
3. 1つの明示的なUndo chunkで変更する
4. 各assignmentまたはSource変更をreadbackする
5. 失敗時は所有Characterをcleanupし、snapshotを明示復元してから元例外を報告する
6. 成功時もツール都合で変更したcurrent Character/Sourceを元へ戻す

procedure loaderは`hikCreateCharacter`、`hikGetNodeIdFromName`、`setCharacterObject`、
`hikGetSkNode`など、そのsliceが実際に呼ぶprocedureの存在確認だけを担当します。HumanIK UI全体の
初期化やDefinition window表示は必須条件にしません。cleanupまたは状態復元にも失敗した場合は、
元の失敗と復元失敗を分けて保持します。

## bind/rest proof とLock gate

assignmentが一意に解決できても、現在姿勢がcharacterizationに適切とは限りません。したがって
CharacterのLockは次をすべて満たした後だけ許可します。

- assignment対象Jointが同じroot階層に属する
- 使用するbind poseまたはrest poseの出所と対象Joint集合を説明できる
- pose適用前後のworld matrixを読み取り、期待姿勢へ到達したことを検証できる
- assignmentのslot readbackが全件一致する
- current Character/Sourceを含む復元snapshotが取得済みである

証明方法が未実装の間、汎用builderはLockしません。`setup_hik_character()`の限定Lockを、上記gateを
満たした根拠として再利用しません。

## 実装sliceとテスト

1. **current state snapshot**
   - current Character、Source、input type、lock状態をpureな値へcapture/restoreする
   - 成功・例外の両方で元状態へ戻ること、外部Characterを削除しないことをMaya testで確認する
2. **既存Character assignment transaction**
   - 全件適用後readbackを追加し、途中失敗時は変更対象slotをsnapshotから復元する
   - 1件目成功後の2件目失敗、readback不一致、cleanup失敗をfixtureで検証する
3. **bind/rest proof**
   - root階層、pose出所、対象Joint集合、world matrix readbackを表す小さな結果型を定義する
   - missing/ambiguous pose、階層外Joint、matrix不一致ではLock前に停止する
4. **Lock付きbuilder**
   - rebind、proof、create、assignment readback、Lock readbackを順に合成する
   - 成功時のCharacterと元current state、各失敗点の所有cleanup/復元、Undo/RedoをMaya 2024で確認する
5. **薄いUI**
   - assignment/merge preview、proof結果、実行可否だけを表示する
   - callback testに加え、Maya GUIでmenu位置、前提、成功表示、Undoをsmoke確認する

各sliceは関連lintとtestを通して個別コミットし、後続sliceを実装済みとして先取り記載しません。
