//! EffectCraft mobile peer network.
//!
//! This transport milestone provides persistent identity, same-Wi-Fi mDNS discovery,
//! public Kademlia peer sampling, Circuit Relay v2 reservation probes, periodic health
//! monitoring, AutoNAT and DCUtR. Application account replication is a separate protocol.

use std::{
    collections::{HashMap, HashSet, VecDeque},
    fs,
    io::{BufRead, BufReader, Write},
    net::{SocketAddr, TcpListener, TcpStream},
    path::Path,
    str::FromStr,
    sync::{atomic::{AtomicBool, Ordering}, mpsc as std_mpsc, Mutex, OnceLock},
    thread,
    time::{Duration, Instant},
};

use jni::{JNIEnv, objects::{JClass, JString}, sys::jstring};
use libp2p::{
    autonat,
    core::{Multiaddr, multiaddr::Protocol, transport::ListenerId},
    dcutr, identify, identity, kad, mdns, noise, ping, relay, tcp,
    request_response::{self, ProtocolSupport, Message as RpcMessage},
    swarm::{NetworkBehaviour, Swarm, SwarmEvent, StreamProtocol},
    SwarmBuilder, yamux, PeerId,
};
use serde::{Deserialize, Serialize};
use tokio::{sync::mpsc::{self, UnboundedReceiver, UnboundedSender}, time::{interval, MissedTickBehavior}};

mod vpn_stream;
mod vpn_proxy;

const DHT_PROTOCOL: StreamProtocol = StreamProtocol::new("/ipfs/kad/1.0.0");
const RELAY_HOP_PROTOCOL: StreamProtocol = StreamProtocol::new("/libp2p/circuit/relay/0.2.0/hop");
const ACCOUNT_RPC_PROTOCOL: StreamProtocol = StreamProtocol::new("/effectcraft/account-api/1.0.0");
const ADMIN_AGENT_VERSION: &str = "/effectcraft/account-admin/1.0.0";
const CLIENT_AGENT_VERSION: &str = "/effectcraft/account-client/1.0.0";
const ADMIN_SERVICE_KEY: &[u8] = b"/effectcraft/account-authorities/v1";
const CLIENT_RPC_PROXY: SocketAddr = SocketAddr::new(std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST), 8789);
const ADMIN_ACCOUNT_BRIDGE: SocketAddr = SocketAddr::new(std::net::IpAddr::V4(std::net::Ipv4Addr::LOCALHOST), 8788);

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AccountRpcRequest {
    method: String,
    path: String,
    #[serde(default)]
    token: String,
    #[serde(default)]
    body: String,
    #[serde(default)]
    preferred_peer_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
struct AccountRpcResponse {
    status: u16,
    body: String,
}

enum RpcCommand {
    Request {
        request: AccountRpcRequest,
        reply: std_mpsc::Sender<Result<AccountRpcResponse, String>>,
    },
    Shutdown,
}

static RPC_COMMAND_TX: OnceLock<Mutex<Option<UnboundedSender<RpcCommand>>>> = OnceLock::new();
static CLIENT_RPC_PROXY_STARTED: AtomicBool = AtomicBool::new(false);
static CLIENT_DATA_DIRECTORY: OnceLock<Mutex<Option<String>>> = OnceLock::new();

fn client_data_directory() -> &'static Mutex<Option<String>> {
    CLIENT_DATA_DIRECTORY.get_or_init(|| Mutex::new(None))
}

fn rpc_command_slot() -> &'static Mutex<Option<UnboundedSender<RpcCommand>>> {
    RPC_COMMAND_TX.get_or_init(|| Mutex::new(None))
}

fn current_rpc_command_tx() -> Option<UnboundedSender<RpcCommand>> {
    rpc_command_slot().lock().ok().and_then(|slot| slot.as_ref().cloned())
}

fn clear_rpc_command_tx() {
    if let Ok(mut slot) = rpc_command_slot().lock() {
        *slot = None;
    }
}

