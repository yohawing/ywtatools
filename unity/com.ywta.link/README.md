# YWTA Link for Unity

Unity Editor の `PlayableDirector` を YWTA Link の Common Playback Session へ接続します。

`Tools > YWTA > Timeline Sync` を有効にすると、選択中の GameObject にある
`PlayableDirector` を使用します。選択がない場合は、読み込み済みSceneに対象が1つだけ
存在するときに限り自動選択します。対象が0件または複数件なら接続しません。

現在の対応範囲は再生・停止、再生位置、既存duration、`Once` / `Loop`です。異なるduration、
逆再生、1倍以外の再生速度、`Ping-pong`は安全のため適用しません。Broker接続先は
`YWTA_LINK_ENDPOINT`、または`%LOCALAPPDATA%\YWTA\Link\runtime\v1\broker.json`から取得します。
接続先がなければ`YWTA_LINK_EXE`、次にユーザーInstallの`current.json`を探索し、Brokerを自動起動します。

## Camera Sync

`Tools > YWTA > Camera Sync` は、選択中のCameraをCommon Camera v1へ接続します。未選択時の
fallbackは、読み込み済みSceneに有効なCameraが1つだけある場合に限ります。

| Unity Camera field | 対応 | 備考 |
| --- | --- | --- |
| world position / rotation | exact | Unity LHとCommon RHをZ反転し、Common Transformはmm |
| scale | exact | `(1, 1, 1)`のみ。親付きまたは非identity scaleは変更前に拒否 |
| Physical focal length / sensor / lens shift | exact | PerspectiveはPhysical Cameraのみ |
| near / far clip、orthographic vertical full height | exact | Unity mとCommon mmを相互変換 |
| output aspect | exact | 既存aspectが一致するときだけ適用し、Render設定は変更しない |
| Physical focus distance / aperture | exact | non-null値はCamera propertyへ完全適用。nullは未提供として既存値を維持 |
| Depth of Field描画 | 対象外 | Volume/Post Processing構成は同期しない |
| exposure、film fit、非Physical FOV Camera | unsupported | Cameraを変更する前にfail closed |

現在のSession APIは上表の`exact` / `unsupported`結果をPeerへ通知しません。対応外の値はCameraを
変更せず接続を失敗状態にし、Consoleへ理由を出します。
