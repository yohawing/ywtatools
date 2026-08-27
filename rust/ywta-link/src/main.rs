//! `ywta-link serve` の最小CLI入口。

use std::env;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::process;
use std::time::Duration;

use ywta_link::broker::{BrokerConfig, BrokerServer};
use ywta_link::runtime::{RuntimeLease, RuntimeManifest};

fn main() {
    if let Err(error) = run(env::args().skip(1)) {
        eprintln!("ywta-link: {error}");
        process::exit(2);
    }
}

fn run(arguments: impl Iterator<Item = String>) -> Result<(), String> {
    let mut arguments = arguments.peekable();
    let Some(command) = arguments.next() else {
        return Err(usage());
    };
    if command == "--help" || command == "-h" {
        println!("{}", usage());
        return Ok(());
    }
    if command != "serve" {
        return Err(usage());
    }

    let mut config = BrokerConfig::default();
    let mut runtime_file = None;
    while let Some(option) = arguments.next() {
        match option.as_str() {
            "--bind" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| "--bind requires an address".to_owned())?;
                config.bind_addr = value
                    .parse::<SocketAddr>()
                    .map_err(|_| "--bind must be a numeric socket address".to_owned())?;
            }
            "--idle-timeout" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| "--idle-timeout requires seconds".to_owned())?;
                let seconds = value
                    .parse::<u64>()
                    .map_err(|_| "--idle-timeout must be a non-negative integer".to_owned())?;
                config.idle_timeout = Duration::from_secs(seconds);
            }
            "--runtime-file" => {
                let value = arguments
                    .next()
                    .ok_or_else(|| "--runtime-file requires an absolute path".to_owned())?;
                let path = PathBuf::from(value);
                if !path.is_absolute() {
                    return Err("--runtime-file must be an absolute path".to_owned());
                }
                runtime_file = Some(path);
            }
            "--help" | "-h" => {
                println!("{}", usage());
                return Ok(());
            }
            _ => return Err(usage()),
        }
    }

    let mut server = BrokerServer::bind(config).map_err(|error| error.to_string())?;
    let endpoint = server.local_addr().map_err(|error| error.to_string())?;
    let _runtime_lease = if let Some(path) = runtime_file {
        let manifest =
            RuntimeManifest::for_endpoint(endpoint).map_err(|error| error.to_string())?;
        server.set_runtime_token(manifest.token.clone());
        Some(RuntimeLease::claim(path, manifest).map_err(|error| error.to_string())?)
    } else {
        None
    };
    println!("YWTA_LINK_ENDPOINT={endpoint}");
    server.run().map_err(|error| error.to_string())
}

fn usage() -> String {
    "usage: ywta-link serve [--bind 127.0.0.1:0] [--idle-timeout seconds] [--runtime-file absolute-path]"
        .to_owned()
}
