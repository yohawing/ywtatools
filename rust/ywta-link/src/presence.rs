//! YWTA Link v1 Peer Presence/Capability広告の型と検証を提供する。

use std::error::Error;
use std::fmt;

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Hello bodyで使用するversioned schema ID。
pub const PEER_HELLO_SCHEMA: &str = "ywta.peer.hello.v1";
/// Presence内の通常文字列に許可する最大Unicode文字数。
pub const PRESENCE_MAX_STRING_LENGTH: usize = 256;
/// Presenceが広告できるProtocol versionの最大数。
pub const PRESENCE_MAX_PROTOCOL_VERSIONS: usize = 16;
/// Presenceで広告できるProtocol versionの最大値。
pub const PRESENCE_MAX_PROTOCOL_VERSION: u16 = u16::MAX;
/// Presenceが広告できるCapabilityの最大数。
pub const PRESENCE_MAX_CAPABILITIES: usize = 128;
/// Capability IDに許可する最大Unicode文字数。
pub const PRESENCE_MAX_CAPABILITY_LENGTH: usize = 256;

/// Hello bodyとして広告するPeerの実装情報。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PeerPresence {
    pub peer_id: String,
    pub application: String,
    pub application_version: String,
    pub plugin_version: String,
    pub protocol_versions: Vec<u16>,
    pub capabilities: Vec<String>,
}

/// Peer Presence metadataがschemaに合わない理由。
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PresenceError {
    message: String,
}

impl PresenceError {
    /// 検証エラーを作成する。
    pub fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for PresenceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl Error for PresenceError {}

impl PeerPresence {
    /// JSON objectのValueからPresenceを復元して検証する。
    pub fn from_value(value: &Value) -> Result<Self, PresenceError> {
        let presence: Self = serde_json::from_value(value.clone())
            .map_err(|error| PresenceError::new(format!("invalid peer hello body: {error}")))?;
        presence.validate()?;
        Ok(presence)
    }

    /// UTF-8 JSONからPresenceを復元して検証する。
    pub fn from_json(json: &[u8]) -> Result<Self, PresenceError> {
        let value: Value = serde_json::from_slice(json)
            .map_err(|error| PresenceError::new(format!("invalid peer hello JSON: {error}")))?;
        Self::from_value(&value)
    }

    /// PresenceをJSON Valueへ変換する。
    pub fn to_value(&self) -> Result<Value, PresenceError> {
        self.validate()?;
        serde_json::to_value(self)
            .map_err(|error| PresenceError::new(format!("cannot encode peer hello: {error}")))
    }

