//! loopback TCP Brokerと副作用を持たないrouting coreを提供する。

use std::collections::{HashMap, HashSet};
use std::error::Error;
use std::fmt;
use std::io;
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread;
use std::time::{Duration, Instant};

use crate::envelope::{Envelope, MessageType, MONITOR_SNAPSHOT_SCHEMA};
use crate::frame::{Frame, FrameError, FrameLimits};
use crate::presence::{PeerPresence, PresenceError, PEER_HELLO_SCHEMA};
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

const RUNTIME_CHALLENGE_FIELD: &str = "ywta_runtime_challenge";
const RUNTIME_TOKEN_FIELD: &str = "ywta_runtime_token";
const RUNTIME_BROKER_SENDER: &str = "ywta-link:broker";
const MONITOR_PEER_PREFIX: &str = "ywta-link:monitor:";
const MONITOR_INCLUDE_PRESENCE_FIELD: &str = "ywta_include_presence";

/// Broker内で接続を区別する短命ID。
pub type ConnectionId = u64;

/// routing先と転送するframeを表す。
#[derive(Clone, Debug, PartialEq)]
pub struct Delivery {
    pub peer_id: String,
    pub frame: Frame,
}

/// CLI Monitorが取得するBrokerの接続状態。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BrokerSnapshot {
    pub protocol_version: u16,
    pub endpoint: String,
    pub pid: u32,
    pub peers: Vec<String>,
    /// Presenceを広告したPeerだけをPeer ID順で収録する。
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub presence: Vec<PeerPresence>,
    pub rooms: Vec<RoomSnapshot>,
}

/// Monitorへ返すRoomの一貫した状態。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct RoomSnapshot {
    pub room: String,
    pub members: Vec<String>,
    pub subscriptions: Vec<SubscriptionSnapshot>,
}

/// Monitorへ返すTopic subscriptionの状態。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct SubscriptionSnapshot {
    pub topic: String,
    pub members: Vec<String>,
}

/// Brokerがfail closedで返す失敗理由。
#[derive(Debug)]
pub enum BrokerError {
    InvalidBindAddress(SocketAddr),
    Frame(FrameError),
    HelloRequired,
    DuplicateHello,
    SenderSpoofing,
    DuplicatePeerId(String),
    NotInRoom(String),
    TargetNotConnected(String),
    DuplicatePendingRequest(String),
    UnknownCorrelationId(String),
    ResponseSenderMismatch(String),
    ResponseTargetMismatch(String),
    ResponseRoomMismatch(String),
    MonitorNotAllowed,
    InvalidMonitorRequest,
    MonitorSerialization(serde_json::Error),
    InvalidPresence(PresenceError),
    Io(io::Error),
}

impl fmt::Display for BrokerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidBindAddress(address) => {
                write!(formatter, "bind address must be loopback: {address}")
            }
            Self::Frame(error) => write!(formatter, "invalid frame: {error}"),
            Self::HelloRequired => formatter.write_str("hello must be the first message"),
            Self::DuplicateHello => formatter.write_str("hello may be sent only once"),
            Self::SenderSpoofing => formatter.write_str("sender differs from hello identity"),
            Self::DuplicatePeerId(peer_id) => {
                write!(formatter, "peer is already active: {peer_id}")
            }
            Self::NotInRoom(room) => write!(formatter, "peer has not joined room: {room}"),
            Self::TargetNotConnected(peer_id) => {
                write!(formatter, "target is not connected: {peer_id}")
            }
            Self::DuplicatePendingRequest(message_id) => {
                write!(
                    formatter,
                    "request message_id is already pending: {message_id}"
                )
            }
            Self::UnknownCorrelationId(correlation_id) => {
                write!(
                    formatter,
                    "correlation_id has no pending request: {correlation_id}"
                )
            }
            Self::ResponseSenderMismatch(correlation_id) => {
                write!(
                    formatter,
                    "response sender does not own request: {correlation_id}"
                )
            }
            Self::ResponseTargetMismatch(correlation_id) => {
                write!(
                    formatter,
                    "response target does not own request: {correlation_id}"
                )
            }
            Self::ResponseRoomMismatch(correlation_id) => {
                write!(
                    formatter,
                    "response room differs from request: {correlation_id}"
                )
            }
            Self::MonitorNotAllowed => {
                formatter.write_str("monitor snapshot is restricted to monitor peers")
            }
            Self::InvalidMonitorRequest => formatter.write_str("invalid monitor snapshot request"),
            Self::MonitorSerialization(error) => {
                write!(formatter, "cannot encode monitor snapshot: {error}")
            }
            Self::InvalidPresence(error) => write!(formatter, "invalid peer presence: {error}"),
            Self::Io(error) => write!(formatter, "broker I/O error: {error}"),
        }
    }
}

impl Error for BrokerError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Frame(error) => Some(error),
            Self::MonitorSerialization(error) => Some(error),
            Self::InvalidPresence(error) => Some(error),
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}

impl From<FrameError> for BrokerError {
    fn from(error: FrameError) -> Self {
        Self::Frame(error)
    }
}

impl From<PresenceError> for BrokerError {
    fn from(error: PresenceError) -> Self {
        Self::InvalidPresence(error)
    }
}

/// 接続状態を持たないrouting core。ネットワークなしで検証できる。
#[derive(Debug, Default)]
pub struct BrokerCore {
    connection_peers: HashMap<ConnectionId, String>,
    peer_connections: HashMap<String, ConnectionId>,
    peer_presence: HashMap<String, PeerPresence>,
    monitor_connections: HashSet<ConnectionId>,
    rooms: HashMap<String, HashSet<String>>,
    subscriptions: HashMap<(String, String), HashSet<String>>,
    pending_requests: HashMap<String, PendingRequest>,
}

#[derive(Debug)]
struct PendingRequest {
    requester: String,
    target: String,
    room: String,
}

impl BrokerCore {
    /// 接続からのframeを検証し、配送対象だけを返す。
    pub fn receive(
        &mut self,
        connection_id: ConnectionId,
        frame: Frame,
    ) -> Result<Vec<Delivery>, BrokerError> {
        self.receive_with_monitor_authorization(connection_id, frame, false)
    }

