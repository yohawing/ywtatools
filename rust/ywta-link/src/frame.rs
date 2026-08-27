//! TCPから独立したYWTA Link v1固定wire frameを提供する。
//!
//! frameは次の順で連結する。整数はすべてbig-endianである。
//!
//! ```text
//! 0..4   magic: "YWTL" (4 bytes)
//! 4..6   protocol version: u16 (1)
//! 6..8   flags: u16 (0)
//! 8..12  JSON header length: u32
//! 12..20 raw binary body length: u64
//! 20..   UTF-8 JSON header, then raw binary body
//! ```

use std::error::Error;
use std::fmt;
use std::io::{self, Read, Write};

use crate::envelope::{Envelope, EnvelopeError};

/// 固定frame先頭のmagic値。
pub const FRAME_MAGIC: [u8; 4] = *b"YWTL";
/// fixed headerが表すProtocol version。
pub const FRAME_PROTOCOL_VERSION: u16 = 1;
/// MVPで許可するflags値。
pub const FRAME_FLAGS: u16 = 0;
/// fixed headerのbyte数。
pub const FIXED_HEADER_LEN: usize = 20;

/// frame受信時に適用する明示的なsize上限。
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FrameLimits {
    pub max_header_len: usize,
    pub max_body_len: usize,
}

impl Default for FrameLimits {
    fn default() -> Self {
        Self {
            max_header_len: 64 * 1024,
            max_body_len: 16 * 1024 * 1024,
        }
    }
}

/// JSON Envelopeと変更しないraw binary bodyを持つframe。
#[derive(Clone, Debug, PartialEq)]
pub struct Frame {
    pub envelope: Envelope,
    pub body: Vec<u8>,
}

/// frameのdecode/encode失敗理由。
#[derive(Debug)]
pub enum FrameError {
    InvalidMagic,
    UnsupportedVersion(u16),
    UnsupportedFlags(u16),
    LengthLimitExceeded,
    LengthOverflow,
    Truncated,
    TrailingBytes,
    Envelope(EnvelopeError),
    Io(io::Error),
}

impl fmt::Display for FrameError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidMagic => formatter.write_str("invalid frame magic"),
            Self::UnsupportedVersion(version) => {
                write!(formatter, "unsupported frame version: {version}")
            }
            Self::UnsupportedFlags(flags) => write!(formatter, "unsupported frame flags: {flags}"),
            Self::LengthLimitExceeded => {
                formatter.write_str("frame length exceeds configured limit")
            }
            Self::LengthOverflow => formatter.write_str("frame length overflows this platform"),
            Self::Truncated => formatter.write_str("truncated frame"),
            Self::TrailingBytes => formatter.write_str("frame contains trailing bytes"),
            Self::Envelope(error) => write!(formatter, "invalid frame envelope: {error}"),
            Self::Io(error) => write!(formatter, "frame I/O error: {error}"),
        }
    }
}

impl Error for FrameError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Envelope(error) => Some(error),
            Self::Io(error) => Some(error),
            _ => None,
        }
    }
}

impl From<EnvelopeError> for FrameError {
    fn from(error: EnvelopeError) -> Self {
        Self::Envelope(error)
    }
}

impl Frame {
    /// 検証済みEnvelopeからframeを作る。
    pub fn new(envelope: Envelope, body: Vec<u8>) -> Result<Self, FrameError> {
        envelope.validate()?;
        Ok(Self { envelope, body })
    }

    /// 固定layoutのbyte列へencodeする。
    pub fn encode(&self, limits: FrameLimits) -> Result<Vec<u8>, FrameError> {
        let header = self.envelope.to_json()?;
        ensure_lengths(header.len(), self.body.len(), limits)?;
        let header_len = u32::try_from(header.len()).map_err(|_| FrameError::LengthOverflow)?;
        let body_len = u64::try_from(self.body.len()).map_err(|_| FrameError::LengthOverflow)?;
        let total_len = FIXED_HEADER_LEN
            .checked_add(header.len())
            .and_then(|value| value.checked_add(self.body.len()))
            .ok_or(FrameError::LengthOverflow)?;
        let mut result = Vec::with_capacity(total_len);
        result.extend_from_slice(&FRAME_MAGIC);
        result.extend_from_slice(&FRAME_PROTOCOL_VERSION.to_be_bytes());
        result.extend_from_slice(&FRAME_FLAGS.to_be_bytes());
        result.extend_from_slice(&header_len.to_be_bytes());
        result.extend_from_slice(&body_len.to_be_bytes());
        result.extend_from_slice(&header);
        result.extend_from_slice(&self.body);
        Ok(result)
    }

