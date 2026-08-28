//! YWTA Link v1共通Envelopeの型と検証を提供する。

use std::error::Error;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

/// Broker MVPが受理する論理Message種別。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum MessageType {
    #[serde(rename = "hello")]
    Hello,
    #[serde(rename = "join")]
    Join,
    #[serde(rename = "leave")]
    Leave,
    #[serde(rename = "subscribe")]
    Subscribe,
    #[serde(rename = "unsubscribe")]
    Unsubscribe,
    #[serde(rename = "publish")]
    Publish,
    #[serde(rename = "request")]
    Request,
    #[serde(rename = "response")]
    Response,
    #[serde(rename = "error")]
    Error,
    #[serde(rename = "ping")]
    Ping,
    #[serde(rename = "pong")]
    Pong,
    #[serde(rename = "binary.begin")]
    BinaryBegin,
    #[serde(rename = "binary.chunk")]
    BinaryChunk,
    #[serde(rename = "binary.end")]
    BinaryEnd,
    #[serde(rename = "monitor.snapshot.request")]
    MonitorSnapshotRequest,
    #[serde(rename = "monitor.snapshot.response")]
    MonitorSnapshotResponse,
}

/// CLI Monitor snapshotのprotocol schema。
pub const MONITOR_SNAPSHOT_SCHEMA: &str = "ywta.monitor.snapshot.v1";

/// JSONの共通Headerを表すEnvelope。
#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
pub struct Envelope {
    pub protocol_version: u16,
    pub message_id: String,
    #[serde(rename = "type")]
    pub message_type: MessageType,
    pub sender: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub room: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub target: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub topic: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub correlation_id: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub schema: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<Value>,
    #[serde(default, flatten)]
    pub extra: Map<String, Value>,
}

/// Envelopeが仕様に合わない理由。
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EnvelopeError {
    message: String,
}

impl EnvelopeError {
    /// 検証エラーを作成する。
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for EnvelopeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for EnvelopeError {}

impl Envelope {
    /// JSON objectからEnvelopeを復元して検証する。
    pub fn from_json(json: &[u8]) -> Result<Self, EnvelopeError> {
        let envelope: Self = serde_json::from_slice(json)
            .map_err(|error| EnvelopeError::new(format!("invalid envelope JSON: {error}")))?;
        envelope.validate()?;
        Ok(envelope)
    }

    /// Envelopeを検証済みJSONへ変換する。
    pub fn to_json(&self) -> Result<Vec<u8>, EnvelopeError> {
        self.validate()?;
        serde_json::to_vec(self)
            .map_err(|error| EnvelopeError::new(format!("cannot encode envelope JSON: {error}")))
    }

