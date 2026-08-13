# AutoRemesher キャンセル方式

## 状態

この文書は実装前の設計決定です。AutoRemesher の処理本体を別プロセスの worker で実行し、
キャンセル時はそのプロセスを終了できる構成を採用します。現時点で実装済みであることを
意味しません。

## 決定

AutoRemesher の計算はホスト DCC のプロセス内で直接実行せず、専用 worker process へ
委譲します。協調キャンセルに応答しない場合も worker だけを強制終了できるため、Maya や
Blender のプロセスを巻き込まずに処理を中断できます。

`external/autoremesher` submodule は変更しません。既存の `ywta_remesh` C ABI も互換性を
維持し、worker は既存 ABI を呼び出す新しい境界として追加します。既存 DLL の関数へ
キャンセル引数を追加したり、途中終了のために submodule を fork したりしません。

### 比較した方式

- **別プロセス worker（採用）:** 既存コアを変更せず hard cancel でき、DCC の安定性と
  障害分離を両立できます。IPC、配布物、起動コストは増えますが、キャンセルの確実性を
  優先します。
- **同一プロセスの thread:** 起動は軽量ですが、既存コアに協調キャンセル点がないため、
  安全に thread を停止できません。処理中の DLL を強制停止すると DCC 全体を破損させる
  おそれがあります。
- **submodule / ABI の改変:** 細粒度の progress とキャンセルを実装できますが、固定した
  upstream と既存 ABI の保守境界を崩します。今回の要件には採用しません。

## Worker protocol

親プロセスは task ごとの一意な一時ディレクトリを作り、入力 request file、出力 result
file、worker executable の絶対パスを明示して起動します。request/result は固定幅整数を
使う versioned binary format とし、少なくとも次を持ちます。

- magic、protocol major/minor、header size、payload size
- request: 頂点、面、AutoRemesher 設定、各配列の要素数
- result: status code、頂点、面、各配列の要素数、診断 message の byte length

major version の不一致、未知の必須 field、上限を超える要素数、size の積算 overflow は
処理前に拒否します。minor version の追加 field は header/payload size により読み飛ばせる
形にします。数値の byte order と浮動小数点形式は protocol に固定し、親と worker の双方で
file size と各 section size の一致を検証します。

進捗は worker の stdout へ一行一 event の machine-readable record として出力します。
各 event は protocol version、task id、phase、0..1 の progress を持ちます。壊れた行や
未知 event は診断として記録しますが、result の成否判定には使いません。stderr は診断専用
とし、ユーザー向け progress と混在させません。

worker は完成結果を最終 path へ直接書きません。同じ一時ディレクトリの partial file へ
全内容を書いて close し、自己検証後に atomic rename で result file を publish します。
親は process exit、exit code、result status、magic/version、file size、要素数と byte size を
すべて検証した場合だけ結果を scene へ反映します。exit code 0 でも result が欠落、不完全、
不整合なら失敗です。キャンセル、crash、timeout、検証失敗では partial/result と task 用
一時ディレクトリを best effort で削除します。削除失敗は次回起動時の期限付き清掃対象にし、
別 task のディレクトリは触りません。

## 実装スライス

### Slice A: worker foundation

- worker executable と versioned request/result codec を追加する
- 既存 `ywta_remesh` ABI を worker から呼び、submodule と公開 ABI は変更しない
- CMake と Nox に worker の build/package entry を追加する
- malformed header、version mismatch、truncated/oversized payload、非ゼロ終了、result の
  atomic publish、一時ファイル清掃を単体・integration test する

### Slice B: Blender

- operator を modal 実行にし、worker の stdout progress を UI へ反映する
- ESC では worker へ通常終了を要求し、短い bounded wait の後も残る場合は process を kill
  して終了を待つ
- cancel、crash、invalid result の場合は scene を一切変更しない。検証済み result だけを
  main thread で一度に反映し、既存の Undo 契約を維持する
- 終了済み worker の再 kill、遅れて届いた result の publish、operator 終了後の callback を
  無視する

### Slice C: Maya

- node/command は worker handle を `WaitForSingleObject` で 25--50 ms ごとに確認し、その間に
  `MComputation` の interruption を監視する
- interruption 時は worker を終了し、bounded wait 後も残る場合は kill する
- cancel 時の出力は、利用可能なら直前の正常 cache、なければ入力 mesh の passthrough とし、
  partial result は publish しない
- worker handle、一時ファイル、`MComputation` を必ず clean up し、同じ評価中に worker を
  自動再起動する loop を作らない。再評価は Maya から次の明示的な dirty evaluation が来た
  ときだけ行う

## Rollback と配布

各スライスは独立して戻せる変更にします。Slice A は DCC から未使用の worker 追加、Slice B
と C はそれぞれ feature flag または接続箇所を戻すだけで従来の同期経路へ戻せる構造にし、
protocol 変更と DCC 接続を同じ commit に混ぜません。

worker executable と必要な runtime/DLL は Maya/Blender の対応アーキテクチャごとに package
へ含め、欠落、実行不可、version 不一致を起動前 preflight で報告します。開発機の PATH や
build directory に偶然ある binary へ fallback しません。配布物について worker と DLL の
identity、依存 DLL、protocol version を検証します。

## 完了ゲート

- protocol codec と process lifecycle の自動テストが通る
- 実処理、ESC / interruption、worker crash、hang、破損 result、書き込み不可を再現し、DCC
  process と scene が保全される
- cancel 後に worker、handle、一時ファイルが残らず、次回の実行が成功する
- Blender の modal progress と ESC、Maya の progress/interruption を実 GUI で確認する
- package を clean machine 相当で展開し、同梱 worker だけで Maya/Blender の smoke test を
  通す

offscreen Qt、mayapy、単体テストだけでは GUI 完了ゲートの代替にしません。Maya と Blender
の実 GUI 証跡をそれぞれ残した後に、キャンセル対応を完了扱いにします。