fn stop_node() {
    let sender = rpc_command_slot().lock().ok().and_then(|mut slot| slot.take());
    if let Some(sender) = sender {
        let _ = sender.send(RpcCommand::Shutdown);
        let deadline = Instant::now() + Duration::from_secs(3);
        while Instant::now() < deadline {
            let stopped = snapshot().lock().map(|state| !state.started).unwrap_or(true);
            if stopped { return; }
            thread::sleep(Duration::from_millis(20));
        }
        set_snapshot(|state| {
            state.last_error = "P2P 节点停止确认超时；后台线程正在退出".to_string();
        });
    } else {
        set_snapshot(|state| {
            state.started = false;
            state.status = "stopped".to_string();
            state.active_relays = 0;
            state.direct_peers = 0;
            state.relay_candidates = 0;
        });
    }
}
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
    account_rpc: request_response::json::Behaviour<AccountRpcRequest, AccountRpcResponse>,
    vpn_stream: libp2p_stream::Behaviour,
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

fn build_swarm(key: identity::Keypair, is_admin: bool) -> Result<Swarm<EffectCraftBehaviour>, Box<dyn std::error::Error + Send + Sync>> {
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
                        if is_admin { ADMIN_AGENT_VERSION } else { CLIENT_AGENT_VERSION }.to_string(),
                        keypair.public(),
                    ).with_push_listen_addr_updates(true),
                ),
                ping: ping::Behaviour::new(ping::Config::new()),
                account_rpc: request_response::json::Behaviour::<AccountRpcRequest, AccountRpcResponse>::new(
                    [(ACCOUNT_RPC_PROTOCOL, ProtocolSupport::Full)],
                    request_response::Config::default(),
                ),
                vpn_stream: libp2p_stream::Behaviour::new(),
            })
        })?
        .build();
    Ok(swarm)
}

fn start_node(data_directory: &str, is_admin: bool) -> Result<String, String> {
    if !is_admin {
        if let Ok(mut saved) = client_data_directory().lock() {
            *saved = Some(data_directory.to_string());
        }
    }
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
        state.discovered_peers = 0;
        state.relay_candidates = 0;
        state.active_relays = 0;
        state.direct_peers = 0;
    }

    let (command_tx, command_rx) = mpsc::unbounded_channel::<RpcCommand>();
    {
        let mut slot = rpc_command_slot().lock().map_err(|_| "P2P command channel is unavailable".to_string())?;
        *slot = Some(command_tx);
    }

    if !is_admin {
        if let Err(error) = start_client_rpc_proxy() {
            clear_rpc_command_tx();
            set_snapshot(|state| {
                state.started = false;
                state.status = "rpc_proxy_error".to_string();
                state.last_error = error.to_string();
            });
            return Err(error);
        }
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
                    clear_rpc_command_tx();
                    set_snapshot(|state| {
                        state.started = false;
                        state.status = "runtime_error".to_string();
                        state.last_error = error.to_string();
                    });
                    return;
                }
            };
            runtime.block_on(run_node(key, is_admin, command_rx));
        })
    {
        clear_rpc_command_tx();
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
pub extern "system" fn Java_com_qianqian_effectcraftadmin_NativeP2P_nativeStopAdmin(
    mut env: JNIEnv,
    _class: JClass,
) -> jstring {
    stop_node();
    new_java_string(&mut env, "OK".to_string())
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

#[no_mangle]
pub extern "system" fn Java_com_artcraft_effectcraft_NativeP2P_nativeConfigureVpnProxy(
    mut env: JNIEnv,
    _class: JClass,
    host: JString,
    ip_csv: JString,
    secret: JString,
) -> jstring {
    let host = match env.get_string(&host) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => return new_java_string(&mut env, format!("ERROR:Worker hostname: {error}")),
    };
    let ip_csv = match env.get_string(&ip_csv) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => return new_java_string(&mut env, format!("ERROR:Worker IP list: {error}")),
    };
    let secret = match env.get_string(&secret) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => return new_java_string(&mut env, format!("ERROR:SOCKS5 secret: {error}")),
    };
    match vpn_proxy::configure_worker(&host, &ip_csv, &secret) {
        Ok(()) => new_java_string(&mut env, "OK".to_string()),
        Err(error) => new_java_string(&mut env, format!("ERROR:{error}")),
    }
}

fn new_java_string(env: &mut JNIEnv, value: String) -> jstring {
    match env.new_string(value) {
        Ok(value) => value.into_raw(),
        Err(_) => std::ptr::null_mut(),
    }
}

