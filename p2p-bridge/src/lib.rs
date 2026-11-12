//! EffectCraft mobile peer network.
//!
//! This transport milestone provides persistent identity, same-Wi-Fi mDNS discovery,
//! public Kademlia peer sampling, Circuit Relay v2 reservation probes, periodic health
//! monitoring, AutoNAT and DCUtR. Application account replication is a separate protocol.

use std::{
    collections::{HashMap, HashSet, VecDeque},
    fs,
    path::Path,
    str::FromStr,
    sync::{Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};

use jni::{JNIEnv, objects::{JClass, JString}, sys::jstring};
use libp2p::{
    autonat,
    core::{Multiaddr, multiaddr::Protocol, transport::ListenerId},
    dcutr, identify, identity, kad, mdns, noise, ping, relay, tcp,
    swarm::{NetworkBehaviour, Swarm, SwarmEvent, StreamProtocol},
    SwarmBuilder, yamux, PeerId,
};
use tokio::time::{interval, MissedTickBehavior};

const DHT_PROTOCOL: StreamProtocol = StreamProtocol::new("/ipfs/kad/1.0.0");
const RELAY_HOP_PROTOCOL: StreamProtocol = StreamProtocol::new("/libp2p/circuit/relay/0.2.0/hop");
const ADMIN_SERVICE_KEY: &[u8] = b"/effectcraft/account-authorities/v1";
const BOOTSTRAP_PEERS: [&str; 4] = [
    "QmNnooDu7bfjPFoTZYxMNLWUQJyrVwtbZg5gBMjTezGAJN",
    "QmQCU2EcMqAqQPR2i9bChDtGNJchTbq5TbXJJ16u19uLTa",
    "QmbLHAnMoJPWSCR5Zhtx6BHJX9KiKNN6tpvbUcqanj75Nb",
    "QmcZf59bWwK5XFi76CZX8cbJ4BhTzzA3gU1ZjYZcYW3dwt",
];
const BOOTSTRAP_DNS: &str = "/dnsaddr/bootstrap.libp2p.io";
const MAX_CONCURRENT_RELAY_PROBES: usize = 8;
const DISCOVERY_INTERVAL: Duration = Duration::from_secs(45);
const HEALTH_INTERVAL: Duration = Duration::from_secs(20);
const FAILED_RELAY_COOLDOWN: Duration = Duration::from_secs(5 * 60);

#[derive(NetworkBehaviour)]
struct EffectCraftBehaviour {
    relay_client: relay::client::Behaviour,
    kad: kad::Behaviour<kad::store::MemoryStore>,
    mdns: mdns::tokio::Behaviour,
    autonat: autonat::Behaviour,
    dcutr: dcutr::Behaviour,
    identify: identify::Behaviour,
    ping: ping::Behaviour,
}

#[derive(Default)]
struct NetworkSnapshot {
    started: bool,
    role: String,
    peer_id: String,
    status: String,
    discovered_peers: usize,
    relay_candidates: usize,
    active_relays: usize,
    direct_peers: usize,
    last_error: String,
}

static SNAPSHOT: OnceLock<Mutex<NetworkSnapshot>> = OnceLock::new();

fn snapshot() -> &'static Mutex<NetworkSnapshot> {
    SNAPSHOT.get_or_init(|| Mutex::new(NetworkSnapshot::default()))
}

fn set_snapshot(update: impl FnOnce(&mut NetworkSnapshot)) {
    if let Ok(mut state) = snapshot().lock() {
        update(&mut state);
    }
}

fn json_escape(value: &str) -> String {
    value.replace('\\', "\\\\").replace('"', "\\\"").replace('\n', " ").replace('\r', " ")
}

