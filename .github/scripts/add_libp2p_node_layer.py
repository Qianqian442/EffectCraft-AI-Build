#!/usr/bin/env python3
"""Add the native Rust-libp2p transport module to the Android EffectCraft build."""
from __future__ import annotations
import os
from pathlib import Path

MODULE = r'''//! Native cross-network peer transport for EffectCraft.
//!
//! This module is compiled only for native targets. The caller must supply a
//! device-specific Ed25519 secret from Android Keystore-backed storage and
//! authenticated public Circuit Relay v2 multiaddresses obtained from the
//! account service. Never embed relay credentials or private keys in the APK.

use std::str::FromStr;
use std::sync::{Arc, atomic::{AtomicBool, Ordering}};
use std::thread::{self, JoinHandle};
use std::time::Duration;

use futures::StreamExt;
use libp2p::{
    Multiaddr, dcutr, identify, identity, noise, relay, tcp, yamux,
    core::multiaddr::Protocol,
    swarm::{NetworkBehaviour, SwarmEvent},
};

#[derive(NetworkBehaviour)]
struct NodeBehaviour {
    relay_client: relay::client::Behaviour,
    identify: identify::Behaviour,
    dcutr: dcutr::Behaviour,
}

/// A running peer transport. Dropping it stops the swarm loop.
pub(crate) struct NodeRuntime {
    shutdown: Arc<AtomicBool>,
    worker: Option<JoinHandle<()>>,
}

impl NodeRuntime {
    /// Start a peer transport using a persistent device identity and public relay addresses.
    ///
    /// Addresses must be complete relay multiaddresses ending in /p2p/<relay-peer-id>.
    /// An empty relay list is rejected rather than pretending the node is connected.
    pub(crate) fn start(
        secret_key: [u8; 32],
        relay_addresses: Vec<String>,
    ) -> Result<Self, String> {
        if relay_addresses.is_empty() {
            return Err("节点网络尚未配置公网中继地址".to_string());
        }

        let identity = identity::Keypair::ed25519_from_bytes(secret_key)
            .map_err(|error| format!("设备节点身份无效：{error}"))?;
        let shutdown = Arc::new(AtomicBool::new(false));
        let thread_shutdown = shutdown.clone();

        let worker = thread::Builder::new()
            .name("effectcraft-libp2p".to_string())
            .spawn(move || {
                let runtime = match tokio::runtime::Builder::new_current_thread()
                    .enable_all()
                    .build()
                {
                    Ok(runtime) => runtime,
                    Err(error) => {
                        log::error!("Unable to start libp2p runtime: {error}");
                        return;
                    }
                };

                if let Err(error) = runtime.block_on(run_swarm(
                    identity,
                    relay_addresses,
                    thread_shutdown,
                )) {
                    log::error!("EffectCraft peer transport stopped: {error}");
                }
            })
            .map_err(|error| format!("无法启动节点网络线程：{error}"))?;

        Ok(Self {
            shutdown,
            worker: Some(worker),
        })
    }
}

impl Drop for NodeRuntime {
    fn drop(&mut self) {
        self.shutdown.store(true, Ordering::Release);
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

async fn run_swarm(
    identity: identity::Keypair,
    relay_addresses: Vec<String>,
    shutdown: Arc<AtomicBool>,
) -> Result<(), String> {
    let local_peer_id = identity.public().to_peer_id();
    let mut swarm = libp2p::SwarmBuilder::with_existing_identity(identity)
        .with_tokio()
        .with_tcp(
            tcp::Config::default().nodelay(true),
            noise::Config::new,
            yamux::Config::default,
        )
        .map_err(|error| format!("TCP transport setup failed: {error}"))?
        .with_quic()
        .with_dns()
        .map_err(|error| format!("DNS transport setup failed: {error}"))?
        .with_relay_client(noise::Config::new, yamux::Config::default)
        .map_err(|error| format!("Relay client setup failed: {error}"))?
        .with_behaviour(|key, relay_client| NodeBehaviour {
            relay_client,
            identify: identify::Behaviour::new(identify::Config::new(
                "/effectcraft/node/1.0.0".to_string(),
                key.public(),
            )),
            dcutr: dcutr::Behaviour::new(key.public().to_peer_id()),
        })
        .map_err(|error| format!("Peer behaviour setup failed: {error}"))?
        .build();

    let quic_listen: Multiaddr = "/ip4/0.0.0.0/udp/0/quic-v1"
        .parse()
        .map_err(|error| format!("Invalid QUIC listen address: {error}"))?;
    let tcp_listen: Multiaddr = "/ip4/0.0.0.0/tcp/0"
        .parse()
        .map_err(|error| format!("Invalid TCP listen address: {error}"))?;
    swarm.listen_on(quic_listen)
        .map_err(|error| format!("QUIC listen failed: {error}"))?;
    swarm.listen_on(tcp_listen)
        .map_err(|error| format!("TCP listen failed: {error}"))?;

    let mut reservations = 0usize;
    for raw_address in relay_addresses {
        let relay_address = Multiaddr::from_str(&raw_address)
            .map_err(|error| format!("Invalid relay multiaddress: {error}"))?;
        if !relay_address.iter().any(|part| matches!(part, Protocol::P2p(_))) {
            return Err("中继地址缺少 /p2p/<relay-peer-id>".to_string());
        }
        swarm.dial(relay_address.clone())
            .map_err(|error| format!("Relay connection failed: {error}"))?;
        swarm.listen_on(relay_address.with(Protocol::P2pCircuit))
            .map_err(|error| format!("Relay reservation failed: {error}"))?;
        reservations += 1;
    }

    log::info!("EffectCraft libp2p node started: peer={local_peer_id}, relay_reservations={reservations}");

    loop {
        tokio::select! {
            _ = tokio::time::sleep(Duration::from_millis(350)) => {
                if shutdown.load(Ordering::Acquire) {
                    break;
                }
            }
            event = swarm.next() => {
                let Some(event) = event else { break; };
                match event {
                    SwarmEvent::NewListenAddr { address, .. } => {
                        log::info!("EffectCraft peer listening on {address}");
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        log::info!("EffectCraft peer connected: {peer_id}");
                    }
                    SwarmEvent::Behaviour(NodeBehaviourEvent::Dcutr(event)) => {
                        log::info!("EffectCraft direct-connection upgrade: {event:?}");
                    }
                    SwarmEvent::Behaviour(NodeBehaviourEvent::RelayClient(event)) => {
                        log::info!("EffectCraft relay event: {event:?}");
                    }
                    SwarmEvent::Behaviour(NodeBehaviourEvent::Identify(event)) => {
                        log::debug!("EffectCraft identify event: {event:?}");
                    }
                    SwarmEvent::OutgoingConnectionError { peer_id, error, .. } => {
                        log::warn!("EffectCraft peer connection failed ({peer_id:?}): {error}");
                    }
                    _ => {}
                }
            }
        }
    }

    log::info!("EffectCraft libp2p node stopped");
    Ok(())
}
'''