    /// Server側でruntime challengeを検証済みのHelloを受け付ける。
    pub fn receive_with_monitor_authorization(
        &mut self,
        connection_id: ConnectionId,
        frame: Frame,
        monitor_authorized: bool,
    ) -> Result<Vec<Delivery>, BrokerError> {
        frame.envelope.validate().map_err(FrameError::from)?;
        let peer_id = match self.connection_peers.get(&connection_id) {
            Some(peer_id) => peer_id.clone(),
            None => return self.register_hello(connection_id, frame, monitor_authorized),
        };
        if matches!(frame.envelope.message_type, MessageType::Hello) {
            return Err(BrokerError::DuplicateHello);
        }
        if frame.envelope.sender != peer_id {
            return Err(BrokerError::SenderSpoofing);
        }

        if self.monitor_connections.contains(&connection_id)
            && !matches!(
                frame.envelope.message_type,
                MessageType::MonitorSnapshotRequest
            )
        {
            return Err(BrokerError::MonitorNotAllowed);
        }

        match frame.envelope.message_type {
            MessageType::Join => {
                let room = required_room(&frame)?;
                self.rooms.entry(room).or_default().insert(peer_id);
                Ok(Vec::new())
            }
            MessageType::Leave => {
                let room = required_room(&frame)?;
                self.remove_from_room(&peer_id, &room);
                Ok(Vec::new())
            }
            MessageType::Subscribe => {
                let room = required_room(&frame)?;
                self.require_room_member(&peer_id, &room)?;
                let topic = required_topic(&frame)?;
                self.subscriptions
                    .entry((room, topic))
                    .or_default()
                    .insert(peer_id);
                Ok(Vec::new())
            }
            MessageType::Unsubscribe => {
                let room = required_room(&frame)?;
                let topic = required_topic(&frame)?;
                self.remove_subscription(&peer_id, &room, &topic);
                Ok(Vec::new())
            }
            MessageType::Publish => self.route_publish(&peer_id, frame),
            MessageType::Request => self.route_request(&peer_id, frame),
            MessageType::Response | MessageType::Error => self.route_response(&peer_id, frame),
            MessageType::Ping
            | MessageType::Pong
            | MessageType::BinaryBegin
            | MessageType::BinaryChunk
            | MessageType::BinaryEnd => Ok(Vec::new()),
            MessageType::MonitorSnapshotRequest => {
                if !self.monitor_connections.contains(&connection_id) {
                    return Err(BrokerError::MonitorNotAllowed);
                }
                if frame.envelope.schema.as_deref() != Some(MONITOR_SNAPSHOT_SCHEMA)
                    || frame.envelope.room.is_some()
                    || frame.envelope.target.is_some()
                    || frame.envelope.topic.is_some()
                    || frame.envelope.correlation_id.is_some()
                    || frame.envelope.body.is_some()
                    || !frame.body.is_empty()
                    || frame
                        .envelope
                        .extra
                        .get(MONITOR_INCLUDE_PRESENCE_FIELD)
                        .is_some_and(|value| !value.is_boolean())
                {
                    return Err(BrokerError::InvalidMonitorRequest);
                }
                Ok(Vec::new())
            }
            MessageType::MonitorSnapshotResponse => Err(BrokerError::InvalidMonitorRequest),
            MessageType::Hello => Err(BrokerError::DuplicateHello),
        }
    }

    /// 切断したPeerのRoomとTopic状態をすべて解放する。
    pub fn disconnect(&mut self, connection_id: ConnectionId) {
        let Some(peer_id) = self.connection_peers.remove(&connection_id) else {
            return;
        };
        self.monitor_connections.remove(&connection_id);
        self.peer_connections.remove(&peer_id);
        self.peer_presence.remove(&peer_id);
        self.rooms.retain(|_, members| {
            members.remove(&peer_id);
            !members.is_empty()
        });
        self.subscriptions.retain(|_, members| {
            members.remove(&peer_id);
            !members.is_empty()
        });
        self.pending_requests
            .retain(|_, pending| pending.requester != peer_id && pending.target != peer_id);
    }

    /// Peer IDに対応する接続IDを返す。
    pub fn connection_id_for_peer(&self, peer_id: &str) -> Option<ConnectionId> {
        self.peer_connections.get(peer_id).copied()
    }

    /// Peer IDに対応するPresence広告を読み取り専用で返す。
    pub fn presence_for_peer(&self, peer_id: &str) -> Option<&PeerPresence> {
        self.peer_presence.get(peer_id)
    }

    /// 現在登録されているPresence広告をPeer ID順のSnapshotで返す。
    pub fn presence_snapshot(&self) -> Vec<PeerPresence> {
        let mut presences = self.peer_presence.values().cloned().collect::<Vec<_>>();
        presences.sort_by(|left, right| left.peer_id.cmp(&right.peer_id));
        presences
    }

    /// 現在登録されているPeer数を返す。
    pub fn peer_count(&self) -> usize {
        self.peer_connections.len()
    }

    /// 接続がhelloを完了済みかを返す。
    pub fn is_registered(&self, connection_id: ConnectionId) -> bool {
        self.connection_peers.contains_key(&connection_id)
    }

    /// 接続がMonitor roleとして認証済みかを返す。
    pub fn is_monitor_connection(&self, connection_id: ConnectionId) -> bool {
        self.monitor_connections.contains(&connection_id)
    }

    /// 未解決Request数を返す。
    pub fn pending_request_count(&self) -> usize {
        self.pending_requests.len()
    }

    /// Monitor用に接続中Peer、Room、Subscriptionを辞書順でSnapshot化する。
    pub fn snapshot(&self) -> (Vec<String>, Vec<RoomSnapshot>) {
        let mut peers = self
            .peer_connections
            .keys()
            .filter(|peer_id| !is_monitor_peer(peer_id))
            .cloned()
            .collect::<Vec<_>>();
        peers.sort();

        let mut rooms = self
            .rooms
            .iter()
            .map(|(room, members)| {
                let mut members = members
                    .iter()
                    .filter(|peer_id| !is_monitor_peer(peer_id))
                    .cloned()
                    .collect::<Vec<_>>();
                members.sort();
                let mut subscriptions = self
                    .subscriptions
                    .iter()
                    .filter_map(|((subscription_room, topic), members)| {
                        if subscription_room != room {
                            return None;
                        }
                        let mut members = members
                            .iter()
                            .filter(|peer_id| !is_monitor_peer(peer_id))
                            .cloned()
                            .collect::<Vec<_>>();
                        members.sort();
                        (!members.is_empty()).then_some(SubscriptionSnapshot {
                            topic: topic.clone(),
                            members,
                        })
                    })
                    .collect::<Vec<_>>();
                subscriptions.sort_by(|left, right| left.topic.cmp(&right.topic));
                RoomSnapshot {
                    room: room.clone(),
                    members,
                    subscriptions,
                }
            })
            .filter(|room| !room.members.is_empty())
            .collect::<Vec<_>>();
        rooms.sort_by(|left, right| left.room.cmp(&right.room));
        (peers, rooms)
    }

    fn register_hello(
        &mut self,
        connection_id: ConnectionId,
        frame: Frame,
        monitor_authorized: bool,
    ) -> Result<Vec<Delivery>, BrokerError> {
        if !matches!(frame.envelope.message_type, MessageType::Hello) {
            return Err(BrokerError::HelloRequired);
        }
        if is_monitor_peer(&frame.envelope.sender)
            && frame.envelope.schema.as_deref() == Some(PEER_HELLO_SCHEMA)
        {
            return Err(BrokerError::MonitorNotAllowed);
        }
        let presence = parse_peer_presence(&frame)?;
        let peer_id = frame.envelope.sender.clone();
        let monitor_reserved = is_monitor_peer(&peer_id);
        let monitor_peer = is_valid_monitor_peer(&peer_id);
        if monitor_reserved
            && (!monitor_peer || !monitor_authorized || !has_runtime_challenge(&frame))
        {
            return Err(BrokerError::MonitorNotAllowed);
        }
        if self.peer_connections.contains_key(&peer_id) {
            return Err(BrokerError::DuplicatePeerId(peer_id));
        }
        self.connection_peers.insert(connection_id, peer_id.clone());
        self.peer_connections.insert(peer_id.clone(), connection_id);
        if let Some(presence) = presence {
            self.peer_presence.insert(peer_id, presence);
        }
        if monitor_peer {
            self.monitor_connections.insert(connection_id);
        }
        Ok(Vec::new())
    }

