//! runtime Brokerの接続状態を取得するCLI Monitor。

use std::env;
use std::error::Error;
use std::fmt;
use std::io;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use crate::broker::{BrokerSnapshot, MONITOR_MAX_HEADER_LEN};
use crate::envelope::{Envelope, MessageType, MONITOR_SNAPSHOT_SCHEMA};
use crate::frame::{Frame, FrameError, FrameLimits};
use crate::presence::PeerPresence;
use crate::runtime::{RuntimeError, RuntimeManifest};
use serde_json::{Map, Value};

const BROKER_SENDER: &str = "ywta-link:broker";
const MONITOR_TIMEOUT: Duration = Duration::from_secs(2);
const RUNTIME_FILE_SUFFIX: &str = "YWTA\\Link\\runtime\\v1\\broker.json";
const MONITOR_INCLUDE_PRESENCE_FIELD: &str = "ywta_include_presence";
const RUNTIME_CHALLENGE_FIELD: &str = "ywta_runtime_challenge";
const RUNTIME_TOKEN_FIELD: &str = "ywta_runtime_token";

/// CLI Monitorが扱うsnapshotの種別。
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MonitorCommand {
    Status,
    Peers,
    Rooms,
}

impl MonitorCommand {
    fn parse(value: &str) -> Result<Self, MonitorError> {
        match value {
            "status" => Ok(Self::Status),
            "peers" => Ok(Self::Peers),
            "rooms" => Ok(Self::Rooms),
            _ => Err(MonitorError::Usage(usage().to_owned())),
        }
    }
}

/// Monitorの接続、protocol、出力に関する失敗。
#[derive(Debug)]
pub enum MonitorError {
    Usage(String),
    Runtime(RuntimeError),
    Io(io::Error),
    Frame(FrameError),
    Json(serde_json::Error),
    Protocol(String),
}

impl fmt::Display for MonitorError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Usage(message) => formatter.write_str(message),
            Self::Runtime(error) => write!(formatter, "runtime manifest error: {error}"),
            Self::Io(error) => write!(formatter, "monitor I/O error: {error}"),
            Self::Frame(error) => write!(formatter, "monitor frame error: {error}"),
            Self::Json(error) => write!(formatter, "monitor JSON error: {error}"),
            Self::Protocol(message) => write!(formatter, "monitor protocol error: {message}"),
        }
    }
}

impl Error for MonitorError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Runtime(error) => Some(error),
            Self::Io(error) => Some(error),
            Self::Frame(error) => Some(error),
            Self::Json(error) => Some(error),
            Self::Usage(_) | Self::Protocol(_) => None,
        }
    }
}

impl From<RuntimeError> for MonitorError {
    fn from(error: RuntimeError) -> Self {
        Self::Runtime(error)
    }
}

impl From<io::Error> for MonitorError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<FrameError> for MonitorError {
    fn from(error: FrameError) -> Self {
        Self::Frame(error)
    }
}

impl From<serde_json::Error> for MonitorError {
    fn from(error: serde_json::Error) -> Self {
        Self::Json(error)
    }
}

/// 指定したMonitor commandを実行し、stdoutへ出す文字列を返す。
pub fn run_cli(command: &str, arguments: &[String]) -> Result<String, MonitorError> {
    let command = MonitorCommand::parse(command)?;
    let options = MonitorOptions::parse(arguments)?;
    let runtime_file = options.runtime_file.unwrap_or(default_runtime_path()?);
    let snapshot = query(&runtime_file)?;
    if options.json {
        return format_json(command, &snapshot);
    }
    Ok(format_human(command, &snapshot))
}