fn snapshot_json() -> String {
    match snapshot().lock() {
        Ok(state) => format!(
            "{{\"started\":{},\"role\":\"{}\",\"peerId\":\"{}\",\"status\":\"{}\",\"discoveredPeers\":{},\"relayCandidates\":{},\"activeRelays\":{},\"directPeers\":{},\"lastError\":\"{}\"}}",
            state.started,
            json_escape(&state.role),
            json_escape(&state.peer_id),
            json_escape(&state.status),
            state.discovered_peers,
            state.relay_candidates,
            state.active_relays,
            state.direct_peers,
            json_escape(&state.last_error),
        ),
        Err(_) => "{\"started\":false,\"status\":\"state_unavailable\"}".to_string(),
    }
}

fn load_or_create_identity(directory: &Path) -> Result<identity::Keypair, String> {
    fs::create_dir_all(directory).map_err(|e| format!("create identity directory: {e}"))?;
    let path = directory.join("effectcraft-p2p-identity.pb");
    if path.exists() {
        let mut bytes = fs::read(&path).map_err(|e| format!("read node identity: {e}"))?;
        return identity::Keypair::from_protobuf_encoding(&mut bytes)
            .map_err(|e| format!("decode node identity: {e}"));
    }

    let key = identity::Keypair::generate_ed25519();
    let bytes = key.to_protobuf_encoding().map_err(|e| format!("encode node identity: {e}"))?;
    let temporary = directory.join("effectcraft-p2p-identity.pb.tmp");
    fs::write(&temporary, bytes).map_err(|e| format!("save node identity: {e}"))?;
    fs::rename(&temporary, &path).map_err(|e| format!("finalize node identity: {e}"))?;
    Ok(key)
}

fn build_swarm(key: identity::Keypair) -> Result<Swarm<EffectCraftBehaviour>, Box<dyn std::error::Error + Send + Sync>> {
    let swarm = SwarmBuilder::with_existing_identity(key.clone())
        .with_tokio()
        .with_tcp(
            tcp::Config::default().nodelay(true),
            noise::Config::new,
            yamux::Config::default,
        )?
        .with_quic()
        .with_dns()?
        .with_relay_client(noise::Config::new, yamux::Config::default)?
        .with_behaviour(|keypair, relay_client| {
            let peer_id = keypair.public().to_peer_id();
            let mut kad_config = kad::Config::new(DHT_PROTOCOL);
            kad_config.set_query_timeout(Duration::from_secs(45));
            let store = kad::store::MemoryStore::new(peer_id);
            let mdns = mdns::tokio::Behaviour::new(mdns::Config::default(), peer_id)?;
            Ok(EffectCraftBehaviour {
                relay_client,
                kad: kad::Behaviour::with_config(peer_id, store, kad_config),
                mdns,
                autonat: autonat::Behaviour::new(peer_id, autonat::Config::default()),
                dcutr: dcutr::Behaviour::new(peer_id),
                identify: identify::Behaviour::new(
                    identify::Config::new(
                        "/effectcraft/p2p/1.0.0".to_string(),
                        keypair.public(),
                    ).with_push_listen_addr_updates(true),
                ),
                ping: ping::Behaviour::new(ping::Config::new()),
            })
        })?
        .build();
    Ok(swarm)
}

fn start_node(data_directory: &str, is_admin: bool) -> Result<String, String> {
    let directory = Path::new(data_directory).join("effectcraft-p2p");
    let key = load_or_create_identity(&directory)?;
    let peer_id = key.public().to_peer_id().to_string();

    {
        let mut state = snapshot().lock().map_err(|_| "network state is unavailable".to_string())?;
        if state.started {
            return Ok(state.peer_id.clone());
        }
        state.started = true;
        state.role = if is_admin { "admin_authority" } else { "client" }.to_string();
        state.peer_id = peer_id.clone();
        state.status = "starting".to_string();
        state.last_error.clear();
    }

    if let Err(error) = thread::Builder::new()
        .name("effectcraft-p2p".to_string())
        .spawn(move || {
            let runtime = match tokio::runtime::Builder::new_multi_thread()
                .worker_threads(2)
                .enable_all()
                .build()
            {
                Ok(runtime) => runtime,
                Err(error) => {
                    set_snapshot(|state| {
                        state.started = false;
                        state.status = "runtime_error".to_string();
                        state.last_error = error.to_string();
                    });
                    return;
                }
            };
            runtime.block_on(run_node(key, is_admin));
        })
    {
        set_snapshot(|state| {
            state.started = false;
            state.status = "thread_error".to_string();
            state.last_error = error.to_string();
        });
        return Err(format!("start peer network thread: {error}"));
    }

    Ok(peer_id)
}

