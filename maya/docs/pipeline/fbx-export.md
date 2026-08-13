# FBX Export

選択AssetまたはSkeleton AnimationをFBXへ書き出します。

## Export Selected FBX

### Reference

- **Menu:** `YWTA > Export Selected FBX`
- **Selection:** Mesh、Skinned Mesh、Asset Group、またはJoint

Skinned Meshを選択した場合は、必要な最上位Influence Jointも自動的に含めます。

## Export Animation FBX

### Reference

- **Menu:** `YWTA > Export Animation FBX`
- **Selection:** 最上位のRoot Joint 1つ
- **Range:** Time SliderのHighlight。未指定時はPlayback Range

選択したSkeletonのAnimationをBakeして書き出します。階層途中のJointはRootとして使用できません。

## File Handling

どちらも同じDirectoryの一時FBXへ書き出し、成功した場合だけ出力先を置き換えます。失敗時は
既存FBXを保護し、Mayaの選択とFBX設定も復元します。

成功したFileの上書きはMaya Undoでは戻りません。既存FBXを残す場合は別名へ書き出してください。