/// runtime manifestからBrokerへ接続し、完全なsnapshotを1回だけ取得する。
pub fn query(runtime_file: impl AsRef<Path>) -> Result<BrokerSnapshot, MonitorError> {
    let manifest = RuntimeManifest::read(runtime_file)?;
    let endpoint = manifest
        .endpoint
        .parse::<SocketAddr>()
        .map_err(|_| MonitorError::Protocol("manifest endpoint is not numeric".to_owned()))?;
    if !endpoint.ip().is_loopback() {
        return Err(MonitorError::Protocol(
            "monitor only accepts loopback endpoints".to_owned(),
        ));
    }

    let mut stream = TcpStream::connect_timeout(&endpoint, MONITOR_TIMEOUT)?;
    stream.set_read_timeout(Some(MONITOR_TIMEOUT))?;
    stream.set_write_timeout(Some(MONITOR_TIMEOUT))?;
    let peer_id = unique_id("monitor");
    let challenge = unique_id("challenge");
    let limits = monitor_frame_limits();
    let hello = hello_frame(&peer_id, &challenge, &manifest.token)?;
    hello.write_to(&mut stream, limits)?;

    let acknowledgement = Frame::read_from(&mut stream, limits)?;
    validate_runtime_ack(&acknowledgement, &hello, &challenge, &manifest.token)?;

    let request = snapshot_request(&peer_id)?;
    request.write_to(&mut stream, limits)?;
    let response = Frame::read_from(&mut stream, limits)?;
    validate_snapshot_response(&response, &request, &peer_id, &manifest)
}

/// `%LOCALAPPDATA%`以下の既定runtime manifest pathを返す。
pub fn default_runtime_path() -> Result<PathBuf, MonitorError> {
    let root = env::var_os("LOCALAPPDATA").ok_or_else(|| {
        MonitorError::Protocol("LOCALAPPDATA is required for the default runtime path".to_owned())
    })?;
    Ok(PathBuf::from(root).join(RUNTIME_FILE_SUFFIX))
}

fn validate_runtime_ack(
    frame: &Frame,
    hello: &Frame,
    challenge: &str,
    token: &str,
) -> Result<(), MonitorError> {
    if frame.envelope.message_type != MessageType::Hello
        || frame.envelope.sender != BROKER_SENDER
        || frame.envelope.correlation_id.as_deref() != Some(hello.envelope.message_id.as_str())
        || frame.envelope.room.is_some()
        || frame.envelope.target.is_some()
        || frame.envelope.topic.is_some()
        || frame.envelope.schema.is_some()
        || frame.envelope.body.is_some()
        || !frame.body.is_empty()
        || frame.envelope.extra.len() != 2
    {
        return Err(MonitorError::Protocol(
            "runtime hello acknowledgement does not match request".to_owned(),
        ));
    }
    let echoed_challenge = frame
        .envelope
        .extra
        .get(RUNTIME_CHALLENGE_FIELD)
        .and_then(Value::as_str);
    let echoed_token = frame
        .envelope
        .extra
        .get(RUNTIME_TOKEN_FIELD)
        .and_then(Value::as_str);
    if echoed_challenge != Some(challenge) || echoed_token != Some(token) {
        return Err(MonitorError::Protocol(
            "runtime hello acknowledgement token mismatch".to_owned(),
        ));
    }
    Ok(())
}

fn validate_snapshot_response(
    frame: &Frame,
    request: &Frame,
    peer_id: &str,
    manifest: &RuntimeManifest,
) -> Result<BrokerSnapshot, MonitorError> {
    if frame.envelope.message_type != MessageType::MonitorSnapshotResponse
        || frame.envelope.sender != BROKER_SENDER
        || frame.envelope.target.as_deref() != Some(peer_id)
        || frame.envelope.correlation_id.as_deref() != Some(request.envelope.message_id.as_str())
        || frame.envelope.schema.as_deref() != Some(MONITOR_SNAPSHOT_SCHEMA)
        || !frame.body.is_empty()
    {
        return Err(MonitorError::Protocol(
            "snapshot response does not match request".to_owned(),
        ));
    }
    let body =
        frame.envelope.body.clone().ok_or_else(|| {
            MonitorError::Protocol("snapshot response body is missing".to_owned())
        })?;
    let snapshot: BrokerSnapshot = serde_json::from_value(body)?;
    validate_snapshot(&snapshot)?;
    validate_manifest_identity(&snapshot, manifest)?;
    Ok(snapshot)
}