    /// 1個だけを含むbyte列からframeをdecodeする。
    pub fn decode(input: &[u8], limits: FrameLimits) -> Result<Self, FrameError> {
        if input.len() < FIXED_HEADER_LEN {
            return Err(FrameError::Truncated);
        }
        let (header_len, body_len) = decode_fixed_header(&input[..FIXED_HEADER_LEN], limits)?;
        let expected_len = FIXED_HEADER_LEN
            .checked_add(header_len)
            .and_then(|value| value.checked_add(body_len))
            .ok_or(FrameError::LengthOverflow)?;
        if input.len() < expected_len {
            return Err(FrameError::Truncated);
        }
        if input.len() > expected_len {
            return Err(FrameError::TrailingBytes);
        }
        let header_end = FIXED_HEADER_LEN + header_len;
        let envelope = Envelope::from_json(&input[FIXED_HEADER_LEN..header_end])?;
        Ok(Self {
            envelope,
            body: input[header_end..].to_vec(),
        })
    }

    /// 任意のRead実装から正確に1個のframeを読む。
    pub fn read_from(reader: &mut impl Read, limits: FrameLimits) -> Result<Self, FrameError> {
        let mut fixed_header = [0_u8; FIXED_HEADER_LEN];
        read_exact(reader, &mut fixed_header)?;
        let (header_len, body_len) = decode_fixed_header(&fixed_header, limits)?;
        let mut header = vec![0_u8; header_len];
        let mut body = vec![0_u8; body_len];
        read_exact(reader, &mut header)?;
        read_exact(reader, &mut body)?;
        let envelope = Envelope::from_json(&header)?;
        Ok(Self { envelope, body })
    }

    /// 任意のWrite実装へ正確に1個のframeを書く。
    pub fn write_to(&self, writer: &mut impl Write, limits: FrameLimits) -> Result<(), FrameError> {
        writer
            .write_all(&self.encode(limits)?)
            .map_err(FrameError::Io)
    }
}

fn decode_fixed_header(
    fixed_header: &[u8],
    limits: FrameLimits,
) -> Result<(usize, usize), FrameError> {
    if fixed_header[..4] != FRAME_MAGIC {
        return Err(FrameError::InvalidMagic);
    }
    let version = u16::from_be_bytes([fixed_header[4], fixed_header[5]]);
    if version != FRAME_PROTOCOL_VERSION {
        return Err(FrameError::UnsupportedVersion(version));
    }
    let flags = u16::from_be_bytes([fixed_header[6], fixed_header[7]]);
    if flags != FRAME_FLAGS {
        return Err(FrameError::UnsupportedFlags(flags));
    }
    let header_len = u32::from_be_bytes([
        fixed_header[8],
        fixed_header[9],
        fixed_header[10],
        fixed_header[11],
    ]);
    let body_len = u64::from_be_bytes([
        fixed_header[12],
        fixed_header[13],
        fixed_header[14],
        fixed_header[15],
        fixed_header[16],
        fixed_header[17],
        fixed_header[18],
        fixed_header[19],
    ]);
    let header_len = usize::try_from(header_len).map_err(|_| FrameError::LengthOverflow)?;
    let body_len = usize::try_from(body_len).map_err(|_| FrameError::LengthOverflow)?;
    ensure_lengths(header_len, body_len, limits)?;
    Ok((header_len, body_len))
}

fn ensure_lengths(
    header_len: usize,
    body_len: usize,
    limits: FrameLimits,
) -> Result<(), FrameError> {
    if header_len > limits.max_header_len || body_len > limits.max_body_len {
        return Err(FrameError::LengthLimitExceeded);
    }
    Ok(())
}