    fn route_publish(&self, sender: &str, frame: Frame) -> Result<Vec<Delivery>, BrokerError> {
        let room = required_room(&frame)?;
        self.require_room_member(sender, &room)?;
        let peers = match &frame.envelope.topic {
            Some(topic) => self.subscriptions.get(&(room, topic.clone())),
            None => self.rooms.get(&room),
        };
        Ok(peers
            .into_iter()
            .flat_map(|peers| peers.iter())
            .filter(|peer_id| peer_id.as_str() != sender)
            .map(|peer_id| Delivery {
                peer_id: peer_id.clone(),
                frame: frame.clone(),
            })
            .collect())
    }

    fn route_request(&mut self, sender: &str, frame: Frame) -> Result<Vec<Delivery>, BrokerError> {
        let room = required_room(&frame)?;
        self.require_room_member(sender, &room)?;
        let target = required_target(&frame)?;
        if !self.peer_connections.contains_key(&target) {
            return Err(BrokerError::TargetNotConnected(target));
        }
        self.require_room_member(&target, &room)?;
        if self
            .pending_requests
            .contains_key(&frame.envelope.message_id)
        {
            return Err(BrokerError::DuplicatePendingRequest(
                frame.envelope.message_id.clone(),
            ));
        }
        self.pending_requests.insert(
            frame.envelope.message_id.clone(),
            PendingRequest {
                requester: sender.to_owned(),
                target: target.clone(),
                room,
            },
        );
        Ok(vec![Delivery {
            peer_id: target,
            frame,
        }])
    }

    fn route_response(&mut self, sender: &str, frame: Frame) -> Result<Vec<Delivery>, BrokerError> {
        let correlation_id = frame
            .envelope
            .correlation_id
            .as_ref()
            .expect("Envelope validation requires correlation_id")
            .clone();
        let pending = self
            .pending_requests
            .get(&correlation_id)
            .ok_or_else(|| BrokerError::UnknownCorrelationId(correlation_id.clone()))?;
        if sender != pending.target {
            return Err(BrokerError::ResponseSenderMismatch(correlation_id));
        }
        let target = required_target(&frame)?;
        if target != pending.requester {
            return Err(BrokerError::ResponseTargetMismatch(correlation_id));
        }
        let room = required_room(&frame)?;
        if room != pending.room {
            return Err(BrokerError::ResponseRoomMismatch(correlation_id));
        }
        self.require_room_member(sender, &room)?;
        self.require_room_member(&target, &room)?;
        self.pending_requests.remove(
            frame
                .envelope
                .correlation_id
                .as_deref()
                .expect("Envelope validation requires correlation_id"),
        );
        Ok(vec![Delivery {
            peer_id: target,
            frame,
        }])
    }

    fn require_room_member(&self, peer_id: &str, room: &str) -> Result<(), BrokerError> {
        if self
            .rooms
            .get(room)
            .is_some_and(|members| members.contains(peer_id))
        {
            Ok(())
        } else {
            Err(BrokerError::NotInRoom(room.to_owned()))
        }
    }

    fn remove_from_room(&mut self, peer_id: &str, room: &str) {
        if let Some(members) = self.rooms.get_mut(room) {
            members.remove(peer_id);
            if members.is_empty() {
                self.rooms.remove(room);
            }
        }
        self.subscriptions
            .retain(|(subscription_room, _), members| {
                if subscription_room == room {
                    members.remove(peer_id);
                }
                !members.is_empty()
            });
        self.pending_requests.retain(|_, pending| {
            pending.room != room || (pending.requester != peer_id && pending.target != peer_id)
        });
    }

    fn remove_subscription(&mut self, peer_id: &str, room: &str, topic: &str) {
        let key = (room.to_owned(), topic.to_owned());
        if let Some(members) = self.subscriptions.get_mut(&key) {
            members.remove(peer_id);
            if members.is_empty() {
                self.subscriptions.remove(&key);
            }
        }
    }
}

fn required_room(frame: &Frame) -> Result<String, BrokerError> {
    frame.envelope.room.clone().ok_or_else(|| {
        BrokerError::Frame(FrameError::from(crate::envelope::EnvelopeError::new(
            "room is required",
        )))
    })
}

fn parse_peer_presence(frame: &Frame) -> Result<Option<PeerPresence>, BrokerError> {
    match frame.envelope.schema.as_deref() {
        None if frame.envelope.body.is_none() && frame.body.is_empty() => Ok(None),
        Some(PEER_HELLO_SCHEMA) => {
            if !frame.body.is_empty() {
                return Err(BrokerError::InvalidPresence(PresenceError::new(
                    "peer hello presence must not have a raw binary body",
                )));
            }
            let body = frame.envelope.body.as_ref().ok_or_else(|| {
                BrokerError::InvalidPresence(PresenceError::new(
                    "peer hello presence body is required",
                ))
            })?;
            let presence = PeerPresence::from_value(body)?;
            if presence.peer_id != frame.envelope.sender {
                return Err(BrokerError::InvalidPresence(PresenceError::new(
                    "peer hello peer_id must match envelope sender",
                )));
            }
            Ok(Some(presence))
        }
        // Helloの未定義metadataは、Presenceとして解釈せず既存のlegacy接続を保つ。
        // Presenceを名乗るschemaだけは上の厳格なdecodeを通る。
        _ => Ok(None),
    }
}

fn is_monitor_peer(peer_id: &str) -> bool {
    peer_id.starts_with(MONITOR_PEER_PREFIX)
}

fn is_valid_monitor_peer(peer_id: &str) -> bool {
    peer_id
        .strip_prefix(MONITOR_PEER_PREFIX)
        .is_some_and(|suffix| !suffix.is_empty())
}

fn has_runtime_challenge(frame: &Frame) -> bool {
    matches!(frame.envelope.message_type, MessageType::Hello)
        && frame
            .envelope
            .extra
            .get(RUNTIME_CHALLENGE_FIELD)
            .and_then(Value::as_str)
            .is_some_and(|challenge| !challenge.is_empty())
}

fn monitor_request_includes_presence(frame: &Frame) -> bool {
    frame
        .envelope
        .extra
        .get(MONITOR_INCLUDE_PRESENCE_FIELD)
        .and_then(Value::as_bool)
        .unwrap_or(false)
}

fn required_topic(frame: &Frame) -> Result<String, BrokerError> {
    frame.envelope.topic.clone().ok_or_else(|| {
        BrokerError::Frame(FrameError::from(crate::envelope::EnvelopeError::new(
            "topic is required",
        )))
    })
}

fn required_target(frame: &Frame) -> Result<String, BrokerError> {
    frame.envelope.target.clone().ok_or_else(|| {
        BrokerError::Frame(FrameError::from(crate::envelope::EnvelopeError::new(
            "target is required",
        )))
    })
}

/// TCP Brokerのbind先とidle終了設定。
#[derive(Clone, Copy, Debug)]
pub struct BrokerConfig {
    pub bind_addr: SocketAddr,
    pub idle_timeout: Duration,
    pub handshake_timeout: Duration,
    pub frame_limits: FrameLimits,
}

impl Default for BrokerConfig {
    fn default() -> Self {
        Self {
            bind_addr: "127.0.0.1:0"
                .parse()
                .expect("default loopback address must parse"),
            idle_timeout: Duration::from_secs(30),
            handshake_timeout: Duration::from_secs(5),
            frame_limits: FrameLimits::default(),
        }
    }
}

/// 指定されたbind先がloopbackだけかを検証する。
pub fn validate_bind_address(bind_addr: SocketAddr) -> Result<(), BrokerError> {
    if bind_addr.ip().is_loopback() {
        Ok(())
    } else {
        Err(BrokerError::InvalidBindAddress(bind_addr))
    }
}

