# YWTA Link v1 仕様

## 文書情報

- 状態: Draft
- 対象: YWTA Link protocol version 1
- 対応環境: Windows 11上で動作するMaya、Blender、Unity、Photoshop、Substance Painter
- 本文書の役割: Broker、Client、DCC Adapter間の責務と互換性契約の正本

本文書では要件の強さを次の語で表す。

- **必須**: v1適合実装が満たさなければならない要件
- **推奨**: 特別な理由がなければ満たす要件
- **任意**: 対応してもしなくてもよい拡張

## 1. 目的

YWTA Linkは、同じコンピューター上で起動している複数のDCCおよび制作アプリを、
ユーザーによるサーバー操作や手動ペアリングなしで接続するローカル連携基盤である。

主なユースケースは次のとおり。

- BlenderとPhotoshop間でTexture Setの要求、書き出し完了、再読み込みを連携する
- Unity、Blender、Maya、Substance Painter間でMaterialの意味情報とTexture更新を連携する
- Blender、Maya、Unity間でCameraのTransformと撮影パラメーターを同期する
- DCC間でBlendshapeまたはShape Keyの現在Weightを同期する
- 作業ごとに同期対象、Authority、適用先を定義し、作業終了時に同期Sessionだけを解体する
- 起動中アプリ、参加Room、提供Capability、直近イベントをCLIで確認する
- 将来のDCC Pluginが既存アプリを直接参照せず、共通Protocolだけで連携へ参加する

成功条件は次のとおり。

1. 最初のClient起動時にBrokerが自動起動し、最後のClient終了後に自動終了する。
2. 各Clientは他Clientの接続先や実装言語を知らずにRoomへ参加できる。
3. Room全体、Topic購読者、特定Peerのいずれにもメッセージを送信できる。
4. 小さい制御情報と大きいBinary payloadを同じ論理Messageとして扱える。
5. Maya、Blender、Substance Painter向けPython Clientを共通化できる。
6. Unity向けC# ClientとPhotoshop向けJavaScript Clientを薄く保てる。
7. ClientまたはBrokerの異常終了後に、他DCCのSceneやDocumentを破壊せず復旧できる。
8. 安定した共通Schemaを作業単位で組み合わせ、DCC固有表現へ明示的に投影できる。

## 2. 非目標

次の機能はv1に含めない。

- LANまたはインターネット越しの通信
- ユーザーアカウント、クラウド同期、外部公開Server
- 人間向けのGUI Chat
- MessageやMaterial状態の永続Database
- 任意のPython、JavaScript、C#コードの遠隔実行
- 実行時に任意Fieldや式を追加できる汎用Schema言語
- 同じ同期Channelを複数Peerが同時編集するmulti-writer merge
- Skeleton構造が異なるDCC間の自動Retarget
- DCC固有Shader Graphの完全な双方向変換
- PhotoshopのLayer Treeと他DCCのNode Graphの完全同期
- 毎FrameのViewport、Simulation、Vertex Streamを前提とした低遅延Streaming
- Shared Memoryを使った転送
- 一般DCC Pluginのインストール、更新、署名、P2P配布

Shared Memoryは将来の任意Capabilityとして予約するが、v1の実装要件にはしない。
YWTA Link Broker自身のユーザー単位bootstrap、更新、探索はv1の対象とする。

## 3. 設計原則

### 3.1 BrokerはRoom型Event Busである

BrokerはDCC用のローカルRoomを提供する。人間向けChatとの類似点は、参加者、Room、
Message、宛先、履歴表示があることに限る。Message本文は自由文ではなく、versioned schemaを
持つEventまたはCommandである。

### 3.2 Brokerは意味データの正本にならない

Brokerが保持するのは接続中Peer、Room、Subscription、未完了Request、ActiveなSync Sessionのmetadata、
短い診断用Event列だけである。Material、Texture、Camera、Motion、Scene、Layer Treeなどの意味状態は
永続保持しない。

本文を解釈しない原則の限定例外として、Broker自身を宛先とするephemeral session slotのjoin Requestだけは
Brokerがversioned schemaを検証し、Room内で共有するSession descriptorを生成する。この例外はSession bootstrapの
atomic claim/joinに限り、DCCの意味データや同期payloadをBrokerの正本にするものではない。

Materialの意味情報はversioned Material Spec、TextureやMeshは各用途の標準形式または
versioned binary schemaを正本とする。Broker再起動後はClientが接続、Room、Capability、
必要な最新状態を再広告する。

### 3.3 Clientは外向き接続だけを持つ

Clientは他Peerを探索したり、他PeerからのTCP接続を待ち受けたりしない。ClientはBrokerへ接続し、
BrokerがMessageを転送する。これにより、DCCごとの実装を接続、再接続、送受信、Main Thread dispatchに
限定する。

### 3.4 BinaryをJSONへ展開しない

画像、Mesh、AnimationなどのBinary payloadをJSON配列またはBase64へ変換してはならない。
JSONは小さいHeaderと意味情報だけに使い、Binary本体はinline binary bodyとして送信する。

### 3.5 受信データは不変Snapshotとして扱う

受信側は受け取ったPayloadを直接共同編集しない。変更結果は新しいrevisionとmessage_idを持つ
別MessageとしてPublishする。将来Shared Memoryを追加する場合も、Publish後の領域は不変、
Consumerはread-onlyを原則とする。

### 3.6 安定Schemaを作業単位で構成する

Camera、Transform、Time、Morph Weight、Motionなど、DCC間で共有できる意味は`YWTA Common`の
versioned schemaとして定義する。作業中の同期関係は、登録済みSchema、Capability、Field subset、
Authority、適用先を`Sync Contract`で組み合わせる。

Sync Contractは新しい実行コードや任意Schemaを持ち込まない。DCC固有名、Scene object、Unit、座標系への
Bindingと変換は各DCC Adapterが所有する。

## 4. Architecture

```text
Maya / Blender / Unity / Photoshop / Substance Painter
                        │
                  DCC Adapter
                        │
          ┌─────────────┴─────────────┐
          │                           │
     YWTA Common              Ephemeral Sync Contract
  安定した意味Schema          作業中のBindingとAuthority
          └─────────────┬─────────────┘
                        │
              YWTA Link Client SDK
                        │
               ywta-link Broker ── CLI Monitor
                        │
        Room / Topic / Target / Request-Response
```

YWTA Linkは転送とRouting、YWTA CommonはDCC非依存の意味、Sync Contractは作業中の接続関係、
DCC AdapterはHost固有のBindingと適用を担当する。4層を分離し、Camera同期を追加してもBrokerや
他DCC Adapterの内部実装を変更しない構造とする。

### 4.1 Broker

Broker本体はRust製の単独実行File `ywta-link.exe` とする。Rustを選ぶ理由は処理性能ではなく、
DCC内蔵Runtimeから独立した配布、Process lifecycle、障害分離である。

Brokerは少なくとも次を提供する。

- Client接続受付
- Protocol version negotiation
- Peer登録とCapability広告
- Room参加と退出
- Topic subscription
- Room、Topic、TargetへのRouting
- RequestとResponseのcorrelation
- Heartbeatと切断検出
- Binary chunkの順序、長さ、上限、backpressure管理
- ActiveなSync Sessionの参加者、状態、Authorityの一時的な仲介
- 診断用の上限付きEvent ring buffer
- Clientが0件になった後のidle shutdown

BrokerはDCC APIを読み込まず、MessageのDCC固有Payloadを解釈しない。Sync Contractについても
登録、状態遷移、Routingに必要なmetadataだけを扱い、CameraやMotionの意味データを変換しない。

### 4.2 CLI Monitor

MonitorはGUIを持たず、Brokerと同じ `ywta-link.exe` のsubcommandとして提供する。

v1の最小実装では、次の3つのsnapshot commandを提供する。

```powershell
ywta-link status [--json] [--runtime-file <absolute-path>]
ywta-link peers  [--json] [--runtime-file <absolute-path>]
ywta-link rooms  [--json] [--runtime-file <absolute-path>]
```

`--runtime-file`を省略した場合は、`%LOCALAPPDATA%\YWTA\Link\runtime\v1\broker.json`を読む。
Monitorはruntime manifestのloopback endpointへ外向きTCP接続し、manifest tokenを含む一回限りの
hello challengeを検証した後、versionedな`monitor.snapshot.request`を送る。Brokerは
`monitor.snapshot.response`で、Broker endpoint、PID、protocol version、接続中Peer ID、Roomのmember、
Topic Subscription、Presenceを広告したPeerの実装情報を返す。既存の`peers`はPresenceの有無にかかわらず
接続中Peer ID全件を含み、追加の`presence`配列は広告済みPeerだけをPeer ID順で含む。Monitor自身のPeer IDは
snapshotから除外する。Binary bodyやMessage履歴は返さない。

Presenceの返却は後方互換のためrequest opt-inとする。Presenceを取得するMonitorはrequestの`extra`へ
`{"ywta_include_presence": true}`を指定し、新Brokerはその場合だけresponse bodyへ`presence`を含める。
旧Monitorのようにこのextraを指定しないrequestでは、新Brokerも`presence` Field自体を省略するため、旧Broker
snapshot形式を厳密にdecodeするMonitorとの相互運用を保つ。このFieldはboolean以外を受理しない。

既定の人間向け出力はstatusのBroker概要、peersのPeer一覧、roomsのRoom/member/Topic一覧とする。`status`には
接続Peer数とPresence広告済みPeer数を表示する。`peers`はPresence付きPeerについてapplication、
application version、plugin version、capabilitiesをPeer単位で表示し、legacy PeerはPeer IDだけを表示する。
`--json`では機械可読なJSONを返し、`peers`の`peers`配列は既存のPeer ID一覧として維持したまま、
Presence詳細を追加の`presence`配列で返す。すべての一覧は辞書順で安定させる。旧Brokerのsnapshotで
`presence`が省略された場合は空配列として扱う。snapshotの将来Fieldは無視できるが、既知Fieldの型、並び、
重複、subset制約はfail closedで検証する。引数値の欠落、
相対runtime path、malformed/stale manifest、token不一致、非loopback endpoint、Broker不在はfail closedとする。

`monitor.snapshot.request`と`monitor.snapshot.response`は`ywta.monitor.snapshot.v1` schemaを必須とする
v1の小さなprotocol拡張であり、通常のRoom/Topic/Target routingへ流さない。Monitor requestは予約した
`ywta-link:monitor:` Peer IDだけが、非空challenge付きHelloと有効なruntime tokenによる専用接続で送信できる。
Monitor接続はsnapshot request以外のrouting操作を行えず、通常Peerはsnapshot requestを送信できない。
Brokerはruntime manifestを有効にした場合だけresponseを返す。

想定Commandは次のとおり。

```powershell
ywta-link serve --background --idle-timeout 30
ywta-link status
ywta-link rooms
ywta-link peers
ywta-link tail --room character-a
ywta-link session start contract.json
ywta-link session list --room character-a
ywta-link session inspect 01J...
ywta-link session close 01J... --policy keep-committed
```

正確なCommand名とOptionはCLI実装時に確定する。CLI出力は人間が読める形式を既定とし、
Automation用JSON出力を任意Optionとして提供する。

### 4.3 Client SDK

Client SDKは言語ごとに薄く実装する。

- Python: Maya、Blender、Substance Painterで共用する純Python package
- C#: Unity Editor向け
- JavaScript: Photoshop UXP向け

Client SDKは次の責務だけを持つ。