fn validate_manifest_identity(
    snapshot: &BrokerSnapshot,
    manifest: &RuntimeManifest,
) -> Result<(), MonitorError> {
    if snapshot.endpoint != manifest.endpoint || snapshot.pid != manifest.pid {
        return Err(MonitorError::Protocol(
            "snapshot broker identity differs from runtime manifest".to_owned(),
        ));
    }
    Ok(())
}

fn validate_snapshot(snapshot: &BrokerSnapshot) -> Result<(), MonitorError> {
    if snapshot.protocol_version != 1 || snapshot.pid == 0 {
        return Err(MonitorError::Protocol(
            "snapshot broker identity is invalid".to_owned(),
        ));
    }
    let endpoint = snapshot
        .endpoint
        .parse::<SocketAddr>()
        .map_err(|_| MonitorError::Protocol("snapshot endpoint is not numeric".to_owned()))?;
    if !endpoint.ip().is_loopback() {
        return Err(MonitorError::Protocol(
            "snapshot endpoint is not loopback".to_owned(),
        ));
    }
    if !is_sorted_unique(&snapshot.peers)
        || snapshot
            .peers
            .iter()
            .any(|peer| peer.is_empty() || peer.starts_with("ywta-link:monitor:"))
    {
        return Err(MonitorError::Protocol(
            "snapshot peers are not sorted and unique".to_owned(),
        ));
    }
    let mut previous_presence_peer = None;
    for presence in &snapshot.presence {
        presence.validate().map_err(|error| {
            MonitorError::Protocol(format!(
                "snapshot presence for {} is invalid: {error}",
                presence.peer_id
            ))
        })?;
        if previous_presence_peer.is_some_and(|previous| previous >= presence.peer_id.as_str())
            || presence.peer_id.starts_with("ywta-link:monitor:")
            || snapshot.peers.binary_search(&presence.peer_id).is_err()
        {
            return Err(MonitorError::Protocol(
                "snapshot presence is not a sorted peer subset".to_owned(),
            ));
        }
        previous_presence_peer = Some(presence.peer_id.as_str());
    }
    let mut previous_room = None;
    for room in &snapshot.rooms {
        if room.room.is_empty()
            || previous_room.is_some_and(|previous| previous >= room.room.as_str())
            || !is_sorted_unique(&room.members)
            || room
                .members
                .iter()
                .any(|peer| peer.is_empty() || peer.starts_with("ywta-link:monitor:"))
            || room
                .members
                .iter()
                .any(|peer| snapshot.peers.binary_search(peer).is_err())
        {
            return Err(MonitorError::Protocol(
                "snapshot room state is not sorted and unique".to_owned(),
            ));
        }
        previous_room = Some(room.room.as_str());
        let mut previous_topic = None;
        for subscription in &room.subscriptions {
            if subscription.topic.is_empty()
                || previous_topic.is_some_and(|previous| previous >= subscription.topic.as_str())
                || !is_sorted_unique(&subscription.members)
                || subscription
                    .members
                    .iter()
                    .any(|peer| peer.is_empty() || peer.starts_with("ywta-link:monitor:"))
                || subscription
                    .members
                    .iter()
                    .any(|peer| room.members.binary_search(peer).is_err())
            {
                return Err(MonitorError::Protocol(
                    "snapshot subscriptions are not sorted and unique".to_owned(),
                ));
            }
            previous_topic = Some(subscription.topic.as_str());
        }
    }
    Ok(())
}

fn is_sorted_unique(values: &[String]) -> bool {
    values.windows(2).all(|window| window[0] < window[1])
}

fn monitor_frame_limits() -> FrameLimits {
    FrameLimits {
        max_header_len: MONITOR_MAX_HEADER_LEN,
        max_body_len: 0,
    }
}

