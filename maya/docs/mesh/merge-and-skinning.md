# Merge Objects and Skinning

Transform階層をJointへ変換し、子孫Meshを結合してBindします。

## Reference

- **Menu:** `YWTA > Mesh > Merge Objects and Skinning`
- **Selection:** 変換する階層のRoot Transform

## Usage

Root Transformを選択して実行します。階層からJointが作成され、子孫Meshは1つに結合されて
Root JointへBindされます。

## Notes

最初に選択したTransformだけを使用します。名前の衝突や途中失敗に対する一括Rollbackを
持たない従来処理です。Sceneのコピーで使用してください。