- Brokerの生存確認と自動起動
- Brokerへの接続と再接続
- Protocol encode/decode
- Room参加、Subscription、Capability広告
- Publish、Request、Response、Error送信
- Binary bodyのchunk送受信
- Network ThreadからDCC Main Threadへの安全なdispatch

#### 4.3.1 Peer PresenceとCapability広告

Clientは、他のPeerが接続先や実装言語を知らなくても利用可能な機能を判定できるよう、任意で
Presence/Capability広告を最初の`hello`へ含める。広告を含める場合、Envelopeの`schema`は
`ywta.peer.hello.v1`、`body`は次の厳密なJSON objectとする。

```json
{
  "peer_id": "blender:peer-001",
  "application": "Blender",
  "application_version": "4.5.0",
  "plugin_version": "0.1.0",
  "protocol_versions": [1],
  "capabilities": ["camera.apply.v1", "camera.read.v1"]
}
```

`peer_id`はEnvelopeの`sender`と完全一致し、全Stringは空でない256文字以内のUTF-8文字列とする。
`protocol_versions`は1以上65535以下の整数の昇順unique配列で、1を含む16件以内とする。
`capabilities`は0件以上128件以内の配列とし、含まれる各IDは空でないversioned identifierの昇順unique値、
256文字以内のUTF-8文字列とする。
未知Field、型違い、上限超過、未versioned ID、不正な並び、`protocol_versions`に1がない広告は
接続登録前にfail closedで拒否する。広告状態はBrokerが接続中だけ保持し、切断時に破棄する。

広告を指定しないClientは、schemaとbodyを省略したlegacy bare `hello`を送信できる。Brokerはこの
legacy形式とPresence付き形式の両方を受理する。Presence schemaを指定したbodyの省略や、bodyのdecode失敗は
受理しない。Presence以外のschema/bodyはlegacy metadataとして解釈せず、既存実装との互換性のためBrokerでは
保持も拒否も行わない。runtime manifest用のchallenge extraはPresence schema/bodyと同じ`hello`に共存できる。
ただしMonitor予約PeerはPresenceを広告できず、Presence schema/body付きHelloを接続登録前に拒否する。
再接続、`close()`後の再接続、Broker runtime replacementでも、同じClientに設定した広告をhelloへ一度だけ
再掲する。Capabilityの意味解釈やnegotiation、routing拒否は各Adapterの次スライスで定義する。

#### 4.3.2 Common Playback Host contract

各DCC Adapterは、Host APIの再生callbackをDCC非依存な`PlaybackHostSnapshot`と
`PlaybackHostEvent`へ投影する。`PlaybackHostRange`はHost時刻値による半開区間、snapshotは
`playing`/`paused`、position、range、正のspeed、forward/reverse、once/loop/ping-pong、time unit、
logical change IDを持つimmutable型である。変更種別は再生開始・停止、paused seek、range/speed/mode変更に
限定し、再生中の毎Frame値をHost eventとして配信しない。`approximated_fields`はHost表現を近似したFieldを
明示するためのbounded metadataであり、後続Controllerが`ywta.common.playback.v1`へ変換してwireへ送る。
Host callbackはnetwork送信を行わず、Controller callbackとの境界に留まる。適用中の同期callback抑止や
遅延callbackのecho判定は各HostとControllerの責務として明示する。

Host時刻からCommon Playbackへ変換するAdapterは、Host 1単位あたりの正の整数
`ticks_per_host_unit`とHost unit rateを設定した`PlaybackTimeMapper`を使用する。wire timebaseは
`host_unit_rate * ticks_per_host_unit`を既約化したRationalRateとし、RationalRateの上限を超える設定は
fail closedとする。Hostのposition/range値は`Fraction(str(value)) * ticks_per_host_unit`が厳密な整数になる
場合だけwire tickへ変換し、丸めや黙ったcoerceを行わない。逆変換はwire timebaseの完全一致を要求し、
tickをscaleで割ってHost値へ戻す。Host floatで厳密に再表現できないtickは拒否する。forward変換では
Host snapshotの`time_unit`が設定値と一致しなければならない。Mapperは`sample_rate`を表現しないため、
逆変換では`sample_rate=null`だけを受理する。state、speed、direction、loop_mode、change_idも保持し、
逆変換の`time_unit`は設定値を使用する。

Hostの`approximated_fields`はwire payloadへそのまま表現できないため、Mapperは
`required_exact_fields`に含まれる近似Fieldがある場合に拒否し、それ以外は変換を許可する。既定値は
`state`、`position`、`playback_range`、`direction`とし、再生ボタンと位置同期を優先してHostが近似し得る
`speed`/`loop_mode`は明示的な許可なしでも変換できる。これらの近似metadataはwireで失われるため、
逆変換時の`approximated_fields`は空tupleとする。

#### 4.3.3 Maya Playback Adapter

Maya Adapterは`MConditionMessage`の`playingBack`と、`MEventMessage`の`timeChanged`、
`playbackRangeChanged`、`playbackSpeedChanged`、`playbackModeChanged`を購読する。再生中の
`timeChanged`は毎Frame publishせず、再生開始・停止、paused中のseek、range/speed/mode変更だけを
immutableなHost snapshotとしてController callbackへ渡す。Bridge callbackから直接network送信してはならない。

Remote Playback snapshotの適用はMaya Main Threadに限定し、`MAnimControl`へrange、time、speed、mode、
play/stopを適用する。Mayaの`maxTime`はinclusive、wireの`end_exclusive`は半開終端なので、変換は
`maya_max + frame_step = wire_end_exclusive`、逆変換は`wire_end_exclusive - frame_step = maya_max`とする。
再生方向は`MAnimControl.playbackBy()`の符号を正本にせず、既定では`maya.cmds.play(query=True, forward=True)`を
使う。queryがboolを返した場合だけ内部の直前方向を更新し、`None`またはquery例外では直前方向を維持する。
Adapterはdirection queryを依存注入できるため、Maya外のunit testでも逆再生を検証できる。
適用中に発生したMaya callbackはlocal changeとして再通知しない。Callback例外はMaya event loopへ漏らさず、
Bridgeの軽量error statusへ隔離する。

Mayaの`playbackSpeed`が0（every-frame再生）またはwireで表現できない値の場合、Adapterは`speed=1.0`
へ近似してもよいが、immutable snapshotの`approximated_fields`へ`speed`を必ず記録する。正の有限値では
このFieldは空とし、Controllerは近似結果を`approximated`として報告できるようにする。Bridgeがapply中に
抑止できるのは同期的に発生したcallbackだけであり、遅延して到着するMaya callbackのecho判定はControllerが
Envelopeの`origin_peer_id`と`change_id`をEchoGuardへ関連付けて行う。Bridge単体で遅延echoまで抑止したとみなしてはならない。

#### 4.3.4 Blender Playback Adapter

Blender Adapterは`bpy.app.handlers.animation_playback_pre`、
`bpy.app.handlers.animation_playback_post`、`bpy.app.handlers.frame_change_post`を購読する。
再生開始は`animation_playback_pre`で保留し、最初のframe deltaが正なら`forward`、負なら`reverse`として
確定した時点で`play_started`を通知する。正しい方向queryを依存注入できる場合だけ、delta確定前の通知を許可する。
再生中の`frame_change_post`は毎Frame eventを生成せず、`animation_playback_post`で最終位置を含む
`play_stopped`を一度だけ通知する。停止中のframe変更だけを`paused_seek`として通知する。

range、speed、loop意図は専用Blender handlerの有無に依存せず、Host Main Threadのtimer/tickでsnapshot差分を
検出する。`frame_start`と`frame_end`はBlender側でinclusive、wire側で半開とし、変換は
`blender_end + frame_step = wire_end_exclusive`、逆変換は`wire_end_exclusive - frame_step = blender_end`とする。
Blender標準sceneに再生倍率またはloop意図の共通setterがない場合、Adapterはspeed/loopのproviderを注入でき、
未対応Fieldは`approximated_fields`またはapply statusで報告する。`fps`/`fps_base`はscene timebaseであり、
再生倍率として変更してはならない。sync modeやframe_stepを暗黙に別のwire Fieldへ再解釈してはならない。
apply providerを注入する場合は、適用後の状態を同じ意味で読み戻せるquery providerも必須とする。

`use_preview_range`が有効な場合は`frame_preview_start/end`をeffective rangeとして使用し、通常rangeと混同しない。
RNAのrange境界はintegerだけをexactに受理し、fractional boundaryは黙ってcoerceせずfail closedとする。
positionの適用は`scene.frame_set(frame, subframe)`を使用する。`frame_change_post`はrender中またはMain Thread以外
からも発火し得るため、`bpy.app.is_job_running("RENDER")`がtrueまたは状態不明の場合はpaused seekへ昇格しない。

Remote snapshotの適用、scene property更新、play/stop operator呼出しはAdapter生成元のBlender Main Threadに
限定する。`screen.is_animation_playing`と`bpy.ops.screen.animation_play`、
`bpy.ops.screen.animation_cancel`はcontext依存のため、Adapterは注入可能なcontrol portを使用し、適用不能時は
fail closedにする。適用中に発生した同期callbackは通知せず、遅延callbackのecho判定はControllerの
`PlaybackEchoGuard`へ委ねる。handler/timer wrapperはstable identityを保持し、利用可能なら
`bpy.app.handlers.persistent`を適用する。timerは`persistent=True`で登録する。handler/timer登録はidempotentで
重複を作らず、解除失敗時は実際に残ったcallbackを保持して再試行できなければならない。Blender event loopへ
callback例外を漏らさず、型名と上限付きmessageだけを軽量statusとして保持する。

#### 4.3.5 Playback Sync Runtime

`PlaybackSyncRuntime`はDCC Main Threadで生成済みの`AdapterDispatch`、
`AuthorityHandoffTransport`、`PlaybackTopicTransport`、`PlaybackController`の所有権を一つの短命Sessionへ束ねる。
RuntimeはClient、Broker、DCC Host objectを生成せず、これらのcomponentを直接closeする責務だけを持つ。
移譲したcomponentは同時利用とRuntime close後の別Session再利用を拒否する。
dispatchのreceiveと両transportのsubscribe/publishは同じClient instanceを共有しなければならない。
`start`は一度だけ実行でき、Authority control topic、Playback topic、dispatchの順に起動する。
いずれかのsubscribeまたはdispatch startが`True`でない場合は両transport、dispatch、Controllerをrollback closeし、
receiverを残さずRuntimeをClosed/Failedとして再起動を拒否する。
ただしunsubscribe rollback自体が失敗した場合はClientを閉じずFailed/openに残し、`close`での再試行を要求する。

`pump(max_items)`は生成元Main Threadだけで実行し、dispatchのdrain handlerからAuthority transportへ先にFrameを渡し、
未処理FrameだけをPlayback transportの処理へ渡す。関連しないFrameもdrain済み件数に含め、handlerまたはdispatchの例外はRuntimeの型付き
Failed状態へ記録して再送出する。Adapterが保持するfailed slotはRuntimeが自動retryまたは破棄してはならない。
`pump`はdrainの前後でreceiver errorを確認し、disconnectやqueue overflowを正常な0件idleとして扱わない。
Runtimeのstart、pump、closeは同期再入を拒否する。

`close`は冪等であり、いずれかのunsubscribe失敗時はdispatchとControllerを停止せず、Runtimeをopenのままclose retryへ
残す。両transportのunsubscribe成功後はdispatchのsession closeとController closeを両方試行し、dispatch停止timeoutまたは
component例外があれば終了後にRuntimeをFailedとして原因を返す。共有Client自体のcloseはAdapterDispatchの
所有責務であり、RuntimeやPlaybackTopicTransportは直接closeしない。