fn hello_frame(peer_id: &str, challenge: &str, token: &str) -> Result<Frame, MonitorError> {
    let mut extra = Map::new();
    extra.insert(
        RUNTIME_CHALLENGE_FIELD.to_owned(),
        Value::String(challenge.to_owned()),
    );
    extra.insert(
        RUNTIME_TOKEN_FIELD.to_owned(),
        Value::String(token.to_owned()),
    );
    Ok(Frame::new(
        Envelope {
            protocol_version: 1,
            message_id: unique_id("hello"),
            message_type: MessageType::Hello,
            sender: peer_id.to_owned(),
            room: None,
            target: None,
            topic: None,
            correlation_id: None,
            schema: None,
            body: None,
            extra,
        },
        Vec::new(),
    )?)
}

fn snapshot_request(peer_id: &str) -> Result<Frame, MonitorError> {
    let mut extra = Map::new();
    extra.insert(MONITOR_INCLUDE_PRESENCE_FIELD.to_owned(), Value::Bool(true));
    Ok(Frame::new(
        Envelope {
            protocol_version: 1,
            message_id: unique_id("snapshot"),
            message_type: MessageType::MonitorSnapshotRequest,
            sender: peer_id.to_owned(),
            room: None,
            target: None,
            topic: None,
            correlation_id: None,
            schema: Some(MONITOR_SNAPSHOT_SCHEMA.to_owned()),
            body: None,
            extra,
        },
        Vec::new(),
    )?)
}

fn unique_id(prefix: &str) -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    format!("ywta-link:{prefix}:{}-{timestamp}", std::process::id())
}

fn format_json(command: MonitorCommand, snapshot: &BrokerSnapshot) -> Result<String, MonitorError> {
    let value = match command {
        MonitorCommand::Status => serde_json::to_value(snapshot)?,
        MonitorCommand::Peers => {
            serde_json::json!({ "peers": snapshot.peers, "presence": snapshot.presence })
        }
        MonitorCommand::Rooms => serde_json::json!({ "rooms": snapshot.rooms }),
    };
    Ok(serde_json::to_string_pretty(&value)?)
}

fn format_human(command: MonitorCommand, snapshot: &BrokerSnapshot) -> String {
    match command {
        MonitorCommand::Status => format!(
            "endpoint: {}\npid: {}\nprotocol: {}\npeers: {}\npresence: {}\nrooms: {}",
            snapshot.endpoint,
            snapshot.pid,
            snapshot.protocol_version,
            snapshot.peers.len(),
            snapshot.presence.len(),
            snapshot.rooms.len()
        ),
        MonitorCommand::Peers => snapshot
            .peers
            .iter()
            .map(|peer_id| {
                let Some(presence) = snapshot
                    .presence
                    .iter()
                    .find(|presence| presence.peer_id == *peer_id)
                else {
                    return peer_id.clone();
                };
                format_peer_presence(peer_id, presence)
            })
            .collect::<Vec<_>>()
            .join("\n"),
        MonitorCommand::Rooms => snapshot
            .rooms
            .iter()
            .map(|room| {
                let subscriptions = room
                    .subscriptions
                    .iter()
                    .map(|subscription| {
                        format!(
                            "  {}: {}",
                            subscription.topic,
                            subscription.members.join(", ")
                        )
                    })
                    .collect::<Vec<_>>();
                let mut lines = vec![format!("{}: {}", room.room, room.members.join(", "))];
                lines.extend(subscriptions);
                lines.join("\n")
            })
            .collect::<Vec<_>>()
            .join("\n"),
    }
}

fn format_peer_presence(peer_id: &str, presence: &PeerPresence) -> String {
    let capabilities = if presence.capabilities.is_empty() {
        "(none)".to_owned()
    } else {
        presence.capabilities.join(", ")
    };
    format!(
        "{peer_id}\n  application: {}\n  application_version: {}\n  plugin_version: {}\n  capabilities: {capabilities}",
        presence.application,
        presence.application_version,
        presence.plugin_version,
    )
}

struct MonitorOptions {
    json: bool,
    runtime_file: Option<PathBuf>,
}

