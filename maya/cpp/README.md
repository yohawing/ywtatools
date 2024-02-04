# 機能紹介

## Dembone

AlembicのようなMeshSequenceデータを複数のボーンを使ったSkinClusterデータに分解（Decompose）するコマンドを提供します。

## swingTwist

ノード ネットワークを作成して、Swing/Twist回転を抽出し、別のTransformのoffsetParentMatrixにコネクションします。
捻り/捩りの挙動を作りたい場合に便利です。

```
shoulder
  |- twist_joint1
  |- twist_joint2
  |- elbow

create_swing_twist(shoulder, twist_joint1, twist_weight=-1.0, swing_weight=0.0)
create_swing_twist(shoulder, twist_joint2, twist_weight=-0.5, swing_weight=0.0)
```

[CMT Swing Twist Decomposition](https://chadmv.github.io/cmt/html/rig/swingtwist.html)