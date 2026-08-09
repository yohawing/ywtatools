# Photoshop 用ツール

Photoshop 用ツールは UXP プラグインとして実装します。現在は
`ywtatools-uxp/` に、外部パッケージへ依存しない最小の開発環境があります。

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

この検証は manifest の基本 contract、エントリーポイント ID、参照ファイルの
存在を確認します。Photoshop 上での読み込み確認は UXP Developer Tool が必要です。