    /// Headerの必須Fieldとroutingに必要なFieldをfail closedで検証する。
    pub fn validate(&self) -> Result<(), EnvelopeError> {
        if self.protocol_version != 1 {
            return Err(EnvelopeError::new("protocol_version must be 1"));
        }
        require_non_empty(&self.message_id, "message_id")?;
        require_non_empty(&self.sender, "sender")?;
        validate_optional(&self.room, "room")?;
        validate_optional(&self.target, "target")?;
        validate_optional(&self.topic, "topic")?;
        validate_optional(&self.correlation_id, "correlation_id")?;

        if matches!(
            self.message_type,
            MessageType::Join
                | MessageType::Leave
                | MessageType::Subscribe
                | MessageType::Unsubscribe
                | MessageType::Publish
                | MessageType::Request
                | MessageType::Response
                | MessageType::Error
        ) {
            require_option(&self.room, "room")?;
        }
        if matches!(
            self.message_type,
            MessageType::Subscribe | MessageType::Unsubscribe
        ) {
            require_option(&self.topic, "topic")?;
        }
        if matches!(
            self.message_type,
            MessageType::Request
                | MessageType::Response
                | MessageType::Error
                | MessageType::MonitorSnapshotResponse
        ) {
            require_option(&self.target, "target")?;
        }
        if matches!(
            self.message_type,
            MessageType::Response | MessageType::Error | MessageType::MonitorSnapshotResponse
        ) {
            require_option(&self.correlation_id, "correlation_id")?;
        }
        if matches!(
            self.message_type,
            MessageType::MonitorSnapshotRequest | MessageType::MonitorSnapshotResponse
        ) && self.schema.as_deref() != Some(MONITOR_SNAPSHOT_SCHEMA)
        {
            return Err(EnvelopeError::new(
                "monitor snapshot messages require the v1 schema",
            ));
        }
        if let Some(schema) = &self.schema {
            if !is_versioned_schema_identifier(schema) {
                return Err(EnvelopeError::new("schema must be a versioned identifier"));
            }
        }
        if self.extra.keys().any(|key| is_known_field(key)) {
            return Err(EnvelopeError::new("extra contains a known envelope field"));
        }
        Ok(())
    }
}

fn require_non_empty(value: &str, field_name: &str) -> Result<(), EnvelopeError> {
    if value.is_empty() {
        return Err(EnvelopeError::new(format!(
            "{field_name} must be a non-empty string"
        )));
    }
    Ok(())
}

fn validate_optional(value: &Option<String>, field_name: &str) -> Result<(), EnvelopeError> {
    if let Some(value) = value {
        require_non_empty(value, field_name)?;
    }
    Ok(())
}

fn require_option(value: &Option<String>, field_name: &str) -> Result<(), EnvelopeError> {
    value
        .as_deref()
        .ok_or_else(|| EnvelopeError::new(format!("{field_name} is required")))
        .and_then(|value| require_non_empty(value, field_name))
}

fn is_known_field(key: &str) -> bool {
    matches!(
        key,
        "protocol_version"
            | "message_id"
            | "type"
            | "sender"
            | "room"
            | "target"
            | "topic"
            | "correlation_id"
            | "schema"
            | "body"
    )
}

/// `name.segment.v1`形式の安定Schema IDかを返す。
pub fn is_versioned_schema_identifier(value: &str) -> bool {
    let Some((prefix, version)) = value.rsplit_once(".v") else {
        return false;
    };
    if prefix.is_empty()
        || version.is_empty()
        || version.starts_with('0')
        || !version.bytes().all(|byte| byte.is_ascii_digit())
    {
        return false;
    }
    prefix.split('.').all(|segment| {
        let mut characters = segment.bytes();
        matches!(characters.next(), Some(first) if first.is_ascii_alphabetic())
            && characters.all(|character| {
                character.is_ascii_alphanumeric() || matches!(character, b'_' | b'-')
            })
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_current_publish_fixture_and_preserves_unknown_field() {
        let envelope = Envelope::from_json(
            br#"{
                "protocol_version": 1,
                "message_id": "msg-preview-001",
                "type": "publish",
                "room": "shot-010",
                "sender": "blender:peer-001",
                "topic": "sync/main-camera",
                "schema": "ywta.sync.preview.v1",
                "body": {"revision": 8},
                "fixture_note": "unknown fields survive"
            }"#,
        )
        .expect("current Python fixture must decode");

        assert_eq!(
            envelope.extra.get("fixture_note"),
            Some(&Value::String("unknown fields survive".to_owned()))
        );
        assert_eq!(
            Envelope::from_json(&envelope.to_json().expect("encode must succeed"))
                .expect("round trip must decode"),
            envelope
        );
    }

    #[test]
    fn rejects_missing_routing_fields_and_unversioned_schema() {
        let missing_room = br#"{
            "protocol_version": 1,
            "message_id": "message-001",
            "type": "publish",
            "sender": "blender:peer-001"
        }"#;
        assert!(Envelope::from_json(missing_room).is_err());

        let bad_schema = br#"{
            "protocol_version": 1,
            "message_id": "message-002",
            "type": "hello",
            "sender": "blender:peer-001",
            "schema": "unversioned"
        }"#;
        assert!(Envelope::from_json(bad_schema).is_err());
    }

    #[test]
    fn accepts_targeted_request_and_correlated_publish_confirmation() {
        let request = Envelope::from_json(
            br#"{
                "protocol_version": 1,
                "message_id": "request-001",
                "type": "request",
                "sender": "maya:peer-001",
                "room": "room-001",
                "target": "blender:peer-001",
                "schema": "ywta.sync.authority.request.v1",
                "body": {"channel_id": "timeline"}
            }"#,
        )
        .expect("authority request must be targeted");
        assert_eq!(request.target.as_deref(), Some("blender:peer-001"));

        let confirmation = Envelope::from_json(
            br#"{
                "protocol_version": 1,
                "message_id": "accepted-001",
                "type": "publish",
                "sender": "blender:peer-001",
                "room": "room-001",
                "topic": "sync/session-001/control",
                "correlation_id": "request-001",
                "schema": "ywta.sync.authority.accepted.v1",
                "body": {"channel_id": "timeline"}
            }"#,
        )
        .expect("publish confirmation correlation is valid");
        assert_eq!(confirmation.correlation_id.as_deref(), Some("request-001"));
    }
}