    /// Peer Presenceの各Fieldをfail closedで検証する。
    pub fn validate(&self) -> Result<(), PresenceError> {
        require_string(&self.peer_id, "peer_id", PRESENCE_MAX_STRING_LENGTH)?;
        require_string(&self.application, "application", PRESENCE_MAX_STRING_LENGTH)?;
        require_string(
            &self.application_version,
            "application_version",
            PRESENCE_MAX_STRING_LENGTH,
        )?;
        require_string(
            &self.plugin_version,
            "plugin_version",
            PRESENCE_MAX_STRING_LENGTH,
        )?;

        if self.protocol_versions.is_empty()
            || self.protocol_versions.len() > PRESENCE_MAX_PROTOCOL_VERSIONS
        {
            return Err(PresenceError::new(
                "protocol_versions has an invalid length",
            ));
        }
        if self
            .protocol_versions
            .windows(2)
            .any(|versions| versions[0] >= versions[1])
        {
            return Err(PresenceError::new(
                "protocol_versions must be sorted and unique",
            ));
        }
        if self.protocol_versions.contains(&0) {
            return Err(PresenceError::new(
                "protocol_versions must contain integers from 1 to 65535",
            ));
        }
        if !self.protocol_versions.contains(&1) {
            return Err(PresenceError::new(
                "protocol_versions must include version 1",
            ));
        }

        if self.capabilities.len() > PRESENCE_MAX_CAPABILITIES {
            return Err(PresenceError::new("capabilities has an invalid length"));
        }
        if self
            .capabilities
            .windows(2)
            .any(|capabilities| capabilities[0] >= capabilities[1])
        {
            return Err(PresenceError::new("capabilities must be sorted and unique"));
        }
        for capability in &self.capabilities {
            require_string(capability, "capability", PRESENCE_MAX_CAPABILITY_LENGTH)?;
            if !is_versioned_identifier(capability) {
                return Err(PresenceError::new(
                    "capabilities must contain non-empty versioned identifiers",
                ));
            }
        }
        Ok(())
    }
}

fn require_string(value: &str, field_name: &str, max_length: usize) -> Result<(), PresenceError> {
    if value.is_empty() || value.chars().count() > max_length {
        return Err(PresenceError::new(format!(
            "{field_name} must be a non-empty string of at most {max_length} characters"
        )));
    }
    Ok(())
}

fn is_versioned_identifier(value: &str) -> bool {
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
    fn parses_shared_golden_fixture() {
        let presence = PeerPresence::from_json(include_bytes!(
            "../../../tests/link/fixtures/peer_hello_v1.json"
        ))
        .expect("golden fixture must decode");

        assert_eq!(presence.peer_id, "blender:peer-001");
        assert_eq!(presence.protocol_versions, vec![1]);
        assert_eq!(
            presence.capabilities,
            vec![
                "camera.apply.v1".to_owned(),
                "camera.read.v1".to_owned(),
                "transform.read.v1".to_owned(),
            ]
        );
    }

    #[test]
    fn rejects_unknown_fields_and_unsorted_metadata() {
        let unknown = serde_json::json!({
            "peer_id": "blender:peer-001",
            "application": "Blender",
            "application_version": "4.5.0",
            "plugin_version": "0.1.0",
            "protocol_versions": [1],
            "capabilities": ["camera.read.v1"],
            "unexpected": true,
        });
        assert!(PeerPresence::from_value(&unknown).is_err());

        let unsorted = serde_json::json!({
            "peer_id": "blender:peer-001",
            "application": "Blender",
            "application_version": "4.5.0",
            "plugin_version": "0.1.0",
            "protocol_versions": [2, 1],
            "capabilities": ["camera.read.v1"],
        });
        assert!(PeerPresence::from_value(&unsorted).is_err());
    }

    #[test]
    fn accepts_protocol_upper_bound_and_empty_capabilities() {
        let value = serde_json::json!({
            "peer_id": "blender:peer-001",
            "application": "Blender",
            "application_version": "4.5.0",
            "plugin_version": "0.1.0",
            "protocol_versions": [1, PRESENCE_MAX_PROTOCOL_VERSION],
            "capabilities": [],
        });
        let presence = PeerPresence::from_value(&value).expect("boundary metadata must decode");

        assert_eq!(presence.protocol_versions, vec![1, 65535]);
        assert!(presence.capabilities.is_empty());
    }

    #[test]
    fn rejects_zero_overflow_and_mixed_protocol_or_capability_values() {
        let base = serde_json::json!({
            "peer_id": "blender:peer-001",
            "application": "Blender",
            "application_version": "4.5.0",
            "plugin_version": "0.1.0",
            "protocol_versions": [1],
            "capabilities": [],
        });
        for versions in [
            serde_json::json!([0, 1]),
            serde_json::json!([1, 65536]),
            serde_json::json!([true]),
        ] {
            let mut value = base.clone();
            value["protocol_versions"] = versions;
            assert!(PeerPresence::from_value(&value).is_err());
        }
        for capabilities in [
            serde_json::json!(["camera.read.v1", 1]),
            serde_json::json!([[]]),
        ] {
            let mut value = base.clone();
            value["capabilities"] = capabilities;
            assert!(PeerPresence::from_value(&value).is_err());
        }
    }
}
