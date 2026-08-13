# Influences

SkinClusterへInfluenceを追加し、未使用のInfluenceを削除します。

## Reference

- **Menu:** `YWTA > Deform`
- **Selection:** Skinned MeshとJoint
- **Undo:** 1回

## Adding Influences

`Add Selected Skin Influences`は、選択したJointを選択MeshのSkinClusterへWeight 0で追加します。
既存Weightは変更しません。

## Removing Influences

`Remove Selected Unused Influences`は、選択したJointのうち、未使用でLockされていないものだけを
削除します。

`Remove Unused Skin Influences`は、選択Meshの全Output Geometryを確認し、未使用Influenceを
まとめて削除します。Option Boxで判定ThresholdとLock済みInfluenceの保護を設定できます。