#### 4.3.6 Playback Session composition

`PlaybackSessionConfig`はPeer、Session、Room、Topic、Channel、初期Authority、Host時刻単位とtimebaseを
すべて明示する。`compose_playback_session`は専用Clientを生成し、ClientのPeer IDがConfigと一致することを
join前に検証してからRoomへjoinし、`AuthorityHandoffTracker`、`AuthorityHandoffTransport`、
`PlaybackTimeMapper`、`PlaybackTopicTransport`、`AdapterDispatch`、`PlaybackController`、
`PlaybackSyncRuntime`を一つの未開始Sessionへ構成する。HostはControllerを生成する前にcallback relayを受け、
relayはController handlerへ一度だけbindする。DCC固有のHostとLifecycleはfactory注入とし、Session自身はDCCを
importしない。Playbackの`topic`は`sync/<session_id>/control`と異ならなければならない。

Sessionの`start`はLifecycleへ委譲する。開始済みSessionの`close`はLifecycle closeの成功後に専用Clientを閉じる。
一度もstartを試行していない場合だけRuntimeを直接closeしてからClientを閉じる。start試行済みのSessionは、
Lifecycleがrollback済みでもLifecycle cleanupを経由する。Lifecycle cleanup失敗時はClientを閉じず、同じowner
threadからcloseを再試行する。

Material変換、Camera適用、Morph Weight更新、Texture出力、Node生成などのDCC操作はClient SDKではなく
各DCC Adapterが所有する。

### 4.4 配布とインストール

Brokerは管理者権限を要求せず、Windows user単位で次の場所へ配置する。

```text
%LOCALAPPDATA%\YWTA\Link\
├── versions\
│   ├── 0.1.0\ywta-link.exe
│   └── 0.2.0\ywta-link.exe
├── current.json
├── runtime\
│   └── v1\broker.json
└── logs\
```

Versionごとにside-by-side配置し、実行中Fileを上書きしてはならない。`current.json` は既定で起動する
Broker versionと実行Fileを指す小さいmanifestとし、一時Fileへの書き込みとatomic replaceで更新する。
`current.json` は `protocol_version`、非空の `version`、Install root内を指す相対 `executable` を必須とする。

通常の利用でglobal PATH、system environment variable、Windows Service登録を要求してはならない。
PATH追加はCLI利用者向けの明示的な任意Optionとする。

ClientがBroker実行Fileを探索する順序は次のとおり。

1. 開発・Test用の明示Override `YWTA_LINK_EXE`
2. `%LOCALAPPDATA%\YWTA\Link\current.json` が指すユーザー単位Install
3. Client packageに同梱された互換Broker artifact
4. PATH上の `ywta-link.exe`。これは任意fallbackであり、Production Adapterは依存しない

`YWTA_LINK_EXE` が設定されているのにFileがない、起動できない、またはProtocol非互換の場合は、
別候補へ黙ってfallbackせず、開発設定の誤りとしてfail closedに報告する。

Client distributionがBrokerを同梱する場合、少なくとも次を持つartifact manifestを同梱する。

```json
{
  "broker_version": "0.1.0",
  "protocol_versions": [1],
  "file": "ywta-link.exe",
  "sha256": "..."
}
```

Clientは同梱artifactのSHA-256とmanifestを検証してから使用する。破損または不一致を黙って実行しては
ならない。v1は起動時のnetwork downloadを要求せず、同梱済みまたはユーザーが明示的に取得した
artifactだけを使用する。

#### 4.4.1 初回bootstrap

Process起動とユーザー領域への書き込みが可能なClientは、互換Brokerがない場合に次を実行できる。

1. 同梱artifact manifestとSHA-256を検証する。
2. Install用OS lockを取得する。
3. Version directoryとは別の一時directoryへ展開する。
4. 展開後のFileを再検証する。
5. Version directoryへatomicに移動する。
6. `current.json` をatomicに更新する。
7. Installed Brokerをbackground起動する。

複数DCCが同時にbootstrapしても、同じVersion directoryや `current.json` を同時更新してはならない。
lock取得に失敗したClientは、他ClientのInstall完了を待ってから再探索する。

Process起動または安全な展開を行えないClientはInstallを試みず、既存Brokerへ接続する。Brokerがない場合は、
実行すべきstandalone setup commandと診断理由を表示する。この制限のあるClientだけを最初に導入した場合も、
手順が行き止まりになってはならない。

#### 4.4.2 Standalone setup

Broker実行File自身がユーザー単位Installを行える構成を推奨する。

```powershell
.\ywta-link.exe install --user
.\ywta-link.exe install --user --add-to-path
```

既定の `install --user` はPATHを変更しない。`--add-to-path` は明示指定時だけUser PATHを変更する。
環境変数変更の反映に新しいShellが必要な場合は、その旨を出力する。

#### 4.4.3 Update

- 起動中BrokerがClientとProtocol互換なら、同梱BrokerのPatch/Minor versionが新しいだけでは強制再起動しない。
- 新しいBrokerは別Version directoryへInstallし、`current.json` だけを新Versionへ切り替える。
- 起動中Brokerは最後のClientが退出するまで旧Versionで継続できる。
- 次のcold startから `current.json` が指す新Versionを使用する。
- 自動downgradeを行わない。
- Protocol互換性がない場合は、同じendpointへ競合Brokerを起動せず、診断を返す。

#### 4.4.4 Uninstallとcleanup

YWTA Linkは複数DCCで共有されるため、個別DCC Pluginの削除に連動してBrokerを削除してはならない。
Uninstallは明示的な共通Commandで行う。

```powershell
ywta-link uninstall --user
ywta-link cleanup
```

Uninstallは起動中Brokerと接続中Peerを確認し、使用中なら既定で拒否する。Version cleanupは実行中Version、
`current.json` が指すVersion、rollback用の直前Versionを削除してはならない。

### 4.5 環境変数

v1で予約する環境変数は次のとおり。

```text
YWTA_LINK_EXE
YWTA_LINK_ENDPOINT
YWTA_LINK_LOG_LEVEL
```

- `YWTA_LINK_EXE`: Broker実行Fileの開発・Test用Override
- `YWTA_LINK_ENDPOINT`: Port衝突、隔離Test、複数Version検証用の接続先Override
- `YWTA_LINK_LOG_LEVEL`: 診断Log levelのOverride

これらは通常利用の必須設定ではない。Clientは現在Processの環境を読むだけとし、起動時にsystemまたは
User environment variableを暗黙に変更してはならない。

## 5. Broker lifecycle

### 5.1 自動起動

1. Clientは `%LOCALAPPDATA%\YWTA\Link\runtime\v1\broker.json` を探索する。
2. Manifestがなければ、ClientはBroker候補をbackground起動する。複数Clientが同時に候補を起動してよい。
3. 各候補は完全なJSONを同一directoryの一時Fileへ書き、hard linkの排他的作成で
   `broker.json` をclaimする。claimできなかった候補は終了する。
4. Clientはclaim完了を上限付きで待ち、Manifestのnumeric loopback endpointへ接続する。
5. Clientは `hello` に一回限りのchallengeを付け、Brokerが返すchallenge、correlation、
   instance tokenをManifestと照合してから接続成功とする。

Runtime manifestは短命な接続先情報だけを持つ。

```json
{
  "protocol_version": 1,
  "endpoint": "127.0.0.1:49152",
  "pid": 12345,
  "token": "12345-..."
}
```

壊れたManifestまたは到達不能なBrokerは、Manifestの更新時刻、移動前後のbyte一致、instance token、
Owner PIDの停止を確認した場合だけstaleとして回収する。PIDの生存を判定できない場合は、複数Brokerへの
分裂を避けるため稼働中として扱う。起動候補がclaim前後に終了した場合、Clientはstartup timeout内で
別候補を再起動できる。

複数DCCを同時起動してもBroker Processは1つだけでなければならない。

### 5.2 自動終了

Brokerは接続中Clientが0件になった後、設定されたidle timeoutを待って終了する。
待機中にClientが再接続した場合は終了を取り消す。
自動起動APIのidle timeoutは正の秒数を必須とする。CLIで明示した0秒は、接続の有無にかかわらず
空のBrokerを直ちに終了させる診断用設定として扱う。

BrokerはWindows Serviceとして常駐せず、Console WindowやTray Iconを必須としない。

### 5.3 異常終了からの復旧

Thin Clientのv1基盤は、呼出元が明示的に呼ぶ同期`reconnect()`を提供してよい。これはbackground thread、
自動DCC dispatch、暗黙のretryを開始しない。明示endpoint Clientは同じnumeric endpointとPeer IDを、runtime
bootstrap Clientは保存済みのruntime bootstrap設定とPeer IDを再利用する。明示endpointの`reconnect()`は有限の
timeoutを必須とし、runtime bootstrapは保存済みstartup timeoutを使う。再接続後は、成功済みRoom joinを
Room名の辞書順で、成功済みSubscriptionを`(room, topic)`の辞書順で再広告する。`leave`は対象Roomとその
Subscriptionを、`unsubscribe`は対象Subscriptionを再広告対象から除去する。再広告途中の失敗は接続を閉じ、
広告状態を次回の明示retry用に保持する。通常のsend/receiveで検出した切断はClient errorとしてsocketを閉じるが、
fixed headerを1 byteも読んでいないidle receive timeoutだけは切断と見なさず、明示retryまたは次のreceiveに
備えてsocketを維持する。fixed header途中またはheader/body途中のtimeoutはframe同期を失うため切断として扱う。
`subscribe`はlocalでjoin済みのRoomだけに許可する。`close(); connect()`でも同じ広告を一度だけ再送し、
`reconnect()`が二重送信してはならない。

AdapterはBroker切断を検出したら、上限付きexponential backoffで再接続してよい。Brokerが存在しなければ、
自動起動手順を再実行してよい。自動retryを採用するAdapterも、再接続後はPeer identity、Room、Capability、
Subscriptionを再広告する。

Brokerは状態非保持を原則とし、再起動前の未完了Requestを成功扱いしてはならない。

## 6. Room、Peer、Topic、Capability

### 6.1 Peer

Peerは起動中のClient instanceである。同じApplicationを複数起動した場合も別Peerとして扱う。

Peerは少なくとも次を広告する。

```json
{
  "peer_id": "blender:01J...",
  "application": "blender",
  "application_version": "4.4",
  "plugin_version": "0.1.0",
  "protocol_versions": [1],
  "capabilities": [
    "camera.read.v1",
    "camera.apply.v1",
    "sync.contract.v1",
    "sync.preview.v1",
    "material.read.v1",
    "material.apply.v1",
    "texture.reload.v1",
    "typed-blob.inline.v1"
  ]
}
```

`peer_id` はBroker Processの生存期間内で一意でなければならない。Application名だけを宛先として
使用してはならない。
`ywta-link:broker`はBroker生成Envelope専用の予約IDであり、ClientのHello sender / Peer IDとして使用した場合は、
Monitor予約IDの認証規則とは別に接続登録前に拒否する。

### 6.2 Room

RoomはProjectまたはAsset作業単位の通信境界である。Peerは0個以上のRoomへ参加できる。
Roomは長めに存続する参加範囲であり、1つのRoom内で複数の短命なSync Sessionを同時に扱える。
Roomへの参加だけでScene変更を開始してはならない。

v1では次を認める。

- Client設定またはProject manifestから得た明示的なRoom ID
- 明示IDがない場合のローカル既定Room `default`

Project pathからRoom IDを自動生成する規則は、異なるDCCでProject rootが一致しない可能性があるため
v1では規定しない。複数Projectの誤同期を避けるため、Adapterは可能な限り明示Room IDを使用する。

