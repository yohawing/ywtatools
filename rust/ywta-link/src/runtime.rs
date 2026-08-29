//! Broker endpointを短命に公開するruntime manifestを提供する。

use std::error::Error;
use std::fmt;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

const MAX_RUNTIME_MANIFEST_BYTES: usize = 4096;
const MAX_RUNTIME_TOKEN_BYTES: usize = 256;

/// runtime fileへ保存する、接続先Brokerの最小情報。
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeManifest {
    pub protocol_version: u16,
    pub endpoint: String,
    pub pid: u32,
    pub token: String,
}

/// runtime manifestのclaimまたは検証失敗。
#[derive(Debug)]
pub enum RuntimeError {
    RuntimePathMustBeAbsolute,
    RuntimeFileAlreadyClaimed,
    InvalidManifest(String),
    Io(io::Error),
    Json(serde_json::Error),
}

impl fmt::Display for RuntimeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::RuntimePathMustBeAbsolute => {
                formatter.write_str("runtime file path must be absolute")
            }
            Self::RuntimeFileAlreadyClaimed => {
                formatter.write_str("runtime file is already claimed")
            }
            Self::InvalidManifest(reason) => {
                write!(formatter, "invalid runtime manifest: {reason}")
            }
            Self::Io(error) => write!(formatter, "runtime I/O error: {error}"),
            Self::Json(error) => write!(formatter, "runtime JSON error: {error}"),
        }
    }
}

impl Error for RuntimeError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Json(error) => Some(error),
            _ => None,
        }
    }
}

/// runtime fileの排他的所有権。Drop時に自身のmanifestだけを解放する。
#[derive(Debug)]
pub struct RuntimeLease {
    path: PathBuf,
    token: String,
}

impl RuntimeManifest {
    /// loopback endpointを持つ現在process用manifestを作る。
    pub fn for_endpoint(endpoint: SocketAddr) -> Result<Self, RuntimeError> {
        if !endpoint.ip().is_loopback() {
            return Err(RuntimeError::InvalidManifest(
                "endpoint must be numeric loopback".to_owned(),
            ));
        }
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap_or_default()
            .as_nanos();
        Ok(Self {
            protocol_version: 1,
            endpoint: endpoint.to_string(),
            pid: std::process::id(),
            token: format!("{}-{timestamp}", std::process::id()),
        })
    }

    /// JSON byte列をparseして、Broker接続に使える値だけを受け入れる。
    pub fn from_json(json: &[u8]) -> Result<Self, RuntimeError> {
        if json.len() > MAX_RUNTIME_MANIFEST_BYTES {
            return Err(RuntimeError::InvalidManifest(
                "runtime manifest exceeds 4 KiB".to_owned(),
            ));
        }
        let manifest: Self = serde_json::from_slice(json).map_err(RuntimeError::Json)?;
        manifest.validate()?;
        Ok(manifest)
    }

    /// runtime fileからcompleteなmanifestだけを読む。
    pub fn read(path: impl AsRef<Path>) -> Result<Self, RuntimeError> {
        let mut json = Vec::new();
        File::open(path)
            .map_err(RuntimeError::Io)?
            .take((MAX_RUNTIME_MANIFEST_BYTES + 1) as u64)
            .read_to_end(&mut json)
            .map_err(RuntimeError::Io)?;
        Self::from_json(&json)
    }

    /// manifestがv1のnumeric loopback endpointを持つか検証する。
    pub fn validate(&self) -> Result<(), RuntimeError> {
        if self.protocol_version != 1 {
            return Err(RuntimeError::InvalidManifest(
                "protocol_version must be 1".to_owned(),
            ));
        }
        if self.pid == 0
            || self.token.is_empty()
            || self.token.len() > MAX_RUNTIME_TOKEN_BYTES
            || !self
                .token
                .bytes()
                .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
        {
            return Err(RuntimeError::InvalidManifest(
                "pid must be non-zero and token must be 1 to 256 filename-safe ASCII bytes"
                    .to_owned(),
            ));
        }
        let endpoint = self.endpoint.parse::<SocketAddr>().map_err(|_| {
            RuntimeError::InvalidManifest("endpoint must be a numeric socket address".to_owned())
        })?;
        if !endpoint.ip().is_loopback() {
            return Err(RuntimeError::InvalidManifest(
                "endpoint must be loopback".to_owned(),
            ));
        }
        Ok(())
    }
}

impl RuntimeLease {
    /// manifestを一度だけhard linkして排他的にclaimする。
    pub fn claim(
        runtime_path: impl AsRef<Path>,
        manifest: RuntimeManifest,
    ) -> Result<Self, RuntimeError> {
        manifest.validate()?;
        let runtime_path = runtime_path.as_ref();
        if !runtime_path.is_absolute() {
            return Err(RuntimeError::RuntimePathMustBeAbsolute);
        }
        let parent = runtime_path.parent().ok_or_else(|| {
            RuntimeError::InvalidManifest("runtime file has no parent directory".to_owned())
        })?;
        fs::create_dir_all(parent).map_err(RuntimeError::Io)?;
        let temporary_path = temporary_path(runtime_path, &manifest.token)?;
        let claim_result = write_temporary_manifest(&temporary_path, &manifest).and_then(|_| {
            fs::hard_link(&temporary_path, runtime_path).map_err(|error| {
                if error.kind() == io::ErrorKind::AlreadyExists {
                    RuntimeError::RuntimeFileAlreadyClaimed
                } else {
                    RuntimeError::Io(error)
                }
            })
        });
        let _ = fs::remove_file(&temporary_path);
        claim_result?;
        Ok(Self {
            path: runtime_path.to_owned(),
            token: manifest.token,
        })
    }

