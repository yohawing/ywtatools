# Selection Sets

よく使うControlの組み合わせを保存し、まとめて選択します。

## Reference

- **Menu:** `YWTA > Animation > Selection Sets`
- **Selection:** Setへ追加するTransform、Joint、Control
- **Undo:** CreateとImportは1回。JSONの保存はMaya Undoの対象外

## Usage

1. Controlを選択します。
2. Selection Setsを開きます。
3. Labelを入力し、`Create from Selection`を実行します。
4. 一覧から`Select Members`を実行し、同じControlが選択されることを確認します。

SetはJSONへExportし、別SceneへImportできます。`Import to Selected`は、現在選択している
CharacterのControlへMemberを対応付けます。

## Notes

空のSet、重複Label、曖昧なControl名は保存またはImportされません。参照Scene内のSetは
削除できません。