### 6.3 Topic

TopicはRoom内のPublish/Subscribe分類である。例を次に示す。

```text
presence
sync/session
camera/main
morph/face
motion/body
material/skin
material/hair
texture/face
texture/clothes
```

Topic名の階層表現は分類用であり、wildcard subscriptionの対応はv1必須ではない。

### 6.4 Capability

CapabilityはPeerが処理できるversioned operationまたはtransportである。

```text
camera.read.v1
camera.apply.v1
transform.read.v1
transform.apply.v1
morph-weights.read.v1
morph-weights.apply.v1
motion.read.v1
motion.apply.v1
sync.contract.v1
sync.authority.v1
sync.preview.v1
sync.commit.v1
material.read.v1
material.apply.v1
material.export.v1
texture.export.v1
texture.reload.v1
typed-blob.inline.v1
```

送信側は対象Peerが必要Capabilityを広告していることを確認する。未知または非対応Capabilityを
暗黙に実行してはならない。

Authority handoffへ参加するPeer（Requestを発行する次Authority、Requestを受理する現在Authority、
Accepted/Rejectedを適用する他のParticipant）は、`sync.authority.v1`をCapabilityとして広告しなければならない。
Session negotiationでは、このCapabilityと対象ChannelのAuthority/Target Bindingを全Participantについて検証し、
不足または非対応の場合はhandoffをActiveとして扱ってはならない。Capabilityを広告しないlegacy Peerへ
Authority handoffを暗黙に適用してはならない。

## 7. Message model

### 7.1 Message種別

v1は少なくとも次の論理Messageを持つ。

- `hello`: Protocol negotiationとPeer登録
- `join`: Room参加
- `leave`: Room退出
- `subscribe`: Topic購読
- `unsubscribe`: Topic購読解除
- `publish`: RoomまたはTopicへのEvent配信
- `request`: 特定Peerへの処理要求
- `response`: Request成功応答
- `error`: Request失敗またはProtocol error
- `ping` / `pong`: 接続生存確認
- `binary.begin` / `binary.chunk` / `binary.end`: chunked binary転送

### 7.2 共通Envelope

共通Envelopeは小さいUTF-8 JSON objectとする。

```json
{
  "protocol_version": 1,
  "message_id": "01J...",
  "type": "publish",
  "room": "character-a",
  "sender": "photoshop:01J...",
  "target": null,
  "topic": "texture/skin",
  "correlation_id": null,
  "schema": "ywta.texture-set.updated.v1",
  "body": {
    "material_id": "skin",
    "revision": 8
  }
}
```

要件は次のとおり。

- `protocol_version`、`message_id`、`type`、`sender` は必須とする。
- Room内Messageでは `room` を必須とする。
- Target送信では `target` を必須とする。
- Requestに対するResponse/Errorは `correlation_id` に元Requestの `message_id` を設定する。
- Schemaを持つPayloadはversionを含む安定IDを指定する。
- 受信側は未知Fieldを無視できなければならない。
- 受信側は必須Field欠落、型不一致、上限超過をfail closedで拒否する。

### 7.3 Routing

Brokerは次のRoutingを提供する。

1. Room broadcast: Room内の全Peerへ送信する。
2. Topic publish: Topic購読中のPeerへ送信する。
3. Target send: 指定 `peer_id` だけへ送信する。
4. Request/Response: `correlation_id` により依頼元へ応答する。

Binary bodyを含むMessageでも同じRouting規則を使用する。

## 8. TransportとWire framing

### 8.1 Transport要件

- Brokerはloopback interfaceだけにbindしなければならない。
- 非loopback接続を受け入れてはならない。
- Clientは外向き接続だけを使用する。
- TransportはControl MessageとBinary Messageの両方を運べなければならない。
- Brokerは受信Message size、chunk size、未完了転送数、queue sizeに上限を持たなければならない。
- 上限値は実装時にbenchmarkと実DCC smokeを基に確定する。

### 8.2 v1のTransport候補

Application protocolはTransportから独立させる。v1実装前のHost feasibility spikeで、次の組み合わせを
確定する。

- Raw localhost TCP: 純Python Clientの第一候補
- WebSocket: Photoshop UXP Clientの第一候補
- Raw TCPまたはWebSocket: Unity C# Client

Brokerが複数Transportを提供する場合も、すべて同じRoom RouterとMessage modelへ接続する。

### 8.3 Wire framingの制約

正確なbyte layoutはTransport spike後にprotocol fixtureとともに確定する。ただし、v1 framingは
次の条件を満たさなければならない。

- Header lengthとBinary body lengthを送信前に宣言する。
- HeaderはUTF-8 JSONとする。
- Binary bodyは変換せずraw bytesとして保持する。
- Base64を使用しない。
- Byte orderと整数幅を仕様で固定する。
- 不正長、overflow、途中切断を検出して転送を破棄する。
- Client実装に汎用RPC frameworkやFFI bindingを要求しない。

Raw TCP用framingは、小さい固定Header、JSON Header、任意Binary bodyの順とする案を第一候補とする。
WebSocketでは同じ論理FrameをBinary Messageとして運べることを推奨する。

## 9. Binary payload

### 9.1 v1標準経路

v1の標準Binary経路はinline binaryである。

```text
Message
├── JSON Header
└── Raw Binary Body
```

大容量Bodyは上限付きchunkへ分割できなければならない。Brokerは可能な限り全Bodyを一度に
materializeせず、backpressureを適用しながら対象Peerへ転送する。

### 9.2 型情報

Binary Messageは少なくとも次をHeaderで宣言する。

```json
{
  "transfer_id": "01J...",
  "schema": "model/gltf-binary",
  "byte_length": 4320000,
  "revision": 12,
  "content_hash": null
}
```

- `schema` は標準media typeまたはversioned YWTA schema IDとする。
- `byte_length` は必須とする。
- `content_hash` はAsset同一性や外部検証が必要な用途では設定する。
- BrokerはPayload schemaの意味を解釈しない。
- Consumerはschema、長さ、構造をDCCへ適用する前に検証する。

Mesh、画像、Sceneについて適切な標準形式が存在する場合は、独自Typed Array schemaより
GLB、PNG、EXRなどの既存形式を優先する。標準形式で表現できない一時Dataに限り、
offset、dtype、shape、strideを持つversioned YWTA binary schemaを定義する。

### 9.3 転送の不変性

送信開始後にProducerがPayload内容を変更してはならない。受信側の編集結果は同じBufferを
書き換えず、新しいrevisionを持つMessageとして送信する。

### 9.4 Shared Memory拡張

`typed-blob.shm.v1` は予約Capabilityとし、v1必須機能にはしない。次の条件が実測で成立した場合だけ、
別仕様として追加を検討する。

- 数百MB級Payloadを反復送信する。
- 毎秒単位の更新が必要になる。
- Broker copyまたはsocket転送が待ち時間の支配要因になる。
- 複数Consumerへのfan-outでmemory bandwidthまたはallocationが問題になる。

追加する場合、raw pointerではなくmapping identifier、offset、length、schemaを渡す。Producerは
Publish後に変更せず、Consumerはread-only mappingを使用する。ACK、timeout、crash cleanup、ACL、
size/stride検証を仕様化するまで本番利用してはならない。

## 10. YWTA Common

### 10.1 役割とSchema規則

YWTA Commonは、複数DCCで共有できる意味を表すversioned schema群である。DCCのAPI objectやNode Graphを
そのまま共通化せず、Adapterが安定ID、Unit、座標系、Host objectを相互変換する。

すべてのCommon schemaは次を満たさなければならない。

- `schema`に互換性を含む安定IDを持つ。
- ObjectとChannelは、表示名とは別にSession内で安定したIDを持つ。
- 長さ、角度、時間、色など、解釈が分かれる値はUnitまたはColor spaceを明示する。
- 送信元、revision、change IDを追跡できる。
- Adapterは適用結果を`exact`、`approximated`、`unsupported`のいずれかで報告する。
- version付きCommon schemaのtop-level Field集合は固定し、同じversionの未知Fieldは拒否する。Fieldを拡張する場合は
  schema versionを上げ、未知の必須意味を推測して適用しない。未確定のnested objectをopaqueに保持する例外は、
  個別schemaで明示する。

OpenUSD、glTF、MaterialX、OpenTimelineIOはField選定と用語の参考にする。ただし、YWTA Linkの通信や
DCC Adapterへ各Runtimeの導入を要求しない。

Schema定義とGolden JSON fixtureを正本とし、Clientごとの実装は小さい型、validator、encode/decodeに
限定する。Code generationや共通Native libraryへのFFIをClient適合要件にしない。

### 10.2 Entity Reference

`ywta.common.entity-ref.v1`は、同期対象をDCC非依存に参照する。

```json
{
  "entity_id": "camera:shot-010-main",
  "kind": "camera",
  "display_name": "Shot010_Main",
  "namespace": "shot-010"
}
```

`entity_id`はSync Session内で安定していなければならない。DCC object path、UUID、Node名との対応は
ContractのBindingまたはAdapter設定へ置き、Common payloadへHost固有pathを必須化しない。

#### v1 wire contract

Entity Reference payloadのtop-level Fieldは`entity_id`、`kind`、`display_name`、`namespace`の4個に固定する。
`schema` discriminatorはpayloadへ含めず、EnvelopeまたはSync Contractのschema ID
（`ywta.common.entity-ref.v1`）で識別する。4 Fieldはすべて必須キーとし、未知Fieldは拒否する。

`entity_id`、`kind`、`display_name`は空でないUTF-8文字列とする。`kind`は閉じたenumにせず、Adapterが拡張できる
non-empty identifierとして扱う。3 Fieldおよび文字列の`namespace`は空白だけの値を拒否するが、表示名などの意味を
持つ文字列に含まれる空白は許可する。`namespace`は`null`または空白でないUTF-8文字列で、`null`はnamespaceなしを表す。
Host path、UUID、Node名をこれらのFieldへ要求しない。

`entity_id`の安定性はSync Session内での意味上の要件であり、statelessなcodecはSession状態を保持せず、その要件を
検証しない。Python codecは入力objectを検証してfrozen dataclassへ変換し、出力はtop-level Fieldを追加せず、
sort keys、allow_nan=falseのdeterministic compact UTF-8 JSONとする。直接constructorもdecodeと同じField検証を行う。

### 10.3 Transform

`ywta.common.transform.v1`は、Translation、Rotation、Scaleと座標系metadataを表す。Matrixだけを唯一の
表現にせず、少なくとも次を規定する。

- 親EntityまたはWorldのどちらを基準にするか
- Right-handedまたはLeft-handed
- Up axisとForward axis
- Translationの長さUnit
- Rotation表現と回転順序
- Scaleと必要な場合のShear対応可否

Adapterは座標系変換後の結果を報告する。Shear、負Scale、分解不能Matrixを黙って近似してはならない。

#### v1 wire contract

Transform payloadのtop-level Fieldは`entity_ref`、`translation`、`rotation`、`scale`、
`coordinate_system`、`unit`、`rotation_order`の7個に固定する。全Fieldを必須キーとし、`schema` discriminatorは
payloadへ含めず、EnvelopeまたはSync Contractのschema ID（`ywta.common.transform.v1`）で識別する。

```json
{
  "entity_ref": {
    "entity_id": "camera:shot-010-main",
    "kind": "camera",
    "display_name": "Shot010_Main",
    "namespace": "shot-010"
  },
  "translation": [0.0, 1200.0, 3500.0],
  "rotation": [0.0, 0.0, 0.0, 1.0],
  "scale": [1.0, 1.0, 1.0],
  "coordinate_system": {
    "space": "world",
    "handedness": "right",
    "up_axis": "+y",
    "forward_axis": "-z",
    "parent_entity_id": null
  },
  "unit": "millimeter",
  "rotation_order": null
}
```

