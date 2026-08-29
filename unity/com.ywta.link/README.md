# YWTA Link for Unity

Unity Editor の `PlayableDirector` を YWTA Link の Common Playback Session へ接続します。

`Tools > YWTA > Timeline Sync` を有効にすると、選択中の GameObject にある
`PlayableDirector` を使用します。選択がない場合は、読み込み済みSceneに対象が1つだけ
存在するときに限り自動選択します。対象が0件または複数件なら接続しません。

現在の対応範囲は再生・停止、再生位置、既存duration、`Once` / `Loop`です。異なるduration、
逆再生、`Ping-pong`は安全のため適用しません。Broker接続先は `YWTA_LINK_ENDPOINT`、または
`%LOCALAPPDATA%\YWTA\Link\runtime\v1\broker.json` から取得します。