/// 1つのloopback TCP listenerとrouting coreを所有するBroker。
pub struct BrokerServer {
    listener: TcpListener,
    config: BrokerConfig,
    core: BrokerCore,
    event_sender: Sender<NetworkEvent>,
    event_receiver: Receiver<NetworkEvent>,
    connections: HashMap<ConnectionId, NetworkConnection>,
    next_connection_id: ConnectionId,
    idle_since: Option<Instant>,
    runtime_token: Option<String>,
    monitor_connections: HashSet<ConnectionId>,
}

impl BrokerServer {
    /// loopbackだけへlistenerをbindする。
    pub fn bind(config: BrokerConfig) -> Result<Self, BrokerError> {
        validate_bind_address(config.bind_addr)?;
        let listener = TcpListener::bind(config.bind_addr).map_err(BrokerError::Io)?;
        listener.set_nonblocking(true).map_err(BrokerError::Io)?;
        let (event_sender, event_receiver) = mpsc::channel();
        Ok(Self {
            listener,
            config,
            core: BrokerCore::default(),
            event_sender,
            event_receiver,
            connections: HashMap::new(),
            next_connection_id: 1,
            // 0秒は、接続がない状態で直ちに終了するという従来の意味を保つ。
            idle_since: Some(Instant::now()),
            runtime_token: None,
            monitor_connections: HashSet::new(),
        })
    }

    /// 実際に割り当てられたloopback endpointを返す。
    pub fn local_addr(&self) -> Result<SocketAddr, BrokerError> {
        self.listener.local_addr().map_err(BrokerError::Io)
    }

    /// runtime manifestを所有するBrokerだけのinstance tokenを設定する。
    pub fn set_runtime_token(&mut self, token: String) {
        self.runtime_token = Some(token);
    }

    /// idle条件を満たすまでBroker event loopを実行する。
    pub fn run(&mut self) -> Result<(), BrokerError> {
        loop {
            self.accept_pending_connections()?;
            self.process_network_events();
            self.close_expired_handshakes_at(Instant::now());
            if self.should_shutdown() {
                return Ok(());
            }
            thread::sleep(Duration::from_millis(5));
        }
    }

    fn accept_pending_connections(&mut self) -> Result<(), BrokerError> {
        loop {
            match self.listener.accept() {
                Ok((stream, _)) => self.start_connection(stream)?,
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => return Ok(()),
                Err(error) => return Err(BrokerError::Io(error)),
            }
        }
    }

    fn start_connection(&mut self, stream: TcpStream) -> Result<(), BrokerError> {
        stream.set_nonblocking(false).map_err(BrokerError::Io)?;
        let connection_id = self.next_connection_id;
        self.next_connection_id += 1;
        let reader_stream = stream.try_clone().map_err(BrokerError::Io)?;
        let closer = stream.try_clone().map_err(BrokerError::Io)?;
        let (outgoing, outgoing_receiver) = mpsc::channel();
        let event_sender = self.event_sender.clone();
        let limits = self.config.frame_limits;
        spawn_writer(
            connection_id,
            stream,
            outgoing_receiver,
            event_sender.clone(),
            limits,
        );
        spawn_reader(connection_id, reader_stream, event_sender, limits);
        self.connections.insert(
            connection_id,
            NetworkConnection {
                outgoing,
                closer,
                accepted_at: Instant::now(),
            },
        );
        self.idle_since = None;
        Ok(())
    }

    fn process_network_events(&mut self) {
        while let Ok(event) = self.event_receiver.try_recv() {
            match event {
                NetworkEvent::Received {
                    connection_id,
                    frame,
                } if self.connections.contains_key(&connection_id) => {
                    let frame = *frame;
                    let runtime_ack = self.runtime_ack_for(&frame);
                    let monitor_hello_authorized = self.monitor_hello_is_authorized(&frame);
                    let is_monitor_request = matches!(
                        frame.envelope.message_type,
                        MessageType::MonitorSnapshotRequest
                    );
                    let monitor_request = is_monitor_request.then(|| {
                        (
                            frame.envelope.message_id.clone(),
                            monitor_request_includes_presence(&frame),
                        )
                    });
                    match self.core.receive_with_monitor_authorization(
                        connection_id,
                        frame,
                        monitor_hello_authorized,
                    ) {
                        Ok(deliveries) => {
                            if monitor_hello_authorized {
                                self.monitor_connections.insert(connection_id);
                            }
                            if let Some(ack) = runtime_ack {
                                self.send_to_connection(connection_id, ack);
                            }
                            if let Some((request_id, include_presence)) = monitor_request {
                                match self.monitor_snapshot_response(
                                    connection_id,
                                    &request_id,
                                    include_presence,
                                ) {
                                    Ok(response) => {
                                        self.send_to_connection(connection_id, response)
                                    }
                                    Err(_) => self.close_connection(connection_id),
                                }
                            }
                            self.dispatch(deliveries);
                        }
                        Err(_) => self.close_connection(connection_id),
                    }
                }
                NetworkEvent::Disconnected { connection_id } => {
                    self.close_connection(connection_id);
                }
                NetworkEvent::Received { .. } => {}
            }
        }
    }

    fn dispatch(&mut self, deliveries: Vec<Delivery>) {
        let mut failed_connections = Vec::new();
        for delivery in deliveries {
            let Some(connection_id) = self.core.connection_id_for_peer(&delivery.peer_id) else {
                continue;
            };
            let Some(connection) = self.connections.get(&connection_id) else {
                continue;
            };
            if connection.outgoing.send(delivery.frame).is_err() {
                failed_connections.push(connection_id);
            }
        }
        for connection_id in failed_connections {
            self.close_connection(connection_id);
        }
    }

    fn send_to_connection(&mut self, connection_id: ConnectionId, frame: Frame) {
        let failed = self
            .connections
            .get(&connection_id)
            .is_none_or(|connection| connection.outgoing.send(frame).is_err());
        if failed {
            self.close_connection(connection_id);
        }
    }

