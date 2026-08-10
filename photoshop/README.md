# Photoshop 用ツール

Photoshop 用ツールは UXP プラグインとして実装します。`ywtatools-uxp/` に、
外部パッケージへ依存しない3DCG向けテクスチャ書き出し環境があります。

## Texture Generator

PSD直下のレイヤーグループをPBRテクスチャ用途として認識し、元PSDを変更せず
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

パネルの **不足グループを作成** で、この構成を現在のPSDへ追加できます。
書き出し時はドキュメントを一時複製し、対象グループだけを表示した状態でPNGを
保存してから複製を破棄します。元PSDの表示状態や履歴は変更しません。

現段階では各グループを個別PNGへ出力します。ORMやUnity HDRP Mask Mapなどの
RGBAチャンネルパッキングは未実装です。

## 必要なもの

- Adobe Photoshop 23.3 以降
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
PBRグループ認識、出力命名を確認します。Photoshop 上での読み込み・実ファイル
出力確認は UXP Developer Tool が必要です。

