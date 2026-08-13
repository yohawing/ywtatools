# Skin Weight Files

Skin WeightをJSONへ保存し、同じMeshまたは別TopologyのMeshへ適用します。

## Reference

- **Menu:** `YWTA > Deform`
- **Selection:** SourceまたはTargetのSkinned Mesh
- **Undo:** LoadとTransferは1回。JSONの保存はMaya Undoの対象外

## Saving

`Save Skin Weights`は、選択したSkinned MeshのWeightとTopology情報をJSONへ保存します。
複数Meshを選択した場合は、選択順に連結した1つの仮想Meshとして記録されます。

`Save Temporary Skin Weights`は、同じ情報をユーザー用の一時JSONへ保存します。

## Loading the Same Topology

`Load Skin Weights (Same Topology)`は、保存時と同じ頂点数とFace接続を持つMeshへ全Weightを
復元します。

`Load Skin Weights to Selected Vertices`は、同じTopologyの選択頂点だけを復元します。

一時JSONを使用する場合は`Load Temporary Skin Weights (Direct)`を実行します。

## Transferring to Different Topology

`Transfer Skin Weights (Configured)`は、保存されたSource形状から別TopologyのTargetへWeightを
転送します。`Skin Transfer Options...`で次の方式を選択できます。

- `closestPoint`
- `rayCast`
- `closestComponent`

一時JSONを使用する場合は`Transfer Temporary Skin Weights (Configured)`を実行します。

## Notes

Scene UnitとUp Axisが保存時と異なる場合、Transferは処理を中止します。一時JSONはMayaを
再起動しても残るため、別Assetへ誤って適用しないよう注意してください。
