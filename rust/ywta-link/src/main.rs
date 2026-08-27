//! `ywta-link` BrokerとCLI Monitorの入口。

use std::env;
use std::net::SocketAddr;
use std::path::PathBuf;
use std::process;
use std::time::Duration;

use ywta_link::broker::{BrokerConfig, BrokerServer};
use ywta_link::monitor;
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
    let remaining = arguments.collect::<Vec<_>>();
    if command == "--help" || command == "-h" {
        if !remaining.is_empty() {
            return Err(usage());
        }
        println!("{}", usage());
        return Ok(());
    }
    match command.as_str() {
        "serve" => {
            if remaining.len() == 1 && matches!(remaining[0].as_str(), "--help" | "-h") {
                println!("{}", usage());
                return Ok(());
            }
            run_serve(remaining.into_iter())
        }
        "status" | "peers" | "rooms" => {
            if remaining.len() == 1 && matches!(remaining[0].as_str(), "--help" | "-h") {
                println!("{}", monitor::usage());
                return Ok(());
            }
            monitor::run_cli(&command, &remaining)
                .map_err(|error| error.to_string())
                .map(|output| {
                    println!("{output}");
                })
        }
        _ => Err(usage()),
    }
}

fn run_serve(arguments: impl Iterator<Item = String>) -> Result<(), String> {
    let mut arguments = arguments.peekable();
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
    "usage: ywta-link <serve|status|peers|rooms> [options]".to_owned()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn monitor_help_only_succeeds_for_the_exact_help_argument() {
        assert!(
            run(["status".to_owned(), "--bad".to_owned(), "--help".to_owned()].into_iter())
                .is_err()
        );
        assert!(run(["status".to_owned(), "--help".to_owned()].into_iter()).is_ok());
        assert!(run([
            "status".to_owned(),
            "--help".to_owned(),
            "--json".to_owned()
        ]
        .into_iter())
        .is_err());
        assert!(
            run(["serve".to_owned(), "--bad".to_owned(), "--help".to_owned()].into_iter()).is_err()
        );
        assert!(
            run(["serve".to_owned(), "--help".to_owned(), "--json".to_owned()].into_iter())
                .is_err()
        );
        assert!(run(["--help".to_owned(), "extra".to_owned()].into_iter()).is_err());
    }
}
