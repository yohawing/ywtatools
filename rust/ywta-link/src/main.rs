//! `ywta-link serve` の最小CLI入口。

use std::env;
use std::net::SocketAddr;
use std::process;
use std::time::Duration;

use ywta_link::broker::{BrokerConfig, BrokerServer};

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
            "--help" | "-h" => {
                println!("{}", usage());
                return Ok(());
            }
            _ => return Err(usage()),
        }
    }

    let mut server = BrokerServer::bind(config).map_err(|error| error.to_string())?;
    let endpoint = server.local_addr().map_err(|error| error.to_string())?;
    println!("YWTA_LINK_ENDPOINT={endpoint}");
    server.run().map_err(|error| error.to_string())
}

fn usage() -> String {
    "usage: ywta-link serve [--bind 127.0.0.1:0] [--idle-timeout seconds]".to_owned()
}