    fn monitor_snapshot_response(
        &self,
        connection_id: ConnectionId,
        request_id: &str,
        include_presence: bool,
    ) -> Result<Frame, BrokerError> {
        if !self.monitor_connections.contains(&connection_id)
            || !self.core.is_monitor_connection(connection_id)
        {
            return Err(BrokerError::MonitorNotAllowed);
        }
        let peer_id = self
            .core
            .connection_peers
            .get(&connection_id)
            .ok_or(BrokerError::MonitorNotAllowed)?;
        let (peers, rooms) = self.core.snapshot();
        let presence = if include_presence {
            self.core.presence_snapshot()
        } else {
            Vec::new()
        };
        let endpoint = self.local_addr()?.to_string();
        let snapshot = BrokerSnapshot {
            protocol_version: 1,
            endpoint,
            pid: std::process::id(),
            peers,
            presence,
            rooms,
        };
        let body = serde_json::to_value(snapshot).map_err(BrokerError::MonitorSerialization)?;
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: format!("broker-monitor-{request_id}"),
                message_type: MessageType::MonitorSnapshotResponse,
                sender: RUNTIME_BROKER_SENDER.to_owned(),
                room: None,
                target: Some(peer_id.clone()),
                topic: None,
                correlation_id: Some(request_id.to_owned()),
                schema: Some(MONITOR_SNAPSHOT_SCHEMA.to_owned()),
                body: Some(body),
                extra: Default::default(),
            },
            Vec::new(),
        )
        .map_err(BrokerError::Frame)
    }

    fn close_connection(&mut self, connection_id: ConnectionId) {
        let Some(connection) = self.connections.remove(&connection_id) else {
            return;
        };
        let _ = connection.closer.shutdown(Shutdown::Both);
        self.monitor_connections.remove(&connection_id);
        self.core.disconnect(connection_id);
        if self.connections.is_empty() {
            self.idle_since = Some(Instant::now());
        }
    }

    fn monitor_hello_is_authorized(&self, frame: &Frame) -> bool {
        self.runtime_token
            .as_deref()
            .is_some_and(|token| !token.is_empty())
            && is_valid_monitor_peer(&frame.envelope.sender)
            && has_runtime_challenge(frame)
    }

    fn close_expired_handshakes_at(&mut self, now: Instant) {
        let expired_connections = self
            .connections
            .iter()
            .filter_map(|(connection_id, connection)| {
                (!self.core.is_registered(*connection_id)
                    && now.saturating_duration_since(connection.accepted_at)
                        >= self.config.handshake_timeout)
                    .then_some(*connection_id)
            })
            .collect::<Vec<_>>();
        for connection_id in expired_connections {
            self.close_connection(connection_id);
        }
    }

    fn should_shutdown(&self) -> bool {
        self.connections.is_empty()
            && self
                .idle_since
                .is_some_and(|instant| instant.elapsed() >= self.config.idle_timeout)
    }

    fn runtime_ack_for(&self, frame: &Frame) -> Option<Frame> {
        if !matches!(frame.envelope.message_type, MessageType::Hello) {
            return None;
        }
        let challenge = frame
            .envelope
            .extra
            .get(RUNTIME_CHALLENGE_FIELD)
            .and_then(Value::as_str)
            .filter(|value| !value.is_empty())?;
        let token = self.runtime_token.as_ref()?;
        let mut extra = Map::new();
        extra.insert(
            RUNTIME_CHALLENGE_FIELD.to_owned(),
            Value::String(challenge.to_owned()),
        );
        extra.insert(RUNTIME_TOKEN_FIELD.to_owned(), Value::String(token.clone()));
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: format!("broker-ack-{}", frame.envelope.message_id),
                message_type: MessageType::Hello,
                sender: RUNTIME_BROKER_SENDER.to_owned(),
                room: None,
                target: None,
                topic: None,
                correlation_id: Some(frame.envelope.message_id.clone()),
                schema: None,
                body: None,
                extra,
            },
            Vec::new(),
        )
        .ok()
    }
}

struct NetworkConnection {
    outgoing: Sender<Frame>,
    closer: TcpStream,
    accepted_at: Instant,
}

enum NetworkEvent {
    Received {
        connection_id: ConnectionId,
        frame: Box<Frame>,
    },
    Disconnected {
        connection_id: ConnectionId,
    },
}

fn spawn_reader(
    connection_id: ConnectionId,
    mut stream: TcpStream,
    event_sender: Sender<NetworkEvent>,
    limits: FrameLimits,
) {
    thread::spawn(move || {
        while let Ok(frame) = Frame::read_from(&mut stream, limits) {
            if event_sender
                .send(NetworkEvent::Received {
                    connection_id,
                    frame: Box::new(frame),
                })
                .is_err()
            {
                return;
            }
        }
        let _ = event_sender.send(NetworkEvent::Disconnected { connection_id });
    });
}

fn spawn_writer(
    connection_id: ConnectionId,
    stream: TcpStream,
    receiver: Receiver<Frame>,
    event_sender: Sender<NetworkEvent>,
    limits: FrameLimits,
) {
    thread::spawn(move || {
        let mut stream = stream;
        writer_loop(connection_id, &mut stream, receiver, event_sender, limits);
    });
}

fn writer_loop(
    connection_id: ConnectionId,
    writer: &mut impl io::Write,
    receiver: Receiver<Frame>,
    event_sender: Sender<NetworkEvent>,
    limits: FrameLimits,
) {
    while let Ok(frame) = receiver.recv() {
        if frame.write_to(writer, limits).is_err() {
            let _ = event_sender.send(NetworkEvent::Disconnected { connection_id });
            return;
        }
    }
}

#[cfg(test)]
mod tests {
    use std::io;
    use std::net::{Ipv4Addr, SocketAddrV4};
    use std::sync::mpsc;

    use serde_json::json;

    use super::*;
    use crate::envelope::Envelope;

    fn frame(
        sender: &str,
        message_type: MessageType,
        room: Option<&str>,
        topic: Option<&str>,
        target: Option<&str>,
        body: &[u8],
    ) -> Frame {
        let message_id = format!("{sender}-{message_type:?}");
        frame_with_id(
            sender,
            &message_id,
            message_type,
            Routing {
                room,
                topic,
                target,
                correlation_id: None,
            },
            body,
        )
    }

