# Interface

YWTA Toolsを有効にすると、主要ツールに加えて小さな補助UIが登録されます。

## YWTA Tab

3D Viewport Sidebar（`N`）の`YWTA`タブには、Shape Key Renameとinfoパネルがあります。
infoパネルからBlenderの`Reload Scripts`とPreferencesを開けます。

`Reload Scripts`は開発中のPython moduleを再読み込みします。SceneのUndoとは別の操作で、
登録済みclassや既存UIが古いmoduleを参照することがあります。通常の制作中ではなく、
アドオン開発時に使用してください。

## Select Panel

Properties EditorのObject Propertiesには、折りたたみ式の`Select`パネルが追加されます。
全選択のtoggle、選択反転、random selectionはBlender標準operatorを呼び出します。

このパネルはScene dataを変更しませんが、現在の選択は変わります。