`entity_ref`は`ywta.common.entity-ref.v1`に適合するobjectで、Transformの対象Entityを安定IDで示す。
`translation`、`rotation`、`scale`はそれぞれ3要素、4要素、3要素のfinite number配列とする。
`rotation`は`[x, y, z, w]`のquaternionに固定し、normが1から1e-6以内の入力だけを受け入れる。codecは入力を
正規化または符号反転せず、`q`と`-q`の両方を許可する。`scale`は0または負の値も表現可能とし、適用可否はAdapterが
`exact`、`approximated`、`unsupported`で報告する。Shearはv1のFieldに含めない。

`coordinate_system`は`space`、`handedness`、`up_axis`、`forward_axis`、`parent_entity_id`の5 Fieldに固定する。
`space`は`world`または`parent`、`handedness`は`right`または`left`、axisは`+x`、`-x`、`+y`、`-y`、
`+z`、`-z`のいずれかとする。UpとForwardは符号を除いた基底axisが異ならなければならない。`world`では
`parent_entity_id`を`null`、`parent`では空白でないUTF-8文字列とし、Entity Reference全体を重複させない。
Transform自身の`entity_id`を直接parentに指定してはならない。複数Entityにまたがる長いcycleの検証は、単一payloadの
codecではなくSync SessionまたはAdapterのscene graph検証で行う。

`unit`はTranslationの長さ単位であり、`millimeter`、`centimeter`、`meter`のいずれかとする。Scaleとquaternionは
unitlessである。`rotation_order`はv1では必須キーかつ`null`に固定する。Euler回転順序はv2または明示的な拡張で
追加する。未知Field、欠落Field、非文字列key、UTF-8へ変換できない文字列は拒否する。Python codecは入力objectを
frozen dataclassへ変換し、出力はsort keys、allow_nan=falseのdeterministic compact UTF-8 JSONとする。

### 10.4 Time

`ywta.common.time.v1`は、単一時刻、範囲、sample rateを表す。Frame番号だけを送らず、整数の分子と分母で
timebaseを表現し、29.97 fpsなどを丸めない。

```json
{
  "time": null,
  "start": 1001,
  "end_exclusive": 1101,
  "timebase": { "rate_num": 24000, "rate_den": 1001 },
  "sample_rate": null
}
```

範囲の終端はexclusiveとする。DCC側のinclusiveなPlayback rangeへの変換はAdapterが行う。
Time payloadのtop-level Fieldは`time`、`start`、`end_exclusive`、`timebase`、`sample_rate`の5個に固定し、
すべて必須キーとする。単一時刻では`time`だけを整数にして`start`と`end_exclusive`を`null`、範囲では
`time`を`null`にして`start`と`end_exclusive`を整数にする。範囲は`start < end_exclusive`の半開区間とする。
tickはJavaScript Clientでも丸めず扱える±(2^53-1)のJSON safe integerに限定する。
`timebase`は必須の`rate_num`/`rate_den` object、`sample_rate`は同じ形式または`null`である。rate objectは
2 Fieldだけを必須とし、未知Fieldを拒否する。
各rateの分子・分母は1以上2^31-1以下の既約整数とし、非既約の入力を正規化してはならない。
同じ範囲の両端が同じrateを持つため、各pointへ`rate_num`と`rate_den`を重複して埋め込まず、payloadの
`timebase`へ一度だけ置く。`sample_rate`はtimebaseとは独立したsampling cadenceを明示する場合に指定し、
省略時は`null`とする。同じrateを明示することも許可する。

本文書はDraftであり、このtyped codecとGolden fixtureを`ywta.common.time.v1`の最初のcanonical wire contractとする。
先行する実装・release済みAdapterはなく、以前の説明用point objectはfreeze前にこの形式へ置き換えた。

### 10.5 Camera

`ywta.common.camera.v1`は、`entity-ref`、`transform`、`time`と組み合わせてCameraを表す。初期Fieldは
次のとおり。

- Projection種別: `perspective`または`orthographic`
- Focal length
- Horizontal aperture、Vertical aperture、Aperture offset
- Near clip、Far clip
- Focus distance、F-stop、Exposure
- Orthographic size
- Film fitまたはGate fitの意図

#### v1 wire contract

Camera payloadのtop-level Fieldは次の15個に固定する。全Fieldを必須キーとし、projectionで適用しない
値だけを`null`にする。`schema` discriminatorはpayloadへ含めず、EnvelopeまたはSync Contractのschema ID
（`ywta.common.camera.v1`）で識別する。`entity_ref`と`time`は、それぞれ確定済みの
`ywta.common.entity-ref.v1`と`ywta.common.time.v1`に適合しなければならない。`transform`は
`ywta.common.transform.v1`に適合するobjectとして保持し、Camera内の`entity_ref`と`transform.entity_ref`は
4 Fieldすべてが一致しなければならない。Cameraの全長さFieldはmm、Transformのunitとは独立して扱う。

本文書はDraftであり、Transform型の確定とCamera Golden fixtureへのcompositionをCamera v1の最初のcanonical
Transform contractとする。先行するrelease済みAdapterはなく、以前のopaqueな説明用objectはfreeze前に置き換えた。

| Field | wire type | 意味・制約 |
| --- | --- | --- |
| `entity_ref`、`transform`、`time` | object | Common object。JSON object以外は拒否する |
| `projection` | string | `perspective` または `orthographic` |
| `focal_length` | number または `null` | Perspective必須。長さはmm、正数 |
| `horizontal_aperture`、`vertical_aperture` | number または `null` | Perspective必須。長さはmm、正数 |
| `aperture_offset` | `[number, number]` または `null` | `[horizontal, vertical]` の順、長さはmm。Perspective必須 |
| `clipping_range` | `[number, number]` | `[near, far]` の順、長さはmm、正数かつnear < far |
| `focus_distance` | number または `null` | 長さはmm、正数。nullは未提供 |
| `f_stop` | number または `null` | 正数、nullは未提供 |
| `exposure` | number または `null` | EV（unitless）のscalar、nullは未提供 |
| `orthographic_size` | number または `null` | Orthographic必須。長さはmm、正数 |
| `film_fit`、`gate_fit` | string または `null` | `horizontal`、`vertical`、`fill`、`overscan` のいずれか |

Orthographicでは`orthographic_size`を必須とし、`focal_length`、`horizontal_aperture`、
`vertical_aperture`、`aperture_offset`は`null`にする。Perspectiveでは逆にそれらのLens Fieldを必須とし、
`orthographic_size`は`null`にする。`focus_distance`、`f_stop`、`exposure`、fit意図は両Projectionで
利用可能だが、未提供なら`null`にできる。Camera固有の全長さ値をmmへ統一することで、OpenUSD Cameraの
focal/aperture語彙とclip/focus/orthographic sizeを同じwire unitで扱い、Transformのunitとは独立に
AdapterがHostのscene unitへ変換する。

Python codecは入力objectを再帰的に検証・immutable copyし、出力は未知Fieldを追加せず、UTF-8の
deterministic compact JSON（sort keys、allow_nan=false）とする。

DCCがFieldを直接表現できない場合は`approximated`または`unsupported`を返す。FOVだけを持つHostでは、
ApertureとFocal lengthのどちらをAuthorityとしたかをAdapterのmapping profileで固定する。

### 10.6 Playback

`ywta.common.playback.v1`は、DCCの再生ボタン操作、停止位置、再生範囲、速度、方向、Loop意図を表す。
再生中の毎Frame値を配信するためのAnimation Streamではなく、再生状態の変更を同期するためのCommon schemaである。

#### v1 wire contract

Playback payloadのtop-level Fieldは`state`、`position`、`playback_range`、`speed`、`direction`、
`loop_mode`、`change_id`の7個に固定する。全Fieldを必須キーとし、`schema` discriminatorはpayloadへ含めず、
EnvelopeまたはSync Contractのschema ID（`ywta.common.playback.v1`）で識別する。`position`は
`ywta.common.time.v1`のsingle-mode object、`playback_range`は同schemaのrange-mode objectでなければならない。
両者の`timebase`は分子・分母が完全一致しなければならず、`position`が範囲外でもpaused seekまたはpre-rollを
表現できるため拒否しない。

| Field | wire type | 意味・制約 |
| --- | --- | --- |
| `state` | string | `playing`または`paused`。`playing`は受信したpositionから再生を開始するstate transition、`paused`はその位置で停止する状態 |
| `position` | object | single-modeのTime。再生位置またはpaused seek位置 |
| `playback_range` | object | range-modeのTime。半開区間として扱う |
| `speed` | number | finiteかつ正の再生倍率。bool、0、負数は不可。0をpauseの代用にしない |
| `direction` | string | `forward`または`reverse` |
| `loop_mode` | string | `once`、`loop`、`ping-pong`。Hostが表現できない場合はnegotiation/apply resultを`approximated`または`unsupported`とする |
| `change_id` | string | 空白だけでないUTF-8文字列。Envelopeの`sender`由来の`origin_peer_id`と組み合わせてremote applyのecho再publishを判定するlogical key。Envelopeの`message_id`はtraceとtransport重複検出に使う |

v1は`stop`をenumに含めない。Stop操作はHost間の意味差が大きいため、Adapterが`paused`と必要な別seekへ
マッピングする。Scrub/seekは`paused`の`position`更新で表す。Playback codecは入力objectを検証してfrozen typed
objectへ変換し、出力は未知Fieldを追加せず、UTF-8のdeterministic compact JSON（sort keys、allow_nan=false）とする。
`change_id`はpayload必須のcontrol metadataであり、Contractの`field_subset`から除外されても全Adapterが消費して
echo判定に使う。`field_subset`はDCCへ適用する意味Fieldだけを列挙する。Local operationが新たに発行した
logical `change_id`は、同一origin／同一Session内で同じ値を再利用してはならない。

### 10.7 Morph Weight

`ywta.common.morph-weights.v1`は、Blendshape、Shape Key、Morph Targetの現在値を表す。

- 安定した`channel_id`と表示名
- 現在Weight、Neutral、許容Min/Max
- 任意のGroup
- revisionとchange ID

v1はMorph形状、Driver Graph、Corrective relation、In-between定義を同期しない。Channelの対応は名前一致へ
固定せず、Sync ContractのBindingで明示する。

### 10.8 Motion Clip

`ywta.common.motion-clip.v1`は、Transform ChannelとMorph Weight Channelの時間変化を表す。Clip ID、Time range、
timebase、Channel binding、KeyまたはSample、Interpolation、Loop intentを持つ。

Motion同期はSkeleton階層、Rest pose、回転表現、補間、Retargetの差が大きい。v1の最初の実証対象にはせず、
Cameraと現在Morph Weightの契約が実Hostで成立した後に導入する。異なるSkeleton間のRetargetはAdapterまたは
別の明示的なmapping profileの責務とする。

### 10.9 意味モデルの参照仕様

Common schemaの設計では、次の公開仕様を語彙とField粒度の参考にする。