#[no_mangle]
pub extern "system" fn Java_com_qianqian_effectcraftadmin_NativeP2P_nativeStartAdmin(
    mut env: JNIEnv,
    _class: JClass,
    directory: JString,
) -> jstring {
    let directory = match env.get_string(&directory) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => return new_java_string(&mut env, format!("ERROR:{error}")),
    };
    match start_node(&directory, true) {
        Ok(peer_id) => new_java_string(&mut env, peer_id),
        Err(error) => new_java_string(&mut env, format!("ERROR:{error}")),
    }
}

#[no_mangle]
pub extern "system" fn Java_com_qianqian_effectcraftadmin_NativeP2P_nativeStatus(
    mut env: JNIEnv,
    _class: JClass,
) -> jstring {
    new_java_string(&mut env, snapshot_json())
}

#[no_mangle]
pub extern "system" fn Java_com_artcraft_effectcraft_NativeP2P_nativeStartClient(
    mut env: JNIEnv,
    _class: JClass,
    directory: JString,
) -> jstring {
    let directory = match env.get_string(&directory) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => return new_java_string(&mut env, format!("ERROR:{error}")),
    };
    match start_node(&directory, false) {
        Ok(peer_id) => new_java_string(&mut env, peer_id),
        Err(error) => new_java_string(&mut env, format!("ERROR:{error}")),
    }
}

#[no_mangle]
pub extern "system" fn Java_com_artcraft_effectcraft_NativeP2P_nativeStatus(
    mut env: JNIEnv,
    _class: JClass,
) -> jstring {
    new_java_string(&mut env, snapshot_json())
}