fn read_exact(reader: &mut impl Read, buffer: &mut [u8]) -> Result<(), FrameError> {
    reader.read_exact(buffer).map_err(|error| {
        if error.kind() == io::ErrorKind::UnexpectedEof {
            FrameError::Truncated
        } else {
            FrameError::Io(error)
        }
    })
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use serde_json::json;

    use super::*;
    use crate::envelope::{Envelope, MessageType};

    fn publish_frame() -> Frame {
        Frame::new(
            Envelope {
                protocol_version: 1,
                message_id: "message-001".to_owned(),
                message_type: MessageType::Publish,
                sender: "blender:peer-001".to_owned(),
                room: Some("shot-010".to_owned()),
                target: None,
                topic: None,
                correlation_id: None,
                schema: Some("ywta.sync.preview.v1".to_owned()),
                body: Some(json!({ "revision": 8 })),
                extra: Default::default(),
            },
            vec![0, 1, 2, 255],
        )
        .expect("test frame must be valid")
    }

    #[test]
    fn frame_round_trips_raw_binary_body() {
        let frame = publish_frame();
        let encoded = frame
            .encode(FrameLimits::default())
            .expect("encode must succeed");

        assert_eq!(
            Frame::decode(&encoded, FrameLimits::default()).expect("decode must succeed"),
            frame
        );
    }

    #[test]
    fn frame_matches_golden_hex_fixture() {
        let expected = decode_hex(include_str!(
            "../../../protocol/ywta-link/v1/valid/frame-publish.hex"
        ));
        let actual = publish_frame()
            .encode(FrameLimits::default())
            .expect("encode must succeed");

        assert_eq!(actual, expected);
        assert_eq!(
            Frame::decode(&expected, FrameLimits::default()).expect("fixture must decode"),
            publish_frame()
        );
    }

    #[test]
    fn frame_rejects_bad_magic_version_flags_and_lengths() {
        let encoded = publish_frame()
            .encode(FrameLimits::default())
            .expect("encode must succeed");

        let mut bad_magic = encoded.clone();
        bad_magic[0] = b'X';
        assert!(matches!(
            Frame::decode(&bad_magic, FrameLimits::default()),
            Err(FrameError::InvalidMagic)
        ));

        let mut bad_version = encoded.clone();
        bad_version[4..6].copy_from_slice(&2_u16.to_be_bytes());
        assert!(matches!(
            Frame::decode(&bad_version, FrameLimits::default()),
            Err(FrameError::UnsupportedVersion(2))
        ));

        let mut bad_flags = encoded.clone();
        bad_flags[6..8].copy_from_slice(&1_u16.to_be_bytes());
        assert!(matches!(
            Frame::decode(&bad_flags, FrameLimits::default()),
            Err(FrameError::UnsupportedFlags(1))
        ));

        let mut bad_length = encoded;
        bad_length[8..12].copy_from_slice(&u32::MAX.to_be_bytes());
        assert!(matches!(
            Frame::decode(&bad_length, FrameLimits::default()),
            Err(FrameError::LengthLimitExceeded)
        ));
    }

    #[test]
    fn frame_rejects_truncated_and_invalid_header_bytes() {
        let encoded = publish_frame()
            .encode(FrameLimits::default())
            .expect("encode must succeed");
        assert!(matches!(
            Frame::decode(&encoded[..encoded.len() - 1], FrameLimits::default()),
            Err(FrameError::Truncated)
        ));
        assert!(matches!(
            Frame::read_from(&mut Cursor::new(&encoded[..10]), FrameLimits::default()),
            Err(FrameError::Truncated)
        ));

        let mut invalid_header = Vec::new();
        invalid_header.extend_from_slice(&FRAME_MAGIC);
        invalid_header.extend_from_slice(&FRAME_PROTOCOL_VERSION.to_be_bytes());
        invalid_header.extend_from_slice(&FRAME_FLAGS.to_be_bytes());
        invalid_header.extend_from_slice(&1_u32.to_be_bytes());
        invalid_header.extend_from_slice(&0_u64.to_be_bytes());
        invalid_header.push(0xff);
        assert!(matches!(
            Frame::decode(&invalid_header, FrameLimits::default()),
            Err(FrameError::Envelope(_))
        ));
    }

    fn decode_hex(text: &str) -> Vec<u8> {
        let text = text.trim();
        assert_eq!(text.len() % 2, 0, "fixture must have whole bytes");
        (0..text.len())
            .step_by(2)
            .map(|index| u8::from_str_radix(&text[index..index + 2], 16))
            .collect::<Result<Vec<_>, _>>()
            .expect("fixture must contain only hexadecimal digits")
    }
}