impl MonitorOptions {
    fn parse(arguments: &[String]) -> Result<Self, MonitorError> {
        let mut json = false;
        let mut runtime_file = None;
        let mut index = 0;
        while index < arguments.len() {
            match arguments[index].as_str() {
                "--json" if !json => json = true,
                "--json" => return Err(MonitorError::Usage(usage().to_owned())),
                "--runtime-file" if runtime_file.is_none() => {
                    let value = arguments.get(index + 1).ok_or_else(|| {
                        MonitorError::Usage("--runtime-file requires an absolute path".to_owned())
                    })?;
                    let path = PathBuf::from(value);
                    if !path.is_absolute() {
                        return Err(MonitorError::Usage(
                            "--runtime-file must be an absolute path".to_owned(),
                        ));
                    }
                    runtime_file = Some(path);
                    index += 1;
                }
                "--runtime-file" => return Err(MonitorError::Usage(usage().to_owned())),
                "--help" | "-h" => return Err(MonitorError::Usage(usage().to_owned())),
                _ => return Err(MonitorError::Usage(usage().to_owned())),
            }
            index += 1;
        }
        Ok(Self { json, runtime_file })
    }
}

/// Monitor commandの利用方法を返す。
pub fn usage() -> &'static str {
    "usage: ywta-link <status|peers|rooms> [--json] [--runtime-file absolute-path]"
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::broker::{BrokerConfig, BrokerServer, RoomSnapshot, SubscriptionSnapshot};
    use crate::envelope::Envelope;
    use crate::presence::PEER_HELLO_SCHEMA;
    use serde_json::json;
    use std::fs;
    use std::sync::mpsc;
    use std::thread;
    use std::time::Instant;

    fn args(values: &[&str]) -> Vec<String> {
        values.iter().map(|value| (*value).to_owned()).collect()
    }

    #[test]
    fn monitor_command_rejects_unknown_duplicate_and_missing_options() {
        assert!(MonitorCommand::parse("unknown").is_err());
        assert!(MonitorOptions::parse(&args(&["--json", "--json"])).is_err());
        assert!(MonitorOptions::parse(&args(&["--runtime-file"])).is_err());
        assert!(MonitorOptions::parse(&args(&["--runtime-file", "relative.json"])).is_err());
        assert!(MonitorOptions::parse(&args(&["--nope"])).is_err());
    }

    #[test]
    fn snapshot_validation_rejects_unsorted_or_monitor_peers() {
        let mut snapshot = BrokerSnapshot {
            protocol_version: 1,
            endpoint: "127.0.0.1:1234".to_owned(),
            pid: 1,
            peers: vec!["b".to_owned(), "a".to_owned()],
            presence: Vec::new(),
            rooms: Vec::new(),
        };
        assert!(validate_snapshot(&snapshot).is_err());
        snapshot.peers = vec!["a".to_owned(), "ywta-link:monitor:1".to_owned()];
        assert!(validate_snapshot(&snapshot).is_err());
    }

    #[test]
    fn snapshot_validation_requires_membership_subsets_and_manifest_identity() {
        let mut snapshot = BrokerSnapshot {
            protocol_version: 1,
            endpoint: "127.0.0.1:1234".to_owned(),
            pid: 1,
            peers: vec!["peer-a".to_owned()],
            presence: Vec::new(),
            rooms: vec![RoomSnapshot {
                room: "room-a".to_owned(),
                members: vec!["peer-b".to_owned()],
                subscriptions: Vec::new(),
            }],
        };
        assert!(validate_snapshot(&snapshot).is_err());
        snapshot.rooms[0].members = vec!["peer-a".to_owned()];
        snapshot.rooms[0].subscriptions = vec![SubscriptionSnapshot {
            topic: "camera".to_owned(),
            members: vec!["peer-b".to_owned()],
        }];
        assert!(validate_snapshot(&snapshot).is_err());
        snapshot.rooms[0].subscriptions[0].members = vec!["ywta-link:monitor:one".to_owned()];
        assert!(validate_snapshot(&snapshot).is_err());
        snapshot.rooms[0].members = vec!["ywta-link:monitor:one".to_owned()];
        snapshot.rooms[0].subscriptions[0].members = vec!["peer-a".to_owned()];
        assert!(validate_snapshot(&snapshot).is_err());
        snapshot.rooms[0].members = vec!["peer-a".to_owned()];
        snapshot.rooms[0].subscriptions[0].members = vec!["peer-a".to_owned()];
        validate_snapshot(&snapshot).expect("valid subset snapshot must pass");

        let manifest = RuntimeManifest {
            protocol_version: 1,
            endpoint: snapshot.endpoint.clone(),
            pid: snapshot.pid,
            token: "token".to_owned(),
        };
        validate_manifest_identity(&snapshot, &manifest).expect("manifest identity must match");
        let mut different_manifest = manifest;
        different_manifest.pid = 2;
        assert!(validate_manifest_identity(&snapshot, &different_manifest).is_err());
        different_manifest.pid = 1;
        different_manifest.endpoint = "127.0.0.1:1235".to_owned();
        assert!(validate_manifest_identity(&snapshot, &different_manifest).is_err());
    }

    #[test]
    fn old_snapshot_json_decodes_without_presence_and_ignores_compatible_fields() {
        let snapshot: BrokerSnapshot = serde_json::from_value(serde_json::json!({
            "protocol_version": 1,
            "endpoint": "127.0.0.1:1234",
            "pid": 1,
            "peers": ["legacy:peer"],
            "rooms": [{
                "room": "room-a",
                "members": ["legacy:peer"],
                "subscriptions": [],
                "future_room_field": true
            }],
            "future_snapshot_field": "ignored"
        }))
        .expect("legacy snapshot must remain decodable");
        assert!(snapshot.presence.is_empty());
        validate_snapshot(&snapshot).expect("legacy snapshot must remain valid");
    }

    #[test]
    fn snapshot_validation_rejects_invalid_presence_subset_or_order() {
        let mut snapshot = BrokerSnapshot {
            protocol_version: 1,
            endpoint: "127.0.0.1:1234".to_owned(),
            pid: 1,
            peers: vec!["peer-a".to_owned(), "peer-b".to_owned()],
            presence: vec![test_presence("peer-c")],
            rooms: Vec::new(),
        };
        assert!(validate_snapshot(&snapshot).is_err());

        snapshot.presence = vec![test_presence("peer-b"), test_presence("peer-a")];
        validate_snapshot(&snapshot).expect_err("presence must be Peer ID sorted");

        snapshot.presence = vec![test_presence("ywta-link:monitor:one")];
        validate_snapshot(&snapshot).expect_err("monitor presence must be hidden");
    }

    #[test]
    fn monitor_outputs_are_command_specific_and_json_is_machine_readable() {
        let snapshot = BrokerSnapshot {
            protocol_version: 1,
            endpoint: "127.0.0.1:1234".to_owned(),
            pid: 1,
            peers: vec!["blender:one".to_owned()],
            presence: Vec::new(),
            rooms: vec![RoomSnapshot {
                room: "shot-a".to_owned(),
                members: vec!["blender:one".to_owned()],
                subscriptions: vec![SubscriptionSnapshot {
                    topic: "camera".to_owned(),
                    members: vec!["blender:one".to_owned()],
                }],
            }],
        };
        let peers = serde_json::from_str::<Value>(
            &format_json(MonitorCommand::Peers, &snapshot).expect("JSON must encode"),
        )
        .expect("peers output must be JSON");
        assert_eq!(peers["peers"][0], "blender:one");
        assert!(peers["presence"].as_array().is_some_and(Vec::is_empty));
        assert_eq!(
            format_human(MonitorCommand::Rooms, &snapshot),
            "shot-a: blender:one\n  camera: blender:one"
        );
    }

    #[test]
    fn real_runtime_monitor_reports_peers_rooms_and_subscriptions() {
        let directory = env::temp_dir().join(format!(
            "ywta-link-monitor-{}-{}",
            std::process::id(),
            unique_id("test").replace(':', "-")
        ));
        let runtime_file = directory.join("broker.json");
        let config = BrokerConfig {
            bind_addr: "127.0.0.1:0".parse().expect("test address must parse"),
            idle_timeout: Duration::from_millis(100),
            handshake_timeout: Duration::from_secs(1),
            ..BrokerConfig::default()
        };
        let mut server = BrokerServer::bind(config).expect("broker must bind");
        let endpoint = server.local_addr().expect("endpoint must resolve");
        let manifest = RuntimeManifest::for_endpoint(endpoint).expect("manifest must build");
        server.set_runtime_token(manifest.token.clone());
        let lease = crate::runtime::RuntimeLease::claim(&runtime_file, manifest.clone())
            .expect("runtime lease must claim");
        let (done_sender, done_receiver) = mpsc::channel();
        let server_thread = thread::spawn(move || {
            let _lease = lease;
            let result = server.run();
            done_sender.send(result).expect("server result must send");
        });

        let mut blender = TcpStream::connect(endpoint).expect("blender peer must connect");
        let mut maya = TcpStream::connect(endpoint).expect("maya peer must connect");
        send_test_frame(&mut blender, test_presence_hello("blender:peer-001"));
        send_test_frame(&mut maya, test_hello("maya:two"));
        send_test_frame(&mut blender, test_join("blender:peer-001", "shot-a"));
        send_test_frame(&mut maya, test_join("maya:two", "shot-a"));
        send_test_frame(&mut maya, test_subscribe("maya:two", "shot-a", "camera"));
        let expected_peers = ["blender:peer-001".to_owned(), "maya:two".to_owned()];
        let deadline = Instant::now() + Duration::from_secs(2);
        let mut last_error = None;
        let snapshot = loop {
            match query(&runtime_file) {
                Ok(snapshot)
                    if snapshot.peers == expected_peers
                        && snapshot.rooms.len() == 1
                        && snapshot.rooms[0].members == expected_peers
                        && snapshot.rooms[0].subscriptions.len() == 1 =>
                {
                    break snapshot;
                }
                Ok(_) => {}
                Err(error) => last_error = Some(error),
            }
            assert!(
                Instant::now() < deadline,
                "state sync timed out: {last_error:?}"
            );
            thread::sleep(Duration::from_millis(5));
        };
        assert_eq!(snapshot.endpoint, endpoint.to_string());
        assert_eq!(snapshot.pid, std::process::id());
        assert_eq!(snapshot.peers, vec!["blender:peer-001", "maya:two"]);
        assert_eq!(snapshot.presence.len(), 1);
        assert_eq!(snapshot.presence[0].peer_id, "blender:peer-001");
        assert_eq!(snapshot.presence[0].application, "Blender");
        assert_eq!(snapshot.rooms.len(), 1);
        assert_eq!(snapshot.rooms[0].room, "shot-a");
        assert_eq!(
            snapshot.rooms[0].members,
            vec!["blender:peer-001", "maya:two"]
        );
        assert_eq!(snapshot.rooms[0].subscriptions[0].topic, "camera");
        assert_eq!(snapshot.rooms[0].subscriptions[0].members, vec!["maya:two"]);

        let runtime_argument = runtime_file.to_string_lossy().into_owned();
        for command in ["status", "peers", "rooms"] {
            let human = run_cli(
                command,
                &["--runtime-file".to_owned(), runtime_argument.clone()],
            )
            .expect("human monitor command must succeed");
            assert!(!human.is_empty());
            let json_output = run_cli(
                command,
                &[
                    "--json".to_owned(),
                    "--runtime-file".to_owned(),
                    runtime_argument.clone(),
                ],
            )
            .expect("JSON monitor command must succeed");
            let json: Value = serde_json::from_str(&json_output).expect("output must be JSON");
            match command {
                "status" => {
                    assert_eq!(json["peers"][0], "blender:peer-001");
                    assert_eq!(json["presence"][0]["peer_id"], "blender:peer-001");
                }
                "peers" => assert_eq!(json["peers"].as_array().map(Vec::len), Some(2)),
                "rooms" => assert_eq!(json["rooms"][0]["room"], "shot-a"),
                _ => unreachable!("command list is fixed"),
            }
        }
        let human_peers = run_cli(
            "peers",
            &["--runtime-file".to_owned(), runtime_argument.clone()],
        )
        .expect("human peers monitor command must succeed");
        assert!(human_peers.contains("application: Blender"));
        assert!(human_peers.contains("capabilities: camera.apply.v1"));
        assert!(human_peers.contains("maya:two"));

        let expected_token = manifest.token.clone();
        let mut wrong_manifest = manifest;
        wrong_manifest.token = "wrong-token".to_owned();
        fs::write(
            &runtime_file,
            serde_json::to_vec(&wrong_manifest).expect("manifest must encode"),
        )
        .expect("wrong manifest must write");
        assert!(query(&runtime_file).is_err());
        fs::write(
            &runtime_file,
            serde_json::to_vec(&RuntimeManifest {
                token: expected_token,
                ..wrong_manifest
            })
            .expect("manifest must encode"),
        )
        .expect("manifest restore must write");
        drop(blender);
        drop(maya);
        assert!(done_receiver
            .recv_timeout(Duration::from_secs(3))
            .expect("server must stop")
            .is_ok());
        server_thread.join().expect("server thread must not panic");
        let _ = fs::remove_dir_all(&directory);
    }

    #[test]
    fn malformed_runtime_manifest_fails_closed_before_connecting() {
        let directory = env::temp_dir().join(format!(
            "ywta-link-monitor-malformed-{}-{}",
            std::process::id(),
            unique_id("test").replace(':', "-")
        ));
        let runtime_file = directory.join("broker.json");
        fs::create_dir_all(&directory).expect("test directory must create");
        fs::write(
            &runtime_file,
            br#"{"protocol_version":1,"endpoint":"127.0.0.1:1"}"#,
        )
        .expect("malformed manifest must write");
        assert!(matches!(
            query(&runtime_file),
            Err(MonitorError::Runtime(RuntimeError::Json(_)))
        ));
        fs::remove_dir_all(&directory).expect("test directory must remove");
    }

    fn send_test_frame(stream: &mut TcpStream, frame: Frame) {
        frame
            .write_to(stream, FrameLimits::default())
            .expect("test frame must write");
    }

    fn test_hello(sender: &str) -> Frame {
        test_frame(sender, MessageType::Hello, None, None)
    }

    fn test_presence_hello(sender: &str) -> Frame {
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
                message_id: unique_id("presence-hello"),
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

    fn test_presence(peer_id: &str) -> PeerPresence {
        let mut body: Value = serde_json::from_slice(include_bytes!(
            "../../../tests/link/fixtures/peer_hello_v1.json"
        ))
        .expect("presence fixture must decode");
        body.as_object_mut()
            .expect("presence fixture must be an object")
            .insert("peer_id".to_owned(), Value::String(peer_id.to_owned()));
        PeerPresence::from_value(&body).expect("presence fixture must validate")
    }

    fn test_join(sender: &str, room: &str) -> Frame {
        test_frame(sender, MessageType::Join, Some(room), None)
    }

    fn test_subscribe(sender: &str, room: &str, topic: &str) -> Frame {
        test_frame(sender, MessageType::Subscribe, Some(room), Some(topic))
    }

    fn test_frame(
        sender: &str,
        message_type: MessageType,
        room: Option<&str>,
        topic: Option<&str>,
    ) -> Frame {
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: unique_id("test-message"),
                message_type,
                sender: sender.to_owned(),
                room: room.map(str::to_owned),
                target: None,
                topic: topic.map(str::to_owned),
                correlation_id: None,
                schema: Some("ywta.test.v1".to_owned()),
                body: Some(json!({"test": true})),
                extra: Default::default(),
            },
            Vec::new(),
        )
        .expect("test frame must be valid")
    }
}
