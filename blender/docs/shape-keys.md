# Shape Key Rename

複数のShape Key名に含まれる文字を検索し、まとめて置換します。

## Reference

- **Location:** 3D Viewport Sidebar（`N`）の `YWTA > ShapeKey名の検索と置換`
- **Selection:** `選択したオブジェクトのみ`がOnなら、対象Meshを1つ以上選択
- **Undo:** Yes

## Usage

1. 対象のMesh Objectを選択します。
2. `検索`へ変更前の文字、`置換`へ変更後の文字を入力します。
3. 必要なら大文字と小文字の区別、対象範囲を変更します。
4. `ShapeKey名を置換`を実行します。

成功すると、変更したObject数とShape Key数がステータスに表示されます。

## Notes

`Basis`は常に除外されます。`選択したオブジェクトのみ`をOffにすると、現在のSceneだけで
なく、Blender fileに読み込まれている全Objectが検索対象になります。意図しないDataまで
変更しないよう、通常はOnのまま使用してください。

大文字と小文字を区別しない場合、現在の実装はShape Key名の最初の一致だけを置換します。