- Camera: [OpenUSD UsdGeomCamera](https://openusd.org/dev/api/class_usd_geom_camera.html)
- Camera、Node Transform、Morph Weight Animation: [glTF 2.0](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)
- Joint AnimationとBlend Shape Weight: [OpenUSD UsdSkel](https://openusd.org/dev/api/_usd_skel__schemas.html)
- Time range: [OpenTimelineIO Time Ranges](https://opentimelineio.readthedocs.io/en/latest/tutorials/time-ranges.html)
- Material: [MaterialX](https://materialx.org/)

参照仕様とYWTA Commonで意味が異なるFieldは、YWTA Common側で変換規則を明記する。参照仕様への変換可能性を
理由に、DCC Adapterの適用結果を自動的に`exact`とみなしてはならない。

## 11. Ephemeral Sync Contract

### 11.1 RoomとSync Sessionの境界

Sync Sessionは、Room内で特定の作業だけを接続する短命な単位である。Roomは参加者をまとめるが、
Sync Sessionは同期対象、Schema、Authority、Target、Binding、終了時の扱いを定義する。

同じRoomで、Camera同期とMorph Weight同期を別Sessionとして開始、停止できる。Sessionを閉じてもRoom接続や
他Sessionを切断してはならない。

Room内で同じ作業用Sessionへ自動参加する場合、Clientはtype=`request`、target=`ywta-link:broker`、
schema=`ywta.session.slot.join.v1`を送る。Requestは参加済みRoomを必須とし、topic、correlation_id、raw binary bodyを
持たない。sender（Peer ID）、room、Request message_idはそれぞれ空白だけではない256 byte以下のUTF-8文字列とする。
JSON bodyは次の2 Fieldだけを持つ。

```json
{
  "slot_id": "playback-sync",
  "metadata": {"purpose": "timeline playback"}
}
```

`slot_id`は空白だけではない256 byte以下のUTF-8文字列、`metadata`はserialized JSONで32 KiB以下のopaqueな
JSON objectとする。Broker Process内のactive slotは全Room合計256個までとし、上限到達後も既存slotへのjoinは
許可するが、新規slotのclaimはfail closedで拒否する。
Brokerは`(room, slot_id)`をatomicにclaimし、最初の参加者を`initial_authority`とするfreshな`session_id`を生成する。
同じslotへの後続参加者には最初の提案を正本とする同一descriptorを返し、後続Requestのmetadataで上書きしない。
Responseはsender=`ywta-link:broker`、target=Requester、元Room、correlation_id=元Request message_id、
schema=`ywta.session.slot.descriptor.v1`とし、bodyに`slot_id`、`session_id`、`initial_authority`、`metadata`、
per-response boolの`created`、`state_peer`の正確に6 Fieldを持つ。atomic claimで作成したRequesterだけが
`created=true`となり、`state_peer`はRequester自身とする。既存slotへのjoinは`created=false`とし、Requester追加前の
既存Participantから辞書順最小のconnected Peerを`state_peer`として返す。`initial_authority`はslot作成時のseedを示す
歴史値であり、現在も接続中のAuthorityを保証しない。`created=false`のConsumerは`state_peer`をlive authorityと
authority revisionの照会先とし、Tracker構築前にParticipant間でreconciliationする。同期できるまでは自動joinした
SessionをActiveにしてはならない。
このRequestは通常の未完了Request表へ積まない。

Peerは同じRoomの複数slotへ参加できる。RoomからのleaveまたはdisconnectでそのPeerを各該当slotから除外し、
参加者が0になったslotは即座に破棄する。0参加者からの再作成では過去と異なるfreshな`session_id`を生成する。
slotとdescriptorは永続化せず、Broker再起動でも破棄する。Clientは再接続後にclaim/joinとBinding検証をやり直す。

### 11.2 Contract

Sync ContractはJSONで表し、任意コード、式、Host API呼び出しを含めない。最小構造を次に示す。

```json
{
  "contract_version": 1,
  "session_id": "01J...",
  "room": "shot-010",
  "purpose": "main camera look-through",
  "owner": "blender:01J...",
  "close_policy": "keep-committed",
  "channels": [
    {
      "channel_id": "main-camera",
      "schema": "ywta.common.camera.v1",
      "authority": "blender:01J...",
      "targets": ["maya:01J...", "unity:01J..."],
      "field_subset": ["transform", "focal_length", "clipping_range"],
      "mode": "preview-commit",
      "conflict_policy": "single-writer",
      "mapping_profile": "camera-default.v1",
      "required": true
    }
  ]
}
```

Contractは登録済みCommon schema、Capability、mapping profileだけを参照する。`field_subset`はSchemaが定義した
Fieldの選択であり、実行時に新しいFieldの意味を発明する仕組みではない。

### 11.3 Negotiationと状態遷移

Sync Sessionは次の状態を持つ。

```text
Draft -> Negotiating -> Active -> Closing -> Closed
                       \-> Failed
```

1. OwnerがDraft ContractをRoomへ提示する。
2. 各ParticipantはCapabilityとローカルBindingを検証し、Channelごとに`exact`、`approximated`、
   `unsupported`と理由を返す。
3. 必須Channelを全Targetへ安全にBindingできた場合だけActiveへ遷移する。
4. 必須条件を満たせない場合はFailedとし、部分的にActiveへ移行しない。
5. 任意Channelの非対応はContractで許可した場合だけActiveを妨げない。

Broker再起動でActive Sessionのmetadataが失われた場合、未完了操作を成功扱いしない。OwnerはContractを
再提示し、ParticipantはBindingとBaselineを再検証してから新しいSessionとして再開する。

### 11.4 Authorityと競合

1つのChannelは既定で1つのAuthorityだけを持つ。Authority以外からの更新をAdapterへ適用してはならない。
Authority移譲は、現在Authority、次Authority、対象revisionを明示したRequest、target Response、
Acceptedのfan-out publishとして行う。現在Authorityが唯一のordering coordinatorである。

v1はsilent last-write-winsとmulti-writer mergeを提供しない。Authority切断時はChannelを停止し、別Peerを
自動昇格させない。

Authority handoffの制御payloadは、次の3つのversioned schemaを使う。Payload自身へschema discriminatorは
含めず、Envelopeの`schema`で識別する。Brokerはこれらのbodyを解釈せず、Envelopeの`target`、
`correlation_id`、`message_id`に従って転送する。

AcceptedはRoom内のSession control topicへ`publish`し、全Participantへfan-outする。control topicは
`sync/<session_id>/control`とし、各ParticipantはSession開始時にこのtopicを購読する。Requestは例外として
Envelope type=`request`で`target=current_authority`へ送信する。Requestを発行する次Authorityは送信前に
local pendingを登録し、現在AuthorityはRequestを受信してpendingを登録する。RequestのEnvelope `message_id`が
handoffのtransport identityとなる。現在Authorityは同じAccepted payload/schemaを、まずtype=`response`、
`target=requester`、`correlation_id=request_message_id`でRequestへのtransport completionとして返し、Brokerは
pendingをcloseする。その後、同じAccepted payload/schemaをtype=`publish`、Session control topic、
`correlation_id=request_message_id`で確定通知としてfan-outする。Rejectedはtype=`response`、
`target=requester`、`correlation_id=request_message_id`だけを返し、fan-outしない。`publish`における
`correlation_id`は任意の一般Envelope Fieldだが、Accepted確定通知では必須である。Adapterはtarget responseを
state変更に使わず、Accepted publish確定通知だけでstateを変更する。RequesterもAccepted publishを待つ。
Authority handoffのordering coordinatorは現在Authorityだけであり、target ResponseをAuthority stateの確定や
Peerごとの順序決定には使わない。Brokerはbody非解釈のまま、Envelopeのrouting情報とRequest pendingだけを処理する。

- `ywta.sync.authority.request.v1`: `session_id`、`channel_id`、`current_authority`、`next_authority`、
  `expected_authority_revision`、`change_id`を必須とする。
- `ywta.sync.authority.accepted.v1`: Requestのidentityに加えて`new_authority_revision`を必須とする。
- `ywta.sync.authority.rejected.v1`: Requestのidentityに加えて非空の`reason`を必須とする。

`authority_revision`はContentの`revision`とは別のcontrol-plane revisionで、Channelごとに0から始める。
Requestは現在のAuthorityと期待revisionが一致する場合だけ有効であり、同一Channelにpending Requestがある間の
別Request、および古い`expected_authority_revision`は拒否する。Requestを受けた現在Authorityだけがacceptまたは
rejectを返せる。acceptでは`new_authority_revision = expected_authority_revision + 1`を検証したうえで、
Authority変更、revision更新、pending解放を一つのatomicな状態遷移として適用する。rejectでは非空理由を返し、
Authorityとauthority revisionを変更せず、該当するlocal pendingだけを解放する。Acceptedを受信したPeerは、
actorが現在Authorityであること、payloadの`current_authority`、`expected_authority_revision`、
`new_authority_revision`が現在stateの次revisionであること、非空`correlation_id`を検証する。同一Requestの
local pendingがある場合だけcorrelationを元Requestの`message_id`と一致させる。Requestを観測していない第三
ParticipantはpendingなしでもAcceptedを適用でき、別Requestのlocal pendingがあっても現在Authorityが選んだ
Acceptedをwinnerとして適用し、そのpendingを解放する。これはsilent last-write-winsではなく、明示されたAccepted
winnerへの収束である。Rejectedは一致するlocal pendingだけを解放し、別RequestのpendingとChannel stateを
変更しない。切断の観測はChannel停止にとどめ、自動的なAuthority昇格やrevision更新を行わない。

### 11.5 Preview、Commit、Cancel

`preview-commit` modeでは、Target AdapterはSession開始時または最初のPreview適用前に復元可能なBaselineを
取得する。

- `preview`: 高頻度更新を許可する。ClientとAdapterは古い未適用Previewをcoalesceできる。DCCが対応する場合、
  個別のUndo履歴を増やさない。
- `commit`: 最後に受理した値を1回のDCC transactionまたはUndo単位として確定する。
- `cancel`: Sessionが保持するBaselineへ戻し、未CommitのPreviewを破棄する。

安全なBaseline復元またはUndo境界を提供できないAdapterは`sync.preview.v1`を広告してはならない。その場合は
明示的なsnapshot applyだけを使用する。

### 11.6 Sessionの終了と解体

Session終了時は、Binding、Authority、専用Subscription、revision cache、未Commit Preview、Baselineを
解放する。終了処理は他SessionやRoom参加状態へ影響してはならない。

`close_policy`は次のいずれかとする。

- `keep-committed`: Commit済みのDCC状態を残し、未Commit Previewだけを破棄する。
- `revert-to-baseline`: Commit有無にかかわらず、Session開始時のBaselineへ戻す。
- `require-explicit-commit`: 未Commit変更がある場合はCloseを拒否し、CommitまたはCancelを要求する。

異常切断時は`require-explicit-commit`と同等にfail closedで扱う。自動的なCommitを行ってはならない。

### 11.7 Playback Sync Loop

Playback操作も既存のsingle-writer Channel Authorityに従う。どのDCCからでも操作できるようにする場合は、
現在Authority、次Authority、対象revisionを明示したAuthority handoffを先に完了させる。silent multi-writerや
last-write-winsで再生状態を競合解決してはならない。
Adapterはローカル再生ボタン操作を契機にAuthority handoffを自動要求してよいが、受理される前の操作を
同期済みとして扱ってはならない。これにより、明示的なmulti-writerを導入せず、どのDCCからの操作も同じUIで開始できる。

Envelopeの`message_id`はtransport eventの重複検出とtraceに使う。Playbackのlogical echo identityは
Envelopeの`sender`由来の`origin_peer_id`と`change_id`の組であり、`message_id`だけで判定してはならない。
Target Adapterはremote applyの`(origin_peer_id, change_id)`を有界cacheへ記憶し、同じ組を自DCCのlocal
playback callbackへ関連付けるguardを持つ。callbackには両方の値を保持し、同じ組から発生したcallbackは、
apply終了後に遅れて到着しても再publishしてはならない。

`change_id`はlocal operationごとに新規発行し、同一origin／同一Session内でlocal logical IDを再利用してはならない。
AdapterはPlaybackをremote applyしている間だけでなく、遅延callbackの判定に必要な期間、remote IDをcacheする。cacheはメモリを
無制限に保持せず、有界FIFOまたは同等の有界集合とする。
Echo GuardはSync Sessionごとに1個生成し、そのSessionがClosedまたはFailedになった時点で破棄する。Room単位や
Client process単位でGuardを使い回し、別Sessionの合法な同一`(origin_peer_id, change_id)`を抑止してはならない。

DCC Adapter内のDCC非依存境界は`PlaybackController`へ集約する。Controllerは生成元のowner threadだけが
`handle_host_event`、`apply_remote`、`close`を呼び出せる。`handle_host_event`はeventをPlaybackへmappingし、
現在Authorityがlocal peerの場合だけpublishする。remote applyに由来するcallbackは`origin_peer_id`を渡し、
同じ`(origin_peer_id, change_id)`をEcho Guardが抑止する。`apply_remote`は現在Authorityのoriginだけを受理し、
local self-originはloopbackとして無視する。mapping、publish、Host applyの実行失敗はFailedへ遷移し、原因の
型名と上限付きmessageだけをstatusで観測できる。Close後のControllerおよびGuardは再利用してはならない。
Guardを省略した場合はControllerが新規作成し、注入した場合もそのControllerへSession単位の所有権を移す。
同じGuardの複数Controllerへの注入とClose後の再利用は拒否する。publisherからの同期再publish、Host applyからの
入れ子remote applyもFailedとして拒否し、Host apply中は同じremote identityのecho抑止だけを再入許可する。

現行Host bridgeは遅延して到着するcallbackへremote originを自動関連付けない。Controller利用側がcallback時に
originを明示して即時echoを抑止することをv1の境界とし、Host bridge自身による遅延callbackへの自動相関は
後続仕様とする。

Authority handoffがpendingの間、local mutationを保留できるHostはacceptまで変更を適用・publishしない。
保留できないHostはlast accepted Playback snapshotを保持し、handoffが拒否またはtimeoutになった場合は
Main Thread上でそのsnapshotを復元する。pending中に追加されたlocal操作はlatestだけへcoalesceし、accept前に
publishしてはならない。

`PlaybackHandoffCoordinator`は、このhandoff待ちとHost rollbackをDCC非依存に束ねる。Coordinatorは既存の
Authority transport、Playback controller、Trackerをborrowし、Clientやcomponentのlifecycleを所有しない。
非Authorityのlocal eventは最新一件だけを保持してRequestを一度だけ送り、Accepted responseだけではpublishせず、
Accepted control publishでlocal Authorityになった後、最新eventのsnapshotをHostへMain Threadで再適用してから一度だけ
Controllerへ渡す。再適用またはpublishに失敗した場合はpublishせずCoordinatorをFailedへ固定する。Rejected responseまたは
別RequestのAcceptedによってlocal pendingが解放された場合はlast authoritative snapshotへ復元して保留eventを破棄する。
現在Authorityへの有効なRequestはCoordinatorがTransportへ明示的にacceptさせる。handoff timeoutはMain Thread上で
同じsnapshotへ一度だけ復元し、Tracker pendingを変更せずCoordinatorをterminal Failedへ固定する。publish、Transport、
rollbackの失敗も同様にFailedとして、原因の型名と上限付きmessageだけをstatusで観測可能にする。closeはCoordinatorの
保留状態だけを一度破棄し、borrowed componentの終了は既存Runtimeが行う。

`playing`を受信したAdapterは、受信した`position`から`direction`と`speed`を使ってHostの再生stateへ遷移させる。
`paused`またはseekを受信したときは、そのpositionで停止して再整合する。`loop_mode`は再生の意図であり、Hostが
非対応の場合はnegotiation/apply resultで`approximated`または`unsupported`を返す。Loop再生中の毎Frame positionを
publishして厳密なclock syncを実現すること、またそれをv1の正確性要件にすることは対象外である。Loopback遅延は
イベント受信時のposition開始とpause/seek時の再整合で扱い、フレームごとのpublishは非推奨とする。

### 11.8 Playback Topic Transport

`PlaybackTopicTransport`はDCC非依存の薄い境界として、既存のLink Clientを借用し、1つのRoom/Topicに
`ywta.common.playback.v1`だけをpublish/receiveする。Transport自身はClientをconnect、closeせず、Room参加や
Brokerのlifecycleも所有しない。生成元のowner threadだけがsubscribe、publish、frame処理、closeを呼び出す。

`subscribe`は冪等で、Clientのsubscribe成功後にだけactiveになる。失敗時は未購読のまま再試行できる。
`publish`はactive中の厳密なPlayback型だけを受理し、EnvelopeのschemaへPlayback schemaを設定し、bodyへ
`Playback.to_dict()`を渡す。返却されたtransport `message_id`は空でない文字列でなければならない。

受信側はtype=`publish`かつbound Room/TopicのFrameだけを処理し、それ以外を無視する。対象Frameはschema一致、
空のraw body、JSON object bodyを必須とし、Playbackへ厳密にdecodeしてから`PlaybackController.apply_remote`へ
Envelopeのsenderをoriginとして渡す。Transportはself-originを先に捨てず、Controllerのloopback規則へ委譲する。
Envelopeの`message_id`はtrace専用であり、Playbackの`change_id`の代用にしてはならない。

`close`はactiveならunsubscribe成功後にだけclosedへ遷移する。unsubscribe失敗時はactive・未closedを保持して
再試行可能とし、借用Client自体をcloseしない。未購読状態のcloseは安全に完了し、二回目以降は冪等に無操作とする。
同じClient上の同一Room/Topicは一つのPlayback Transportだけが排他的に所有し、close成功後にleaseを解放する。
unsubscribe失敗中のleaseは保持し、別Transportによる購読解除との競合を防ぐ。

### 11.8.1 Authority Handoff Transport

`AuthorityHandoffTransport`は既存Clientと`AuthorityHandoffTracker`を借用し、Room内の
`sync/<session_id>/control`だけを購読する。Transport自身はClient、Room、Brokerのlifecycleを所有せず、
生成元のowner threadだけがsubscribe、Request、Frame処理、accept/reject、closeを呼び出す。Playback Topic
Transportと同じClientを共有できるが、control topicのleaseは別に管理する。

`request_handoff`はRequest Envelopeの`message_id`を送信前に確定し、同じIDでTrackerへlocal pendingを登録してから、
type=`request`、`target=current_authority`、schema=`ywta.sync.authority.request.v1`で送信する。Clientは予約済み
`message_id`を受け付ける。現在AuthorityがRequestを受信しても、Transportはpending登録だけを行い、acceptまたは
rejectを自動実行してはならない。呼び出し側が明示的にaccept/rejectを選択する。

acceptはTrackerの既存handoffを検証・適用した後、同じAccepted payload/schemaをtype=`response`、
`target=next_authority`、`correlation_id=request_message_id`で先に返し、その後type=`publish`、control topic、
同じ`correlation_id`でfan-outする。rejectはtype=`response`のRejectedだけを返し、fan-outしない。Requesterの
Authority stateはAccepted target responseでは変更せず、Accepted control publishの検証・適用だけで変更する。
受信FrameはRoom、control topic、schema、type、sender、target、correlation、Session、payload bodyをfail closedで
検証し、raw binary bodyを拒否する。Client例外はTransport固有の型付き例外へ変換する。closeは冪等で、unsubscribe
失敗時はactive/openを保持して再試行可能にする。pendingまたはAuthority stateを変更した後のRequest、Response、
Publish I/O失敗はTransportをterminal failedへ固定し、failed後はcloseだけをunsubscribe再試行とlease解放のために
許可する。送信前検証またはTracker検証の失敗は、partial mutationがない限りfailedへ遷移させない。

Playback Sync runtimeはAuthority transport、Playback transport、Playback Controller、handoff Coordinatorを同じClient、
Tracker、dispatchへ束ねて所有する。構成時はHostから初期Baselineを一度だけ取得し、Host callbackをCoordinatorへ接続した後に
Lifecycleへ渡す。開始時はcontrol topic、Playback topic、dispatchの順に起動し、pumpでは各FrameをCoordinatorへ先に渡し、
未処理FrameだけをPlayback transportへ渡す。各pumpのdrain後（0件を含む）はCoordinatorのhandoff timeoutを確認し、期限切れまたは
Coordinator FailedならruntimeもFailedへ遷移する。終了時はCoordinatorを先に閉じ、両transportのunsubscribeを確認してから
dispatchとControllerを終了する。いずれかのunsubscribe失敗時はCoordinatorが閉じた状態でもdispatchとControllerを保持し、
closeを再試行できる状態に残す。

### 11.9 MessageとCLI

Session制御は通常の`publish`、`request`、`response`を使い、Payload schemaとして少なくとも次を定義する。

- `ywta.sync.contract.proposed.v1`
- `ywta.sync.contract.accepted.v1`
- `ywta.sync.contract.rejected.v1`
- `ywta.sync.authority.request.v1`
- `ywta.sync.authority.accepted.v1`
- `ywta.sync.authority.rejected.v1`
- `ywta.sync.preview.v1`
- `ywta.sync.commit.v1`
- `ywta.sync.cancel.v1`
- `ywta.sync.close.v1`

CLIはSessionの開始、一覧、検査、終了を提供する。v1のContract形式はJSONに限定し、YAML parserなどの
追加依存を要求しない。頻用Contractのpreset化は任意機能とする。

## 12. MaterialとTextureの同期境界

### 12.1 Material

各DCCのShader Graphを正本にしない。共通のversioned Material Specが意味情報を保持し、
各DCC Adapterが自分のMaterial表現へ投影する。

共通候補は次のとおり。

- 安定した `material_id`
- shader modelまたはprofile
- scalar、vector、color parameter
- Texture slot semantic
- source pathまたはAsset identity
- color space
- channel packing
- UV set、tiling、UDIM情報
- revision、origin、change ID
- DCC固有拡張

v1ではMetallic-Roughness PBRなど明示的に対応した共通部分だけを同期する。非対応Fieldを黙って
近似または削除してはならず、Adapterは `exact`、`approximated`、`unsupported` を区別することを推奨する。

### 12.2 TextureとPhotoshop Layer

PhotoshopがPSDとLayer構造の正本を所有する。Blender、Maya、UnityはTexture slotと出力結果を所有する。
Layer Treeそのものを双方向同期せず、次を連携する。

- 必要なTexture semanticの要求
- Photoshop側のGroup/template生成
- Texture export要求と結果
- Texture Set revision更新
- DCC側のTexture reload結果

### 12.3 同期Loop防止

変更Messageは `origin`、`revision`、`message_id` または同等のchange IDを持つ。Clientは自分が適用した
同一変更を新規変更として再Publishしてはならない。

## 13. ThreadingとDCC安全性

- Network callbackからDCC APIを直接呼び出してはならない。
- Client SDKは受信Messageをqueueへ積み、各DCCのMain Thread dispatch機構で実行する。
- 共通Adapterは`Client.receive(timeout=None)`を専用のbackground receiver threadからだけ呼び出し、Frameを有界queueへ順序どおり積む。
  Clientのblocking readは`stop`時の`Client.close`で解除する。Adapter側でread timeoutをpollingし、送信と同じsocketの
  timeout設定を変更してはならない。`TimeoutError`を正常なpollとして無視せずreceiver errorとして観測可能にする。
- Host API callbackはreceiver threadから呼び出してはならない。Host Main Threadが明示的に`drain(handler, max_items)`を実行し、
  queueから取り出したFrameを適用する。Adapter生成元のHost thread以外からの`drain`は拒否する。
- queueは固定上限を持たなければならない。満杯になった場合はFrameを暗黙にdropせず、overflowを記録してreceiverを停止するfail-closedとする。
- `start`はone-shotであり、clean stop後の再startを行わない。`stop`はidempotentで有限timeoutだけ待機する。
  receiverのdisconnect/errorとoverflowは例外本体やtracebackを保持せず、型名と上限付きmessageなどの軽量statusから観測できなければならない。
- Host handlerの例外はreceiver threadへ伝播させず、対象Frameを有界なfailed slotへ隔離する。その`drain`の後続Frameは処理せず、
  Main Threadだけが`take_failed()`で明示回収する。Adapterはfailed Frameを自動retryしてはならず、rollbackやidentity再検証はHost側が判断する。
- Sync SessionをCloseしたAdapterは停止後にpending queueとfailed slotを破棄できる。Sessionをまたいでpending Frameを再利用してはならない。
- Scene、Document、Projectを変更するCommandは、Adapter側で対象identityと現在状態を再検証する。
- Message受信だけを理由に、未保存Sceneの破棄、Document置換、Application終了を行ってはならない。
- Command失敗を成功として応答してはならない。
- 部分適用が危険な操作は、DCCのUndoまたはtransaction境界を使用してfail closedに処理する。

## 14. Security

YWTA Link v1は同じWindows user session内の信頼された制作Tool連携を対象とする。悪意ある同一User
Processに対する完全なsecurity boundaryは提供しない。

それでも次を必須とする。

- loopback以外へbindしない。
- 任意コード、shell command、任意module importをMessageから実行しない。
- Sync Contractから任意Schema、式、Script、未登録mapping profileを実行しない。
- Capability allowlist外のCommandを拒否する。
- Message size、文字列長、配列数、Binary length、queue数へ上限を設ける。
- Pathを扱う場合はAdapterの許可rootとcanonical pathを検証する。
- Binary構造をDCC APIへ渡す前にbounds、offset、stride、countを検証する。
- 未知Schemaを暗黙に適用しない。

破壊的または外部書き込みを伴うCommandは、Adapter設定またはDCC UIによる明示許可を要求できる。

## 15. Compatibility

- ProtocolとPayload schemaは個別にversion管理する。
- v1 Clientは接続時に対応Protocol versionを広告する。
- 共通Versionがない場合、Brokerは接続を拒否して理由を返す。
- 共通Envelope、および個別schemaが明示的に拡張可能としたobjectの互換追加Fieldは、受信側が無視できるようにする。
  Common schemaの固定top-level Fieldを追加する場合は、同じversionへ追加せずschema versionを上げる。
- 必須Field削除、型変更、意味変更は新しいschema versionを必要とする。
- Optional機能はCapability negotiationを使い、全Clientへ実装を強制しない。

## 16. Observability

Brokerは上限付きEvent ring bufferへ次を記録する。

- Broker起動と終了理由
- Peer join/leave
- Room join/leave
- Capability一覧
- Routing結果
- Request開始、成功、失敗、timeout
- Sync Sessionの状態遷移、Authority変更、Commit、Cancel、Close理由
- Binary転送のschema、size、所要時間、失敗理由
- Protocol違反と切断理由

既定LogへMaterial parameterやBinary本文を記録してはならない。CLI Monitorはこの診断情報を
表示するが、永続Chat historyにはしない。

## 17. 検証要件

### 17.1 Protocol contract

- 全言語Clientが同一のGolden JSON fixtureをencode/decodeできる。
- Header/Binary framingのGolden byte fixtureが一致する。
- 未知Field、未知Capability、非対応Versionを規定どおり処理する。
- malformed JSON、不正長、overflow、途中切断をfail closedで拒否する。

### 17.2 Broker

- 複数Client同時起動でもBrokerが1Processだけ起動する。
- Room broadcast、Topic publish、Target sendが混線しない。
- Request/Response correlationが正しい。
- 切断PeerへMessageを配送済み扱いしない。
- 最後のClient切断後にidle timeoutで終了する。
- Broker再起動後にClientが再接続、再参加、再購読する。
- 遅いConsumerへbackpressureを適用し、Broker memoryを無制限に増加させない。

### 17.3 Installと探索

- PATHと環境変数を設定していない新規User profileへInstallできる。
- 管理者権限なしでInstall、起動、更新、Uninstallできる。
- 複数Clientの同時bootstrapでもVersion directoryと `current.json` が破損しない。
- artifact hash不一致、欠落、非互換Versionをfail closedで拒否する。
- 実行中Brokerを上書きせず、side-by-sideに新VersionをInstallできる。
- `YWTA_LINK_EXE` の有効、欠落、非互換ケースを規定どおり処理する。
- PATH fallbackなしでも全Production AdapterがBrokerを発見できる。
- 個別DCC Pluginの削除が共有Brokerを削除しない。
- 使用中BrokerのUninstallを既定で拒否する。

### 17.4 Binary

- 0 byte、小さいPayload、複数chunk、上限付近のPayloadを検証する。
- chunk欠落、重複、順序違反、長さ不一致を拒否する。
- Base64またはJSON数値配列へ変換せずbyte一致で往復する。
- 複数Consumerへの配送で内容が一致する。

### 17.5 Sync Contract

- Contract JSON fixtureを全言語Clientが同じ意味で検証する。
- DraftからClosedまたはFailedまで、許可された状態遷移だけを受理する。
- 必須CapabilityまたはBindingの不足時にActiveへ遷移しない。
- Authority以外の更新、古いrevision、二重Commitを拒否する。
- Previewをcoalesceしても最後の値が一致し、Commitが1つのUndo単位になる。
- Cancelと`revert-to-baseline`が開始時の値を復元する。
- Close後にBinding、Subscription、Baseline、revision cacheが残らない。
- Broker再起動後に古いSessionを暗黙再開しない。

### 17.6 DCC host

Pure unit testやmockだけで完了扱いにしない。少なくとも次の実Host smokeを個別に記録する。

- MayaとBlenderの自動Broker起動、相互Presence、再接続
- Photoshop UXPのlocalhost接続、Binary送受信、manifest permission
- Unity Editorの接続、Main Thread dispatch、Domain Reload後の再接続
- Substance Painter Plugin環境の接続とMain Thread dispatch
- BlenderをCamera Authority、MayaまたはUnityをTargetとしたPreview、Commit、Cancel、Close
- Morph Weightの明示Bindingと、非対応Channelの`unsupported`報告

未実行Hostは `not_run` として明示し、他Hostの成功で代替しない。

## 18. 実装Phase

### Phase 0: Transport feasibility

- Raw TCPとWebSocketの最小echoを各Hostで確認する。
- Photoshop UXP permission、Unity Domain Reload、Maya/Blender Main Thread dispatchを確認する。
- v1 Wire framingとGolden byte fixtureを確定する。
- ユーザー単位Install layout、artifact manifest、探索順序のfixtureを確定する。

完了条件: 各Hostの利用可能Transport表と、少なくともMaya、Blender、Photoshopで共通Messageを
往復できる根拠がある。

### Phase 1: Broker、CLI、Python Client

- Rust Brokerの自動起動、自動終了、Room、Peer、Topic、Target routingを実装する。
- CLI Monitorを実装する。
- 共通Python ClientでMayaとBlenderを接続する。
- `install --user`、side-by-side Update、探索、concurrent bootstrapを実装する。

完了条件: PATH設定のない新規User profileでMayaとBlenderがBrokerをbootstrapし、同じRoomへ自動参加して、
Presence、Publish、Target requestを実Hostで往復する。

### Phase 2: Inline Binary

- Raw binary body、chunk、backpressure、上限、schema検証を実装する。
- MayaとBlender間で標準形式のBinary fixtureを往復する。

完了条件: Binary fixtureがbyte一致し、途中切断、欠落chunk、遅いConsumerの回帰Testが通る。

### Phase 3: CommonとSync Contract基盤

- Entity Reference、Transform、Time、Camera、Morph WeightのSchemaとGolden fixtureを確定する。
- PlaybackのSchema、Golden fixture、single-writerの再生Sync Loop規則を確定する。
- Contract validation、Negotiation、状態遷移、Authority、Preview、Commit、Cancel、Closeを実装する。
- CLIへSessionの開始、一覧、検査、終了を追加する。

完了条件: PythonとRustで同じContract fixtureを解釈でき、Broker単体TestでSession lifecycle、競合拒否、
Broker再起動時のfail closedが成立し、Playbackのchange ID/echo抑止規則をAdapter契約として検証できる。

### Phase 4: Camera実証

- BlenderをAuthority、MayaとUnityをTargetとするCamera Adapterを実装する。
- Transform、Focal length、Aperture、Clipping rangeをPreview、Commit、Cancelする。
- DCC差を`exact`、`approximated`、`unsupported`で記録する。

完了条件: 同じContractからMayaとUnityへCameraを適用し、Previewの間引き、1回のUndo Commit、Cancel、
Session解体を実Hostで確認する。

### Phase 5: Morph Weight

- Blender Shape Key、Maya Blend Shape、Unity BlendShapeのChannel bindingを実装する。
- 現在Weightの一方向同期から開始し、名前不一致と非対応範囲を明示する。

完了条件: 明示BindingしたChannelだけが更新され、未Binding Channelを変更せず、CancelでBaselineへ戻る。

### Phase 6: Production Adapter拡張

- Photoshop Texture GeneratorとBlenderのTexture Set更新を接続する。
- Unity、Maya、Blender、Substance PainterのMaterial Spec Adapterを段階導入する。
- Skeleton bindingと補間の契約が固まった後にMotion Clip Adapterを導入する。

完了条件: Adapterごとの実Host smokeと、対応Fieldの`exact`、`approximated`、`unsupported`が記録される。

### Phase 7: Performance review

- 代表的なTexture、GLB、Material更新のsize、latency、allocation、Broker memoryを測定する。
- Camera PreviewとMorph Weight更新のlatency、coalesce数、Main Thread適用時間を測定する。
- Inline Binaryが要求を満たさない場合だけShared Memory拡張を設計する。

完了条件: Shared Memoryを追加するか、不要として据え置くかを実測値で判断できる。

## 19. 未確定事項

実装開始前またはPhase 0で次を確定する。

1. Raw TCPの固定Header byte layoutとWebSocket framingの対応
2. Message、chunk、queue、timeout、Event ring bufferの既定上限
3. Room IDを保存するProject manifestのFile名と配置
4. Rust crateの外部依存追加方針
5. Photoshop UXPでlocalhost WebSocketへ許可する正確なmanifest設定
6. Substance Painter Plugin環境で使用するTransportとMain Thread dispatch方法
7. Material Specを既存Projectから共有するか、YWTA Link用schemaとして新設するか
8. Broker artifact署名をv1必須にするか、同梱manifestのSHA-256検証をv1要件とするか
9. Cameraの既定Length unit、座標系、Film fit mapping profile
10. Sync SessionのContract保存場所と、CLIから開始する際のOwner identity
11. Preview rate limit、coalesce、Baseline保持量、Commit timeoutの既定上限
12. Session異常終了後にTarget AdapterがBaselineを保持する期限

未確定事項を暗黙の実装判断で固定せず、Protocol fixtureまたは本文書の改訂として記録する。
