# Photoshop 用ツール

Photoshop 用ツールは UXP プラグインとして実装します。`ywtatools-uxp/` に、
外部パッケージへ依存しない3DCG向けテクスチャ書き出し環境があります。

## Texture Generator

PSD直下のレイヤーグループをPBRまたはToonテクスチャ用途として認識し、元PSDを変更せず
`<ベース名>_<用途>.png` へ一括出力します。

認識する標準グループは次のとおりです。大文字小文字と空白、`_`、`-` の違いは
無視し、`Albedo` / `Diffuse` や `Metalness` などの一般的な別名も認識します。

- `BaseColor`
- `Normal`
- `Roughness`
- `Metallic`
- `AO`
- `Emissive`
- `Opacity`
- `Height`
- `Mask`

Toonテンプレートは次の汎用キャラクター向けグループを作成・認識します。

- `BaseColor`
- `ShadeColor`
- `ShadowMask`
- `Specular`
- `RimLight`
- `MatCap`
- `Emissive`
- `OutlineMask`
- `FaceShadow`（`FaceSDF` も別名として認識）

パネルでPBRまたはToonを選び、**不足グループを作成** で選択中の構成を
現在のPSDへ追加できます。
書き出し時はドキュメントを一時複製し、対象グループだけを表示した状態でPNGを
保存してから複製を破棄します。元PSDの表示状態や履歴は変更しません。

PBR選択時は、用途別PNGに加え、次のRGBAパッキングプリセットを選択できます。
Toonの各マスクは用途やシェーダーによって割り当てが異なるため、現段階では個別PNGだけを
出力します。

- **Generic / Unreal ORM**: R=AO、G=Roughness、B=Metallic
- **Unity URP Metallic Smoothness**: R=Metallic、A=Smoothness（Roughness反転）
- **Unity HDRP Mask Map**: R=Metallic、G=AO、B=Mask、A=Smoothness

入力グループが無いチャンネルは、AO/Roughnessは白、その他は黒という中立値を
使います。透明領域も同じ中立値へ合成します。パック処理はPhotoshop Imaging APIで
各グループを512px高のタイルとして読み、出力も同じ単位で一時ドキュメントへ
書き戻して解放するため、巨大入力全体のRGBAバッファをメモリへ保持しません。
出力は現段階では原寸・8bit PNGです。

実機検証が完了するまでは、パッキング出力を本番素材の正本として扱わないでください。

## 必要なもの

- Adobe Photoshop 24.4 以降
- Adobe UXP Developer Tool

UXP Developer Tool は Creative Cloud Desktop からインストールしてください。
初回起動時は管理者権限で Developer Mode を有効にする必要があります。

## 読み込み

1. Photoshop を起動する
2. UXP Developer Tool で **Add Plugin** を選ぶ
3. `photoshop/ywtatools-uxp/manifest.json` を指定する
4. 追加された **YWTA Tools** の **Load** を実行する
5. Photoshop の「プラグイン」メニューから **YWTA Tools** パネルを開く

ファイル変更後は UXP Developer Tool の **Reload** または **Watch** を使います。
`manifest.json` を変更した場合は、一度 **Unload** してから **Load** してください。

## 検証

```bash
uvx nox -s photoshop_validate
```

この検証は manifest の基本 contract、エントリーポイント ID、参照ファイル、
PBRグループ認識、出力命名、RGBA割り当て、透明領域、Roughness反転を確認します。
Photoshop 上での読み込み・実ファイル出力確認は UXP Developer Tool が必要です。