    struct Routing<'a> {
        room: Option<&'a str>,
        topic: Option<&'a str>,
        target: Option<&'a str>,
        correlation_id: Option<&'a str>,
    }

    fn frame_with_id(
        sender: &str,
        message_id: &str,
        message_type: MessageType,
        routing: Routing<'_>,
        body: &[u8],
    ) -> Frame {
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: message_id.to_owned(),
                message_type,
                sender: sender.to_owned(),
                room: routing.room.map(str::to_owned),
                target: routing.target.map(str::to_owned),
                topic: routing.topic.map(str::to_owned),
                correlation_id: routing.correlation_id.map(str::to_owned),
                schema: Some("ywta.sync.preview.v1".to_owned()),
                body: Some(json!({ "revision": 1 })),
                extra: Default::default(),
            },
            body.to_vec(),
        )
        .expect("test frame must be valid")
    }

    fn request(sender: &str, message_id: &str, room: &str, target: &str) -> Frame {
        frame_with_id(
            sender,
            message_id,
            MessageType::Request,
            Routing {
                room: Some(room),
                topic: None,
                target: Some(target),
                correlation_id: None,
            },
            &[],
        )
    }

    fn response(
        sender: &str,
        message_id: &str,
        room: &str,
        target: &str,
        correlation_id: &str,
    ) -> Frame {
        frame_with_id(
            sender,
            message_id,
            MessageType::Response,
            Routing {
                room: Some(room),
                topic: None,
                target: Some(target),
                correlation_id: Some(correlation_id),
            },
            &[],
        )
    }

    fn hello(sender: &str) -> Frame {
        frame(sender, MessageType::Hello, None, None, None, &[])
    }

    fn presence_hello(sender: &str) -> Frame {
        let mut body: Value = serde_json::from_slice(include_bytes!(
            "../../../tests/link/fixtures/peer_hello_v1.json"
        ))
        .expect("presence fixture must decode");
        body.as_object_mut()
            .expect("presence fixture must be an object")
            .insert("peer_id".to_owned(), Value::String(sender.to_owned()));
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: format!("{sender}-presence-hello"),
                message_type: MessageType::Hello,
                sender: sender.to_owned(),
                room: None,
                target: None,
                topic: None,
                correlation_id: None,
                schema: Some(PEER_HELLO_SCHEMA.to_owned()),
                body: Some(body),
                extra: Default::default(),
            },
            Vec::new(),
        )
        .expect("presence hello must be valid")
    }

    fn monitor_hello(sender: &str, challenge: Option<&str>) -> Frame {
        let mut frame = hello(sender);
        if let Some(challenge) = challenge {
            frame.envelope.extra.insert(
                RUNTIME_CHALLENGE_FIELD.to_owned(),
                Value::String(challenge.to_owned()),
            );
        }
        frame
    }

    fn monitor_request(sender: &str) -> Frame {
        monitor_request_with_presence(sender, false)
    }

    fn monitor_request_with_presence(sender: &str, include_presence: bool) -> Frame {
        let mut extra = Map::new();
        if include_presence {
            extra.insert(MONITOR_INCLUDE_PRESENCE_FIELD.to_owned(), Value::Bool(true));
        }
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: format!("{sender}-monitor-request"),
                message_type: MessageType::MonitorSnapshotRequest,
                sender: sender.to_owned(),
                room: None,
                target: None,
                topic: None,
                correlation_id: None,
                schema: Some(MONITOR_SNAPSHOT_SCHEMA.to_owned()),
                body: None,
                extra,
            },
            Vec::new(),
        )
        .expect("monitor request must be valid")
    }

    fn join(sender: &str, room: &str) -> Frame {
        frame(sender, MessageType::Join, Some(room), None, None, &[])
    }

    fn subscribe(sender: &str, room: &str, topic: &str) -> Frame {
        frame(
            sender,
            MessageType::Subscribe,
            Some(room),
            Some(topic),
            None,
            &[],
        )
    }

    fn connect(core: &mut BrokerCore, connection_id: ConnectionId, peer_id: &str) {
        core.receive(connection_id, hello(peer_id))
            .expect("hello must register peer");
    }

    #[test]
    fn rejects_non_loopback_bind_address() {
        let bind_addr = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::UNSPECIFIED, 0));

        assert!(matches!(
            validate_bind_address(bind_addr),
            Err(BrokerError::InvalidBindAddress(_))
        ));
    }

    #[test]
    fn requires_hello_and_rejects_sender_spoofing() {
        let mut core = BrokerCore::default();

        assert!(matches!(
            core.receive(1, join("blender:one", "room-a")),
            Err(BrokerError::HelloRequired)
        ));
        connect(&mut core, 1, "blender:one");
        assert!(matches!(
            core.receive(1, join("maya:spoof", "room-a")),
            Err(BrokerError::SenderSpoofing)
        ));
    }

    #[test]
    fn monitor_role_requires_challenge_and_rejects_regular_routing() {
        let mut core = BrokerCore::default();
        let monitor_id = "ywta-link:monitor:one";
        assert!(matches!(
            core.receive(1, monitor_hello(monitor_id, Some("challenge"))),
            Err(BrokerError::MonitorNotAllowed)
        ));
        assert!(matches!(
            core.receive_with_monitor_authorization(
                1,
                monitor_hello("ywta-link:monitor:", Some("challenge")),
                true
            ),
            Err(BrokerError::MonitorNotAllowed)
        ));
        assert!(matches!(
            core.receive_with_monitor_authorization(1, monitor_hello(monitor_id, None), true),
            Err(BrokerError::MonitorNotAllowed)
        ));
        let mut monitor_presence = presence_hello(monitor_id);
        monitor_presence.envelope.extra.insert(
            RUNTIME_CHALLENGE_FIELD.to_owned(),
            Value::String("challenge".to_owned()),
        );
        assert!(matches!(
            core.receive_with_monitor_authorization(1, monitor_presence, true),
            Err(BrokerError::MonitorNotAllowed)
        ));
        assert!(!core.is_registered(1));

        core.receive_with_monitor_authorization(
            1,
            monitor_hello(monitor_id, Some("challenge")),
            true,
        )
        .expect("authenticated monitor must register");
        assert!(core.is_monitor_connection(1));
        core.receive(2, hello("maya:two"))
            .expect("regular peer must register");
        assert!(core.receive(1, monitor_request(monitor_id)).is_ok());
        let mut malformed_request = monitor_request(monitor_id);
        malformed_request.body = vec![1];
        assert!(matches!(
            core.receive(1, malformed_request),
            Err(BrokerError::InvalidMonitorRequest)
        ));
        let mut malformed_option = monitor_request(monitor_id);
        malformed_option.envelope.extra.insert(
            MONITOR_INCLUDE_PRESENCE_FIELD.to_owned(),
            Value::String("true".to_owned()),
        );
        assert!(matches!(
            core.receive(1, malformed_option),
            Err(BrokerError::InvalidMonitorRequest)
        ));
        assert!(matches!(
            core.receive(1, join(monitor_id, "room-a")),
            Err(BrokerError::MonitorNotAllowed)
        ));
        assert!(matches!(
            core.receive(2, monitor_request("maya:two")),
            Err(BrokerError::MonitorNotAllowed)
        ));
        core.disconnect(1);
        assert!(!core.is_monitor_connection(1));
    }

    #[test]
    fn server_requires_runtime_token_for_monitor_hello_authorization() {
        let mut server = BrokerServer::bind(BrokerConfig::default()).expect("server must bind");
        let monitor_id = "ywta-link:monitor:one";
        let monitor_frame = monitor_hello(monitor_id, Some("challenge"));
        assert!(!server.monitor_hello_is_authorized(&monitor_frame));

        server.set_runtime_token("runtime-token".to_owned());
        assert!(server.monitor_hello_is_authorized(&monitor_frame));
        assert!(!server.monitor_hello_is_authorized(&hello("maya:two")));
        assert!(!server.monitor_hello_is_authorized(&monitor_hello(monitor_id, None)));
        server.set_runtime_token(String::new());
        assert!(!server.monitor_hello_is_authorized(&monitor_frame));
    }

    #[test]
    fn rejects_duplicate_active_peer_id() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");

        assert!(matches!(
            core.receive(2, hello("blender:one")),
            Err(BrokerError::DuplicatePeerId(_))
        ));
    }

    #[test]
    fn registers_presence_and_cleans_it_on_disconnect() {
        let mut core = BrokerCore::default();
        core.receive(1, presence_hello("blender:peer-001"))
            .expect("presence hello must register");

        let presence = core
            .presence_for_peer("blender:peer-001")
            .expect("presence must be retained");
        assert_eq!(presence.application, "Blender");
        assert_eq!(core.presence_snapshot().len(), 1);

        assert!(matches!(
            core.receive(2, presence_hello("blender:peer-001")),
            Err(BrokerError::DuplicatePeerId(peer_id)) if peer_id == "blender:peer-001"
        ));
        core.disconnect(1);
        assert!(core.presence_for_peer("blender:peer-001").is_none());
        assert!(core.presence_snapshot().is_empty());
    }

    #[test]
    fn monitor_snapshot_presence_is_opt_in_and_old_response_is_decodable() {
        let mut server = BrokerServer::bind(BrokerConfig::default()).expect("server must bind");
        let monitor_id = "ywta-link:monitor:one";
        server
            .core
            .receive_with_monitor_authorization(
                1,
                monitor_hello(monitor_id, Some("challenge")),
                true,
            )
            .expect("monitor hello must register");
        server.monitor_connections.insert(1);
        server
            .core
            .receive(2, presence_hello("blender:peer-001"))
            .expect("presence peer must register");

        let old_request = monitor_request(monitor_id);
        server
            .core
            .receive(1, old_request)
            .expect("old monitor request must remain valid");
        let old_response = server
            .monitor_snapshot_response(1, "old", false)
            .expect("old response must encode");
        let old_body = old_response
            .envelope
            .body
            .expect("old response body must exist");
        assert!(
            old_body
                .as_object()
                .expect("old response must be an object")
                .get("presence")
                .is_none(),
            "old-style response must omit the additive presence field"
        );
        let old_snapshot: BrokerSnapshot =
            serde_json::from_value(old_body).expect("new monitor must decode old response");
        assert!(old_snapshot.presence.is_empty());

        let new_request = monitor_request_with_presence(monitor_id, true);
        server
            .core
            .receive(1, new_request)
            .expect("presence opt-in request must be valid");
        let new_response = server
            .monitor_snapshot_response(1, "new", true)
            .expect("new response must encode");
        let new_body = new_response
            .envelope
            .body
            .expect("new response body must exist");
        assert_eq!(new_body["presence"][0]["peer_id"], "blender:peer-001");
    }

    #[test]
    fn rejects_invalid_presence_before_registering_connection() {
        let mut unknown_field = presence_hello("blender:peer-001");
        unknown_field
            .envelope
            .body
            .as_mut()
            .expect("presence body must exist")
            .as_object_mut()
            .expect("presence body must be an object")
            .insert("unexpected".to_owned(), Value::Bool(true));
        assert!(matches!(
            core_receive_invalid_presence(unknown_field),
            Err(BrokerError::InvalidPresence(_))
        ));
    }

    fn core_receive_invalid_presence(frame: Frame) -> Result<Vec<Delivery>, BrokerError> {
        let mut core = BrokerCore::default();
        let result = core.receive(1, frame);
        assert!(!core.is_registered(1));
        assert!(core.presence_snapshot().is_empty());
        result
    }

    #[test]
    fn room_publish_is_isolated_and_keeps_binary_bytes() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        connect(&mut core, 3, "unity:three");
        for (connection_id, peer_id, room) in [
            (1, "blender:one", "room-a"),
            (2, "maya:two", "room-a"),
            (3, "unity:three", "room-b"),
        ] {
            core.receive(connection_id, join(peer_id, room))
                .expect("join must succeed");
        }

        let binary_body = [0, 1, 2, 255];
        let deliveries = core
            .receive(
                1,
                frame(
                    "blender:one",
                    MessageType::Publish,
                    Some("room-a"),
                    None,
                    None,
                    &binary_body,
                ),
            )
            .expect("publish must route");

        assert_eq!(deliveries.len(), 1);
        assert_eq!(deliveries[0].peer_id, "maya:two");
        assert_eq!(deliveries[0].frame.body, binary_body);
    }

    #[test]
    fn topic_publish_reaches_only_subscribers() {
        let mut core = BrokerCore::default();
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two"), (3, "unity:three")] {
            connect(&mut core, connection_id, peer_id);
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(2, subscribe("maya:two", "room-a", "camera"))
            .expect("subscription must succeed");

        let deliveries = core
            .receive(
                1,
                frame(
                    "blender:one",
                    MessageType::Publish,
                    Some("room-a"),
                    Some("camera"),
                    None,
                    &[],
                ),
            )
            .expect("topic publish must route");

        assert_eq!(deliveries.len(), 1);
        assert_eq!(deliveries[0].peer_id, "maya:two");
    }

    #[test]
    fn disconnect_removes_room_and_topic_membership() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two")] {
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(2, subscribe("maya:two", "room-a", "camera"))
            .expect("subscription must succeed");
        core.disconnect(2);

        let room_deliveries = core
            .receive(
                1,
                frame(
                    "blender:one",
                    MessageType::Publish,
                    Some("room-a"),
                    None,
                    None,
                    &[],
                ),
            )
            .expect("publish must route");
        let topic_deliveries = core
            .receive(
                1,
                frame(
                    "blender:one",
                    MessageType::Publish,
                    Some("room-a"),
                    Some("camera"),
                    None,
                    &[],
                ),
            )
            .expect("topic publish must route");

        assert!(room_deliveries.is_empty());
        assert!(topic_deliveries.is_empty());
        assert_eq!(core.peer_count(), 1);
    }

    #[test]
    fn target_routing_delivers_only_to_target() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        connect(&mut core, 3, "unity:three");
        for (connection_id, peer_id, room) in [
            (1, "blender:one", "room-a"),
            (2, "maya:two", "room-a"),
            (3, "unity:three", "room-b"),
        ] {
            core.receive(connection_id, join(peer_id, room))
                .expect("join must succeed");
        }

        let deliveries = core
            .receive(
                1,
                request("blender:one", "request-001", "room-a", "maya:two"),
            )
            .expect("target request must route");

        assert_eq!(deliveries.len(), 1);
        assert_eq!(deliveries[0].peer_id, "maya:two");
    }

    #[test]
    fn target_routing_rejects_cross_room_target() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "unity:three");
        core.receive(1, join("blender:one", "room-a"))
            .expect("join must succeed");
        core.receive(2, join("unity:three", "room-b"))
            .expect("join must succeed");

        assert!(matches!(
            core.receive(
                1,
                request("blender:one", "request-002", "room-a", "unity:three")
            ),
            Err(BrokerError::NotInRoom(room)) if room == "room-a"
        ));
    }

    #[test]
    fn response_routes_only_for_matching_pending_request() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two")] {
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(
            1,
            request("blender:one", "request-003", "room-a", "maya:two"),
        )
        .expect("request must route");
        assert!(matches!(
            core.receive(1, request("blender:one", "request-003", "room-a", "maya:two")),
            Err(BrokerError::DuplicatePendingRequest(message_id)) if message_id == "request-003"
        ));

        let deliveries = core
            .receive(
                2,
                response(
                    "maya:two",
                    "response-003",
                    "room-a",
                    "blender:one",
                    "request-003",
                ),
            )
            .expect("matching response must route");

        assert_eq!(deliveries.len(), 1);
        assert_eq!(deliveries[0].peer_id, "blender:one");
        assert_eq!(core.pending_request_count(), 0);
    }

    #[test]
    fn response_rejects_forged_or_unknown_correlation() {
        let mut core = BrokerCore::default();
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two"), (3, "unity:three")] {
            connect(&mut core, connection_id, peer_id);
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(
            1,
            request("blender:one", "request-004", "room-a", "maya:two"),
        )
        .expect("request must route");

        assert!(matches!(
            core.receive(
                3,
                response(
                    "unity:three",
                    "response-forged",
                    "room-a",
                    "blender:one",
                    "request-004",
                )
            ),
            Err(BrokerError::ResponseSenderMismatch(correlation_id)) if correlation_id == "request-004"
        ));
        assert!(matches!(
            core.receive(
                2,
                response(
                    "maya:two",
                    "response-unknown",
                    "room-a",
                    "blender:one",
                    "request-missing",
                )
            ),
            Err(BrokerError::UnknownCorrelationId(correlation_id)) if correlation_id == "request-missing"
        ));
    }

    #[test]
    fn disconnect_removes_pending_requests() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two")] {
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(
            1,
            request("blender:one", "request-005", "room-a", "maya:two"),
        )
        .expect("request must route");
        core.disconnect(2);

        assert_eq!(core.pending_request_count(), 0);
    }

    #[test]
    fn leaving_room_removes_related_pending_requests() {
        let mut core = BrokerCore::default();
        connect(&mut core, 1, "blender:one");
        connect(&mut core, 2, "maya:two");
        for (connection_id, peer_id) in [(1, "blender:one"), (2, "maya:two")] {
            core.receive(connection_id, join(peer_id, "room-a"))
                .expect("join must succeed");
        }
        core.receive(
            1,
            request("blender:one", "request-leave", "room-a", "maya:two"),
        )
        .expect("request must route");

        core.receive(
            2,
            frame(
                "maya:two",
                MessageType::Leave,
                Some("room-a"),
                None,
                None,
                &[],
            ),
        )
        .expect("leave must succeed");

        assert_eq!(core.pending_request_count(), 0);
    }

    #[test]
    fn handshake_timeout_closes_unregistered_connection_without_waiting() {
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            handshake_timeout: Duration::from_millis(10),
            ..BrokerConfig::default()
        };
        let mut server = BrokerServer::bind(config).expect("server must bind");
        let client = TcpStream::connect(server.local_addr().expect("address must resolve"))
            .expect("client must connect");
        server
            .accept_pending_connections()
            .expect("server must accept client");
        let connection_id = *server
            .connections
            .keys()
            .next()
            .expect("connection must be tracked");
        let now = Instant::now();
        server
            .connections
            .get_mut(&connection_id)
            .expect("connection must exist")
            .accepted_at = now
            .checked_sub(Duration::from_millis(11))
            .expect("instant must support test offset");

        server.close_expired_handshakes_at(now);

        assert!(server.connections.is_empty());
        assert!(!server.core.is_registered(connection_id));
        drop(client);
    }

    #[test]
    fn writer_loop_reports_disconnection_after_write_failure() {
        struct FailingWriter;

        impl io::Write for FailingWriter {
            fn write(&mut self, _: &[u8]) -> io::Result<usize> {
                Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "test write failure",
                ))
            }

            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }

        let (sender, receiver) = mpsc::channel();
        sender
            .send(hello("blender:one"))
            .expect("send must succeed");
        drop(sender);
        let (event_sender, event_receiver) = mpsc::channel();
        let mut writer = FailingWriter;

        writer_loop(
            42,
            &mut writer,
            receiver,
            event_sender,
            FrameLimits::default(),
        );

        assert!(matches!(
            event_receiver.recv_timeout(Duration::from_secs(1)),
            Ok(NetworkEvent::Disconnected { connection_id: 42 })
        ));
    }

    #[test]
    fn runtime_hello_ack_echoes_challenge_and_instance_token() {
        let mut server = BrokerServer::bind(BrokerConfig::default()).expect("server must bind");
        server.set_runtime_token("runtime-token-001".to_owned());
        let mut client_hello = hello("blender:one");
        client_hello
            .envelope
            .extra
            .insert(RUNTIME_CHALLENGE_FIELD.to_owned(), json!("challenge-001"));

        let acknowledgement = server
            .runtime_ack_for(&client_hello)
            .expect("runtime hello must receive an acknowledgement");

        assert_eq!(acknowledgement.envelope.message_type, MessageType::Hello);
        assert_eq!(acknowledgement.envelope.sender, RUNTIME_BROKER_SENDER);
        assert_eq!(
            acknowledgement.envelope.correlation_id.as_deref(),
            Some(client_hello.envelope.message_id.as_str())
        );
        assert_eq!(
            acknowledgement.envelope.extra.get(RUNTIME_CHALLENGE_FIELD),
            Some(&json!("challenge-001"))
        );
        assert_eq!(
            acknowledgement.envelope.extra.get(RUNTIME_TOKEN_FIELD),
            Some(&json!("runtime-token-001"))
        );
    }

    #[test]
    fn tcp_broker_routes_binary_publish_between_room_members() {
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            idle_timeout: Duration::from_millis(20),
            handshake_timeout: Duration::from_secs(1),
            ..BrokerConfig::default()
        };
        let limits = config.frame_limits;
        let mut server = BrokerServer::bind(config).expect("server must bind");
        let address = server.local_addr().expect("server address must resolve");
        let mut sender = TcpStream::connect(address).expect("sender must connect");
        let mut target = TcpStream::connect(address).expect("target must connect");
        target
            .set_read_timeout(Some(Duration::from_secs(1)))
            .expect("read timeout must be configured");

        hello("blender:one")
            .write_to(&mut sender, limits)
            .expect("sender hello must write");
        hello("maya:two")
            .write_to(&mut target, limits)
            .expect("target hello must write");
        pump_until(&mut server, "hello registration", |server| {
            server.core.peer_count() == 2
        });
        join("blender:one", "room-a")
            .write_to(&mut sender, limits)
            .expect("sender join must write");
        join("maya:two", "room-a")
            .write_to(&mut target, limits)
            .expect("target join must write");
        pump_until(&mut server, "room membership", |server| {
            server
                .core
                .rooms
                .get("room-a")
                .is_some_and(|members| members.len() == 2)
        });
        let binary_body = [0, 1, 2, 255];
        frame(
            "blender:one",
            MessageType::Publish,
            Some("room-a"),
            None,
            None,
            &binary_body,
        )
        .write_to(&mut sender, limits)
        .expect("publish must write");
        let (finished, receiver) = mpsc::channel();
        let handle = thread::spawn(move || {
            let result = server.run();
            let _ = finished.send(result);
        });

        let delivered = Frame::read_from(&mut target, limits).expect("target must receive publish");

        assert_eq!(delivered.envelope.sender, "blender:one");
        assert_eq!(delivered.body, binary_body);
        drop(sender);
        drop(target);
        assert!(receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("server must finish after bounded idle timeout")
            .is_ok());
        handle.join().expect("server thread must not panic");
    }

    fn pump_until(
        server: &mut BrokerServer,
        description: &str,
        condition: impl Fn(&BrokerServer) -> bool,
    ) {
        for _ in 0..100 {
            server
                .accept_pending_connections()
                .expect("server must accept connections");
            server.process_network_events();
            server.close_expired_handshakes_at(Instant::now());
            if condition(server) {
                return;
            }
            thread::sleep(Duration::from_millis(2));
        }
        panic!(
            "timed out waiting for {description}: {} connections, {} peers",
            server.connections.len(),
            server.core.peer_count()
        );
    }

    #[test]
    fn idle_shutdown_is_bounded_after_last_disconnect() {
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            idle_timeout: Duration::from_millis(30),
            ..BrokerConfig::default()
        };
        let mut server = BrokerServer::bind(config).expect("server must bind");
        let address = server.local_addr().expect("server address must resolve");
        let (finished, receiver) = mpsc::channel();
        let handle = thread::spawn(move || {
            let result = server.run();
            let _ = finished.send(result);
        });
        let client = TcpStream::connect(address).expect("client must connect");
        drop(client);

        let result = receiver
            .recv_timeout(Duration::from_secs(2))
            .expect("server must finish within bounded timeout");
        assert!(result.is_ok());
        handle.join().expect("server thread must not panic");
    }

    #[test]
    fn idle_shutdown_is_bounded_without_connections() {
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            idle_timeout: Duration::from_millis(20),
            ..BrokerConfig::default()
        };
        let mut server = BrokerServer::bind(config).expect("server must bind");
        let (finished, receiver) = mpsc::channel();
        let handle = thread::spawn(move || {
            let result = server.run();
            let _ = finished.send(result);
        });

        let result = receiver
            .recv_timeout(Duration::from_secs(1))
            .expect("server must finish without a client");
        assert!(result.is_ok());
        handle.join().expect("server thread must not panic");
    }

    #[test]
    fn zero_idle_timeout_shuts_down_immediately_when_empty() {
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            idle_timeout: Duration::ZERO,
            ..BrokerConfig::default()
        };
        let server = BrokerServer::bind(config).expect("server must bind");

        assert!(server.should_shutdown());
    }
}