    /// leaseが所有するruntime file pathを返す。
    pub fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for RuntimeLease {
    fn drop(&mut self) {
        let should_remove =
            RuntimeManifest::read(&self.path).is_ok_and(|manifest| manifest.token == self.token);
        if should_remove {
            let _ = fs::remove_file(&self.path);
        }
    }
}

fn temporary_path(runtime_path: &Path, token: &str) -> Result<PathBuf, RuntimeError> {
    let file_name = runtime_path
        .file_name()
        .ok_or_else(|| RuntimeError::InvalidManifest("runtime file has no filename".to_owned()))?;
    let parent = runtime_path.parent().expect("absolute path has a parent");
    Ok(parent.join(format!(".{}.{}.tmp", file_name.to_string_lossy(), token)))
}

fn write_temporary_manifest(path: &Path, manifest: &RuntimeManifest) -> Result<(), RuntimeError> {
    let json = serde_json::to_vec(manifest).map_err(RuntimeError::Json)?;
    let mut file: File = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(RuntimeError::Io)?;
    file.write_all(&json).map_err(RuntimeError::Io)?;
    file.sync_all().map_err(RuntimeError::Io)
}

#[cfg(test)]
mod tests {
    use std::sync::{mpsc, Arc, Barrier};
    use std::thread;

    use super::*;

    fn test_directory(name: &str) -> PathBuf {
        let timestamp = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock must be after epoch")
            .as_nanos();
        std::env::temp_dir().join(format!(
            "ywta-link-runtime-{name}-{}-{timestamp}",
            std::process::id()
        ))
    }

    fn manifest() -> RuntimeManifest {
        RuntimeManifest::for_endpoint("127.0.0.1:34567".parse().expect("address must parse"))
            .expect("loopback manifest must be valid")
    }

    #[test]
    fn manifest_read_and_token_are_bounded() {
        let directory = test_directory("bounded-manifest");
        fs::create_dir_all(&directory).expect("test directory must exist");
        let path = directory.join("runtime.json");
        fs::write(&path, vec![b' '; MAX_RUNTIME_MANIFEST_BYTES + 1])
            .expect("oversized fixture must write");
        assert!(matches!(
            RuntimeManifest::read(&path),
            Err(RuntimeError::InvalidManifest(message)) if message.contains("4 KiB")
        ));

        let mut invalid_token = manifest();
        invalid_token.token = "x".repeat(MAX_RUNTIME_TOKEN_BYTES + 1);
        assert!(matches!(
            invalid_token.validate(),
            Err(RuntimeError::InvalidManifest(_))
        ));
        invalid_token.token = "unsafe/path".to_owned();
        assert!(matches!(
            invalid_token.validate(),
            Err(RuntimeError::InvalidManifest(_))
        ));
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn concurrent_claim_has_exactly_one_winner() {
        let directory = test_directory("concurrent");
        let path = directory.join("runtime.json");
        let barrier = Arc::new(Barrier::new(2));
        let (sender, receiver) = mpsc::channel();
        let mut workers = Vec::new();
        for _ in 0..2 {
            let path = path.clone();
            let barrier = Arc::clone(&barrier);
            let sender = sender.clone();
            workers.push(thread::spawn(move || {
                barrier.wait();
                let _ = sender.send(RuntimeLease::claim(path, manifest()));
            }));
        }
        drop(sender);
        for worker in workers {
            worker.join().expect("claim worker must not panic");
        }
        let results = receiver.into_iter().collect::<Vec<_>>();
        let leases = results
            .into_iter()
            .filter_map(Result::ok)
            .collect::<Vec<_>>();

        assert_eq!(leases.len(), 1);
        assert!(RuntimeManifest::read(&path).is_ok());
        drop(leases);
        fs::remove_dir_all(&directory).expect("remove exact test directory");
    }

    #[test]
    fn manifest_is_complete_and_competing_claim_is_rejected() {
        let directory = test_directory("complete");
        let path = directory.join("runtime.json");
        let lease = RuntimeLease::claim(&path, manifest()).expect("first claim must succeed");
        let loaded = RuntimeManifest::read(&path).expect("manifest must be parseable");

        assert_eq!(loaded.protocol_version, 1);
        assert_eq!(loaded.endpoint, "127.0.0.1:34567");
        assert!(matches!(
            RuntimeLease::claim(&path, manifest()),
            Err(RuntimeError::RuntimeFileAlreadyClaimed)
        ));
        drop(lease);
        fs::remove_dir_all(&directory).expect("remove exact test directory");
    }

    #[test]
    fn replaced_token_survives_owner_drop() {
        let directory = test_directory("replacement");
        let path = directory.join("runtime.json");
        let lease = RuntimeLease::claim(&path, manifest()).expect("claim must succeed");
        let mut replacement = manifest();
        replacement.token = "replacement-token".to_owned();
        fs::write(
            &path,
            serde_json::to_vec(&replacement).expect("manifest JSON must encode"),
        )
        .expect("test replacement must write");

        drop(lease);

        assert!(path.exists());
        fs::remove_dir_all(&directory).expect("remove exact test directory");
    }

    #[test]
    fn owner_drop_removes_its_manifest() {
        let directory = test_directory("drop");
        let path = directory.join("runtime.json");
        let lease = RuntimeLease::claim(&path, manifest()).expect("claim must succeed");

        assert_eq!(lease.path(), path);
        drop(lease);
        assert!(!path.exists());
        fs::remove_dir_all(&directory).expect("remove exact test directory");
    }
}