def main() -> None:
    root = Path(os.environ["EFFECTCRAFT_DIR"])
    manifest = root / "crates/ui-egui/Cargo.toml"
    source = root / "crates/ui-egui/src/lib.rs"
    node = root / "crates/ui-egui/src/p2p_node.rs"

    cargo = manifest.read_text(encoding="utf-8")
    marker = "[target.'cfg(not(target_arch = \"wasm32\"))'.dependencies]\n"
    if marker not in cargo:
        raise SystemExit("native dependency section not found in ui-egui/Cargo.toml")
    deps = '''# Cross-network mobile peer transport (native Android/desktop only).
libp2p = { version = "=0.57.1", default-features = false, features = ["tokio", "tcp", "quic", "dns", "noise", "yamux", "relay", "dcutr", "identify", "macros", "ed25519"] }
tokio = { version = "1", features = ["rt", "time", "net", "macros"] }
futures = "0.3"
'''
    if 'libp2p = { version = "=0.57.1"' not in cargo:
        cargo = cargo.replace(marker, marker + deps, 1)
        manifest.write_text(cargo, encoding="utf-8")

    lib = source.read_text(encoding="utf-8")
    mod_line = '#[cfg(not(target_arch = "wasm32"))]\nmod p2p_node;\n'
    if mod_line not in lib:
        anchor = "pub(crate) mod a11y;\n"
        if anchor not in lib:
            raise SystemExit("ui-egui module insertion point not found")
        lib = lib.replace(anchor, anchor + "\n" + mod_line, 1)
        source.write_text(lib, encoding="utf-8")

    if node.exists():
        if node.read_text(encoding="utf-8") != MODULE:
            raise SystemExit("p2p_node.rs already exists with different content")
    else:
        node.write_text(MODULE, encoding="utf-8")

    print("Installed native rust-libp2p peer transport module and pinned dependencies.")

if __name__ == "__main__":
    main()