async fn run_node(key: identity::Keypair, is_admin: bool, mut commands: UnboundedReceiver<RpcCommand>) {
    let local_peer_id = key.public().to_peer_id();
    let mut swarm = match build_swarm(key, is_admin) {
        Ok(swarm) => swarm,
        Err(error) => {
            clear_rpc_command_tx();
            set_snapshot(|state| {
                state.started = false;
                state.status = "transport_error".to_string();
                state.last_error = error.to_string();
            });
            return;
        }
    };

    let mut vpn_control = swarm.behaviour().vpn_stream.new_control();
    let mut incoming_vpn_streams = vpn_control
        .accept(StreamProtocol::new(vpn_stream::PROTOCOL_NAME))
        .expect("VPN stream protocol is registered only once");
    let vpn_stream_slots = std::sync::Arc::new(tokio::sync::Semaphore::new(4));

    if !is_admin {
        let control = vpn_control.clone();
        tokio::spawn(async move {
            if let Err(error) = vpn_proxy::run_local_socks_proxy(control).await {
                set_snapshot(|state| {
                    state.last_error = format!("local account VPN SOCKS5 bridge stopped: {error}");
                });
            }
        });
    }

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
    swarm.behaviour_mut().kad.get_closest_peers(local_peer_id);
    let service_key = kad::RecordKey::new(&ADMIN_SERVICE_KEY);
    if !is_admin {
        swarm.behaviour_mut().kad.get_providers(service_key.clone());
    }
    let mut authority_advertised = false;

    let mut candidate_queue: VecDeque<(PeerId, Multiaddr)> = VecDeque::new();
    let mut candidate_addresses: HashMap<PeerId, Multiaddr> = HashMap::new();
    let mut attempting: HashSet<PeerId> = HashSet::new();
    let mut active_relays: HashSet<PeerId> = HashSet::new();
    let mut listener_peers: HashMap<ListenerId, PeerId> = HashMap::new();
    let mut failed_until: HashMap<PeerId, Instant> = HashMap::new();
    let mut admin_peers: Vec<PeerId> = Vec::new();
    let mut vpn_clients: HashSet<PeerId> = HashSet::new();
    let mut deferred_rpc: VecDeque<(AccountRpcRequest, std_mpsc::Sender<Result<AccountRpcResponse, String>>)> = VecDeque::new();
    let mut pending_rpc: HashMap<request_response::OutboundRequestId, std_mpsc::Sender<Result<AccountRpcResponse, String>>> = HashMap::new();

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
            command = commands.recv() => {
                match command {
                    Some(RpcCommand::Shutdown) | None => break,
                    Some(RpcCommand::Request { request, reply }) if !is_admin => {
                        if request.preferred_peer_id.is_empty() {
                            let _ = reply.send(Err("必须先固定管理员 Peer ID，保护账号凭据不被冒充节点窃取".to_string()));
                            continue;
                        }
                        let preferred = PeerId::from_str(&request.preferred_peer_id).ok()
                            .filter(|peer| admin_peers.contains(peer));
                        if let Some(peer) = preferred {
                            let request_id = swarm.behaviour_mut().account_rpc.send_request(&peer, request);
                            pending_rpc.insert(request_id, reply);
                        } else {
                            if let Ok(peer) = PeerId::from_str(&request.preferred_peer_id) {
                                swarm.behaviour_mut().kad.get_closest_peers(peer);
                            }
                            deferred_rpc.push_back((request, reply));
                            swarm.behaviour_mut().kad.get_providers(service_key.clone());
                        }
                    }
                    Some(RpcCommand::Request { reply, .. }) => {
                        let _ = reply.send(Err("管理员节点不接受本机发起的账号请求".to_string()));
                    }
                }
            }
            incoming_vpn = futures::StreamExt::next(&mut incoming_vpn_streams) => {
                if let Some((peer_id, stream)) = incoming_vpn {
                    if is_admin && vpn_clients.contains(&peer_id) {
                        if let Ok(permit) = vpn_stream_slots.clone().try_acquire_owned() {
                            tokio::spawn(async move {
                                let _permit = permit;
                                if let Err(error) = vpn_stream::serve_admin_stream(stream).await {
                                    set_snapshot(|state| {
                                        state.last_error = format!("account VPN stream ended: {error}");
                                    });
                                }
                            });
                        } else {
                            set_snapshot(|state| {
                                state.last_error = "account VPN stream limit reached".to_string();
                            });
                        }
                    }
                }
            }
            event = futures::StreamExt::next(&mut swarm) => {
                let Some(event) = event else { break };
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
                        if !is_admin && info.agent_version == ADMIN_AGENT_VERSION {
                            vpn_proxy::set_admin_peer(peer_id);
                        }
                        if is_admin && info.agent_version == CLIENT_AGENT_VERSION {
                            // Noise authenticates the peer key; this session marker
                            // only permits EffectCraft client peers to request egress.
                            vpn_clients.insert(peer_id);
                        }
                        for address in &info.listen_addrs {
                            swarm.behaviour_mut().kad.add_address(&peer_id, address.clone());
                        }

                        let peer_is_pinned = deferred_rpc.iter().any(|(request, _)| {
                            request.preferred_peer_id == peer_id.to_string()
                        });
                        if !is_admin
                            && (info.agent_version == ADMIN_AGENT_VERSION || peer_is_pinned)
                            && !admin_peers.contains(&peer_id)
                        {
                            admin_peers.push(peer_id);
                            dispatch_deferred_for_peer(&mut swarm, peer_id, &mut deferred_rpc, &mut pending_rpc);
                            set_snapshot(|state| state.status = "authenticated_admin_account_node_discovered".to_string());
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
                                if peer_id == local_peer_id { continue; }
                                // DHT provider records are discovery hints, not proof of
                                // administrator identity. Wait for the Noise-authenticated
                                // Identify handshake before sending credentials.
                                if !swarm.is_connected(&peer_id) {
                                    let _ = swarm.dial(libp2p::swarm::dial_opts::DialOpts::peer_id(peer_id).build());
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::AccountRpc(request_response::Event::Message { peer, message, .. })) => {
                        match message {
                            RpcMessage::Request { request, channel, .. } => {
                                let response = if is_admin {
                                    forward_to_local_account_service(&request)
                                } else {
                                    AccountRpcResponse { status: 403, body: r#"{\"detail\":\"该节点不是管理员账号服务器\"}"#.to_string() }
                                };
                                let _ = swarm.behaviour_mut().account_rpc.send_response(channel, response);
                                set_snapshot(|state| {
                                    state.status = if is_admin { "account_rpc_serving" } else { "account_rpc_rejected" }.to_string();
                                    state.last_error.clear();
                                });
                                let _ = peer;
                            }
                            RpcMessage::Response { request_id, response } => {
                                if let Some(reply) = pending_rpc.remove(&request_id) {
                                    let _ = reply.send(Ok(response));
                                }
                            }
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::AccountRpc(request_response::Event::OutboundFailure { request_id, error, .. })) => {
                        if let Some(reply) = pending_rpc.remove(&request_id) {
                            let _ = reply.send(Err(format!("账号节点请求失败：{error}")));
                        }
                    }
                    SwarmEvent::Behaviour(EffectCraftBehaviourEvent::AccountRpc(request_response::Event::InboundFailure { error, .. })) => {
                        set_snapshot(|state| state.last_error = format!("账号请求接收失败：{error}"));
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
                    SwarmEvent::ExternalAddrConfirmed { address } => {
                        if is_admin {
                            // Publish only after AutoNAT/Identify has confirmed a
                            // genuinely reachable public address.
                            if authority_advertised {
                                swarm.behaviour_mut().kad.stop_providing(&service_key);
                                authority_advertised = false;
                            }
                            match swarm.behaviour_mut().kad.start_providing(service_key.clone()) {
                                Ok(_) => {
                                    authority_advertised = true;
                                    set_snapshot(|state| {
                                        state.status = "admin_authority_advertised_direct".to_string();
                                        state.last_error = format!("已发布可直连的管理员地址：{address}");
                                    });
                                }
                                Err(error) => set_snapshot(|state| state.last_error = format!("账号权威节点发布失败：{error}")),
                            }
                        }
                    }
                    SwarmEvent::NewListenAddr { address, .. } => {
                        // A phone behind NAT must publish its accepted relay-circuit
                        // address, not its unusable 0.0.0.0 listener address. Refresh
                        // the DHT record so it includes the new relay circuit address.
                        if is_admin && address.iter().any(|protocol| matches!(protocol, Protocol::P2pCircuit)) {
                            if authority_advertised {
                                swarm.behaviour_mut().kad.stop_providing(&service_key);
                                authority_advertised = false;
                            }
                            match swarm.behaviour_mut().kad.start_providing(service_key.clone()) {
                                Ok(_) => {
                                    authority_advertised = true;
                                    set_snapshot(|state| {
                                        state.status = "admin_authority_advertised_via_relay".to_string();
                                        state.last_error.clear();
                                    });
                                }
                                Err(error) => set_snapshot(|state| state.last_error = format!("账号权威节点发布失败：{error}")),
                            }
                        }
                    }
                    SwarmEvent::ConnectionEstablished { peer_id, .. } => {
                        if admin_peers.contains(&peer_id) {
                            set_snapshot(|state| state.status = "admin_account_node_connected".to_string());
                        }
                    }
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
                swarm.behaviour_mut().kad.get_closest_peers(local_peer_id);
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
    clear_rpc_command_tx();
    set_snapshot(|state| {
        state.started = false;
        state.status = "stopped".to_string();
        state.active_relays = 0;
        state.direct_peers = 0;
        state.relay_candidates = 0;
    });
}



fn dispatch_deferred_for_peer(
    swarm: &mut Swarm<EffectCraftBehaviour>,
    peer_id: PeerId,
    deferred: &mut VecDeque<(AccountRpcRequest, std_mpsc::Sender<Result<AccountRpcResponse, String>>)>,
    pending: &mut HashMap<request_response::OutboundRequestId, std_mpsc::Sender<Result<AccountRpcResponse, String>>>,
) {
    let count = deferred.len();
    for _ in 0..count {
        let Some((request, reply)) = deferred.pop_front() else { break };
        let matches = !request.preferred_peer_id.is_empty()
            && PeerId::from_str(&request.preferred_peer_id).ok() == Some(peer_id);
        if matches {
            let request_id = swarm.behaviour_mut().account_rpc.send_request(&peer_id, request);
            pending.insert(request_id, reply);
        } else {
            deferred.push_back((request, reply));
        }
    }
}

fn ensure_client_rpc_sender() -> Result<UnboundedSender<RpcCommand>, String> {
    if let Some(sender) = current_rpc_command_tx() {
        return Ok(sender);
    }

    let directory = client_data_directory().lock()
        .map_err(|_| "客户端节点路径状态不可用".to_string())?
        .clone()
        .ok_or_else(|| "客户端 P2P 节点尚未初始化，请重新打开 EffectCraft".to_string())?;

    // Wait for a failed Swarm thread to finish its cleanup before creating a
    // replacement. This avoids overlapping two libp2p nodes with one identity.
    let shutdown_deadline = Instant::now() + Duration::from_secs(3);
    while Instant::now() < shutdown_deadline {
        if let Some(sender) = current_rpc_command_tx() {
            return Ok(sender);
        }
        let started = snapshot().lock().map(|state| state.started).unwrap_or(false);
        if !started { break; }
        thread::sleep(Duration::from_millis(40));
    }

    if current_rpc_command_tx().is_none() {
        let started = snapshot().lock().map(|state| state.started).unwrap_or(false);
        if !started {
            start_node(&directory, false)?;
        }
    }

    let ready_deadline = Instant::now() + Duration::from_secs(6);
    while Instant::now() < ready_deadline {
        if let Some(sender) = current_rpc_command_tx() {
            return Ok(sender);
        }
        let (started, status, last_error) = snapshot().lock()
            .map(|state| (state.started, state.status.clone(), state.last_error.clone()))
            .unwrap_or((false, "state_unavailable".to_string(), String::new()));
        if !started && matches!(status.as_str(), "transport_error" | "runtime_error" | "thread_error" | "rpc_proxy_error") {
            return Err(format!("P2P 节点自动恢复失败：{status}；{last_error}"));
        }
        thread::sleep(Duration::from_millis(60));
    }
    Err("P2P 网络节点恢复超时，请确认网络权限后重试".to_string())
}

fn send_account_rpc(
    sender: UnboundedSender<RpcCommand>,
    request: AccountRpcRequest,
) -> Result<AccountRpcResponse, ()> {
    let (reply_tx, reply_rx) = std_mpsc::channel();
    sender.send(RpcCommand::Request { request, reply: reply_tx }).map_err(|_| ())?;
    Ok(match reply_rx.recv_timeout(Duration::from_secs(38)) {
        Ok(Ok(response)) => response,
        Ok(Err(error)) => AccountRpcResponse { status: 503, body: serde_json::json!({"detail": error}).to_string() },
        Err(_) => AccountRpcResponse { status: 504, body: r#"{"detail":"等待管理员账号节点响应超时"}"#.to_string() },
    })
}

fn start_client_rpc_proxy() -> Result<(), String> {
    if CLIENT_RPC_PROXY_STARTED.load(Ordering::Acquire) {
        return Ok(());
    }
    let listener = TcpListener::bind(CLIENT_RPC_PROXY)
        .map_err(|error| format!("账号本机代理 8789 绑定失败：{error}"))?;
    if CLIENT_RPC_PROXY_STARTED.swap(true, Ordering::AcqRel) {
        drop(listener);
        return Ok(());
    }
    let spawn = thread::Builder::new()
        .name("effectcraft-account-rpc-proxy".to_string())
        .spawn(move || {
            for stream in listener.incoming() {
                match stream {
                    Ok(stream) => {
                        let _ = thread::Builder::new().name("effectcraft-account-rpc-call".to_string()).spawn(move || {
                            serve_client_rpc(stream);
                        });
                    }
                    Err(error) => {
                        set_snapshot(|state| state.last_error = format!("account RPC proxy accept: {error}"));
                        break;
                    }
                }
            }
            CLIENT_RPC_PROXY_STARTED.store(false, Ordering::Release);
        });
    if let Err(error) = spawn {
        CLIENT_RPC_PROXY_STARTED.store(false, Ordering::Release);
        return Err(format!("账号本机代理线程启动失败：{error}"));
    }
    Ok(())
}

fn serve_client_rpc(mut stream: TcpStream) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(8)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(40)));
    let clone = match stream.try_clone() {
        Ok(s) => s,
        Err(e) => { write_proxy_error(&mut stream, e.to_string()); return; }
    };
    let mut line = String::new();
    if BufReader::new(clone).read_line(&mut line).is_err() || line.len() > 1_200_000 {
        write_proxy_error(&mut stream, "请求数据读取失败或超过限制".to_string());
        return;
    }
    let request: AccountRpcRequest = match serde_json::from_str(&line) {
        Ok(request) => request,
        Err(error) => { write_proxy_error(&mut stream, format!("账号请求格式错误：{error}")); return; }
    };
    if !matches!(request.method.as_str(), "GET" | "POST" | "PUT" | "DELETE") || !request.path.starts_with("/v1/") {
        write_proxy_error(&mut stream, "账号请求接口不受支持".to_string());
        return;
    }
    let command_tx = match ensure_client_rpc_sender() {
        Ok(sender) => sender,
        Err(error) => {
            write_proxy_error(&mut stream, format!("P2P 网络节点尚未就绪：{error}"));
            return;
        }
    };
    let response = match send_account_rpc(command_tx, request.clone()) {
        Ok(response) => response,
        Err(_) => {
            // Remove the dead sender first. ensure_client_rpc_sender then waits
            // for run_node cleanup before rebuilding the Swarm with the same key.
            clear_rpc_command_tx();
            // The preferred administrator Peer ID remains in the original request,
            // so recovery cannot redirect credentials to another discovered peer.
            match ensure_client_rpc_sender() {
                Ok(recovered) => match send_account_rpc(recovered, request) {
                    Ok(response) => response,
                    Err(_) => {
                        let status = snapshot_json();
                        AccountRpcResponse {
                            status: 503,
                            body: serde_json::json!({"detail": format!("P2P 网络节点自动恢复后仍无法发送账号请求；当前状态：{status}")}).to_string(),
                        }
                    }
                },
                Err(error) => AccountRpcResponse {
                    status: 503,
                    body: serde_json::json!({"detail": error}).to_string(),
                },
            }
        }
    };
    if let Ok(serialized) = serde_json::to_string(&response) {
        let _ = writeln!(stream, "{serialized}");
        let _ = stream.flush();
    }
}

fn write_proxy_error(stream: &mut TcpStream, detail: String) {
    let response = AccountRpcResponse { status: 503, body: serde_json::json!({"detail": detail}).to_string() };
    if let Ok(serialized) = serde_json::to_string(&response) {
        let _ = writeln!(stream, "{serialized}");
        let _ = stream.flush();
    }
}

fn forward_to_local_account_service(request: &AccountRpcRequest) -> AccountRpcResponse {
    let mut stream = match TcpStream::connect_timeout(&ADMIN_ACCOUNT_BRIDGE, Duration::from_secs(5)) {
        Ok(stream) => stream,
        Err(error) => return AccountRpcResponse { status: 503, body: serde_json::json!({"detail": format!("管理员手机账号服务未启动：{error}")}).to_string() },
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(5)));
    let line = match serde_json::to_string(request) {
        Ok(line) => line,
        Err(error) => return AccountRpcResponse { status: 400, body: serde_json::json!({"detail": error.to_string()}).to_string() },
    };
    if writeln!(stream, "{line}").is_err() || stream.flush().is_err() {
        return AccountRpcResponse { status: 503, body: r#"{"detail":"无法转发到管理员账号服务"}"#.to_string() };
    }
    let mut response = String::new();
    if BufReader::new(stream).read_line(&mut response).is_err() {
        return AccountRpcResponse { status: 503, body: r#"{"detail":"管理员账号服务未返回响应"}"#.to_string() };
    }
    serde_json::from_str(&response).unwrap_or_else(|error| AccountRpcResponse {
        status: 502,
        body: serde_json::json!({"detail": format!("管理员账号服务响应格式错误：{error}")}).to_string(),
    })
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

    #[test]
    fn closed_client_command_channel_is_detected_for_retry() {
        let (sender, receiver) = mpsc::unbounded_channel::<RpcCommand>();
        drop(receiver);
        let request = AccountRpcRequest {
            method: "POST".to_string(),
            path: "/v1/register".to_string(),
            token: String::new(),
            body: r#"{\"qq\":\"123456789\"}"#.to_string(),
            preferred_peer_id: "12D3KooWTestPinnedAdminPeerId123456789".to_string(),
        };
        assert!(send_account_rpc(sender, request).is_err());
    }

    #[test]
    fn account_rpc_request_keeps_the_pinned_admin_identity() {
        let request = AccountRpcRequest {
            method: "POST".to_string(),
            path: "/v1/login".to_string(),
            token: String::new(),
            body: r#"{\"identifier\":\"123456789\",\"password\":\"not-logged\"}"#.to_string(),
            preferred_peer_id: "12D3KooWTestPinnedAdminPeerId123456789".to_string(),
        };
        let encoded = serde_json::to_string(&request).expect("request serializes");
        let decoded: AccountRpcRequest = serde_json::from_str(&encoded).expect("request deserializes");
        assert_eq!(decoded.preferred_peer_id, request.preferred_peer_id);
        assert_eq!(decoded.path, "/v1/login");
    }
}

#[no_mangle]
pub extern "system" fn Java_com_artcraft_effectcraft_NativeP2P_nativeClearVpnProxyConfig(
    _env: JNIEnv,
    _class: JClass,
) {
    vpn_proxy::clear_worker_config();
}
#[no_mangle]
pub extern "system" fn Java_com_artcraft_effectcraft_NativeP2P_nativeSetVpnControlToken(
    mut env: JNIEnv,
    _class: JClass,
    token: JString,
) {
    let token = match env.get_string(&token) {
        Ok(value) => value.to_string_lossy().into_owned(),
        Err(error) => {
            set_snapshot(|state| state.last_error = format!("VPN control token read failed: {error}"));
            return;
        }
    };
    if let Err(error) = vpn_proxy::set_vpn_control_token(&token) {
        set_snapshot(|state| state.last_error = error);
    }
}
