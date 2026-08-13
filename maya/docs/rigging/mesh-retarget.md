# RBF Mesh Retarget

[← Rigging](README.md)

`ywta.rig.meshretarget.retarget` は、元ボディと編集後ボディの対応頂点を
RBF control point として、衣装などの follower mesh を複製して変形します。

## Current contract

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

元の follower は変更せず、変形結果を duplicate として作成します。作成直後の Maya
Undo で duplicate を取り消せます。