fn new_java_string(env: &mut JNIEnv, value: String) -> jstring {
    match env.new_string(value) {
        Ok(value) => value.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

async fn run_node(key: identity::Keypair, is_admin: bool) {
    let local_peer_id = key.public().to_peer_id();
    let mut swarm = match build_swarm(key) {
        Ok(swarm) => swarm,
        Err(error) => {
            set_snapshot(|state| {
                state.started = false;
                state.status = "transport_error".to_string();
                state.last_error = error.to_string();
            });
            return;
        }
    };

    if let Err(error) = swarm.listen_on("/ip4/0.0.0.0/tcp/0".parse().expect("valid TCP multiaddr")) {
        set_snapshot(|state| state.last_error = format!("TCP listener: {error}"));
    }
    if let Err(error) = swarm.listen_on("/ip4/0.0.0.0/udp/0/quic-v1".parse().expect("valid QUIC multiaddr")) {
        set_snapshot(|state| state.last_error = format!("QUIC listener: {error}"));
    }

    for peer in BOOTSTRAP_PEERS {
        if let Ok(peer_id) = PeerId::from_str(peer) {
            if let Ok(address) = BOOTSTRAP_DNS.parse::<Multiaddr>() {
                swarm.behaviour_mut().kad.add_address(&peer_id, address);
            }
        }
    }
    let _ = swarm.behaviour_mut().kad.bootstrap();
    swarm.behaviour_mut().kad.get_closest_peers(PeerId::random());
    let service_key = kad::RecordKey::new(&ADMIN_SERVICE_KEY);
    if is_admin {
        let _ = swarm.behaviour_mut().kad.start_providing(service_key.clone());
    } else {
        swarm.behaviour_mut().kad.get_providers(service_key.clone());
    }

    let mut candidate_queue: VecDeque<(PeerId, Multiaddr)> = VecDeque::new();
    let mut candidate_addresses: HashMap<PeerId, Multiaddr> = HashMap::new();
    let mut attempting: HashSet<PeerId> = HashSet::new();
    let mut active_relays: HashSet<PeerId> = HashSet::new();
    let mut listener_peers: HashMap<ListenerId, PeerId> = HashMap::new();
    let mut failed_until: HashMap<PeerId, Instant> = HashMap::new();

    let mut discovery_tick = interval(DISCOVERY_INTERVAL);
    discovery_tick.set_missed_tick_behavior(MissedTickBehavior::Delay);
    discovery_tick.tick().await;
    let mut health_tick = interval(HEALTH_INTERVAL);
    health_tick.set_missed_tick_behavior(MissedTickBehavior::Delay);
    health_tick.tick().await;

    set_snapshot(|state| {
        state.status = "discovering_public_relays".to_string();
        state.peer_id = local_peer_id.to_string();
    });

    loop {
        tokio::select! {
            event = futures::StreamExt::next(&mut swarm) => {
                let Some(event) = event else { continue };
                match event {
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::Kad(kad::Event::OutboundQueryProgressed {
                        result: kad::QueryResult::GetClosestPeers(Ok(result)),
                        ..
                    })) => {
                        for peer in result.peers {
                            if peer.peer_id == local_peer_id {
                                continue;
                            }
                            for address in peer.addrs {
                                let address = address.with(Protocol::P2p(peer.peer_id));
                                candidate_addresses.insert(peer.peer_id, address.clone());
                                candidate_queue.push_back((peer.peer_id, address));
                            }
                        }
                        set_snapshot(|state| {
                            state.discovered_peers = candidate_addresses.len();
                            state.relay_candidates = candidate_queue.len() + attempting.len() + active_relays.len();
                        });
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::Mdns(mdns::Event::Discovered(peers))) => {
                        for (peer_id, address) in peers {
                            swarm.behaviour_mut().kad.add_address(&peer_id, address.clone());
                            candidate_addresses.insert(peer_id, address.clone().with(Protocol::P2p(peer_id)));
                            if !swarm.is_connected(&peer_id) && !attempting.contains(&peer_id) {
                                let _ = swarm.dial(address.with(Protocol::P2p(peer_id)));
                            }
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::Identify(identify::Event::Received { peer_id, info, .. })) => {
                        for address in &info.listen_addrs {
                            swarm.behaviour_mut().kad.add_address(&peer_id, address.clone());
                        }

                        let supports_relay_v2 = info.protocols.iter().any(|protocol| protocol == &RELAY_HOP_PROTOCOL);
                        if supports_relay_v2
                            && attempting.contains(&peer_id)
                            && !active_relays.contains(&peer_id)
                            && !listener_peers.values().any(|known| *known == peer_id)
                        {
                            if let Some(address) = candidate_addresses.get(&peer_id).cloned() {
                                match swarm.listen_on(address.with(Protocol::P2pCircuit)) {
                                    Ok(listener_id) => { listener_peers.insert(listener_id, peer_id); }
                                    Err(error) => {
                                        attempting.remove(&peer_id);
                                        failed_until.insert(peer_id, Instant::now() + FAILED_RELAY_COOLDOWN);
                                        set_snapshot(|state| state.last_error = format!("relay reservation start: {error}"));
                                    }
                                }
                            }
                        } else if !supports_relay_v2 {
                            attempting.remove(&peer_id);
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::Kad(kad::Event::OutboundQueryProgressed {
                        result: kad::QueryResult::GetProviders(Ok(kad::GetProvidersOk::FoundProviders { providers, .. })),
                        ..
                    })) => {
                        if !is_admin {
                            for peer_id in providers {
                                if peer_id != local_peer_id && !swarm.is_connected(&peer_id) {
                                    let _ = swarm.dial(libp2p::swarm::dial_opts::DialOpts::peer_id(peer_id).build());
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::RelayClient(
                        relay::client::Event::ReservationReqAccepted { relay_peer_id, .. }
                    )) => {
                        attempting.remove(&relay_peer_id);
                        active_relays.insert(relay_peer_id);
                        set_snapshot(|state| {
                            state.active_relays = active_relays.len();
                            state.status = "public_relays_connected".to_string();
                        });
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::Ping(event)) => {
                        if event.result.is_err() && active_relays.contains(&event.peer) {
                            set_snapshot(|state| state.status = "relay_health_degraded".to_string());
                        }
                    }
                    SwarmEvent::ConnectionEstablished { .. } => {}
                    SwarmEvent::ListenerError { listener_id, error } => {
                        if let Some(peer_id) = listener_peers.remove(&listener_id) {
                            attempting.remove(&peer_id);
                            active_relays.remove(&peer_id);
                            failed_until.insert(peer_id, Instant::now() + FAILED_RELAY_COOLDOWN);
                            set_snapshot(|state| {
                                state.active_relays = active_relays.len();
                                state.last_error = format!("relay {peer_id} unavailable: {error}");
                            });
                        }
                    }
                    SwarmEvent::ListenerClosed { listener_id, .. } => {
                        if let Some(peer_id) = listener_peers.remove(&listener_id) {
                            active_relays.remove(&peer_id);
                            attempting.remove(&peer_id);
                            failed_until.insert(peer_id, Instant::now() + FAILED_RELAY_COOLDOWN);
                            set_snapshot(|state| state.active_relays = active_relays.len());
                        }
                    }
                    SwarmEvent::ConnectionClosed { peer_id, .. } => {
                        if active_relays.remove(&peer_id) {
                            set_snapshot(|state| state.active_relays = active_relays.len());
                        }
                        attempting.remove(&peer_id);
                    }
                    SwarmEvent::OutgoingConnectionError { peer_id: Some(peer_id), .. } => {
                        attempting.remove(&peer_id);
                        failed_until.insert(peer_id, Instant::now() + FAILED_RELAY_COOLDOWN);
                    }
                    _ => {}
                }
            }
            _ = discovery_tick.tick() => {
                let _ = swarm.behaviour_mut().kad.bootstrap();
                swarm.behaviour_mut().kad.get_closest_peers(PeerId::random());
                if !is_admin {
                    swarm.behaviour_mut().kad.get_providers(service_key.clone());
                }
            }
            _ = health_tick.tick() => {
                // Probe candidates in batches to protect mobile radio/battery. Accepted relays
                // are retained independently, so the pool is not fixed to two or another pair.
                let mut started = 0usize;
                while attempting.len() < MAX_CONCURRENT_RELAY_PROBES && started < MAX_CONCURRENT_RELAY_PROBES {
                    let Some((peer_id, address)) = candidate_queue.pop_front() else { break };
                    if active_relays.contains(&peer_id) || attempting.contains(&peer_id) || swarm.is_connected(&peer_id) {
                        continue;
                    }
                    if failed_until.get(&peer_id).is_some_and(|until| *until > Instant::now()) {
                        continue;
                    }
                    attempting.insert(peer_id);
                    match swarm.dial(address) {
                        Ok(()) => started += 1,
                        Err(error) => {
                            attempting.remove(&peer_id);
                            failed_until.insert(peer_id, Instant::now() + FAILED_RELAY_COOLDOWN);
                            set_snapshot(|state| state.last_error = format!("relay candidate dial: {error}"));
                        }
                    }
                }
                let connected = swarm.connected_peers().count();
                set_snapshot(|state| {
                    state.active_relays = active_relays.len();
                    state.direct_peers = connected.saturating_sub(active_relays.len());
                    state.relay_candidates = candidate_queue.len() + attempting.len() + active_relays.len();
                    if state.active_relays == 0 && state.status != "transport_error" {
                        state.status = "searching_and_testing_free_relays".to_string();
                    }
                });
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_json_is_valid_and_escaped() {
        set_snapshot(|state| {
            state.started = true;
            state.peer_id = "node\\\"a".to_string();
            state.status = "testing".to_string();
            state.last_error = "line1\nline2".to_string();
        });
        let value: serde_json::Value = serde_json::from_str(&snapshot_json()).expect("valid JSON");
        assert_eq!(value["started"], true);
        assert_eq!(value["peerId"], "node\\\"a");
        assert_eq!(value["lastError"], "line1 line2");
    }
}
