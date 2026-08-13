# RBF Mesh Retarget

[← Rigging](README.md)

`ywta.rig.meshretarget.retarget` は、元ボディと編集後ボディの対応頂点を
RBF control point として、衣装などの follower mesh を複製して変形します。

## RBF Workbench

Maya の `YWTA > Rigging > RBF Mesh Retarget...` から最小ワークベンチを開けます。
Source Body と Modified Body は同一 topology の mesh を指定し、Followers には
変形対象を `Add Selected` で複数追加します。`Remove` と `Clear` は一覧だけを変更し、
元meshは変更しません。

`Preview` は `max_control_points=64` の低密度計算でduplicateを作成します。Previewの
duplicateは次のPreview、本適用、またはウィンドウを閉じるときに追跡して削除されます。
`Apply max control points` は 4〜4096 の整数で、本適用時だけ指定値をbackendへ渡します。
本適用前にもPreview duplicateを削除するため、backendのtransaction/Undo契約をそのまま
利用できます。backendで例外が発生した場合は日本語警告を表示し、部分的なscene変更の
rollback判断はbackend契約に委ねます。

この文書とテストはcallback、backend引数、preview cleanup、元mesh非破壊の契約を検証します。
実Maya GUIでの視認性・操作感はまだ確認していません。

## Current contract

- `retarget` は実行前に source / target / follower 全てを検証します。mesh以外、存在しない名前、曖昧な短縮名、参照node、空のfollower、重複入力、source / target のfollower混入を拒否します。
- source と target は頂点数だけでなく、各faceのvertex connectivity（順序を含む）が一致している必要があります。全inputのworld matrixも完全一致が必要です。object-space頂点を別のworld transformへ誤適用する可能性がある入力はfail-closedとなります。
- source と target は同一トポロジー、同一頂点順、同一頂点数が必要です。
- `stride` は両方へ同じ間隔で適用されます。大きくすると control point 数は減りますが、
  局所変形の精度も下がります。
- `max_control_points` を指定すると、頂点順のstrideではなく決定的な
  farthest-point samplingで空間的に分散した点を選びます。
- 6 kernel（linear、gaussian、thin plate、multi-quadratic、inverse
  multi-quadratic、Beckert-Wendland C2）を提供します。
- 3D affine 項を含むため、非退化な control point 配置では全 kernel が affine 変換を
  浮動小数点誤差内で再現します。
- source/target 数の不一致は `ValueError`、重複点や同一平面上だけの点など、拡大行列が
  特異になる配置は `numpy.linalg.LinAlgError` になります。

## Cost characteristics

control point 数を `n`、follower 頂点数を `m` とします。重み計算では
`(n + 4) x (n + 4)` の密行列を解くため、時間は O(n³)、主なメモリは O(n²) です。
各 follower は `m x n` の距離行列と basis 行列を個別に作るため、時間と一時メモリは
それぞれ O(mn) です。現行実装は follower 間で距離行列を再利用しません。

`RbfSolver` はMayaに依存せず、一度解いたweightを `transform_many` で複数 followerへ
再利用します。`progress(phase, done, total)` と `cancelled()` callbackを指定できます。
キャンセルはsampling、solveの前後、各followerの前後で確認しますが、BLAS/LAPACKが
密行列をsolveしている途中は協調中断できません。
Farthest-point sampling自体の時間は O(nk)、一時メモリは O(n) です（kは選択点数）。

float64 の source 距離行列と拡大行列だけでも下限はおよそ
`8 * n² + 8 * (n + 4)²` bytes です。たとえば n=1,000 で約15.3 MiB となり、
線形 solver の作業領域と follower 行列は別途必要です。このため高密度 mesh では
`stride` または `max_control_points` による sampling を前提とします。

## Provenance

RBF の拡大行列と kernel は PyGeM の RBF 実装を基にしています。参照した履歴を
`meshretarget.py` に固定し、MIT notice は
`maya/ywta/rig/PyGeM-LICENSE.rst` に同梱しています。

## Undo

solverのfitと全followerの変形計算はscene編集前に完了します。計算に失敗した場合はduplicateを
作成しません。編集段階は単一のUndo chunkでduplicateとsetPointsを行い、途中で失敗した場合は
そのchunkを一度Undoしてrollbackします。成功時の戻り値は作成したduplicateの名前リストです。
元のsource / target / followerは変更せず、成功後のMaya Undo一回で全duplicateを取り消せます。
